"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ChatSessionSummary,
  LifelogSummary,
  OwnerRequiredError,
  SyncStatus,
  deleteChatSession,
  fetchChatSessions,
  fetchLifelogs,
  fetchSyncStatus,
  lockOwner,
  triggerSync,
  unlockOwner,
} from "@/lib/api";

export default function Sidebar({
  mode,
  onModeChange,
  onOpenLifelog,
  activeChatId,
  onSelectChat,
  onNewChat,
  chatsRefreshKey,
}: {
  mode: "owner" | "guest" | null;
  onModeChange: (mode: "owner" | "guest") => void;
  onOpenLifelog: (id: string) => void;
  activeChatId: string | null;
  onSelectChat: (id: string) => void;
  onNewChat: () => void;
  chatsRefreshKey: number;
}) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [lifelogs, setLifelogs] = useState<LifelogSummary[]>([]);
  const [chats, setChats] = useState<ChatSessionSummary[]>([]);
  const [recordingsOpen, setRecordingsOpen] = useState(false);
  const [dateFilter, setDateFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [pin, setPin] = useState("");
  const [pinError, setPinError] = useState(false);

  const refresh = useCallback(async () => {
    if (mode !== "owner") return;
    try {
      setStatus(await fetchSyncStatus());
    } catch {
      setStatus({ status: "backend_unreachable" });
    }
    try {
      setChats(await fetchChatSessions());
    } catch (e) {
      if (e instanceof OwnerRequiredError) setChats([]);
    }
    try {
      setLifelogs(await fetchLifelogs(100));
    } catch (e) {
      if (e instanceof OwnerRequiredError) setLifelogs([]);
    }
  }, [mode]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, [refresh, chatsRefreshKey]);

  const handleUnlock = async (e: React.FormEvent) => {
    e.preventDefault();
    setPinError(false);
    const ok = await unlockOwner(pin);
    setPin("");
    if (ok) {
      onModeChange("owner");
    } else {
      setPinError(true);
    }
  };

  const handleLock = async () => {
    await lockOwner();
    setLifelogs([]);
    setChats([]);
    onModeChange("guest");
  };

  const handleSync = async () => {
    setBusy(true);
    try {
      await triggerSync(false);
      await refresh();
    } catch {
      // owner-only; ignore in guest mode
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteChat = async (id: string) => {
    try {
      await deleteChatSession(id);
      setChats((prev) => prev.filter((c) => c.id !== id));
      if (id === activeChatId) onNewChat();
    } catch {
      // transient — next refresh reconciles
    }
  };

  const filtered = dateFilter
    ? lifelogs.filter((l) => l.start_time?.startsWith(dateFilter))
    : lifelogs;

  const running = status?.running;
  const statusLabel =
    status === null
      ? "Loading…"
      : status.status === "backend_unreachable"
      ? "Backend offline"
      : running
      ? "Syncing…"
      : status.status === "never_synced"
      ? "Never synced"
      : status.status === "success"
      ? `${status.lifelogs_synced ?? 0} lifelogs synced`
      : status.status === "error"
      ? "Last sync failed"
      : status.status ?? "Unknown";

  return (
    <aside className="w-72 shrink-0 h-full border-r border-zinc-800 bg-zinc-950 flex flex-col">
      <div className="px-4 py-4 border-b border-zinc-800">
        <h1 className="font-semibold text-lg tracking-tight">
          Limitless <span className="text-indigo-400">Chat</span>
        </h1>
        <p className="text-xs text-zinc-500 mt-0.5">
          Search your recorded conversations
        </p>
      </div>

      {/* Privacy lock */}
      <div className="px-4 py-3 border-b border-zinc-800">
        {mode === "owner" ? (
          <div className="flex items-center justify-between">
            <span className="text-xs text-emerald-400">
              <span className="mr-1.5">&#128275;</span>Owner mode
            </span>
            <button
              onClick={handleLock}
              className="text-xs px-2.5 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700 transition-colors cursor-pointer"
            >
              Lock
            </button>
          </div>
        ) : mode === "guest" ? (
          <form onSubmit={handleUnlock} className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs text-amber-400">
                <span className="mr-1.5">&#128274;</span>Guest mode
              </span>
            </div>
            <div className="flex gap-1.5">
              <input
                type="password"
                inputMode="numeric"
                value={pin}
                onChange={(e) => setPin(e.target.value)}
                placeholder="PIN"
                className="flex-1 min-w-0 bg-zinc-900 border border-zinc-700/70 rounded-md px-2 py-1
                           text-xs focus:outline-none focus:border-indigo-500"
              />
              <button
                type="submit"
                disabled={!pin}
                className="text-xs px-2.5 py-1 rounded-md bg-indigo-600 hover:bg-indigo-500
                           disabled:opacity-40 transition-colors cursor-pointer"
              >
                Unlock
              </button>
            </div>
            {pinError && <p className="text-[10px] text-red-400">Incorrect PIN</p>}
          </form>
        ) : (
          <span className="text-xs text-zinc-600">Checking access…</span>
        )}
      </div>

      {mode === "owner" ? (
        <>
          {/* Query history */}
          <div className="px-3 py-3">
            <button
              onClick={onNewChat}
              className="w-full text-left text-sm px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500
                         font-medium transition-colors cursor-pointer"
            >
              + New chat
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-2 pb-2 min-h-0">
            <p className="px-2 pb-1 text-[10px] uppercase tracking-wider text-zinc-600">
              Query history
            </p>
            {chats.length === 0 && (
              <p className="px-2 text-xs text-zinc-600">No saved chats yet.</p>
            )}
            {chats.map((c) => (
              <div
                key={c.id}
                className={`group flex items-center rounded-lg transition-colors ${
                  c.id === activeChatId ? "bg-zinc-800" : "hover:bg-zinc-800/70"
                }`}
              >
                <button
                  onClick={() => onSelectChat(c.id)}
                  className="flex-1 min-w-0 text-left px-2 py-2 cursor-pointer"
                >
                  <p className="text-xs text-zinc-200 truncate">
                    {c.title || "Untitled chat"}
                  </p>
                  {c.updated_at && (
                    <p className="text-[10px] text-zinc-500">
                      {new Date(c.updated_at).toLocaleString(undefined, {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </p>
                  )}
                </button>
                <button
                  onClick={() => handleDeleteChat(c.id)}
                  title="Delete chat"
                  className="opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-red-400
                             px-2 py-1 text-xs transition-opacity cursor-pointer"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>

          {/* Limitless recordings — pinned to the bottom, collapsible */}
          <div className="border-t border-zinc-800 shrink-0">
            <button
              onClick={() => setRecordingsOpen((v) => !v)}
              className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-zinc-900/70
                         transition-colors cursor-pointer"
            >
              <span className="text-[10px] uppercase tracking-wider text-zinc-500">
                Limitless recordings
              </span>
              <span className="flex items-center gap-2">
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full ${
                    running
                      ? "bg-amber-400 animate-pulse"
                      : status?.status === "success"
                      ? "bg-emerald-400"
                      : "bg-zinc-600"
                  }`}
                />
                <span className="text-zinc-500 text-xs">
                  {recordingsOpen ? "▾" : "▴"}
                </span>
              </span>
            </button>
            {recordingsOpen && (
              <div className="border-t border-zinc-800/60">
                <div className="px-4 py-2 flex items-center justify-between gap-2">
                  <span
                    className={`text-[11px] ${
                      status?.status === "error" ||
                      status?.status === "backend_unreachable"
                        ? "text-red-400"
                        : "text-zinc-500"
                    }`}
                  >
                    {statusLabel}
                  </span>
                  <button
                    onClick={handleSync}
                    disabled={busy || running}
                    className="text-[11px] px-2 py-0.5 rounded-md bg-zinc-800 hover:bg-zinc-700
                               disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    {running ? "Syncing…" : "Sync now"}
                  </button>
                </div>
                <div className="px-4 pb-2">
                  <input
                    type="date"
                    value={dateFilter}
                    onChange={(e) => setDateFilter(e.target.value)}
                    className="w-full bg-zinc-900 border border-zinc-700/70 rounded-md px-2 py-1
                               text-xs text-zinc-300 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div className="max-h-56 overflow-y-auto px-2 pb-2">
                  {filtered.length === 0 && (
                    <p className="px-2 text-xs text-zinc-600">
                      {lifelogs.length === 0
                        ? "No lifelogs yet. Run a sync."
                        : "No lifelogs on this date."}
                    </p>
                  )}
                  {filtered.map((log) => (
                    <button
                      key={log.id}
                      onClick={() => onOpenLifelog(log.id)}
                      className="w-full text-left px-2 py-1.5 rounded-lg hover:bg-zinc-800/70 transition-colors cursor-pointer"
                    >
                      <p className="text-xs text-zinc-200 truncate">
                        {log.is_starred ? "★ " : ""}
                        {log.title ?? "Untitled"}
                      </p>
                      {log.start_time && (
                        <p className="text-[10px] text-zinc-500">
                          {new Date(log.start_time).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "numeric",
                            minute: "2-digit",
                          })}
                        </p>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </>
      ) : (
        // Guests see nothing: no recordings, no query history — chat only.
        <div className="flex-1" />
      )}
    </aside>
  );
}
