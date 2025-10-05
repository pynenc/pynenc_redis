"""
Redis plugin builder extensions for Pynenc.

This module contains the Redis-specific builder methods that will be moved to the
pynenc-redis plugin package. It demonstrates how plugins can extend PynencBuilder
with backend-specific functionality using the entry points system.

Key components:
- RedisBuilderPlugin: Plugin class that registers Redis methods
- redis(): Main method for full Redis stack configuration
- redis_arg_cache(): Redis-specific argument caching method
- redis_trigger(): Redis-specific trigger system method
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pynenc.builder import PynencBuilder


class RedisBuilderPlugin:
    """
    Redis plugin that provides builder methods for Redis backend configuration.

    This class will be moved to the pynenc-redis plugin package and registered
    via entry points to extend PynencBuilder with Redis-specific methods.
    """

    @staticmethod
    def register_builder_methods(builder_class: type["PynencBuilder"]) -> None:
        """
        Register Redis builder methods with PynencBuilder.

        This method is called automatically when the plugin is discovered via entry points.

        :param type["PynencBuilder"] builder_class: The PynencBuilder class to extend
        """
        # Register main Redis method
        builder_class.register_plugin_method("redis", redis)

        # Register component-specific methods
        builder_class.register_plugin_method("redis_arg_cache", redis_arg_cache)
        builder_class.register_plugin_method("redis_trigger", redis_trigger)

        # Register configuration validator
        builder_class.register_plugin_validator(validate_redis_config)


def redis(
    builder: "PynencBuilder", url: str | None = None, db: int | None = None
) -> "PynencBuilder":
    """
    Configure Redis components for the Pynenc application.

    This sets up all Redis-related components (orchestrator, broker, state backend,
    and argument cache) to use Redis as their backend.

    :param PynencBuilder builder: The PynencBuilder instance
    :param str | None url: The Redis URL to connect to. If specified, overrides all other connection
        parameters including host, port, and db
    :param int | None db: The Redis database number to use. Only valid when url is not provided.
        If url is provided, the database should be specified in the URL itself
    :return: The builder instance for method chaining
    :raises ValueError: If both url and db are provided, since url takes precedence
    """
    if url and db is not None:
        raise ValueError(
            "Cannot specify both 'url' and 'db' parameters. "
            "When using 'url', specify the database in the URL (e.g., 'redis://host:port/db'). "
            "The 'url' parameter overrides all other connection settings."
        )

    if url:
        builder._config["redis_url"] = url
    elif db is not None:
        builder._config["redis_db"] = db

    builder._config.update(
        {
            "orchestrator_cls": "RedisOrchestrator",
            "broker_cls": "RedisBroker",
            "state_backend_cls": "RedisStateBackend",
            "arg_cache_cls": "RedisArgCache",
            "trigger_cls": "RedisTrigger",
        }
    )
    builder._plugin_components.add("redis")
    builder._using_memory_components = False
    return builder


def redis_arg_cache(
    builder: "PynencBuilder",
    min_size_to_cache: int = 1024,
    local_cache_size: int = 1024,
) -> "PynencBuilder":
    """
    Configure Redis-based argument caching.

    This method configures the Redis argument cache with the specified parameters.
    It requires that Redis components have been configured either through redis()
    or through configuration files.

    :param PynencBuilder builder: The PynencBuilder instance
    :param int min_size_to_cache: Minimum string length (in characters) required to cache an argument.
        Arguments smaller than this size will be passed directly. Default is 1024 characters (roughly 1KB)
    :param int local_cache_size: Maximum number of items to cache locally. Default is 1024
    :return: The builder instance for method chaining
    :raises ValueError: If Redis configuration is not present
    """
    if "redis" not in builder._plugin_components and "redis_url" not in builder._config:
        raise ValueError(
            "Redis arg cache requires redis configuration. Call redis() first."
        )

    builder._config.update(
        {
            "arg_cache_cls": "RedisArgCache",
            "min_size_to_cache": min_size_to_cache,
            "local_cache_size": local_cache_size,
        }
    )
    builder._plugin_components.add("redis")
    return builder


def redis_trigger(
    builder: "PynencBuilder",
    scheduler_interval_seconds: int = 60,
    enable_scheduler: bool = True,
) -> "PynencBuilder":
    """
    Configure Redis-based trigger system.

    This method configures the Redis trigger system with the specified parameters.
    It requires that Redis components have been configured either through redis()
    or through configuration files.

    :param PynencBuilder builder: The PynencBuilder instance
    :param int scheduler_interval_seconds: Interval in seconds for the scheduler to check for time-based triggers.
        Default is 60 seconds (1 minute)
    :param bool enable_scheduler: Whether to enable the scheduler for time-based triggers.
        Default is True
    :return: The builder instance for method chaining
    :raises ValueError: If Redis configuration is not present
    """
    if "redis" not in builder._plugin_components and "redis_url" not in builder._config:
        raise ValueError(
            "Redis trigger requires redis configuration. Call redis() first."
        )

    builder._config.update(
        {
            "trigger_cls": "RedisTrigger",
            "scheduler_interval_seconds": scheduler_interval_seconds,
            "enable_scheduler": enable_scheduler,
        }
    )
    builder._plugin_components.add("redis")
    return builder


def validate_redis_config(config: dict[str, Any]) -> None:
    """
    Validate Redis plugin configuration.

    This function validates that Redis configuration is present when Redis components
    are being used. It's called automatically during the build process.

    :param dict[str, Any] config: The builder configuration dictionary
    :raises ValueError: If Redis configuration is invalid
    """
    uses_redis = any(
        config.get(key, "").startswith("Redis")
        for key in [
            "orchestrator_cls",
            "broker_cls",
            "state_backend_cls",
            "arg_cache_cls",
            "trigger_cls",
        ]
    )

    if uses_redis:
        # Ensure Redis connection configuration is present
        has_redis_config = any(
            [
                config.get("redis_url"),
                config.get("redis_host"),
                config.get("redis_db") is not None,
            ]
        )

        if not has_redis_config:
            raise ValueError(
                "Redis components require connection configuration. "
                "Set redis_url, redis_host, or call redis() with connection parameters."
            )
