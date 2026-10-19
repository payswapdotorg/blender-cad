"""Regeneration tests (contracts §5.3; FP-ANN-015 associativity).

The full end-to-end walkthrough drives LINE (bcdraft) + DIMLINEAR
select-object path + scripted MOVE (bcdraft) + refresh through the REAL
combined registry — the exact seam bcshell's post-transaction sync hook
uses (contracts §7).
"""

from bcdoc.entities import Dim, Line
from bcdraw.regen import refresh_document


def _line_doc(document):
    with document.transaction("setup"):
        line = document.add_entity(Line((0, 0, 0), (10, 0, 0)))
    return document, line


def test_free_dim_is_stable_under_refresh(document):
    with document.transaction("setup"):
        document.add_entity(Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0,
                                offset_point=(5, 3, 0), measurement=10.0))
    result = refresh_document(document)
    assert result == {"refreshed": 0}
    assert document.entities()[0].measurement == 10.0


def test_associativity_refresh_updates_cached_measurement(document):
    doc, line = _line_doc(document)
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
              measured_id=line.id, measurement=10.0)
    with doc.transaction("add dim"):
        doc.add_entity(dim)

    # MOVE the measured line via a journaled document transaction
    with doc.transaction("move"):
        doc.update_entity(line.id, p1=(0, 0, 0), p2=(25, 0, 0))

    result = refresh_document(doc)
    assert result == {"refreshed": 1}
    assert dim.measurement == 25.0
    # definition points untouched (offset_point + stored p1/p2 authoritative)
    assert dim.offset_point == (5.0, 3.0, 0.0)
    assert dim.p1 == (0.0, 0.0, 0.0) and dim.p2 == (10.0, 0.0, 0.0)

    # idempotent: nothing moved since the last refresh
    assert refresh_document(doc) == {"refreshed": 0}


def test_refresh_counts_only_changed_dims(document):
    doc, line = _line_doc(document)
    dim_a = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
                measured_id=line.id, measurement=10.0)
    dim_b = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, -3, 0),
                measurement=10.0)  # free dim, already current
    with doc.transaction("dims"):
        doc.add_entity(dim_a)
        doc.add_entity(dim_b)
    with doc.transaction("move"):
        doc.update_entity(line.id, p1=(0, 0, 0), p2=(17, 0, 0))
    assert refresh_document(doc) == {"refreshed": 1}   # only dim_a changed
    assert dim_a.measurement == 17.0 and dim_b.measurement == 10.0


def test_refresh_works_through_text_override_dims(document):
    doc, line = _line_doc(document)
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
              measured_id=line.id, measurement=10.0, text_override="TYP")
    with doc.transaction("add dim"):
        doc.add_entity(dim)
    with doc.transaction("move"):
        doc.update_entity(line.id, p1=(0, 0, 0), p2=(4, 0, 0))
    assert refresh_document(doc) == {"refreshed": 1}
    assert dim.measurement == 4.0  # cache tracks geometry; display text is "TYP"


def test_refresh_after_undo_leaves_cache_until_next_refresh(document):
    """Documented policy: the measurement cache is derived state — UNDO
    restores the line but not the cache; the next refresh re-syncs (the
    shell hook runs after every committed transaction, incl. UNDO)."""
    doc, line = _line_doc(document)
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
              measured_id=line.id, measurement=10.0)
    with doc.transaction("add dim"):
        doc.add_entity(dim)
    with doc.transaction("move"):
        doc.update_entity(line.id, p1=(0, 0, 0), p2=(30, 0, 0))
    refresh_document(doc)
    assert dim.measurement == 30.0
    doc.undo()   # line restored to 10; cache stays 30 until refreshed
    refresh_document(doc)
    assert dim.measurement == 10.0


# ---------------------------------------------------------------------------
# end-to-end through the real command registry (the shell sync seam)
# ---------------------------------------------------------------------------

def test_dimregen_command_reports_refresh_count(document, make_context, run):
    doc, line = _line_doc(document)
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
              measured_id=line.id, measurement=10.0)
    with doc.transaction("add dim"):
        doc.add_entity(dim)
    ctx = make_context(doc)
    result = run(ctx, "DIMREGEN", [])
    assert result.status == "ok"
    assert "0 dimension(s) refreshed" in result.summary
    with doc.transaction("move"):
        doc.update_entity(line.id, p1=(0, 0, 0), p2=(12, 0, 0))
    ctx2 = make_context(doc)
    result2 = run(ctx2, "DIMREGEN", [])
    assert result2.status == "ok"
    assert "1 dimension(s) refreshed" in result2.summary
    assert dim.measurement == 12.0


def test_full_associativity_walkthrough_through_registry(document, make_context, run):
    """LINE -> DIMLINEAR (select-object path) -> scripted MOVE -> DIMREGEN
    -> scripted SCALE -> DIMREGEN: the FP-ANN-015 flow through one combined
    registry. A pure translation keeps the measured length (asserted), the
    resolved GEOMETRY still follows the live line; a geometry change
    (SCALE x2) is what flips the cached measurement on refresh."""
    from bccmd import selection_input

    from bcdraw.dims import resolve_dimension

    ctx = make_context()
    line_result = run(ctx, "line", ["0,0", "10,0", ""])
    assert line_result.status == "ok"
    line_id = line_result.created[0]

    dim_result = run(ctx, "dimlinear",
                     ["", selection_input([line_id]), "5,3"])
    assert dim_result.status == "ok"
    dim = document.get(dim_result.created[0])
    assert dim.measured_id == line_id
    assert dim.measurement == 10.0
    assert "10.0000" in dim_result.summary

    # 1) translate the line: the measured LENGTH is unchanged (a linear dim
    #    measures p1->p2, not world position) -> refresh reports nothing to do
    move_result = run(ctx, "move",
                      [selection_input([line_id]), "0,0", "@20,0"])
    assert move_result.status == "ok"
    regen_result = run(make_context(document), "dimregen", [])
    assert regen_result.status == "ok"
    assert "0 dimension(s) refreshed" in regen_result.summary
    assert dim.measurement == 10.0
    # ... but the RESOLVED geometry followed the live line (associativity):
    # the dim line now spans x=20..30 at y=3, stored definition points intact
    geometry, text = resolve_dimension(dim, document)
    assert geometry.dim_line_p1 == (20.0, 3.0, 0.0)
    assert geometry.dim_line_p2 == (30.0, 3.0, 0.0)
    assert dim.p1 == (0.0, 0.0, 0.0) and dim.p2 == (10.0, 0.0, 0.0)
    assert text == "10.0000"

    # 2) actually change the measured geometry (SCALE x2) -> stale cache,
    #    refresh updates it (the shell sync hook's whole point)
    scale_result = run(ctx, "scale",
                       [selection_input([line_id]), "0,0", "2"])
    assert scale_result.status == "ok"
    assert dim.measurement == 10.0          # stale until refreshed
    regen_result = run(make_context(document), "dimregen", [])
    assert regen_result.status == "ok"
    assert "1 dimension(s) refreshed" in regen_result.summary
    assert dim.measurement == 20.0
