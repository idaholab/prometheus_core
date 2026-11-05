# Full local setup

A start-to-finish install of the platform with everything running on your own
machine: the SDK built from the checkout next to it, the debug agents, a local
DeepLynx, and a local Keycloak for single sign-on. Nothing here is shared
infrastructure, and nothing but the LLM provider is reached over the network.

The [README quickstart](../../README.md) is the shorter path, with the defaults.
This page is the long one, with every option turned on.

## What you end up with

| | |
| --- | --- |
| React frontend | http://localhost:5150 |
| Backend API | http://localhost:8600 |
| DeepLynx UI / API | http://localhost:3000 / http://localhost:5000 |
| Keycloak | http://localhost:8180 |
| Agents | 9 registered: client-agent, synthesis-agent, and the 7 debug agents |

## Prerequisites

- Docker and Docker Compose.
  - **Windows**: run everything from a WSL2 shell, not from Windows directly.
    See [Windows + WSL2 setup](windows-wsl2-setup.md) for enabling WSL2
    integration in Docker Desktop first.
  - **Linux**: do not run `make` with `sudo`. It creates a root-owned `.env`
    and every later `make` as yourself fails with "permission denied". Add
    yourself to the `docker` group instead. If you already did it, `sudo chown
    $USER .env`.
- `make` and `openssl`. A minimal distro or WSL image may have neither.
- An API key for one of the supported LLM providers.

**Free these host ports first: 5150, 8600, 6379, 3000, 5000, 8180.** The two
that usually collide are DeepLynx's 3000 and 5000: if you already run DeepLynx
yourself, stop it (`docker compose -p deeplynx down`) before continuing, since
the two cannot both bind those ports. Docker Desktop reports the clash as
`ports are not available: ... /forwards/expose returned unexpected status: 500`,
which does not name the conflict.

## 1. Clone

```bash
git clone https://github.com/idaholab/prometheus_core.git
cd prometheus_core/platform
```

The SDK is at `prometheus_core/sdk`, already a sibling of `platform/`, so
building it locally needs no second clone.

## 2. Create .env

```bash
make init-env
```

In a terminal this asks four things:

| Prompt | Answer |
| --- | --- |
| `Build the SDK base image locally (LOCAL_SDK)?` | Enter (yes) |
| `Run DeepLynx locally (LOCAL_DEEPLYNX)?` | Enter (yes) |
| Which LLM profile | arrow keys, then Enter |
| The API key for it | paste it |

It also generates `AGENT_SECRET`, `REDIS_PASSWORD`, `ADMIN_DB_PASSWORD`,
`BACKEND_JWT_SECRET` and `ADMIN_DB_ENCRYPTION_KEY`.

**Back up `.env` now.** Lose `ADMIN_DB_ENCRYPTION_KEY` and the encrypted rows in
admin-db — OIDC client secrets and signing keys — cannot be read again.

## 3. Add the two settings nothing asks about

Open `.env` and add:

```dotenv
DEBUG_AGENTS=true
BACKEND_PUBLIC_URL=http://localhost:5150
```

`DEBUG_AGENTS=true` includes the seven agents under `agents/debug-agents/`
(corrosion, radiation, thermal, material-data, thread-pattern, artifact-debug,
code-render-debug), taking the stack from 2 registered agents to 9. In a plain
checkout the specialist agents exist *only* there, so without this you get the
orchestrator and synthesis agent and nothing to dispatch to.

`BACKEND_PUBLIC_URL` is the address the browser uses to reach the platform. The
backend sends it to the identity provider as the `redirect_uri` and has no
other way to know it. It has to be set **before** the backend starts, or OIDC
sign-in fails with a redirect-URI mismatch. See
[Local OIDC provider](local-oidc.md).

`.env` should now contain:

```dotenv
LOCAL_SDK=true
LOCAL_DEEPLYNX=true
DEBUG_AGENTS=true
BACKEND_PUBLIC_URL=http://localhost:5150
LLM_CONFIG_PROFILE=<the profile you picked>
LLM_API_KEY=<its key>
```

## 4. Start the platform

```bash
make up
```

This builds the SDK base image from `../sdk`, builds nine agent images plus the
backend and frontend, starts DeepLynx, and runs `make deeplynx-setup`, which
creates a DeepLynx project and API key and writes the `DEEPLYNX_*` lines back
into `.env`.

**The first run takes roughly 15 to 30 minutes** with the debug agents
included; later runs are minutes. `make up-fg` runs it in the foreground if you
would rather watch than wait on a detached container.

It returns only once every healthcheck passes, the backend and frontend answer
on their ports, and all nine agents have registered.

## 5. Create the first administrator

Open http://localhost:5150. The first-run wizard asks for a username and
password. **Save them**: this is the only account that exists, and the only one
that can register the identity provider in step 7.

Forgotten it later: `make clear-admin-users` deletes the local accounts and the
wizard runs again.

## 6. Start Keycloak

```bash
make oidc-up
```

This has to come after `make up`, because Keycloak joins the Docker network
that `make up` creates. It runs as its own Compose project, so `make down` and
`make restart` leave it running.

## 7. Register the provider

Sign in as the administrator, go to **Admin → Identity Providers**, add one:

| Field | Value |
| --- | --- |
| Provider ID | `keycloak` |
| Display name | `Keycloak` |
| Issuer URL | `http://keycloak:8080/realms/prometheus` |
| Client ID | `prometheus-platform` |
| Client secret | `local-dev-only-not-a-real-secret` |
| Scopes | `openid profile email` |

The issuer URL is the container address, not `localhost:8180`: the backend
fetches the discovery document over the Docker network.
[Local OIDC provider](local-oidc.md) explains why those differ, and how to add
your own users.

## 8. Check it

```bash
make check                                  # 9 agents registered
curl -s localhost:8600/api/auth/providers   # lists keycloak
```

Log out. The login page now shows **Sign in with Keycloak** below the password
form; the realm's test user is `prometheus` / `prometheus`.

## Day to day

```bash
make up                  # start (leaves Keycloak alone)
make down                # stop (likewise)
make oidc-up             # start Keycloak
make oidc-down           # stop it, keeping its realm
make logs SERVICE=backend
make ps
make clear-admin-users   # forgot the local administrator password
```

Resetting goes in widening circles: `make oidc-reset` discards Keycloak's
users, `make down-v` drops the platform's volumes, and `make clobber` deletes
admin-db and Valkey — every user, signing key, OIDC registration and
conversation — for reinstalling after `.env` was lost.
