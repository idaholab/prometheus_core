# Encryption & Keys

A security-architecture reference: every secret and key in the platform, what
each one protects, where it lives, and what breaks if it's lost or rotated.
`multi-user-setup.md` is the operational how-to (setup wizard, admin UI,
OIDC configuration); this page is the map you'd want before touching any of
it — read it once, then use `multi-user-setup.md` for day-to-day operation.

## The four kinds of secret

Four genuinely different mechanisms exist in this stack. They're easy to
conflate because they're all "a JWT" or "a key" at a glance — they are not
interchangeable, and none of them substitutes for another.

| # | Secret | Algorithm | Protects | Lives in |
|---|---|---|---|---|
| 1 | `BACKEND_JWT_SECRET` | HS256 (symmetric) | The browser session cookie | Backend env only |
| 2 | Identity signing key | RS256 (asymmetric) | The platform identity JWT (`userToken`, backend→agents) | admin-db (`SigningKey`, Fernet-encrypted) once one exists, else `USER_IDENTITY_PRIVATE_KEY` env |
| 3 | `ADMIN_DB_ENCRYPTION_KEY` | Fernet (AES-128-CBC + HMAC-SHA256) | Secret #2's private key material, and every OIDC provider's `client_secret`, at rest in admin-db | Backend env only |
| 4 | Local account passwords | bcrypt (one-way hash, not encryption — there is no key that reverses it) | Local login credentials | admin-db (`users.password_hash`) |

Plus one pre-existing, unrelated secret worth naming so it isn't confused with
the above: `AGENT_SECRET` is a bearer token for A2A auth between the backend,
client-agent, and every specialist agent — it has nothing to do with *who the
user is* (identity plane) and predates all of this.

SMTP passwords (`SMTP_PASSWORD` and `SMTP_<NAME>_PASSWORD`) are external
credentials, held only in the backend environment and never stored by the
platform; see [Platform settings](platform-settings.md).

### Why four, not one

- **#1 (session cookie) is deliberately separate from #2 (identity JWT).**
  The session cookie is backend-to-browser and never leaves the backend; the
  identity JWT is backend-to-agents and is handed to every specialist agent,
  including third-party ones. Reusing one secret for both would mean an
  agent — or a compromised agent deployment — could forge a *login* cookie,
  not just an identity claim. HS256 is fine for #1 precisely because nothing
  outside the backend ever needs to verify it.
- **#2 is RS256, not HS256, for the same reason in the other direction:** the
  identity JWT *is* handed to every agent. A symmetric secret shared with N
  verifiers is a secret held by N parties, any one of which could then mint
  a token for any user. RS256 means only the backend (holding the private
  key) can mint; every verifier — including third-party agents — holds only
  a public key or a JWKS URL, neither of which can forge anything. (This is
  exactly why HS256 was removed entirely from the identity plane — see
  `prometheus_api/docs/agent/AGENT_MIGRATIONS.md`'s 0.12.0 entry. It was
  never removed from the *session cookie*, which has a different threat
  model and was never in scope for that change.)
- **#3 exists because #2's private key and every OIDC `client_secret` sit in
  Postgres**, a store an operator might reasonably need to dump, back up, or
  query directly for other reasons. Encrypting those two column values means
  a database dump or a read-only SQL console alone can't recover them —
  recovering them also requires `ADMIN_DB_ENCRYPTION_KEY`, which never
  touches admin-db itself (see "Where each secret is set" below).
- **#4 is a one-way hash, not encryption**, because a password should never
  be recoverable by anyone, including the platform operator — encryption
  implies a key that reverses it; hashing has no such key by design.

## Where each secret is set

```
┌────────────────────────────────────────────────────────────────────────┐
│  Secret                        Set on             Never set on        │
├────────────────────────────────────────────────────────────────────────┤
│  BACKEND_JWT_SECRET             backend             every agent        │
│  Identity private key (#2)      backend (or         every agent        │
│    admin-db, once generated)    admin-db)                              │
│  Identity public key / JWKS_URL every agent          backend            │
│  ADMIN_DB_ENCRYPTION_KEY         backend             admin-db itself,   │
│                                                       every agent       │
└────────────────────────────────────────────────────────────────────────┘
```

The pattern across all of them: whatever can *mint* or *decrypt* something
lives on exactly one service (the backend) and nowhere else. Everything an
agent holds can only *verify* — never forge, never decrypt.

`ADMIN_DB_ENCRYPTION_KEY` specifically must never be set on admin-db itself
(it isn't a Postgres setting at all, and admin-db has no use for it) and
never on an agent (agents never touch admin-db or its encrypted columns
directly — only the backend does, through the admin API).

## Bootstrap fallback vs. DB-authoritative

Secret #2 has two possible sources. Which one is authoritative depends on
whether admin-db has an active key:

- **Default (no `USER_IDENTITY_PRIVATE_KEY`)**: at startup the backend calls
  `ensure_active_signing_key()` (`backend/app/signing_keys.py`). When admin-db
  has no active key, it creates and activates one, under a Postgres advisory
  lock so that the workers create one key only. When
  `ADMIN_DB_ENCRYPTION_KEY` is missing or unusable, it logs a warning and the
  backend boots without a DB key.
- **`USER_IDENTITY_PRIVATE_KEY` set**: the startup step creates nothing.
  `mint_for_user()` uses the static key (hand-generated,
  `prometheus-identity-keygen` or `openssl`) until an admin activates a key
  under Admin > Signing Keys.
- **After a key is active in admin-db** (created at startup or by an admin):
  Postgres becomes authoritative. `mint_for_user()` prefers the active
  `SigningKey` row, cached in-process for ~60s (invalidated immediately on
  the next activate/retire, so rotation doesn't wait out the cache). The env
  var is not read again unless every DB key is retired with none active.

This is a one-way trapdoor in normal operation, not a toggle: once a key
exists in admin-db and is active, it wins every time, permanently, until an
admin retires it with no replacement (which the admin API refuses — see
`backend/app/routers/admin_keys.py` — specifically so `mint_for_user()` is
never silently pushed back onto a possibly-unconfigured env var mid-flight).

## Key rotation and the JWKS_URL recommendation

Every agent verifying the identity JWT (secret #2's public half) can do so
two ways:

- **`USER_IDENTITY_PUBLIC_KEY`** — a static value. Works, but has no way to
  observe a key rotated through the admin UI. After a rotation, every agent
  still pinned to the old public key starts rejecting tokens the moment the
  old key is retired (or sooner, if `kid` mismatches strictly) — the operator
  must manually redistribute the new key to every agent, including
  third-party ones.
- **`JWKS_URL`, pointed at the platform backend's own `GET
  /.well-known/jwks.json`** (recommended) — the backend serves every key in
  admin-db (active and recently-retired) as an RFC 7517 keyset, unauthenticated
  (it's public key material only). `PyJWKClient` on the verifying side
  refreshes automatically on an unrecognized `kid`. An admin-UI rotation then
  needs **zero action on any agent**.

Every `PrometheusAgent` also still serves its *own* `GET /.well-known/jwks.json`,
built from that one agent's own env vars (unchanged, pre-dates the admin
UI). It's still useful for an admin-db-less deployment, but it can never
reflect a DB-driven rotation — prefer the backend's endpoint. See
`prometheus_api/docs/agent/IDENTITY_KEY_MANAGEMENT.md` for the full
agent-side picture (this page is the platform-side companion to it).

## What breaks if a secret is lost or rotated

| Secret | Lost | Rotated |
|---|---|---|
| `BACKEND_JWT_SECRET` | Every session cookie fails verification — everyone is logged out. No stored data is affected (nothing is encrypted with it). | Same as lost — rotating it *is* forcing global re-login by design. |
| Identity signing key | Agents can no longer verify new tokens once the old key is gone from the JWKS; already-issued tokens verify until they expire, then fail. | Zero-downtime via the admin UI + `JWKS_URL` (see above); manual and disruptive via static `USER_IDENTITY_PUBLIC_KEY`. |
| `ADMIN_DB_ENCRYPTION_KEY` | Every `SigningKey.private_key_encrypted` and `OidcProvider.client_secret_encrypted` row becomes permanently undecryptable (`EncryptionError`, `app/crypto.py`) — the ciphertext is still in the table, but nothing can read it back. Recovery is regenerating signing keys and re-entering every OIDC provider's client secret, not data recovery. | Same failure mode as losing it, for every row encrypted under the *old* key — re-encrypting existing rows under a new key isn't automated (see `docs/dev-docs/multi-user-setup.md` for the operational note). New rows written after rotation are fine. |
| Local password hash | N/A — nothing to lose; it's derived, not stored reversibly. | N/A — "rotating" a password hash is just a user changing their password. |

`ADMIN_DB_ENCRYPTION_KEY` is the one secret in this list that is **not**
optional the moment you use signing keys or OIDC providers, but is easy to
forget because local-password login works fine without it. `make up`/`make
restart` generate one into `.env` automatically if it's blank (see
`scripts/init_env.py`) — see it once, in `.env`, and
back that file up; there's no recovery path for encrypted rows without it.

## Cross-references

- `docs/docs/dev-docs/multi-user-setup.md` — operational guide: first-run
  setup, the admin UI, OIDC provider configuration, env var reference.
- `prometheus_api/docs/agent/IDENTITY_KEY_MANAGEMENT.md` — agent-author
  reference for RS256 key generation, third-party integration, and rotation
  from the *verifying* side.
- `prometheus_api/docs/agent/MULTI_USER.md` — the identity JWT flow and
  per-user credential broker, from the agent-author side.
- `backend/app/crypto.py`, `backend/app/passwords.py`, `backend/app/identity.py`,
  `backend/app/signing_keys.py` — the actual implementation of secrets #2–#4.
