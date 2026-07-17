import logging
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.privacy import require_owner
from app.config import get_settings
from app.db.models import Lifelog, SyncState
from app.db.session import get_db
from app.ingestion.pipeline import run_sync

logger = logging.getLogger(__name__)
router = APIRouter()

_sync_lock = threading.Lock()

# Give the app time to finish booting before the first scheduled sync.
_SCHEDULER_INITIAL_DELAY_SECONDS = 90.0


def _run_sync_safe(full: bool) -> None:
    try:
        run_sync(full=full)
    except Exception:
        logger.exception("Background sync failed")
    finally:
        _sync_lock.release()


def start_sync_scheduler() -> None:
    """Run incremental syncs on a fixed interval in a daemon thread.

    Uses the same lock as the manual /sync endpoint, so a scheduled run is
    skipped (not queued) while a manual sync is in flight, and vice versa.
    """
    interval_minutes = get_settings().sync_interval_minutes
    if interval_minutes <= 0:
        logger.info("Sync scheduler disabled (SYNC_INTERVAL_MINUTES<=0)")
        return

    def _loop() -> None:
        time.sleep(_SCHEDULER_INITIAL_DELAY_SECONDS)
        while True:
            if _sync_lock.acquire(blocking=False):
                logger.info("Starting scheduled incremental sync")
                _run_sync_safe(full=False)
            else:
                logger.info("Scheduled sync skipped; another sync is running")
            time.sleep(interval_minutes * 60)

    threading.Thread(target=_loop, name="sync-scheduler", daemon=True).start()
    logger.info("Sync scheduler started (every %d minutes)", interval_minutes)


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
    status = state.last_sync_status
    # The lock lives in this process: if the DB says "running" but no thread
    # holds the lock, the server restarted mid-sync. The next (scheduled or
    # manual) sync resumes from the watermark.
    if status == "running" and not _sync_lock.locked():
        status = "interrupted"
    graph_pending = db.execute(
        select(func.count()).select_from(Lifelog).where(Lifelog.graph_ingested.is_(False))
    ).scalar()
    return {
        "status": status,
        "graph_pending": graph_pending,
        "running": _sync_lock.locked(),
        "last_updated_at": state.last_updated_at.isoformat() if state.last_updated_at else None,
        "last_sync_started": state.last_sync_started.isoformat() if state.last_sync_started else None,
        "last_sync_finished": state.last_sync_finished.isoformat() if state.last_sync_finished else None,
        "lifelogs_synced": state.lifelogs_synced,
        "error": state.last_sync_error,
    }
