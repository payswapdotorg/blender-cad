"""``cad.system`` namespace — M1 subset: honest capability discovery.

Implemented (contract §6.13; m1-module-contracts §8):

- ``cad.system.capabilities`` — the single source of truth for available tools
  (— · read-only)

NOT implemented at M1 (honest subset, NOT advertised; m1-module-contracts §8:
"cad.system.preview/commit batching: NOT advertised at M1 — planned M5"):
``cad.system.preview``, ``cad.system.commit``, ``cad.system.rollback``,
``cad.system.permissions``, ``cad.system.activity``, ``cad.system.events``.

The capabilities payload is the honesty contract of the adapter:

- ``tools`` lists EXACTLY the registered/dispatchable tools — the advertised set is
  the dispatchable set, no more, no less (asserted by tests).
- ``version: "1.0-m1"`` — the M1 subset marker (m1-module-contracts §12); the full
  v1 registry (62 tools, contract §6) arrives by M5.
- ``implemented_subset: true`` — stated explicitly so no consumer mistakes the
  subset for the whole contract.
- ``limits.max_batch: 1`` — no staged batches at M1 (each call is one transaction);
  ``timeout_default_s`` is omitted because the in-process adapter runs no
  time-budgeted calls (omitting beats inventing a number).
- ``events: []`` — the M1 adapter implements no event subscription tool; the
  event vocabulary for the M5 sidecar bridge is designed (design-only) in
  ``bcagent.runtime_interface``.
"""

from __future__ import annotations

from .base import ToolContext, ToolSpec


def _capabilities(ctx: ToolContext, args: dict) -> dict:
    return ctx.adapter.capabilities()


TOOL_SPECS = [
    ToolSpec(tool_id="cad.system.capabilities", run=_capabilities),
]
