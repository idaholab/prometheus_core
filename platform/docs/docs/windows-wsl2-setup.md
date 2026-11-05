# Windows + WSL2 setup

The platform runs under WSL2 the same way it runs on native Linux, but Docker
Desktop needs to be told to hand its daemon to your distro first. Do this
before working through the [Quickstart](../../README.md#quickstart).

## 1. Install Docker Desktop and enable WSL2 integration

Install [Docker Desktop for Windows](https://docs.docker.com/desktop/features/wsl/),
then turn on WSL2 integration:

![Docker Desktop General settings with "WSL2" selected as the Docker VMM](images/windows_wsl_docker_desktop_1.png)

In **Settings > Resources > WSL integration**, enable integration with your
default WSL distro (and any additional distro you run the platform from):

![Docker Desktop Resources > WSL integration, with the default distro and an additional distro enabled](images/windows_wsl_docker_desktop_2.png)

## 2. Restart WSL and Docker Desktop

Integration doesn't always take effect until both sides restart. From
PowerShell:

```powershell
wsl --shutdown
```

Close all open terminals, then quit Docker Desktop fully (not just the
window) and reopen it.

## 3. Verify the WSL distro can reach the Docker daemon

Open your WSL distro and confirm the socket is there and the client can talk
to the server:

```bash
ls -la /var/run/docker.sock
docker ps
docker info
```

`docker ps` returning an (empty) table and `docker info` printing both a
`Client:` and a `Server:` block confirms the distro is talking to Docker
Desktop's daemon. If `docker info` only shows `Client:` with no `Server:`
section, WSL integration isn't enabled for this distro yet — recheck step 1.

## 4. Install the remaining prerequisites inside WSL

These aren't WSL-specific, but a fresh distro is usually missing all three:

```bash
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# make (RHEL-based distros, e.g. Rocky/AlmaLinux)
sudo dnf groupinstall "Development Tools"

# openssl (RHEL-based distros)
sudo dnf install openssl
```

Debian/Ubuntu-based distros can substitute `sudo apt install build-essential openssl`.

## 5. Ports and files

- Docker Desktop forwards the published ports to Windows, so a Windows browser opens the stack on
  `localhost` (`5150` for the UI; with `LOCAL_DEEPLYNX=true` also `3000` for the DeepLynx UI and
  `5000` for its API). A Windows program already listening on one of those ports collides with
  the stack: stop it, or change the matching `*_PORT` in `.env` (DeepLynx's UI only works with
  its API on `5000`).
- Keep the clone in the WSL filesystem (for example `~/prometheus`), not under `/mnt/c`, and edit
  `.env` with an editor inside WSL. A Windows editor can save it with CRLF line endings, and then
  `make` doesn't read `LOCAL_SDK=true` or `LOCAL_DEEPLYNX=true` as `true`.

From here, continue with the main [Quickstart](../../README.md#quickstart).
