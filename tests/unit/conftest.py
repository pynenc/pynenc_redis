from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import fakeredis
import pytest
from pynenc import PynencBuilder

from pynenc_redis.util import mongo_client

if TYPE_CHECKING:
    from collections.abc import Generator

    from pynenc.app import Pynenc


class MockLock:
    """
    Dummy lock implementation for testing with fakeredis.
    Simulates acquire/release with token logic to avoid Redis scripting.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.locked = False
        self.token = None

    def acquire(self, blocking: bool = True, **kwargs: Any) -> bool:
        if not self.locked:
            self.locked = True
            self.token = "mock-token"  # type: ignore
            return True
        return False

    def release(self, expected_token: str | None = None) -> None:
        # Accept expected_token for compatibility, ignore its value
        self.locked = False
        self.token = None

    def do_release(self, expected_token: str | None = None) -> None:
        # Called internally by redis-py lock release
        self.release(expected_token)


@pytest.fixture(scope="function")
def app_instance() -> "Generator['Pynenc', None, None]":
    """
    Fixture that provides a Pynenc app instance with a Redis backend,
    using fakeredis to mock Redis for unit tests.

    :return: Generator yielding a Pynenc app instance with Redis backend
    """
    lock_registry: dict[str, MockLock] = {}

    def mock_lock_factory(name: str, *args: Any, **kwargs: Any) -> MockLock:
        # Return the same lock instance for the same key to simulate contention
        if name not in lock_registry:
            lock_registry[name] = MockLock(*args, **kwargs)
        return lock_registry[name]

    with (
        patch.object(
            mongo_client, "get_redis_client", return_value=fakeredis.FakeRedis()
        ),
        patch("redis.ConnectionPool.from_url", lambda *a, **kw: None),
        patch("redis.Redis", fakeredis.FakeRedis),
        patch("redis.lock.Lock", MockLock),
        patch.object(fakeredis.FakeRedis, "lock", mock_lock_factory),
    ):
        app = PynencBuilder().redis(url="redis://localhost:6379/0").build()
        yield app  # type: ignore
