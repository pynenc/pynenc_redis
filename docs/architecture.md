# Architecture

How `pynenc-redis` uses Redis internally.

## Connection Pooling

The plugin maintains a global `ConnectionPool` per unique set of connection parameters.
All components within the same process share the same pool, protected by an `RLock` for
thread safety. Connections are validated at acquisition time with configurable health checks.

## Key Naming

Every Redis key follows the pattern:

```
__pynenc__:{app_id}:{component}:{type}:{id}
```

Special characters (`[`, `]`, `*`) are sanitized to avoid conflicts with Redis glob
patterns. The `app_id` acts as a namespace — multiple Pynenc applications can safely
share a single Redis instance.

```{note}
`SCAN` is always used instead of `KEYS` for bulk lookups, so large keyspaces never
block the Redis server.
```

## Atomic Operations

| Mechanism                | Where it's used                                                           |
| ------------------------ | ------------------------------------------------------------------------- |
| **Pipelines**            | Status transitions and batch routing — consistent multi-key writes        |
| **SETNX + TTL**          | Distributed trigger claim locks — first writer wins                       |
| **WATCH / MULTI / EXEC** | Cron execution tracking — optimistic locking prevents duplicate execution |

## Data Structures

| Redis Type      | Usage                                                                        |
| --------------- | ---------------------------------------------------------------------------- |
| **Strings**     | Invocation data, status records, results, exceptions, timestamps             |
| **Lists**       | Broker FIFO queue (`LPUSH` / `BLPOP`), invocation history                    |
| **Sets**        | Invocations by status, task membership, trigger/condition relationships      |
| **Sorted Sets** | Time-indexed invocations (pagination), auto-purge tracking, blocking control |

## Logging

The plugin logs through the Pynenc application logger (`self.app.logger`):

| Level       | What's logged                                                 |
| ----------- | ------------------------------------------------------------- |
| **DEBUG**   | Client initialization, invocation routing, status transitions |
| **WARNING** | Missing invocations encountered during operations             |
| **ERROR**   | Timestamp parsing failures                                    |
