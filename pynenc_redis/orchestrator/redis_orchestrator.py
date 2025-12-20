import json
import threading
from collections.abc import Iterator
from concurrent.futures import Future
from datetime import UTC, datetime
from functools import cached_property
from time import time
from typing import TYPE_CHECKING

import redis
from pynenc.call import Call
from pynenc.exceptions import (
    CycleDetectedError,
)
from pynenc.invocation.dist_invocation import DistributedInvocation
from pynenc.invocation.status import (
    InvocationStatus,
    InvocationStatusRecord,
    status_record_transition,
)
from pynenc.orchestrator.atomic_service import ActiveRunnerInfo
from pynenc.orchestrator.base_orchestrator import (
    BaseBlockingControl,
    BaseCycleControl,
    BaseOrchestrator,
)
from pynenc.types import Params, Result

from pynenc_redis.conf.config_orchestrator import ConfigOrchestratorRedis
from pynenc_redis.util.mongo_client import get_redis_client
from pynenc_redis.util.redis_keys import Key

if TYPE_CHECKING:
    from pynenc.app import Pynenc
    from pynenc.runner.runner_context import RunnerContext
    from pynenc.task import Task


# Thread registry to avoid duplicating status update threads for the same invocation
_pending_resolution_threads: dict[str, Future[None]] = {}
_registry_lock = threading.Lock()


def _clean_dead_threads() -> None:
    """Remove completed futures from the registry to prevent memory leaks."""
    with _registry_lock:
        completed_keys = [
            inv_id
            for inv_id, future in _pending_resolution_threads.items()
            if future.done()
        ]
        for inv_id in completed_keys:
            _pending_resolution_threads.pop(inv_id)


class StatusNotFound(Exception):
    """Raised when a status is not found in Redis"""


class RedisCycleControl(BaseCycleControl):
    """
    A Redis-based implementation of cycle control using a directed acyclic graph (DAG).

    This class manages the dependencies between task invocations in Redis
    to prevent cycles in task calling patterns, which could lead to deadlocks or infinite loops.

    :param Pynenc app: The Pynenc application instance.
    :param redis.Redis client: The Redis client instance.
    """

    def __init__(self, app: "Pynenc", client: redis.Redis) -> None:
        self.app = app
        self.key = Key(app.app_id, "cycle_control")
        self.client = client

    def purge(self) -> None:
        """Purges all data related to cycle control from Redis."""
        self.key.purge(self.client)

    def add_call_and_check_cycles(
        self, caller: "DistributedInvocation", callee: "DistributedInvocation"
    ) -> None:
        """Adds a new call relationship between invocations and checks for potential cycles."""
        if caller.call_id == callee.call_id:
            raise CycleDetectedError.from_cycle([caller.call])
        if cycle := self.find_cycle_caused_by_new_invocation(caller, callee):
            raise CycleDetectedError.from_cycle(cycle)
        self.client.set(self.key.call(caller.call_id), caller.call.to_json())
        self.client.set(self.key.call(callee.call_id), callee.call.to_json())
        self.client.sadd(self.key.edge(caller.call_id), callee.call_id)
        self.client.sadd(self.key.reverse_edge(callee.call_id), caller.call_id)

    def get_callees(self, caller_call_id: str) -> Iterator[str]:
        """
        Returns an iterator of direct callee call_ids for the given caller_call_id.

        :param caller_call_id: The call_id of the caller invocation.
        :return: Iterator of callee call_ids.
        """
        for callee_call_id in self.client.smembers(self.key.edge(caller_call_id)):
            yield callee_call_id.decode()

    def _get_all_call_ids(self) -> Iterator[str]:
        """Returns an iterator of all call_ids in the graph."""
        for key in self.client.scan_iter(match=self.key.call("*")):
            yield key.decode().split(":")[-1]

    def _get_all_edges(self) -> Iterator[tuple[str, str]]:
        """Returns an iterator of all edges in the graph as (caller_call_id, callee_call_id) tuples."""
        for key in self.client.scan_iter(match=self.key.edge("*")):
            key_str = key.decode()
            caller_call_id = key_str.split(":")[-1]
            for callee_bytes in self.client.smembers(key):
                callee_call_id = callee_bytes.decode()
                yield (caller_call_id, callee_call_id)

    def _get_all_reverse_edges(self) -> Iterator[tuple[str, str]]:
        """Returns an iterator of all reverse edges in the graph as (callee_call_id, caller_call_id) tuples."""
        for key in self.client.scan_iter(match=self.key.reverse_edge("*")):
            key_str = key.decode()
            caller_call_id = key_str.split(":")[-1]
            for callee_bytes in self.client.smembers(key):
                callee_call_id = callee_bytes.decode()
                yield (caller_call_id, callee_call_id)

    def remove_edges(self, call_id: str) -> None:
        """
        Removes all outgoing and incoming edges for a given call in the graph.

        :param call_id: The ID of the call whose edges should be removed.
        """
        # Remove outgoing edges
        self.client.delete(self.key.edge(call_id))
        # Remove incoming edges: for each caller in reverse_edge, remove call_id from their edge set
        for caller_call_id_bytes in self.client.smembers(
            self.key.reverse_edge(call_id)
        ):
            caller_call_id = caller_call_id_bytes.decode()
            self.client.srem(self.key.edge(caller_call_id), call_id)
        # Remove reverse edge set for call_id
        self.client.delete(self.key.reverse_edge(call_id))

    def clean_up_invocation_cycles(self, invocation_id: str) -> None:
        """
        Cleans up any cycle-related data when an invocation is finished.

        :param invocation_id: The ID of the invocation that has finished.
        """
        call_id = self.app.orchestrator.get_invocation_call_id(invocation_id)
        if not self.app.orchestrator.any_non_final_invocations(call_id):
            self.client.delete(self.key.call(call_id))
            self.remove_edges(call_id)

    def find_cycle_caused_by_new_invocation(
        self, caller: "DistributedInvocation", callee: "DistributedInvocation"
    ) -> list["Call"]:
        """
        Checks if adding a new call from `caller` to `callee` would create a cycle.
        :param DistributedInvocation caller: The invocation making the call.
        :param DistributedInvocation callee: The invocation being called.
        :return: List of `Call` objects forming the cycle, if a cycle is detected; otherwise, an empty list.
        """
        # Temporarily add the edge to check if it would cause a cycle
        self.client.sadd(self.key.edge(caller.call_id), callee.call_id)

        # Set for tracking visited nodes
        visited: set[str] = set()

        # List for tracking the nodes on the path from caller to callee
        path: list[str] = []

        cycle = self._is_cyclic_util(caller.call_id, visited, path)

        # Remove the temporarily added edge
        self.client.srem(self.key.edge(caller.call_id), callee.call_id)

        return cycle

    def _is_cyclic_util(
        self,
        current_call_id: str,
        visited: set[str],
        path: list[str],
    ) -> list["Call"]:
        """
        A utility function for cycle detection.
        :param str current_call_id: The current call ID being examined.
        :param set[str] visited: A set of visited call IDs for cycle detection.
        :param list[str] path: A list representing the current path of call IDs.
        :return: List of `Call` objects forming a cycle, if a cycle is detected; otherwise, an empty list.
        """
        visited.add(current_call_id)
        path.append(current_call_id)

        call_cycle = []
        for _neighbour_call_id in self.client.smembers(self.key.edge(current_call_id)):
            neighbour_call_id = _neighbour_call_id.decode()
            if neighbour_call_id not in visited:
                cycle = self._is_cyclic_util(neighbour_call_id, visited, path)
                if cycle:
                    return cycle
            elif neighbour_call_id in path:
                cycle_start_index = path.index(neighbour_call_id)
                for _id in path[cycle_start_index:]:
                    if call_json := self.client.get(self.key.call(_id)):
                        call_cycle.append(Call.from_json(self.app, call_json.decode()))
        path.pop()
        return call_cycle


class RedisBlockingControl(BaseBlockingControl):
    """
    A Redis-based implementation of blocking control for task invocations.

    Manages invocation dependencies and blocking states in a Redis-backed environment,
    ensuring that invocations waiting for others are properly tracked and released.

    :param Pynenc app: The Pynenc application instance.
    :param redis.Redis client: The Redis client instance.
    """

    def __init__(self, app: "Pynenc", client: redis.Redis) -> None:
        self.app = app
        self.key = Key(app.app_id, "blocking_control")
        self.client = client

    def purge(self) -> None:
        """Purges all data related to blocking control from Redis."""
        self.key.purge(self.client)

    def waiting_for_results(
        self, caller_invocation_id: str, result_invocation_ids: list[str]
    ) -> None:
        """
        Notifies the system that an invocation is waiting for the results of other invocations.

        :param caller_invocation_id: The ID of the invocation that is waiting.
        :param result_invocation_ids: The IDs of the invocations being waited on.
        """
        for waited_invocation_id in result_invocation_ids:
            self.client.set(
                self.key.invocation(waited_invocation_id), waited_invocation_id
            )
            self.client.sadd(
                self.key.waited_by(waited_invocation_id), caller_invocation_id
            )
            self.client.zadd(self.key.all_waited(), {waited_invocation_id: time()})
            if not self.client.exists(self.key.waiting_for(waited_invocation_id)):
                self.client.zadd(self.key.not_waiting(), {waited_invocation_id: time()})
        if self.client.zscore(self.key.not_waiting(), caller_invocation_id) is not None:
            self.client.zrem(self.key.not_waiting(), caller_invocation_id)
        self.client.sadd(
            self.key.waiting_for(caller_invocation_id), *result_invocation_ids
        )

    def release_waiters(self, waited_invocation_id: str) -> None:
        """
        Releases any invocations that are waiting on the specified invocation.

        :param waited_invocation_id: The ID of the invocation that has finished and can release its waiters.
        """
        for waiter_invocation_id in self.client.smembers(
            self.key.waited_by(waited_invocation_id)
        ):
            self.client.srem(
                self.key.waiting_for(waiter_invocation_id.decode()),
                waited_invocation_id,
            )
            if not self.client.exists(self.key.waiting_for(waiter_invocation_id)):
                self.client.zadd(self.key.not_waiting(), {waiter_invocation_id: time()})
        self.client.delete(self.key.invocation(waited_invocation_id))
        self.client.delete(self.key.waiting_for(waited_invocation_id))
        self.client.delete(self.key.waited_by(waited_invocation_id))
        self.client.zrem(self.key.all_waited(), waited_invocation_id)
        self.client.zrem(self.key.not_waiting(), waited_invocation_id)

    def get_blocking_invocations(self, max_num_invocations: int) -> Iterator[str]:
        """
        Retrieves invocation IDs that are blocking others but are not blocked themselves.

        :param max_num_invocations: The maximum number of blocking invocation IDs to retrieve.
        :return: An iterator over unblocked, blocking invocation IDs, ordered by age (oldest first).
        """
        index = 0
        page_size = max(10, max_num_invocations)
        count = 0
        while count < max_num_invocations:
            if not (
                page := self.client.zrange(
                    self.key.not_waiting(), index, index + page_size - 1
                )
            ):
                break
            index += page_size
            for waited_invocation_id in page:
                invocation_id = waited_invocation_id.decode()
                val_inv_id = self.client.get(self.key.invocation(invocation_id))
                if not val_inv_id:
                    continue
                try:
                    status_record = self.app.orchestrator.get_invocation_status_record(
                        invocation_id
                    )
                    if status_record.status.is_available_for_run():
                        yield invocation_id
                        count += 1
                    if count == max_num_invocations:
                        break
                except KeyError:
                    self.app.logger.warning(
                        f"Skipping invocation {invocation_id} in get_blocking_invocations: "
                        "status not found in Redis"
                    )
                if max_num_invocations == 0:
                    break


class RedisOrchestrator(BaseOrchestrator):
    """
    Orchestrator implementation using Redis for distributed invocation management.

    Stores status records with ownership tracking by invocation_id, using atomic
    transactions for status changes.
    """

    def __init__(self, app: "Pynenc") -> None:
        super().__init__(app)
        self._client: redis.Redis | None = None
        self._cycle_control: RedisCycleControl | None = None
        self._blocking_control: RedisBlockingControl | None = None
        self.key = Key(app.app_id, "orchestrator")

    @cached_property
    def conf(self) -> ConfigOrchestratorRedis:
        return ConfigOrchestratorRedis(
            config_values=self.app.config_values,
            config_filepath=self.app.config_filepath,
        )

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = get_redis_client(self.conf)
        return self._client

    @property
    def cycle_control(self) -> "RedisCycleControl":
        if not self._cycle_control:
            self._cycle_control = RedisCycleControl(self.app, self.client)
        return self._cycle_control

    @property
    def blocking_control(self) -> "RedisBlockingControl":
        if not self._blocking_control:
            self._blocking_control = RedisBlockingControl(self.app, self.client)
        return self._blocking_control

    def get_existing_invocations(
        self,
        task: "Task[Params, Result]",
        key_serialized_arguments: dict[str, str] | None = None,
        statuses: list["InvocationStatus"] | None = None,
    ) -> Iterator[str]:
        """
        Retrieves existing invocation IDs based on task, arguments, and status.

        :param task: The task for which to retrieve invocations.
        :param key_serialized_arguments: Serialized arguments to filter invocations.
        :param statuses: The statuses to filter invocations.
        :return: An iterator over the matching invocation IDs.
        """
        task_id: str = task.task_id
        invocation_ids: set[str] = set()
        for inv_id in self.client.smembers(self.key.task(task_id)):
            invocation_ids.add(inv_id.decode() if isinstance(inv_id, bytes) else inv_id)
        if key_serialized_arguments:
            for arg, val in key_serialized_arguments.items():
                arg_val_ids = {
                    id.decode() if isinstance(id, bytes) else id
                    for id in self.client.smembers(self.key.args(task_id, arg, val))
                }
                invocation_ids &= arg_val_ids
        if statuses:
            status_ids: set[str] = set()
            for status in statuses:
                status_ids |= {
                    id.decode() if isinstance(id, bytes) else id
                    for id in self.client.smembers(
                        self.key.status_to_invocations(status)
                    )
                }
            invocation_ids &= status_ids
        for inv_id in invocation_ids:
            yield inv_id

    def get_task_invocation_ids(self, task_id: str) -> Iterator[str]:
        """
        Retrieves all invocation IDs associated with a specific task ID.

        :param task_id: The task ID to filter invocations.
        :return: Iterator of invocation IDs for the specified task.
        """
        for inv_id in self.client.smembers(self.key.task(task_id)):
            yield inv_id.decode() if isinstance(inv_id, bytes) else inv_id

    def get_invocation_ids_paginated(
        self,
        task_id: str | None = None,
        statuses: list["InvocationStatus"] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[str]:
        """
        Retrieves invocation IDs with pagination support.

        Uses Redis sorted sets indexed by registration time for efficient pagination.
        Results are ordered by registration time (newest first).

        :param task_id: Optional task ID to filter by.
        :param statuses: Optional statuses to filter by.
        :param limit: Maximum number of results to return.
        :param offset: Number of results to skip.
        :return: List of matching invocation IDs.
        """
        # Determine which sorted set to use based on task_id filter
        if task_id:
            source_key = self.key.task_invocations_by_time(task_id)
        else:
            source_key = self.key.all_invocations_by_time()

        # If no status filter, use direct range query (newest first = reverse order)
        if not statuses:
            raw_ids = self.client.zrevrange(source_key, offset, offset + limit - 1)
            return [
                inv_id.decode() if isinstance(inv_id, bytes) else inv_id
                for inv_id in raw_ids
            ]

        # With status filter, need to intersect with status sets
        status_keys = [self.key.status_to_invocations(status) for status in statuses]

        # Get all invocation IDs from status sets
        status_inv_ids: set[str] = set()
        for status_key in status_keys:
            for inv_id in self.client.smembers(status_key):
                decoded_id = inv_id.decode() if isinstance(inv_id, bytes) else inv_id
                status_inv_ids.add(decoded_id)

        if not status_inv_ids:
            return []

        # Get invocations from time-sorted set with their scores for ordering
        # Using zrevrange with scores to get all, then filter and paginate
        all_with_scores = self.client.zrevrange(source_key, 0, -1, withscores=True)

        # Filter by status and collect in order
        filtered_ids = []
        for inv_id, _score in all_with_scores:
            decoded_id = inv_id.decode() if isinstance(inv_id, bytes) else inv_id
            if decoded_id in status_inv_ids:
                filtered_ids.append(decoded_id)

        # Apply pagination
        return filtered_ids[offset : offset + limit]

    def count_invocations(
        self,
        task_id: str | None = None,
        statuses: list["InvocationStatus"] | None = None,
    ) -> int:
        """
        Counts invocations matching the given filters.

        :param task_id: Optional task ID to filter by.
        :param statuses: Optional statuses to filter by.
        :return: The total count of matching invocations.
        """
        # Determine source based on task_id filter
        if task_id:
            source_key = self.key.task_invocations_by_time(task_id)
        else:
            source_key = self.key.all_invocations_by_time()

        # If no status filter, return count from sorted set
        if not statuses:
            return self.client.zcard(source_key)

        # With status filter, need to count intersection
        # Get all invocation IDs from the source
        source_inv_ids: set[str] = {
            inv_id.decode() if isinstance(inv_id, bytes) else inv_id
            for inv_id in self.client.zrange(source_key, 0, -1)
        }

        if not source_inv_ids:
            return 0

        # Get all invocation IDs matching any of the statuses
        status_inv_ids: set[str] = set()
        for status in statuses:
            for inv_id in self.client.smembers(self.key.status_to_invocations(status)):
                decoded_id = inv_id.decode() if isinstance(inv_id, bytes) else inv_id
                status_inv_ids.add(decoded_id)

        # Return count of intersection
        return len(source_inv_ids & status_inv_ids)

    def get_call_invocation_ids(self, call_id: str) -> Iterator[str]:
        """
        Retrieves all invocation IDs associated with a specific call ID.

        :param call_id: The call ID to filter invocations.
        :return: Iterator of invocation IDs for the specified call.
        """
        for inv_id in self.client.smembers(self.key.call_to_invocation(call_id)):
            yield inv_id.decode() if isinstance(inv_id, bytes) else inv_id

    def get_invocation_call_id(self, invocation_id: str) -> str:
        """
        Retrieves the call ID associated with a specific invocation ID.

        :param invocation_id: The invocation ID to look up.
        :return: The call ID associated with the invocation.
        :raises KeyError: If the mapping is not found.
        """
        self.client.get(self.key.invocation_to_call(invocation_id))
        if call_id := self.client.get(self.key.invocation_to_call(invocation_id)):
            return call_id.decode() if isinstance(call_id, bytes) else call_id
        raise KeyError(f"Invocation to call mapping for {invocation_id} not found")

    def any_non_final_invocations(self, call_id: str) -> bool:
        """
        Checks if there are any non-final invocations for a specific call ID.

        :param call_id: The call ID to check for non-final invocations.
        :return: True if there are non-final invocations, False otherwise.
        """
        for invocation_id in self.get_call_invocation_ids(call_id):
            status_record = self.get_invocation_status_record(invocation_id)
            if not status_record.status.is_final():
                return True
        return False

    def _register_new_invocations(
        self,
        invocations: list["DistributedInvocation[Params, Result]"],
        owner_id: str | None = None,
    ) -> InvocationStatusRecord:
        """
        Register new invocations with status REGISTERED if they don't exist yet.

        Initializes the necessary Redis data structures for task-to-invocation,
        call-to-invocation mappings, status, and retry tracking.
        """
        status_record = InvocationStatusRecord(InvocationStatus.REGISTERED, owner_id)
        for invocation in invocations:
            # Skip if already registered
            if self.client.exists(
                self.key.invocation_to_status(invocation.invocation_id)
            ):
                continue

            # Add to task's invocation set
            self.client.sadd(
                self.key.task(invocation.task.task_id), invocation.invocation_id
            )

            # Add to call's invocation set
            self.client.sadd(
                self.key.call_to_invocation(invocation.call_id),
                invocation.invocation_id,
            )

            # Store invocation_id -> call_id mapping
            self.client.set(
                self.key.invocation_to_call(invocation.invocation_id),
                invocation.call_id,
            )

            # Set status to REGISTERED
            self._set_status_record(invocation.invocation_id, status_record)

            # Initialize retry count to 0
            self.client.set(self.key.invocation_retries(invocation.invocation_id), 0)

            # Add to time-indexed sorted sets for pagination support
            registration_time = time()
            self.client.zadd(
                self.key.all_invocations_by_time(),
                {invocation.invocation_id: registration_time},
            )
            self.client.zadd(
                self.key.task_invocations_by_time(invocation.task.task_id),
                {invocation.invocation_id: registration_time},
            )
        return status_record

    def _set_status_record(
        self, invocation_id: str, status_record: InvocationStatusRecord
    ) -> None:
        """Store a status record in Redis."""
        pipeline = self.client.pipeline(transaction=True)
        pipeline.sadd(
            self.key.status_to_invocations(status_record.status), invocation_id
        )
        pipeline.set(
            self.key.invocation_to_status(invocation_id),
            json.dumps(status_record.to_json()),
        )
        pipeline.execute()

    def _atomic_status_transition(
        self, invocation_id: str, status: InvocationStatus, owner_id: str | None = None
    ) -> InvocationStatusRecord:
        """
        Perform atomic status transition with validation.

        Uses Redis transactions to ensure atomic updates with ownership validation.
        """
        # Get current status record
        current_record = self.get_invocation_status_record(invocation_id)

        # Validate and compute new record
        new_record = status_record_transition(current_record, status, owner_id)

        # Use Redis transaction for atomic update
        pipeline = self.client.pipeline(transaction=True)

        # Remove from old status set
        pipeline.srem(
            self.key.status_to_invocations(current_record.status), invocation_id
        )

        # Add to new status set and update status record
        pipeline.sadd(self.key.status_to_invocations(new_record.status), invocation_id)
        pipeline.set(
            self.key.invocation_to_status(invocation_id),
            json.dumps(new_record.to_json()),
        )

        pipeline.execute()

        self.app.logger.debug(
            f"Transitioned invocation {invocation_id} from {current_record.status} to {status}"
        )

        return new_record

    def get_invocation_status_record(
        self, invocation_id: str
    ) -> InvocationStatusRecord:
        """
        Retrieves the status record of a specific invocation.

        :param invocation_id: The id of the invocation whose status is to be retrieved.
        :return: The current status record of the invocation.
        :raises KeyError: If invocation not found.
        """
        if encoded_status := self.client.get(
            self.key.invocation_to_status(invocation_id)
        ):
            status_dict = json.loads(encoded_status.decode())
            return InvocationStatusRecord.from_json(status_dict)
        raise KeyError(f"Invocation status {invocation_id} not found in Redis")

    def index_arguments_for_concurrency_control(
        self,
        invocation: "DistributedInvocation[Params, Result]",
    ) -> None:
        """
        Caches the required data to implement concurrency control.

        :param invocation: The invocation to be cached.
        """
        for key, value in invocation.serialized_arguments.items():
            self.client.sadd(
                self.key.args(invocation.task.task_id, key, value),
                invocation.invocation_id,
            )

    def set_up_invocation_auto_purge(self, invocation_id: str) -> None:
        """
        Sets up automatic purging for an invocation after a defined period.

        :param invocation_id: The invocation to set up for auto purge.
        """
        self.client.zadd(
            self.key.invocation_auto_purge(),
            {invocation_id: time()},
        )

    def auto_purge(self) -> None:
        """
        Automatically purges invocations that have been in their final state beyond a specified duration.
        """
        end_time = (
            time() - self.app.orchestrator.conf.auto_final_invocation_purge_hours * 3600
        )
        for _invocation_id in self.client.zrangebyscore(
            self.key.invocation_auto_purge(), 0, end_time
        ):
            invocation_id = _invocation_id.decode()
            try:
                invocation = self.app.state_backend.get_invocation(invocation_id)
                task_id = invocation.task.task_id
                # clean up task keys
                self.client.srem(self.key.task(task_id), invocation_id)
                if not self.client.smembers(self.key.task(task_id)):
                    self.client.delete(self.key.task(task_id))
                # clean up task-status keys
                status_record = self.get_invocation_status_record(invocation_id)
                self.client.srem(
                    self.key.status_to_invocations(status_record.status), invocation_id
                )
                if not self.client.smembers(
                    self.key.status_to_invocations(status_record.status)
                ):
                    self.client.delete(
                        self.key.status_to_invocations(status_record.status)
                    )
            except KeyError:
                self.app.logger.warning(f"{invocation_id=} not found during auto purge")
            self.client.delete(self.key.invocation_to_status(invocation_id))
            self.client.zrem(self.key.invocation_auto_purge(), invocation_id)

    def increment_invocation_retries(self, invocation_id: str) -> None:
        """
        Increments the retry count of a specific invocation.

        :param invocation_id: The id of the invocation for which to increment retries.
        """
        self.client.incr(self.key.invocation_retries(invocation_id))

    def get_invocation_retries(self, invocation_id: str) -> int:
        """
        Retrieves the number of retries for a specific invocation.

        :param invocation_id: The id of the invocation whose retry count is to be retrieved.
        :return: The number of retries for the invocation.
        """
        if encoded_retries := self.client.get(
            self.key.invocation_retries(invocation_id)
        ):
            return int(encoded_retries.decode())
        return 0

    def filter_by_status(
        self, invocation_ids: list[str], status_filter: frozenset["InvocationStatus"]
    ) -> list[str]:
        """
        Filters a list of invocation ids by their status in an optimized way.

        :param invocation_ids: The invocation ids to filter
        :param status_filter: The statuses to filter by.
        :return: List of invocation ids matching the status filter
        """
        if not invocation_ids or not status_filter:
            return []
        with self.client.pipeline(transaction=False) as pipe:
            for inv_id in invocation_ids:
                pipe.get(self.key.invocation_to_status(inv_id))
            status_results = pipe.execute()
        filtered = []
        for i, inv_id in enumerate(invocation_ids):
            status_json = status_results[i]
            if not status_json:
                continue
            status_dict = json.loads(status_json.decode())
            status_record = InvocationStatusRecord.from_json(status_dict)
            if status_record.status in status_filter:
                filtered.append(inv_id)
        return filtered

    def register_runner_heartbeat(self, runner_ctx: "RunnerContext") -> None:
        """Register or update a runner's heartbeat timestamp."""
        current_time = time()
        runner_id = runner_ctx.runner_id
        runner_json = runner_ctx.to_json()
        runner_key = self.key.runner_heartbeat(runner_id)

        pipeline = self.client.pipeline(transaction=True)

        # Add to sorted set only if doesn't exist (NX flag preserves creation order)
        pipeline.zadd(self.key.runner_heartbeats(), {runner_id: current_time}, nx=True)

        # Always update the hash - use HSET with multiple fields
        # If key doesn't exist, this creates it with all fields
        # If key exists, this only updates the fields we specify
        pipeline.hsetnx(runner_key, "creation_timestamp", current_time)
        pipeline.hset(
            runner_key,
            mapping={
                "runner_context_json": runner_json,
                "last_heartbeat": current_time,
            },
        )

        pipeline.execute()

    def record_atomic_service_execution(
        self, runner_ctx: "RunnerContext", start_time: datetime, end_time: datetime
    ) -> None:
        """
        Record the latest atomic service execution window for a runner.

        :param runner_ctx: The runner context
        :param start_time: Service execution start timestamp
        :param end_time: Service execution end timestamp
        """
        runner_id = runner_ctx.runner_id
        runner_key = self.key.runner_heartbeat(runner_id)

        self.client.hset(
            runner_key,
            mapping={
                "last_service_start": start_time.timestamp(),
                "last_service_end": end_time.timestamp(),
            },
        )

    def get_active_runners(self) -> list[ActiveRunnerInfo]:
        """Retrieve all active runners with heartbeat information."""
        from pynenc.runner.runner_context import RunnerContext

        timeout_seconds = self.conf.runner_heartbeat_timeout_minutes * 60
        current_time = time()
        cutoff_time = current_time - timeout_seconds

        # Get all runner IDs ordered by creation time (sorted set score)
        all_runner_ids = self.client.zrange(self.key.runner_heartbeats(), 0, -1)

        # Use pipeline to fetch all runner data at once
        if not all_runner_ids:
            return []

        pipeline = self.client.pipeline(transaction=False)
        for runner_id_bytes in all_runner_ids:
            runner_id = runner_id_bytes.decode()
            pipeline.hgetall(self.key.runner_heartbeat(runner_id))

        runner_data_list = pipeline.execute()

        active_runners = []
        for runner_data in runner_data_list:
            if not runner_data:
                continue

            try:
                last_heartbeat = float(runner_data[b"last_heartbeat"].decode())
                # Filter by heartbeat timeout
                if last_heartbeat < cutoff_time:
                    continue

                runner_ctx = RunnerContext.from_json(
                    runner_data[b"runner_context_json"].decode()
                )

                # Optional service execution timestamps
                last_service_start = None
                last_service_end = None
                if b"last_service_start" in runner_data:
                    last_service_start = datetime.fromtimestamp(
                        float(runner_data[b"last_service_start"].decode()), tz=UTC
                    )
                if b"last_service_end" in runner_data:
                    last_service_end = datetime.fromtimestamp(
                        float(runner_data[b"last_service_end"].decode()), tz=UTC
                    )

                active_runners.append(
                    ActiveRunnerInfo(
                        runner_ctx=runner_ctx,
                        creation_time=datetime.fromtimestamp(
                            float(runner_data[b"creation_timestamp"].decode()), tz=UTC
                        ),
                        last_heartbeat=datetime.fromtimestamp(last_heartbeat, tz=UTC),
                        last_service_start=last_service_start,
                        last_service_end=last_service_end,
                    )
                )
            except (ValueError, KeyError):
                # Skip invalid runner contexts
                continue

        return active_runners

    def cleanup_inactive_runners(self) -> None:
        """Remove runners that haven't sent a heartbeat within the timeout period."""
        timeout_seconds = self.conf.runner_heartbeat_timeout_minutes * 60
        current_time = time()
        cutoff_time = current_time - timeout_seconds

        # Get all runner IDs from sorted set
        all_runner_ids = self.client.zrange(self.key.runner_heartbeats(), 0, -1)

        if not all_runner_ids:
            return

        # Use pipeline to fetch heartbeat times
        pipeline = self.client.pipeline(transaction=False)
        for runner_id_bytes in all_runner_ids:
            runner_id = runner_id_bytes.decode()
            pipeline.hget(self.key.runner_heartbeat(runner_id), "last_heartbeat")

        heartbeat_times = pipeline.execute()

        # Identify inactive runners
        inactive_runner_ids = []
        for runner_id_bytes, heartbeat_bytes in zip(
            all_runner_ids, heartbeat_times, strict=False
        ):
            if not heartbeat_bytes:
                # Runner data missing, consider inactive
                inactive_runner_ids.append(runner_id_bytes.decode())
                continue

            try:
                last_heartbeat = float(heartbeat_bytes.decode())
                if last_heartbeat < cutoff_time:
                    inactive_runner_ids.append(runner_id_bytes.decode())
            except ValueError:
                # Invalid heartbeat data, consider inactive
                inactive_runner_ids.append(runner_id_bytes.decode())

        # Clean up inactive runners in a single pipeline
        if inactive_runner_ids:
            pipeline = self.client.pipeline(transaction=True)
            for runner_id in inactive_runner_ids:
                pipeline.delete(self.key.runner_heartbeat(runner_id))
                pipeline.zrem(self.key.runner_heartbeats(), runner_id)
            pipeline.execute()

    def get_pending_invocations_for_recovery(self) -> Iterator[str]:
        """Retrieve invocation IDs stuck in PENDING status beyond the allowed time."""
        max_pending_seconds = self.app.conf.max_pending_seconds
        current_time = datetime.now(UTC)
        cutoff_timestamp = current_time.timestamp() - max_pending_seconds

        # Get all PENDING invocations
        pending_invocations = self.client.smembers(
            self.key.status_to_invocations(InvocationStatus.PENDING)
        )

        for invocation_id_bytes in pending_invocations:
            invocation_id = invocation_id_bytes.decode()
            try:
                status_record = self.get_invocation_status_record(invocation_id)
                if status_record.timestamp.timestamp() <= cutoff_timestamp:
                    yield invocation_id
            except KeyError:
                # Invocation no longer exists
                continue

    def purge(self) -> None:
        """Remove all invocations from the orchestrator"""
        self.key.purge(self.client)
        self.cycle_control.purge()
        self.blocking_control.purge()
