"""Unit tests for RedisBuilderPlugin and its builder functions."""

from unittest.mock import MagicMock

import pytest

from pynenc_redis.builder import (
    RedisBuilderPlugin,
    redis,
    redis_client_data_store,
    redis_trigger,
    validate_redis_config,
)


@pytest.fixture
def builder() -> MagicMock:
    """Fake PynencBuilder with the attributes used by redis builder functions."""
    b = MagicMock()
    b._config = {}
    b._plugin_components = set()
    b._using_memory_components = True
    return b


# --- RedisBuilderPlugin.register_builder_methods ---


def test_register_builder_methods_should_register_all_methods_and_validator() -> None:
    """Test that all plugin methods and the validator are registered."""
    builder_class = MagicMock()
    RedisBuilderPlugin.register_builder_methods(builder_class)

    builder_class.register_plugin_method.assert_any_call("redis", redis)
    builder_class.register_plugin_method.assert_any_call(
        "redis_client_data_store", redis_client_data_store
    )
    builder_class.register_plugin_method.assert_any_call("redis_trigger", redis_trigger)
    builder_class.register_plugin_validator.assert_called_once_with(
        validate_redis_config
    )


# --- redis() ---


def test_redis_should_configure_all_components(builder: MagicMock) -> None:
    result = redis(builder)

    assert result is builder
    assert builder._config["orchestrator_cls"] == "RedisOrchestrator"
    assert builder._config["broker_cls"] == "RedisBroker"
    assert builder._config["state_backend_cls"] == "RedisStateBackend"
    assert builder._config["client_data_store_cls"] == "RedisClientDataStore"
    assert builder._config["trigger_cls"] == "RedisTrigger"
    assert "redis" in builder._plugin_components
    assert builder._using_memory_components is False


def test_redis_should_set_url_when_provided(builder: MagicMock) -> None:
    redis(builder, url="redis://myhost:6379/1")
    assert builder._config["redis_url"] == "redis://myhost:6379/1"


def test_redis_should_set_db_when_provided(builder: MagicMock) -> None:
    redis(builder, db=5)
    assert builder._config["redis_db"] == 5


def test_redis_should_raise_when_both_url_and_db_provided(
    builder: MagicMock,
) -> None:
    with pytest.raises(ValueError, match="Cannot specify both"):
        redis(builder, url="redis://localhost:6379/0", db=3)


# --- redis_client_data_store() ---


def test_redis_client_data_store_should_configure_defaults(
    builder: MagicMock,
) -> None:
    builder._plugin_components.add("redis")

    result = redis_client_data_store(builder)

    assert result is builder
    assert builder._config["client_data_store_cls"] == "RedisClientDataStore"
    assert builder._config["min_size_to_cache"] == 1024
    assert builder._config["local_cache_size"] == 1024


def test_redis_client_data_store_should_accept_custom_params(
    builder: MagicMock,
) -> None:
    builder._plugin_components.add("redis")

    redis_client_data_store(builder, min_size_to_cache=512, local_cache_size=256)

    assert builder._config["min_size_to_cache"] == 512
    assert builder._config["local_cache_size"] == 256


def test_redis_client_data_store_should_raise_without_redis(
    builder: MagicMock,
) -> None:
    with pytest.raises(ValueError, match="requires redis configuration"):
        redis_client_data_store(builder)


def test_redis_client_data_store_should_work_with_redis_url_in_config(
    builder: MagicMock,
) -> None:
    builder._config["redis_url"] = "redis://localhost:6379/0"
    redis_client_data_store(builder)
    assert builder._config["client_data_store_cls"] == "RedisClientDataStore"


# --- redis_trigger() ---


def test_redis_trigger_should_configure_defaults(builder: MagicMock) -> None:
    builder._plugin_components.add("redis")

    result = redis_trigger(builder)

    assert result is builder
    assert builder._config["trigger_cls"] == "RedisTrigger"
    assert builder._config["scheduler_interval_seconds"] == 60
    assert builder._config["enable_scheduler"] is True


def test_redis_trigger_should_accept_custom_params(builder: MagicMock) -> None:
    builder._plugin_components.add("redis")

    redis_trigger(builder, scheduler_interval_seconds=30, enable_scheduler=False)

    assert builder._config["scheduler_interval_seconds"] == 30
    assert builder._config["enable_scheduler"] is False


def test_redis_trigger_should_raise_without_redis(builder: MagicMock) -> None:
    with pytest.raises(ValueError, match="requires redis configuration"):
        redis_trigger(builder)


def test_redis_trigger_should_work_with_redis_url_in_config(
    builder: MagicMock,
) -> None:
    builder._config["redis_url"] = "redis://localhost:6379/0"
    redis_trigger(builder)
    assert builder._config["trigger_cls"] == "RedisTrigger"


# --- validate_redis_config() ---


def test_validate_should_pass_when_no_redis_components() -> None:
    validate_redis_config({"orchestrator_cls": "MemoryOrchestrator"})


def test_validate_should_pass_with_redis_url() -> None:
    validate_redis_config(
        {
            "orchestrator_cls": "RedisOrchestrator",
            "redis_url": "redis://localhost:6379/0",
        }
    )


def test_validate_should_pass_with_redis_host() -> None:
    validate_redis_config(
        {
            "broker_cls": "RedisBroker",
            "redis_host": "localhost",
        }
    )


def test_validate_should_pass_with_redis_db() -> None:
    validate_redis_config(
        {
            "state_backend_cls": "RedisStateBackend",
            "redis_db": 0,
        }
    )


def test_validate_should_raise_when_redis_cls_without_connection_config() -> None:
    with pytest.raises(ValueError, match="require connection configuration"):
        validate_redis_config({"orchestrator_cls": "RedisOrchestrator"})
