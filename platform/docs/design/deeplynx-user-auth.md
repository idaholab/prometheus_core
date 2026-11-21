# DeepLynx User Credentials Without a Second Login

| | |
| --- | --- |
| **Status** | Design, not built. |
| **Builds on** | [Credential Plane for Agents](credential-plane.md) (PPLT-31). This document defines the `deeplynx` resource there: its `idp_derived` and `oauth_link` auth modes and how each one gets a DeepLynx token for a user. |
| **Related** | [ADR-003 Agent-Scoped Credentials][adr-003] § 2.6, [User Proof Chain](user-proof-chain.md) |
| **DeepLynx source** | `deeplynx.helpers/Middleware/NexusAuthenticationMiddleware.cs`, `deeplynx.business/TokenBusiness.cs`, `deeplynx.business/OauthHandshakeBusiness.cs`, `deeplynx.business/OauthDeviceAuthorizationBusiness.cs` |

Prometheus uses DeepLynx as its storage engine. Today every agent and the backend
reach DeepLynx with one shared service API key (`DEEPLYNX_KEY` / `DEEPLYNX_SECRET`).
Every read and write runs as that service account. DeepLynx sees no user, and its
project permissions don't apply.

Both systems log users in through OIDC. The goal is to give each Prometheus user a
DeepLynx credential **without a separate DeepLynx login wherever the deployment
allows it**, and with at most a one-time link where it doesn't.

Two kinds of deployment are in scope:

- **Shared IdP.** Prometheus and DeepLynx use the same OIDC provider (for example
  one Okta authorization server, or one Entra tenant).
- **Separate IdPs.** Prometheus and DeepLynx use different providers (for example
  Prometheus on one Okta or Entra tenant, DeepLynx on another).

Readers: the platform developer who builds the `deeplynx` resource in the broker,
and the operator who configures a DeepLynx service instance.

## What DeepLynx accepts

The DeepLynx API takes a bearer token (header, `?token=` query or `access_token`
cookie). `NexusAuthenticationMiddleware` routes on the JWT `alg` and `iss`:

| Token | DeepLynx validates | Who issues it |
| --- | --- | --- |
| HS256 | Signature with `JWT_SECRET_KEY`, `jti` present and not revoked in `OauthTokens`, `apiKey` claim still exists for the user | DeepLynx itself: `POST /oauth/tokens` (key + secret), `POST /api/v2/oauth/exchange` (auth code), `POST /oauth/token` (device code or refresh token) |
| RS256, `iss == JWT_ISSUER` | JWKS from the issuer's discovery document, `aud == JWT_AUDIENCE`, lifetime | The OIDC provider DeepLynx is configured for |
| RS256, Entra issuer | JWKS of that issuer, plus the issuer and audience checks of the next DeepLynx release | Entra |

After validation DeepLynx takes an email from the claims (`ClaimsEmailExtractor`:
nameidentifier, `email`, `preferred_username`, `upn`, ..., `sub` if it looks like an
email). It upserts the `Users` row **by email** and adds the user to the default
organization. DeepLynx has no separate "DeepLynx account" step: a token that it
accepts is a DeepLynx login.

Two facts follow from this:

1. Any access token from DeepLynx's own IdP, with DeepLynx's audience, works at
   DeepLynx. Prometheus doesn't need DeepLynx to mint anything.
2. DeepLynx identifies a user by email. Whatever path is used, the email that
   DeepLynx sees decides whose data and permissions apply.

## The design in one paragraph

The `deeplynx` service instance (an admin-defined row in `service_instances`) gets
one of three auth modes. In `idp_derived`, the backend broker uses the user's
stored Plane 1 refresh token to get an access token for DeepLynx's audience, from
the same IdP or through a federated token exchange. The user does nothing beyond
the Prometheus login. In `oauth_link`, the user clicks **Connect DeepLynx** once.
DeepLynx's own OAuth server runs the consent, and usually SSO makes this one click.
The broker keeps the DeepLynx refresh token in Vault. `key_secret` stays as the
interim and dev mode. In every mode, agents get only a short-lived DeepLynx token
from the broker ([Credential Plane](credential-plane.md) § Agent flow), never a
refresh token or an IdP token for another audience.

**A DeepLynx link is mandatory.** Every Prometheus user must have a working link to
the deployment's **primary** DeepLynx instance. Artifacts and lineage are written
only there. The platform has no shared service-key fallback. Other DeepLynx
instances are **read-only** sources, and each one is linked separately (see
[Several DeepLynx instances](#several-deeplynx-instances)).

## Choosing the mode per deployment

```mermaid
flowchart TD
  Q1{"Does Prometheus log users in through<br/>DeepLynx's issuer (JWT_ISSUER)?"}
  Q1 -->|yes| A["Topology A: shared IdP<br/>idp_derived, strategy = refresh"]
  Q1 -->|no| Q2{"Does DeepLynx's IdP accept a token<br/>from Prometheus's IdP in a token exchange?<br/>(federation / trusted issuer)"}
  Q2 -->|yes| B["Topology B: federated IdPs<br/>idp_derived, strategy = token_exchange"]
  Q2 -->|no| C["Topology C: unrelated IdPs<br/>oauth_link (one-time Connect DeepLynx)"]
  A -.->|"dev stack, local OIDC provider"| D["key_secret"]
  C -.->|"until DeepLynx returns refresh tokens"| D
```

| Topology | Example | Mode | User action | Needs a DeepLynx change? |
| --- | --- | --- | --- | --- |
| A. Shared IdP | Both on Okta auth server `https://idp.example/oauth2/aus123`, or both in one Entra tenant | `idp_derived` (`refresh`) | None | No |
| B. Federated IdPs | Prometheus on Entra tenant X, DeepLynx on Okta, and Okta trusts tenant X as a token-exchange issuer | `idp_derived` (`token_exchange`) | None | No (IdP configuration only) |
| C. Unrelated IdPs | Prometheus on Okta org 1, DeepLynx on Entra tenant Y, no trust between them | `oauth_link` | One click on **Connect DeepLynx**, then a DeepLynx login if the browser has no session there | Yes, for silent renewal: see [DeepLynx gaps](#deeplynx-gaps) |
| Dev | Local OIDC provider, DeepLynx with `DISABLE_BACKEND_AUTHENTICATION` | `key_secret` | Paste key and secret once | No |

The admin picks the mode when registering the instance. The broker never guesses
the topology at run time.

### The INL deployment: topology C

Prometheus logs in through `https://identity-preview.inl.gov` and DeepLynx through
`https://identity.inl.gov`. The public discovery documents
(`/.well-known/openid-configuration`, checked 2026-11-21) show:

- Both issuers are **Okta org authorization servers**: the `issuer` is the bare
  host, not `/oauth2/<id>`.
- They are **separate Okta orgs**: their JWKS (`/oauth2/v1/keys`) have different
  key IDs. A token from one never validates at the other.
- Both list `urn:ietf:params:oauth:grant-type:token-exchange`. Okta supports token
  exchange only between apps under one custom authorization server of one org,
  so it doesn't bridge two orgs.

So INL is **topology C**, and DeepLynx uses `oauth_link`. Topology B would need the
Okta admins to federate the two orgs (Org2Org) *and* to accept the other org's
tokens in a token exchange. That is not an available configuration as far as this
design knows (open question 1).

**Finding `JWT_ISSUER` and `JWT_AUDIENCE`** for a DeepLynx deployment, in order of
reliability:

1. The DeepLynx API deployment's environment: `kubernetes/sandbox.yaml` and
   `development.yaml` take both from `${JWT_ISSUER}` / `${JWT_AUDIENCE}`, so the
   values are in the deployment's secret or variable store. The DeepLynx team can
   read them out.
2. Decode an access token that DeepLynx accepts. Log in to the DeepLynx UI; the
   NextAuth session (`/api/auth/session`) carries `tokens.access_token`. Paste it
   into a JWT decoder and read `iss` and `aud`. It is an Okta-signed token, so this
   is safe to inspect locally but must not be shared.
3. DeepLynx's sample `docker-compose.yaml` sets `JWT_AUDIENCE` to the issuer URL
   (`https://identity-preview.inl.gov`). That is the `aud` that an Okta org
   authorization server puts in access tokens, so the production values are most
   likely `JWT_ISSUER = JWT_AUDIENCE = https://identity.inl.gov`.

If (3) holds, it matters for security: an org authorization server gives **every**
app in the org access tokens with the same `aud`. Any INL Okta app's access token
then authenticates at DeepLynx, and Okta documents org-server access tokens as
meant for Okta's own APIs, not for validation by other resource servers. This
design doesn't depend on it, because Prometheus never forwards an Okta token in
topology C. It is noted for the DeepLynx team (G6).

## Topology A: shared IdP

Prometheus and DeepLynx are two clients of one OIDC provider. The token Prometheus
needs is an ordinary access token for DeepLynx's API audience.

### Login (Plane 1)

At login the backend asks for the scopes that the `deeplynx` instance lists, plus
`offline_access`. The backend stores the refresh token in Vault at
`secret/data/idp/{sub}` ([Credential Plane](credential-plane.md) § Plane 1 token
retention). Today the OIDC callback
([`backend/app/security.py`](../../backend/app/security.py)) keeps only the
`id_token`, so this is the one change to the login path.

The `id_token` is never forwarded to DeepLynx. Its `aud` is Prometheus's client ID,
and DeepLynx rejects it.

### Issue

```mermaid
sequenceDiagram
  participant SA as agent
  participant BR as backend broker
  participant V as Vault
  participant IdP as shared IdP
  participant DL as DeepLynx
  SA->>BR: POST /internal/credentials/issue {resource: deeplynx} + WST
  Note over BR: grant, declaration, scope checks (credential-plane)
  BR->>BR: cache hit for (sub, instance) with > 5 min left?
  BR->>V: read secret/data/idp/{sub}
  BR->>IdP: grant_type=refresh_token, scope=<deeplynx scopes>
  IdP-->>BR: access_token (aud = DeepLynx), new refresh_token
  BR->>V: write rotated refresh_token
  BR-->>SA: {jwt_token, org_id, project_id, base_url, expires_at}
  SA->>DL: Authorization: Bearer <access_token>
  DL->>DL: iss/aud/JWKS, user by email
```

Per IdP:

- **Okta.** The audience belongs to the authorization server, not the client. The
  Prometheus client must use the **same custom authorization server** as DeepLynx
  (`JWT_ISSUER`, not the Okta org server). Then a refresh with DeepLynx's scopes
  returns a token that DeepLynx accepts. If the authorization server serves other
  APIs too, all of them accept that token. See
  [Security notes](#security-notes).
- **Entra.** A token is issued for one resource. The Entra refresh token is
  multi-resource, so the broker asks for `scope=api://<deeplynx-app-id>/.default`
  with the user's refresh token. The Prometheus app registration needs a delegated
  permission on the DeepLynx API, with admin consent. Entra's On-Behalf-Of grant
  does the same thing starting from an access token. The broker uses the refresh
  path, because it already holds the refresh token.

### Identity

Both sides see the same IdP account, so the email matches. DeepLynx normalizes
`@azuregov.inl.gov` to `@inl.gov`. The broker doesn't need to replicate that,
because it passes the IdP's token through unchanged.

## Topology B: federated IdPs

DeepLynx trusts only its own issuer, so a token from Prometheus's IdP can't be
used directly. Some IdP pairs can bridge this without user interaction. DeepLynx's
IdP is configured to accept the other IdP's tokens as a subject token in an RFC 8693
token exchange, and to issue its own access token for the DeepLynx audience in
return:

- Okta: token exchange with a trusted external issuer, on a custom authorization
  server.
- Entra: federated identity credentials or B2B guest accounts, which give a home
  tenant account a token for a resource tenant.
- Keycloak: external-to-internal token exchange with an identity-provider link.

The broker's issue path is topology A's with one more step:

1. Refresh the Plane 1 token at Prometheus's IdP (as in A), with the scope that the
   bridge expects as the subject token audience.
2. `POST <deeplynx-idp>/token` with
   `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`,
   `subject_token=<step 1 token>`, `subject_token_type=...:access_token` (or
   `id_token`, where the bridge needs that), `audience=<JWT_AUDIENCE>`, and the
   broker's client credentials at DeepLynx's IdP.
3. Return the result as in A.

**The email must match.** DeepLynx keys users by email. The exchanged token has to
carry the same email that the user has at DeepLynx. If the two IdPs map users
differently (another domain, a guest UPN such as `alice_example.com#EXT#@...`), the
bridge has to map the claim, or DeepLynx creates a second, empty user. The admin
test of the instance ([Admin setup](#admin-setup)) checks this with the admin's own
account.

Whether B is available depends on the IdP product, license tier and policy of the
deployment, not on Prometheus or DeepLynx. If it isn't available, the deployment is
topology C.

## Topology C: unrelated IdPs

When the IdPs don't trust each other, no protocol lets Prometheus mint a DeepLynx
identity silently, and none should. Something has to establish that Prometheus
user `alice` is DeepLynx user `alice@...`, and only the user can vouch for that,
by logging in to DeepLynx once. The design makes that a **one-time link**, not a
login per session.

DeepLynx already is an OAuth 2.0 authorization server for registered applications
(`OauthApplication`: client ID, client secret hash, callback URL). The admin
registers Prometheus as a DeepLynx OAuth application once. The instance then uses
`oauth_link`:

```mermaid
sequenceDiagram
  participant U as browser
  participant BE as Prometheus backend
  participant DUI as DeepLynx UI (/api/oauth/authorize)
  participant DIdP as DeepLynx's IdP
  participant DL as DeepLynx API
  U->>BE: Connected accounts: Connect DeepLynx
  BE-->>U: 302 DeepLynx /api/oauth/authorize?client_id&redirect_uri&state
  U->>DUI: authorize
  alt no DeepLynx session in this browser
    DUI-->>U: DeepLynx login page
    U->>DIdP: log in (SSO if a session exists)
  end
  DUI->>DL: /oauth/authorize with the user's IdP token
  DL-->>U: 302 redirect_uri?code&state
  U->>BE: /api/credentials/deeplynx/callback?code&state
  BE->>DL: POST /api/v2/oauth/exchange (code, client_id, client_secret)
  DL-->>BE: DeepLynx token (+ refresh token, see gaps)
  BE->>BE: Vault secret/data/deeplynx/<instance>/{sub}
```

After the link, the broker issues the same short-lived token shape as in A. If it
holds a DeepLynx refresh token, it renews through `POST /oauth/token`
(`grant_type=refresh_token`). The user sees **Linked as alice@...**, the DeepLynx
email from the token's `sub`, which the broker stores as `external_subject`.
**The two emails may differ**, and that is allowed. The DeepLynx account the user
linked is the source of truth for DeepLynx access; the Connected accounts view
shows both.

Because the link is mandatory, the platform drives it:

- **First login.** After the Prometheus login, the backend checks the link to the
  primary instance. If there is none, the UI shows a blocking **Connect DeepLynx**
  step before the chat opens. The user completes one DeepLynx (Okta) login, or none
  if the browser already has an `identity.inl.gov` session.
- **Expired or revoked link.** When a refresh fails (`invalid_grant`), the broker
  marks the link `expired` and returns `not_linked`. The running agent pauses with
  the existing credential INPUT_REQUIRED path, and the card offers
  **Reconnect DeepLynx** in place of the grant buttons. After the reconnect, the
  agent resumes.
- **Linking is per user, not per agent.** The per-agent grant of the credential
  plane still applies on top of the link.

A **device-code** variant (`POST /oauth/device/code`, user enters the code at
`/oauth/device/verify`) works with no redirect URI. It already returns a refresh
token (30 days, access token 480 min). It is the fallback when the DeepLynx UI
can't redirect back to the Prometheus backend, for example across network zones.

## DeepLynx gaps

These are the DeepLynx changes that would make topology C as smooth as A. None of
them blocks topologies A or B.

| # | Gap | Effect on Prometheus | Proposed DeepLynx change |
| --- | --- | --- | --- |
| G1 | The authorization-code exchange (`/oauth/exchange`) returns only an access token (default 480 min), with no refresh token | The link expires after 8 h; the user has to click Connect again | Return a refresh token, as the device flow already does (`OauthRefreshTokens`) |
| G2 | Each exchange and each refresh runs `CreateApiKey`, so every renewal adds an API key row for the user | Per-user key rows grow without bound under a broker that renews hourly | Reuse one key per (user, application), or delete the previous key on refresh |
| G3 | `/oauth/exchange` takes `client_secret` in the query string | The secret lands in access logs on both sides | Accept form-encoded `POST` bodies (RFC 6749 § 2.3.1) |
| G4 | Only one non-Entra issuer (`JWT_ISSUER`) | A DeepLynx shared by deployments with different Okta servers can't use topology A for all of them | A list of trusted issuers, each with its audience. Not planned for the next release; not needed at INL (topology C) |
| G5 | The device-flow refresh token doesn't rotate and has a fixed 30-day lifetime from issue (`LastUsedAt` is updated, `ExpiresAt` is not) | Every user re-links at least every 30 days, even when active; a leaked refresh token stays valid for its whole life | Rotate the refresh token on each use (return a new one, revoke the old one), with a sliding idle timeout and an absolute cap |
| G6 | With an Okta org authorization server, `JWT_AUDIENCE` is the org URL that every app in the org gets | Not a Prometheus problem in topology C; it widens who can call DeepLynx | A custom Okta authorization server with a DeepLynx-only audience |

The DeepLynx team is expected to take G1-G3 and G5, so the target is the
redirect flow with a rotating refresh token. Until G1 lands, `oauth_link` uses the
device flow, which already returns a refresh token; the redirect flow would need a
reconnect every 8 h. Until G2 lands, the broker caches a DeepLynx token per
(user, instance) until 5 minutes before expiry, so it renews at most every few
hours, not on every issue.

## Several DeepLynx instances

A deployment can read from several DeepLynx instances, but writes artifacts and
lineage to exactly one.

| | Primary instance | Secondary instances |
| --- | --- | --- |
| `service_instances.role` | `primary` (exactly one per deployment) | `read_only` |
| Link | Mandatory, enforced at first login | Linked on first use, through the same card as an expired link |
| Allowed actions (`allowed_scopes`) | `read_artifact`, `write_artifact`, `write_lineage` | `read_artifact` only; the broker refuses a write action with `scope_not_allowed` |
| Mode | Whatever its topology gives | Each instance has its own mode; they may differ |
| SDK default | `send_deeplynx_artifact` and the lineage writer always use it | Only when an agent asks for that instance by name |

The `read_only` role is a broker check, not only a convention: the issued token
for a secondary instance may still carry write rights at that DeepLynx, so the
broker refuses to issue it for a write action.

**`deeplynx://` URIs don't name an instance today.** The format is
`deeplynx://organizations/{org}/projects/{project}/items/{item}`
([`sdk/prometheus_api/storage_client/uri.py`](../../../sdk/prometheus_api/storage_client/uri.py)).
With one instance that is unambiguous. With several, a reader (an agent or the
backend's viewers) can't tell which instance an item URI points to. This design
proposes adding the instance name as the authority,
`deeplynx://<instance>/organizations/...`, and reading a URI without one as the
primary instance. That keeps every URI written so far valid. It is a separate SDK
change (open question 3).

## Rejected: DeepLynx trusts Prometheus as an issuer

DeepLynx could accept Prometheus's own RS256 identity JWT
([`backend/app/identity.py`](../../backend/app/identity.py)) as a trusted issuer.
Topology C would then work without a link. This is rejected:

- Prometheus would become an identity provider for DeepLynx. A compromised
  Prometheus backend could act as any DeepLynx user, including users who never
  used Prometheus.
- The Prometheus `sub` is a username and not an email. DeepLynx would need a new
  identity mapping.
- It needs G4 and a DeepLynx change anyway, and it removes the user's own consent
  step that topology C relies on.

If a deployment explicitly wants it (one operator runs both systems and accepts
the trust), it can be a fourth mode later. Nothing in this design blocks it.

## Admin setup

The `deeplynx` service instance (`service_instances` +
`service_types.deeplynx`, see [Credential Plane](credential-plane.md) § Data model)
holds:

| Field | `idp_derived` / `refresh` | `idp_derived` / `token_exchange` | `oauth_link` | `key_secret` |
| --- | --- | --- | --- | --- |
| `base_uri` | yes | yes | yes | yes |
| `role` (`primary` or `read_only`) | yes | yes | yes | yes |
| `plane1_provider_id` (the Prometheus `OidcProvider` it derives from) | yes | yes | – | – |
| `scopes` (added to the Plane 1 login) | yes | yes (subject audience) | – | – |
| `token_endpoint`, `audience` | – | DeepLynx IdP's | – | – |
| `client_id`, `client_secret` | – | broker's client at DeepLynx's IdP | Prometheus's DeepLynx OAuth application | – |
| `ui_base_uri` (DeepLynx UI, for `/api/oauth/authorize`) | – | – | yes | – |
| Default `org_id`, `project_id` | yes | yes | yes | user-supplied |

**Test instance** (admin view): the backend runs the mode with the admin's own
account and calls `GET /api/v2/users/current`. It reports the issuer,
the audience and the email that DeepLynx resolved. This catches a wrong
authorization server (A), a claim-mapping mismatch (B) or a bad callback URL (C)
before users see it.

A user who logged in through a different Plane 1 provider than
`plane1_provider_id` can't use an `idp_derived` instance. Because the primary link
is mandatory, a deployment whose users log in through several Plane 1 providers
registers its primary instance as `oauth_link`, which works for every user.

## Security notes

- **Audience isolation.** In topology A the agent receives an IdP access token. If
  the IdP authorization server serves several APIs with one audience (for example
  Okta's `api://default`), that token also works at those APIs. Each DeepLynx
  deployment should have its **own audience** (a dedicated Okta authorization server
  or an Entra app ID URI). The admin test warns when `audience` matches a well-known
  shared default.
- **Agents never get refresh tokens** or Plane 1 tokens. They get a DeepLynx-audience
  access token of at most the IdP's lifetime (typically 60 min), or a DeepLynx HS256
  token that the broker requests with `expiration` ≤ 60 min, for one operation.
- **Revocation.** Logout and unlink delete the Vault entry and revoke the upstream
  refresh token (the IdP's `revocation_endpoint`; DeepLynx
  `DELETE /api/v2/oauth/tokens/revoke` for DeepLynx-issued tokens). An IdP account that is
  disabled fails the next refresh, so derived DeepLynx access ends within one token
  lifetime.
- **DeepLynx permissions apply.** The user gets what DeepLynx grants their linked
  account. The WST `bindings` ([Credential Plane](credential-plane.md) § WST) narrow
  it to one project per run but can't widen it. With no service-key fallback, a
  user can't see an artifact in a DeepLynx project they have no access to, even
  when another user's agent posted it into a shared conversation. The viewer shows
  `No access in DeepLynx` for that artifact.

## Rollout

Each step is mergeable on its own. The service-key path keeps working until step
8, behind `DEEPLYNX_USER_CREDENTIALS`; step 8 removes it, because the link is
mandatory. INL (topology C) needs steps 3, 4, 5, 7 and 8, with step 5 before
step 4. Steps 1, 2 and 6 serve shared-IdP and federated deployments.

| Step | Area | What | Depends on |
| --- | --- | --- | --- |
| 1 | backend | Plane 1 token retention (only for `idp_derived` deployments): request `offline_access` + instance scopes, store the refresh token in Vault, revoke on logout | PPLT-31 step 2 (Vault, tables) |
| 2 | backend | `deeplynx` issuer for `idp_derived` / `refresh`, with the per-(user, instance) token cache and the admin test | 1 |
| 3 | sdk | `ConnectionConfig.from_credential` already passes `jwt_token` through as an opaque bearer, so an RS256 IdP token works unchanged. Add: on a 401, `AsyncStorageClient` asks the broker again, instead of calling `/oauth/tokens` | PPLT-31 step 1 |
| 4 | platform | The first agent on the broker for DeepLynx (PPLT-31 step 4), behind `DEEPLYNX_USER_CREDENTIALS=1` | 3, and 2 or 5 |
| 5 | backend | `oauth_link` for DeepLynx: the callback route, the Connect button, the device-code fallback | PPLT-31 step 3 (views) |
| 6 | backend | `idp_derived` / `token_exchange` | 2, and a deployment that needs it |
| 7 | sdk + platform | Instance-qualified `deeplynx://<instance>/...` URIs, the `role` check in the broker, reads from secondary instances | 5 |
| 8 | platform | The first-login Connect DeepLynx gate; backend DeepLynx calls (`uri_resolver.py`, uploads, mesh service) use the user's credential; remove `DEEPLYNX_KEY` / `DEEPLYNX_SECRET` from agents and the backend | 4, 5 |

## Decisions (2026-11-21)

- **INL topology.** Prometheus uses `identity-preview.inl.gov`, DeepLynx uses
  `identity.inl.gov`: two Okta orgs, so INL is topology C (`oauth_link`).
- **The DeepLynx link is mandatory.** No shared service-key fallback, for agents
  or for the backend.
- **The DeepLynx email may differ** from the Prometheus email. The linked DeepLynx
  account is authoritative for DeepLynx access.
- **Several instances, one writer.** Reads may come from several DeepLynx
  instances; artifacts and lineage are written only to the primary instance.
- **DeepLynx gaps.** The DeepLynx team is expected to take G1-G3 (and G5). Several
  trusted issuers (G4) are not expected in the next release.

## Open questions

| # | Question | Who decides | Blocks |
| --- | --- | --- | --- |
| 1 | Confirm the production `JWT_ISSUER` and `JWT_AUDIENCE` of DeepLynx (see [Finding them](#the-inl-deployment-topology-c)). If they are the org URL, does the DeepLynx team want a custom authorization server (G6)? Do the INL Okta admins rule out org-to-org federation with token exchange (topology B)? | DeepLynx team, INL Okta admins | Nothing in Prometheus; confirms that topology C is the right choice |
| 2 | Prometheus's OAuth application in DeepLynx: who registers it (client ID, secret, callback URL) for each Prometheus environment (dev, preview, production), and must the callback be on an `inl.gov` host? | DeepLynx team | Step 5 |
| 3 | The instance-qualified `deeplynx://<instance>/...` URI: accept the proposal, or keep the instance elsewhere (for example in `ArtifactReference.metadata`)? | prometheus_api owner | Step 7 |
| 4 | Is a link to a secondary (read-only) instance also mandatory, or linked on first use as proposed? | Platform Technical Lead | Step 7 |
| 5 | Do Prometheus users who have no DeepLynx account yet get one? DeepLynx auto-provisions on first login, but only into the default organization. Who adds them to the project that Prometheus writes to? | DeepLynx team, Platform Technical Lead | Step 8 (first-login gate) |
| 6 | Service work without a user (scheduled jobs, the debug agents, the `PROMETHEUS_DEBUG` stack): do they keep a DeepLynx service account, outside the user credential path? | Platform Technical Lead | Step 8 |

[adr-003]: https://nstinl.atlassian-us-gov-mod.net/wiki/spaces/Prometheus/pages/34866140
