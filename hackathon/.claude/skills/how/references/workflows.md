# Workflows: chain skills with a YAML file

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

A workflow is a fixed chain of skill calls (deck 04, A37-A38). Put `*.yaml` in `workflows/` (rename the
template `.example` file); the base class merges it into the card at startup. The LLM sees one tool,
`workflow_<id>`, and each workflow is a slash command; `/workflows` lists them. The orchestrator chains
skills by itself too: use a workflow only when the order must never change. Code:
`prometheus_platform/agents/client-agent/workflow_library/`.

```yaml
id: neutron.step_to_checked_mesh        # prefix with your team
name: STEP to checked mesh
version: "1.0.0"                        # quote it, else no compile
description: Mesh a STEP file, then report mesh quality.   # required
inputs: {required: [step_artifact_id]}
steps:
  - id: mesh
    skill_id: geometry_meshing
    params: {step_artifact_id: {from: input.step_artifact_id}}
    outputs: [{to_context: mesh_id, from: artifact_id}]
  - id: check
    skill_id: neutron_mesh_quality_report
    depends_on: [mesh]
    params: {mesh_artifact_id: {from: context.mesh_id}, x_column: {from: input.x_column, optional: true}}
```

Bindings: `input.*`, `context.*`, `step.<id>.result`, `{literal: ...}`. A plain `input.*` binding is
required: add `optional: true` for a form answer. Example: `prometheus_platform/agents/debug-agents/artifact-debug-agent/workflows/patriotic_usa_png.yaml`.

## Discovery and errors

Workflows compile only at a discovery refresh (every 300 s): after `make up`, run the refresh
(`conventions.md`, "Safe fixes"). A workflow that fails to compile is skipped. See the catalog and the
errors (no secret):

```sh
docker compose -p prometheus_platform exec -T client-agent python -c "import os, json, urllib.request as u; r=u.Request('http://localhost:8000/workflows/catalog', headers={'Authorization':'Bearer '+os.environ['AGENT_SECRET']}); d=json.load(u.urlopen(r)); [print(w['id'], w['version'], '|', w['display_name'], '| owner:', w['owner']) for w in d['workflows']]; [print('ERROR:', e) for e in d.get('errors', [])]"
```
