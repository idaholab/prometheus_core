# Platform settings

The platform settings file holds settings that the operator owns. In this release it holds one
section, `smtp`, which defines the SMTP servers the platform can send email through. The file is
optional. With no file, email is off and the platform runs normally.

The backend reads the file one time, at startup. An administrator can read the loaded result,
with no password values, at `GET /api/admin/email-settings`. `platform/backend/CONTRACT.md`
("Admin: email settings") gives the response shape.

## The file and its path

| Item | Value |
|---|---|
| File in the checkout | `platform/settings/platform-settings.yml` (gitignored) |
| Example in the checkout | `platform/settings/platform-settings.example.yml` (committed) |
| Mount | Compose mounts `./settings` read-only at `/app/settings`, on the `backend` service only |
| File in the container | `/app/settings/platform-settings.yml` |
| Path variable | `PROMETHEUS_SETTINGS_PATH`, default `/app/settings/platform-settings.yml` |

Git ignores every file in `platform/settings/` except the example. Your settings file and a CA
bundle in the same directory are never committed.

## Set up email

Run each command from the `platform/` directory.

1. Copy the example to the settings file:

    ```bash
    cp settings/platform-settings.example.yml settings/platform-settings.yml
    ```

2. Edit `platform/settings/platform-settings.yml` to keep only the configurations that you need.
3. For each configuration with a `password`, set its variable in the backend environment. Refer to
   [Passwords](#passwords).
4. Start the backend again. A new or changed password variable needs a new container:

    ```bash
    docker compose -p prometheus_platform -f docker-compose.yml up -d backend
    ```

    A stack started with extra compose files (`docker-compose.override.yml`, the generated
    `docker-compose.agents.yml`) needs the same `-f` flags.

5. Read the startup log of the backend. Refer to [Startup log](#startup-log).

The backend reads the file only at startup. After you change only the file, restart the backend:

```bash
docker restart backend
```

A change to the file needs no image rebuild. `docker restart` keeps the environment of the
container, so it does not apply a changed password variable. For a changed password variable, run
this command from `platform/`:

```bash
docker compose -p prometheus_platform -f docker-compose.yml up -d backend
```

A stack started with extra compose files (`docker-compose.override.yml`, the generated
`docker-compose.agents.yml`) needs the same `-f` flags. Do not use `make restart` or `make up` for
this change, because they clear the LiteLLM database.

## The `smtp` section

The file is a YAML mapping. The backend reads only its `smtp` key and ignores all other top-level
keys. The `smtp` section has two keys, and no others:

- `configurations`: a map of named SMTP configurations. It must have one or more entries.
- `default`: the name of the configuration that the platform uses. You can omit it only when
  `configurations` has exactly one entry.

This example is the committed example file:

```yaml
smtp:
  default: relay            # optional when exactly one configuration exists
  configurations:
    relay:
      host: smtp.example.org
      port: 25                  # default 587
      security: none            # none | starttls | ssl; default starttls
      from_address: prometheus@example.org
      from_name: Prometheus     # optional
      verify_tls: true          # default true
      ca_bundle: /app/settings/relay-ca.pem   # optional; PPLT-131 reads it
    mailpit:
      host: mailpit
      port: 1025
      security: none
      from_address: dev@example.com
      username: dev             # optional
      password: os.environ/SMTP_MAILPIT_PASSWORD   # optional; env reference only
```

### Configuration fields

The name of a configuration is its map key. A name has 1 to 64 characters of `a`-`z`, `0`-`9`
and `-`. A configuration accepts only the fields below. An unknown field makes the configuration
invalid.

| Field | Required | Rule | Default |
|---|---|---|---|
| `host` | yes | 1 to 255 characters, no whitespace | none |
| `port` | no | an integer from 1 to 65535 | `587` |
| `security` | no | `none`, `starttls` or `ssl` | `starttls` |
| `from_address` | yes | a valid email address | none |
| `from_name` | no | at most 255 characters | none |
| `username` | no | at most 255 characters | none |
| `password` | no | an environment reference only; refer to [Passwords](#passwords) | none |
| `verify_tls` | no | `true` or `false` | `true` |
| `ca_bundle` | no | a path, at most 512 characters | none |

The address check rejects a domain with no dot, such as `dev@localhost`. For a local test
address, use a domain such as `example.com`.

This release does not send email and does not read `ca_bundle`. PPLT-131 adds the send path and
the check that the `ca_bundle` file exists.

## Passwords

Never write a password in the settings file. Give a password only as a reference to an
environment variable of the backend:

```yaml
password: os.environ/SMTP_PASSWORD
```

The variable name must be `SMTP_PASSWORD` or `SMTP_<NAME>_PASSWORD`, for example
`SMTP_MAILPIT_PASSWORD`. `<NAME>` uses `A`-`Z` and `0`-`9`, in one or more parts joined by `_`.
These values make the configuration invalid:

- A literal password, for example `password: hunter2`.
- A reference to a variable with a different name, for example
  `password: os.environ/BACKEND_JWT_SECRET`.
- A reference to a variable that is not set, or that is empty.

The backend reads the value at startup and keeps it in memory only. The admin API and the log
never show the value.

### Give the backend a password variable

Compose forwards `SMTP_PASSWORD` to the backend, with an empty default. To set it, add this line
to `platform/.env`:

```bash
SMTP_PASSWORD=<smtp-password>
```

Compose does not forward an `SMTP_<NAME>_PASSWORD` variable. To forward one, add it to the
`backend` service in `platform/docker-compose.override.yml`. Git ignores this file, and Compose
includes it when it exists:

```yaml
services:
  backend:
    environment:
      SMTP_MAILPIT_PASSWORD: ${SMTP_MAILPIT_PASSWORD:-}
```

Then set `SMTP_MAILPIT_PASSWORD=<smtp-password>` in `platform/.env`. Run this command from
`platform/`:

```bash
docker compose -p prometheus_platform -f docker-compose.yml -f docker-compose.override.yml up -d backend
```

A stack started with other extra compose files (the generated `docker-compose.agents.yml`) needs
the same `-f` flags.

In production, the deployment fills these variables from its secrets vault (SR-7, ADR-001
Pattern A). The platform stores no SMTP password. Refer to
[Encryption & Keys](encryption-and-keys.md) for the other secrets of the platform.

## What a bad file does

The backend never fails to start because of the settings file. A problem turns email off, or
skips one configuration.

| Condition | Result |
|---|---|
| The file does not exist | Email is off. No error. |
| The file has no `smtp` section | Email is off. No error. |
| The file is not valid YAML, or is not a mapping | Email is off, with an error. |
| `smtp` is not a mapping, has an unknown key, or has no configurations | Email is off, with an error. |
| `default` is omitted and there are two or more configurations | Email is off, with an error. |
| `default` names no configuration in the file | Email is off, with an error. |
| A configuration breaks a field rule or a password rule | That configuration is invalid and is skipped. The other configurations load. |
| `default` names an invalid configuration | Email is off. The configuration shows its own error. |

Email is on only when `default` names a valid configuration. The admin API shows this as
`configured: true`.

## Startup log

At startup, the backend writes one `WARNING` line for a file error, and one `WARNING` line for
each invalid configuration:

```text
email: /app/settings/platform-settings.yml: smtp.default must name one of smtp.configurations
email: configuration mailpit is invalid: SMTP_MAILPIT_PASSWORD is not set
```

Then it writes one `INFO` summary line:

```text
email: 1 configurations, default relay, 1 invalid
```

With no file, the summary line is `email: 0 configurations, default None, 0 invalid`. No log line
contains a password value.

## Check the loaded settings

An administrator can read the loaded settings. The route returns `401` without a session, and
`403` for a user who is not an administrator. As an administrator, open the platform in the
browser, and run this in the browser console:

```javascript
fetch("/api/admin/email-settings").then((r) => r.json())
```

Each configuration shows `valid`, its `error`, `has_password` and `password_env`. The route returns
the state loaded at startup. It does not read the file again.
