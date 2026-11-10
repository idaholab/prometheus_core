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

import { useRef, useState } from "react";
import { Chat } from "@/features/chat";
import { StatusPanel } from "./StatusPanel";

/**
 * Home = the merged command center (Figma dashboard-home / -chat / -artifacts):
 * the live Chat on the left, a persistent status rail on the right. Chat is
 * always mounted — it swaps its own transcript area for the Figma welcome
 * screen while idle, and keeps its composer either way.
 *
 * The scroll container ref lives here (not in Chat) so this panel and the
 * status rail scroll independently and the scrollbar sits at the panel
 * boundary rather than hugging Chat's narrower centered message column.
 */
export function Home() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [statusCollapsed, setStatusCollapsed] = useState(false);

  return (
    <div className="flex flex-1 flex-col overflow-hidden lg:flex-row">
      <section className="flex min-w-0 flex-1 flex-col border-b border-base-300 lg:border-b-0 lg:border-r">
        <Chat scrollContainerRef={scrollRef} />
      </section>
      <aside
        className={`flex shrink-0 flex-col overflow-hidden transition-[width] duration-200 ${
          statusCollapsed ? "w-16" : "w-full lg:w-96 xl:w-[26rem]"
        }`}
      >
        <StatusPanel
          collapsed={statusCollapsed}
          onCollapse={() => setStatusCollapsed(true)}
          onExpand={() => setStatusCollapsed(false)}
        />
      </aside>
    </div>
  );
}
