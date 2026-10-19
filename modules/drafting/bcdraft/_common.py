"""Shared prompt/selection helpers for bcdraft command implementations.

These are steps-generator utilities: ``ask_point`` etc. yield Requests and
return converted values, so both command drivers (blocking Runner via
``run_steps``, and the modal viewport operator via StepDriver) execute the
exact same logic (contract §4, m1-module-contracts.md).
"""

from __future__ import annotations

from typing import List

from bccmd import CommandContext, InputValue, Point, Request
from bcdoc.errors import EntityNotFound
from . import geometry


def existing_ids(doc, ids) -> List[str]:
    """Filter ``ids`` to entities that exist, order-preserved, de-duplicated.

    ``Document.get`` raises :class:`EntityNotFound` for unknown ids (no None
    returns), so existence is probed with try/except — a stale id in a
    selection or a scripted test must never crash a command.
    """
    seen = set()
    out = []
    for eid in ids:
        if eid in seen:
            continue
        seen.add(eid)
        try:
            doc.get(eid)
        except EntityNotFound:
            continue
        out.append(eid)
    return out


def ask_point(ctx: CommandContext, request: Request) -> Point:
    """Yield ``request`` until a point arrives; keywords echo a diagnostic."""
    while True:
        value = yield request
        try:
            return require_point(value)
        except ValueError as exc:
            ctx.feedback(str(exc))


def require_point(value: InputValue) -> Point:
    if value.kind == "point" and isinstance(value.value, Point):
        return value.value
    if value.kind == "keyword" and value.value == "Enter":
        raise ValueError("Point required (Enter is not valid here)")
    raise ValueError(f"Point required, got {value.kind} input")


def ask_positive_distance(ctx: CommandContext, request: Request) -> float:
    while True:
        value = yield request
        try:
            number = require_positive_number(value)
        except ValueError as exc:
            ctx.feedback(str(exc))
            continue
        if value.kind == "point":
            # point entry at a distance prompt: distance from last point
            reference = ctx.last_point
            if reference is None:
                ctx.feedback("No reference point for distance")
                continue
            number = geometry.dist_2d(
                (reference.x, reference.y), (value.value.x, value.value.y)
            )
            if number <= 0.0:
                ctx.feedback("Distance must be positive")
                continue
        return number


def require_positive_number(value: InputValue) -> float:
    if value.kind in ("distance", "angle") and isinstance(value.value, (int, float)):
        number = float(value.value)
        if number <= 0.0:
            raise ValueError("Value must be positive")
        return number
    if value.kind == "point":
        return 0.0  # handled by caller (needs ctx.last_point)
    raise ValueError(f"Number required, got {value.kind!r} input")


def select_ids(ctx: CommandContext, command_name: str) -> List[str]:
    """Selection prompt with PICKFIRST-style preselection (ux-spec §3.5).

    Preselected entities (``document.selection``) are passed straight to the
    command; otherwise the command asks once. An empty selection ends the
    command politely ("no objects selected").
    """
    doc = ctx.document
    pre = sorted(doc.selection.ids)
    if pre:
        ids = existing_ids(doc, pre)
        ctx.feedback(f"{command_name}: {len(ids)} object(s) preselected")
        return ids
    request = Request("selection", f"{command_name} Select objects:")
    while True:
        value = yield request
        if value.kind == "selection":
            return existing_ids(doc, value.value or [])
        if value.kind == "keyword" and value.value == "Enter":
            return []
        ctx.feedback(f"{command_name}: select objects or press Enter")


def add_entity(ctx: CommandContext, entity, label: str):
    """Add one entity inside a fresh committed transaction (one undo step)."""
    doc = ctx.document
    with doc.transaction(label):
        return doc.add_entity(entity)
