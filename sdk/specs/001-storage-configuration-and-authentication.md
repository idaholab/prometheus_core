# 001 — Storage configuration and authentication

status: implemented
sources: README.md, docs/storage-client/GUIDE.md, docs/ENV_SETUP.md, prometheus_api/storage_client/connection.py, prometheus_api/storage_client/client.py, prometheus_api/storage_client/async_client.py, prometheus_api/storage_client/auth.py, prometheus_api/storage_client/exceptions.py, tests/unit/test_connection.py, tests/unit/test_env_config.py, tests/unit/test_exceptions.py, tests/unit/test_client_errors.py
depends-on: none

## Purpose
Provide a single typed contract for connecting to DeepLynx and a consistent sync/async HTTP client foundation for every storage resource.

## Requirements
- REQ-001-01: `ConnectionConfig` MUST require `organization_id`, `project_id`, and exactly one auth method: either `jwt_token` or both `api_key` and `api_secret`.
- REQ-001-02: `ConnectionConfig` MUST reject configurations that provide both JWT and API key credentials.
- REQ-001-03: `ConnectionConfig` MUST normalize `base_url` by removing trailing slashes and MUST default to `https://deeplynx.inl.gov/api/v1`.
- REQ-001-04: `ConnectionConfig` MUST reject non-positive `timeout` values and negative `max_retries` values. ⚠ untested
- REQ-001-05: `ConnectionConfig` instances MUST be immutable and expose `uses_api_key` and `uses_jwt` booleans.
- REQ-001-06: `ConnectionConfig.from_env(...)` MUST load DeepLynx credentials, org/project IDs, optional data source ID, and base URL from an explicit env file, then environment variables, with explicit `organization_id` and `project_id` parameters overriding env values.
- REQ-001-07: `StorageClient` and `AsyncStorageClient` MUST initialize their HTTP and auth handlers only through their context manager protocols and MUST raise `StorageClientError` if a request is made before initialization.
- REQ-001-08: Client resource properties MUST lazily construct stable handlers for `items`, `files`, `relationships`, `search`, `tags`, and `timeseries`.
- REQ-001-09: Client requests MUST attach bearer authentication headers and merge caller-provided request headers without dropping auth headers.
- REQ-001-10: Client requests MUST retry timeout and connection failures up to `max_retries`, and MUST map 401, 404, other 4xx, and 5xx responses to `AuthenticationError`, `ItemNotFoundError`, `ValidationError`, and `APIError` respectively. The mapped exception MUST reach the caller as that type, with the server's message and (for `ValidationError`/`APIError`) the response body in `details`; it MUST NOT be re-wrapped in a generic `StorageClientError`.
- REQ-001-11: API-key authentication MUST exchange `apiKey` and `apiSecret` for a JWT through `/oauth/tokens`, cache it, and refresh managed tokens before expiry or after one managed-token 401. ⚠ untested
- REQ-001-12: If `data_source_id` is not configured, clients MUST fetch and cache the project default data source or raise a `StorageClientError` that instructs users to set `DEEPLYNX_DATA_SOURCE_ID`. ⚠ untested

## Behavior
- BEH-001-01: GIVEN a config with API key credentials WHEN request headers are requested THEN the auth handler obtains a JWT and returns `Authorization: Bearer <token>`.
- BEH-001-02: GIVEN a config with a JWT token WHEN request headers are requested THEN the auth handler uses that token directly and does not manage refresh.
- BEH-001-03: GIVEN an HTTP 404 response WHEN the storage client handles it THEN an `ItemNotFoundError` is raised with the API error message when available.
- BEH-001-04: GIVEN an HTTP 400 response with a JSON error body WHEN a request is made through `StorageClient` or `AsyncStorageClient` THEN a `ValidationError` carrying the server's error message and the parsed body in `details` reaches the caller, and the request is not retried.

## Interfaces
- `ConnectionConfig(organization_id: int, project_id: int, data_source_id: int | None = None, base_url: str = ..., api_key: str | None = None, api_secret: str | None = None, jwt_token: str | None = None, timeout: float = 30.0, max_retries: int = 3, verify_ssl: bool = True)`
- `ConnectionConfig.from_env(env_file: Path | None = None, organization_id: int | None = None, project_id: int | None = None, **kwargs) -> ConnectionConfig`
- `ConnectionConfig.uses_api_key -> bool`
- `ConnectionConfig.uses_jwt -> bool`
- `StorageClient(config: ConnectionConfig)`
- `AsyncStorageClient(config: ConnectionConfig)`
- `StorageClient.items/files/relationships/search/tags/timeseries`
- `AsyncStorageClient.items/files/relationships/search/tags/timeseries`
- `AuthHandler(config: ConnectionConfig, client: httpx.Client).get_headers() -> dict[str, str]`
- `AsyncAuthHandler(config: ConnectionConfig, client: httpx.AsyncClient).get_headers() -> dict[str, str]`
- `StorageClientError(message: str, details: dict | None = None)`
- `AuthenticationError`, `ItemNotFoundError(item_id: Any, message: str | None = None)`, `ValidationError`, `APIError(message: str, status_code: int | None = None, response_data: dict | None = None)`

## Constraints
- Storage configuration values are environment-specific; code MUST NOT hard-code credentials, org/project IDs, or DeepLynx deployment URLs outside documented defaults.
- Sync and async clients SHOULD preserve equivalent behavior for shared authentication, request handling, data source lookup, and error mapping.
- Request retry behavior is immediate retry only; no backoff contract is currently enforced.

## Out of scope / Non-goals
- This package does not implement DeepLynx credential issuance beyond exchanging configured API keys for JWTs.
- This spec does not require storage clients to be usable outside their context manager protocols.

## Open questions
- Token refresh has no direct unit coverage (REQ-001-11); retry behavior and response error mapping are covered by `tests/unit/test_client_errors.py`.
- `ConnectionConfig` forbids extra fields through Pydantic config, but there is no explicit regression test for unknown fields.
