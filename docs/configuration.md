# Configuration Reference

All settings can be provided via the builder, environment variables, or YAML config files.
See the [Pynenc configuration guide](https://pynenc.readthedocs.io/en/latest/configuration/index.html) for the general mechanism.

## Connection Settings — `ConfigRedis`

Shared by all Redis-backed components.

| Setting                            | Type    | Default       | Description                                                              |
| ---------------------------------- | ------- | ------------- | ------------------------------------------------------------------------ |
| `redis_url`                        | `str`   | `""`          | Full Redis URL, e.g. `redis://localhost:6379/0`. Overrides host/port/db. |
| `redis_host`                       | `str`   | `"localhost"` | Redis server hostname                                                    |
| `redis_port`                       | `int`   | `6379`        | Redis server port                                                        |
| `redis_db`                         | `int`   | `0`           | Redis database number (0–15)                                             |
| `redis_username`                   | `str`   | `""`          | Username for Redis ACL authentication                                    |
| `redis_password`                   | `str`   | `""`          | Password for Redis authentication                                        |
| `socket_timeout`                   | `float` | `5.0`         | Timeout for socket read/write operations (seconds)                       |
| `socket_connect_timeout`           | `float` | `5.0`         | Timeout for the initial connection (seconds)                             |
| `health_check_interval`            | `int`   | `30`          | Interval between connection health checks (seconds)                      |
| `max_connection_attempts`          | `int`   | `3`           | Maximum connection retry attempts                                        |
| `redis_pool_max_connections`       | `int`   | `100`         | Maximum connections in the pool                                          |
| `redis_pool_health_check_interval` | `float` | `30.0`        | Health check interval for pooled connections (seconds)                   |

## Orchestrator Settings — `ConfigOrchestratorRedis`

| Setting                          | Type    | Default | Description                                          |
| -------------------------------- | ------- | ------- | ---------------------------------------------------- |
| `max_pending_resolution_threads` | `int`   | `50`    | Thread pool size for resolving PENDING invocations   |
| `redis_retry_base_delay_sec`     | `float` | `0.1`   | Base delay for exponential backoff retries (seconds) |
| `redis_retry_max_delay_sec`      | `float` | `1.0`   | Maximum delay between retries (seconds)              |

## State Backend Settings — `ConfigStateBackendRedis`

| Setting                 | Type  | Default | Description                                              |
| ----------------------- | ----- | ------- | -------------------------------------------------------- |
| `pagination_batch_size` | `int` | `100`   | Batch size for paginating through invocation collections |

## Environment Variables

Every setting maps to `PYNENC_{SETTING_UPPERCASE}`:

```bash
export PYNENC_REDIS_URL="redis://localhost:6379/0"
export PYNENC_REDIS_PASSWORD="mysecret"
export PYNENC_REDIS_POOL_MAX_CONNECTIONS=50
export PYNENC_MAX_PENDING_RESOLUTION_THREADS=25
```

## YAML Configuration

```yaml
# pynenc.yaml
redis_url: "redis://localhost:6379/0"
redis_pool_max_connections: 50
max_pending_resolution_threads: 25
pagination_batch_size: 200
```
