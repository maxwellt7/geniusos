"use client";

import { useCallback, useEffect, useState } from "react";
import {
  LifelogSummary,
  OwnerRequiredError,
  SyncStatus,
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
}: {
  mode: "owner" | "guest" | null;
  onModeChange: (mode: "owner" | "guest") => void;
  onOpenLifelog: (id: string) => void;
}) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [lifelogs, setLifelogs] = useState<LifelogSummary[]>([]);
  const [dateFilter, setDateFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [pin, setPin] = useState("");
  const [pinError, setPinError] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await fetchSyncStatus());
    } catch {
      setStatus({ status: "backend_unreachable" });
      return;
    }
    try {
      setLifelogs(await fetchLifelogs(100));
    } catch (e) {
      if (e instanceof OwnerRequiredError) setLifelogs([]);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, [refresh, mode]);

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
      ? `Synced ${status.lifelogs_synced ?? 0} lifelogs`
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

      <div className="px-4 py-3 border-b border-zinc-800 space-y-2">
        <div className="flex items-center justify-between">
          <span
            className={`text-xs ${
              status?.status === "error" || status?.status === "backend_unreachable"
                ? "text-red-400"
                : "text-zinc-400"
            }`}
          >
            <span
              className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle ${
                running
                  ? "bg-amber-400 animate-pulse"
                  : status?.status === "success"
                  ? "bg-emerald-400"
                  : "bg-zinc-600"
              }`}
            />
            {statusLabel}
          </span>
          {mode === "owner" && (
            <button
              onClick={handleSync}
              disabled={busy || running}
              className="text-xs px-2.5 py-1 rounded-md bg-indigo-600 hover:bg-indigo-500
                         disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
            >
              {running ? "Syncing…" : "Sync now"}
            </button>
          )}
        </div>
        {status?.last_sync_finished && (
          <p className="text-[10px] text-zinc-600">
            Last sync {new Date(status.last_sync_finished).toLocaleString()}
          </p>
        )}
        {status?.error && (
          <p className="text-[10px] text-red-400/80 line-clamp-2">{status.error}</p>
        )}
      </div>

      {mode === "owner" ? (
        <>
          <div className="px-4 py-3 border-b border-zinc-800">
            <input
              type="date"
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
              className="w-full bg-zinc-900 border border-zinc-700/70 rounded-md px-2 py-1.5
                         text-xs text-zinc-300 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex-1 overflow-y-auto px-2 py-2">
            <p className="px-2 pb-1 text-[10px] uppercase tracking-wider text-zinc-600">
              Recent conversations
            </p>
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
                className="w-full text-left px-2 py-2 rounded-lg hover:bg-zinc-800/70 transition-colors cursor-pointer"
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
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center px-6">
          <p className="text-xs text-zinc-600 text-center leading-relaxed">
            Conversation browsing is locked.
            <br />
            Enter the PIN to view transcripts.
          </p>
        </div>
      )}
    </aside>
  );
}
