import logging
import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.privacy import require_owner
from app.db.models import SyncState
from app.db.session import get_db
from app.ingestion.pipeline import run_sync

logger = logging.getLogger(__name__)
router = APIRouter()

_sync_lock = threading.Lock()


def _run_sync_safe(full: bool) -> None:
    try:
        run_sync(full=full)
    except Exception:
        logger.exception("Background sync failed")
    finally:
        _sync_lock.release()


@router.post("/sync", dependencies=[Depends(require_owner)])
def trigger_sync(full: bool = False):
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A sync is already running")
    thread = threading.Thread(target=_run_sync_safe, args=(full,), daemon=True)
    thread.start()
    return {"status": "started", "full": full}


@router.get("/sync/status")
def sync_status(db: Session = Depends(get_db)):
    state = db.get(SyncState, 1)
    if state is None:
        return {"status": "never_synced"}
    return {
        "status": state.last_sync_status,
        "running": _sync_lock.locked(),
        "last_updated_at": state.last_updated_at.isoformat() if state.last_updated_at else None,
        "last_sync_started": state.last_sync_started.isoformat() if state.last_sync_started else None,
        "last_sync_finished": state.last_sync_finished.isoformat() if state.last_sync_finished else None,
        "lifelogs_synced": state.lifelogs_synced,
        "error": state.last_sync_error,
    }
