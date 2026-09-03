from collections.abc import Sequence
from functools import cached_property
from typing import TYPE_CHECKING

import redis
from pynenc.broker.base_broker import BaseBroker
from pynenc.identifiers.invocation_id import InvocationId

from pynenc_redis.conf.config_broker import ConfigBrokerRedis
from pynenc_redis.util.mongo_client import get_redis_client
from pynenc_redis.util.redis_keys import Key

if TYPE_CHECKING:
    from pynenc.app import Pynenc


class RedisBroker(BaseBroker):
    """
    A Redis-backed implementation of the BaseBroker.

    This subclass of BaseBroker implements the abstract methods for routing,
    retrieving, and purging invocations using Redis as the message broker.
    It is suitable for production environments where robustness and scalability
    are required.

    :param Pynenc app: A reference to the Pynenc application.
    """

    def __init__(self, app: "Pynenc") -> None:
        super().__init__(app)
        self._client: redis.Redis | None = None
        self.key = Key(app.app_id, "broker")

    @property
    def client(self) -> redis.Redis:
        """Lazy initialization of Redis client"""
        if self._client is None:
            self.app.logger.debug("Lazy initializing Redis client for queue")
            self._client = get_redis_client(self.conf)
        return self._client

    @cached_property
    def conf(self) -> ConfigBrokerRedis:
        return ConfigBrokerRedis(
            config_values=self.app.config_values,
            config_filepath=self.app.config_filepath,
        )

    _MAX_SEQUENCE = 2**63 - 1

    @classmethod
    def _queue_member(cls, sequence: int, invocation_id: "InvocationId") -> str:
        """Encode FIFO order into the member used for equal Redis scores."""
        if sequence > cls._MAX_SEQUENCE:
            raise OverflowError("Redis broker sequence exhausted")
        reverse_sequence = cls._MAX_SEQUENCE - sequence
        return f"{reverse_sequence:019d}:{invocation_id}"

    @staticmethod
    def _invocation_id_from_member(member: bytes | str) -> InvocationId:
        """Decode an invocation ID from a Redis sorted-set member."""
        value = member.decode() if isinstance(member, bytes) else member
        _, invocation_id = value.split(":", 1)
        return InvocationId(invocation_id)

    def _route_invocation(
        self, invocation_id: "InvocationId", queue_name: str, priority: float
    ) -> None:
        """Route an invocation through a priority-ordered Redis sorted set."""
        sequence = int(self.client.incr(self.key.broker_sequence()))
        member = self._queue_member(sequence, invocation_id)
        self.client.zadd(self.key.broker_queue(queue_name), {member: priority})
        self.app.logger.debug(
            f"Routed invocation {invocation_id} to Redis queue:{queue_name} "
            f"priority:{priority}"
        )

    def _route_invocations(
        self,
        invocation_ids: Sequence["InvocationId"],
        queue_name: str,
        priority: float,
    ) -> None:
        """Routes multiple invocations at once using Redis pipeline for better performance."""
        if not invocation_ids:
            return

        last_sequence = int(
            self.client.incrby(self.key.broker_sequence(), len(invocation_ids))
        )
        first_sequence = last_sequence - len(invocation_ids) + 1
        with self.client.pipeline() as pipe:
            for offset, invocation_id in enumerate(invocation_ids):
                member = self._queue_member(first_sequence + offset, invocation_id)
                pipe.zadd(
                    self.key.broker_queue(queue_name),
                    {member: priority},
                )
            pipe.execute()
        self.app.logger.debug(
            f"Routed {len(invocation_ids)} invocations to Redis queue:{queue_name}"
        )

    def retrieve_invocation(
        self, queue_name: str | None = None
    ) -> "InvocationId | None":
        """Retrieve the next invocation from the Redis queue."""
        queue = self.conf.queues[0] if queue_name is None else queue_name
        self._validate_queue_names((queue,))
        if messages := self.client.zpopmax(self.key.broker_queue(queue), count=1):
            return self._invocation_id_from_member(messages[0][0])
        return None

    def count_invocations(self, queue_names: Sequence[str] | None = None) -> int:
        """
        Get the number of invocations in the Redis queue.

        This method queries the Redis queue for the number of messages currently in the queue.

        :return: The number of invocations in the queue.
        """
        queues = self.conf.queues if queue_names is None else tuple(queue_names)
        self._validate_queue_names(queues)
        return sum(self.client.zcard(self.key.broker_queue(queue)) for queue in queues)

    def purge(self) -> None:
        """
        Purge all invocations from the Redis queue.

        This method delegates to the `purge` method of the RedisQueue to clear all messages.
        """
        self.app.logger.debug("Purging all invocations from Redis queue")
        self.key.purge(self.client)
