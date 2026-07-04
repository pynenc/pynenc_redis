"""
Redis-backed implementation of the trigger system.

This module provides a distributed trigger system implementation using Redis
for persistence and coordination across multiple application instances.
"""

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import cached_property
from typing import TYPE_CHECKING

import redis
from pynenc.identifiers.task_id import TaskId
from pynenc.models.trigger_definition_dto import TriggerDefinitionDTO
from pynenc.trigger.base_trigger import BaseTrigger
from pynenc.trigger.conditions import CompositeLogic, TriggerCondition, ValidCondition
from pynenc.trigger.monitoring import (
    EventMarker,
    EventMarkerPage,
    EventRecord,
    TriggerRunRecord,
)
from pynenc.trigger.types import ConditionId

from pynenc_redis.conf.config_trigger import ConfigTriggerRedis
from pynenc_redis.util.mongo_client import get_redis_client
from pynenc_redis.util.redis_keys import Key

if TYPE_CHECKING:
    from pynenc.app import Pynenc
    from pynenc.trigger.conditions import ConditionContext


def _trigger_definition_dto_from_json(data: dict) -> TriggerDefinitionDTO:
    """Reconstruct TriggerDefinitionDTO from JSON data."""
    return TriggerDefinitionDTO(
        trigger_id=data["trigger_id"],
        task_id=TaskId.from_key(data["task_id_key"]),
        condition_ids=data["condition_ids"],
        logic=CompositeLogic(data["logic_value"]),
        argument_provider_json=data.get("argument_provider_json"),
    )


class RedisTrigger(BaseTrigger):
    """
    Redis-backed implementation of the trigger system.

    This implementation uses Redis to store trigger conditions and definitions,
    making it suitable for distributed systems where multiple application instances
    need coordinated trigger behavior with persistence and reliability.
    """

    def __init__(self, app: "Pynenc") -> None:
        """
        Initialize the Redis-based trigger component.

        :param app: The Pynenc application instance
        """
        super().__init__(app)
        self._client: redis.Redis | None = None
        self.key = Key(app.app_id, "trigger")

    @cached_property
    def conf(self) -> ConfigTriggerRedis:
        """
        Get the Redis trigger configuration.

        :return: Configuration for Redis trigger
        """
        return ConfigTriggerRedis(
            config_values=self.app.config_values,
            config_filepath=self.app.config_filepath,
        )

    @property
    def client(self) -> redis.Redis:
        """
        Lazy initialization of Redis client.

        :return: Redis client instance
        """
        if self._client is None:
            self.app.logger.debug("Lazy initializing Redis client for trigger system")
            self._client = get_redis_client(self.conf)
        return self._client

    def _register_condition(self, condition: TriggerCondition) -> None:
        """
        Register a condition in Redis.

        :param condition: The condition to register
        """
        condition_id = condition.condition_id
        self.client.set(
            self.key.condition(condition_id),
            condition.to_json(self.app),
        )

    def get_condition(self, condition_id: str) -> TriggerCondition | None:
        """
        Get a condition by its ID from Redis.

        :param condition_id: ID of the condition to retrieve
        :return: The condition if found, None otherwise
        """
        condition_data = self.client.get(self.key.condition(condition_id))
        if condition_data:
            return TriggerCondition.from_json(condition_data.decode(), self.app)
        return None

    def register_trigger(self, trigger: "TriggerDefinitionDTO") -> None:
        """
        Register a trigger definition in Redis.

        :param trigger: The trigger definition to register
        """
        trigger_data = {
            "trigger_id": trigger.trigger_id,
            "task_id_key": trigger.task_id.key,
            "condition_ids": trigger.condition_ids,
            "logic_value": trigger.logic.value,
            "argument_provider_json": trigger.argument_provider_json,
        }
        self.client.set(
            self.key.trigger(trigger.trigger_id),
            json.dumps(trigger_data),
        )

        # Map each condition to this trigger
        for condition_id in trigger.condition_ids:
            self.client.sadd(
                self.key.condition_triggers(condition_id),
                trigger.trigger_id,
            )

        # Register with task for easy lookup
        self.client.sadd(
            self.key.task_triggers(trigger.task_id.key),
            trigger.trigger_id,
        )

    def _get_trigger(self, trigger_id: str) -> "TriggerDefinitionDTO | None":
        """
        Get a trigger definition by ID from Redis.

        :param trigger_id: ID of the trigger to retrieve
        :return: The trigger definition if found, None otherwise
        """
        trigger_data = self.client.get(self.key.trigger(trigger_id))
        if trigger_data:
            data = json.loads(trigger_data.decode())
            return _trigger_definition_dto_from_json(data)
        return None

    def get_triggers_for_condition(
        self, condition_id: str
    ) -> list["TriggerDefinitionDTO"]:
        """
        Get all triggers that depend on a specific condition from Redis.

        :param condition_id: ID of the condition
        :return: List of trigger definitions using this condition
        """
        trigger_ids = self.client.smembers(self.key.condition_triggers(condition_id))
        triggers = []

        for trigger_id in trigger_ids:
            trigger = self._get_trigger(trigger_id.decode())
            if trigger:
                triggers.append(trigger)

        return triggers

    def get_triggers_for_task(self, task_id: "TaskId") -> list["TriggerDefinitionDTO"]:
        """
        Get all triggers associated with a specific task from Redis.

        :param task_id: ID of the task to find triggers for
        :return: List of trigger definitions for this task
        """
        trigger_ids = self.client.smembers(self.key.task_triggers(task_id.key))
        triggers = []
        for trigger_id in trigger_ids:
            trigger = self._get_trigger(trigger_id.decode())
            if trigger:
                triggers.append(trigger)

        return triggers

    def record_valid_condition(self, valid_condition: ValidCondition) -> None:
        """
        Record that a condition has been satisfied with a specific context in Redis.

        :param valid_condition: The valid condition to record
        """
        self.client.set(
            self.key.valid_condition(valid_condition.valid_condition_id),
            valid_condition.to_json(self.app),
        )

    def record_valid_conditions(self, valid_conditions: list[ValidCondition]) -> None:
        """
        Record that multiple conditions have been satisfied with their respective contexts in Redis.

        :param valid_conditions: The list of valid conditions to record
        """
        if not valid_conditions:
            return

        pipeline = self.client.pipeline()
        for condition in valid_conditions:
            pipeline.set(
                self.key.valid_condition(condition.valid_condition_id),
                condition.to_json(self.app),
            )
        pipeline.execute()

    def get_valid_conditions(self) -> dict[str, ValidCondition]:
        """
        Get all currently valid conditions and their contexts from Redis.

        :return: Dictionary mapping condition IDs to their valid conditions
        """
        valid_conditions: dict[str, ValidCondition] = {}

        # Get all valid condition keys
        keys_pattern = self.key.valid_condition("*")
        all_keys = self.client.keys(keys_pattern)

        if not all_keys:
            return valid_conditions

        # Get all valid conditions in a single operation
        pipeline = self.client.pipeline()
        for key in all_keys:
            pipeline.get(key)
        for data in pipeline.execute():
            if data:
                vc = ValidCondition.from_json(data.decode(), self.app)
                valid_conditions[vc.valid_condition_id] = vc
        return valid_conditions

    def clear_valid_conditions(self, conditions: Iterable["ValidCondition"]) -> None:
        """
        Clear valid conditions after they have been processed from Redis.

        :param conditions: List of valid conditions to clear
        """
        if not conditions:
            return

        pipeline = self.client.pipeline()
        for condition in conditions:
            pipeline.delete(self.key.valid_condition(condition.valid_condition_id))
        pipeline.execute()

    def _get_all_conditions(self) -> list[TriggerCondition]:
        """
        Get all registered conditions from Redis.

        :return: List of all conditions
        """
        conditions: list[TriggerCondition] = []

        # Get all condition keys
        keys_pattern = self.key.condition("*")
        all_keys = self.client.keys(keys_pattern)

        if not all_keys:
            return conditions

        # Get all conditions in a single operation
        pipeline = self.client.pipeline()
        for key in all_keys:
            pipeline.get(key)
        results = pipeline.execute()

        # Process the results
        for data in results:
            if data:
                condition = TriggerCondition.from_json(data.decode(), self.app)
                conditions.append(condition)

        return conditions

    def _purge(self) -> None:
        """
        Purge all trigger-related data from Redis.

        Removes all conditions, triggers, and valid conditions for this application.
        """
        self.key.purge(self.client)

    def get_last_cron_execution(self, condition_id: ConditionId) -> datetime | None:
        """
        Get the timestamp of the last execution of a cron condition from Redis.

        :param condition_id: ID of the cron condition
        :return: Timestamp of last execution, or None if never executed
        """
        timestamp_str = self.client.get(self.key.cron_last_execution(condition_id))
        if not timestamp_str:
            return None

        try:
            # Parse the ISO format datetime string
            return datetime.fromisoformat(timestamp_str.decode())
        except (ValueError, AttributeError) as e:
            self.app.logger.error(f"Failed to parse timestamp {timestamp_str}: {e}")
            return None

    def store_last_cron_execution(
        self,
        condition_id: str,
        execution_time: datetime,
        expected_last_execution: datetime | None = None,
    ) -> bool:
        """
        Store the last execution time for a cron condition with optimistic locking.

        Uses Redis atomic operations to ensure thread safety:
        1. For new records (no expected_last_execution): Uses SETNX for atomic create-if-not-exists
        2. For updating existing records: Uses optimistic locking with WATCH/MULTI/EXEC pattern

        :param condition_id: ID of the cron condition
        :param execution_time: Time of execution to store
        :param expected_last_execution: Expected current value (for optimistic locking)
        :return: True if update successful, False if another process updated first
        """
        key = self.key.cron_last_execution(condition_id)
        new_value = execution_time.isoformat()
        expected_value = (
            expected_last_execution.isoformat() if expected_last_execution else None
        )

        if expected_last_execution is None:
            # Case 1: No expected value - use SETNX for atomic create-if-not-exists
            return bool(self.client.setnx(key, new_value))
        else:
            # Case 2: Expected value provided - use optimistic locking
            # Start a transaction with WATCH
            pipe = self.client.pipeline()
            pipe.watch(key)
            current_value: str | bytes | None = pipe.get(key)  # type: ignore
            if current_value and isinstance(current_value, bytes):
                current_value = current_value.decode("utf-8")
            if current_value != expected_value:
                pipe.unwatch()
                return False
            # Value matches expected, proceed with update
            pipe.multi()
            pipe.set(key, new_value)
            # Execute returns None if transaction failed due to key modification
            results = pipe.execute()
            return bool(results and results[0])

    def _register_source_task_condition(
        self, task_id: "TaskId", condition_id: str
    ) -> None:
        """
        Register the conditions that are sourced from a task in Redis.

        This method stores a mapping from source task IDs to the condition IDs
        that monitor them, enabling efficient lookup when task status changes.

        :param task_id: ID of the source task
        :param condition_id: ID of the condition sourced from the task
        """
        self.client.sadd(
            self.key.source_task_conditions(task_id.key),
            condition_id,
        )

    def get_conditions_sourced_from_task(
        self, task_id: "TaskId", context_type: type["ConditionContext"] | None = None
    ) -> list["TriggerCondition"]:
        """
        Get all conditions that are sourced from a specific task.

        These are conditions that monitor the task and might be satisfied by its status or results.

        :param task_id: ID of the source task
        :param context_type: Optional context type to filter conditions by
        :return: List of conditions monitoring this task
        """
        condition_ids = self.client.smembers(
            self.key.source_task_conditions(task_id.key)
        )
        conditions = []

        for condition_id in condition_ids:
            condition = self.get_condition(condition_id.decode())
            if condition:
                if context_type is None or condition.context_type == context_type:
                    conditions.append(condition)
        return conditions

    def claim_trigger_execution(
        self, trigger_id: str, valid_condition_id: str, expiration_seconds: int = 60
    ) -> bool:
        """
        Atomically claim the right to execute a trigger for a specific valid condition.

        Uses Redis's SETNX (SET if Not eXists) for atomic claim operations across multiple workers.
        The claim automatically expires after the specified seconds to prevent stale locks.

        :param trigger_id: ID of the trigger being executed
        :param valid_condition_id: ID of the valid condition being processed
        :param expiration_seconds: Number of seconds after which the claim expires
        :return: True if the claim was successful, False if another worker has claimed it
        """
        claim_key = self.key.trigger_execution_claim(trigger_id, valid_condition_id)

        # Try to set the key only if it doesn't exist (SETNX) with an expiration
        # Returns 1 if the key was set (claim successful), 0 otherwise
        result = self.client.set(
            claim_key,
            datetime.now(UTC).isoformat(),
            nx=True,  # Only set if key doesn't exist (SETNX)
            ex=expiration_seconds,  # Set expiration time
        )

        return bool(result)

    def claim_trigger_run(
        self, trigger_run_id: str, expiration_seconds: int = 60
    ) -> bool:
        """
        Atomically claim the right to execute a trigger run.

        Uses Redis's SETNX (SET if Not eXists) for atomic claim operations across multiple workers.
        The claim automatically expires after the specified seconds to prevent stale locks.

        :param trigger_run_id: Unique ID for this trigger run
        :param expiration_seconds: Number of seconds after which the claim expires
        :return: True if the claim was successful, False if another worker has claimed it
        """
        claim_key = self.key.trigger_run_claim(trigger_run_id)

        # Try to set the key only if it doesn't exist (SETNX) with an expiration
        # Returns True if the key was set (claim successful), False otherwise
        result = self.client.set(
            claim_key,
            datetime.now(UTC).isoformat(),
            nx=True,  # Only set if key doesn't exist (SETNX)
            ex=expiration_seconds,  # Set expiration time
        )

        return bool(result)

    def clean_task_trigger_definitions(self, task_id: "TaskId") -> None:
        """
        Remove all trigger definitions for a specific task from Redis.

        This method removes all trigger definitions associated with the given task
        and their references in the index keys. It's safe to use in a distributed
        environment as it uses Redis atomic operations.

        :param task_id: ID of the task to clean triggers for
        """
        # Get all trigger IDs for this task
        task_trigger_key = self.key.task_triggers(task_id.key)
        trigger_ids = self.client.smembers(task_trigger_key)

        if not trigger_ids:
            return

        pipeline = self.client.pipeline()

        for trigger_id in trigger_ids:
            trigger_data = self.client.get(self.key.trigger(trigger_id.decode()))
            if trigger_data:
                data = json.loads(trigger_data.decode())
                trigger = _trigger_definition_dto_from_json(data)
                for condition_id in trigger.condition_ids:
                    pipeline.srem(
                        self.key.condition_triggers(condition_id), trigger_id.decode()
                    )
                pipeline.delete(self.key.trigger(trigger_id.decode()))
        pipeline.delete(task_trigger_key)
        pipeline.execute()

    # ── Monitoring API (events + trigger runs) ─────────────────────────
    @staticmethod
    def _ts_score(timestamp: datetime) -> float:
        """Convert a datetime to an epoch-millisecond score for sorted sets."""
        return timestamp.timestamp() * 1000.0

    def _event_keys_for(self, event: EventRecord) -> list[str]:
        """Return the auxiliary index keys associated with one event."""
        return [
            self.key.events_by_time(),
            self.key.events_by_code(event.event_code),
            self.key.events_matched(),
            self.key.events_triggered(),
        ]

    def store_event(self, event: EventRecord) -> None:
        """Persist or replace one ``EventRecord`` and its indexes."""
        score = self._ts_score(event.timestamp)
        payload = event.to_json(self.app)
        pipe = self.client.pipeline()
        pipe.set(self.key.event_hash(event.event_id), payload)
        pipe.zadd(self.key.events_by_time(), {event.event_id: score})
        pipe.zadd(self.key.events_by_code(event.event_code), {event.event_id: score})
        pipe.sadd(self.key.events_codes(), event.event_code)
        if event.matched:
            pipe.zadd(self.key.events_matched(), {event.event_id: score})
        else:
            pipe.zrem(self.key.events_matched(), event.event_id)
        if event.triggered:
            pipe.zadd(self.key.events_triggered(), {event.event_id: score})
        else:
            pipe.zrem(self.key.events_triggered(), event.event_id)
        pipe.execute()
        if event.triggered_invocation_ids:
            self._seed_event_triggered_invocations(
                event.event_id, event.triggered_invocation_ids, score
            )

    def _seed_event_triggered_invocations(
        self, event_id: str, invocation_ids: Iterable[str], score: float
    ) -> None:
        """Seed legacy event->invocation links from an ``EventRecord`` payload."""
        key = self.key.event_triggered_invocations(event_id)
        existing = {item.decode() for item in self.client.lrange(key, 0, -1)}
        new_ids = [inv for inv in invocation_ids if inv not in existing]
        if not new_ids:
            return
        pipe = self.client.pipeline()
        pipe.rpush(key, *new_ids)
        pipe.zadd(self.key.events_triggered(), {event_id: score})
        pipe.execute()

    def get_event(self, event_id: str) -> "EventRecord | None":
        """Return one stored event or ``None`` if it does not exist."""
        raw = self.client.get(self.key.event_hash(event_id))
        if not raw:
            return None
        return self._hydrate_event(EventRecord.from_json(raw.decode(), self.app))

    def get_events(
        self,
        *,
        event_code: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        matched: bool | None = None,
        triggered: bool | None = None,
        emitted_by_invocation_id: str | None = None,
        emitted_by_task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EventRecord]:
        """Return events ordered by ``timestamp`` descending after filtering."""
        candidates = self._select_event_ids(event_code, start_time, end_time)
        records = self._load_events(candidates)
        results: list[EventRecord] = []
        skipped = 0
        for record in records:
            if matched is not None and record.matched != matched:
                continue
            if triggered is not None and record.triggered != triggered:
                continue
            if (
                emitted_by_invocation_id is not None
                and record.emitted_by_invocation_id != emitted_by_invocation_id
            ):
                continue
            if (
                emitted_by_task_id is not None
                and record.emitted_by_task_id != emitted_by_task_id
            ):
                continue
            if skipped < offset:
                skipped += 1
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results

    def count_events(
        self,
        *,
        event_code: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        matched: bool | None = None,
        triggered: bool | None = None,
        emitted_by_invocation_id: str | None = None,
        emitted_by_task_id: str | None = None,
    ) -> int:
        """Count events matching the same filters as ``get_events``."""
        candidates = self._select_event_ids(event_code, start_time, end_time)
        return sum(
            1
            for record in self._load_events(candidates)
            if (matched is None or record.matched == matched)
            and (triggered is None or record.triggered == triggered)
            and (
                emitted_by_invocation_id is None
                or record.emitted_by_invocation_id == emitted_by_invocation_id
            )
            and (
                emitted_by_task_id is None
                or record.emitted_by_task_id == emitted_by_task_id
            )
        )

    def _load_events(self, event_ids: list[str]) -> list[EventRecord]:
        """Batch-load events via ``MGET`` preserving the input order."""
        if not event_ids:
            return []
        keys = [self.key.event_hash(eid) for eid in event_ids]
        raws = self.client.mget(keys)
        out: list[EventRecord] = []
        for raw in raws:
            if raw is None:
                continue
            out.append(
                self._hydrate_event(EventRecord.from_json(raw.decode(), self.app))
            )
        return out

    def _hydrate_event(self, record: EventRecord) -> EventRecord:
        """Attach backend-indexed trigger relations to an event record."""
        record.triggered_invocation_ids = self.get_invocations_triggered_by_event(
            record.event_id
        )
        return record

    def _select_event_ids(
        self,
        event_code: str | None,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> list[str]:
        """Run the indexed ``ZRANGEBYSCORE`` query and return event ids desc."""
        index_key = (
            self.key.events_by_code(event_code)
            if event_code is not None
            else self.key.events_by_time()
        )
        min_score: float | str = self._ts_score(start_time) if start_time else "-inf"
        max_score: float | str = self._ts_score(end_time) if end_time else "+inf"
        raw = self.client.zrevrangebyscore(index_key, max_score, min_score)
        return [item.decode() for item in raw]

    def list_event_codes(self) -> list[str]:
        """Return the sorted list of distinct event codes ever stored."""
        raw = self.client.smembers(self.key.events_codes())
        return sorted(item.decode() for item in raw)

    def get_event_markers_in_timerange(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        event_code: str | None = None,
        state: str = "all",
        limit: int = 1000,
        offset: int = 0,
    ) -> EventMarkerPage:
        candidates = self._select_event_ids(event_code, start_time, end_time)
        filtered = [
            record
            for record in self._load_events(candidates)
            if self._marker_matches(record, state)
        ]
        total = len(filtered)
        page = list(reversed(filtered[offset : offset + limit]))
        return EventMarkerPage(
            markers=[
                EventMarker(
                    event_id=record.event_id,
                    event_code=record.event_code,
                    timestamp=record.timestamp,
                    matched=record.matched,
                    triggered=record.triggered,
                    emitted_by_invocation_id=record.emitted_by_invocation_id,
                    emitted_by_runner_context_id=(record.emitted_by_runner_context_id),
                )
                for record in page
            ],
            total=total,
            truncated=offset + len(page) < total,
        )

    @staticmethod
    def _marker_matches(record: EventRecord, state: str) -> bool:
        if state == "matched":
            return record.matched
        if state == "unmatched":
            return not record.matched
        if state == "triggered":
            return record.triggered
        if state == "untriggered":
            return not record.triggered
        return True

    def link_trigger_run_to_events(
        self,
        event_ids: list[str],
        invocation_id: str,
        *,
        trigger_run_id: str,
    ) -> None:
        if not event_ids:
            return
        pipe = self.client.pipeline()
        for event_id in event_ids:
            key = self.key.event_triggered_invocations(event_id)
            existing = {item.decode() for item in self.client.lrange(key, 0, -1)}
            if invocation_id not in existing:
                pipe.rpush(key, invocation_id)
            event = self.get_event(event_id)
            if event is not None:
                pipe.zadd(
                    self.key.events_triggered(),
                    {event_id: self._ts_score(event.timestamp)},
                )
            if trigger_run_id:
                pipe.sadd(self.key.trigger_runs_for_event(event_id), trigger_run_id)
        pipe.execute()

    def get_invocations_triggered_by_event(self, event_id: str) -> list[str]:
        raw = self.client.lrange(self.key.event_triggered_invocations(event_id), 0, -1)
        return [item.decode() for item in raw]

    def store_trigger_run(self, run: TriggerRunRecord) -> None:
        """Persist or replace one ``TriggerRunRecord`` and its indexes."""
        sort_time = run.executed_at or run.claimed_at or datetime.now(UTC)
        score = self._ts_score(sort_time)
        pipe = self.client.pipeline()
        pipe.set(self.key.trigger_run_hash(run.trigger_run_id), run.to_json())
        pipe.zadd(self.key.trigger_runs_by_time(), {run.trigger_run_id: score})
        for event_id in run.event_ids:
            pipe.sadd(self.key.trigger_runs_for_event(event_id), run.trigger_run_id)
        for source_id in run.source_invocation_ids:
            pipe.sadd(
                self.key.trigger_runs_sourced_by_invocation(source_id),
                run.trigger_run_id,
            )
        if run.triggered_invocation_id:
            pipe.sadd(
                self.key.trigger_runs_for_invocation(run.triggered_invocation_id),
                run.trigger_run_id,
            )
        for valid_condition_id in self._valid_condition_ids_for_run(run):
            pipe.sadd(
                self.key.trigger_runs_for_valid_condition(valid_condition_id),
                run.trigger_run_id,
            )
        pipe.execute()

    def get_trigger_run(self, trigger_run_id: str) -> "TriggerRunRecord | None":
        """Return the stored ``TriggerRunRecord`` or ``None``."""
        raw = self.client.get(self.key.trigger_run_hash(trigger_run_id))
        if not raw:
            return None
        return TriggerRunRecord.from_json(raw.decode())

    def get_trigger_runs_for_event(self, event_id: str) -> list[TriggerRunRecord]:
        """Return all trigger runs that reference ``event_id``."""
        ids = self.client.smembers(self.key.trigger_runs_for_event(event_id))
        return self._load_runs(ids)

    def get_trigger_runs_for_invocation(
        self, invocation_id: str
    ) -> list[TriggerRunRecord]:
        """Return all trigger runs linked to ``invocation_id``."""
        ids = self.client.smembers(self.key.trigger_runs_for_invocation(invocation_id))
        return self._load_runs(ids)

    def get_trigger_runs_sourced_by_invocation(
        self, invocation_id: str
    ) -> list[TriggerRunRecord]:
        """Return trigger runs whose source participant is ``invocation_id``."""
        ids = self.client.smembers(
            self.key.trigger_runs_sourced_by_invocation(invocation_id)
        )
        return self._load_runs(ids)

    def get_trigger_runs_for_valid_condition(
        self, valid_condition_id: str
    ) -> list[TriggerRunRecord]:
        """Return trigger runs that include ``valid_condition_id``."""
        ids = self.client.smembers(
            self.key.trigger_runs_for_valid_condition(valid_condition_id)
        )
        runs = self._load_runs(ids)
        if runs:
            return runs
        return super().get_trigger_runs_for_valid_condition(valid_condition_id)

    def get_trigger_runs_in_timerange(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        event_code: str | None = None,
        task_id_key: str | None = None,
        limit: int | None = None,
    ) -> list[TriggerRunRecord]:
        """Return trigger runs executed between ``start_time`` and ``end_time``."""
        raw = self.client.zrevrangebyscore(
            self.key.trigger_runs_by_time(),
            self._ts_score(end_time),
            self._ts_score(start_time),
        )
        results: list[TriggerRunRecord] = []
        for item in raw:
            run = self.get_trigger_run(item.decode())
            if run is None:
                continue
            if task_id_key is not None and run.task_id_key != task_id_key:
                continue
            if event_code is not None and not self._run_matches_event_code(
                run, event_code
            ):
                continue
            results.append(run)
            if limit is not None and len(results) >= limit:
                break
        return results

    def _run_matches_event_code(self, run: TriggerRunRecord, event_code: str) -> bool:
        """Return ``True`` if any of ``run.event_ids`` has the given code."""
        for event_id in run.event_ids:
            event = self.get_event(event_id)
            if event is not None and event.event_code == event_code:
                return True
        return False

    def _load_runs(self, raw_ids: Iterable[object]) -> list[TriggerRunRecord]:
        """Resolve a collection of raw bytes ids into ``TriggerRunRecord``."""
        runs: list[TriggerRunRecord] = []
        for item in raw_ids:
            run_id = _decode_redis_value(item)
            run = self.get_trigger_run(run_id)
            if run is not None:
                runs.append(run)
        return runs

    @staticmethod
    def _valid_condition_ids_for_run(run: TriggerRunRecord) -> set[str]:
        ids = set(run.valid_condition_ids)
        for participant in run.participants or []:
            if participant.valid_condition_id:
                ids.add(participant.valid_condition_id)
        return ids

    # ── Auto-purge (events + trigger runs) ─────────────────────────────
    # The driving algorithm lives in BaseTrigger._auto_purge_events; this
    # class supplies the Redis primitives.

    def _age_purge_events(self, threshold: datetime) -> list[str]:
        """Delete events older than ``threshold`` from event indexes."""
        cutoff = self._ts_score(threshold)
        ids = self.client.zrangebyscore(self.key.events_by_time(), "-inf", f"({cutoff}")
        event_ids = [item.decode() for item in ids]
        self._delete_event_rows(event_ids)
        return event_ids

    def _cap_purge_events(self) -> list[str]:
        """Drop oldest events until the total count fits ``event_max_records``."""
        max_records = self.conf.event_max_records
        if max_records <= 0:
            return []
        total = self.client.zcard(self.key.events_by_time())
        excess = total - max_records
        if excess <= 0:
            return []
        ids = self.client.zrange(self.key.events_by_time(), 0, excess - 1)
        event_ids = [item.decode() for item in ids]
        self._delete_event_rows(event_ids)
        return event_ids

    def _cascade_delete_runs_for_events(self, event_ids: list[str]) -> int:
        """Delete trigger runs referencing any of ``event_ids``."""
        run_ids = self._collect_run_ids_for_events(event_ids)
        if not run_ids:
            return 0
        return self._delete_trigger_runs(run_ids)

    def _delete_event_rows(self, event_ids: list[str]) -> None:
        """Remove events from indexes/hash storage. Does not cascade runs."""
        if not event_ids:
            return
        records = self._load_events(event_ids)
        codes_touched = {r.event_code for r in records}
        pipe = self.client.pipeline()
        for event_id in event_ids:
            pipe.delete(self.key.event_hash(event_id))
            pipe.zrem(self.key.events_by_time(), event_id)
            pipe.zrem(self.key.events_matched(), event_id)
            pipe.zrem(self.key.events_triggered(), event_id)
            pipe.delete(self.key.event_triggered_invocations(event_id))
        for code in codes_touched:
            pipe.zrem(self.key.events_by_code(code), *event_ids)
        pipe.execute()
        if codes_touched:
            self._prune_empty_event_codes(codes_touched)

    def _collect_run_ids_for_events(self, event_ids: list[str]) -> list[str]:
        """Return the trigger-run ids referencing any of ``event_ids``."""
        pipe = self.client.pipeline()
        for event_id in event_ids:
            pipe.smembers(self.key.trigger_runs_for_event(event_id))
        seen: set[str] = set()
        for raw_set in pipe.execute():
            for item in raw_set or []:
                seen.add(item.decode() if isinstance(item, bytes) else item)
        return list(seen)

    def _prune_empty_event_codes(self, codes: Iterable[str]) -> None:
        """Remove codes from ``events_codes`` whose per-code index is empty."""
        pipe = self.client.pipeline()
        codes_list = list(codes)
        for code in codes_list:
            pipe.zcard(self.key.events_by_code(code))
        sizes = pipe.execute()
        empty = [code for code, size in zip(codes_list, sizes, strict=True) if not size]
        if empty:
            self.client.srem(self.key.events_codes(), *empty)

    def _age_purge_trigger_runs(self, threshold: datetime) -> int:
        """Delete trigger runs older than ``threshold``."""
        cutoff = self._ts_score(threshold)
        ids = self.client.zrangebyscore(
            self.key.trigger_runs_by_time(), "-inf", f"({cutoff}"
        )
        return self._delete_trigger_runs([item.decode() for item in ids])

    def _cap_purge_trigger_runs(self) -> int:
        """Drop oldest trigger runs until the count fits ``trigger_run_max_records``."""
        max_records = self.conf.trigger_run_max_records
        if max_records <= 0:
            return 0
        total = self.client.zcard(self.key.trigger_runs_by_time())
        excess = total - max_records
        if excess <= 0:
            return 0
        ids = self.client.zrange(self.key.trigger_runs_by_time(), 0, excess - 1)
        return self._delete_trigger_runs([item.decode() for item in ids])

    def _delete_trigger_runs(self, run_ids: list[str]) -> int:
        """Remove the given trigger run ids from all indexes and the hash store."""
        if not run_ids:
            return 0
        pipe = self.client.pipeline()
        for run_id in run_ids:
            run = self.get_trigger_run(run_id)
            pipe.delete(self.key.trigger_run_hash(run_id))
            pipe.zrem(self.key.trigger_runs_by_time(), run_id)
            if run is None:
                continue
            for event_id in run.event_ids:
                pipe.srem(self.key.trigger_runs_for_event(event_id), run_id)
            for source_id in run.source_invocation_ids:
                pipe.srem(
                    self.key.trigger_runs_sourced_by_invocation(source_id), run_id
                )
            if run.triggered_invocation_id:
                pipe.srem(
                    self.key.trigger_runs_for_invocation(run.triggered_invocation_id),
                    run_id,
                )
            for valid_condition_id in self._valid_condition_ids_for_run(run):
                pipe.srem(
                    self.key.trigger_runs_for_valid_condition(valid_condition_id),
                    run_id,
                )
        pipe.execute()
        return len(run_ids)


def _decode_redis_value(value: object) -> str:
    """Decode Redis bytes-like values into text keys."""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, bytearray):
        return bytes(value).decode()
    if isinstance(value, memoryview):
        return value.tobytes().decode()
    return str(value)
