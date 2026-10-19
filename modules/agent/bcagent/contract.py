"""cad-tool-contract/v1 constants, envelope builders and the structured error model.

This module implements the *in-process JSON-RPC mapping* conventions of
``docs/20-agent/cad-tool-contract-v1.md`` (contract §1: "An equivalent JSON-RPC 2.0
method mapping (method name = tool id) is normative for in-process and test use"):

Envelope (contract §2)::

    {"status": "ok",   "doc_version": <int>, "result": {...}}
    {"status": "error", "doc_version": <int>,
     "error": {"code": "CAD_E_*", "message": "...", "details": {...}, "retryable": bool}}

Request (all tools)::

    {"tool": "cad.geometry.create", "session_token": "st-...", "args": {...}}

``base_doc_version`` is a per-tool request field of transactional tools (contract §2),
NOT an envelope field.

M1 honesty notes (binding):

- The adapter implements a documented SUBSET of the v1 tool registry; the advertised
  capabilities (``adapter.capabilities()`` / ``cad.system.capabilities``) list exactly
  the implemented tools with ``version: "1.0-m1"`` and ``implemented_subset: true``
  (m1-module-contracts §8/§12).
- ``CAD_E_KERNEL_FAILURE`` and ``CAD_E_TIMEOUT`` exist in the error model (contract §3)
  and are fully mapped, but no M1 code path can raise them: there is no geometry
  kernel dependency at M1 (kernel adoption is M3, ADR-0002) and the in-process adapter
  runs no time-budgeted calls. This is by design, not an omission; M5 reviews both.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Identity / versions (m1-module-contracts §12)
# ---------------------------------------------------------------------------

#: Contract id, verbatim (contract §1). Breaking changes require v2 + adapter window.
CONTRACT_VERSION = "cad-tool-contract/v1"

#: Advertised capabilities version — honest "v1 tool SUBSET implemented" marker.
CAPABILITIES_VERSION = "1.0-m1"

#: CAD application (extension) version at M1.
APP_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Modes and permission classes (glossary §6, permissions-and-execution-model §1-§3)
# ---------------------------------------------------------------------------

#: Agent modes, escalating capability order (order is load-bearing).
MODES = ("read-only", "propose", "approve", "autonomous")

#: mode name -> rank; a session mode satisfies a requirement when rank >= required.
MODE_RANK = {mode: index for index, mode in enumerate(MODES)}

#: The seven permission classes (glossary §6). Only ``doc-edit`` is mode-governed;
#: the others always require explicit approval (permissions doc §3).
PERMISSION_CLASSES = (
    "doc-edit",
    "terminal",
    "filesystem",
    "network",
    "dependencies",
    "skill-install",
    "publish",
)

# ---------------------------------------------------------------------------
# Error model (contract §3) — the 8 CAD_E codes with retryable flags
# ---------------------------------------------------------------------------

CAD_E_DOC_VERSION_CONFLICT = "CAD_E_DOC_VERSION_CONFLICT"
CAD_E_PERMISSION_DENIED = "CAD_E_PERMISSION_DENIED"
CAD_E_VALIDATION = "CAD_E_VALIDATION"
CAD_E_ENTITY_NOT_FOUND = "CAD_E_ENTITY_NOT_FOUND"
CAD_E_KERNEL_FAILURE = "CAD_E_KERNEL_FAILURE"
CAD_E_UNSUPPORTED_ENTITY = "CAD_E_UNSUPPORTED_ENTITY"
CAD_E_TIMEOUT = "CAD_E_TIMEOUT"
CAD_E_INTERNAL = "CAD_E_INTERNAL"

#: retryable flags exactly as the contract §3 table states them.
CAD_E_RETRYABLE = {
    CAD_E_DOC_VERSION_CONFLICT: True,   # re-read, re-plan, re-preview
    CAD_E_PERMISSION_DENIED: False,
    CAD_E_VALIDATION: False,
    CAD_E_ENTITY_NOT_FOUND: False,
    CAD_E_KERNEL_FAILURE: True,          # retry once (unreachable at M1 — no kernel)
    CAD_E_UNSUPPORTED_ENTITY: False,
    CAD_E_TIMEOUT: True,                # retry once (unreachable at M1 — no budgets)
    CAD_E_INTERNAL: False,
}

#: All CAD_E tool-execution error codes (the contract §3 set, nothing more).
CAD_E_CODES = frozenset(CAD_E_RETRYABLE)

#: Transport-level dispatch error for tools that are not advertised by
#: ``cad.system.capabilities`` (contract §1: "Tools not advertised ... return
#: method-not-found at transport level"). Deliberately NOT a ``CAD_E_*`` code — it is
#: a dispatch/transport failure, not a tool-execution error.
METHOD_NOT_FOUND = "method-not-found"


# ---------------------------------------------------------------------------
# Structured errors (internal control flow -> envelope by the adapter)
# ---------------------------------------------------------------------------


class CadError(Exception):
    """Base for all structured adapter errors; carries the envelope error payload."""

    code = CAD_E_INTERNAL
    retryable = False

    def __init__(self, message: str, details: dict | None = None,
                 retryable: bool | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if retryable is not None:
            self.retryable = retryable

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }


class PermissionDeniedError(CadError):
    code = CAD_E_PERMISSION_DENIED


class ValidationError(CadError):
    code = CAD_E_VALIDATION


class EntityNotFoundError(CadError):
    code = CAD_E_ENTITY_NOT_FOUND


class DocVersionConflictError(CadError):
    """base_doc_version precondition failed (contract §4 / conflict rule R1).

    ``details`` always carries ``current_doc_version`` and ``base_doc_version``
    (contract §3); nothing was applied.
    """

    code = CAD_E_DOC_VERSION_CONFLICT
    retryable = True

    def __init__(self, current_doc_version: int, base_doc_version: int) -> None:
        super().__init__(
            "base_doc_version precondition failed; nothing was applied",
            details={
                "current_doc_version": current_doc_version,
                "base_doc_version": base_doc_version,
            },
        )
        self.current_doc_version = current_doc_version
        self.base_doc_version = base_doc_version


class UnsupportedEntityError(CadError):
    code = CAD_E_UNSUPPORTED_ENTITY


class InternalCadError(CadError):
    code = CAD_E_INTERNAL


class MethodNotFoundError(CadError):
    """Transport-level: the requested tool id is not in the advertised registry."""

    code = METHOD_NOT_FOUND


# ---------------------------------------------------------------------------
# Envelope builders (contract §2)
# ---------------------------------------------------------------------------


def ok_envelope(doc_version: int, result: dict) -> dict:
    """Build an ``ok`` envelope. ``doc_version`` is the version AFTER the call."""
    return {"status": "ok", "doc_version": doc_version, "result": result}


def error_envelope(doc_version: int, error: CadError) -> dict:
    """Build an ``error`` envelope; ``doc_version`` is the current (unchanged) version.

    For tools inside transactions the document has rolled back, so the echoed
    ``doc_version`` equals the pre-call version.
    """
    return {
        "status": "error",
        "doc_version": doc_version,
        "error": error.as_dict(),
    }
