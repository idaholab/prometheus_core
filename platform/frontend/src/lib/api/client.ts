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
 * Typed fetch wrappers for the backend `/api` surface.
 *
 * Every call sends the auth cookie (`credentials: "include"`). Non-2xx responses
 * throw an {@link ApiError} carrying the status so callers can distinguish 401
 * (unauthenticated) from other failures. Mirrors `backend/app/routers/*`.
 */

import type {
  AdminUser,
  AdminUserCreate,
  AdminUserUpdate,
  AuthProvider,
  ChatMessageRequest,
  ChatMessageResponse,
  ConfigResponse,
  ConversationDetailResponse,
  ConversationHistoryResponse,
  ConversationResumeRequest,
  ConversationSummary,
  ConversationTasksResponse,
  CreateSessionRequest,
  OidcProvider,
  OidcProviderCreate,
  OidcProviderUpdate,
  SessionResponse,
  SetupStatus,
  SigningKey,
  UploadDescriptor,
  User,
} from "./types";

const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body — keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  // 204/empty bodies → undefined; callers that expect a body type won't hit this.
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  // --- setup (first-run wizard) ---
  /** GET /api/setup/status — unauthenticated; true until the first admin exists. */
  setupStatus(): Promise<SetupStatus> {
    return request<SetupStatus>("/setup/status");
  },

  /** POST /api/setup/bootstrap — creates the first admin account and logs it in
   * (sets the session cookie, same as login). Throws ApiError(409) if setup has
   * already been completed. */
  async bootstrap(username: string, password: string): Promise<User> {
    const body = await request<{ user: User }>("/setup/bootstrap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    return body.user;
  },

  // --- auth ---
  async login(username: string, password: string): Promise<User> {
    const body = await request<{ user: User }>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    return body.user;
  },

  logout(): Promise<void> {
    return request<void>("/auth/logout", { method: "POST" });
  },

  /** GET /api/auth/me — resolves to the user, or throws ApiError(401) if not authed. */
  me(): Promise<User> {
    return request<User>("/auth/me");
  },

  /** GET /api/auth/providers — public; enabled OIDC providers for <Login> to render. */
  listAuthProviders(): Promise<AuthProvider[]> {
    return request<AuthProvider[]>("/auth/providers");
  },

  /** URL for GET /api/auth/login/{provider_id} -- a full-page navigation
   * (`window.location.href = ...`), never a fetch: it's a server redirect to
   * the identity provider, not a JSON response. */
  loginUrl(providerId: string): string {
    return `${API_BASE}/auth/login/${encodeURIComponent(providerId)}`;
  },

  // --- config / session ---
  getConfig(): Promise<ConfigResponse> {
    return request<ConfigResponse>("/config");
  },

  createSession(profile?: string, bindSeq?: number): Promise<SessionResponse> {
    const body: CreateSessionRequest = { bind_seq: bindSeq };
    if (profile) body.profile = profile;
    return request<SessionResponse>("/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  // --- chat turn ---
  sendMessage(body: ChatMessageRequest): Promise<ChatMessageResponse> {
    return request<ChatMessageResponse>("/chat/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  // --- uploads ---
  uploadFile(file: File): Promise<UploadDescriptor> {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<UploadDescriptor>("/uploads", { method: "POST", body: form });
  },

  // --- history ---
  getRecentConversations(limit = 20): Promise<ConversationHistoryResponse> {
    return request<ConversationHistoryResponse>(`/conversations/recent?limit=${limit}`);
  },

  /** Read a conversation's transcript without rebinding the session. */
  getConversation(conversationId: string): Promise<ConversationDetailResponse> {
    return request<ConversationDetailResponse>(`/conversations/${encodeURIComponent(conversationId)}`);
  },

  /** GET /api/conversations/{id}/tasks — the conversation's background-task tree
   * (one root per chat turn, its specialist dispatches as children), newest first. */
  getConversationTasks(conversationId: string): Promise<ConversationTasksResponse> {
    return request<ConversationTasksResponse>(`/conversations/${encodeURIComponent(conversationId)}/tasks`);
  },

  /** Rebind the session to a past conversation; the next chat turn continues it. */
  resumeConversation(conversationId: string, bindSeq?: number): Promise<ConversationDetailResponse> {
    const body: ConversationResumeRequest = { bind_seq: bindSeq };
    return request<ConversationDetailResponse>(
      `/conversations/${encodeURIComponent(conversationId)}/resume`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
  },

  renameConversation(conversationId: string, title: string): Promise<ConversationSummary> {
    return request<ConversationSummary>(`/conversations/${encodeURIComponent(conversationId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
  },

  /** Soft delete: the conversation drops out of `getRecentConversations`. */
  deleteConversation(conversationId: string): Promise<void> {
    return request<void>(`/conversations/${encodeURIComponent(conversationId)}`, {
      method: "DELETE",
    });
  },

  /** URL for an artifact's bytes; used directly as an <img>/<embed> src or fetch target. */
  artifactContentUrl(artifactId: string): string {
    return `${API_BASE}/artifacts/${encodeURIComponent(artifactId)}/content`;
  },

  /** The baked HTML report a producer attached to an artifact (see `has_report`). */
  artifactReportUrl(artifactId: string): string {
    return `${API_BASE}/artifacts/${encodeURIComponent(artifactId)}/report`;
  },

  // --- admin: users (require_admin server-side; 403 for non-admins) ---
  listAdminUsers(): Promise<AdminUser[]> {
    return request<AdminUser[]>("/admin/users");
  },

  createAdminUser(input: AdminUserCreate): Promise<AdminUser> {
    return request<AdminUser>("/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  },

  updateAdminUser(userId: string, patch: AdminUserUpdate): Promise<AdminUser> {
    return request<AdminUser>(`/admin/users/${encodeURIComponent(userId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  },

  deleteAdminUser(userId: string): Promise<void> {
    return request<void>(`/admin/users/${encodeURIComponent(userId)}`, { method: "DELETE" });
  },

  // --- admin: signing keys (require_admin server-side; 403 for non-admins) ---
  listSigningKeys(): Promise<SigningKey[]> {
    return request<SigningKey[]>("/admin/signing-keys");
  },

  generateSigningKey(): Promise<SigningKey> {
    return request<SigningKey>("/admin/signing-keys", { method: "POST" });
  },

  activateSigningKey(keyId: string): Promise<SigningKey> {
    return request<SigningKey>(`/admin/signing-keys/${encodeURIComponent(keyId)}/activate`, { method: "POST" });
  },

  retireSigningKey(keyId: string): Promise<SigningKey> {
    return request<SigningKey>(`/admin/signing-keys/${encodeURIComponent(keyId)}/retire`, { method: "POST" });
  },

  // --- admin: OIDC identity providers (require_admin server-side; 403 for non-admins) ---
  listOidcProviders(): Promise<OidcProvider[]> {
    return request<OidcProvider[]>("/admin/oidc-providers");
  },

  createOidcProvider(input: OidcProviderCreate): Promise<OidcProvider> {
    return request<OidcProvider>("/admin/oidc-providers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  },

  updateOidcProvider(id: string, patch: OidcProviderUpdate): Promise<OidcProvider> {
    return request<OidcProvider>(`/admin/oidc-providers/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  },

  deleteOidcProvider(id: string): Promise<void> {
    return request<void>(`/admin/oidc-providers/${encodeURIComponent(id)}`, { method: "DELETE" });
  },
};
