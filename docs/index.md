:::{image} \_static/logo.png
:alt: Pynenc
:align: center
:height: 90px
:class: hero-logo
:::

# Pynenc Redis Plugin

**Full-stack Redis backend for [Pynenc](https://pynenc.readthedocs.io/) distributed task orchestration.**

The `pynenc-redis` plugin provides all five Pynenc components running on Redis.
Install it alongside Pynenc and it registers itself automatically via Python entry points.

```bash
pip install pynenc-redis
```

## Components at a Glance

| Component             | Class                  | Role                                                  |
| --------------------- | ---------------------- | ----------------------------------------------------- |
| **Orchestrator**      | `RedisOrchestrator`    | Distributed status tracking & blocking control        |
| **Broker**            | `RedisBroker`          | FIFO message queue via Redis lists with blocking pop  |
| **State Backend**     | `RedisStateBackend`    | Persistent state, results, exceptions & workflow data |
| **Client Data Store** | `RedisClientDataStore` | Argument caching for large serialized payloads        |
| **Trigger**           | `RedisTrigger`         | Event-driven & cron-based task scheduling             |

---

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
```

`.redis()` registers every component at once. See {doc}`installation` for
environment-variable and Docker Compose alternatives.

---

::::{grid} 1 2 3 3
:gutter: 3
:padding: 0

:::{grid-item-card} 🚀 Installation & Quick Start
:link: installation
:link-type: doc
:shadow: sm

Get up and running with `PynencBuilder`, environment variables, and Docker Compose examples.
:::

:::{grid-item-card} ⚙️ Configuration Reference
:link: configuration
:link-type: doc
:shadow: sm

All connection, pool, orchestrator, state backend, and trigger settings — with types, defaults, and descriptions.
:::

:::{grid-item-card} 🏗️ Architecture
:link: architecture
:link-type: doc
:shadow: sm

How the plugin uses Redis: connection pooling, key naming convention, atomic operations, and data structure choices.
:::
::::

---

Part of the **[Pynenc](https://pynenc.readthedocs.io/) ecosystem** ·
[MongoDB Plugin](https://pynenc-mongodb.readthedocs.io/) ·
[RabbitMQ Plugin](https://pynenc-rabbitmq.readthedocs.io/)

```{toctree}
:hidden:
:maxdepth: 2
:caption: Redis Plugin

installation
configuration
architecture
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: API Reference

apidocs/index.rst
```

```{toctree}
:hidden:
:caption: Pynenc Ecosystem

Pynenc Docs <https://pynenc.readthedocs.io/>
MongoDB Plugin <https://pynenc-mongodb.readthedocs.io/>
RabbitMQ Plugin <https://pynenc-rabbitmq.readthedocs.io/>
```
