"""CadToolAdapter — the in-process ``cad.*`` tool server (M1 subset).

Implements m1-module-contracts §8 + the JSON-RPC mapping conventions of
docs/20-agent/cad-tool-contract-v1.md §1-§4:

- ``dispatch({"tool", "session_token", "args"}) -> envelope`` — one call, one
  envelope (``ok`` with ``result`` / ``error`` with the structured error object).
- ``capabilities() -> dict`` — the honest advertisement consumed by
  ``cad.system.capabilities``.

Dispatch order (deterministic, deny-early — recorded for the contract tests):

1. request must be an object; ``tool`` a non-empty string (else ``CAD_E_VALIDATION``)
2. ``session_token`` must resolve to a live session — unknown, malformed and
   REVOKED tokens are all ``CAD_E_PERMISSION_DENIED`` (never a crash; mission rule)
3. the tool must be registered — else the transport-level ``method-not-found``
   (contract §1: "tools not advertised ... return method-not-found at transport
   level"; this is deliberately NOT a CAD_E tool-execution code)
4. permission check: minimum mode, then required classes (default DENY — a
   read-only session with no grants can only run read tools)
5. ``args`` must be an object; tool-level validation raises ``CAD_E_VALIDATION``
6. transactional tools: ``base_doc_version`` must be an int and equal the current
   ``doc_version`` — else ``CAD_E_DOC_VERSION_CONFLICT`` with
   ``{current_doc_version, base_doc_version}`` and NOTHING APPLIED (checked
   before the transaction opens; contract §4 / conflict rule R1)
7. transactional tools execute inside exactly ONE ``bcdoc`` transaction
   (``agent:<session_id>:<tool>`` label, permissions doc §4) — one committed call =
   one undo step; any exception rolls the whole call back (bcdoc guarantees; the
   adapter maps the failure to the envelope and echoes the UNCHANGED doc_version)
8. unexpected exceptions become ``CAD_E_INTERNAL`` (never leak tracebacks into
   envelopes; the tool rolled back if it was transactional)

Concurrency: v0 is single-threaded by design (in-process use from the CAD app;
the M5 sidecar bridge serializes calls onto this thread). Not thread-safe.

Security boundary (binding, glossary §6 + m1-module-contracts §8/§10): this module
imports ``bcdoc`` (and ``bcio`` for the ``cad.io`` tools) ONLY. It NEVER imports
``bpy`` or ``bcshell`` — agents change drawings only through the document's
transaction system, never via the Blender scene. Enforced by the security tests.
"""

from __future__ import annotations

from .contract import (
    APP_VERSION,
    CAPABILITIES_VERSION,
    CONTRACT_VERSION,
    CadError,
    DocVersionConflictError,
    InternalCadError,
    MethodNotFoundError,
    PermissionDeniedError,
    ValidationError,
    error_envelope,
    ok_envelope,
)
from .permissions import PermissionBroker
from .sessions import SessionManager
from .tools import register_all
from .tools.base import ToolContext


class CadToolAdapter:
    """In-process server for the M1 ``cad.*`` subset over one bcdoc Document."""

    CONTRACT_VERSION = CONTRACT_VERSION

    def __init__(self, document, session_manager=None) -> None:
        self._doc = document
        self._sessions = session_manager if session_manager is not None else SessionManager()
        self._broker = PermissionBroker()
        self._tools: dict = {}
        register_all(self._tools)

    # -- host surface ---------------------------------------------------------

    @property
    def session_manager(self) -> SessionManager:
        """The session authority owned by the host (grant/revoke live here)."""
        return self._sessions

    @property
    def document(self):
        """The bcdoc Document this adapter serves (single document at M1)."""
        return self._doc

    @property
    def tool_ids(self) -> list:
        """Registered tool ids in deterministic namespace order."""
        return list(self._tools)

    def capabilities(self) -> dict:
        """Honest advertisement (contract §6.13; m1-module-contracts §12).

        The ``tools`` list IS the dispatchable set — the security tests assert
        advertised == dispatchable (no more, no less).
        """
        tools = []
        for tool_id, spec in self._tools.items():
            tools.append(
                {
                    "id": tool_id,
                    "transactional": spec.transactional,
                    "permissions": {
                        "classes": list(spec.classes),
                        "min_mode": spec.min_mode,
                    },
                    "version_added": spec.version_added,
                }
            )
        return {
            "contract_version": self.CONTRACT_VERSION,
            "version": CAPABILITIES_VERSION,
            "product_version": APP_VERSION,
            "implemented_subset": True,
            "tools": tools,
            "limits": {"max_batch": 1},
            # No event subscription tool is implemented at M1 -> empty list.
            "events": [],
        }

    # -- dispatch ---------------------------------------------------------------

    def dispatch(self, request) -> dict:
        """One request -> one envelope. Never raises, never crashes the caller
        (the structured error model carries every failure)."""
        try:
            return self._dispatch_inner(request)
        except CadError as exc:
            return error_envelope(self._doc.doc_version, exc)
        except Exception as exc:  # noqa: BLE001 — the boundary of last resort
            tool = request.get("tool") if isinstance(request, dict) else None
            return error_envelope(
                self._doc.doc_version,
                InternalCadError(
                    f"unexpected internal failure: "
                    f"{type(exc).__name__}: {exc}",
                    details={"tool": tool},
                ),
            )

    def _dispatch_inner(self, request) -> dict:
        if not isinstance(request, dict):
            raise ValidationError(
                "request must be a JSON object",
                details={"got_type": type(request).__name__},
            )
        tool_id = request.get("tool")
        if not isinstance(tool_id, str) or not tool_id.strip():
            raise ValidationError(
                "request.tool must be a non-empty string",
                details={"field": "tool"},
            )
        token = request.get("session_token")
        session = self._sessions.get(token)
        if session is None:
            raise PermissionDeniedError(
                "unknown, malformed or revoked session token",
                details={"tool": tool_id},
            )
        spec = self._tools.get(tool_id)
        if spec is None:
            raise MethodNotFoundError(
                f"tool not advertised by cad.system.capabilities: {tool_id}",
                details={
                    "tool": tool_id,
                    "hint": "call cad.system.capabilities for the implemented set",
                },
            )
        args = request.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ValidationError(
                "request.args must be an object",
                details={"field": "args", "got_type": type(args).__name__},
            )
        self._broker.check(session, spec.min_mode, spec.classes)

        base_doc_version = None
        if spec.transactional:
            base_doc_version = args.get("base_doc_version")
            if isinstance(base_doc_version, bool) or not isinstance(base_doc_version, int):
                raise ValidationError(
                    "transactional tools require an integer base_doc_version",
                    details={"tool": tool_id, "field": "base_doc_version"},
                )
            current = self._doc.doc_version
            if base_doc_version != current:
                raise DocVersionConflictError(current, base_doc_version)

        ctx = ToolContext(session=session, doc=self._doc, adapter=self)
        if spec.transactional and spec.adapter_managed_transaction:
            label = f"agent:{session.session_id}:{tool_id}"
            with self._doc.transaction(label):
                result = spec.run(ctx, args)
        else:
            # non-transactional tools, and transactional tools whose single
            # transaction is owned by the implementation (cad.io.import_dxf:
            # bcio opens exactly one transaction; bcdoc v0 does not nest —
            # the base_doc_version precondition above already ran, so R1 holds)
            result = spec.run(ctx, args)
        return ok_envelope(self._doc.doc_version, result)
