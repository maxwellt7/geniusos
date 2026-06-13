# Limitless Lifelog Query System

Conversational search over your [Limitless](https://www.limitless.ai) lifelogs, built on a
three-layer hybrid architecture:

| Layer | Store | Purpose |
| --- | --- | --- |
| Structured | Postgres (Neon) | Lifelog metadata, utterances, sync watermarks, temporal filters |
| Semantic | Pinecone (integrated embeddings) | Meaning-based search over transcript chunks |
| Relational | Neo4j Aura + Graphiti | Bi-temporal knowledge graph for multi-hop questions |

A FastAPI backend ingests the Limitless `/v1/lifelogs` API, routes each user question to the
right layer (semantic / relational / temporal), and streams LLM answers with citations back to a
Next.js chat UI.

## Setup

### 1. Provision services
- **Neon** (or any Postgres): create a database, copy the connection string.
- **Pinecone**: an index with integrated embeddings is expected (default name
  `limitless-lifelogs`, embedding field `chunk_text`).
- **Neo4j Aura**: create a free instance, note URI/user/password.
- API keys: Limitless, OpenAI.

### 2. Backend
```bash
cd backend
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your keys and connection strings
alembic upgrade head    # create tables
uvicorn app.main:app --reload --port 8000
```

### 3. Ingest data
```bash
# from backend/ with the venv active
python -m scripts.create_index    # one-time: create the Pinecone index
python -m scripts.sync            # incremental sync (Postgres + Pinecone)
python -m scripts.sync --full     # full backfill
python -m scripts.sync --graph    # knowledge graph ingestion (LLM-heavy, run when ready)
```
Set `ENABLE_GRAPH_INGESTION=true` in `.env` to chain graph ingestion onto every sync.

### 4. Frontend
```bash
cd frontend
pnpm install
cp .env.example .env.local
pnpm dev
```
Open http://localhost:3000.

## Privacy: owner/guest modes

Set `OWNER_PIN` in `backend/.env` and the app starts **locked in guest mode**:

- Privacy-sensitive questions (the owner's opinions/statements about people —
  "what does he think of me?") are refused before any retrieval runs, without
  confirming whether matching content exists, and logged to an audit table.
- Transcript browsing, citation snippets/drawers, and sync controls are owner-only.
- Answer synthesis carries a standing rule to suppress opinions about people
  in guest mode even when a query slips past the classifier.
- Entering the PIN unlocks owner mode for the session (sliding idle timeout,
  default 15 min, `OWNER_SESSION_TIMEOUT_MINUTES`). Blocked-query history:
  `GET /api/privacy/events` (owner only).

Leave `OWNER_PIN` empty to disable the lock entirely.

## API
- `POST /api/chat` — SSE stream: `routing`, `citations`, `token`*, `done` (header `X-Owner-Token` for owner mode)
- `POST /api/sync?full=bool` — trigger background sync (owner)
- `GET /api/sync/status` — watermark + last sync result
- `GET /api/lifelogs`, `GET /api/lifelogs/{id}` — browse transcripts (owner)
- `POST /api/privacy/unlock|lock`, `GET /api/privacy/status|events` — session management

## Project layout
```
backend/app/ingestion/   Limitless client, ContentNode parser, semantic chunker, pipeline
backend/app/vector/      Pinecone store (integrated embeddings)
backend/app/graph/       Graphiti + Neo4j entity types and episodes
backend/app/retrieval/   Intent router, multi-layer retrievers, cited synthesis
frontend/components/     Chat UI, citation chips, transcript drawer, sync sidebar
```
