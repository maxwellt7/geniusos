export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---- Owner/guest session ----

const TOKEN_KEY = "limitless-owner-token";

export function getOwnerToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(TOKEN_KEY);
}

type ClerkGlobal = {
  loaded?: boolean;
  session?: { getToken: () => Promise<string | null> };
};

async function clerkToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { Clerk?: ClerkGlobal };
  // Clerk's JS hot-loads after hydration. Requests fired on mount would go
  // out without auth (backend 401s -> UI wrongly falls back to guest mode),
  // so wait briefly for Clerk before giving up on a token.
  for (let i = 0; i < 40 && !w.Clerk?.loaded; i++) {
    await new Promise((r) => setTimeout(r, 250));
  }
  try {
    return w.Clerk?.session ? await w.Clerk.session.getToken() : null;
  } catch {
    return null; // not signed in — fall through unauthenticated
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  const owner = getOwnerToken();
  if (owner) headers["X-Owner-Token"] = owner;
  const token = await clerkToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export interface PrivacyStatus {
  mode: "owner" | "guest";
  pin_configured: boolean;
}

export async function fetchPrivacyStatus(): Promise<PrivacyStatus> {
  const res = await fetch(`${API_BASE}/api/privacy/status`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to load privacy status");
  return res.json();
}

export async function unlockOwner(pin: string): Promise<boolean> {
  const res = await fetch(`${API_BASE}/api/privacy/unlock`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin }),
  });
  if (res.status === 401) return false;
  if (!res.ok) throw new Error("Unlock failed");
  const data = await res.json();
  if (data.token) sessionStorage.setItem(TOKEN_KEY, data.token);
  return true;
}

export async function lockOwner(): Promise<void> {
  await fetch(`${API_BASE}/api/privacy/lock`, {
    method: "POST",
    headers: await authHeaders(),
  });
  sessionStorage.removeItem(TOKEN_KEY);
}

export interface Citation {
  n: number;
  kind: "chunk" | "fact";
  lifelog_id: string | null;
  lifelog_title: string;
  start_time: string | null;
  speakers: string[];
  chunk_index: number | null;
  snippet: string;
}

export interface RoutingInfo {
  intent: string;
  search_query: string;
  start_date: string | null;
  end_date: string | null;
  speaker: string | null;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface LifelogSummary {
  id: string;
  title: string | null;
  start_time: string | null;
  end_time: string | null;
  is_starred: boolean;
}

export interface UtteranceDetail {
  sequence: number;
  node_type: string | null;
  speaker_name: string | null;
  speaker_identifier: string | null;
  text: string;
  start_time: string | null;
  start_offset_ms: number | null;
}

export interface LifelogDetail extends LifelogSummary {
  utterances: UtteranceDetail[];
}

export interface SyncStatus {
  status: string;
  running?: boolean;
  last_updated_at?: string | null;
  last_sync_started?: string | null;
  last_sync_finished?: string | null;
  lifelogs_synced?: number;
  error?: string | null;
}

export interface ChatSessionSummary {
  id: string;
  title: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ChatSessionDetail {
  id: string;
  title: string | null;
  messages: {
    role: "user" | "assistant";
    content: string;
    citations: Citation[];
    routing: RoutingInfo | null;
  }[];
}

export async function fetchChatSessions(): Promise<ChatSessionSummary[]> {
  const res = await fetch(`${API_BASE}/api/chats`, {
    headers: await authHeaders(),
  });
  if (res.status === 403) throw new OwnerRequiredError();
  if (!res.ok) throw new Error("Failed to load chat history");
  const data = await res.json();
  return data.chats;
}

export async function fetchChatSession(id: string): Promise<ChatSessionDetail> {
  const res = await fetch(`${API_BASE}/api/chats/${id}`, {
    headers: await authHeaders(),
  });
  if (res.status === 403) throw new OwnerRequiredError();
  if (!res.ok) throw new Error("Failed to load chat");
  return res.json();
}

export async function deleteChatSession(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chats/${id}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete chat");
}

export interface ChatStreamHandlers {
  onSession?: (sessionId: string) => void;
  onRouting?: (info: RoutingInfo) => void;
  onCitations?: (citations: Citation[]) => void;
  onToken?: (token: string) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
}

export async function streamChat(
  message: string,
  history: ChatTurn[],
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
  sessionId?: string | null
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ message, history, session_id: sessionId ?? null }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`Chat request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const processEvent = (block: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) return;
    const data = JSON.parse(dataLines.join("\n"));
    if (event === "session") handlers.onSession?.(data.id);
    else if (event === "routing") handlers.onRouting?.(data);
    else if (event === "citations") handlers.onCitations?.(data);
    else if (event === "token") handlers.onToken?.(data.token);
    else if (event === "error") handlers.onError?.(data.message);
    else if (event === "done") handlers.onDone?.();
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (block.trim()) processEvent(block);
    }
  }
}

export class OwnerRequiredError extends Error {
  constructor() {
    super("Owner access required");
    this.name = "OwnerRequiredError";
  }
}

export async function fetchLifelogs(limit = 50): Promise<LifelogSummary[]> {
  const res = await fetch(`${API_BASE}/api/lifelogs?limit=${limit}`, {
    headers: await authHeaders(),
  });
  if (res.status === 403) throw new OwnerRequiredError();
  if (!res.ok) throw new Error("Failed to load lifelogs");
  const data = await res.json();
  return data.lifelogs;
}

export async function fetchLifelog(id: string): Promise<LifelogDetail> {
  const res = await fetch(`${API_BASE}/api/lifelogs/${id}`, {
    headers: await authHeaders(),
  });
  if (res.status === 403) throw new OwnerRequiredError();
  if (!res.ok) throw new Error("Failed to load lifelog");
  return res.json();
}

export async function fetchSyncStatus(): Promise<SyncStatus> {
  const res = await fetch(`${API_BASE}/api/sync/status`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to load sync status");
  return res.json();
}

export async function triggerSync(full = false): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sync?full=${full}`, {
    method: "POST",
    headers: await authHeaders(),
  });
  if (res.status === 403) throw new OwnerRequiredError();
  if (!res.ok && res.status !== 409) {
    throw new Error("Failed to start sync");
  }
}
