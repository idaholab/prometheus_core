// This file is part of Prometheus
// https://inl.gov/super-intelligence/prometheus/
//
// Copyright 2026 Battelle Energy Alliance, LLC
// All rights reserved, see NOTICE.txt for full restrictions
// https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
//
// Licensed under the MIT License, please see LICENSE for details
// https://github.com/idaholab/prometheus_core/blob/main/LICENSE
//
// SPDX-License-Identifier: MIT

/**
 * TypeScript mirror of the backend wire contract.
 *
 * Hand-kept in sync with `backend/app/contract.py` (and `backend/CONTRACT.md`).
 * These are the shapes the `/api` client and the chat store code against. If the
 * backend contract changes, update this file + the store/adapter together.
 */

// --- Status + enums ---------------------------------------------------------

export type ChatStatus =
  | "needs_info"
  | "plan_ready"
  | "executing"
  | "completed"
  | "recommendation"
  | "answer"
  | "backgrounded"
  | "error";

export type RenderHint =
  | "pdf"
  | "image"
  | "json"
  | "ifc"
  | "mesh"
  | "mermaid"
  | "thermal"
  | "report"
  | "code"
  | "table"
  | "reference"
  | "file"
  | "unknown";

export type FieldInputType =
  "text" | "number" | "email" | "password" | "date" | "datetime" | "textarea" | "select" | "checkbox";

// --- needs_info form schema -------------------------------------------------

export interface SelectOption {
  label: string;
  value: string;
}

export interface FormField {
  id: string;
  label: string;
  input_type: FieldInputType;
  required: boolean;
  options?: SelectOption[] | null;
  default?: unknown;
  help?: string | null;
  placeholder?: string | null;
  rows?: number | null;
  min?: number | null;
  max?: number | null;
  step?: number | null;
}

// --- artifacts --------------------------------------------------------------

export interface Citation {
  source?: string | null;
  section?: string | null;
  page?: string | null;
}

export interface ArtifactMeta {
  artifact_id: string;
  name: string;
  mime_type?: string | null;
  json_type?: string | null;
  description: string;
  uri?: string | null;
  tags: string[];
  json_body?: unknown;
  render_hint: RenderHint;
  citation?: Citation | null;
  producer_agent_id?: string | null;
  created_at?: string | null;
  /** `inline` in the message body (default) or `panel`: only in the side
   * artifact panel. Set by the producing agent; mirrors `ArtifactMeta.display`
   * in backend/app/contract.py. */
  display?: ArtifactDisplay;
}

export type ArtifactDisplay = "inline" | "panel";

// --- uploads ----------------------------------------------------------------

export interface UploadDescriptor {
  upload_id: string;
  name: string;
  mime_type: string;
  size_bytes: number;
}

// --- chat request / response ------------------------------------------------

export interface ChatMessageRequest {
  query: string;
  followup_answers?: Record<string, unknown> | null;
  plan_approved?: boolean;
  plan_rejected?: boolean;
  workflow_id?: string | null;
  upload_ids?: UploadDescriptor[] | null;
}

export interface ChatMessageResponse {
  turn_id: string;
  status: ChatStatus;
  message?: string | null;
  // needs_info
  followup_questions?: FormField[] | null;
  // plan_ready
  plan?: Record<string, unknown> | null;
  auto_approve?: boolean;
  // completed | answer | recommendation | needs_info (outputs made before the form)
  artifacts?: ArtifactMeta[] | null;
  // completed | answer | recommendation
  report?: string | null;
  response_text?: string | null;
  recommended_materials?: string[] | null;
  follow_up_suggestions?: string[] | null;
  // backgrounded
  task_id?: string | null;
}

// --- SSE events (discriminated on `type`) -----------------------------------

export interface StatusEvent {
  type: "status";
  turn_id: string;
  message: string;
  history?: string[] | null;
}

export interface TaskProgressEvent {
  type: "task_progress";
  task_id: string;
  message: string;
}

export interface TaskDoneEvent {
  type: "task_done";
  task_id: string;
  state: string;
  message?: string | null;
  response?: ChatMessageResponse | null;
}

export type ServerEvent = StatusEvent | TaskProgressEvent | TaskDoneEvent;

// --- auth / session / config ------------------------------------------------

export interface User {
  identifier: string;
  role: string;
  provider: string;
}

export interface SetupStatus {
  needs_setup: boolean;
}

export interface AuthProvider {
  provider_id: string;
  display_name: string;
}

// --- admin: users -------------------------------------------------------------

export interface AdminUser {
  id: string;
  username: string;
  role: string;
  provider: string;
  external_subject?: string | null;
  email?: string | null;
  display_name?: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at?: string | null;
}

export interface AdminUserCreate {
  username: string;
  password: string;
  role: string;
}

export interface AdminUserUpdate {
  role?: string;
  password?: string;
  is_active?: boolean;
  display_name?: string;
  email?: string;
}

// --- admin: signing keys -------------------------------------------------------

export interface SigningKey {
  id: string;
  kid: string;
  public_key_pem: string;
  is_active: boolean;
  created_at: string;
  retired_at?: string | null;
}

// --- admin: OIDC identity providers --------------------------------------------

export interface OidcProvider {
  id: string;
  provider_id: string;
  display_name: string;
  issuer_url: string;
  client_id: string;
  scopes: string;
  default_role: string;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface OidcProviderCreate {
  provider_id: string;
  display_name: string;
  issuer_url: string;
  client_id: string;
  client_secret: string;
  scopes: string;
  default_role: string;
  is_enabled: boolean;
}

export interface OidcProviderUpdate {
  display_name?: string;
  issuer_url?: string;
  client_id?: string;
  client_secret?: string;
  scopes?: string;
  default_role?: string;
  is_enabled?: boolean;
}

// --- workflows ----------------------------------------------------------------

export type WorkflowComplexity = "complex" | "moderate" | "simple";

/** `local` for a client-agent workflow file, `agent_card` for a workflow an agent card declares. */
export type WorkflowSource = "local" | "agent_card";

/** One row of `GET /api/workflows` (`Workflow` in `contract.py`). */
export interface Workflow {
  /** The library id; the value `ChatMessageRequest.workflow_id` takes to run it. */
  workflow_id: string;
  name: string;
  summary: string;
  /** `General` when none is set. */
  category: string;
  version: string;
  source: WorkflowSource;
  owner: string | null;
  complexity: WorkflowComplexity | null;
  estimated_runtime_seconds: number | null;
  /** Raw speed-up over the manual baseline, e.g. 2.0; the UI formats "2.0x". */
  speedup: number | null;
  /** Whether chat pauses for the user's approval before the workflow runs. */
  requires_approval: boolean;
  /** Distinct agents over the `skill` nodes. */
  agent_count: number;
  checkpoint_count: number;
}

export interface GraphNodeInput {
  port: string;
  source: string | null;
  optional: boolean;
}

export interface GraphNode {
  node_id: string;
  kind: "skill" | "checkpoint" | "qa_gate";
  skill_id: string | null;
  /** The skill's name from its agent card when known, else the step id. */
  label: string;
  /** Null when no registered agent serves the skill. */
  agent_name: string | null;
  /** Whether the step's output is the workflow's result. */
  is_final: boolean;
  inputs: GraphNodeInput[];
}

/** `data` when the target reads the source's output, `order` when it only runs after it. */
export type GraphEdgeKind = "data" | "order";

export interface GraphEdge {
  edge_id: string;
  from_node: string;
  to_node: string;
  kind: GraphEdgeKind;
  /** The target input port of a `data` edge; null for an `order` edge. */
  port: string | null;
}

export interface WorkflowGraph {
  workflow_id: string;
  mode: "dag" | "sequential" | "parallel";
  nodes: GraphNode[];
  edges: GraphEdge[];
}

/** The input paths a workflow declares. */
export interface WorkflowInputs {
  required: string[];
  optional: string[];
}

/** `GET /api/workflows/{workflow_id}`: one template with its inputs and graph. */
export interface WorkflowDetail extends Workflow {
  inputs: WorkflowInputs;
  graph: WorkflowGraph;
}

/** `GET /api/workflows`. `available` is false when the client-agent workflow library is
 * unreachable or off; `workflows` is then empty (200, as `GET /api/agents`). */
export interface WorkflowListResponse {
  available: boolean;
  workflows: Workflow[];
}

/** Body of `POST /api/sessions` (`CreateSessionRequest` in `contract.py`).
 *
 * Rebind ordering: the server applies a rebind (`POST /sessions`, `/resume`) only
 * if its `bind_seq` is greater than the last one it applied, so a slow, superseded
 * request cannot rebind the session after a newer one. A superseded create still
 * answers 200 with a fresh `conversation_id` that is not bound; discard it. */
export interface CreateSessionRequest {
  profile?: string;
  bind_seq?: number;
}

export interface ConversationResumeRequest {
  bind_seq?: number;
}

export interface SessionResponse {
  conversation_id: string;
  profile: string;
  chat_intro: string;
  chat_suggestion_title: string;
  workflow_suggestions: string[];
  auto_approve_steps: boolean;
}

export interface ChatProfile {
  name: string;
  markdown_description: string;
  icon?: string | null;
}

export interface ConfigResponse {
  profiles: ChatProfile[];
  chat_intro: string;
  chat_suggestion_title: string;
  workflow_suggestions: string[];
  auto_approve_steps: boolean;
  max_upload_bytes: number;
}

// --- history ----------------------------------------------------------------

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  query: string;
  status: string;
  timestamp: string;
  pending: boolean;
}

export interface ConversationHistoryResponse {
  available: boolean;
  conversations: ConversationSummary[];
}

export interface ConversationMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  /** Ids of the artifacts this turn produced, resolved in the detail's `artifacts`. */
  artifact_ids: string[];
}

export interface ConversationDetailResponse {
  conversation_id: string;
  title: string;
  profile: string;
  auto_approve_steps: boolean;
  messages: ConversationMessage[];
  artifacts: ArtifactMeta[];
}
