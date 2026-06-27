export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---- Owner/guest session ----

const TOKEN_KEY = "limitless-owner-token";

export function getOwnerToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(TOKEN_KEY);
}

async function authHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  const owner = getOwnerToken();
  if (owner) headers["X-Owner-Token"] = owner;
  if (typeof window !== "undefined") {
    try {
      const clerk = (
        window as unknown as {
          Clerk?: { session?: { getToken: () => Promise<string | null> } };
        }
      ).Clerk;
      const token = clerk?.session ? await clerk.session.getToken() : null;
      if (token) headers["Authorization"] = `Bearer ${token}`;
    } catch {
      // Clerk not ready / not signed in — fall through unauthenticated.
    }
  }
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

export interface ChatStreamHandlers {
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
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ message, history }),
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
    if (event === "routing") handlers.onRouting?.(data);
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
