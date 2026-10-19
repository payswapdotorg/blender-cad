"""Permission broker: mode minimums + permission-class checks, default DENY.

Policy engine for the per-tool requirement columns of
docs/20-agent/cad-tool-contract-v1.md §6 (format: "classes required · minimum mode"):

- Read tools: no class, minimum mode ``read-only``.
- ``doc-edit`` tools (transactional): minimum mode ``propose`` + class ``doc-edit``
  (permissions doc §3: only ``doc-edit`` is mode-governed).
- ``cad.io`` exports: class ``filesystem``, work in ``read-only`` mode (contract §5).
- ``cad.io`` imports: classes ``doc-edit`` + ``filesystem`` (contract §6.9), minimum
  mode ``propose``.

The broker owns NO state: sessions (mode, granted classes) live in
``bcagent.sessions.SessionManager``; the broker only *checks*, raising
``PermissionDeniedError`` so the adapter can emit the structured envelope. Deny is
the default — every check must pass explicitly.
"""

from __future__ import annotations

from .contract import (
    CAD_E_PERMISSION_DENIED,
    MODE_RANK,
    PermissionDeniedError,
)


class PermissionBroker:
    """Stateless checker: does this session satisfy this tool's requirements?"""

    def check_mode(self, session, min_mode: str) -> None:
        """Raise :class:`PermissionDeniedError` when the session mode is below
        ``min_mode`` (mode ranks are the glossary §6 escalation order)."""
        required_rank = MODE_RANK.get(min_mode)
        if required_rank is None:
            raise ValueError(f"tool spec bug: unknown min_mode {min_mode!r}")
        if MODE_RANK[session.mode] < required_rank:
            raise PermissionDeniedError(
                f"agent mode '{session.mode}' is below the required mode "
                f"'{min_mode}' for this tool",
                details={
                    "mode": session.mode,
                    "required_mode": min_mode,
                    "missing_classes": [],
                },
            )

    def check_classes(self, session, classes) -> None:
        """Raise :class:`PermissionDeniedError` when any required permission class
        is missing from the session's granted set (default: nothing is granted)."""
        missing = sorted(set(classes) - set(session.granted))
        if missing:
            raise PermissionDeniedError(
                "permission denied: required class(es) not granted: "
                + ", ".join(missing),
                details={
                    "mode": session.mode,
                    "required_mode": None,
                    "required_classes": sorted(set(classes)),
                    "missing_classes": missing,
                },
            )

    def check(self, session, min_mode: str, classes) -> None:
        """Combined check (mode first, then classes — deny early, reveal little)."""
        self.check_mode(session, min_mode)
        self.check_classes(session, classes)

    @staticmethod
    def requirement_error_code() -> str:
        """The envelope code used for denials (exposed for tests/documentation)."""
        return CAD_E_PERMISSION_DENIED
