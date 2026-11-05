# Local OIDC provider

The login page can offer single sign-on buttons next to the username and
password form, but only once an identity provider is registered. This runs a
[Keycloak](https://www.keycloak.org/) next to the platform to be that provider,
so the OIDC flow can be exercised end to end without a real one.

For local use only. The realm, its client secret and its test user are fixed in
this repository, and the Keycloak admin password defaults to `admin`.

## Start it

Keycloak joins the platform's Docker network, so start the platform first:

```
cd platform
make up
make oidc-up
```

`make oidc-up` starts Keycloak and its Postgres from
`docker-compose.oidc.yml` and waits until both are healthy. The first start
takes a little longer, while Keycloak runs its database migrations and imports
`keycloak/realm-prometheus.json`.

Keycloak then serves its admin console at http://localhost:8180 (`admin` /
`admin`). Like the local DeepLynx, the port is published on `127.0.0.1`, so
only your own machine reaches it. `KEYCLOAK_PORT`, `KEYCLOAK_ADMIN`,
`KEYCLOAK_ADMIN_PASSWORD` and `KEYCLOAK_DB_PASSWORD` in `.env` override the
defaults.

It runs as its own Compose project (`<project>_oidc`), so `make down` and
`make restart` leave it running. Stop it with `make oidc-down`, which keeps the
realm, or `make oidc-reset`, which deletes Keycloak's database so the realm
file is imported again on the next start.

## Point the platform at it

Two things are needed: the backend has to know its own browser-facing address,
and an admin has to register the provider once.

### 1. Set `BACKEND_PUBLIC_URL`

In `.env`:

```
BACKEND_PUBLIC_URL=http://localhost:5150
```

The backend sends a `redirect_uri` to the provider and has no other way to know
what address the browser used to reach it: `request.base_url` is whatever the
Vite dev server or nginx used internally. The value must match what the
provider has registered, byte for byte. `keycloak/realm-prometheus.json`
registers `http://localhost:5150/api/auth/callback/keycloak`, so use
`http://localhost:5150` while the dev frontend is the way in. Restart the
backend afterwards.

### 2. Register the provider

Sign in as an admin, go to **Admin → Identity Providers**, add a provider, and
fill in:

| Field | Value |
| --- | --- |
| Provider ID | `keycloak` |
| Display name | `Keycloak` |
| Issuer URL | `http://keycloak:8080/realms/prometheus` |
| Client ID | `prometheus-platform` |
| Client secret | `local-dev-only-not-a-real-secret` |
| Scopes | `openid profile email` |
| Default role | `user` |

The provider ID is part of the callback URL
(`<BACKEND_PUBLIC_URL>/api/auth/callback/<provider_id>`), so it has to be
exactly `keycloak` to match the redirect URI in the realm file. It cannot be
changed after the provider is created.

The issuer URL is the **container** address, not `localhost:8180`: it is the
backend that fetches the discovery document, over the Docker network. See
"Why two addresses" below.

The provider is stored in `admin-db` with its client secret encrypted, so it
survives restarts. `make down-v` and `make clobber` remove it.

## Sign in

Log out, and the login page now shows a **Sign in with Keycloak** button below
the password form. The realm has one user:

| Username | Password |
| --- | --- |
| `prometheus` | `prometheus` |

On the first sign-in the backend creates a matching platform account from the
ID token's claims, with the provider's default role. Later sign-ins reuse it
and refresh the email and display name.

## Why two addresses

Keycloak is reachable at `localhost:8180` from the browser and at
`keycloak:8080` from inside the Docker network, and a single OIDC provider has
to work for both. The browser cannot resolve `keycloak`, and the backend
container's `localhost` is itself.

The discovery document is what splits them. `KC_HOSTNAME` pins Keycloak's
*frontchannel* URLs — the issuer, and the authorization endpoint the browser is
redirected to — to `http://localhost:8180`. `KC_HOSTNAME_BACKCHANNEL_DYNAMIC`
then lets the *backchannel* URLs — the token endpoint and the JWKS URI, which
only the backend fetches — be whatever host asked for the document. Fetched
from the backend at `http://keycloak:8080/...`, discovery comes back as:

```
issuer                   http://localhost:8180/realms/prometheus
authorization_endpoint   http://localhost:8180/realms/prometheus/protocol/openid-connect/auth
token_endpoint           http://keycloak:8080/realms/prometheus/protocol/openid-connect/token
jwks_uri                 http://keycloak:8080/realms/prometheus/protocol/openid-connect/certs
```

Each URL is then reachable by whoever uses it. This works because the backend
takes the issuer it expects in the ID token from the discovery document rather
than from the configured issuer URL (`backend/app/oidc.py`), so the `iss` claim
the browser-facing issuer produces is the one it checks against.

A provider without that split needs one address that resolves the same way
everywhere, which on Windows means an entry in the hosts file.

## Troubleshooting

**"Invalid parameter: redirect_uri" on the Keycloak login page.** The
`redirect_uri` the backend sent is not the one the realm registered. Check that
`BACKEND_PUBLIC_URL` is `http://localhost:5150` with no trailing slash, that
the provider ID is `keycloak`, and that the backend was restarted after `.env`
changed.

**The button does not appear.** The provider is disabled, or
`GET /api/auth/providers` returns an empty list. Check it with
`curl -s localhost:8600/api/auth/providers`.

**"Could not fetch OIDC discovery document".** The backend cannot reach
Keycloak. Confirm the issuer URL is `http://keycloak:8080/realms/prometheus`
and that Keycloak is attached to the platform's network:
`docker compose -p <project>_oidc ps`.

**Sign-in works, but the account is named `keycloak:<uuid>`.** The ID token
carried no `preferred_username` or `email`, which means the provider's scopes
do not include `profile` and `email`.
