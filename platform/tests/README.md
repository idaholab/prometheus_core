# Platform tests

| Suite | Marker | Command | Needs |
|-------|--------|---------|-------|
| Static | `not integration` | `make test-static` | Nothing: reads the compose files, `.env.example` and the code |
| Integration | `integration` | `make test-integration` | Docker; uses a running stack, or starts its own |
| System | `system` | `make test-system` | A full stack with real LLM and DeepLynx credentials |

## Integration tests

The integration tests (`infrastructure/test_integration_*.py`) talk to the
containers: Postgres, Valkey, and the backend.

- **With a running stack** (`make up`): when `backend` is running, the
  tests use that stack as is. Credentials and host ports come from
  `platform/.env`, and the tests neither start nor stop a container. Everything
  they create in Valkey has a unique test name and is deleted again.
- **Without one**: the `docker_compose_up` fixture starts the infrastructure
  services, plus client-agent and backend, from `docker-compose.yml` using a
  generated `.env.test` (throwaway secrets, offset ports). When the session
  ends, it tears them down along with their volumes. This path is currently
  broken: `.env.test` lacks `ADMIN_DB_PASSWORD`, and the client-agent build
  needs the `PROMETHEUS_API_BASE_IMAGE_*` values that only the Makefile sets.
  Use `make up` first.

The containers have fixed names, so the two can't run side by side. Stop a
running stack first if you want the fixture's own one.

### CI

The `platform: up` job in `.github/workflows/test.yml` runs this suite. It runs
`make up LOCAL_SDK=true`, which waits for every healthcheck and for every
agent to register with the backend, then runs `make test-integration` against
that stack. It then runs the other start targets against the stack (`make restart`,
`make ng-restart`, `make down` then `make restart`, and `make down-v` then
`make up`), checks that `.env` is unchanged after each, runs the integration
tests again, and always runs `make down-v`. If the job fails, the container
logs (one file per service plus a combined one) are uploaded as the
`platform-up-logs` artifact. It runs on every pull request and every push to
`devel`, like the rest of the workflow; the whole job takes a few minutes.

The `platform: up deeplynx` job does the same with `LOCAL_DEEPLYNX=true`
(see `../docs/docs/local-deeplynx.md`), with only the default agents and no
frontend: DeepLynx runs next to the platform from its published images, and
`make deeplynx-setup` (`./platformctl deeplynx setup`) gives the services a real project and API key for it.
`test_integration_deeplynx.py` stores an item and a file through the backend's
storage client and reads them back; without the local DeepLynx those tests are
skipped. Across the start targets, the DeepLynx settings in `.env` have to be
kept until `make down-v` and replaced after it. Its logs are uploaded as
`platform-up-deeplynx-logs`.

### No real LLM or DeepLynx credentials

None of the integration tests call an LLM or DeepLynx, and nothing at startup
does either, so CI sets **stub credentials** instead of using secrets:

- `LLM_CONFIG_PROFILE=anthropic` with `LLM_API_KEY=sk-ant-test-not-real`.
  Agents only call a model while handling a chat turn, which no integration
  test starts.
- `DEEPLYNX_KEY`, `DEEPLYNX_SECRET`, `DEEPLYNX_ORG_ID` and
  `DEEPLYNX_PROJECT_ID` with placeholder values. Agents check at startup that
  DeepLynx is configured but don't connect until an artifact is stored. In
  `platform: up deeplynx` they are real, for the local DeepLynx, and need
  no secrets either.

That makes these tests safe to run on pull requests from forks, which get no
repository secrets. A test that does need a model response would need a mock
LLM endpoint instead, for example an `LLM_CONFIG_FILE` profile whose `api_base`
points at a stub server only CI starts.

## System tests

The system tests (`system/`, `-m system`) drive a real chat through the
client-agent and judge its answers with an LLM, so they need a real LLM key and
a reachable DeepLynx. They don't run in CI yet. See `../README.md`, "Full-system
tests", for running them locally.
