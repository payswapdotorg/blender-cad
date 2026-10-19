"""bcagent — the in-process ``cad.*`` tool adapter (CAD tool contract v1, M1 subset).

Public surface (m1-module-contracts §8)::

    from bcagent import CadToolAdapter, SessionManager

    sessions = SessionManager()
    adapter = CadToolAdapter(document, sessions)
    session = sessions.issue_session()                  # read-only, no classes
    reply = adapter.dispatch({"tool": "cad.doc.status",
                              "session_token": session.token,
                              "args": {}})

Implements the in-process JSON-RPC mapping of docs/20-agent/cad-tool-contract-v1.md
(method name = tool id; envelope per contract §2; structured errors per §3).

Security boundary (binding, glossary §6 / m1-module-contracts §8/§10): bcagent
imports ``bcdoc`` (document) and ``bcio`` (DXF, for the ``cad.io`` tools) ONLY —
never ``bpy``, never ``bcshell``. Agents change drawings exclusively through bcdoc
transactions. Enforced by ``modules/agent/tests/test_security_boundary.py``.

Honesty: ``adapter.capabilities()`` advertises exactly the implemented M1 subset
(``implemented_subset: true``, ``version: "1.0-m1"``) — never the full v1 registry.
"""

from __future__ import annotations

from .adapter import CadToolAdapter
from .contract import (
    APP_VERSION,
    CAD_E_CODES,
    CAD_E_DOC_VERSION_CONFLICT,
    CAD_E_ENTITY_NOT_FOUND,
    CAD_E_INTERNAL,
    CAD_E_KERNEL_FAILURE,
    CAD_E_PERMISSION_DENIED,
    CAD_E_RETRYABLE,
    CAD_E_TIMEOUT,
    CAD_E_UNSUPPORTED_ENTITY,
    CAD_E_VALIDATION,
    CAPABILITIES_VERSION,
    CONTRACT_VERSION,
    METHOD_NOT_FOUND,
    MODES,
    PERMISSION_CLASSES,
    CadError,
    DocVersionConflictError,
    EntityNotFoundError,
    InternalCadError,
    MethodNotFoundError,
    PermissionDeniedError,
    UnsupportedEntityError,
    ValidationError,
)
from .permissions import PermissionBroker
from .runtime_interface import (
    AppHandshakeReply,
    EventEnvelope,
    EventSequence,
    RuntimeHandshake,
    spawn_sidecar_spec,
)
from .sessions import Session, SessionManager
from .tools import ALL_TOOL_IDS

__version__ = APP_VERSION

__all__ = [
    # core
    "CadToolAdapter",
    "SessionManager",
    "Session",
    "PermissionBroker",
    # contract vocabulary
    "CONTRACT_VERSION",
    "CAPABILITIES_VERSION",
    "APP_VERSION",
    "MODES",
    "PERMISSION_CLASSES",
    "CAD_E_CODES",
    "CAD_E_RETRYABLE",
    "CAD_E_DOC_VERSION_CONFLICT",
    "CAD_E_PERMISSION_DENIED",
    "CAD_E_VALIDATION",
    "CAD_E_ENTITY_NOT_FOUND",
    "CAD_E_KERNEL_FAILURE",
    "CAD_E_UNSUPPORTED_ENTITY",
    "CAD_E_TIMEOUT",
    "CAD_E_INTERNAL",
    "METHOD_NOT_FOUND",
    # errors
    "CadError",
    "PermissionDeniedError",
    "ValidationError",
    "EntityNotFoundError",
    "DocVersionConflictError",
    "UnsupportedEntityError",
    "InternalCadError",
    "MethodNotFoundError",
    # runtime interface (DESIGN-ONLY at M1 — no process is spawned)
    "RuntimeHandshake",
    "AppHandshakeReply",
    "EventEnvelope",
    "EventSequence",
    "spawn_sidecar_spec",
    # honest tool inventory
    "ALL_TOOL_IDS",
]
