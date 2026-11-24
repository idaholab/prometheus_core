---
title: Workflow Templates
description: Schema and authoring guide for reusable Prometheus workflow templates
icon: lucide/workflow
---

# Workflow Templates

Workflow templates are reusable execution blueprints for multi-step Prometheus analyses. They let the
client-agent run a known sequence of skills, collect required inputs, pass outputs from one step into later
steps, and publish the workflow as a catalog item, planner tool, and slash command.

Use a workflow template when the order of operations matters or when the same chain of skills should be
available to users without asking the planner to rediscover the sequence every time. Examples include
material assessment workflows that retrieve material data, run several specialist analyses, and synthesize a
final report.

Templates can be owned by the platform or by specialist agents:

- **Platform-owned workflows** live in `agents/client-agent/workflows/*.yaml` or `*.yml`.
- **Agent-owned workflows** live with the agent, either in the agent card's top-level `workflows` array or in
  workflow files loaded by `PrometheusAgent` from `workflows/` or `AGENT_WORKFLOWS`.

Agent-owned workflows are discovered from the agent card, compiled against the currently discovered skill
schemas, merged into the same platform workflow catalog, and health-checked against their provider agent
before execution.

## File locations

### Platform-owned workflows

The client-agent workflow registry loads local workflow files from `WORKFLOW_LIBRARY_DIR`, which defaults to
`/app/workflows` inside the client-agent container. In the source tree these are normally authored under:

```text
agents/client-agent/workflows/*.yaml
agents/client-agent/workflows/*.yml
```

Each platform-local file should contain one workflow object.

### Agent-owned workflows

Agents can publish workflow templates in two ways:

1. Add workflow objects to the source `agent_card.json` under a top-level `workflows` array.
2. Add `*.yaml`, `*.yml`, or `*.json` workflow files to `workflows/` beside `agent_card.json`.

`PrometheusAgent` loads workflow files at startup and inserts them into the served raw agent card. If
`AGENT_WORKFLOWS` is set, it overrides the default `workflows/` directory. Relative `AGENT_WORKFLOWS` paths
resolve relative to `agent_card.json`, so agent cards and workflow files stay relocatable as a pair.

Agent-owned workflow files may contain one workflow object, a list of workflow objects, or a wrapper object:

```yaml
workflows:
  - id: thermal_agent.quick_check
    name: Quick Thermal Check
    version: "1.0.0"
    description: Run a quick thermal analysis.
    steps:
      - id: analyze
        skill_id: analyze_thermal
```

## Minimal template

```yaml
id: provider.workflow_name
name: Workflow Name
version: "1.0.0"
description: What this workflow does.

inputs:
  required:
    - input_data
  optional: []

execution:
  mode: sequential
  max_concurrency: 1
  on_error: fail_fast

steps:
  - id: run_primary_skill
    skill_id: primary_skill_id
    is_final: true
    params:
      input_data:
        from: input.input_data

outputs:
  final:
    from: step.run_primary_skill.result

metadata:
  requires_approval: false
  estimated_duration_seconds: 30
  owner: provider

ui:
  category: Provider
  display_name: Workflow Name
  summary: One-sentence catalog summary.
```

## Complete schema

### Top-level workflow object

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | Yes | -- | Global workflow identifier. Prefer a provider namespace, such as `thermal_agent.quick_check`. |
| `name` | string | Yes | -- | Human-readable workflow name. |
| `version` | string | Yes | -- | Workflow version. Quote semantic versions in YAML, for example `"1.0.0"`. |
| `description` | string | Yes | -- | User- and planner-facing description. |
| `matching` | object | No | See below | Legacy deterministic matching metadata. New templates should rely on planner workflow tools and slash invocation instead. |
| `inputs` | object | No | Empty required and optional lists | Declared user-provided inputs. The compiler may infer additional required inputs from bindings and skill schemas. |
| `execution` | object | No | Sequential, concurrency 3, fail fast | Scheduling and error behavior. |
| `steps` | array | Yes | `[]`, but compile fails | Ordered list of workflow steps. The compiler rejects workflows with no steps. |
| `outputs` | object | No | Empty final mapping | Final output mapping. |
| `metadata` | object | No | No approval, owner, or source metadata | Workflow ownership, approval, duration, and source metadata. |
| `ui` | object | No | No UI overrides | Catalog and input-form display hints. |

Unknown fields are not part of the stable contract. The current Pydantic models ignore extra fields, so do not
depend on unrecognized keys for durable behavior.

### `matching`

```yaml
matching:
  priority: 0
  patterns: []
  tags: []
  semantic_fallback:
    enabled: false
    min_confidence: 0.8
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `priority` | integer | `0` | Sort weight for deterministic matches. |
| `patterns` | array of strings | `[]` | Legacy regex-like patterns. Placeholders such as `{material_id}` become capture groups. |
| `tags` | array of strings | `[]` | Descriptive tags. |
| `semantic_fallback.enabled` | boolean | `false` | Reserved semantic fallback flag. |
| `semantic_fallback.min_confidence` | number | `0.8` | Reserved semantic fallback threshold. |

`patterns` are kept for compatibility. Prefer workflow catalog selection, generated planner tools, or slash
commands for new user-facing behavior.

### `inputs`

```yaml
inputs:
  required:
    - material_id
    - context.temperature_c
  optional:
    - context.pressure_mpa
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `required` | array of strings | `[]` | Input paths that must be available before execution. |
| `optional` | array of strings | `[]` | Input paths that should not be promoted to required when referenced by bindings. |

The compiler also scans step `params` and skill input schemas:

- Any binding from `input.*` becomes a required workflow input unless the binding has `optional: true` or its
  path appears in `inputs.optional`.
- Required skill fields bound from `input.*` become required workflow inputs.
- Required skill fields satisfied by `literal`, `step.*`, or context produced by ancestor step outputs do not
  become user inputs.
- Required skill fields bound from external `context.*` become required as `context.<path>` unless an ancestor
  step writes that context path.

### `execution`

```yaml
execution:
  mode: sequential
  max_concurrency: 3
  on_error: fail_fast
```

| Field | Type | Default | Allowed values | Description |
|-------|------|---------|----------------|-------------|
| `mode` | string | `sequential` | `sequential`, `parallel`, `dag` | Step scheduling mode. |
| `max_concurrency` | integer | `3` | Any positive integer | Maximum ready steps to run at once in `parallel` or `dag` modes. |
| `on_error` | string | `fail_fast` | `fail_fast`, `continue_with_partial` | Whether failures stop scheduling or allow independent work to continue. |

Sequential mode runs one ready step at a time. Parallel and DAG modes run currently ready steps up to
`max_concurrency`. Dependencies are still enforced in DAG mode.

### `steps`

```yaml
steps:
  - id: retrieve_material
    skill_id: get_material_data
    depends_on: []
    params: {}
    outputs: []
    when: {}
    is_final: false
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | Yes | -- | Unique step identifier within the workflow. |
| `skill_id` | string | Yes | -- | Skill to invoke. In strict mode, this must exist in the capability cache. |
| `depends_on` | array of strings | No | `[]` | Step IDs that must succeed before this step is ready. |
| `params` | object | No | `{}` | Recursive parameter binding tree for the skill payload. |
| `outputs` | array of objects | No | `[]` | Context writes from this step's result. |
| `when` | object | No | `{}` | Conditional skip rules. Currently supports `not_in_context`. |
| `is_final` | boolean | No | `false` | Marks this step as the fallback final output when `outputs.final` is not set. |

Step IDs must be unique. Unknown `depends_on` references and dependency cycles are compile errors.

`when.not_in_context` skips the step if the named context path already exists:

```yaml
when:
  not_in_context: material_data
```

### `params`

Step `params` can be plain values or recursive binding nodes.

Literal values:

```yaml
params:
  width:
    literal: 512
  color:
    literal: blue
```

User inputs:

```yaml
params:
  material_id:
    from: input.material_id
```

Workflow context:

```yaml
params:
  material_data:
    from: context.material_data
```

Prior step results:

```yaml
params:
  radiation:
    from: step.analyze_radiation.result
```

Optional bindings:

```yaml
params:
  context:
    pressure_mpa:
      from: input.context.pressure_mpa
      optional: true
```

Supported `from` roots are `input.`, `context.`, and `step.`. Optional bindings are omitted from the step
payload when the value is missing. The executor also adds `conversation_id` to every step payload and forwards
`context.artifacts` as `artifacts` when the step payload does not set `artifacts` explicitly.

### Step `outputs`

```yaml
steps:
  - id: retrieve_material
    skill_id: get_material_data
    outputs:
      - to_context: material_data
        from: result
      - to_context: material_id
        from: material_id
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `to_context` | string | Yes | Context path to write. |
| `from` | string | No | Result path to read. If omitted, the whole step result is written. |

`from: result` maps the whole step result if the result object has no nested `result` key.

### Workflow `outputs`

```yaml
outputs:
  final:
    from: step.synthesize_report.result
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `final` | object | `{}` | Final output mapping. Only `from` is currently interpreted. |
| `final.from` | string | -- | Step result reference, usually `step.<step_id>.result`. |

If `outputs.final.from` is not set, the executor returns the first `is_final: true` step result. If no step is
marked final, it returns the last step result.

### `metadata`

```yaml
metadata:
  requires_approval: false
  estimated_duration_seconds: 30
  owner: provider-name
  source_agent_id: provider-agent-id
  source_agent_url: http://provider:8000
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `requires_approval` | boolean | `false` | Whether the workflow should require user approval before execution. |
| `estimated_duration_seconds` | integer or null | `null` | Estimated runtime shown in catalog metadata. |
| `owner` | string or null | `null` | Owning team or agent. Agent-card workflows get this injected when missing. |
| `source_agent_id` | string or null | `null` | Provider agent ID. Normally injected by the client-agent registry. |
| `source_agent_url` | string or null | `null` | Provider direct URL. Normally injected by the client-agent registry. |

For agent-owned workflows, `source_agent_id` and `source_agent_url` are used for the provider health check
before workflow execution. Local platform workflows do not have source metadata and skip this guard.

### `ui`

```yaml
ui:
  category: Safety
  display_name: Comprehensive Material Analysis
  summary: Full multi-domain assessment.
  input_overrides:
    context.temperature_c:
      label: Coolant temperature
      description: Operating coolant temperature.
      type: number
      unit: C
      options: []
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `category` | string or null | `null` | Catalog category. Defaults to `General` in catalog output. |
| `display_name` | string or null | `null` | Catalog display name. Defaults to `name`. |
| `summary` | string or null | `null` | Catalog summary. Defaults to `description`. |
| `complexity` | `complex`, `moderate`, `simple`, or null | `null` | How complex the workflow is. The Workflow Console shows it when set. |
| `speedup` | number or null | `null` | The speed-up over the manual baseline, as a raw number (`2.5`, not `"2.5x"`). The Workflow Console shows it when set. |
| `input_overrides` | object | `{}` | Per-input display hints for workflow input forms. |

`complexity` and `speedup` are optional. When a workflow does not set them, `GET /api/workflows` returns them as `null`.

Input override fields:

| Field | Type | Description |
|-------|------|-------------|
| `label` | string | Form label. |
| `description` | string | Form help text. |
| `type` | string | Form type hint such as `text`, `number`, or `integer`. |
| `unit` | string | Unit hint appended to form descriptions when not already present. |
| `options` | array | Selectable options. |

## Full example

```yaml
id: comprehensive_material_analysis
name: Comprehensive Material Analysis
version: "1.0.0"
description: Multi-step safety analysis using data and specialist skills.

inputs:
  required:
    - material_id
    - context.temperature_c
  optional:
    - context.pressure_mpa
    - context.neutron_flux_n_cm2_s
    - context.operating_hours

execution:
  mode: dag
  max_concurrency: 3
  on_error: fail_fast

steps:
  - id: retrieve_material
    skill_id: get_material_data
    params:
      material_id:
        from: input.material_id
    outputs:
      - to_context: material_data
        from: result

  - id: analyze_radiation
    skill_id: analyze_radiation_damage
    depends_on: [retrieve_material]
    params:
      material_id:
        from: input.material_id
      context:
        neutron_flux_n_cm2_s:
          from: input.context.neutron_flux_n_cm2_s
          optional: true
        operating_hours:
          from: input.context.operating_hours
          optional: true

  - id: synthesize_report
    skill_id: synthesize_material_analysis
    depends_on: [retrieve_material, analyze_radiation]
    is_final: true
    params:
      material_id:
        from: input.material_id
      material_data:
        from: context.material_data
      radiation:
        from: step.analyze_radiation.result

outputs:
  final:
    from: step.synthesize_report.result

metadata:
  requires_approval: true
  estimated_duration_seconds: 270
  owner: materials-team

ui:
  category: Safety
  display_name: Comprehensive Material Analysis
  summary: Full multi-domain assessment with data retrieval and specialist analysis.
  input_overrides:
    context.temperature_c:
      label: Coolant temperature
      description: Operating coolant temperature.
      unit: C
      type: number
```

## Authoring notes

- Keep workflow IDs stable and globally unique. Prefer `provider.workflow_name`.
- Quote YAML scalars containing `#`, colon-sensitive text, leading braces, or other YAML-sensitive characters.
  For example, write `literal: "USA is #1"`.
- Do not depend on `matching.patterns` for core behavior in new workflows. Registered workflows are exposed to
  the planner as workflow tools and can be invoked explicitly by slash command.
- If an agent is containerized, copy its workflow directory into the runtime image. The generated agent template
  uses `COPY workflows /app/workflows`.
- The agent template ships `workflows/example_workflow.yaml.example` so new agents do not publish a sample
  workflow until the author intentionally renames and reviews it.
