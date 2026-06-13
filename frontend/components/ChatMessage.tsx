"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Citation, RoutingInfo } from "@/lib/api";
import CitationChip from "./CitationChip";

export interface UiMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  routing?: RoutingInfo;
  error?: string;
  streaming?: boolean;
}

const INTENT_LABELS: Record<string, string> = {
  semantic: "Semantic search",
  relational: "Knowledge graph",
  temporal: "Time filter",
  blocked: "Private",
};

/** Turn bare [1] citation markers into markdown links so we can render chips. */
function linkifyCitations(text: string): string {
  return text.replace(/\[(\d{1,2})\](?!\()/g, "[$1](#cite-$1)");
}

export default function ChatMessage({
  message,
  onCitationClick,
}: {
  message: UiMessage;
  onCitationClick: (c: Citation) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2.5 text-sm whitespace-pre-wrap">
          {message.content}
        </div>
      </div>
    );
  }

  const citationByN = new Map<number, Citation>();
  for (const c of message.citations ?? []) citationByN.set(c.n, c);

  return (
    <div className="flex flex-col items-start gap-1.5">
      {message.routing && (
        <span className="text-[11px] uppercase tracking-wide text-zinc-500">
          {INTENT_LABELS[message.routing.intent] ?? message.routing.intent}
          {message.routing.speaker ? ` · ${message.routing.speaker}` : ""}
          {message.routing.start_date
            ? ` · from ${message.routing.start_date.slice(0, 10)}`
            : ""}
        </span>
      )}
      <div className="max-w-[90%] rounded-2xl rounded-bl-sm bg-zinc-800/80 px-4 py-2.5 text-sm leading-relaxed markdown-body">
        {message.content ? (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children }) => {
                if (href?.startsWith("#cite-")) {
                  const n = parseInt(href.slice(6), 10);
                  const citation = citationByN.get(n);
                  if (citation) {
                    return (
                      <CitationChip
                        citation={citation}
                        onClick={onCitationClick}
                      />
                    );
                  }
                  return <span>[{n}]</span>;
                }
                return (
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="text-indigo-400 underline"
                  >
                    {children}
                  </a>
                );
              },
            }}
          >
            {linkifyCitations(message.content)}
          </ReactMarkdown>
        ) : message.streaming ? (
          <span className="inline-flex gap-1 py-1">
            <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 animate-bounce [animation-delay:300ms]" />
          </span>
        ) : null}
        {message.error && (
          <p className="text-red-400 text-xs mt-1">Error: {message.error}</p>
        )}
      </div>
      {(message.citations?.length ?? 0) > 0 && !message.streaming && (
        <div className="flex flex-wrap gap-1.5 max-w-[90%] pt-0.5">
          {message.citations!.map((c) => (
            <button
              key={c.n}
              onClick={() => onCitationClick(c)}
              className="text-[11px] px-2 py-1 rounded-lg bg-zinc-900 border border-zinc-700/70
                         text-zinc-400 hover:text-zinc-100 hover:border-indigo-500/50 transition-colors
                         max-w-[260px] truncate text-left cursor-pointer"
              title={c.snippet}
            >
              <span className="text-indigo-400 font-semibold mr-1">{c.n}</span>
              {c.lifelog_title}
              {c.start_time
                ? ` · ${new Date(c.start_time).toLocaleDateString()}`
                : ""}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
