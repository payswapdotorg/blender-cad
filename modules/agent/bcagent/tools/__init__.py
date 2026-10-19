"""Tool registry for the M1 ``cad.*`` subset — one module per namespace.

Namespaces implemented at M1 (m1-module-contracts §8; the advertised set is
EXACTLY the tools registered here — capabilities honesty):

- ``cad.doc``      — info, status
- ``cad.select``   — get, set, count, filter
- ``cad.geometry`` — create, get, query, transform
- ``cad.layers``   — list
- ``cad.io``       — export_dxf, import_dxf
- ``cad.system``   — capabilities

Every tool module exposes ``TOOL_SPECS: list[ToolSpec]``; each spec's docstring
records its subset decisions versus contract v1 (docs/20-agent/cad-tool-contract-v1.md).
"""

from __future__ import annotations

from . import (
    doc_tools,
    geometry_tools,
    io_tools,
    layers_tools,
    select_tools,
    system_tools,
)
from .base import ToolSpec

__all__ = ["ToolSpec", "register_all", "TOOL_MODULES", "ALL_TOOL_IDS"]

#: namespace module order — deterministic capability listing order.
TOOL_MODULES = (
    doc_tools,
    select_tools,
    geometry_tools,
    layers_tools,
    io_tools,
    system_tools,
)


def register_all(registry: dict) -> None:
    """Register every M1 tool spec into ``registry`` (tool_id -> ToolSpec).

    Duplicate ids are a programming error (loud, at import/registration time).
    """
    for module in TOOL_MODULES:
        for spec in getattr(module, "TOOL_SPECS", ()):
            if spec.tool_id in registry:
                raise ValueError(f"duplicate tool id: {spec.tool_id}")
            registry[spec.tool_id] = spec


def all_tool_ids() -> list:
    """The exact advertised/dispatchable tool id set (for tests + honesty checks)."""
    ids: list = []
    for module in TOOL_MODULES:
        for spec in getattr(module, "TOOL_SPECS", ()):
            ids.append(spec.tool_id)
    return ids


ALL_TOOL_IDS = all_tool_ids()
