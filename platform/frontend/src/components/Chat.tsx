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

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Square, ChevronDown, ChevronRight, Wrench, Paperclip, X, FileText, Loader2, AlertCircle } from "lucide-react";
import { api } from "@/lib/api/client";
import { chatStore, useChatState } from "@/lib/store/chat";
import type { ChatItem, NeedsInfoItem, PlanItem, ToolItem } from "@/lib/store/chat";
import type { UploadDescriptor } from "@/lib/api/types";
import { FollowupForm } from "./chat/FollowupForm";
import { WelcomeScreen } from "./chat/WelcomeScreen";
import { Markdown } from "./Markdown";
import { ElementList } from "./ElementRenderer";
import { artifactsToElements } from "@/lib/elements/artifactAdapter";
import { modelLabel } from "@/lib/modelLabel";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const AssistantAvatar = () => (
  <img
    src="/images/Prometheus_mark_white.png"
    alt="Prometheus"
    className="w-6 h-6 rounded-full shrink-0 bg-neutral object-contain p-1"
  />
);

function ToolStep({ item }: { item: ToolItem }) {
  const [open, setOpen] = useState(false);
  const isDone = item.done;
  const history = item.history.filter(Boolean);
  const hasHistory = history.length > 0;

  return (
    <div className="flex gap-2 justify-start">
      <div className="w-6 h-6 shrink-0 flex items-center justify-center">
        <Wrench size={13} className={isDone ? "text-base-content/30" : "text-primary animate-pulse"} />
      </div>
      <div className="flex flex-col gap-0.5 max-w-xl">
        <button
          className="flex items-center gap-1 text-sm text-base-content/50 hover:text-base-content/70 transition-colors text-left"
          onClick={() => setOpen((v) => !v)}
          disabled={!hasHistory}
        >
          {hasHistory ? (
            open ? <ChevronDown size={13} /> : <ChevronRight size={13} />
          ) : (
            <span className="w-3.25" />
          )}
          <span className={isDone ? "" : "italic text-shimmer"}>{item.name || "Processing…"}</span>
        </button>
        {open && hasHistory && (
          <pre className="text-xs text-base-content/40 bg-base-300 rounded p-2 whitespace-pre-wrap leading-5 mt-1">
            {history.join("\n")}
          </pre>
        )}
      </div>
    </div>
  );
}

function stepLabel(step: unknown): string {
  if (typeof step === "string") return step;
  if (step && typeof step === "object") {
    const s = step as Record<string, unknown>;
    const desc = typeof s.description === "string" ? s.description : "";
    const agent = typeof s.agent === "string" ? s.agent : typeof s.name === "string" ? s.name : "";
    if (agent && desc) return `${agent} — ${desc}`;
    return desc || agent || JSON.stringify(step);
  }
  return String(step);
}

function PlanCard({
  item,
  disabled,
  onDecide,
}: {
  item: PlanItem;
  disabled: boolean;
  onDecide: (approved: boolean) => void;
}) {
  const steps = Array.isArray((item.plan as { steps?: unknown[] })?.steps)
    ? ((item.plan as { steps: unknown[] }).steps)
    : [];
  return (
    <div className="mt-2 rounded-xl border border-base-300 bg-base-200 p-4 max-w-xl space-y-3">
      {steps.length > 0 && (
        <ol className="list-decimal pl-5 space-y-1 text-sm">
          {steps.map((s, i) => (
            <li key={i}>{stepLabel(s)}</li>
          ))}
        </ol>
      )}
      {item.decided === null && !item.autoApprove ? (
        <div className="flex gap-2">
          <button className="btn btn-primary btn-sm" disabled={disabled} onClick={() => onDecide(true)}>
            Approve
          </button>
          <button
            className="btn btn-ghost btn-sm border border-base-300"
            disabled={disabled}
            onClick={() => onDecide(false)}
          >
            Reject
          </button>
        </div>
      ) : item.decided ? (
        <p className="text-xs text-base-content/60">Plan {item.decided}.</p>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// File upload
// ---------------------------------------------------------------------------

const DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const USER_MESSAGE_TOP_PADDING = 16;
const LATEST_MESSAGE_BOTTOM_PADDING = 24;
const RESUME_FOLLOW_THRESHOLD = 40;

interface Attachment {
  localId: string;
  file: File;
  uploading: boolean;
  descriptor?: UploadDescriptor;
  error?: string;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------
// Main Chat component
// ---------------------------------------------------------------------------

interface ChatProps {
  // Owned by the parent (ProjectView) so that, once a second panel (artifact
  // viewer) is added alongside Chat, each panel scrolls independently and
  // the scrollbar sits at the panel boundary rather than hugging the
  // narrower max-w-4xl message column. Chat still owns all the scroll
  // *behavior* (autoscroll, spacer sizing, follow-latest detection) — only
  // the DOM node + its overflow styling live one level up.
  scrollContainerRef: React.RefObject<HTMLDivElement>;
}

export function Chat({ scrollContainerRef }: ChatProps) {
  const { items, awaiting, config, resumingConversationId } = useChatState();
  const maxUploadBytes = config?.max_upload_bytes || DEFAULT_MAX_UPLOAD_BYTES;
  const activeModelLabel = modelLabel(config);

  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lastUserMessageRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const spacerRef = useRef<HTMLDivElement>(null);
  const followLatestRef = useRef(true);
  const pendingUserScrollRef = useRef(false);
  const prevUserCountRef = useRef(0);
  const lastScrollTopRef = useRef(0);
  const [showScrollToLatest, setShowScrollToLatest] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const uploadingCount = attachments.filter((a) => a.uploading).length;
  const readyDescriptors = attachments
    .filter((a) => a.descriptor && !a.error)
    .map((a) => a.descriptor as UploadDescriptor);

  const handlePickFiles = () => fileInputRef.current?.click();

  const handleFilesSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length) return;

    const next: Attachment[] = [];
    for (const file of files) {
      const localId = `${file.name}-${file.size}-${Math.random().toString(36).slice(2)}`;
      if (file.size > maxUploadBytes) {
        next.push({ localId, file, uploading: false, error: "File exceeds the upload limit" });
        continue;
      }
      next.push({ localId, file, uploading: true });

      api
        .uploadFile(file)
        .then((descriptor) => {
          setAttachments((prev) =>
            prev.map((a) => (a.localId === localId ? { ...a, uploading: false, descriptor } : a)),
          );
        })
        .catch((err: unknown) => {
          setAttachments((prev) =>
            prev.map((a) =>
              a.localId === localId
                ? { ...a, uploading: false, error: err instanceof Error ? err.message : "Upload failed" }
                : a,
            ),
          );
        });
    }
    setAttachments((prev) => [...prev, ...next]);
  };

  const removeAttachment = (localId: string) =>
    setAttachments((prev) => prev.filter((a) => a.localId !== localId));

  // Prefill the composer from a ?prompt= query param (deep-link support) — populates
  // the input only, never auto-sends. Runs once, then scrubs the param.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    let prefill = params.get("prompt");
    if (prefill) {
      if (prefill.startsWith('"') && prefill.endsWith('"') && prefill.length >= 2) {
        prefill = prefill.slice(1, -1);
      }
      setInput(prefill);
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, []);

  const lastItem: ChatItem | undefined = items[items.length - 1];
  let lastUserIdx = -1;
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].kind === "user") {
      lastUserIdx = i;
      break;
    }
  }
  const userCount = items.filter((i) => i.kind === "user").length;
  const hasMessages = items.length > 0;
  // A resume clears `items` before awaiting, so `hasMessages` alone cannot tell an
  // empty conversation from one still being fetched — without this the welcome
  // screen flashed for the whole round trip.
  const resuming = resumingConversationId !== null;

  // Disabling the textarea for a resume drops its focus (a reload mounts it
  // enabled, so `autoFocus` fires first); give it back once the transcript lands.
  useEffect(() => {
    if (!resuming) textareaRef.current?.focus();
  }, [resuming]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [input]);

  const showLoadingDots = awaiting && lastItem?.kind === "user";

  // Once real content overflows, keep enough trailing room for the newest user
  // message to sit near the top. Measure with the previous spacer intact so a
  // temporary reset cannot clamp the scroll position during a streamed response.
  const updateSpacer = useCallback(() => {
    const el = scrollContainerRef.current;
    const userMsg = lastUserMessageRef.current;
    const spacer = spacerRef.current;
    if (!spacer) return;
    if (!el || !userMsg) {
      spacer.style.minHeight = "0px";
      return;
    }
    const elRect = el.getBoundingClientRect();
    const userTop = el.scrollTop + userMsg.getBoundingClientRect().top - elRect.top;
    const heightWithoutSpacer = el.scrollHeight - spacer.getBoundingClientRect().height;
    if (heightWithoutSpacer <= el.clientHeight) {
      spacer.style.minHeight = "0px";
      return;
    }
    const needed = Math.max(
      0,
      userTop + el.clientHeight - USER_MESSAGE_TOP_PADDING - heightWithoutSpacer,
    );
    spacer.style.minHeight = `${Math.ceil(needed)}px`;
  }, [scrollContainerRef]);

  // The spacer's previous sibling is always the latest rendered content,
  // including loading, tool, and ask rows that are not assistant messages.
  const getLatestScrollTop = useCallback(() => {
    const el = scrollContainerRef.current;
    const userMsg = lastUserMessageRef.current;
    const spacer = spacerRef.current;
    const latestContent = spacer?.previousElementSibling;
    if (!el || !userMsg || !latestContent) return 0;

    const elRect = el.getBoundingClientRect();
    const userTop = el.scrollTop + userMsg.getBoundingClientRect().top - elRect.top;
    const latestContentBottom =
      el.scrollTop + latestContent.getBoundingClientRect().bottom - elRect.top;
    return Math.max(
      userTop - USER_MESSAGE_TOP_PADDING,
      latestContentBottom - el.clientHeight + LATEST_MESSAGE_BOTTOM_PADDING,
      0,
    );
  }, [scrollContainerRef]);

  const scrollToLatest = useCallback((behavior: ScrollBehavior) => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const top = getLatestScrollTop();
    if (Math.abs(top - el.scrollTop) > 1) el.scrollTo({ top, behavior });
    if (behavior === "auto") lastScrollTopRef.current = el.scrollTop;
  }, [getLatestScrollTop, scrollContainerRef]);

  useLayoutEffect(() => {
    updateSpacer();
    const newUserMessage = userCount > prevUserCountRef.current;
    prevUserCountRef.current = userCount;

    if (!followLatestRef.current) return;
    const smooth = pendingUserScrollRef.current && newUserMessage;
    if (smooth) pendingUserScrollRef.current = false;
    scrollToLatest(
      smooth && !window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "smooth"
        : "auto",
    );
  }, [awaiting, items, scrollToLatest, updateSpacer, userCount]);

  useEffect(() => {
    const el = scrollContainerRef.current;
    const messageList = messageListRef.current;
    if (!el || !messageList) return;

    let frame = 0;
    let initialized = false;
    const syncLayout = () => {
      if (!initialized) {
        initialized = true;
        return;
      }
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        updateSpacer();
        if (followLatestRef.current) scrollToLatest("auto");
      });
    };
    // Handles wrapping, panel resizes, expanded tools, and async viewer loads.
    const observer = new ResizeObserver(syncLayout);
    observer.observe(el);
    observer.observe(messageList);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [hasMessages, scrollContainerRef, scrollToLatest, updateSpacer]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const scrollingUp = el.scrollTop < lastScrollTopRef.current - 1;
    const nearLatest = getLatestScrollTop() - el.scrollTop <= RESUME_FOLLOW_THRESHOLD;
    lastScrollTopRef.current = el.scrollTop;

    if (scrollingUp) {
      followLatestRef.current = false;
      setShowScrollToLatest(true);
    } else if (nearLatest) {
      followLatestRef.current = true;
      setShowScrollToLatest(false);
    } else if (!followLatestRef.current) {
      setShowScrollToLatest(true);
    }
  };

  const handleScrollToLatest = () => {
    followLatestRef.current = true;
    setShowScrollToLatest(false);
    updateSpacer();
    scrollToLatest(
      window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    );
  };

  const handleSend = (content = input.trim()) => {
    if (!content && !readyDescriptors.length) return;
    if (uploadingCount > 0) return;
    followLatestRef.current = true;
    pendingUserScrollRef.current = true;
    setShowScrollToLatest(false);
    void chatStore.sendTurn(content, readyDescriptors);
    setInput("");
    setAttachments([]);
  };

  const handleStop = () => chatStore.stop();

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  };

  const renderItem = (item: ChatItem, i: number) => {
    const userRef = i === lastUserIdx ? lastUserMessageRef : undefined;

    switch (item.kind) {
      case "user":
        return (
          <div key={item.id} ref={userRef} className="flex gap-2 justify-end">
            {item.text ? (
              <span className="px-4 py-2 rounded-xl max-w-xl text-base whitespace-pre-wrap bg-base-300 text-base-content">
                {item.text}
              </span>
            ) : null}
          </div>
        );

      case "tool":
        return (
          <div key={item.id} className="space-y-2">
            <ToolStep item={item} />
          </div>
        );

      case "error":
        return (
          <div key={item.id} className="flex gap-2 justify-start">
            <div className="w-6 h-6 shrink-0 flex items-center justify-center">
              <AlertCircle size={14} className="text-error/70" />
            </div>
            <div className="flex-1 text-sm text-error/90 bg-error/10 rounded px-3 py-2">{item.text}</div>
          </div>
        );

      case "needs_info": {
        const ni = item as NeedsInfoItem;
        return (
          <div key={item.id} className="flex gap-2 justify-start">
            <AssistantAvatar />
            <div className="flex-1 text-base text-base-content">
              {ni.message && <Markdown>{ni.message}</Markdown>}
              <FollowupForm
                fields={ni.fields}
                disabled={ni.submitted || awaiting}
                onSubmit={(answers) => chatStore.submitFollowup(ni.id, answers)}
              />
            </div>
          </div>
        );
      }

      case "plan": {
        const pl = item as PlanItem;
        return (
          <div key={item.id} className="flex gap-2 justify-start">
            <AssistantAvatar />
            <div className="flex-1 text-base text-base-content">
              {pl.message && <Markdown>{pl.message}</Markdown>}
              <PlanCard item={pl} disabled={awaiting} onDecide={(ok) => chatStore.decidePlan(pl.id, ok)} />
            </div>
          </div>
        );
      }

      case "assistant":
        return (
          <div key={item.id} className="flex gap-2 justify-start">
            <AssistantAvatar />
            <div className="flex-1 text-base text-base-content [&_p]:text-[length:inherit] [&_p]:leading-normal [&_p]:my-2 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:my-2 [&_a]:underline">
              {item.text && <Markdown>{item.text}</Markdown>}
              <ElementList elements={artifactsToElements(item.artifacts)} onSend={handleSend} />
              {item.recommendedMaterials.length > 0 && (
                <p className="mt-2 text-sm text-base-content/70">
                  Recommended materials: {item.recommendedMaterials.join(", ")}
                </p>
              )}
              {item.followUpSuggestions.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {item.followUpSuggestions.map((s) => (
                    <button
                      key={s}
                      className="btn btn-xs btn-ghost border border-base-300"
                      onClick={() => handleSend(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
    }
  };

  return (
    <div className="flex flex-col flex-1 w-full overflow-hidden">
      <div className="relative flex flex-1 min-h-0 overflow-hidden">
        {resuming ? (
          <div
            className="flex min-w-0 flex-1 flex-col items-center justify-center gap-4"
            role="status"
          >
            <span className="loading loading-spinner w-16 h-16 text-primary" />
            <p className="text-lg text-base-content/70">Loading conversation&hellip;</p>
          </div>
        ) : !hasMessages ? (
          <WelcomeScreen onSelect={(text) => handleSend(text)} />
        ) : (
          <div
            ref={scrollContainerRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto"
          >
            <div ref={messageListRef} className="max-w-4xl mx-auto p-5 space-y-5">
              {items.map((item, i) => renderItem(item, i))}

              {showLoadingDots && (
                <div
                  className="flex gap-2 justify-start"
                  aria-live="polite"
                  aria-label="Assistant is thinking"
                >
                  <AssistantAvatar />
                  <span className="loading loading-dots loading-md text-base-content self-center" />
                </div>
              )}

              <div ref={spacerRef} aria-hidden />
            </div>
          </div>
        )}

        {hasMessages && (
          <button
            type="button"
            onClick={handleScrollToLatest}
            className={`btn btn-circle btn-sm absolute bottom-4 left-1/2 z-10 -translate-x-1/2 border border-base-300 bg-base-100 text-base-content shadow-md transition-all duration-200 motion-reduce:transition-none hover:bg-base-200 dark:bg-accent dark:text-accent-content dark:hover:bg-accent/70 ${
              showScrollToLatest
                ? "translate-y-0 opacity-100"
                : "pointer-events-none translate-y-2 opacity-0"
            }`}
            aria-label="Scroll to latest message"
            aria-hidden={!showScrollToLatest}
            tabIndex={showScrollToLatest ? 0 : -1}
          >
            <ArrowDown size={18} />
          </button>
        )}
      </div>

      <div className="px-4 pt-3 pb-2">
        <div className="max-w-4xl mx-auto">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="*/*"
            className="hidden"
            onChange={handleFilesSelected}
          />
          <div className="rounded-3xl border border-base-300 bg-base-200 shadow-sm focus-within:border-primary/60 focus-within:shadow-md transition-all">
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 px-3 pt-3">
                {attachments.map((a) => (
                  <div
                    key={a.localId}
                    className={`flex items-center gap-2 rounded-full pl-2 pr-1 py-1 text-xs ${
                      a.error ? "bg-error/10 text-error" : "bg-base-300 text-base-content"
                    }`}
                    title={a.error ?? `${a.file.name} (${formatBytes(a.file.size)})`}
                  >
                    {a.uploading ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />}
                    <span className="max-w-45 truncate">{a.file.name}</span>
                    <span className="text-base-content/50">{formatBytes(a.file.size)}</span>
                    <button
                      onClick={() => removeAttachment(a.localId)}
                      className="rounded-full p-0.5 hover:bg-base-100"
                      aria-label={`Remove ${a.file.name}`}
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="relative flex items-end">
              <button
                className="btn btn-ghost btn-circle btn-sm absolute bottom-2.5 left-2.5"
                onClick={handlePickFiles}
                // An upload is staged under the session's current conversation, which
                // is still the previous one until the resume returns.
                disabled={awaiting || resuming}
                aria-label="Attach files"
              >
                <Paperclip size={16} />
              </button>
              <textarea
                ref={textareaRef}
                className="flex-1 bg-transparent resize-none outline-none pl-14 pr-14 py-4 text-base leading-6 placeholder:text-base-content/50 max-h-50"
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Message..."
                autoFocus
                // Until the resume returns, the server session is still bound to the
                // PREVIOUS conversation, so a turn sent now lands in the wrong one.
                disabled={resuming}
              />
              <button
                className="btn btn-primary btn-circle btn-sm absolute bottom-2.5 right-2.5 disabled:opacity-40"
                onClick={() => (awaiting ? handleStop() : handleSend())}
                disabled={resuming || (!awaiting && !input.trim() && readyDescriptors.length === 0)}
                aria-label={awaiting ? "Stop response" : "Send message"}
              >
                {awaiting ? (
                  <Square size={14} fill="currentColor" />
                ) : uploadingCount > 0 ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <ArrowUp size={18} />
                )}
              </button>
            </div>
          </div>
          {activeModelLabel !== null && (
            <p className="m-0 px-2 pt-1 text-right font-mono text-[11px] text-base-content/70">{activeModelLabel}</p>
          )}
        </div>
      </div>
      <p className="text-center text-xs text-base-content/70 pb-2">
        LLMs can make mistakes. Check important info.
      </p>
    </div>
  );
}
