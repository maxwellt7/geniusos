import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.privacy import resolve_mode
from app.db.models import ChatMessage, ChatSession, PrivacyEvent, utcnow
from app.db.session import db_session, get_db
from app.retrieval.retrievers import retrieve
from app.retrieval.router import classify_query
from app.retrieval.synthesis import build_citations, stream_answer

router = APIRouter()

# Deliberately non-confirming: never reveals whether matching content exists.
PRIVACY_REFUSAL = (
    "I can't share private or personal information about the owner or other "
    "individuals. I'm happy to help with questions about meetings, decisions, "
    "events, or topics."
)


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []
    session_id: str | None = None


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _next_sequence(session: Session, session_id: str) -> int:
    current = session.execute(
        select(func.max(ChatMessage.sequence)).where(ChatMessage.session_id == session_id)
    ).scalar()
    return (current or 0) + 1


def _ensure_session(session_id: str | None, first_message: str) -> str:
    """Create the chat session on first message; bump updated_at otherwise."""
    with db_session() as session:
        if session_id:
            existing = session.get(ChatSession, session_id)
            if existing is not None:
                existing.updated_at = utcnow()
                return existing.id
        new_id = uuid.uuid4().hex
        title = first_message.strip()[:80] or "New chat"
        session.add(ChatSession(id=new_id, title=title))
        return new_id


def _save_message(
    session_id: str,
    role: str,
    content: str,
    citations: list | None = None,
    routing: dict | None = None,
) -> None:
    with db_session() as session:
        session.add(
            ChatMessage(
                session_id=session_id,
                sequence=_next_sequence(session, session_id),
                role=role,
                content=content,
                citations=citations or [],
                routing=routing,
            )
        )
        chat = session.get(ChatSession, session_id)
        if chat is not None:
            chat.updated_at = utcnow()


@router.post("/chat")
async def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    mode: str = Depends(resolve_mode),
):
    history = [t.model_dump() for t in req.history]

    routed = classify_query(req.message, history)
    routing_payload = {
        "intent": routed.intent,
        "search_query": routed.search_query,
        "start_date": routed.start_date.isoformat() if routed.start_date else None,
        "end_date": routed.end_date.isoformat() if routed.end_date else None,
        "speaker": routed.speaker,
    }

    chat_session_id = _ensure_session(req.session_id, req.message)
    _save_message(chat_session_id, "user", req.message)

    if mode == "guest" and routed.privacy_sensitive:
        db.add(PrivacyEvent(question=req.message, subject_person=routed.subject_person))
        db.commit()
        _save_message(
            chat_session_id, "assistant", PRIVACY_REFUSAL,
            routing={**routing_payload, "intent": "blocked"},
        )

        def blocked_stream():
            yield _sse("session", {"id": chat_session_id})
            yield _sse("routing", {"intent": "blocked", "search_query": "", "start_date": None,
                                   "end_date": None, "speaker": None})
            yield _sse("citations", [])
            yield _sse("token", {"token": PRIVACY_REFUSAL})
            yield _sse("done", {})

        return StreamingResponse(
            blocked_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    ctx = await retrieve(db, routed)
    citations = build_citations(ctx)
    # Guests get NO citation metadata: even titles/speakers/timestamps leak
    # the contents of private conversations. The model still cites [n]
    # markers internally; they render as plain text without chips.
    client_citations = [] if mode == "guest" else citations

    def event_stream():
        yield _sse("session", {"id": chat_session_id})
        yield _sse("routing", routing_payload)
        yield _sse("citations", client_citations)
        answer_parts: list[str] = []
        try:
            for token in stream_answer(
                req.message, routed, ctx, citations, history, guest_mode=(mode == "guest")
            ):
                answer_parts.append(token)
                yield _sse("token", {"token": token})
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})
            return
        finally:
            if answer_parts:
                _save_message(
                    chat_session_id, "assistant", "".join(answer_parts),
                    citations=client_citations, routing=routing_payload,
                )
        yield _sse("done", {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
