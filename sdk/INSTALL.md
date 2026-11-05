# Installation

There are three supported ways to use `prometheus-api`, in order of preference:

1. **[Container](#container-recommended)** — pull a published image and run it. Easiest path; no Python toolchain required.
2. **[Library](#library)** — install the package into your own Python environment.
3. **[Development checkout](#development)** — clone the repo and use `uv` to work on `prometheus-api` itself.

---

## Container (recommended)

Multi-arch images (`linux/amd64`, `linux/arm64`) are published to the GitHub Container Registry after every green CI run on `devel`:

```bash
docker pull ghcr.io/idaholab/prometheus_core/prometheus_sdk-devel:20261031-b999096
```

Tags are `<commit date>-<7 char sha>` of the `devel` commit the image was built from. The [package page](https://github.com/idaholab/prometheus_core/pkgs/container/prometheus_core%2Fprometheus_sdk-devel) lists them; the platform pins one with `PROMETHEUS_API_BASE_IMAGE_HASH` in [`platform/Makefile`](../platform/Makefile).

Run the image, mounting a `.env` based on `.env.example` so DeepLynx credentials are available:

```bash
docker run -it --rm \
  --env-file .env \
  ghcr.io/idaholab/prometheus_core/prometheus_sdk-devel:20261031-b999096 /bin/bash
```

### Building the image locally

To use the SDK as it is in your checkout instead, build the image from this directory into your local Docker image store:

```bash
make build-local                     # → prometheus_api:local (host architecture)
```

The image trusts the CA certificates in [`common/certs`](../common/certs/README.md) (the INL bundle by default). To trust your own, add them there before building.

The platform does this for you with `LOCAL_SDK=true` (see the [platform README](../platform/README.md#2-get-the-base-image)).

---

## Library

Install from the git repository into your own venv. Use `pip` or `uv pip`:

```bash
pip install "git+https://github.com/idaholab/prometheus_core.git#subdirectory=sdk"
```

To pin to a specific branch, tag, or commit:

```bash
pip install "git+https://github.com/idaholab/prometheus_core.git@<ref>#subdirectory=sdk"
```

After installing, sanity-check the import:

```bash
python -c "from prometheus_api.storage_client import StorageClient; from prometheus_api.agent import PrometheusAgent; print('ok')"
```

Then copy `.env.example` to `.env` and fill in your DeepLynx credentials (see `README.md` for the variable reference).

---

## Development

The project is `uv`-managed. To work on `prometheus-api` itself:

```bash
git clone https://github.com/idaholab/prometheus_core.git
cd prometheus_core/sdk
uv sync
make check    # ruff + mypy
make test     # pytest (unit only; integration tests need .env)
make hooks    # optional: install local pre-commit/pre-push checks
```

`uv sync` creates `.venv/` and installs everything from `uv.lock`, including the `dev` dependency group. Run any tool through `uv run` (e.g., `uv run pytest tests/test_models.py`) or use the Makefile targets.

For architecture, conventions, and the full list of common commands, see [DEVELOPMENT.md](DEVELOPMENT.md).
