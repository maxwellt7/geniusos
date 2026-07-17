"""One-off smoke test for the sync scheduler + status fixes (run: python test_sync_scheduler.py)."""

import threading

from fastapi.testclient import TestClient

import app.api.sync as sync_api
from app.main import app


def test_scheduler_thread_starts_on_app_startup():
    with TestClient(app):
        names = [t.name for t in threading.enumerate()]
        assert "sync-scheduler" in names, f"scheduler thread missing; threads: {names}"
    print("PASS: scheduler thread starts with the app")


def test_status_reports_interrupted_when_lock_free():
    class FakeState:
        last_sync_status = "running"
        last_updated_at = None
        last_sync_started = None
        last_sync_finished = None
        lifelogs_synced = 42
        last_sync_error = None

    class FakeResult:
        def scalar(self):
            return 0

    class FakeDb:
        def get(self, *_a, **_k):
            return FakeState()

        def execute(self, *_a, **_k):
            return FakeResult()

    out = sync_api.sync_status(db=FakeDb())
    assert out["status"] == "interrupted", out
    assert out["running"] is False, out

    # And while the lock is actually held, "running" stays "running".
    assert sync_api._sync_lock.acquire(blocking=False)
    try:
        out = sync_api.sync_status(db=FakeDb())
        assert out["status"] == "running", out
        assert out["running"] is True, out
    finally:
        sync_api._sync_lock.release()
    print("PASS: interrupted/running status logic")


def test_scheduler_disabled_when_interval_zero():
    from app.config import get_settings

    settings = get_settings()
    original = settings.sync_interval_minutes
    settings.sync_interval_minutes = 0
    try:
        before = sum(1 for t in threading.enumerate() if t.name == "sync-scheduler")
        sync_api.start_sync_scheduler()
        after = sum(1 for t in threading.enumerate() if t.name == "sync-scheduler")
        assert before == after, "scheduler started despite interval=0"
    finally:
        settings.sync_interval_minutes = original
    print("PASS: scheduler disabled at interval=0")


if __name__ == "__main__":
    test_status_reports_interrupted_when_lock_free()
    test_scheduler_disabled_when_interval_zero()
    test_scheduler_thread_starts_on_app_startup()
    print("ALL TESTS PASSED")
