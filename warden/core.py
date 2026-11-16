"""Core orchestration — polling loop, session registry, comparison."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from dataclasses import dataclass, field, fields, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .audit import AuditLogger
from .freshness import DEFAULT_STALE_AFTER_SECONDS, STALE, assess, format_age
from .matcher import dual_compare
from .polling import get_strategy, PollingStrategy


def format_result_line(result: dict, *, agent_id: Optional[str] = None) -> str:
    """
    Render a single check_once() result as a one-line status string,
    expanding DIVERGENT results into their word/trigram rater breakdown.
    Shared by run_loop (single-session) and run_daemon (multi-session) so
    both surfaces display DIVERGENT results identically.
    """
    tag = result.get("tag", "?")
    status = result.get("status") or "(none)"
    prefix = f"[{result.get('timestamp', '')}] "
    if agent_id is not None:
        prefix += f"{agent_id:12} "

    if tag == "DIVERGENT":
        word_tag = result.get("word_tag", "?")
        trigram_tag = result.get("trigram_tag", "?")
        return (
            f"{prefix}{tag:9} | word={word_tag} trigram={trigram_tag} | "
            f"{status[:80]}"
        )
    if tag == "STALE":
        age = result.get("status_age_seconds")
        if age is None:
            age = result.get("status_min_age_seconds")
            age_text = f"at least {format_age(age)} old" if age is not None else "old"
        else:
            age_text = f"{format_age(age)} old"
        return f"{prefix}{tag:9} | {age_text}, not scored | {status[:80]}"
    return f"{prefix}{tag:9} | {status[:80]}"


@dataclass
class Session:
    agent_id: str
    agent_type: str
    objective: str
    interval_seconds: int = 600  # 10 min default
    strategy_name: str = "claude-code"
    transcript_path: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )
    last_checked: Optional[str] = None
    last_status: Optional[str] = None
    last_tag: Optional[str] = None
    last_word_tag: Optional[str] = None
    last_trigram_tag: Optional[str] = None
    active: bool = True
    # A status older than this is tagged STALE and not scored.
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS
    last_freshness: Optional[str] = None
    last_status_age_seconds: Optional[float] = None


class RegistryError(RuntimeError):
    """The session registry exists but cannot be read."""


class Warden:
    def __init__(self, root: Path | str = ".warden"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.objectives_dir = self.root / "objectives"
        self.objectives_dir.mkdir(exist_ok=True)
        self.registry_path = self.root / "sessions.json"
        self.audit = AuditLogger(self.root)
        self._sessions: dict[str, Session] = {}
        self._unreadable: list = []
        self._load_registry()

    # ------------------------------------------------------------------
    # Registry persistence
    # ------------------------------------------------------------------
    def _load_registry(self) -> None:
        """Replace the in-memory registry with what is on disk.

        Each record is parsed on its own: one bad record never hides the
        others. Records that cannot be read are kept verbatim and written
        back on save, so nothing is lost by a load/save round trip.
        """
        self._sessions = {}
        self._unreadable: list = []
        if not self.registry_path.exists():
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("registry is not a list")
        except (OSError, ValueError) as exc:
            raise RegistryError(
                f"Cannot read session registry {self.registry_path}: {exc}. "
                "Fix or move the file; WARDEN will not overwrite it."
            ) from exc

        known = {f.name for f in fields(Session)}
        for item in data:
            try:
                # Fields this version does not know are ignored, not fatal.
                s = Session(**{k: v for k, v in item.items() if k in known})
                self._sessions[s.agent_id] = s
            except Exception as exc:
                self._unreadable.append(item)
                print(
                    f"[warden] Skipped unreadable registry record ({exc}); "
                    "kept on disk unchanged.",
                    file=sys.stderr,
                )

    def _save_registry(self) -> None:
        data = [asdict(s) for s in self._sessions.values()] + list(self._unreadable)
        tmp = self.registry_path.with_name(self.registry_path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.registry_path)  # atomic: readers never see half a file

    @contextlib.contextmanager
    def _locked(self):
        """Exclusive lock across processes for read-modify-write of the registry."""
        lock_path = self.root / "sessions.lock"
        with open(lock_path, "a+") as handle:
            try:
                import fcntl
            except ImportError:  # Windows: no advisory lock; writes stay atomic
                yield
                return
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _mutate(self, agent_id: str, change) -> Optional[Session]:
        """Apply `change(session_or_None) -> Session | None` to ONE session.

        Re-reads the registry under the lock first, so a session registered
        or stopped by another process in the meantime is never overwritten
        by this process's older copy.
        """
        with self._locked():
            self._load_registry()
            updated = change(self._sessions.get(agent_id))
            if updated is not None:
                self._sessions[agent_id] = updated
                self._save_registry()
            return updated

    def _objective_path(self, agent_id: str) -> Path:
        safe = agent_id.replace("/", "_").replace(" ", "_")
        return self.objectives_dir / f"{safe}.objective"

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    def watch(
        self,
        *,
        agent_id: str,
        objective: str,
        agent_type: str = "claude-code",
        interval_seconds: int = 600,
        transcript_path: Optional[str] = None,
        stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    ) -> Session:
        """Register a session for monitoring."""
        session = Session(
            agent_id=agent_id,
            agent_type=agent_type,
            objective=objective.strip(),
            interval_seconds=interval_seconds,
            strategy_name=agent_type,
            transcript_path=transcript_path,
            active=True,
            stale_after_seconds=stale_after_seconds,
        )
        self._mutate(agent_id, lambda _existing: session)
        self._objective_path(agent_id).write_text(objective.strip() + "\n", encoding="utf-8")
        return session

    def stop(self, agent_id: str) -> bool:
        def deactivate(existing: Optional[Session]) -> Optional[Session]:
            if existing is not None:
                existing.active = False
            return existing

        return self._mutate(agent_id, deactivate) is not None

    def list_sessions(self, active_only: bool = True) -> list[Session]:
        sessions = list(self._sessions.values())
        if active_only:
            sessions = [s for s in sessions if s.active]
        return sessions

    # ------------------------------------------------------------------
    # Single check
    # ------------------------------------------------------------------
    def _get_strategy(self, session: Session) -> PollingStrategy:
        kwargs = {}
        if session.transcript_path:
            kwargs["transcript_path"] = session.transcript_path
        return get_strategy(session.strategy_name, **kwargs)

    def check_once(self, agent_id: str) -> dict:
        """
        Poll one session, compare, log, return result dict.
        """
        session = self._sessions.get(agent_id)
        if session is None:
            return {"error": f"Unknown session: {agent_id}"}

        strategy = self._get_strategy(session)
        reading = strategy.read(session.agent_id)
        status = reading.text if reading else None

        now = datetime.now().astimezone()
        fresh = assess(reading, now, session.stale_after_seconds)
        freshness_extra = {
            "freshness": fresh.state,
            "status_age_seconds": (
                round(fresh.age_seconds, 1) if fresh.age_seconds is not None else None
            ),
            "status_min_age_seconds": (
                round(fresh.min_age_seconds, 1)
                if fresh.min_age_seconds is not None else None
            ),
            "status_time": (
                reading.observed_at.isoformat(timespec="seconds")
                if reading and reading.observed_at else None
            ),
            "freshness_basis": fresh.basis,
            "stale_after_seconds": session.stale_after_seconds,
            "transcript": reading.source if reading else None,
        }

        if status and fresh.state == STALE:
            # A stale status says nothing about what the agent is doing now.
            # Record it; do not score it.
            if fresh.age_seconds is not None:
                age_text = f"{format_age(fresh.age_seconds)} old"
            else:
                age_text = f"at least {format_age(fresh.min_age_seconds or 0)} old"
            final_tag = "STALE"
            word_tag = trigram_tag = None
            note = (
                f"Last WARDEN_STATUS is {age_text} "
                f"(limit {format_age(session.stale_after_seconds)}, "
                f"basis: {fresh.basis}). Not scored."
            )
            extra = dict(freshness_extra)
        else:
            result = dual_compare(status or "", session.objective)
            final_tag = result.final_tag
            word_tag, trigram_tag = result.word_tag, result.trigram_tag
            note = result.note
            if status and fresh.state != "FRESH":
                note += " Status age could not be verified."
            extra = {
                "word_tag": result.word_tag,
                "word_score": round(result.word_score, 3),
                "trigram_tag": result.trigram_tag,
                "trigram_score": round(result.trigram_score, 3),
                **freshness_extra,
            }

        # False when this poll saw the same status and reached the same tag
        # as the previous one, so repeats can be filtered out of the trail.
        extra["changed"] = (status, final_tag) != (session.last_status, session.last_tag)

        self.audit.log(
            agent_id=session.agent_id,
            objective=session.objective,
            status=status or "",
            tag=final_tag,
            note=note,
            extra=extra,
        )

        checked_at = now.isoformat(timespec="seconds")

        def record(existing: Optional[Session]) -> Optional[Session]:
            if existing is None:      # removed by another process meanwhile
                return None
            existing.last_checked = checked_at
            session.last_status, session.last_tag = status, final_tag
            existing.last_status = status
            existing.last_tag = final_tag
            existing.last_word_tag = word_tag
            existing.last_trigram_tag = trigram_tag
            existing.last_freshness = fresh.state
            existing.last_status_age_seconds = freshness_extra["status_age_seconds"]
            return existing

        self._mutate(agent_id, record)

        return {
            "agent_id": session.agent_id,
            "objective": session.objective,
            "status": status,
            "tag": final_tag,
            "word_tag": word_tag,
            "trigram_tag": trigram_tag,
            "note": note,
            "timestamp": checked_at,
            "transcript": reading.source if reading else None,
            "freshness": fresh.state,
            "status_age_seconds": freshness_extra["status_age_seconds"],
            "status_min_age_seconds": freshness_extra["status_min_age_seconds"],
        }

    def check_all(self) -> list[dict]:
        results = []
        for s in self.list_sessions(active_only=True):
            results.append(self.check_once(s.agent_id))
        return results

    # ------------------------------------------------------------------
    # Blocking watch loop
    # ------------------------------------------------------------------
    def run_loop(
        self,
        agent_id: str,
        *,
        once: bool = False,
        interval_override: Optional[int] = None,
    ) -> None:
        """
        Poll a single session on an interval until stopped or Ctrl-C.
        """
        session = self._sessions.get(agent_id)
        if session is None:
            raise ValueError(f"Unknown session: {agent_id}")

        interval = interval_override or session.interval_seconds
        print(
            f"[warden] Watching {agent_id} every {interval}s "
            f"(objective: {session.objective[:60]}…)"
        )
        print("[warden] Ctrl-C to stop.\n")

        try:
            while True:
                result = self.check_once(agent_id)
                print(format_result_line(result))
                if once:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[warden] Stopped.")

    # ------------------------------------------------------------------
    # Multi-session daemon
    # ------------------------------------------------------------------
    def _is_due(self, session: "Session", now: datetime) -> bool:
        if not session.last_checked:
            return True
        try:
            last = datetime.fromisoformat(session.last_checked)
        except ValueError:
            return True
        if last.tzinfo is None:
            # A timestamp without an offset cannot be compared safely;
            # checking early is harmless, crashing the daemon is not.
            return True
        return (now - last).total_seconds() >= session.interval_seconds

    def run_daemon(self, tick_seconds: int = 30) -> None:
        """
        Single long-running process that checks every ACTIVE registered
        session on its own --interval, sleeping `tick_seconds` between
        scan passes. Reloads the registry each tick so sessions registered
        from another terminal are picked up without restarting the daemon.
        """
        print(f"[warden] Daemon started. Tick={tick_seconds}s. Ctrl-C to stop.\n")
        try:
            while True:
                self._load_registry()
                active = self.list_sessions(active_only=True)
                if not active:
                    print("[warden] No active sessions yet — waiting...")
                now = datetime.now().astimezone()
                for session in active:
                    try:
                        if self._is_due(session, now):
                            result = self.check_once(session.agent_id)
                            print(format_result_line(result, agent_id=session.agent_id))
                    except Exception as exc:
                        # One bad session must not stop monitoring of the rest.
                        print(
                            f"[warden] Check failed for {session.agent_id}: "
                            f"{type(exc).__name__}: {exc}",
                            file=sys.stderr,
                        )
                time.sleep(tick_seconds)
        except KeyboardInterrupt:
            print("\n[warden] Daemon stopped.")