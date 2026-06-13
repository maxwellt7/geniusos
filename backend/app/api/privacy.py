"""Owner/guest session management.

The app defaults to GUEST mode. A PIN (OWNER_PIN in .env) unlocks OWNER mode
for the session via a bearer token with a sliding idle timeout. If no PIN is
configured, the app always runs in owner mode.

Guests:
- cannot run privacy-sensitive queries (owner's opinions/statements about people)
- cannot list or read raw transcripts
"""

import hmac
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import PrivacyEvent
from app.db.session import get_db

router = APIRouter()

# token -> expiry epoch seconds (in-memory; relocks on backend restart)
_sessions: dict[str, float] = {}


def _timeout_seconds() -> float:
    return get_settings().owner_session_timeout_minutes * 60


def _purge_expired() -> None:
    now = time.time()
    for token in [t for t, exp in _sessions.items() if exp < now]:
        _sessions.pop(token, None)


def resolve_mode(x_owner_token: str | None = Header(default=None)) -> str:
    """FastAPI dependency: returns 'owner' or 'guest' for this request."""
    settings = get_settings()
    if not settings.owner_pin:
        return "owner"
    _purge_expired()
    if x_owner_token and x_owner_token in _sessions:
        # Sliding expiry: activity keeps the session alive.
        _sessions[x_owner_token] = time.time() + _timeout_seconds()
        return "owner"
    return "guest"


def require_owner(mode: str = Depends(resolve_mode)) -> str:
    if mode != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    return mode


class UnlockRequest(BaseModel):
    pin: str


@router.post("/privacy/unlock")
def unlock(req: UnlockRequest):
    settings = get_settings()
    if not settings.owner_pin:
        return {"mode": "owner", "token": None, "detail": "No PIN configured; always owner"}
    if not hmac.compare_digest(req.pin, settings.owner_pin):
        raise HTTPException(status_code=401, detail="Incorrect PIN")
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + _timeout_seconds()
    return {"mode": "owner", "token": token}


@router.post("/privacy/lock")
def lock(x_owner_token: str | None = Header(default=None)):
    if x_owner_token:
        _sessions.pop(x_owner_token, None)
    return {"mode": "guest"}


@router.get("/privacy/status")
def status(mode: str = Depends(resolve_mode)):
    settings = get_settings()
    return {"mode": mode, "pin_configured": bool(settings.owner_pin)}


@router.get("/privacy/events")
def list_events(
    db: Session = Depends(get_db),
    _: str = Depends(require_owner),
    limit: int = 100,
):
    events = db.execute(
        select(PrivacyEvent).order_by(PrivacyEvent.created_at.desc()).limit(limit)
    ).scalars().all()
    return {
        "events": [
            {
                "id": e.id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "question": e.question,
                "subject_person": e.subject_person,
                "action": e.action,
            }
            for e in events
        ]
    }
