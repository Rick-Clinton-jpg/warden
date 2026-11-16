"""Tests for the status freshness rules and the STALE tag."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from warden.core import Warden, format_result_line
from warden.freshness import FRESH, STALE, UNVERIFIED, assess
from warden.polling.base import StatusReading
from warden.polling.file_watcher import FileWatcherStrategy, parse_record_time

NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)


def test_record_timestamp_fresh_and_stale():
    fresh = StatusReading("x", observed_at=NOW - timedelta(minutes=5), time_source="record-timestamp")
    stale = StatusReading("x", observed_at=NOW - timedelta(hours=33.8), time_source="record-timestamp")
    assert assess(fresh, NOW, 1800).state == FRESH
    result = assess(stale, NOW, 1800)
    assert result.state == STALE
    assert result.age_seconds == 121680.0


def test_boundary_is_not_stale():
    at_limit = StatusReading("x", observed_at=NOW - timedelta(seconds=1800))
    assert assess(at_limit, NOW, 1800).state == FRESH


def test_future_timestamp_is_clock_skew_not_negative_age():
    ahead = StatusReading("x", observed_at=NOW + timedelta(minutes=2))
    result = assess(ahead, NOW, 1800)
    assert result.state == FRESH and result.age_seconds == 0.0


def test_old_mtime_proves_stale():
    reading = StatusReading("x", latest_possible_at=NOW - timedelta(hours=2), time_source="file-mtime")
    result = assess(reading, NOW, 1800)
    assert result.state == STALE
    assert result.age_seconds is None and result.min_age_seconds == 7200


def test_recent_mtime_cannot_prove_fresh():
    reading = StatusReading("x", latest_possible_at=NOW - timedelta(seconds=10), time_source="file-mtime")
    assert assess(reading, NOW, 1800).state == UNVERIFIED


def test_no_time_evidence_is_unverified():
    assert assess(StatusReading("x"), NOW, 1800).state == UNVERIFIED
    assert assess(None, NOW, 1800).state == UNVERIFIED


def test_parse_record_time():
    assert parse_record_time("2026-11-16T12:00:00.123Z") == NOW.replace(microsecond=123000)
    assert parse_record_time("2026-11-16T17:30:00+05:30") == NOW
    # No offset -> ambiguous -> rejected rather than guessed
    assert parse_record_time("2026-11-16T12:00:00") is None
    assert parse_record_time("yesterday") is None
    assert parse_record_time(None) is None
    assert parse_record_time(1731758400) is None


def _write_transcript(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _assistant(text: str, when: datetime | None) -> dict:
    rec = {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    if when is not None:
        rec["timestamp"] = when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return rec


def test_file_watcher_reads_time_of_the_latest_status(tmp_path: Path):
    t = tmp_path / "s.jsonl"
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    new = datetime.now(timezone.utc) - timedelta(minutes=1)
    _write_transcript(t, [
        _assistant("WARDEN_STATUS: first thing", old),
        _assistant("WARDEN_STATUS: second thing", new),
        _assistant("no status in this later message", datetime.now(timezone.utc)),
    ])
    reading = FileWatcherStrategy(transcript_path=str(t)).read("any")
    assert reading.text == "second thing"
    assert abs((reading.observed_at - new).total_seconds()) < 1
    assert reading.time_source == "record-timestamp"


def test_stale_status_in_an_active_transcript_is_not_scored(tmp_path: Path):
    """The case the README describes: the transcript is still being written
    to, but the last status line is many hours old."""
    t = tmp_path / "s.jsonl"
    now = datetime.now(timezone.utc)
    _write_transcript(t, [
        _assistant("WARDEN_STATUS: Building the API wrapper endpoints", now - timedelta(hours=34)),
        _assistant("still working, no status line", now),
    ])
    w = Warden(root=tmp_path / ".warden")
    w.watch(agent_id="a", objective="Build API wrapper endpoints", transcript_path=str(t))
    result = w.check_once("a")

    assert result["tag"] == "STALE"
    assert result["word_tag"] is None and result["trigram_tag"] is None
    assert 33.9 * 3600 < result["status_age_seconds"] < 34.1 * 3600

    rec = w.audit.read(session="a")[0]
    assert rec["tag"] == "STALE"
    assert rec["freshness"] == "STALE"
    assert "word_score" not in rec
    assert rec["status"] == "Building the API wrapper endpoints"
    assert "34.0h old" in format_result_line(result)


def test_fresh_status_is_scored_as_before(tmp_path: Path):
    t = tmp_path / "s.jsonl"
    _write_transcript(t, [
        _assistant("WARDEN_STATUS: Build API wrapper endpoints",
                   datetime.now(timezone.utc) - timedelta(minutes=2)),
    ])
    w = Warden(root=tmp_path / ".warden")
    w.watch(agent_id="a", objective="Build API wrapper endpoints", transcript_path=str(t))
    result = w.check_once("a")
    assert result["tag"] == "MATCH"
    assert result["freshness"] == "FRESH"
    assert w.audit.read(session="a")[0]["word_score"] == 1.0


def test_untimestamped_transcript_old_file_is_stale(tmp_path: Path):
    t = tmp_path / "s.log"
    t.write_text("WARDEN_STATUS: Build API wrapper endpoints\n", encoding="utf-8")
    two_hours_ago = (datetime.now() - timedelta(hours=2)).timestamp()
    os.utime(t, (two_hours_ago, two_hours_ago))
    w = Warden(root=tmp_path / ".warden")
    w.watch(agent_id="a", objective="Build API wrapper endpoints", transcript_path=str(t))
    result = w.check_once("a")
    assert result["tag"] == "STALE"
    assert result["status_age_seconds"] is None
    assert result["status_min_age_seconds"] >= 7199


def test_untimestamped_transcript_recent_file_is_scored_but_flagged(tmp_path: Path):
    t = tmp_path / "s.log"
    t.write_text("WARDEN_STATUS: Build API wrapper endpoints\n", encoding="utf-8")
    w = Warden(root=tmp_path / ".warden")
    w.watch(agent_id="a", objective="Build API wrapper endpoints", transcript_path=str(t))
    result = w.check_once("a")
    assert result["tag"] == "MATCH"
    assert result["freshness"] == "UNVERIFIED"
    assert "could not be verified" in result["note"]


def test_stale_after_is_per_session_and_survives_reload(tmp_path: Path):
    w = Warden(root=tmp_path / ".warden")
    w.watch(agent_id="a", objective="o", stale_after_seconds=120)
    assert Warden(root=tmp_path / ".warden").list_sessions()[0].stale_after_seconds == 120


def test_registry_written_before_this_change_still_loads(tmp_path: Path):
    root = tmp_path / ".warden"
    root.mkdir()
    (root / "sessions.json").write_text(json.dumps([{
        "agent_id": "old", "agent_type": "claude-code", "objective": "o",
        "interval_seconds": 600, "strategy_name": "claude-code",
        "transcript_path": None, "created_at": "2026-08-15T09:00:00+05:30",
        "last_checked": None, "last_status": None, "last_tag": None,
        "last_word_tag": None, "last_trigram_tag": None, "active": True,
    }]), encoding="utf-8")
    sessions = Warden(root=root).list_sessions()
    assert len(sessions) == 1 and sessions[0].stale_after_seconds == 1800
