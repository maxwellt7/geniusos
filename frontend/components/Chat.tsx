"use client";

import { useEffect, useRef, useState } from "react";
import {
  Citation,
  ChatTurn,
  fetchChatSession,
  fetchPrivacyStatus,
  streamChat,
} from "@/lib/api";
import ChatMessage, { UiMessage } from "./ChatMessage";
import Sidebar from "./Sidebar";
import TranscriptDrawer from "./TranscriptDrawer";

const SUGGESTIONS = [
  "What did I talk about today?",
  "Summarize my most recent conversation",
  "What advice have I been given recently?",
];

export default function Chat() {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [activeLifelogId, setActiveLifelogId] = useState<string | null>(null);
  const [privacyMode, setPrivacyMode] = useState<"owner" | "guest" | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [chatsRefreshKey, setChatsRefreshKey] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const newChat = () => {
    setMessages([]);
    setSessionId(null);
    setActiveCitation(null);
  };

  const openChat = async (id: string) => {
    try {
      const detail = await fetchChatSession(id);
      setSessionId(detail.id);
      setMessages(
        detail.messages.map((m) => ({
          role: m.role,
          content: m.content,
          citations: m.citations?.length ? m.citations : undefined,
          routing: m.routing ?? undefined,
        }))
      );
      setActiveCitation(null);
    } catch {
      // deleted or unreachable — fall back to a fresh chat
      newChat();
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    fetchPrivacyStatus()
      .then((s) => setPrivacyMode(s.mode))
      .catch(() => setPrivacyMode("guest"));
  }, []);

  // Locking hands the screen to a guest: wipe the owner's conversation.
  useEffect(() => {
    if (privacyMode === "guest") {
      setMessages([]);
      setSessionId(null);
      setActiveCitation(null);
      setActiveLifelogId(null);
    }
  }, [privacyMode]);

  // Re-check periodically: the server relocks owner sessions after idle timeout.
  useEffect(() => {
    const interval = setInterval(() => {
      fetchPrivacyStatus()
        .then((s) => setPrivacyMode(s.mode))
        .catch(() => {});
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || streaming) return;

    const history: ChatTurn[] = messages
      .filter((m) => !m.error)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [
      ...prev,
      { role: "user", content: trimmed },
      { role: "assistant", content: "", streaming: true },
    ]);
    setInput("");
    setStreaming(true);

    const update = (fn: (m: UiMessage) => UiMessage) => {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = fn(next[next.length - 1]);
        return next;
      });
    };

    try {
      await streamChat(
        trimmed,
        history,
        {
          onSession: (id) => {
            setSessionId(id);
            setChatsRefreshKey((k) => k + 1);
          },
          onRouting: (routing) => update((m) => ({ ...m, routing })),
          onCitations: (citations) =>
            update((m) => ({
              ...m,
              citations: citations.length ? citations : undefined,
            })),
          onToken: (token) =>
            update((m) => ({ ...m, content: m.content + token })),
          onError: (message) => update((m) => ({ ...m, error: message })),
          onDone: () => update((m) => ({ ...m, streaming: false })),
        },
        undefined,
        sessionId
      );
    } catch (e) {
      update((m) => ({
        ...m,
        error: e instanceof Error ? e.message : "Request failed",
      }));
    } finally {
      setStreaming(false);
      update((m) => ({ ...m, streaming: false }));
    }
  };

  return (
    <div className="flex h-dvh">
      {/* Mobile: sidebar becomes a slide-in drawer behind a backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <div
        className={`fixed inset-y-0 left-0 z-40 transition-transform duration-200 md:static md:z-auto md:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <Sidebar
          mode={privacyMode}
          onModeChange={setPrivacyMode}
          onOpenLifelog={(id) => {
            setActiveLifelogId(id);
            setSidebarOpen(false);
          }}
          activeChatId={sessionId}
          onSelectChat={(id) => {
            openChat(id);
            setSidebarOpen(false);
          }}
          onNewChat={() => {
            newChat();
            setSidebarOpen(false);
          }}
          chatsRefreshKey={chatsRefreshKey}
        />
      </div>

      <main className="flex-1 flex flex-col min-w-0">
        {/* Mobile top bar */}
        <div className="md:hidden flex items-center gap-3 px-4 py-3 border-b border-zinc-800 bg-zinc-950">
          <button
            onClick={() => setSidebarOpen(true)}
            aria-label="Open menu"
            className="text-zinc-300 hover:text-zinc-100 text-xl leading-none cursor-pointer"
          >
            ☰
          </button>
          <h1 className="font-semibold tracking-tight">
            Limitless <span className="text-indigo-400">Chat</span>
          </h1>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">
            {messages.length === 0 && (
              <div className="pt-24 text-center space-y-6">
                <div>
                  <h2 className="text-2xl font-semibold text-zinc-200">
                    Ask your memory anything
                  </h2>
                  <p className="text-sm text-zinc-500 mt-2">
                    Semantic search, relationship reasoning, and time filters
                    over your lifelogs.
                  </p>
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      className="text-xs px-3 py-2 rounded-full border border-zinc-700/80
                                 text-zinc-400 hover:text-zinc-100 hover:border-indigo-500/60
                                 transition-colors cursor-pointer"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <ChatMessage
                key={i}
                message={m}
                onCitationClick={(c) => {
                  if (privacyMode === "owner") setActiveCitation(c);
                }}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="border-t border-zinc-800 bg-zinc-950/80 backdrop-blur">
          <form
            className="max-w-3xl mx-auto px-6 py-4 flex gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about your conversations…"
              className="flex-1 bg-zinc-900 border border-zinc-700/70 rounded-xl px-4 py-3
                         text-sm placeholder:text-zinc-600 focus:outline-none focus:border-indigo-500"
            />
            <button
              type="submit"
              disabled={streaming || !input.trim()}
              className="px-5 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-sm font-medium
                         disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
            >
              {streaming ? "Thinking…" : "Send"}
            </button>
          </form>
        </div>
      </main>

      {privacyMode === "owner" && (activeCitation || activeLifelogId) && (
        <TranscriptDrawer
          citation={activeCitation}
          lifelogId={activeLifelogId}
          onClose={() => {
            setActiveCitation(null);
            setActiveLifelogId(null);
          }}
        />
      )}
    </div>
  );
}
