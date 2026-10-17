# Multi-User Setup

This document covers how to configure and operate the Prometheus platform for
multiple simultaneous users.  It is the operator/developer companion to the
`prometheus_api` implementation reference at
`prometheus_api/docs/agent/MULTI_USER.md`.

For a security-architecture view of every secret and key mentioned below —
what each one protects, where it's set, and what breaks if it's lost or
rotated — see `docs/docs/dev-docs/encryption-and-keys.md`.

---

## How multi-user works at the platform level

The frontend is a React SPA (`frontend/`) talking to a standalone FastAPI
`backend/` service (`app/routers/*`, `app/services/*`) — the successor to the
old Chainlit Python frontend. Login, session state, and A2A calls all live in
`backend/`; the identity plane sits on top of that:

```
User logs in (local password, or an admin-configured OIDC provider -- see
"OIDC identity providers" below)
    ↓
backend/app/security.py issues a session-cookie JWT (BACKEND_JWT_SECRET),
carrying { sub: user_id, role, sid, exp } — this is NOT the identity token below
    ↓
Every POST /api/chat/messages (backend/app/routers/chat.py):
  identity.mint_for_user(claims.sub) mints a short-lived PLATFORM JWT
  (signed RS256 with USER_IDENTITY_PRIVATE_KEY) via
  prometheus_api.agent.identity.mint_user_token
    ↓
backend/app/a2a_client.py::A2AClient.send() attaches it to
  message.metadata["userToken"] on the outbound A2A call
    ↓
client-agent verifies the JWT → establishes identity_scope for the turn
  ├─ Binds conversation_id to user_id on first touch (conv_owner Redis key)
  ├─ Rejects cross-user access to existing conversations
  └─ Propagates userToken to every downstream specialist agent call
    ↓
Specialist agents verify the JWT independently
  └─ Can call self.get_credential(resource) for per-user JIT secrets
```

**Two distinct JWTs, two distinct keys** — easy to conflate, so be precise:
- `BACKEND_JWT_SECRET` (HS256) signs the
  **browser session cookie** — backend-to-browser only, never leaves the backend.
- The **platform identity JWT** — backend-to-agents, carried in
  `message.metadata["userToken"]` — is signed RS256 with whichever key
  `identity.mint_for_user()` resolves (see "Managing signing keys" below):
  admin-db's active key if one exists, else `USER_IDENTITY_PRIVATE_KEY`. Every
  agent verifies with `USER_IDENTITY_PUBLIC_KEY` or a `JWKS_URL`, never the
  private key — a compromised agent cannot forge tokens for other users.

### Managing signing keys via the admin UI (preferred)

On a fresh install you do not create the first key. At startup, each backend
worker calls `ensure_active_signing_key()` (`backend/app/signing_keys.py`)
from the lifespan in `backend/app/main.py`. When admin-db has no active
`SigningKey` row, it generates one RS256 key, stores it, and activates it.
A Postgres advisory lock serializes the workers, so one install gets one key.
It creates nothing when `USER_IDENTITY_PRIVATE_KEY` is set, and it leaves
inactive and retired rows untouched.

An admin can generate, activate, and retire RS256 keys from **Admin > Signing
Keys** (`frontend/src/components/admin/AdminSigningKeys.tsx`) — no `.env` edit
or container restart needed. Once a key is active, Postgres is
authoritative: `backend/app/identity.py::mint_for_user()` prefers admin-db's
active `SigningKey` row (private key Fernet-encrypted at rest,
`backend/app/crypto.py`) over the env var below, which is a **static-key
alternative** for a deployment that sets it before the first start.

Encrypting that private key (and any OIDC client secret, see below) at rest
needs `ADMIN_DB_ENCRYPTION_KEY` set — `make up`/`make restart` generate one
into `.env` automatically if it's blank (`scripts/init_env.py`, via the
`init-env` Makefile target), so this is normally nothing to think about.
Starting the stack any other way (e.g. `docker compose up` directly, or CI)
needs `python3 scripts/init_env.py` run first, or the key set by hand.
Leaving it unset doesn't block local-password login — only signing-key
generation and OIDC provider configuration need it. At startup, the backend
logs a warning that names `ADMIN_DB_ENCRYPTION_KEY`, creates no key, and
boots. The admin API calls fail with an actionable error message (not a
bare 500).

- `POST /api/admin/signing-keys` generates a keypair without activating it.
- `POST /api/admin/signing-keys/{id}/activate` makes it the one key that mints
  new tokens; whichever key was active before is deactivated but stays in the
  table, un-retired, until explicitly retired.
- `POST /api/admin/signing-keys/{id}/retire` marks a key done (no longer
  eligible for `/activate`) — but it keeps appearing in the JWKS below, so
  tokens minted before a rotation stay verifiable until they naturally expire.
  Refuses to retire the active key with no replacement (would silently fall
  back to the env var, usually unconfigured).
- **`GET /.well-known/jwks.json`** (unauthenticated, backend root — not under
  `/api`) serves every key in the table, active or retired, as an RFC 7517
  keyset. Point every agent's `JWKS_URL` here instead of distributing
  `USER_IDENTITY_PUBLIC_KEY` by hand — including third-party agents, which
  never need to see this backend's private key at all. All behind
  `require_admin` except the JWKS endpoint itself, which is public by design
  (it's public key material only).

The platform mints its **own** internal identity JWT rather than forwarding the
session cookie or any external IdP token. This means multi-user works
correctly even when deployed without a federated IdP (e.g. local password
users only).

---

## Configuration

### Generate a keypair (static-key alternative only)

You normally do not need this step: the backend creates the first key at
startup (see above). Use this env-var path only for a deployment that must
sign with a key that you generate and hold outside admin-db. Set
`USER_IDENTITY_PRIVATE_KEY` before the first start, because the backend then
creates no DB key. Signing is RS256
only — there is no shared-secret option. Generate a keypair with the tool that
ships in `prometheus_api` (already installed in every agent container,
including the backend):

```bash
prometheus-identity-keygen --out-dir ./keys
# → ./keys/identity_private.pem  (0600 — backend only, never on an agent)
# → ./keys/identity_public.pem   (safe to distribute to every agent)
```

Or with plain `openssl` (zero dependencies):
```bash
openssl genrsa -out identity_private.pem 4096
openssl rsa -in identity_private.pem -pubout -out identity_public.pem
```

See `prometheus_api/docs/agent/IDENTITY_KEY_MANAGEMENT.md` for key rotation and
third-party (JWKS) distribution.

### Required env vars (add to `.env`)

```bash
# Backend only — mints tokens. Never set this on an agent container.
USER_IDENTITY_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"

# Every agent — verifies tokens. Safe to distribute; cannot forge anything.
USER_IDENTITY_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n"

# Shared across backend + all agents; must match exactly.
USER_IDENTITY_ISS=prometheus-platform   # default
USER_IDENTITY_AUD=prometheus-agents     # default

USER_IDENTITY_TTL=7200           # seconds; backend only (minted-token lifetime)
USER_IDENTITY_REQUIRED=true      # false for dev/smoke-test only
```

Multi-line PEM values need careful quoting in `.env`/compose; the
`\n`-escaped single-line form above (which `prometheus-identity-keygen`
prints by default) is the simplest to paste directly.

### `.env.example` / `docker-compose.yml` (already wired up)

`USER_IDENTITY_PRIVATE_KEY` and `USER_IDENTITY_TTL` are set **only** on the
`backend` service's own `environment:` block. `JWKS_URL`, `USER_IDENTITY_PUBLIC_KEY`,
`USER_IDENTITY_ISS`, `USER_IDENTITY_AUD`, `USER_IDENTITY_REQUIRED`, and
`CREDENTIAL_BROKER` live in the root `x-common-env` anchor, shared by `backend`
and every root-defined service (`client-agent`). Every per-agent
`docker-compose.yml` under `agents/*/` (no shared anchor across separate
compose files) carries the same verification-side vars individually.

`JWKS_URL` defaults to `http://backend:8000/.well-known/jwks.json` — the
backend's own container name/port on `agent-network`, reachable from every
agent without any configuration. This is what makes an admin-generated
signing key (Admin > Signing Keys) verifiable by every agent immediately,
with no `USER_IDENTITY_PUBLIC_KEY` set anywhere: `JWKS_URL`, when set, always
takes priority over a static public key (`prometheus_api.agent.identity.verify_user_token`).
Only override it for an agent that can't reach that internal URL — a
third-party agent outside this docker network needs this platform's *public*
JWKS URL instead (or a static public key), from the platform operator.

`agents/debug-agents/*` (only included with `DEBUG_AGENTS=true`) predate this
wiring and don't verify identity tokens at all yet — a known gap, not
something this section's defaults reach.

### Local users

Local accounts are no longer configured in `config.yml` — they live in a
dedicated Postgres database (`admin-db`, separate from `litellm-db`; see
`docker-compose.yml`'s `admin-db` service and `ADMIN_DATABASE_URL` /
`ADMIN_DB_ENCRYPTION_KEY` in `.env.example`). Passwords are hashed with bcrypt
(`backend/app/passwords.py`), never stored or compared in cleartext.

On first run (no `users` row exists yet), the React app shows a setup wizard
(`frontend/src/components/SetupWizard.tsx`) instead of the login screen — it
creates the first account, always `role: "admin"`, and logs it in immediately.
Backing endpoints: `GET /api/setup/status` reports whether setup is still
needed (`frontend/src/App.tsx`'s boot sequence checks this before deciding
whether to render the wizard, login, or the app), `POST /api/setup/bootstrap`
creates that first account (and refuses, `409`, once any account exists).
`backend/app/security.py::PasswordIdentityProvider` then authenticates against
that table on every login.

Creating *additional* local users, editing roles, deactivating, or deleting
accounts is now an admin-only API: `GET/POST /api/admin/users` and
`PATCH/DELETE /api/admin/users/{id}` (`backend/app/routers/admin_users.py`),
gated by `app.security.require_admin` (403 for non-admins). It refuses any
change that would leave zero active admins (demoting, deactivating, or
deleting the last one all `409`). The React app surfaces this as an **Admin**
tab (`frontend/src/layouts/ProjectView.tsx`), visible only when the logged-in
user's `role` is `"admin"` (tracked in `frontend/src/lib/store/session.ts`) —
`frontend/src/components/admin/AdminUsers.tsx` is the users table + create/edit
forms.

### OIDC identity providers (Okta or any generic OIDC issuer)

Configured entirely through **Admin > Identity Providers**
(`frontend/src/components/admin/AdminOidcProviders.tsx`) — no `.env` vars, no
restart. Backend CRUD: `GET/POST /api/admin/oidc-providers`,
`PATCH/DELETE /api/admin/oidc-providers/{id}` (`backend/app/routers/admin_oidc.py`),
same `require_admin` gate as the users/keys admin APIs. `client_secret` is
write-only — accepted on create/update, Fernet-encrypted at rest
(`app/crypto.py`), never returned by any response. `provider_id` (a URL slug,
e.g. `okta`) is immutable after creation — it's the path segment in the login
routes below and the value stored in `users.provider` for accounts created
through it.

The full authorization-code flow (`app/security.py::GenericOidcProvider`,
`app/oidc.py` for the discovery/token-exchange/verification plumbing):

- `GET /api/auth/login/{provider_id}` — redirects the browser to the
  provider's `authorization_endpoint` (fetched fresh from
  `{issuer_url}/.well-known/openid-configuration` on every login — an admin
  editing `issuer_url` takes effect immediately, nothing to restart). Sets a
  short-lived, signed `oidc_flow` cookie carrying this one attempt's
  `state`/`nonce` — there is no server-side flow-state store, so any backend
  worker can finish the callback without shared state. (Sessions, logout
  markers and the SSE bus live in Valkey; see `backend/README.md`.)
- **Register this exact URL as the redirect URI with the provider**:
  `${BACKEND_PUBLIC_URL}/api/auth/callback/{provider_id}`. `BACKEND_PUBLIC_URL`
  (`.env`) must be set to whatever origin the *browser* actually uses to
  reach the platform (e.g. `http://localhost:5150` for the Vite dev server in
  dev, or the public HTTPS domain in production) — left blank, the backend
  falls back to introspecting the request it received
  (`app/security.py::_callback_url`), which is wrong the moment anything
  proxies `/api` requests to it: it sees its own internal host:port, not the
  browser-facing origin, and the identity provider rejects the login with a
  redirect_uri mismatch.
- `GET /api/auth/callback/{provider_id}` — verifies `state` against the flow
  cookie, exchanges the code for tokens, verifies the `id_token`'s signature
  against the issuer's own JWKS (`jwt.PyJWKClient`, so key rotation on the
  *IdP's* side is handled automatically), plus `iss`/`aud`/`exp`/`nonce`, then
  upserts a `users` row keyed by `(provider_id, external_subject)` —
  auto-provisioned with the provider's configured `default_role` on first
  login, matched by that same key (not username) on every login after.
  Existing local accounts and other providers' accounts are never touched.
- `GET /api/auth/providers` (public, unauthenticated) lists enabled providers
  by `provider_id`/`display_name` — `Login.tsx` renders a
  "Sign in with {display_name}" button per entry, replacing what used to be a
  permanently-hidden Okta-shaped stub.

Deactivating an OIDC-provisioned account (**Admin > Users**, same as a local
account) blocks that identity's next login (`400`) without touching the
provider config or other accounts under it. Disabling the provider itself
(**Admin > Identity Providers**) blocks *all* logins through it, including
existing accounts, until re-enabled — both routes read live from the DB on
every request, never a cached snapshot.

Whichever identity source signs a user in, `mint_for_user(claims.sub)` (the
platform identity JWT described above) is unaffected — it mints from whatever
`sub` the login flow resolved, local password or OIDC alike.

---

## Credential broker

### Development (default)

No extra config needed.  Set `CREDENTIAL_BROKER=env` (or omit it — it is the
default) and configure the global credentials as before:
```bash
CREDENTIAL_BROKER=env
DEEPLYNX_JWT_TOKEN=...
DEEPLYNX_ORG_ID=42
DEEPLYNX_PROJECT_ID=7
SLURM_JWT_TOKEN=...
SLURM_REST_URL=http://slurm.hpc/slurm/v0.0.40
```
All users receive the same global credentials.  Appropriate for dev, CI, and
single-user deployments.

### Production with Vault

```bash
CREDENTIAL_BROKER=vault
VAULT_ADDR=https://vault.example.com
VAULT_JWT_ROLE=prometheus-agent
# One of the following workload auth methods:
VAULT_AGENT_SECRET=<per-agent-shared-secret>
# or mTLS (stronger):
VAULT_MTLS_CERT=/certs/agent.crt
VAULT_MTLS_KEY=/certs/agent.key
VAULT_MTLS_CA=/certs/ca.crt
```

Each user must link their resource credentials once (via a forthcoming
consent UI or directly in Vault) at the paths the policy covers:
```
secret/data/deeplynx/{user_id}   →  {"jwt_token": "user-specific-dl-token"}
secret/data/slurm/{user_id}      →  {"token": "user-slurm-token", "user": "hpcuser"}
```

See `prometheus_api/docs/agent/MULTI_USER.md` § Vault broker for the full Vault
policy HCL.

### Third-party agent providers

If an external team or vendor registers an agent with your platform, give them
only `USER_IDENTITY_PUBLIC_KEY` (or point them at `JWKS_URL`) — they can verify
that incoming JWTs were signed by your platform without being able to forge
tokens for any user. This is the whole point of RS256: never share
`USER_IDENTITY_PRIVATE_KEY` with anyone outside the platform backend.

Every `PrometheusAgent` now serves `GET /.well-known/jwks.json` — the RSA public
key as a JSON Web Key Set.  Third-party agents set `JWKS_URL` to this endpoint
and `verify_user_token` fetches and caches the key automatically, with transparent
key rotation via the JWT `kid` header.  No private key or shared secret needs to
leave your organisation.

See `prometheus_api/docs/agent/IDENTITY_KEY_MANAGEMENT.md` for the full key
distribution table, key generation steps, and rotation guide.

---

## Mesh/IFC dataset isolation (decision: no per-user path namespacing)

`GET /api/artifacts/mesh/{dataset_id}/{filename}` (`backend/app/routers/artifacts.py`)
requires a valid session (`Depends(current_claims)`) — a real improvement over
the old Chainlit setup, which served `/public/mesh-data/{dataset_id}/...`
**unauthenticated**. But the endpoint is deliberately **not** per-user
path-namespaced: `dataset_id` is a content hash and the converted-VTP cache is
shared across users by design (uploading the same file twice converts once).

This is intentional, not an oversight. The actual data-access boundary is
**DeepLynx itself**: each user/project has separate DeepLynx credentials
(see Credential broker below), so a user can never reach another user's
*source* artifact regardless of how the local rendering cache is laid out —
namespacing the local VTP cache by user would only protect a cache of content
the requester could already fetch on their own. `GET /api/artifacts/{id}/content`
(the non-mesh artifact endpoint) is separately — and more strongly — isolated:
it resolves against `session.artifacts`, so it can only ever address the
calling session's own catalog.

If this changes (e.g. mesh conversion moves to per-user DeepLynx-backed
storage rather than a local disk cache), revisit this section before assuming
the auth gate alone is sufficient.

---

## Conversation isolation

Each conversation is owned by the user who created it:

- **First turn**: `record_conversation_owner(conv_id, user_id)` writes a Redis
  key `conv_owner:{conv_id} = user_id` and adds `conv_id` to
  `user:convs:{user_id}`.
- **Subsequent turns**: `assert_conversation_owner(conv_id, user_id)` rejects the
  request if a different user owns it.
- **`/history`**: scoped to the current user via the `user:convs:{user_id}` Redis
  set — no global scan.

The underlying Redis keys for artifacts, task graphs, and status are **not**
renamed; access control is enforced at the entry point only.  This is correct
because `conversation_id` is a random UUID that is unguessable in practice.

---

## User-scoped uploads

`POST /api/uploads` (`backend/app/routers/uploads.py`) mints a `user_token` via
`identity.mint_for_user(claims.sub)` and passes it to
`A2AClient.stage_upload(..., user_token=...)`, which forwards it as an explicit
**query param** on the client-agent's raw `/uploads/stage` endpoint
(`agents/client-agent/orchestrator/service.py::_stage_upload_endpoint`).

That endpoint verifies the token directly (`verify_user_token(user_token)`)
rather than reading the ambient identity context — it's a raw Starlette route
added via `app.add_route`, not routed through `PrometheusAgentExecutor.execute()`,
so no `identity_scope()` is ever active there. (An earlier version of this code
tried to read `current_user_id()` from that ambient context and always got
`None` — a real bug, not a hypothetical; if you see staged uploads with an
empty `user_id`, check that `user_token` is actually being passed as a query
param, not assumed from context.)

The verified `user_id` is stamped into the staged upload's metadata. When the
agent later processes the upload, it rejects retrieval by a different user:

```python
# file_upload_handler.resolve_staged_upload(uploaded_file, user_id="alice")
# → raises PermissionError if the upload was staged by "bob"
```

---

## Developer guide: adding credentials to a new agent

1. Set `requires_user_isolation = True` on the agent if it holds credentials
   across multiple `await` calls (e.g. job submission + polling).  Stateless
   agents that fetch and immediately use a credential do not need it.

2. Call `self.get_credential(resource)` inside `_execute`:

```python
from prometheus_api.agent import PrometheusAgent
from prometheus_api.storage_client.connection import ConnectionConfig

class MyNewAgent(PrometheusAgent):
    requires_user_isolation = True   # optional; set if holding creds across awaits

    async def _execute(self, params, context, event_queue):
        user_id = params["user_id"]   # already verified

        # JIT credential — never cache this
        cred = await self.get_credential("deeplynx")
        config = ConnectionConfig.from_credential(cred)

        await self.send_status_update(context, event_queue,
            message=f"Fetching data for {user_id}...")
        # ... use config ...
        return {"status": "success"}
```

3. Add the agent's resource requirements to its `agent_card.json` (future:
   will feed the consent/permission UI):

```json
{
  "name": "my-new-agent",
  "required_credentials": [
    {"resource": "deeplynx", "required": true}
  ]
}
```

4. Run `make generate` to pick up the new `docker-compose.yml` if you created a
   new agent directory.

---

## Running without multi-user (single-user / dev)

Set `USER_IDENTITY_REQUIRED=false` in `.env`.  Agents synthesise a synthetic
`UserIdentity(user_id="local")` for requests that carry no `userToken`.  All
existing behaviour is preserved.  The ownership and history-scoping features
still work (scoped to the `"local"` user_id).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Agent returns `"Identity verification failed: userToken has expired"` | Turn lasted longer than `USER_IDENTITY_TTL` | Increase `USER_IDENTITY_TTL` (default 7200) |
| Agent returns `"No 'userToken' found in message metadata"` | `USER_IDENTITY_REQUIRED=true` but the backend has no active signing key and no `USER_IDENTITY_PRIVATE_KEY` (usually the startup warning about `ADMIN_DB_ENCRYPTION_KEY`) | Set `ADMIN_DB_ENCRYPTION_KEY` (`python3 scripts/init_env.py`) and restart the backend, or activate a key under **Admin > Signing Keys** |
| Agent fails to verify with "USER_IDENTITY_PUBLIC_KEY ... is required" | Agent has no public key or `JWKS_URL` configured | Set `USER_IDENTITY_PUBLIC_KEY` (never the private key) on the agent |
| `CredentialError: VAULT_ADDR is required` | `CREDENTIAL_BROKER=vault` but Vault env not set | Set `VAULT_ADDR` and `VAULT_JWT_ROLE`, or switch to `CREDENTIAL_BROKER=env` |
| `/history` shows no conversations | User has not yet created any conversations in this deployment | Expected — history is now per-user |
| Worker pool capacity error | Too many concurrent users for `USER_WORKER_MAX` | Increase `USER_WORKER_MAX` (default 32) |

---

## See also

- `prometheus_api/docs/agent/MULTI_USER.md` — implementation reference for agent authors
- `prometheus_api/docs/agent/IDENTITY_KEY_MANAGEMENT.md` — RS256 key generation, key distribution, third-party agent integration via JWKS
- `prometheus_api/docs/agent/GUIDE.md` — general PrometheusAgent developer guide
- `docs/docs/dev-docs/adding-agents.md` — how to create a new specialist agent
- `docs/docs/dev-docs/artifacts.md` — artifact model and rendering
