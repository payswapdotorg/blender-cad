"""``agent-runtime-interface/v1`` — handshake/event/spawn DESIGN (no process at M1).

DESIGN-ONLY MODULE (binding): this module defines the dataclasses and constants of
the versioned control-channel interface between the CAD application and the ZCode
runtime sidecar (zcode-adaptation-plan §3) and the planned sidecar spawn parameters.

**NO PROCESS IS SPAWNED AT M1.** Nothing in this module starts, talks to, or
supervises any external process; there is no sidecar at M1 (it is an M5 deliverable,
glossary §11). The M5 sidecar bridge (module ``agent``) will consume
:func:`spawn_sidecar_spec` and the handshake dataclasses below; until then they
exist so the interface shape is pinned, reviewable and testable WITHOUT a live
runtime (ADR-0004 "interface-first": the contract precedes the process).

Facts baked in from the M1 spike (docs/20-agent/zcode-runtime-spike-m1.md):
- the pinned ZCode tree builds `packages/zcode-server-cli` (`bin zcode` →
  `dist/server-cli.js`, tsup, exit 0) and `packages/rpc` (tsc, exit 0);
- `packages/server/src/entry-stdio.ts` speaks a stdio hello/ack handshake
  (`zcode-hello`) with logs redirected to stderr — the port-free entry candidate;
- ``ZCODE_AGENT_SERVER_COMMAND`` in the child env overrides bundled agent wiring
  (host control point); the data root is ``$ZCODE_DATA_BASE_DIR``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Interface identity (zcode-adaptation-plan §3)
# ---------------------------------------------------------------------------

INTERFACE_NAME = "agent-runtime-interface/v1"

#: The tool contract version(s) the app currently serves (contract §1).
CONTRACT_VERSIONS = ("cad-tool-contract/v1",)

#: Document/control event types the app can stream to the sidecar
#: (contract §7 payload schemas; adaptation plan §3 "Event subscription").
EVENT_TYPES = (
    "doc.version_changed",
    "selection.changed",
    "approval.requested",
    "activity.appended",
)

#: Control-channel lifecycle events — runtime-interface events, NOT document events
#: (adaptation plan §3; they never appear on the document event stream).
CONTROL_EVENT_TYPES = (
    "approval.resolved",
    "permission.changed",
    "shutdown.requested",
)

#: Restart state resync checklist (adaptation plan §3.1) — binding constants:
#: (state, on-restart action, rationale).
RESTART_RESYNC_CHECKLIST: tuple = (
    ("doc_version", "resync", "cheap, always current (handshake + cad.doc.status)"),
    ("selection_epoch", "resync", "cheap, always current"),
    ("document_status", "resync", "cheap, always current"),
    ("session_mode", "restore_from_authority", "authority lives in the app, not the sidecar"),
    ("granted_classes", "restore_from_authority", "same"),
    ("pending_previews", "drop", "stale by definition; agent re-plans (rule R4)"),
    ("pending_proposals", "drop", "stale by definition; agent re-plans (rule R4)"),
    ("entity_locks", "release_at_crash", "locks protect previews that no longer exist"),
    ("pending_approvals", "lapse_with_notification", "the user decides again"),
    ("activity_log", "retain_in_app; sidecar re-reads tail", "append-only, app-owned"),
)


# ---------------------------------------------------------------------------
# Handshake dataclasses (plan §3 JSON, shape-pinned)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeHandshake:
    """Sidecar -> app handshake issued at sidecar start (plan §3)."""

    runtime_name: str = "zcode-runtime"
    fork: str = "payswapdotorg/ZCode"
    upstream_ref: str = "0a1fc56d279fd1001f78387bd81aec1c26767411"
    version: str = "3.16.1-adapted"
    contract_versions: tuple = CONTRACT_VERSIONS
    capabilities_terminal: bool = True
    capabilities_browser: bool = True
    capabilities_computer_use: bool = True
    providers: tuple = ("openrouter", "local")
    event_replay: bool = True

    def to_dict(self) -> dict:
        return {
            "interface": INTERFACE_NAME,
            "runtime": {
                "name": self.runtime_name,
                "fork": self.fork,
                "upstream_ref": self.upstream_ref,
                "version": self.version,
            },
            "contract_versions": list(self.contract_versions),
            "capabilities": {
                "terminal": self.capabilities_terminal,
                "browser": self.capabilities_browser,
                "computer_use": self.capabilities_computer_use,
                "providers": list(self.providers),
                "event_replay": self.event_replay,
            },
        }


@dataclass(frozen=True)
class AppHandshakeReply:
    """App -> sidecar reply (session established + state snapshot; plan §3)."""

    session_token: str
    mode: str = "read-only"
    permissions: tuple = ()          # granted classes; default: NONE (least privilege)
    app_version: str = "0.1.0"
    doc_version: int = 0
    selection_epoch: int = 0
    units: dict = field(
        default_factory=lambda: {"length": "mm", "angle": "deg"}
    )

    def to_dict(self) -> dict:
        return {
            "interface": INTERFACE_NAME,
            "app_version": self.app_version,
            "session": {
                "session_token": self.session_token,
                "mode": self.mode,
                "permissions": list(self.permissions),
            },
            "doc": {
                "doc_version": self.doc_version,
                "selection_epoch": self.selection_epoch,
                "units": dict(self.units),
            },
        }


@dataclass(frozen=True)
class EventEnvelope:
    """One control/document event; ``seq`` is MONOTONIC per session (contract §7)
    so the sidecar can detect gaps and replay from ``since_seq``."""

    event: str                       # one of EVENT_TYPES / CONTROL_EVENT_TYPES
    seq: int
    ts: str                          # ISO-8601 UTC
    session: str                     # agent session id, e.g. "as-7f3a"
    payload: dict = field(default_factory=dict)
    since_seq: int | None = None     # on subscribe replies: replay point

    def to_dict(self) -> dict:
        out = {
            "event": self.event,
            "seq": self.seq,
            "ts": self.ts,
            "session": self.session,
            "payload": dict(self.payload),
        }
        if self.since_seq is not None:
            out["since_seq"] = self.since_seq
        return out


@dataclass
class EventSequence:
    """DESIGN-ONLY monotonic sequence counter for the M5 event stream.

    M1 note: the in-process adapter implements no event stream; this counter
    exists so the monotonicity requirement (gap detection, replay) is encoded
    and unit-testable before the live bridge lands at M5.
    """

    _next: int = 1

    def next_seq(self) -> int:
        seq = self._next
        self._next += 1
        return seq


# ---------------------------------------------------------------------------
# Sidecar spawn parameters (planned — NOT executed at M1)
# ---------------------------------------------------------------------------

#: Environment variables passed through to the sidecar process (plan §5: provider
#: keys are read from the environment only, never persisted; spike §5: host
#: control points). Everything else is scrubbed.
SIDECAR_ENV_PASSTHROUGH = (
    "PATH",
    "HOME",
    "ZCODE_DATA_BASE_DIR",
    "ZCODE_AGENT_SERVER_COMMAND",
    "ZCODE_AGENT_SERVER_ARGS_JSON",
    "OPENROUTER_API_KEY",
)


def spawn_sidecar_spec(fork_root: str | None = None) -> dict:
    """Planned process parameters for the M5 sidecar bridge — a DOCUMENTED STUB.

    **This function spawns nothing.** It returns the parameters the M5 bridge
    (module ``agent``) will use when the sidecar becomes a deliverable: the
    binary path is the pinned-fork build of ``packages/zcode-server-cli``
    (spike-verified: tsup build exit 0, headless ``version`` exit 0), the
    preferred mode is the PORT-FREE stdio path (``proxy-stdio``; plan §3 option
    B — dual stdio channels, no sockets), and the env passthrough is the
    least-privilege list above (provider keys from the environment only).
    """
    root = fork_root or "<payswapdotorg/ZCode checkout at upstream-pin-0a1fc56>"
    return {
        "interface": INTERFACE_NAME,
        "planned": True,  # DESIGN-ONLY at M1 — nothing spawns
        "binary": f"{root}/packages/zcode-server-cli/dist/server-cli.js",
        "argv_candidates": [
            # port-free stdio control (preferred; server entry already speaks a
            # hello/ack handshake over stdio — spike §5.3):
            ["proxy-stdio"],
            # port-binding supervisor mode (fallback; binds host/port on `serve`):
            ["serve"],
        ],
        "env_passthrough": list(SIDECAR_ENV_PASSTHROUGH),
        "control_channel": "json-rpc-2.0 over stdio (packages/rpc seam)",
        "handshake": RuntimeHandshake().to_dict().__class__.__name__,
        "supervision": {
            "restart_budget_per_session": 3,
            "then": "manual-restart indicator (no silent relaunching)",
        },
        "notes": [
            "M5 decision (after the source audit): proxy-stdio vs serve.",
            "The M5 bridge validates the handshake with RuntimeHandshake.to_dict()",
            "and replies with AppHandshakeReply.to_dict(); restart follows the",
            "RESTART_RESYNC_CHECKLIST constants above.",
        ],
    }
