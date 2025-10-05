<p align="center">
  <img src="https://pynenc.org/assets/img/avatar-icon.png" alt="Pynenc Redis" width="300">
</p>
<h1 align="center">Pynenc Redis Plugin</h1>
<p align="center">
    <em>Redis backend implementation for Pynenc distributed task management</em>
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

**Main Documentation**: <a href="https://docs.pynenc.org" target="_blank">https://docs.pynenc.org</a>

**Source Code**: <a href="https://github.com/pynenc/pynenc-redis" target="_blank">https://github.com/pynenc/pynenc-redis</a>

**Pynenc Core**: <a href="https://github.com/pynenc/pynenc" target="_blank">https://github.com/pynenc/pynenc</a>

---

The `pynenc-redis` plugin provides Redis-based implementations for Pynenc's core components, enabling distributed task orchestration with Redis as the backend. This plugin offers production-ready implementations for orchestration, message brokering, state management, argument caching, and trigger systems.

## Overview

This plugin extends Pynenc with Redis-backed implementations for:

- **RedisOrchestrator**: Distributed task orchestration and coordination
- **RedisBroker**: Message queue and task distribution
- **RedisStateBackend**: Persistent state and result storage
- **RedisArgCache**: Efficient argument caching for large payloads
- **RedisTrigger**: Event-driven and scheduled task execution

## Installation

Install the plugin using pip:

```bash
pip install pynenc-redis
```

The plugin automatically registers itself with Pynenc when installed.

## Quick Start

### Using PynencBuilder (Recommended)

The easiest way to configure Redis components is using the `PynencBuilder`:

```python
from pynenc import PynencBuilder

# Basic Redis configuration
app = (
    PynencBuilder()
    .redis(url="redis://localhost:6379")
    .process_runner()
    .build()
)

@app.task
def add(x: int, y: int) -> int:
    return x + y
```

### Configuration Options

#### Full Redis Stack

Configure all Redis components with a single call:

```python
app = (
    PynencBuilder()
    .redis(url="redis://localhost:6379/0")  # With database number
    .multi_thread_runner()
    .build()
)
```

Or using individual parameters:

```python
app = (
    PynencBuilder()
    .redis(db=1)  # Uses default host/port with specific database
    .process_runner()
    .build()
)
```

#### Redis Argument Cache

Configure Redis-based argument caching for large payloads:

```python
app = (
    PynencBuilder()
    .redis(url="redis://localhost:6379")
    .redis_arg_cache(
        min_size_to_cache=1024,    # Cache arguments > 1KB
        local_cache_size=1000       # Keep 1000 entries in local cache
    )
    .build()
)
```

#### Redis Trigger System

Enable Redis-based triggers for scheduled and event-driven tasks:

```python
app = (
    PynencBuilder()
    .redis(url="redis://localhost:6379")
    .redis_trigger(
        scheduler_interval_seconds=60,  # Check every minute
        enable_scheduler=True
    )
    .build()
)
```

### Using pyproject.toml

Alternatively, configure Redis components in your `pyproject.toml`:

```toml
[tool.pynenc]
app_id = "my_app"
orchestrator_cls = "RedisOrchestrator"
broker_cls = "RedisBroker"
state_backend_cls = "RedisStateBackend"
arg_cache_cls = "RedisArgCache"
trigger_cls = "RedisTrigger"
runner_cls = "ProcessRunner"

[tool.pynenc.redis]
redis_url = "redis://localhost:6379/0"
# Or use individual parameters:
# redis_host = "localhost"
# redis_port = 6379
# redis_db = 0
```

## Plugin Components

### RedisOrchestrator

Manages task dependencies and execution flow using Redis:

- Atomic operations for task state transitions
- Efficient dependency tracking
- Batch processing for high-throughput scenarios
- Connection pooling and automatic reconnection

### RedisBroker

Distributes tasks across workers:

- FIFO task queue with blocking pop operations
- Efficient batch routing
- Configurable timeouts and retry mechanisms
- Support for task priorities

### RedisStateBackend

Persists task state and results:

- Invocation history and status tracking
- Result storage with TTL support
- Workflow data persistence
- App discovery and registration

### RedisArgCache

Optimizes handling of large arguments:

- Automatic caching based on size thresholds
- LRU eviction for memory management
- Shared cache across processes
- Fingerprint-based deduplication

### RedisTrigger

Enables event-driven task execution:

- Cron-based scheduling
- Task status change triggers
- Result-based triggers
- Custom event handling

## Connection Configuration

The plugin supports multiple ways to configure Redis connections:

### URL-based (Recommended)

```python
.redis(url="redis://localhost:6379/0")
.redis(url="redis://:password@localhost:6379/0")
.redis(url="rediss://localhost:6380/0")  # SSL/TLS
```

### Parameter-based

```python
.redis(db=1)  # Uses REDIS_HOST and REDIS_PORT from config/env
```

### Environment Variables

```bash
PYNENC__REDIS__REDIS_URL="redis://localhost:6379/0"
# Or individual parameters:
PYNENC__REDIS__REDIS_HOST="localhost"
PYNENC__REDIS__REDIS_PORT=6379
PYNENC__REDIS__REDIS_DB=0
```

## Advanced Features

### Connection Resilience

The plugin includes robust connection handling:

- Automatic reconnection with exponential backoff
- Configurable retry mechanisms
- Socket timeouts and health checks
- Connection pooling

### Performance Optimization

- Batch processing for parallel task creation
- Pipeline operations for reduced network overhead
- Local caching to minimize Redis queries
- Efficient serialization strategies

### Monitoring Integration

Works seamlessly with Pynenc's monitoring interface:

```bash
pynenc --app your_app monitor
```

## Development and Testing

The plugin supports both development and production modes:

### Development Mode

```python
# Synchronous execution for testing
app = (
    PynencBuilder()
    .redis(url="redis://localhost:6379")
    .dev_mode(force_sync_tasks=True)
    .build()
)
```

### Integration Testing

Integration tests use testcontainers to automatically manage Redis instances. Docker must be installed and running for integration tests to execute.

Run tests with:

```bash
poetry run pytest tests/integration/
```

## Requirements

- Python >= 3.11.6
- Pynenc >= 0.0.24
- Redis >= 4.6.0
- A running Redis server

## Documentation

For comprehensive documentation on Pynenc and its features, visit:

- **Main Documentation**: https://docs.pynenc.org
- **API Reference**: https://docs.pynenc.org/apidocs/
- **Usage Examples**: https://github.com/pynenc/samples

## Contributing

Contributions are welcome! Please see the [Contributing Guide](CONTRIBUTING.md) for details.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- **Issues**: https://github.com/pynenc/pynenc-redis/issues
- **Discussions**: https://github.com/pynenc/pynenc/discussions
- **Main Project**: https://github.com/pynenc/pynenc
