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
 * The idle state of the chat panel (Figma dashboard-home 131:161): a session
 * strip, a hero, and a grid of suggestion cards.
 *
 * Visuals come from the redesign's `HomeWelcome`; the content is real —
 * intro/suggestion copy from the backend `/api/config` payload (falling back
 * to `src/config.ts`), gated to the Beginner chat profile exactly as the
 * pre-redesign welcome screen was. It renders *above* Chat's own composer, so
 * there is deliberately no input here: file uploads, the stop button, and the
 * upload-descriptor path all stay on the single real composer.
 */

import { Atom, Flame, Network, ShieldCheck, SplitSquareHorizontal } from "lucide-react";
import {
  chatIntro as fallbackIntro,
  chatSuggestionTitle as fallbackSuggestionTitle,
  workflowSuggestions as fallbackSuggestions,
} from "@/config";
import { StatusPill } from "@/components/ui/StatusPill";
import { useChatType } from "@/lib/useChatType";
import { useChatState } from "@/lib/store/chat";
import { SuggestionCard } from "../dashboard/SuggestionCard";

// `config.workflow_suggestions` is a plain string[], so icons are decorative
// and cycled positionally rather than carried by the data.
const CARD_ICONS = [
  <Flame size={14} />,
  <Network size={14} />,
  <ShieldCheck size={14} />,
  <SplitSquareHorizontal size={14} />,
];

export function WelcomeScreen({ onSelect }: { onSelect: (text: string) => void }) {
  const [chatType] = useChatType();
  const { config } = useChatState();
  const showSuggestions = chatType === "Beginner";
  const intro = config?.chat_intro || fallbackIntro;
  const suggestionTitle = config?.chat_suggestion_title || fallbackSuggestionTitle;
  const suggestions = config?.workflow_suggestions?.length
    ? config.workflow_suggestions
    : fallbackSuggestions;

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
      <div className="flex shrink-0 items-center justify-between px-6 pb-4 pt-6">
        <div>
          <p className="m-0 text-base font-bold text-base-content">New Session</p>
          <p className="m-0 text-xs text-base-content/60">Initialize reactor planner agent</p>
        </div>
        <StatusPill tone="neutral" label="Idle" />
      </div>

      <div className="flex flex-1 flex-col items-center justify-center gap-8 px-6 py-10">
        <div className="rounded-full border border-primary bg-primary/10 p-3">
          <Atom size={28} className="text-primary" />
        </div>
        <div className="max-w-md space-y-2 text-center">
          <h2 className="m-0 text-2xl font-bold text-base-content">{intro}</h2>
          {showSuggestions && (
            <p className="m-0 text-sm text-base-content/60">{suggestionTitle}</p>
          )}
        </div>
        {showSuggestions && (
          <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
            {suggestions.map((suggestion, i) => (
              <SuggestionCard
                key={suggestion}
                icon={CARD_ICONS[i % CARD_ICONS.length]}
                title={suggestion}
                onClick={() => onSelect(suggestion)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
