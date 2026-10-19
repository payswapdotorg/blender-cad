"""Agent sessions: token issuance, mode, granted permission classes, revocation.

Implements the session half of the permission model
(docs/20-agent/permissions-and-execution-model.md §1-§3):

- Every session starts in ``read-only`` mode with ZERO permission classes granted
  (permissions doc §1 "Defaults (binding)" + §7 "Least privilege") — default DENY.
- Modes are user-controlled; the adapter never escalates on its own.
- Grants are revocable at any time with immediate effect (permissions doc §3).

Token format is opaque: ``"st-" + uuid4().hex`` (mission contract for M1). Tokens are
single-use secrets, not derivable from session ids. Revocation is permanent for the
token (a new session needs a new token).

This module is pure Python and imports NO other bc* package (security boundary,
m1-module-contracts §2/§8).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .contract import MODE_RANK, PERMISSION_CLASSES


def _validate_mode(mode: str) -> str:
    if mode not in MODE_RANK:
        raise ValueError(f"unknown agent mode: {mode!r} (known: {sorted(MODE_RANK)})")
    return mode


def _validate_classes(classes) -> frozenset:
    unknown = sorted(set(classes) - set(PERMISSION_CLASSES))
    if unknown:
        raise ValueError(f"unknown permission classes: {unknown}")
    return frozenset(classes)


@dataclass
class Session:
    """One agent session: identity + mode + granted permission classes.

    ``session_id`` is the stable audit identity (``as-…``, used in undo-group labels
    like ``agent:<session_id>:<tool>`` per permissions doc §4); ``token`` is the
    per-session secret carried on every request (contract §1).
    """

    token: str
    session_id: str
    mode: str = "read-only"
    granted: frozenset = field(default_factory=frozenset)
    revoked: bool = False

    # -- host-driven mutations (never agent-driven) --------------------------

    def set_mode(self, mode: str) -> None:
        """User-controlled mode escalation/demotion (permissions doc §1)."""
        self.mode = _validate_mode(mode)

    def grant_classes(self, classes) -> None:
        """Grant permission classes (host action; e.g. approval prompt outcome)."""
        self.granted |= _validate_classes(classes)

    def revoke_class(self, class_name: str) -> None:
        """Revoke one class with immediate effect (permissions doc §3)."""
        _validate_classes([class_name])
        self.granted = self.granted - {class_name}


class SessionManager:
    """Issues, looks up and revokes agent sessions.

    Default DENY: ``issue_session()`` without arguments creates a read-only session
    with no permission classes; such a session can only use read-only tools.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    # -- lifecycle ------------------------------------------------------------

    def issue_session(self, mode: str = "read-only", classes=()) -> Session:
        """Create a session; returns the ``Session`` (token is ``session.token``).

        Defaults are the binding least-privilege state (read-only, no classes).
        Hosts escalate explicitly via :meth:`Session.set_mode` / ``grant_classes``.
        """
        mode = _validate_mode(mode)
        granted = _validate_classes(classes)
        token = "st-" + uuid.uuid4().hex
        session = Session(
            token=token,
            session_id="as-" + uuid.uuid4().hex[:12],
            mode=mode,
            granted=granted,
        )
        self._sessions[token] = session
        return session

    def get(self, token) -> Session | None:
        """Return the live session for ``token``, else ``None``.

        Unknown, malformed and revoked tokens all return ``None`` — the adapter
        turns that into ``CAD_E_PERMISSION_DENIED`` (never a crash).
        """
        if not isinstance(token, str):
            return None
        session = self._sessions.get(token)
        if session is None or session.revoked:
            return None
        return session

    def revoke(self, token) -> bool:
        """Revoke a session permanently; subsequent calls are denied. Returns
        whether a live session was revoked."""
        session = self._sessions.get(token) if isinstance(token, str) else None
        if session is None or session.revoked:
            return False
        session.revoked = True
        return True

    def revoke_class(self, token, class_name: str) -> bool:
        """Revoke one permission class mid-session with immediate effect."""
        session = self.get(token)
        if session is None:
            return False
        session.revoke_class(class_name)
        return True

    def set_mode(self, token, mode: str) -> bool:
        """User-controlled mode change for a live session."""
        session = self.get(token)
        if session is None:
            return False
        session.set_mode(mode)
        return True

    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if not s.revoked)
