"""Query history: list, read, and delete saved chat sessions.

Owner-only — chat history reveals everything ever asked and answered, so
guests get no access at all.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.privacy import require_owner
from app.db.models import ChatSession
from app.db.session import get_db

router = APIRouter(dependencies=[Depends(require_owner)])


@router.get("/chats")
def list_chats(db: Session = Depends(get_db), limit: int = Query(100, le=500)):
    sessions = db.execute(
        select(ChatSession).order_by(ChatSession.updated_at.desc()).limit(limit)
    ).scalars().all()
    return {
        "chats": [
            {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in sessions
        ]
    }


@router.get("/chats/{session_id}")
def get_chat(session_id: str, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "routing": m.routing,
            }
            for m in session.messages
        ],
    }


@router.delete("/chats/{session_id}")
def delete_chat(session_id: str, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    db.delete(session)
    db.commit()
    return {"deleted": session_id}
