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
  - **macOS without Docker Desktop**: if your organization does not license
    Docker Desktop, Colima runs the stack instead. See
    [Running without Docker Desktop](#running-without-docker-desktop-macos)
    below — it installs entirely under `$HOME` and needs no admin rights.
- `make` and `openssl`. A minimal distro or WSL image may have neither.
- An API key for one of the supported LLM providers.

**Free these host ports first: 5150, 8600, 6379, 3000, 5000, 8180.** The two
that usually collide are DeepLynx's 3000 and 5000: if you already run DeepLynx
yourself, stop it (`docker compose -p deeplynx down`) before continuing, since
the two cannot both bind those ports. Docker Desktop reports the clash as
`ports are not available: ... /forwards/expose returned unexpected status: 500`,
which does not name the conflict.

## Running without Docker Desktop (macOS)

Docker Desktop is the licensed product; the `docker` CLI (Apache-2.0) and
[Colima](https://github.com/abiosoft/colima) (MIT) are not. Colima runs a small
Linux VM and exposes a Docker socket, which is all
`infrastructure/scripts/check-local-prereqs.sh` asks for: the `docker` command
on `PATH`, a daemon that answers `docker info`, and server version 24.0 or
newer.

Everything below installs under `$HOME`, so it works on a managed laptop where
you are in `staff` rather than `admin`, `/usr/local/bin` is not writable, and
there is no Homebrew. With Homebrew and admin rights, `brew install colima
docker docker-compose docker-buildx` replaces everything up to
[Start the VM](#start-the-vm).

The commands are written for Apple Silicon (`arm64`). On an Intel Mac,
substitute `x86_64` for `aarch64` in the download URLs and `amd64` for `arm64`.

### Directories

```bash
mkdir -p ~/.local/bin ~/.local/share ~/.local/libexec ~/.docker/cli-plugins
mkdir -p ~/Downloads/container-tooling/{docker,lima}
```

### Docker CLI

A static build of the client alone — no daemon, no Docker Desktop.

```bash
cd ~/Downloads/container-tooling/docker
curl -fsSLO https://download.docker.com/mac/static/stable/aarch64/docker-29.9.3.tgz
tar -xzf docker-29.9.3.tgz
install -m 755 docker/docker ~/.local/bin/docker
```

### Lima

Colima drives [Lima](https://github.com/lima-vm/lima), which it does not
bundle. The tarball's `bin`, `libexec` and `share` directories have to keep
their relative layout, or `limactl` cannot find its guest agents.

```bash
cd ~/Downloads/container-tooling/lima
curl -fsSLO https://github.com/lima-vm/lima/releases/download/v2.2.1/lima-2.2.1-Darwin-arm64.tar.gz
tar -xzf lima-2.2.1-Darwin-arm64.tar.gz
cp -R bin/. ~/.local/bin/
cp -R libexec/. ~/.local/libexec/
cp -R share/. ~/.local/share/
```

**Install Colima and Lima as a matched pair.** Colima 0.10.3 expects Lima
2.2.1 — the versions Homebrew ships together. Pairing a 0.10.x Colima with a
Lima 1.x tarball is the usual self-inflicted failure here.

**Run `colima stop` before repeating these copies.** While the VM is up, two
`limactl` processes (`usernet` and `hostagent`) are executing from
`~/.local/bin/limactl`. Overwriting that file in place invalidates its code
signature, and macOS then kills every later run:

```
zsh: killed     limactl --version
```

The file is not corrupt — `shasum` matches and `codesign --verify` passes —
so the error is misleading. Writing a *new* file at the path fixes it, with
or without the VM running:

```bash
rm -f ~/.local/bin/limactl
cp ~/Downloads/container-tooling/lima/bin/limactl ~/.local/bin/
```

`rm` only unlinks, so the running processes keep the old copy and the VM is
undisturbed. The same applies to `docker` and `colima` if you reinstall them
while the VM is up.

### Colima

```bash
curl -fsSL -o ~/.local/bin/colima \
  https://github.com/abiosoft/colima/releases/download/v0.10.3/colima-Darwin-arm64
chmod 755 ~/.local/bin/colima
```

### The Compose and buildx plugins

The static CLI ships with neither, and both are required: the Makefile drives
`docker compose`, and `make base-image` passes `--build-context`, which only
BuildKit understands.

```bash
curl -fsSL -o ~/.docker/cli-plugins/docker-compose \
  https://github.com/docker/compose/releases/download/v5.7.0/docker-compose-darwin-aarch64
curl -fsSL -o ~/.docker/cli-plugins/docker-buildx \
  https://github.com/docker/buildx/releases/download/v0.38.2/buildx-v0.38.2.darwin-arm64
chmod 755 ~/.docker/cli-plugins/docker-{compose,buildx}
```

Skip buildx and the SDK build fails at `unknown flag: --build-context`, after a
`DEPRECATED: The legacy builder is deprecated` warning that reads like noise
but is the actual cause — without the plugin the CLI silently falls back to the
legacy builder.

### PATH

Add to `~/.zshrc`, then open a new terminal:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Check all four separately, so one failure does not hide the rest:

```bash
docker --version
colima version
limactl --version
docker compose version
```

### Start the VM

```bash
colima start --cpu 6 --memory 8 --disk 100 --vm-type vz --mount-type virtiofs
```

Colima's defaults of 2 CPUs and 2 GB are far too small for this stack — it
runs fifteen containers with the debug agents and local DeepLynx. `--vm-type
vz` uses Apple's Virtualization framework (macOS 13+), which is faster than
the QEMU default.

**On a 16 GB machine, 8 GB to the VM leaves macOS about 8 GB.** Drop to
`--memory 6` if the host starts swapping during the build.

Colima points the `docker` CLI at the VM itself by creating and selecting a
`colima` context, so nothing else needs configuring. Confirm with:

```bash
docker info
```

The SDK base image and the DeepLynx v0.8.0 images both publish `arm64`
manifests, so nothing here is emulated. Colima registers amd64 emulation at
startup anyway, so an amd64-only image would still run, slowly.

`colima stop` reclaims the memory when you are done; after a reboot, plain
`colima start` remembers the sizing above.

### Turn off AirPlay Receiver

**macOS listens on port 5000 itself.** AirPlay Receiver binds it on every
interface, so DeepLynx's port is taken before the stack starts. Turn it off in
**System Settings → General → AirDrop & Handoff → AirPlay Receiver**.

Left on, `make up` reaches DeepLynx, hangs for five minutes, and fails:

```
 ✔ Container prometheus_platform-deeplynx-ui-1       Healthy
[ERROR] DeepLynx didn't answer at http://localhost:5000/api/v1/health within 300s.
```

Every container reports `Healthy` because DeepLynx is fine — the check never
reaches it. `docker-compose.deeplynx.yml` publishes the API on IPv4 only
(`127.0.0.1:5000:5000`), but `scripts/deeplynx_setup.py` asks for
`http://localhost:5000`, and `localhost` resolves to IPv6 `::1` first. AirPlay
answers there with `403`, so the script never falls back to IPv4 and retries
that same `403` until it times out.

`lsof` names the culprit — `ControlCe` is AirPlay, inside Control Center:

```bash
lsof -nP -iTCP:5000 -sTCP:LISTEN
```

Both listeners are visible at once, which is what makes this confusing:

```bash
# quote the IPv6 URL: zsh treats the brackets as a glob pattern
curl -so /dev/null -w '%{http_code}\n' 'http://[::1]:5000/api/v1/health'  # 403
curl -so /dev/null -w '%{http_code}\n' 'http://127.0.0.1:5000/api/v1/health'  # 200
```

If your organization locks that setting, set `DEEPLYNX_SERVER_PORT=5050` in
`.env` instead; the Makefile passes it to the setup script. The agents reach
DeepLynx over the Docker network and do not care. **The DeepLynx web UI does**
— it calls `localhost:5000` from the browser, baked in at build time, so on
any other port the UI at http://localhost:3000 stops working. Turning AirPlay
Receiver off is the only fix that leaves the whole stack working, since the
browser resolves `::1` first too.

From here, continue with [1. Clone](#1-clone).

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

If `make up` stops with `container prometheus_platform-backend-1 is unhealthy`
and the backend logs say `password authentication failed for user "admin"`, an
older admin-db volume is still using a previous `ADMIN_DB_PASSWORD`. Postgres
keeps that password in the volume and ignores the one in `.env`. On WSL2 the
same failure often leaves the shell's working directory stale, so the next
`make` prints `getcwd: No such file or directory` and `scripts/init_env.py`
exits with `FileNotFoundError` even though the file is still there. Drop the
volumes, re-enter the directory, and start again:

```bash
make down-v
cd ..
cd platform
make up
```

`make down-v` deletes the platform volumes, including every local user and
conversation. The two `cd` commands are what clear the stale WSL directory;
the prompt can already say `platform` and still need them.

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

On Colima, `colima start` has to come before any of these after a reboot, and
`colima stop` gives the VM's memory back when you are done for the day.

Resetting goes in widening circles: `make oidc-reset` discards Keycloak's
users, `make down-v` drops the platform's volumes, and `make clobber` deletes
admin-db and Valkey — every user, signing key, OIDC registration and
conversation — for reinstalling after `.env` was lost.
