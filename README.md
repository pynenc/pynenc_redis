<p align="center">
  <img src="https://pynenc.org/assets/img/pynenc_logo.png" alt="Pynenc" width="300">
</p>
<h1 align="center">Pynenc Redis Plugin</h1>
<p align="center">
    <em>Full-stack Redis backend for Pynenc distributed task orchestration</em>
</p>
<p align="center">
    <a href="https://pypi.org/project/pynenc-redis" target="_blank">
        <img src="https://img.shields.io/pypi/v/pynenc-redis?color=%2334D058&label=pypi%20package" alt="Package version">
    </a>
    <a href="https://pypi.org/project/pynenc-redis" target="_blank">
        <img src="https://img.shields.io/pypi/pyversions/pynenc-redis.svg?color=%2334D058" alt="Supported Python versions">
    </a>
    <a href="https://github.com/pynenc/pynenc-redis/commits/main">
        <img src="https://img.shields.io/github/last-commit/pynenc/pynenc-redis" alt="GitHub last commit">
    </a>
    <a href="https://github.com/pynenc/pynenc-redis/blob/main/LICENSE">
        <img src="https://img.shields.io/github/license/pynenc/pynenc-redis" alt="GitHub license">
    </a>
</p>

---

**Documentation**: <a href="https://pynenc-redis.readthedocs.io" target="_blank">https://pynenc-redis.readthedocs.io</a>

**Pynenc Documentation**: <a href="https://docs.pynenc.org" target="_blank">https://docs.pynenc.org</a>

**Source Code**: <a href="https://github.com/pynenc/pynenc-redis" target="_blank">https://github.com/pynenc/pynenc-redis</a>

---

The `pynenc-redis` plugin provides all five Pynenc backend components running on Redis, enabling production-ready distributed task orchestration with a single infrastructure dependency.

## Components

| Component             | Class                  | Role                                                  |
| --------------------- | ---------------------- | ----------------------------------------------------- |
| **Orchestrator**      | `RedisOrchestrator`    | Distributed status tracking & blocking control        |
| **Broker**            | `RedisBroker`          | FIFO message queue via Redis lists with blocking pop  |
| **State Backend**     | `RedisStateBackend`    | Persistent state, results, exceptions & workflow data |
| **Client Data Store** | `RedisClientDataStore` | Argument caching for large serialized payloads        |
| **Trigger**           | `RedisTrigger`         | Event-driven & cron-based task scheduling             |

## Installation

```bash
pip install pynenc-redis
```

The plugin registers itself automatically via Python entry points when installed.

## Quick Start

```python
from pynenc import PynencBuilder

app = (
    PynencBuilder()
    .app_id("my_app")
    .redis(url="redis://localhost:6379")  # all components on Redis
    .process_runner()
    .build()
)

@app.task
def add(x: int, y: int) -> int:
    return x + y

result = add(1, 2).result  # 3
```

`.redis()` registers every component at once. Start a runner with:

```bash
pynenc --app=tasks.app runner start
```

For a complete working example with Docker Compose and multiple workers, see the [basic_redis_example](https://github.com/pynenc/samples/tree/main/basic_redis_example) in the pynenc samples repository.

## Configuration

### Builder Parameters

```python
# URL-based (recommended)
app = (
    PynencBuilder()
    .app_id("my_app")
    .redis(url="redis://localhost:6379/0")
    .multi_thread_runner(min_threads=2, max_threads=8)
    .build()
)

# Database number only (uses host/port from env or defaults)
app = (
    PynencBuilder()
    .app_id("my_app")
    .redis(db=1)
    .process_runner()
    .build()
)
```

### Component-Specific Configuration

```python
app = (
    PynencBuilder()
    .app_id("my_app")
    .redis(url="redis://localhost:6379")
    .redis_client_data_store(
        min_size_to_cache=1024,   # cache arguments > 1KB
        local_cache_size=1000,    # local LRU cache entries
    )
    .redis_trigger(
        scheduler_interval_seconds=60,
        enable_scheduler=True,
    )
    .build()
)
```

### Environment Variables

```bash
PYNENC__REDIS__REDIS_URL="redis://localhost:6379/0"
# Or individual parameters:
PYNENC__REDIS__REDIS_HOST="localhost"
PYNENC__REDIS__REDIS_PORT=6379
PYNENC__REDIS__REDIS_DB=0
```

### Connection URLs

```python
.redis(url="redis://localhost:6379/0")           # Standard
.redis(url="redis://:password@localhost:6379/0")  # With password
.redis(url="rediss://localhost:6380/0")           # SSL/TLS
```

## Requirements

- Python >= 3.11
- Pynenc >= 0.1.0
- redis >= 4.6.0
- A running Redis server

## Related Plugins

- **[pynenc-mongodb](https://github.com/pynenc/pynenc-mongodb)**: Full-stack MongoDB backend
- **[pynenc-rabbitmq](https://github.com/pynenc/pynenc-rabbitmq)**: RabbitMQ broker (pairs with Redis for state/orchestrator/triggers)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
