from typing import TYPE_CHECKING

import redis

if TYPE_CHECKING:
    from pynenc.invocation.status import InvocationStatus

PYNENC_KEY_PREFIX = "__pynenc__"


def sanitize_for_redis(s: str) -> str:
    """
    Sanitizes a string for use as a Redis key.

    :param str s: The string to sanitize.
    :return: The sanitized string.
    """
    if s is None:
        return ""
    replacements = {
        "[": "__OPEN_BRACKET__",
        "]": "__CLOSE_BRACKET__",
        "*": "__ASTERISK__",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    return s


class Key:
    """
    Helper class to manage Redis key formats for various components.

    :param str app_id: The application ID.
    :param str prefix: The prefix for the keys.
    """

    def __init__(self, app_id: str, prefix: str) -> None:
        prefix = sanitize_for_redis(prefix)
        if not prefix:
            raise ValueError("Prefix cannot be an empty string or None")
        app_id = sanitize_for_redis(app_id)
        if not app_id:
            raise ValueError("App ID cannot be an empty string or None")
        if ":" in app_id:
            raise ValueError("App ID cannot contain ':'")
        if prefix and not prefix.endswith(":"):
            prefix += ":"
        self._class_prefix = prefix
        self._app_id = app_id
        self._prefix = f"{PYNENC_KEY_PREFIX}:{app_id}:{prefix}"

    @property
    def prefix(self) -> str:
        """Read-only property for the Redis key prefix."""
        return self._prefix

    def invocation(self, invocation_id: str) -> str:
        return f"{self.prefix}invocation:{invocation_id}"

    def task(self, task_id: str) -> str:
        return f"{self.prefix}task:{task_id}"

    def args(self, task_id: str, arg: str, val: str) -> str:
        return f"{self.prefix}task:{task_id}:arg:{arg}:val:{val}"

    def status_to_invocations(self, status: "InvocationStatus") -> str:
        """Get the Redis key for the set of invocation IDs with a specific status."""
        return f"{self.prefix}status:{status}"

    def invocation_to_status(self, invocation_id: str) -> str:
        return f"{self.prefix}invocation_status:{invocation_id}"

    def pending_timer(self, invocation_id: str) -> str:
        return f"{self.prefix}pending_timer:{invocation_id}"

    def previous_status(self, invocation_id: str) -> str:
        return f"{self.prefix}invocation_previous_status:{invocation_id}"

    def invocation_retries(self, invocation_id: str) -> str:
        return f"{self.prefix}invocation_retries:{invocation_id}"

    def call(self, call_id: str) -> str:
        return f"{self.prefix}call:{call_id}"

    def call_to_invocation(self, call_id: str) -> str:
        return f"{self.prefix}call_to_invocation:{call_id}"

    def invocation_to_call(self, invocation_id: str) -> str:
        """Get the Redis key for mapping an invocation_id to its call_id."""
        return f"{self.prefix}invocation_to_call:{invocation_id}"

    def edge(self, call_id: str) -> str:
        return f"{self.prefix}edge:{call_id}"

    def reverse_edge(self, callee_call_id: str) -> str:
        return f"{self.prefix}reverse_edge:{callee_call_id}"

    def waiting_for(self, invocation_id: str) -> str:
        return f"{self.prefix}waiting_for:{invocation_id}"

    def waited_by(self, invocation_id: str) -> str:
        return f"{self.prefix}waited_by:{invocation_id}"

    def all_waited(self) -> str:
        return f"{self.prefix}all_waited"

    def not_waiting(self) -> str:
        return f"{self.prefix}not_waiting"

    def runner_heartbeat(self, runner_id: str) -> str:
        return f"{self.prefix}runner_heartbeat:{runner_id}"

    def runner_heartbeats(self) -> str:
        return f"{self.prefix}runner_heartbeats"

    def atomic_service_executions(self) -> str:
        """Sorted set of atomic-service execution ids ordered by start time."""
        return f"{self.prefix}atomic_service_executions"

    def atomic_service_active_execution(self) -> str:
        """Current atomic-service execution id while a run is active."""
        return f"{self.prefix}atomic_service_active_execution"

    def atomic_service_execution(self, execution_id: str) -> str:
        """JSON storage for one atomic-service execution record."""
        return f"{self.prefix}atomic_service_execution:{execution_id}"

    def history(self, invocation_id: str) -> str:
        return f"{self.prefix}history:{invocation_id}"

    def history_by_timestamp(self) -> str:
        """Get key for sorted set of all history entries indexed by timestamp."""
        return f"{self.prefix}history_by_timestamp"

    def result(self, invocation_id: str) -> str:
        return f"{self.prefix}result:{invocation_id}"

    def exception(self, invocation_id: str) -> str:
        return f"{self.prefix}exception:{invocation_id}"

    def invocation_auto_purge(self) -> str:
        return f"{self.prefix}invocation_auto_purge"

    def all_invocations_by_time(self) -> str:
        """Get key for sorted set of all invocation IDs indexed by registration time."""
        return f"{self.prefix}all_invocations_by_time"

    def task_invocations_by_time(self, task_id: str) -> str:
        """Get key for sorted set of invocation IDs for a task indexed by registration time."""
        return f"{self.prefix}task_invocations_by_time:{task_id}"

    def default_queue(self) -> str:
        return f"{self.prefix}default_queue"

    def client_data_store(self, key: str) -> str:
        return f"{self.prefix}client_data_store:{key}"

    def purge(self, client: redis.Redis) -> None:
        """
        Purges all keys with the given prefix in Redis.

        :param redis.Redis client: The Redis client.
        """
        pattern = f"{self.prefix}*"
        keys = list(client.scan_iter(pattern, count=1000))
        if keys:
            batch_size = 1000
            for i in range(0, len(keys), batch_size):
                batch = keys[i : i + batch_size]
                client.delete(*batch)

    def condition(self, condition_id: str) -> str:
        """Get key for storing a trigger condition."""
        return f"{self.prefix}condition:{condition_id}"

    def trigger(self, trigger_id: str) -> str:
        """Get key for storing a trigger definition."""
        return f"{self.prefix}trigger:{trigger_id}"

    def valid_condition(self, condition_id: str) -> str:
        """Get key for storing a valid condition."""
        return f"{self.prefix}valid_condition:{condition_id}"

    def task_triggers(self, task_id: str) -> str:
        """Get key for storing triggers associated with a task."""
        return f"{self.prefix}task_triggers:{task_id}"

    def condition_triggers(self, condition_id: str) -> str:
        """Get key for storing triggers that use a condition."""
        return f"{self.prefix}condition_triggers:{condition_id}"

    def event_channel(self) -> str:
        """Get channel name for publishing trigger events."""
        return f"{self.prefix}events"

    def cron_last_execution(self, condition_id: str) -> str:
        """
        Generate a key for storing the last execution time of a cron condition.

        :param condition_id: ID of the cron condition
        :return: Redis key string
        """
        return f"{self.prefix}cron_last_execution:{condition_id}"

    def source_task_conditions(self, task_id: str) -> str:
        """
        Generate key for source task to condition mapping.

        This key stores conditions that are sourced from a specific task.

        :param task_id: ID of the source task
        :return: Redis key for task's source conditions
        """
        return f"{self.prefix}source_task_conditions:{task_id}"

    # ── Monitoring keys (events + trigger runs) ────────────────────────
    def event_hash(self, event_id: str) -> str:
        """JSON storage for one ``EventRecord``."""
        return f"{self.prefix}evts_hash:{event_id}"

    def events_by_time(self) -> str:
        """Sorted set of ``event_id`` ordered by epoch-millisecond timestamp."""
        return f"{self.prefix}evts_by_time"

    def events_by_code(self, event_code: str) -> str:
        """Sorted set of ``event_id`` for a single ``event_code``."""
        return f"{self.prefix}evts_by_code:{event_code}"

    def events_codes(self) -> str:
        """Set of distinct ``event_code`` values seen so far."""
        return f"{self.prefix}evts_codes"

    def events_matched(self) -> str:
        """Sorted set of matched event ids by timestamp."""
        return f"{self.prefix}evts_matched"

    def events_triggered(self) -> str:
        """Sorted set of events that produced at least one invocation."""
        return f"{self.prefix}evts_triggered"

    def trigger_run_hash(self, trigger_run_id: str) -> str:
        """JSON storage for one ``TriggerRunRecord``."""
        return f"{self.prefix}trun_hash:{trigger_run_id}"

    def trigger_runs_by_time(self) -> str:
        """Sorted set of ``trigger_run_id`` ordered by epoch-millisecond time."""
        return f"{self.prefix}truns_by_time"

    def trigger_runs_for_event(self, event_id: str) -> str:
        """Set of trigger run ids that reference an event."""
        return f"{self.prefix}truns_for_event:{event_id}"

    def trigger_runs_for_invocation(self, invocation_id: str) -> str:
        """Set of trigger run ids that produced an invocation."""
        return f"{self.prefix}truns_for_invocation:{invocation_id}"

    def trigger_runs_sourced_by_invocation(self, invocation_id: str) -> str:
        """Set of trigger run ids that used an invocation as source."""
        return f"{self.prefix}truns_sourced_by_invocation:{invocation_id}"

    def trigger_runs_for_valid_condition(self, valid_condition_id: str) -> str:
        """Set of trigger run ids that included a valid condition."""
        return f"{self.prefix}truns_for_valid_condition:{valid_condition_id}"

    def event_triggered_invocations(self, event_id: str) -> str:
        """Ordered list of invocation ids triggered by an event."""
        return f"{self.prefix}evts_triggered_invocations:{event_id}"

    def trigger_execution_claim(self, trigger_id: str, valid_condition_id: str) -> str:
        """
        Generate a key for a trigger execution claim.

        This key is used to atomically claim the right to execute a trigger
        for a specific valid condition across multiple workers.

        :param trigger_id: ID of the trigger definition
        :param valid_condition_id: ID of the valid condition
        :return: Redis key for the trigger execution claim
        """
        return (
            f"{self.prefix}:trigger:execution_claim:{trigger_id}:{valid_condition_id}"
        )

    def trigger_run_claim(self, trigger_run_id: str) -> str:
        """
        Generate a key for a trigger run claim.

        This key is used to atomically claim the right to execute a specific trigger run
        across multiple workers. A trigger run is a unique execution attempt for a
        trigger and its satisfied conditions.

        :param trigger_run_id: Unique ID for this trigger run
        :return: Redis key for the trigger run claim
        """
        return f"{self.prefix}:trigger:run_claim:{trigger_run_id}"

    def workflow_run_by_id(self, workflow_id: str) -> str:
        """
        Get key for storing a workflow run by its unique workflow_id.

        :param workflow_id: The unique workflow ID
        :return: Redis key for the workflow run
        """
        return f"{self.prefix}workflow:run:{workflow_id}"

    def workflow_type_index(self, workflow_type: str) -> str:
        """
        Get key for storing the set of workflow_ids for a workflow_type.

        :param workflow_type: The workflow type (task_id)
        :return: Redis key for the workflow type index set
        """
        return f"{self.prefix}workflow:type_index:{workflow_type}"

    def workflow_types(self) -> str:
        """
        Get key for storing workflow types set.

        This key automatizes purge as it follows the app-scoped prefix pattern.

        :return: Redis key for workflow types set
        """
        return f"{self.prefix}workflow:types"

    def workflow_data_value(self, workflow_id: str, key: str) -> str:
        return f"{self.prefix}workflow:{workflow_id}:data:{key}"

    def workflow_deterministic_value(self, workflow_id: str, key: str) -> str:
        """
        Get key for storing a deterministic value for workflow operations.

        :param workflow_id: ID of the workflow
        :param key: Identifier for the deterministic value
        :return: Redis key for the deterministic value
        """
        return f"{self.prefix}workflow:{workflow_id}:det:{key}"

    def runner_context(self, runner_id: str) -> str:
        """
        Get key for storing a runner context.

        :param runner_id: The runner's unique identifier
        :return: Redis key for the runner context
        """
        return f"{self.prefix}runner_context:{runner_id}"

    def workflow_sub_invocations(self, workflow_id: str) -> str:
        """
        Get key for storing sub-invocation IDs that run inside a workflow.

        This key automatizes purge as it follows the app-scoped prefix pattern.

        :param workflow_id: ID of the workflow
        :return: Redis key for workflow sub-invocations set
        """
        return f"{self.prefix}workflow:{workflow_id}:sub_invocations"

    def parent_invocation_children(self, parent_invocation_id: str) -> str:
        """
        Get key for storing child invocation IDs spawned by a parent invocation.

        :param parent_invocation_id: The parent invocation ID
        :return: Redis key for parent's child invocations set
        """
        return f"{self.prefix}parent_invocation_children:{parent_invocation_id}"

    def parent_event_children(self, parent_event_id: str) -> str:
        """
        Get key for storing invocation IDs spawned by a trigger event.

        :param parent_event_id: The parent event ID
        :return: Redis key for event-triggered child invocations
        """
        return f"{self.prefix}parent_event_children:{parent_event_id}"

    def workflow_invocations(self, workflow_id: str) -> str:
        """
        Get key for storing invocation IDs that belong to a specific workflow.

        :param workflow_id: ID of the workflow
        :return: Redis key for workflow invocations set
        """
        return f"{self.prefix}workflow:invocations:{workflow_id}"

    def workflow_type_invocations(self, workflow_type_key: str) -> str:
        """
        Get key for storing invocation IDs grouped by workflow type.

        :param workflow_type_key: The workflow type key (task_id key)
        :return: Redis key for workflow type invocations set
        """
        return f"{self.prefix}workflow:type_invocations:{workflow_type_key}"

    @staticmethod
    def all_apps_info_key(app_id: str) -> str:
        """
        Get key for storing app information in the central registry.

        This uses a special prefix outside the normal app namespace
        to make discovery possible across all apps.

        :param app_id: The ID of the app
        :return: Redis key for app information
        """
        return f"{PYNENC_KEY_PREFIX}:{PYNENC_KEY_PREFIX}:apps_info:{app_id}"
