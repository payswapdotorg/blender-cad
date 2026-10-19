"""Persistence tests: annotations + layouts + styles survive the
bcdoc/2 serialize -> load round trip (contracts §2.7, §10 W-C row).

Documents always load with current_space "MODEL" / active_layout None
(session state — pinned divergence), but entity spaces, dim/text/mtext
content, styles, layout records and settings all round-trip; entity ids
are stable so dim associativity (measured_id) keeps working after reload.
"""

from bcdoc.document import Document
from bcdoc.entities import Dim, Line, Mtext, Text, Viewport
from bcdraw.regen import refresh_document


def _populated_doc():
    doc = Document(name="Persist")
    doc.settings.set("LUPREC", 2)
    with doc.transaction("setup"):
        line = doc.add_entity(Line((0, 0, 0), (10, 0, 0)))
        doc.add_entity(Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0,
                           offset_point=(5, 3, 0), measured_id=line.id,
                           measurement=10.0))
        doc.add_entity(Text((1, 1, 0), height=3.0, rotation=15.0,
                            content="TITLE", style="Standard",
                            justification="CENTER"))
        doc.add_entity(Mtext((2, 2, 0), width=40.0, content="a\nb"))
        doc.add_layout("Sheet1", page_width=297.0, page_height=210.0)
        doc.add_entity(Text((5, 5, 0), content="frame", space="Sheet1"))
        doc.add_entity(Viewport((5.0, 2.0, 0.0), 4.0, (0, 0, 0), (40, 20, 0),
                                space="Sheet1"))
        doc.add_text_style("Notes", height=3.5, width_factor=0.8)
        doc.add_dim_style("Big", dimscale=2.0, dimtxt=5.0, dimasz=3.0,
                          dimexo=0.5, dimexe=1.0)
    doc.settings.set("DIMSTYLE", "Big")
    return doc


def test_roundtrip_keeps_annotation_entities_and_fields():
    doc = _populated_doc()
    mirror = Document.load(doc.serialize())

    kinds = mirror.count_by_kind()
    assert kinds["line"] == 1 and kinds["dim"] == 1
    assert kinds["text"] == 2 and kinds["mtext"] == 1
    assert kinds["viewport"] == 1

    dims = [e for e in mirror.entities() if e.kind == "dim"]
    assert dims[0].dim_type == "linear"
    assert dims[0].p1 == (0.0, 0.0, 0.0) and dims[0].p2 == (10.0, 0.0, 0.0)
    assert dims[0].offset_point == (5.0, 3.0, 0.0)
    assert dims[0].measurement == 10.0
    assert dims[0].style == "Standard"

    texts = [e for e in mirror.entities() if e.kind == "text"]
    by_space = {t.space: t for t in texts}
    assert by_space["MODEL"].content == "TITLE"
    assert by_space["MODEL"].justification == "CENTER"
    assert by_space["MODEL"].height == 3.0
    assert by_space["Sheet1"].content == "frame"     # space routing kept

    mtexts = [e for e in mirror.entities() if e.kind == "mtext"]
    assert mtexts[0].content == "a\nb"
    assert mtexts[0].width == 40.0

    viewports = [e for e in mirror.entities() if e.kind == "viewport"]
    assert viewports[0].space == "Sheet1"
    assert viewports[0].view_height == 4.0
    assert viewports[0].p1 == (0.0, 0.0, 0.0) and viewports[0].p2 == (40.0, 20.0, 0.0)


def test_roundtrip_keeps_styles_layouts_and_settings():
    doc = _populated_doc()
    mirror = Document.load(doc.serialize())
    assert "Notes" in mirror.text_styles()
    assert mirror.text_style("Notes").height == 3.5
    assert mirror.text_style("Notes").width_factor == 0.8
    assert "Big" in mirror.dim_styles()
    assert mirror.dim_style("Big").dimscale == 2.0
    assert mirror.settings.get("DIMSTYLE") == "Big"
    assert mirror.settings.get("LUPREC") == 2
    record = mirror.layout("Sheet1")
    assert (record.page_width, record.page_height) == (297.0, 210.0)
    # session state is NOT persisted (pinned divergence, §2.4)
    assert mirror.current_space == "MODEL"
    assert mirror.active_layout is None


def test_byte_stable_roundtrip():
    doc = _populated_doc()
    text = doc.serialize()
    assert Document.load(text).serialize() == text


def test_associativity_survives_reload_and_refresh():
    doc = _populated_doc()
    mirror = Document.load(doc.serialize())

    line = [e for e in mirror.entities() if e.kind == "line"][0]
    dim = [e for e in mirror.entities() if e.kind == "dim"][0]
    assert dim.measured_id == line.id       # ids stable across serialization

    with mirror.transaction("move"):
        mirror.update_entity(line.id, p1=(0, 0, 0), p2=(20, 0, 0))
    result = refresh_document(mirror)
    assert result == {"refreshed": 1}
    assert dim.measurement == 20.0


def test_loaded_settings_drive_formatting_and_geometry():
    from bcdraw.formats import format_length

    doc = _populated_doc()
    mirror = Document.load(doc.serialize())
    assert format_length(12.5, mirror.settings) == "12.50"   # LUPREC 2 kept
    from bcdraw.dims import resolve_dimension
    dim = [e for e in mirror.entities() if e.kind == "dim"][0]
    geometry, text = resolve_dimension(dim, mirror)
    assert geometry.measurement == 10.0
    assert text == "10.00"
