# Muninn Specialist Agent

This package is the Prometheus Platform deployment wrapper for Muninn.

It intentionally owns only:

- the platform launcher in `agent.py`
- the platform agent card in `agent_card.json`
- the environment-rendered runtime config template
- the Dockerfile and Compose wiring

The actual Prometheus runtime implementation stays in the `muninn` package and
is installed into the image from Jack's fork at the pinned `MUNINN_GIT_REF`.
That ref pin is temporary while the Prometheus packaging work lives outside the
main Muninn repo.

## Build contract

- base image: `mooseharbor.hpc.inl.gov/prometheus_api/prometheus_api-py312:${PROMETHEUS_API_BASE_IMAGE_HASH}`
- package install source: `muninn` from `github.inl.gov/jack-cavaluzzi/muninn`
- dependency auth: Docker BuildKit SSH forwarding (`build.ssh: [default]`)

The Muninn package brings in its pinned `moosenger` dependency transitively.
`prometheus_api` is not reinstalled in this image; it comes from the base image.

## Local runtime data

Persistent runtime state for the container lives under:

- `runtime/muninn/vector_data`
- `runtime/muninn/.moosenger_fs`

Those directories are bind-mounted into the container and intentionally kept
inside `prometheus_platform` so the deployment does not depend on sibling repo
checkouts at runtime.
