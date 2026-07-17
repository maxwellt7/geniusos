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

# Explicit lock: when True, even Clerk-authenticated requests are guests
# until the PIN is entered. This is what makes "Lock" real when handing the
# signed-in device to someone else. In-memory: a backend restart unlocks
# (Clerk still gates who can reach the API at all).
_locked = False


def _timeout_seconds() -> float:
    return get_settings().owner_session_timeout_minutes * 60


def _purge_expired() -> None:
    now = time.time()
    for token in [t for t, exp in _sessions.items() if exp < now]:
        _sessions.pop(token, None)


def resolve_mode(
    x_owner_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> str:
    """FastAPI dependency: returns 'owner' or 'guest' for this request."""
    settings = get_settings()

    def _valid_pin_token() -> bool:
        _purge_expired()
        if x_owner_token and x_owner_token in _sessions:
            # Sliding expiry: activity keeps the session alive.
            _sessions[x_owner_token] = time.time() + _timeout_seconds()
            return True
        return False

    # Explicitly locked: only a PIN unlock token restores owner mode, even
    # for Clerk-authenticated requests (the whole point of "Lock" is handing
    # the signed-in device to a guest).
    if _locked:
        return "owner" if _valid_pin_token() else "guest"

    # A valid Clerk session is the owner: sign-up is allowlisted to the owner,
    # so anyone who can authenticate via Clerk is the owner.
    from app.auth.clerk import clerk_user_from_header

    if clerk_user_from_header(authorization):
        return "owner"
    if not settings.owner_pin:
        return "owner"
    return "owner" if _valid_pin_token() else "guest"


def require_owner(mode: str = Depends(resolve_mode)) -> str:
    if mode != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    return mode


class UnlockRequest(BaseModel):
    pin: str


@router.post("/privacy/unlock")
def unlock(req: UnlockRequest):
    global _locked
    settings = get_settings()
    if not settings.owner_pin:
        _locked = False
        return {"mode": "owner", "token": None, "detail": "No PIN configured; always owner"}
    if not hmac.compare_digest(req.pin, settings.owner_pin):
        raise HTTPException(status_code=401, detail="Incorrect PIN")
    _locked = False
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + _timeout_seconds()
    return {"mode": "owner", "token": token}


@router.post("/privacy/lock")
def lock(x_owner_token: str | None = Header(default=None)):
    global _locked
    _locked = True
    _sessions.clear()
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
