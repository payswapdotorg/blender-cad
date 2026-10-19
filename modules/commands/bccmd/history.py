"""Command history — session transcript powering repeat + F2-style recall.

Entries record: command name, raw inputs (as typed), result summary, status
and an ISO-8601 UTC timestamp. ``recent(n)`` returns the newest ``n`` entries
(oldest first) for the command-line dock echo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class HistoryEntry:
    command: str
    inputs: List[str] = field(default_factory=list)
    summary: str = ""
    status: str = "ok"          # "ok" | "cancelled"
    timestamp: str = ""

    def echo_lines(self) -> List[str]:
        lines = [f"Command: {self.command}"]
        for raw in self.inputs:
            lines.append(f"  {raw}")
        lines.append(f"  -> {self.summary} [{self.status}]")
        return lines


class History:
    """Bounded, append-only command history."""

    def __init__(self, limit: int = 1000):
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self.limit = limit
        self._entries: List[HistoryEntry] = []

    # -- writing -------------------------------------------------------------
    def append(
        self,
        command: str,
        raw_inputs: Optional[List[str]] = None,
        summary: str = "",
        status: str = "ok",
        timestamp: Optional[str] = None,
    ) -> HistoryEntry:
        entry = HistoryEntry(
            command=str(command),
            inputs=[str(i) for i in (raw_inputs or [])],
            summary=str(summary),
            status=str(status),
            timestamp=timestamp
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._entries.append(entry)
        if len(self._entries) > self.limit:
            self._entries = self._entries[-self.limit:]
        return entry

    # -- reading --------------------------------------------------------------
    def recent(self, n: int = 20) -> List[HistoryEntry]:
        """The newest ``n`` entries, oldest first."""
        if n < 1:
            return []
        return self._entries[-n:]

    def entries(self) -> List[HistoryEntry]:
        return list(self._entries)

    def last_command(self) -> Optional[str]:
        """Name of the most recent entry (Enter-at-idle repeats it, ux-spec §3.2)."""
        if not self._entries:
            return None
        return self._entries[-1].command

    def as_lines(self, n: int = 40) -> List[str]:
        lines: List[str] = []
        for entry in self.recent(n):
            lines.extend(entry.echo_lines())
        return lines

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries = []
