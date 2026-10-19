"""Dimension regeneration — keep cached measurements current (contracts
§5.3; inventory FP-ANN-015).

``refresh_document(doc)`` walks every ``dim`` entity, resolves it through
:class:`bcdraw.dims.resolve_dimension` (associative dims follow their live
LINE geometry, free dims their stored definition points) and updates the
stored ``measurement`` CACHE. The definition points (``p1`` / ``p2`` /
``angle`` / ``offset_point``) and ``measured_id`` are AUTHORITATIVE — they
are never touched here; only the derived cache follows the geometry.

Policy decisions (documented divergences, kept honest):

- the cache write is a DIRECT attribute update, NOT a journaled
  ``Document.update_entity`` call: the measurement is derived state (like
  selection/session state), definition points are the content — so
  refreshing never floods the undo stack. The shell sync hook runs this
  after EVERY committed transaction (contracts §7) and DIMREGEN exposes it
  as a command; UNDO/REDO leave the cache as-is until the next refresh
  (which the hook always runs);
- contract §5.3 also says "update stored measurement + text geometry" —
  the Dim entity stores NO text cache (``text_position`` is authoritative
  user data; the formatted text is computed on demand by
  ``resolve_dimension``), so the measurement is the only cached field;
- ``{"refreshed": n}`` counts the dims whose cached value actually CHANGED
  (idempotent: re-running with nothing moved reports 0) — the task letter's
  "returns count" read at its useful edge, documented here.

Called by: DIMREGEN (commands_ann) and bcshell's post-transaction sync hook
(contracts §7: ``bcshell`` calls ``bcdraw.regen.refresh_document(doc)``
before syncing display).
"""

from __future__ import annotations

from .dims import resolve_dimension


def refresh_document(doc) -> dict:
    """Refresh every dim's cached measurement; ``{"refreshed": n}``.

    Never raises for well-formed documents: ``resolve_dimension`` itself
    degrades gracefully (missing measured entity -> stored points; missing
    style -> Standard), so one odd dimension cannot break the display sync.
    """
    refreshed = 0
    for entity in doc.entities():
        if entity.kind != "dim":
            continue
        geometry, _text = resolve_dimension(entity, doc)
        if entity.measurement != geometry.measurement:
            # Derived cache update (see module docstring — un-journaled by
            # design; definition points remain the undoable content).
            entity.measurement = float(geometry.measurement)
            refreshed += 1
    return {"refreshed": refreshed}


__all__ = ["refresh_document"]
