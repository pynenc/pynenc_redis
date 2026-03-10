from functools import cached_property
from typing import TYPE_CHECKING

import redis
from pynenc.client_data_store.base_client_data_store import BaseClientDataStore

from pynenc_redis.conf.config_client_data_store import ConfigClientDataStoreRedis
from pynenc_redis.util.mongo_client import get_redis_client
from pynenc_redis.util.redis_keys import Key

if TYPE_CHECKING:
    from pynenc.app import Pynenc


class RedisClientDataStore(BaseClientDataStore):
    """
    Redis-based implementation of argument caching.

    Stores serialized arguments in Redis for distributed access.
    Suitable for production use as cache is shared across all processes.
    """

    def __init__(self, app: "Pynenc") -> None:
        super().__init__(app)
        self._client: redis.Redis | None = None
        self.key = Key(app.app_id, "client_data_store")

    @property
    def client(self) -> redis.Redis:
        """Lazy initialization of Redis client"""
        if self._client is None:
            self._client = get_redis_client(self.conf)
        return self._client

    @cached_property
    def conf(self) -> ConfigClientDataStoreRedis:
        """Get Redis-specific configuration."""
        return ConfigClientDataStoreRedis(
            config_values=self.app.config_values,
            config_filepath=self.app.config_filepath,
        )

    def _store(self, key: str, value: str) -> None:
        """
        Store a value in Redis.

        :param str key: The cache key
        :param str value: The serialized value to cache
        """
        self.client.set(self.key.client_data_store(key), value)

    def _retrieve(self, key: str) -> str:
        """
        Retrieve a value from Redis.

        :param str key: The cache key
        :return: The cached serialized value
        :raises KeyError: If key not found in cache
        """
        if value := self.client.get(self.key.client_data_store(key)):
            return value.decode()
        raise KeyError(f"Cache key not found: {key}")

    def _purge(self) -> None:
        """Clear all cached arguments from Redis."""
        self.key.purge(self.client)
