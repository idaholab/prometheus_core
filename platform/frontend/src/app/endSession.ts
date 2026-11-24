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
 * What every end of a session does, in one place: logging out, the event
 * stream finding the session gone, and a 401 from a server-data request.
 */
import { setCurrentUser } from "@/features/auth";
import { chatStore } from "@/features/chat";

/**
 * - `"logout"`: the user signed out. Chat forgets this tab's conversation, so
 *   the next user can't resume it.
 * - `"lost"`: the session expired. Chat keeps the conversation, so signing back
 *   in resumes it.
 */
export type SessionEnd = "logout" | "lost";

/** End the session, then `leave` (navigate to Login). */
export async function endSession(how: SessionEnd, leave: () => void | Promise<void>): Promise<void> {
  if (how === "logout") chatStore.clear();
  else chatStore.suspendForReauth();
  setCurrentUser(null);
  await leave();
}
