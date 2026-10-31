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
  | "uq"
  | "report"
  | "code"
  | "table"
  | "reference"
  | "file"
  | "unknown";

export type FieldInputType =
  | "text"
  | "number"
  | "email"
  | "password"
  | "date"
  | "datetime"
  | "textarea"
  | "select"
  | "checkbox";

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

/** A button a producing agent attached to its artifact (validated by the backend). */
export interface ArtifactLink {
  label: string;
  url: string;
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
  /** Buttons the producing agent attached (metadata.links); absolute http(s) only. */
  links?: ArtifactLink[];
  /** The producer attached a baked HTML report in DeepLynx, served at `/api/artifacts/{id}/report`. */
  has_report?: boolean;
}

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
  // completed | answer | recommendation
  report?: string | null;
  response_text?: string | null;
  artifacts?: ArtifactMeta[] | null;
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
