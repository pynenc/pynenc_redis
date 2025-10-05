from cistell import ConfigField
from pynenc.conf.config_orchestrator import ConfigOrchestrator

from pynenc_redis.conf.config_redis import ConfigRedis


class ConfigOrchestratorRedis(ConfigOrchestrator, ConfigRedis):
    """Specific Configuration for the Redis Orchestrator

    :cvar ConfigField[int] max_pending_resolution_threads:
        This integer value controls the maximum number of worker threads used by the
        ThreadPoolExecutor for resolving PENDING status invocations. When an invocation
        enters PENDING state, a background thread is used to check if it needs to be
        resolved (when the pending timeout expires). This limits the number of concurrent
        Redis connections used for this process, helping to prevent connection pool
        exhaustion while still allowing enough parallelism to handle many pending
        invocations. Default is 50 threads.

    :cvar ConfigField[int] redis_retry_max_attempts:
        Maximum number of retry attempts for Redis operations that encounter specific
        exceptions such as StatusNotFound. After this many failed attempts, the
        operation will raise the exception. Default is 3 attempts.

    :cvar ConfigField[float] redis_retry_base_delay_sec:
        Base delay in seconds between retry attempts. The retry system uses
        exponential backoff, where each retry waits progressively longer
        (base_delay * 2^attempt). Default is 0.1 seconds.

    :cvar ConfigField[float] redis_retry_max_delay_sec:
        Maximum delay between retry attempts in seconds, regardless of the
        exponential backoff calculation. This ensures that even after many
        retries, the delay won't exceed a reasonable upper bound. Default is 1.0 second.
    """

    max_pending_resolution_threads = ConfigField(50)
    redis_retry_max_attempts = ConfigField(3)
    redis_retry_base_delay_sec = ConfigField(0.1)
    redis_retry_max_delay_sec = ConfigField(1.0)
