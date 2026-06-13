from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.privacy import require_owner
from app.db.models import Lifelog, Utterance
from app.db.session import get_db

# Raw transcripts are owner-only: a guest browsing full conversations would
# bypass every chat-level privacy control.
router = APIRouter(dependencies=[Depends(require_owner)])


@router.get("/lifelogs")
def list_lifelogs(
    db: Session = Depends(get_db),
    limit: int = Query(50, le=200),
    offset: int = 0,
    start: datetime | None = None,
    end: datetime | None = None,
):
    stmt = select(Lifelog).order_by(Lifelog.start_time.desc()).limit(limit).offset(offset)
    if start:
        stmt = stmt.where(Lifelog.start_time >= start)
    if end:
        stmt = stmt.where(Lifelog.start_time <= end)
    lifelogs = db.execute(stmt).scalars().all()
    total = db.execute(select(func.count()).select_from(Lifelog)).scalar()

    return {
        "total": total,
        "lifelogs": [
            {
                "id": log.id,
                "title": log.title,
                "start_time": log.start_time.isoformat() if log.start_time else None,
                "end_time": log.end_time.isoformat() if log.end_time else None,
                "is_starred": log.is_starred,
            }
            for log in lifelogs
        ],
    }


@router.get("/lifelogs/{lifelog_id}")
def get_lifelog(lifelog_id: str, db: Session = Depends(get_db)):
    log = db.get(Lifelog, lifelog_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Lifelog not found")

    utterances = db.execute(
        select(Utterance)
        .where(Utterance.lifelog_id == lifelog_id)
        .order_by(Utterance.sequence)
    ).scalars().all()

    return {
        "id": log.id,
        "title": log.title,
        "start_time": log.start_time.isoformat() if log.start_time else None,
        "end_time": log.end_time.isoformat() if log.end_time else None,
        "is_starred": log.is_starred,
        "utterances": [
            {
                "sequence": u.sequence,
                "node_type": u.node_type,
                "speaker_name": u.speaker_name,
                "speaker_identifier": u.speaker_identifier,
                "text": u.text,
                "start_time": u.start_time.isoformat() if u.start_time else None,
                "start_offset_ms": u.start_offset_ms,
            }
            for u in utterances
        ],
    }
