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

    def route_invocation(self, invocation_id: "InvocationId") -> None:
        """Route an invocation by sending it to the Redis queue."""
        self.client.rpush(self.key.default_queue(), invocation_id)
        self.app.logger.debug(f"Routed invocation {invocation_id} to Redis queue")

    def route_invocations(self, invocation_ids: list["InvocationId"]) -> None:
        """Routes multiple invocations at once using Redis pipeline for better performance."""
        if not invocation_ids:
            return

        with self.client.pipeline() as pipe:
            for invocation_id in invocation_ids:
                pipe.rpush(self.key.default_queue(), invocation_id)
            pipe.execute()
        self.app.logger.debug(
            f"Routed {len(invocation_ids)} invocations to Redis queue"
        )

    def retrieve_invocation(self) -> "InvocationId | None":
        """Retrieve the next invocation from the Redis queue."""
        if msg := self.client.blpop(
            self.key.default_queue(), timeout=self.app.broker.conf.queue_timeout_sec
        ):
            # blpop returns tuple of (key, value)
            return InvocationId(msg[1].decode())
        return None

    def count_invocations(self) -> int:
        """
        Get the number of invocations in the Redis queue.

        This method queries the Redis queue for the number of messages currently in the queue.

        :return: The number of invocations in the queue.
        """
        return self.client.llen(self.key.default_queue())

    def purge(self) -> None:
        """
        Purge all invocations from the Redis queue.

        This method delegates to the `purge` method of the RedisQueue to clear all messages.
        """
        self.app.logger.debug("Purging all invocations from Redis queue")
        self.key.purge(self.client)
