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

## Behavior

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
