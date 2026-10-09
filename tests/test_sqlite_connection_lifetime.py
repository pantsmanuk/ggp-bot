"""Connections must close without relying on garbage collection."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from ggp_bot.db_cleanup import scheduler
from ggp_bot.intranet.state_tracking import TimeClockStateTracker
from ggp_bot.intranet.token_storage import TokenStorage
from ggp_bot.slack.lunch_timer import LunchTimerManager


@pytest.fixture
def connections(monkeypatch):
    # Keep strong references so garbage collection cannot hide leaked handles.
    opened = []
    connect = sqlite3.connect

    def tracked_connect(*args, **kwargs):
        conn = connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    try:
        yield opened
    finally:
        for conn in opened:
            conn.close()


def assert_closed(connections):
    assert connections
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            conn.execute("SELECT 1")


def test_token_storage_persistence_and_closure(tmp_path, connections):
    storage = TokenStorage(tmp_path / "tokens.db", Fernet.generate_key().decode())
    assert storage.get_token("missing") is None
    storage.save_token("U1", "test-token", ["bot:directory"])
    assert storage.get_token("U1").token == "test-token"
    assert storage.has_token("U1")
    assert storage.get_all_users() == ["U1"]
    assert storage.get_stats()["total_tokens"] == 1
    storage.log_token_audit_summary()
    assert storage.validate_all_tokens()["valid"] == 1
    storage.save_token("U1", "updated-token", ["bot:directory"])
    assert storage.get_token("U1").token == "updated-token"
    assert storage.remove_token("U1")
    assert not storage.remove_token("U1")
    storage.save_token("expired", "test-token", ["bot:directory"], "2000-01-01T00:00:00")
    assert storage.get_token("expired") is None
    assert storage.get_all_users() == []
    storage.save_token("U2", "test-token", ["bot:directory"])
    assert storage.clear_all() == 1
    assert storage.get_stats()["total_tokens"] == 0
    assert_closed(connections)


def test_timeclock_persistence_and_closure(tmp_path, connections):
    tracker = TimeClockStateTracker(str(tmp_path / "state.db"))
    assert tracker.get_last_state("U1") is None
    tracker.update_state("U1", "in", 1)
    assert tracker.get_last_state("U1") == "in"
    assert not tracker.should_notify("U1", "in")
    assert tracker.should_notify("U1", "out")
    tracker.update_state("U1", "out", 2)
    assert tracker.get_last_state("U1") == "out"
    tracker.clear_state("U1")
    assert tracker.get_last_state("U1") is None
    assert_closed(connections)


@pytest.mark.asyncio
async def test_timer_polling_and_warnings_close_connections(tmp_path, connections):
    manager = LunchTimerManager(tmp_path / "timers.db")
    manager.set_client(AsyncMock())
    assert not manager.has_active_timer("U1")
    assert manager._load_timer_from_db("missing") is None
    assert manager.start_timer("U1", "C1")
    manager._active_timers.clear()
    assert not manager.start_timer("U1", "C1")
    assert manager.has_active_timer("U1")
    manager._active_timers.clear()
    await manager._process_timers()
    timer = manager._active_timers["U1"]
    manager._send_warning = AsyncMock()
    for minutes in (55, 59, 60):
        timer.start_time = datetime.now() - timedelta(minutes=minutes)
        await manager._process_timers()
    assert manager._send_warning.await_count == 3
    manager._active_timers.clear()
    timer = manager._load_timer_from_db("U1")
    assert timer.warning_55_sent and timer.warning_59_sent and timer.warning_60_sent
    assert manager.cancel_timer("U1")
    assert not manager.cancel_timer("U1")
    # More checks than a typical 1024-descriptor limit allows leaked connections.
    for _ in range(1200):
        await manager._process_timers()
    assert_closed(connections)


@pytest.mark.asyncio
async def test_cleanup_and_token_audit_close_connections(tmp_path, connections, monkeypatch):
    storage = TokenStorage(tmp_path / "tokens.db", Fernet.generate_key().decode())
    manager = LunchTimerManager(tmp_path / "timers.db")
    tracker = TimeClockStateTracker(str(tmp_path / "state.db"))
    monkeypatch.setattr(scheduler, "token_storage", storage)
    monkeypatch.setattr(scheduler, "lunch_timer_manager", manager)
    monkeypatch.setattr(scheduler, "timeclock_tracker", tracker)
    storage.save_token("U1", "test-token", ["bot:directory"])
    manager.start_timer("U1", "C1")
    tracker.update_state("U1", "in", 1)
    result = await scheduler.DatabaseCleanupScheduler().run_now()
    assert result["lunch_timers_removed"] == 1
    assert result["timeclock_records_removed"] == 1
    assert result["token_audit"]["valid"] == 1
    assert not manager.has_active_timer("U1")
    assert tracker.get_last_state("U1") is None
    assert storage.has_token("U1")
    assert_closed(connections)


def test_failed_token_write_rolls_back_and_closes(tmp_path, connections, monkeypatch):
    storage = TokenStorage(tmp_path / "tokens.db", Fernet.generate_key().decode())
    connect = sqlite3.connect

    class FailedCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("injected commit failure")

    def failing_connect(*args, **kwargs):
        return connect(*args, factory=FailedCommit, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", failing_connect)
        with pytest.raises(sqlite3.OperationalError, match="injected commit failure"):
            storage.save_token("U1", "test-token", ["bot:directory"])
    assert storage.get_token("U1") is None
    assert_closed(connections)


@pytest.mark.asyncio
async def test_timer_read_error_closes_connection(tmp_path, connections, caplog):
    manager = LunchTimerManager(tmp_path / "timers.db")
    manager.set_client(AsyncMock())
    conn = sqlite3.connect(manager.db_path)
    conn.execute("DROP TABLE lunch_timers")
    conn.commit()
    conn.close()
    await manager._process_timers()
    assert "Failed to load timers from DB" in caplog.text
    assert_closed(connections)
