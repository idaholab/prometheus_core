# 9 (future): Run the platform from pre-built images

> **Status: Not started**

## Goal

Run the platform from published images instead of building it, at the
version an agent repo pins: `./platformctl --set PLATFORM_SOURCE=image up`,
or `PLATFORM_SOURCE=image` in `.env`. An agent developer with a
`prometheus_core` submodule (step 7) gets exactly the platform their agent
was written for, without building it.

See `design.md`, "Where the platform's code comes from".

## Today

- `publish.yml` pushes `prometheus_sdk-devel`, `prometheus_backend-devel`
  and `prometheus_frontend-devel` to `ghcr.io/idaholab/prometheus_core`
  after each green run on `devel`, tagged `<commit date>-<7 char sha>`.
- The client-agent and the platform's own agents aren't published.
- The base-image pin (`PROMETHEUS_API_BASE_IMAGE_HASH`) is a separate value
  from the platform version, and points at a different registry
  (`containers.github.inl.gov`).

## Work

- **Publish what's missing:** the client-agent and the platform's in-tree
  agents (`publish.yml`), and release images without `-devel` once releases
  exist.
- **`PLATFORM_SOURCE=image`:** the compose target's `generate()` writes
  `docker-compose.images.yml` (an `image:` per published service, `build:`
  removed) and adds it to the entry file's `include`. The base compose files
  don't change.
- **Version to image tag:** from `platform_version()` (the checkout's or the
  submodule's commit) to the published tag. `PLATFORM_IMAGE_TAG` overrides
  it; `PLATFORM_IMAGE_REGISTRY` points a fork at its own registry.
- **Checks:** a `doctor` check that the images for the version exist, run
  before `up` pulls. Unpublished commits (e.g. a local branch) fail with a
  clear "no images for `<version>`; use `PLATFORM_SOURCE=build`".
- **Mixed mode:** services without a published image still build, so a
  developer can run published platform images with a local agent.
- **Labels stay off images:** `io.prometheus.platform.root` (a host path)
  is a container label set at run time, never baked into a published image.
- **The base image follows the version:** in image mode, the agents' base
  image comes from the same published `prometheus_sdk` tag, not the separate
  pin.

## Tests

- **Unit:** the generated images file per service; tag resolution; the
  missing-image check; mixed mode.
- **Live:** `up` from published images of a known tag (CI only, with
  registry access).

## Output

- `up` with `PLATFORM_SOURCE=image`: which images and tag it pulls, and
  which services still build; the summary shows the source and version.

## Replaces

- Building the platform's services for agent developers who only need a
  running platform (opt-in; `build` stays the default for platform
  development).

## Docs and slides

- **User guide:** `setup.md` gets "run from images"; `agents.md` gets the
  submodule plus images quick start.
- `platform/README.md`: running from images, and when to use it.
- `agent-template/` docs: the submodule plus `PLATFORM_SOURCE=image` as the
  quick start for a new agent repo.
- Hackathon: if images are published before an event, the setup slides
  (deck 03) and `environment.md` can drop the first long build. Rebuild the
  decks.

## What changes for you

- **Commands:** nothing changes unless you set `PLATFORM_SOURCE=image`.
- **Files created:** `docker-compose.images.yml` (generated) in image mode.
- **Roll back:** revert the PR, or set `PLATFORM_SOURCE=build`.

## Breaking changes

None: `PLATFORM_SOURCE` defaults to `build`.

## Prepared for in steps 1 to 7

- `PLATFORM_SOURCE` is a setting from step 1, with only `build`.
- `platform_version()` exists from step 1.
- How each service gets its image is decided in one place, the compose
  target's `generate()`.
- The entry file's `include` list is generated, so adding an images file
  changes nothing else.
- Step 7 finds the platform through a submodule and compares versions.

## Review

Before merging, run the reviewers in `reviews.md` for this step: technical, CI, security, rollout, agent developer.
Record each finding in the PR as fixed, deferred or rejected.
