# 8 (future): Run the platform on k3d

> **Status: Not started**

## Goal

`./platformctl --target k3d up` (or `PLATFORM_TARGET=k3d`) runs the platform
on the local k3d cluster, with no changes to the actions.

## Requirements

This step satisfies the requirements tagged `(planned: step 8)` in
[`build/specs/`](../../../build/specs/000-index.md). They are early drafts:
this step's PR will refine them once the k3d target's design is known. It
removes each tag and cites the ID from the test that proves it. When it
lands, REQ-008-02's refusal of `k3d` is retired.

- [008 Where and how the platform runs](../../../build/specs/008-where-and-how-the-platform-runs.md):
  REQ-008-04, REQ-008-05, REQ-008-10 to REQ-008-12 (`--target k3d up` and
  its summary, `cluster up|down|reset` keeping "already running", the k3d
  checks in `doctor`, every command working or refusing cleanly)

## Work

- `targets/k3d.py`, implementing `targets/base.py`, on new adapters
  `system/k3d.py` and `system/kubectl.py`.
- Per-agent cluster manifests or Helm values, attached to the agent records
  from `compose_files.py`.
- k3d-only checks: cluster running, registry on `localhost:5001`, kubectl
  context.
- `cluster up|down|reset`, replacing the `cluster-*` Make targets and
  `infrastructure/scripts/cluster-up.sh` and the `--cluster` mode of
  `check-local-prereqs.sh`. CI checks `cluster-up`'s "already running" output
  (`test.yml:272`); keep it.

## Output

- `cluster up`: the steps (tools, CA, cluster, registry) and the cluster's
  registry address; keeps "already running" word for word.
- `up --target k3d`: the same summary as compose, with the cluster's URLs.

## Replaces

- `infrastructure/scripts/cluster-up.sh` and
  `check-local-prereqs.sh --cluster`; the `cluster-*` Make targets forward.

## Docs and slides

- **User guide:** a `cluster.md` page (running on k3d), and `from-make.md`
  rows for `cluster-*`.
- `platform/README.md`'s local cluster section and the CI comments switch
  to `./platformctl cluster ...` and `--target k3d`.
- Hackathon deck 03 (deployment) if it covers the cluster; rebuild.

## What changes for you

- **Commands:** `make cluster-*` forward to `./platformctl cluster ...`.
  Nothing changes for the compose platform.
- **Roll back:** revert the PR.

## Breaking changes

None expected: `cluster-up`, `cluster-down` and `cluster-reset` forward,
and `cluster-up` keeps its "already running" message.

## Prepared for in steps 1 to 4

- Actions only use the `Target` interface, never `docker compose`.
- Containers are found by service, never by name.
- Checks declare the targets they apply to.
- Agent discovery returns records, not compose file paths.

## From the step 1 review

- **A target registry** (reported). `context.build` validates the target name and then always
  builds `ComposeTarget`, and `Context.target` is typed as `ComposeTarget`, so a second target means
  editing `context.py`. Add a `TARGETS` registry (name to class) and type the field as the base
  class. `Target.service_url`, `ComposeTarget.build_cache_on` and `Compose.exec` had no callers in
  step 1: use or drop them.
- **Git behind an adapter** (reported): `env_checks` and `config.platform_version` call `git`
  through `ctx.runner` directly. Only `system/` should know argv: add a git adapter.

## Review

Before merging, run `/review-panel` on the PR (see `reviews.md`) with these reviewers: technical, CI and tests, security, rollout, Linux/WSL.

Ask them to look at:

- **Technical:** that no action changes, only the target and its adapters; `cluster up|down|reset`
  replacing the `cluster-*` targets and `cluster-up.sh`.
- **CI and tests:** `cluster-up`'s "already running" output that `test.yml:272` checks; the cost
  of a cluster in CI.
- **Security:** acting on the wrong kubectl context; the registry on `localhost:5001`; secrets in
  manifests or Helm values.
- **Rollout:** people using `make cluster-*` and the `--cluster` mode of `check-local-prereqs.sh`.
- **Linux/WSL:** k3d on Docker Desktop and on Engine; the local registry.
