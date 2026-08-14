# Multi-User Setup

This document covers how to configure and operate the Prometheus platform for
multiple simultaneous users.  It is the operator/developer companion to the
`prometheus_api` implementation reference at
`prometheus_api/docs/agent/MULTI_USER.md`.

---

## How multi-user works at the platform level

```
User logs in (local password or Okta OIDC)
    ↓
Chainlit frontend creates a cl.User with identifier = user_id
    ↓
on_chat_start stores user_id in cl.user_session
    ↓
Every A2A turn:
  message_handler.py mints a short-lived platform JWT (USER_IDENTITY_SECRET)
  attaches it to message.metadata["userToken"]
    ↓
client-agent verifies the JWT → establishes identity_scope for the turn
  ├─ Binds conversation_id to user_id on first touch (conv_owner Redis key)
  ├─ Rejects cross-user access to existing conversations
  └─ Propagates userToken to every downstream specialist agent call
    ↓
Specialist agents verify the JWT independently
  └─ Can call self.get_credential(resource) for per-user JIT secrets
```

The platform mints its **own** internal JWT rather than forwarding the IdP token.
This means multi-user works correctly even when deployed without a federated IdP
(e.g. local password users only).

---

## Configuration

### Required env vars (add to `.env`)

```bash
# Identity — must match across all services (frontend + all agents)
USER_IDENTITY_SECRET=change-this-to-a-long-random-string
USER_IDENTITY_ALG=HS256          # HS256 (default) or RS256
USER_IDENTITY_ISS=prometheus-platform   # default
USER_IDENTITY_AUD=prometheus-agents     # default
USER_IDENTITY_TTL=7200           # seconds; must cover the longest expected turn
USER_IDENTITY_REQUIRED=true      # false for dev/smoke-test only
```

For RS256 (asymmetric, preferred for production):
```bash
USER_IDENTITY_ALG=RS256
USER_IDENTITY_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
USER_IDENTITY_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n..."
# Private key is only needed by the frontend (minting).
# Public key is sufficient for agents (verification only).
```

### `.env.example` additions (already added)

The following variables have been added to `docker-compose.yml` and should be
templated in `.env.example`:
```
USER_IDENTITY_SECRET=
USER_IDENTITY_REQUIRED=true
CREDENTIAL_BROKER=env
```

### Local users

Add users in `frontend/config.yml`:
```yaml
local-users:
  - username: "alice"
    password: "replace-with-a-strong-password"
    role: "admin"
  - username: "bob"
    password: "replace-with-another-strong-password"
    role: "user"
```

Plain-text passwords are only used for local dev.  For production, enable Okta
(see `.env.example` `OAUTH_OKTA_*` vars) — the OAuth callback extracts the OIDC
`sub` claim as the canonical user_id automatically.

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

If an external team or vendor registers an agent with your platform, **use RS256**.
Give them only the `USER_IDENTITY_PUBLIC_KEY` — they can verify that incoming JWTs
were signed by your platform without being able to forge tokens.

With HS256 you would have to share `USER_IDENTITY_SECRET`, which lets them
impersonate any user.  Never do this.

A JWKS endpoint (`GET /.well-known/jwks.json`) is the cleanest long-term solution:
third-party agents fetch the current public key automatically and key rotation
requires no manual coordination.  The endpoint is not yet served by the platform;
until it is, distribute the public key as a PEM file.

See `prometheus_api/docs/agent/IDENTITY_KEY_MANAGEMENT.md` for the full key
distribution table, key generation steps, and rotation guide.

---

## Per-user dataset isolation

Mesh and IFC visualization datasets are now written under per-user paths when a
user is logged in:

```
# Before (shared, unauthenticated):
/public/mesh-data/{dataset_id}/...
/public/ifc-data/{dataset_id}/...

# After (per-user):
/public/mesh-data/{user_id}/{dataset_id}/...
/public/ifc-data/{user_id}/{dataset_id}/...
```

Dataset URLs served to the frontend follow the same scheme, so links are only
guessable by someone who knows both the user_id and the random dataset_id.
Datasets generated in sessions without a logged-in user (auth disabled) continue
to use the old flat path for backward compatibility.

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

Staged uploads are stamped with the uploading user's `user_id` in their metadata.
When the agent processes the upload, it rejects retrieval by a different user:

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
| Agent returns `"No 'userToken' found in message metadata"` | `USER_IDENTITY_REQUIRED=true` but frontend has no `USER_IDENTITY_SECRET` configured | Set `USER_IDENTITY_SECRET` in `.env` |
| `CredentialError: VAULT_ADDR is required` | `CREDENTIAL_BROKER=vault` but Vault env not set | Set `VAULT_ADDR` and `VAULT_JWT_ROLE`, or switch to `CREDENTIAL_BROKER=env` |
| `/history` shows no conversations | User has not yet created any conversations in this deployment | Expected — history is now per-user |
| Worker pool capacity error | Too many concurrent users for `USER_WORKER_MAX` | Increase `USER_WORKER_MAX` (default 32) |

---

## See also

- `prometheus_api/docs/agent/MULTI_USER.md` — implementation reference for agent authors
- `prometheus_api/docs/agent/GUIDE.md` — general PrometheusAgent developer guide
- `docs/dev-docs/adding-agents.md` — how to create a new specialist agent
- `docs/dev-docs/artifacts.md` — artifact model and rendering
