"use client";

import { Citation } from "@/lib/api";

export default function CitationChip({
  citation,
  onClick,
}: {
  citation: Citation;
  onClick: (c: Citation) => void;
}) {
  return (
    <button
      onClick={() => onClick(citation)}
      title={`${citation.lifelog_title}${
        citation.start_time
          ? ` — ${new Date(citation.start_time).toLocaleString()}`
          : ""
      }`}
      className="inline-flex items-center justify-center align-super text-[10px] font-semibold
                 min-w-[18px] h-[18px] px-1 mx-0.5 rounded-full
                 bg-indigo-500/20 text-indigo-300 border border-indigo-500/40
                 hover:bg-indigo-500/40 hover:text-indigo-100 transition-colors cursor-pointer"
    >
      {citation.n}
    </button>
  );
}
