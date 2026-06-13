"use client";

import { useEffect, useRef, useState } from "react";
import { Citation, LifelogDetail, fetchLifelog } from "@/lib/api";

export default function TranscriptDrawer({
  citation,
  lifelogId,
  onClose,
}: {
  citation: Citation | null;
  lifelogId: string | null;
  onClose: () => void;
}) {
  const id = citation?.lifelog_id ?? lifelogId;
  const [detail, setDetail] = useState<LifelogDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const highlightRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    setDetail(null);
    fetchLifelog(id)
      .then(setDetail)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  // Find the first utterance covered by the cited snippet to highlight.
  const snippetLines = (citation?.snippet ?? "")
    .split("\n")
    .map((l) => {
      const idx = l.indexOf(": ");
      return idx >= 0 ? l.slice(idx + 2).trim() : l.trim();
    })
    .filter((l) => l.length > 12 && !l.startsWith("#"));

  const highlightSequences = new Set<number>();
  if (detail && snippetLines.length > 0) {
    for (const u of detail.utterances) {
      if (snippetLines.some((l) => u.text.includes(l) || l.includes(u.text))) {
        highlightSequences.add(u.sequence);
      }
    }
  }

  useEffect(() => {
    if (detail && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [detail]);

  if (!id) return null;

  let firstHighlightRendered = false;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <aside className="relative w-full max-w-xl h-full bg-zinc-925 bg-zinc-900 border-l border-zinc-800 flex flex-col shadow-2xl">
        <header className="px-5 py-4 border-b border-zinc-800 flex items-start justify-between gap-4">
          <div>
            <h2 className="font-semibold text-zinc-100">
              {detail?.title ?? citation?.lifelog_title ?? "Transcript"}
            </h2>
            {detail?.start_time && (
              <p className="text-xs text-zinc-500 mt-0.5">
                {new Date(detail.start_time).toLocaleString()}
                {detail.end_time
                  ? ` – ${new Date(detail.end_time).toLocaleTimeString()}`
                  : ""}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-200 text-xl leading-none cursor-pointer"
            aria-label="Close"
          >
            ×
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {loading && <p className="text-zinc-500 text-sm">Loading transcript…</p>}
          {error && <p className="text-red-400 text-sm">{error}</p>}
          {detail?.utterances.map((u) => {
            const isHeading = u.node_type?.startsWith("heading");
            const highlighted = highlightSequences.has(u.sequence);
            const setRef = highlighted && !firstHighlightRendered;
            if (setRef) firstHighlightRendered = true;
            if (isHeading) {
              return (
                <h3
                  key={u.sequence}
                  className="text-sm font-semibold text-zinc-300 pt-3"
                >
                  {u.text}
                </h3>
              );
            }
            return (
              <div
                key={u.sequence}
                ref={setRef ? highlightRef : undefined}
                className={`rounded-lg px-3 py-2 text-sm ${
                  highlighted
                    ? "bg-indigo-500/15 border border-indigo-500/40"
                    : "bg-zinc-800/50"
                }`}
              >
                <div className="flex items-baseline justify-between gap-2 mb-0.5">
                  <span className="text-xs font-semibold text-indigo-300">
                    {u.speaker_name ??
                      (u.speaker_identifier === "user" ? "You" : "Unknown")}
                  </span>
                  {u.start_time && (
                    <span className="text-[10px] text-zinc-500 shrink-0">
                      {new Date(u.start_time).toLocaleTimeString()}
                    </span>
                  )}
                </div>
                <p className="text-zinc-200 leading-relaxed">{u.text}</p>
              </div>
            );
          })}
        </div>
      </aside>
    </div>
  );
}
