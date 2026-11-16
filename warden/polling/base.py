"""Abstract base for pluggable polling strategies."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class StatusReading:
    """A status line plus whatever evidence exists for when it was emitted.

    observed_at        -- timezone-aware time the status was emitted, taken
                          from the record that carried it. None if the source
                          has no per-record time.
    latest_possible_at -- a time the status cannot be newer than (e.g. the
                          transcript file's mtime). It can prove a status is
                          old; it cannot prove a status is fresh.
    time_source        -- where the time evidence came from.
    """

    text: str
    observed_at: Optional[datetime] = None
    latest_possible_at: Optional[datetime] = None
    time_source: str = "none"


class PollingStrategy(ABC):
    """Return the latest WARDEN_STATUS line (or None)."""

    @abstractmethod
    def poll(self, session_id: str) -> Optional[str]:
        """
        Return the most recent valid WARDEN_STATUS text, or None if
        no status was found in the polling window.
        """
        pass

    def read(self, session_id: str) -> Optional[StatusReading]:
        """
        Return the most recent status together with its time evidence.
        Default: wrap poll() with no time evidence, so strategies that only
        implement poll() keep working and are reported as UNVERIFIED.
        """
        text = self.poll(session_id)
        if not text:
            return None
        return StatusReading(text=text)

    def extract_status(self, text: str) -> Optional[str]:
        """
        Scan text (multi-line or single) for the most recent valid
        WARDEN_STATUS line. Robust to extra whitespace and multiline noise.
        """
        if not text:
            return None

        latest: Optional[str] = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("WARDEN_STATUS:"):
                # Everything after the first colon
                parts = stripped.split(":", 1)
                if len(parts) == 2:
                    status = parts[1].strip()
                    # Truncate at first embedded newline (shouldn't happen)
                    status = status.split("\n")[0].strip()
                    if status:
                        latest = status
        return latest