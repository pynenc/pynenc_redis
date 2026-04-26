# Installation & Quick Start

## Install

```bash
pip install pynenc-redis
```

The plugin registers itself automatically via the `pynenc.plugins` entry point — no extra configuration needed.

## Quick Start

### PynencBuilder (Recommended)

```python
from pynenc import PynencBuilder

app = (
    PynencBuilder()
    .app_id("my_app")
    .redis(url="redis://localhost:6379")
    .process_runner()
    .build()
)

@app.task
def add(x: int, y: int) -> int:
    return x + y

result = add(1, 2).result  # 3
```

For a complete working example with Docker Compose and multiple workers, see the [basic_redis_example](https://github.com/pynenc/samples/tree/main/basic_redis_example) in the pynenc samples repository.

### Environment Variables

```bash
PYNENC_REDIS_URL=redis://localhost:6379 pynenc worker
```

### Docker Compose

```yaml
services:
  redis:
    image: redis:7
    ports: ["6379:6379"]

  worker:
    build: .
    environment:
      PYNENC_REDIS_URL: redis://redis:6379
    depends_on: [redis]
    command: pynenc worker
```

## Builder Methods

### `.redis(url, db)`

Configure all Redis components at once — orchestrator, broker, state backend, client data store, and trigger.

```python
# Using URL (recommended)
builder.redis(url="redis://localhost:6379/0")

# Using database number with default host/port
builder.redis(db=1)
```

| Parameter | Type          | Description                                                |
| --------- | ------------- | ---------------------------------------------------------- |
| `url`     | `str \| None` | Full Redis URL. Overrides all other connection parameters. |
| `db`      | `int \| None` | Redis database number. Cannot be used together with `url`. |

### `.redis_client_data_store(min_size_to_cache, local_cache_size)`

Override argument cache settings. Requires `.redis()` to be called first.

```python
builder.redis(url="redis://localhost:6379").redis_client_data_store(
    min_size_to_cache=2048,
    local_cache_size=500,
)
```

| Parameter           | Type  | Default | Description                                        |
| ------------------- | ----- | ------- | -------------------------------------------------- |
| `min_size_to_cache` | `int` | `1024`  | Minimum serialized size (chars) to trigger caching |
| `local_cache_size`  | `int` | `1024`  | Maximum items kept in the local in-process cache   |

### `.redis_trigger(scheduler_interval_seconds, enable_scheduler)`

Fine-tune the trigger scheduler. Requires `.redis()` to be called first.

```python
builder.redis(url="redis://localhost:6379").redis_trigger(
    scheduler_interval_seconds=30,
)
```

| Parameter                    | Type   | Default | Description                                            |
| ---------------------------- | ------ | ------- | ------------------------------------------------------ |
| `scheduler_interval_seconds` | `int`  | `60`    | How often the scheduler checks for time-based triggers |
| `enable_scheduler`           | `bool` | `True`  | Whether to run the trigger scheduler at all            |
