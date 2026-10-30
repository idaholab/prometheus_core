# 8 (future): Run the platform on k3d

> **Status: Not started**

## Goal

`./platformctl --target k3d up` (or `PLATFORM_TARGET=k3d`) runs the platform
on the local k3d cluster, with no changes to the actions.

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

## Breaking changes

None expected: `cluster-up`, `cluster-down` and `cluster-reset` forward,
and `cluster-up` keeps its "already running" message.

## Prepared for in steps 1 to 4

- Actions only use the `Target` interface, never `docker compose`.
- Containers are found by service, never by name.
- Checks declare the targets they apply to.
- Agent discovery returns records, not compose file paths.

## Review

Before merging, run the reviewers in `reviews.md` for this step: technical, CI, security, rollout, Linux/WSL.
Record each finding in the PR as fixed, deferred or rejected.
