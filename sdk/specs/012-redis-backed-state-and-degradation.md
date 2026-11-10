# 012 — Redis-backed state and degradation

status: implemented
sources: prometheus_api/redis_utils.py, prometheus_api/agent/task_store.py, prometheus_api/agent/base.py, tests/unit/test_redis_utils.py, tests/unit/test_task_store.py, tests/unit/test_agent.py
depends-on: none

## Purpose
Provide a shared Redis connection recipe and durable A2A task storage that degrades gracefully when Redis is unavailable.

## Requirements
- REQ-012-01: `redis_url_from_env()` MUST return `REDIS_URL` when set and `redis://localhost:6379` otherwise.
- REQ-012-02: `create_redis_client(...)` MUST use an explicit URL or `REDIS_URL`, set `decode_responses=True` by default, apply explicit `password` or `REDIS_PASSWORD`, and let the explicit/env password override any password embedded in the URL.
- REQ-012-03: `create_redis_client(...)` MUST ping by default, return a Redis client on success, and return `None` while logging a warning on connection failure.
- REQ-012-04: `RedisTaskStore` MUST default its Redis URL from `REDIS_URL` or localhost and its TTL to 24 hours unless `ttl_seconds` or integer `TASK_STORE_TTL_SECONDS` is provided.
- REQ-012-05: Invalid `TASK_STORE_TTL_SECONDS` values MUST fall back to the default TTL. ⚠ untested
- REQ-012-06: Task store keys MUST use `a2a:task:{task_id}`.
- REQ-012-07: `RedisTaskStore.save(...)`, `get(...)`, and `delete(...)` MUST offload synchronous Redis/memory work with `asyncio.to_thread`.
- REQ-012-08: Saving a task MUST overwrite any prior task with the same ID and use Redis TTL when `ttl_seconds > 0`; non-positive TTL MUST save without expiration. ⚠ untested
- REQ-012-09: When Redis is unavailable or an operation fails, `RedisTaskStore` MUST degrade to a thread-safe in-memory fallback for save/get/delete.
- REQ-012-10: `RedisTaskStore.get(...)` MUST return `None` for missing tasks and corrupt/non-Task payloads.
- REQ-012-11: `RedisTaskStore.delete(...)` MUST be a no-op for missing task IDs.
- REQ-012-12: `TERMINAL_STATES` MUST include completed, canceled, failed, and rejected, and MUST exclude non-terminal working.
- REQ-012-13: `PrometheusAgent.build_app(...)` MUST use `RedisTaskStore` unless `PROMETHEUS_TASK_STORE=memory`.

## Behavior
- BEH-012-01: GIVEN an unreachable Redis URL WHEN `create_redis_client(...)` is called THEN it returns `None` and logs the failure.
- BEH-012-02: GIVEN the fallback task store has saved a task WHEN the task is loaded THEN the A2A `Task` model round-trips with its ID, context ID, and state.
- BEH-012-03: GIVEN a task is deleted twice WHEN using the fallback store THEN the second delete succeeds without error.

## Interfaces
- `DEFAULT_REDIS_URL = "redis://localhost:6379"`
- `redis_url_from_env() -> str`
- `create_redis_client(url: str | None = None, *, password: str | None = None, decode_responses: bool = True, ping: bool = True) -> redis.Redis | None`
- `TERMINAL_STATES: frozenset[TaskState]`
- `RedisTaskStore(redis_url: str | None = None, ttl_seconds: int | None = None)`
- `RedisTaskStore.redis_client -> redis.Redis | None`
- `RedisTaskStore.save(task: Task, context: Any | None = None) -> None`
- `RedisTaskStore.get(task_id: str, context: Any | None = None) -> Task | None`
- `RedisTaskStore.delete(task_id: str, context: Any | None = None) -> None`

## Constraints
- Redis degradation MUST be logged so loss of cross-process durability is visible.
- Redis clients use decoded string responses by default across Prometheus components.
- In-memory fallbacks are process-local and do not survive process restart.

## Out of scope / Non-goals
- This package does not provision Redis, manage Redis schemas, or provide distributed locking.
- `RedisTaskStore` does not enforce terminal-state immutability.

## Open questions
- `TERMINAL_STATES` is exported but currently not used by `RedisTaskStore` to reject overwrites of terminal tasks.
- TTL behavior for Redis writes is implemented but only fallback round-trips are covered by tests.
