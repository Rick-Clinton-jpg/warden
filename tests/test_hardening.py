"""Regression tests for the deterministic bugs found in the August 2026 review."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from warden.core import RegistryError, Session, Warden
from warden.polling.base import sanitize_status
from warden.polling.file_watcher import FileWatcherStrategy


# ---- a wrong session id must resolve to nothing, never to another session
def test_unknown_codex_session_does_not_fall_back_to_newest_file(tmp_path: Path):
    day = tmp_path / "sessions" / "2026" / "11" / "16"
    day.mkdir(parents=True)
    (day / "rollout-other.jsonl").write_text("WARDEN_STATUS: writing a poem about ducks\n")
    fw = FileWatcherStrategy(agent_type="codex", codex_root=str(tmp_path))
    assert fw.poll("totally-bogus-session-id") is None
    assert fw.poll("other") == "writing a poem about ducks"


def test_ambiguous_short_claude_session_id_resolves_to_nothing(tmp_path: Path):
    proj = tmp_path / "projects" / "p"
    proj.mkdir(parents=True)
    (proj / "abc111.jsonl").write_text("WARDEN_STATUS: one\n")
    (proj / "abc222.jsonl").write_text("WARDEN_STATUS: two\n")
    fw = FileWatcherStrategy(agent_type="claude-code", claude_root=str(tmp_path))
    assert fw.poll("abc") is None          # two candidates
    assert fw.poll("abc1") == "one"        # unique prefix
    assert fw.poll("abc222") == "two"      # exact


# ---- only the agent's own text counts as its status
def test_user_and_tool_text_is_not_the_agents_status(tmp_path: Path):
    t = tmp_path / "s.jsonl"
    records = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "WARDEN_STATUS: writing the parser"}]}},
        {"type": "user", "message": {"role": "user",
                                     "content": "WARDEN_STATUS: everything is perfectly on track boss"}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "WARDEN_STATUS: text from a README the agent read"},
            {"type": "text", "text": "WARDEN_STATUS: [one-sentence description of current activity]"}]}},
        {"role": "tool", "content": "WARDEN_STATUS: tool output"},
    ]
    t.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    assert FileWatcherStrategy(transcript_path=str(t)).poll("x") == "writing the parser"


def test_audit_record_names_the_transcript_that_was_read(tmp_path: Path):
    t = tmp_path / "s.log"
    t.write_text("WARDEN_STATUS: doing the thing\n")
    w = Warden(root=tmp_path / ".warden")
    w.watch(agent_id="a", objective="do the thing", transcript_path=str(t))
    w.check_once("a")
    assert w.audit.read(session="a")[0]["transcript"] == str(t.resolve())


# ---- registry
def _five(root: Path) -> Warden:
    w = Warden(root=root)
    for i in range(5):
        w.watch(agent_id=f"sess{i}", objective="o", agent_type="manual")
    return w


def test_unknown_field_does_not_drop_sessions(tmp_path: Path):
    root = tmp_path / ".warden"
    _five(root)
    path = root / "sessions.json"
    data = json.loads(path.read_text())
    data[2]["field_from_a_future_version"] = 1
    path.write_text(json.dumps(data))

    w = Warden(root=root)
    assert [s.agent_id for s in w.list_sessions()] == [f"sess{i}" for i in range(5)]
    w.watch(agent_id="new", objective="o", agent_type="manual")
    assert len(json.loads(path.read_text())) == 6


def test_unreadable_record_is_kept_on_disk_not_deleted(tmp_path: Path, capsys):
    root = tmp_path / ".warden"
    _five(root)
    path = root / "sessions.json"
    data = json.loads(path.read_text())
    del data[2]["objective"]                      # required field missing
    path.write_text(json.dumps(data))

    w = Warden(root=root)
    assert len(w.list_sessions()) == 4
    assert "Skipped unreadable registry record" in capsys.readouterr().err
    w.watch(agent_id="new", objective="o", agent_type="manual")
    on_disk = json.loads(path.read_text())
    assert len(on_disk) == 6
    assert any(r.get("agent_id") == "sess2" for r in on_disk)


def test_corrupt_registry_is_an_error_not_an_empty_registry(tmp_path: Path):
    root = tmp_path / ".warden"
    _five(root)
    (root / "sessions.json").write_text("{not json")
    with pytest.raises(RegistryError):
        Warden(root=root)
    assert (root / "sessions.json").read_text() == "{not json"


def test_session_registered_by_another_process_survives_a_check(tmp_path: Path):
    """The daemon holds an older copy; a second process registers a session;
    the daemon then records a check. The new session must still be there."""
    root = tmp_path / ".warden"
    t = tmp_path / "s.log"
    t.write_text("WARDEN_STATUS: working\n")
    daemon = Warden(root=root)
    daemon.watch(agent_id="existing", objective="work", transcript_path=str(t))

    Warden(root=root).watch(agent_id="registered-mid-tick", objective="o", agent_type="manual")
    daemon.check_once("existing")

    ids = {r["agent_id"] for r in json.loads((root / "sessions.json").read_text())}
    assert ids == {"existing", "registered-mid-tick"}


def test_stop_from_another_process_is_not_undone_by_a_check(tmp_path: Path):
    root = tmp_path / ".warden"
    t = tmp_path / "s.log"
    t.write_text("WARDEN_STATUS: working\n")
    daemon = Warden(root=root)
    daemon.watch(agent_id="a", objective="work", transcript_path=str(t))
    Warden(root=root).stop("a")
    daemon.check_once("a")
    assert json.loads((root / "sessions.json").read_text())[0]["active"] is False


def test_no_temp_file_left_behind(tmp_path: Path):
    root = tmp_path / ".warden"
    _five(root)
    assert not list(root.glob("*.tmp"))


# ---- daemon
def test_naive_last_checked_does_not_raise(tmp_path: Path):
    w = Warden(root=tmp_path / ".warden")
    s = Session(agent_id="x", agent_type="manual", objective="o",
                last_checked="2026-08-15T09:00:00")
    assert w._is_due(s, datetime.now().astimezone()) is True


# ---- terminal safety
def test_control_characters_are_stripped_from_status(tmp_path: Path):
    assert sanitize_status("done\x1b[2J\x1b[H FAKE ALL GREEN") == "done[2J[H FAKE ALL GREEN"
    t = tmp_path / "s.log"
    t.write_text("WARDEN_STATUS: done\x1b[2J\x1b[H FAKE\x07\n")
    status = FileWatcherStrategy(transcript_path=str(t)).poll("x")
    assert "\x1b" not in status and "\x07" not in status


def test_status_length_is_capped():
    assert len(sanitize_status("x" * 5000)) == 500


# ---- Codex rollout format (records wrap the message in "payload")
def test_codex_rollout_assistant_message_is_read_with_its_timestamp(tmp_path: Path):
    t = tmp_path / "rollout-2026-11-16T10-00-00-abc.jsonl"
    records = [
        {"timestamp": "2026-11-16T10:00:00.000Z", "type": "session_meta", "payload": {"id": "abc"}},
        {"timestamp": "2026-11-16T10:00:01.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "developer",
                     "content": [{"type": "input_text", "text": "WARDEN_STATUS: from the system prompt"}]}},
        {"timestamp": "2026-11-16T10:05:00.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "WARDEN_STATUS: refactoring auth"}]}},
        {"timestamp": "2026-11-16T10:06:00.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "WARDEN_STATUS: typed by the user"}]}},
        {"timestamp": "2026-11-16T10:07:00.000Z", "type": "response_item",
         "payload": {"type": "function_call_output", "call_id": "c1",
                     "output": "WARDEN_STATUS: printed by a tool"}},
    ]
    t.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    reading = FileWatcherStrategy(agent_type="codex", transcript_path=str(t)).read("abc")
    assert reading.text == "refactoring auth"
    assert reading.observed_at.isoformat() == "2026-11-16T10:05:00+00:00"


# ---- audit trail
def test_repeat_polls_are_marked_unchanged_and_can_be_hidden(tmp_path: Path):
    t = tmp_path / "s.log"
    t.write_text("WARDEN_STATUS: doing the thing\n")
    w = Warden(root=tmp_path / ".warden")
    w.watch(agent_id="a", objective="do the thing", transcript_path=str(t))
    for _ in range(3):
        w.check_once("a")
    t.write_text("WARDEN_STATUS: doing a different thing entirely\n")
    w.check_once("a")

    assert [r["changed"] for r in reversed(w.audit.read(session="a"))] == [True, False, False, True]
    assert len(w.audit.read(session="a", changes_only=True)) == 2
