# 008 - Where and how the platform runs

status: draft
sources: platform/ctl/platformctl/targets/base.py, platform/ctl/platformctl/targets/__init__.py, platform/ctl/platformctl/config.py, infrastructure/scripts/cluster-up.sh, platform/plans/platformctl/08-k3d-target.md, platform/plans/platformctl/09-platform-images.md
tests: platform/ctl/tests
depends-on: 001, 004, 005

## Purpose
The same commands can run the platform somewhere other than local Compose,
and from published images instead of a local build. Today only the refusal
of anything else exists; the k3d target (step 8) and running from images
(step 9) fill this in.

## Requirements

Targets

- REQ-008-01: `--target` and the `PLATFORM_TARGET` setting MUST choose where
  the platform runs, with `--target` winning; `compose` is the default.
- REQ-008-02: `--target k3d` (or `PLATFORM_TARGET=k3d`) MUST exit 1 with
  "target `k3d` is not supported yet", and an unknown target MUST exit 1
  naming the valid choice.
- REQ-008-03: A command that needs something the chosen target can't do MUST
  exit 1 with "`<command>` is not supported on target `<name>`".
- REQ-008-04: `--target k3d up` MUST run the platform on the local k3d
  cluster and end with the same summary as compose, with the cluster's URLs.
  (planned: step 8)
- REQ-008-05: `cluster up`, `cluster down` and `cluster reset` MUST replace
  the `cluster-*` Make targets, and `cluster up` MUST keep its "already
  running" output word for word. (planned: step 8)

Where the code comes from

- REQ-008-06: `PLATFORM_SOURCE` MUST default to `build`, and
  `PLATFORM_SOURCE=image` MUST exit 1 with "not supported yet" until step 9.
- REQ-008-07: `PLATFORM_SOURCE=image` MUST run each service that has a
  published image from the image tagged for the platform version, and build
  the rest. (planned: step 9)
- REQ-008-08: `PLATFORM_IMAGE_TAG` MUST override the tag the version maps
  to, and `PLATFORM_IMAGE_REGISTRY` the registry. (planned: step 9)
- REQ-008-09: When no images exist for the version, `up` MUST stop before
  pulling with "no images for `<version>`; use `PLATFORM_SOURCE=build`".
  (planned: step 9)

## Behavior

- BEH-008-01: GIVEN `PLATFORM_TARGET=k3d` in `.env` WHEN the user runs
  `--target compose doctor` THEN the compose target is used.

## Interfaces
- `--target compose|k3d`, `PLATFORM_TARGET`
- `PLATFORM_SOURCE=build|image`, `PLATFORM_IMAGE_TAG`,
  `PLATFORM_IMAGE_REGISTRY`
- `./platformctl cluster up|down|reset`

## Constraints
- `cluster up`'s "already running" stays word for word (CI checks it).

## Out of scope / Non-goals
- How a target is implemented (`platform/ctl/README.md`).
- Publishing the images (the Release and publishing area, 300s).

## Open questions
