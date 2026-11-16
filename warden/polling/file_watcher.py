"""File-watcher polling for Claude Code and Codex session transcripts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import PollingStrategy, StatusReading


def parse_record_time(value: object) -> Optional[datetime]:
    """Parse a transcript record's ISO-8601 timestamp into an aware datetime.

    Returns None for anything that is not an unambiguous point in time
    (missing, malformed, or without a UTC offset) -- a guessed timezone
    would make a stale status look fresh or the reverse.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _expand(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


class FileWatcherStrategy(PollingStrategy):
    """
    Poll Claude Code / Codex session transcripts for the latest
    WARDEN_STATUS line.

    Claude Code layout (2026):
        ~/.claude/projects/<encoded-project-path>/<session-id>.jsonl

    Codex layout:
        ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
        (or direct path if the user supplies a full transcript path)

    We support two modes:
    1. Explicit transcript path via `transcript_path`
    2. Heuristic search under the known roots using `session_id`
    """

    def __init__(
        self,
        agent_type: str = "claude-code",
        transcript_path: Optional[str] = None,
        claude_root: Optional[str] = None,
        codex_root: Optional[str] = None,
        max_tail_lines: int = 400,
    ):
        self.agent_type = agent_type
        self.transcript_path = (
            _expand(transcript_path) if transcript_path else None
        )
        self.claude_root = _expand(
            claude_root or os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")
        )
        self.codex_root = _expand(
            codex_root or os.environ.get("CODEX_HOME", "~/.codex")
        )
        self.max_tail_lines = max_tail_lines

    def poll(self, session_id: str) -> Optional[str]:
        reading = self.read(session_id)
        return reading.text if reading else None

    def read(self, session_id: str) -> Optional[StatusReading]:
        path = self._resolve_transcript(session_id)
        if path is None or not path.exists():
            return None

        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            text = self._read_tail(path)
        except OSError:
            return None

        # JSONL transcripts: keep each record's own timestamp with its text
        if path.suffix == ".jsonl":
            pieces = self._extract_pieces_from_jsonl(text)
        else:
            pieces = [(text, None)]

        latest: Optional[StatusReading] = None
        for piece_text, record_time in pieces:
            status = self.extract_status(piece_text)
            if status:
                latest = StatusReading(
                    text=status,
                    observed_at=record_time,
                    latest_possible_at=mtime,
                    time_source="record-timestamp" if record_time else "file-mtime",
                )
        return latest

    def _resolve_transcript(self, session_id: str) -> Optional[Path]:
        if self.transcript_path is not None:
            return self.transcript_path

        # Try Claude Code first
        if self.agent_type in ("claude-code", "claude", "auto"):
            found = self._find_claude_session(session_id)
            if found:
                return found

        # Then Codex
        if self.agent_type in ("codex", "openai-codex", "auto"):
            found = self._find_codex_session(session_id)
            if found:
                return found

        return None

    def _find_claude_session(self, session_id: str) -> Optional[Path]:
        """Search ~/.claude/projects/**/<session_id>.jsonl"""
        projects = self.claude_root / "projects"
        if not projects.is_dir():
            # Also try the alternate location some installs use
            alt = Path.home() / ".config" / "claude" / "projects"
            if alt.is_dir():
                projects = alt
            else:
                return None

        # Exact match first
        for path in projects.rglob(f"{session_id}.jsonl"):
            return path

        # Fuzzy: session_id may be a short prefix
        for path in projects.rglob("*.jsonl"):
            if session_id in path.stem:
                return path

        return None

    def _find_codex_session(self, session_id: str) -> Optional[Path]:
        """Search ~/.codex/sessions/** for matching rollout-*.jsonl"""
        sessions = self.codex_root / "sessions"
        if not sessions.is_dir():
            return None

        candidates = list(sessions.rglob(f"*{session_id}*.jsonl"))
        if not candidates:
            candidates = list(sessions.rglob("rollout-*.jsonl"))

        if not candidates:
            return None

        # Prefer most recently modified
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]

    def _read_tail(self, path: Path) -> str:
        """Read the last N lines efficiently without loading huge files."""
        # For modest files just read everything; for large ones tail
        size = path.stat().st_size
        if size < 512_000:  # ~512 KB
            return path.read_text(encoding="utf-8", errors="replace")

        # Simple reverse-line read
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            block = 8192
            data = b""
            while end > 0 and data.count(b"\n") <= self.max_tail_lines:
                start = max(0, end - block)
                f.seek(start)
                data = f.read(end - start) + data
                end = start
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()[-self.max_tail_lines :]
            return "\n".join(lines)

    def _extract_text_from_jsonl(self, raw: str) -> str:
        """
        Pull human-readable text out of Claude/Codex JSONL transcripts
        so that WARDEN_STATUS lines embedded in assistant messages are visible.
        """
        return "\n".join(text for text, _ in self._extract_pieces_from_jsonl(raw))

    def _extract_pieces_from_jsonl(
        self, raw: str
    ) -> list[tuple[str, Optional[datetime]]]:
        """
        Same extraction as _extract_text_from_jsonl, but each piece of text
        keeps the timestamp of the JSONL record it came from (None when the
        record has no usable top-level "timestamp").
        """
        pieces: list[tuple[str, Optional[datetime]]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # Plain text line — keep it
                pieces.append((line, None))
                continue

            # Common shapes
            if isinstance(obj, dict):
                when = parse_record_time(obj.get("timestamp"))

                # Claude-style message content
                message = obj.get("message")
                content = obj.get("content") or (
                    message.get("content") if isinstance(message, dict) else None
                )
                if isinstance(content, str):
                    pieces.append((content, when))
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            pieces.append((part.get("text", ""), when))
                        elif isinstance(part, str):
                            pieces.append((part, when))

                # Codex / generic text fields
                for key in ("text", "output", "message", "content"):
                    val = obj.get(key)
                    if isinstance(val, str) and val:
                        pieces.append((val, when))

                # Nested agent_message style
                item = obj.get("item") or {}
                if isinstance(item, dict):
                    for key in ("text", "content", "message"):
                        val = item.get(key)
                        if isinstance(val, str):
                            pieces.append((val, when))

        return pieces
