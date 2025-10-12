from collections.abc import Iterator
from functools import cached_property
from typing import TYPE_CHECKING, Any

import redis
from pynenc.exceptions import InvocationNotFoundError
from pynenc.invocation.dist_invocation import DistributedInvocation
from pynenc.state_backend.base_state_backend import BaseStateBackend, InvocationHistory
from pynenc.workflow import WorkflowIdentity

from pynenc_redis.conf.config_redis import ConfigRedis
from pynenc_redis.conf.config_state_backend import ConfigStateBackendRedis
from pynenc_redis.util.mongo_client import get_redis_client
from pynenc_redis.util.redis_keys import Key

if TYPE_CHECKING:
    from pynenc.app import AppInfo, Pynenc
    from pynenc.types import Result


class RedisStateBackend(BaseStateBackend):
    """
    A Redis-based implementation of the state backend.

    This backend uses Redis to store and retrieve the state of invocations, including their data,
    history, results, and exceptions. It's suitable for distributed systems where shared state management is required.
    """

    def __init__(self, app: "Pynenc") -> None:
        super().__init__(app)
        self._client: redis.Redis | None = None
        self.key = Key(app.app_id, "state_backend")

    @cached_property
    def conf(self) -> ConfigStateBackendRedis:
        return ConfigStateBackendRedis(
            config_values=self.app.config_values,
            config_filepath=self.app.config_filepath,
        )

    @property
    def client(self) -> redis.Redis:
        """Lazy initialization of Redis client"""
        if self._client is None:
            self._client = get_redis_client(self.conf)
        return self._client

    def purge(self) -> None:
        """Clears all data from the Redis backend for the current `app.app_id`."""
        self.key.purge(self.client)

    def _upsert_invocations(self, invocations: list["DistributedInvocation"]) -> None:
        """
        Updates or inserts multiple invocations.

        :param list[DistributedInvocation] invocations: The invocations to upsert.
        """
        for invocation in invocations:
            self.client.set(
                self.key.invocation(invocation.invocation_id), invocation.to_json()
            )

    def _get_invocation(self, invocation_id: str) -> "DistributedInvocation":
        """
        Retrieves an invocation from Redis by its ID.

        :param str invocation_id: The ID of the invocation to retrieve.
        :return: The retrieved invocation object.
        """
        if inv := self.client.get(self.key.invocation(invocation_id)):
            return DistributedInvocation.from_json(self.app, inv.decode())
        raise InvocationNotFoundError(f"Invocation {invocation_id} not found")

    def _add_histories(
        self, invocation_ids: list[str], invocation_history: "InvocationHistory"
    ) -> None:
        """
        Adds a histories record for a list of invocations.

        :param list[str] invocation_ids: The IDs of the invocations.
        :param InvocationHistory invocation_history: The history record to add.
        """
        for invocation_id in invocation_ids:
            self.client.rpush(
                self.key.history(invocation_id),
                invocation_history.to_json(),
            )

    def _get_history(self, invocation_id: str) -> list[InvocationHistory]:
        """
        Retrieves the history of an invocation ordered by timestamp.

        :param str invocation_id: The ID of the invocation to get the history from
        :return: List of InvocationHistory records
        """
        histories = [
            InvocationHistory.from_json(h.decode())
            for h in self.client.lrange(self.key.history(invocation_id), 0, -1)
        ]
        # Order histories by their _timestamp attribute
        return sorted(histories, key=lambda h: getattr(h, "_timestamp", float("-inf")))

    def _set_result(self, invocation_id: str, result: "Result") -> None:
        """
        Sets the result of an invocation.

        :param str invocation_id: The ID of the invocation to set
        :param Result result: The result to set
        """
        self.client.set(
            self.key.result(invocation_id),
            self.app.serializer.serialize(result),
        )

    def _get_result(self, invocation_id: str) -> "Result":
        """
        Retrieves the result of an invocation.

        :param str invocation_id: The ID of the invocation to get the result from
        :return: The result value
        """
        if res := self.client.get(self.key.result(invocation_id)):
            return self.app.serializer.deserialize(res.decode())
        raise KeyError(f"Result for invocation {invocation_id} not found")

    def _set_exception(self, invocation_id: str, exception: "Exception") -> None:
        """
        Sets the raised exception by an invocation ran.

        :param str invocation_id: The ID of the invocation to set
        :param Exception exception: The exception raised
        """
        self.client.set(
            self.key.exception(invocation_id), self.serialize_exception(exception)
        )

    def _get_exception(self, invocation_id: str) -> Exception:
        """
        Retrieves the exception of an invocation.

        :param str invocation_id: The ID of the invocation to get the exception from
        :return: The exception object
        """
        if exc := self.client.get(self.key.exception(invocation_id)):
            return self.deserialize_exception(exc.decode())
        raise KeyError(f"Exception for invocation {invocation_id} not found")

    def get_workflow_data(
        self, workflow_identity: "WorkflowIdentity", key: str, default: Any = None
    ) -> Any:
        """
        Get a value from workflow data.

        :param workflow_identity: Workflow identity
        :param key: Data key to retrieve
        :param default: Default value if key doesn't exist
        :return: Stored value or default
        """
        data_key = self.key.workflow_data_value(workflow_identity.workflow_id, key)
        serialized_value = self.client.get(data_key)

        if serialized_value is None:
            return default

        return self.app.serializer.deserialize(serialized_value.decode())

    def set_workflow_data(
        self, workflow_identity: "WorkflowIdentity", key: str, value: Any
    ) -> None:
        """
        Set a value in workflow data.

        :param workflow_identity: Workflow identity
        :param key: Data key to set
        :param value: Value to store
        """
        data_key = self.key.workflow_data_value(workflow_identity.workflow_id, key)
        serialized_value = self.app.serializer.serialize(value)
        self.client.set(data_key, serialized_value)

    def store_app_info(self, app_info: "AppInfo") -> None:
        """
        Register this app's information in the state backend for discovery.

        :param app_info: The app information to store
        """
        self.client.set(self.key.all_apps_info_key(app_info.app_id), app_info.to_json())

    def get_app_info(self) -> "AppInfo":
        """
        Retrieve information of the current app.

        :return: The app information
        :raises ValueError: If app info is not found
        """
        from pynenc.app import AppInfo

        app_info_data = self.client.get(self.key.all_apps_info_key(self.app.app_id))

        if not app_info_data:
            raise ValueError(f"No app info found for app_id '{self.app.app_id}'")

        return AppInfo.from_json(app_info_data.decode())

    @staticmethod
    def discover_app_infos() -> dict[str, "AppInfo"]:
        """
        Retrieve all app information registered in this state backend.

        :return: Dictionary mapping app_id to app information
        """
        from pynenc.app import AppInfo

        redis_client = get_redis_client(ConfigRedis())
        # Scan for all app info keys
        pattern = Key.all_apps_info_key("*")
        all_keys = redis_client.keys(pattern)
        # Extract all available app IDs and Info
        result = {}
        for key in all_keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            app_id = key_str.split(":")[-1]  # Last part is app_id
            app_info_data = redis_client.get(key_str)
            if app_info_data:
                app_info = AppInfo.from_json(app_info_data.decode())
                result[app_id] = app_info
        return result

    def store_workflow_run(self, workflow_identity: "WorkflowIdentity") -> None:
        """
        Store a workflow run for tracking and monitoring.

        Maintains workflow type registry and specific workflow run instances.
        This enables monitoring of workflow types and their execution history.

        :param workflow_identity: The workflow identity to store
        """
        # Store the workflow JSON by workflow_id (unique)
        workflow_id_key = self.key.workflow_run_by_id(workflow_identity.workflow_id)
        self.client.set(workflow_id_key, workflow_identity.to_json())

        # Add workflow_type to the set of all workflow types
        workflow_types_key = self.key.workflow_types()
        self.client.sadd(workflow_types_key, workflow_identity.workflow_type)

        # Add workflow_id to the set for this workflow_type
        workflow_type_index_key = self.key.workflow_type_index(
            workflow_identity.workflow_type
        )
        self.client.sadd(workflow_type_index_key, workflow_identity.workflow_id)

    def get_all_workflow_types(self) -> Iterator[str]:
        """
        Retrieve all workflow types (workflow_task_ids) stored in this Redis state backend.

        :return: Iterator of workflow task IDs representing different workflow types (task_ids)
        """
        workflow_types_key = self.key.workflow_types()
        workflow_types = self.client.smembers(workflow_types_key)
        return (wt.decode() for wt in workflow_types)

    def get_all_workflow_runs(self) -> Iterator["WorkflowIdentity"]:
        """
        Retrieve workflow run identities from this Redis state backend.

        :return: Iterator of workflow identities for runs
        """
        # Get runs for all workflow types - iterate through known workflow types
        workflow_types_key = self.key.workflow_types()
        workflow_types = self.client.smembers(workflow_types_key)
        seen_ids = set()
        for wt in workflow_types:
            wt_str = wt.decode()
            workflow_type_index_key = self.key.workflow_type_index(wt_str)
            workflow_ids = self.client.smembers(workflow_type_index_key)
            for wid in workflow_ids:
                wid_str = wid.decode()
                if wid_str not in seen_ids:
                    seen_ids.add(wid_str)
                    workflow_id_key = self.key.workflow_run_by_id(wid_str)
                    wf_json = self.client.get(workflow_id_key)
                    if wf_json:
                        yield WorkflowIdentity.from_json(wf_json.decode())

    def get_workflow_runs(self, workflow_type: str) -> Iterator["WorkflowIdentity"]:
        """
        Retrieve workflow run identities from this Redis state backend with pagination.

        Uses configurable batch size to efficiently handle large datasets without
        overwhelming memory usage by processing data in manageable chunks.

        :param workflow_type: Filter for specific workflow type
        :return: Iterator of workflow identities for runs
        """
        workflow_type_index_key = self.key.workflow_type_index(workflow_type)
        workflow_ids = self.client.smembers(workflow_type_index_key)
        for wid in workflow_ids:
            workflow_id_key = self.key.workflow_run_by_id(wid.decode())
            wf_json = self.client.get(workflow_id_key)
            if wf_json:
                yield WorkflowIdentity.from_json(wf_json.decode())

    def store_workflow_sub_invocation(
        self, parent_workflow_id: str, sub_invocation_id: str
    ) -> None:
        """
        Store a sub-invocation ID that runs inside a parent workflow.

        :param parent_workflow_id: The workflow ID that contains the sub-invocation
        :param sub_invocation_id: The invocation ID of the task/sub-workflow running inside
        """
        sub_invocations_key = self.key.workflow_sub_invocations(parent_workflow_id)
        self.client.sadd(sub_invocations_key, sub_invocation_id)

    def get_workflow_sub_invocations(self, workflow_id: str) -> Iterator[str]:
        """
        Retrieve all sub-invocation IDs that run inside a specific workflow.

        :param workflow_id: The workflow ID to get sub-invocations for
        :return: Iterator of invocation IDs that run inside the workflow
        """
        sub_invocations_key = self.key.workflow_sub_invocations(workflow_id)
        sub_invocation_ids = self.client.smembers(sub_invocations_key)
        return (sid.decode() for sid in sub_invocation_ids)
