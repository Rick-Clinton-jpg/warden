"""Manual / fallback polling — user pastes the status line."""

from datetime import datetime
from typing import Optional

from .base import PollingStrategy, StatusReading


class ManualInputStrategy(PollingStrategy):
    """Prompt the user to paste the latest WARDEN_STATUS."""

    def poll(self, session_id: str) -> Optional[str]:
        try:
            raw = input(
                f"[warden] Paste latest WARDEN_STATUS for session '{session_id}' "
                "(or empty to skip): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if not raw:
            return None

        # Accept either the full "WARDEN_STATUS: ..." line or just the text
        if raw.startswith("WARDEN_STATUS:"):
            return self.extract_status(raw)
        return raw
    def read(self, session_id: str) -> Optional[StatusReading]:
        text = self.poll(session_id)
        if not text:
            return None
        # The user supplied this line just now; that is the only time we can
        # evidence. It is the time of pasting, not of the agent's emission.
        return StatusReading(
            text=text,
            observed_at=datetime.now().astimezone(),
            time_source="manual-input",
        )
