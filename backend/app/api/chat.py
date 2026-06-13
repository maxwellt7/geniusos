import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.privacy import resolve_mode
from app.db.models import PrivacyEvent
from app.db.session import get_db
from app.retrieval.retrievers import retrieve
from app.retrieval.router import classify_query
from app.retrieval.synthesis import build_citations, stream_answer

router = APIRouter()

# Deliberately non-confirming: never reveals whether matching content exists.
PRIVACY_REFUSAL = (
    "I can't share personal opinions or private statements about individuals. "
    "I'm happy to help with questions about meetings, decisions, events, or topics."
)


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat")
async def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    mode: str = Depends(resolve_mode),
):
    history = [t.model_dump() for t in req.history]

    routed = classify_query(req.message, history)

    if mode == "guest" and routed.privacy_sensitive:
        db.add(PrivacyEvent(question=req.message, subject_person=routed.subject_person))
        db.commit()

        def blocked_stream():
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
    if mode == "guest":
        # Snippets are raw transcript excerpts; they'd bypass the LLM-level
        # privacy rule. Guests get titles/timestamps only.
        citations = [{**c, "snippet": ""} for c in citations]

    def event_stream():
        yield _sse(
            "routing",
            {
                "intent": routed.intent,
                "search_query": routed.search_query,
                "start_date": routed.start_date.isoformat() if routed.start_date else None,
                "end_date": routed.end_date.isoformat() if routed.end_date else None,
                "speaker": routed.speaker,
            },
        )
        yield _sse("citations", citations)
        try:
            for token in stream_answer(
                req.message, routed, ctx, citations, history, guest_mode=(mode == "guest")
            ):
                yield _sse("token", {"token": token})
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})
            return
        yield _sse("done", {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
