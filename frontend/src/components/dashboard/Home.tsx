import { useRef } from "react";
import { chatStore, useChatState } from "@/lib/store/chat";
import { Chat } from "../Chat";
import { HomeWelcome } from "./HomeWelcome";
import { StatusPanel } from "./StatusPanel";

/**
 * Home = the merged command center (Figma dashboard-home / -chat / -artifacts).
 * A persistent status rail on the right; on the left, the welcome launcher
 * while idle, swapping to the live Chat once a conversation exists. Launching
 * from the welcome seeds the conversation (chat is already bootstrapped in
 * App.tsx at auth), which flips this to the active state.
 */
export function Home() {
  const { items } = useChatState();
  const active = items.length > 0;
  const scrollRef = useRef<HTMLDivElement>(null);

  return (
    <div className="flex flex-1 flex-col overflow-hidden lg:flex-row">
      <section className="flex min-w-0 flex-1 flex-col border-b border-base-300 lg:border-b-0 lg:border-r">
        {active ? (
          <Chat scrollContainerRef={scrollRef} />
        ) : (
          <HomeWelcome onStart={(prompt) => void chatStore.sendTurn(prompt)} />
        )}
      </section>
      <aside className="flex w-full shrink-0 flex-col lg:w-96 xl:w-[26rem]">
        <StatusPanel />
      </aside>
    </div>
  );
}
