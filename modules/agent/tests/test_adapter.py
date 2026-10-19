"""Contract tests for the bcagent adapter — TP-CAT-07 precursor (M1 subset).

Covers (mission + m1-module-contracts §10 + cad-tool-contract-v1 §9):

- envelope correctness (ok/error shapes, doc_version echo)
- every CAD_E code path exercised (see ``test_error_model_table`` for the two
  M1-unreachable codes: ``CAD_E_KERNEL_FAILURE`` — no kernel until M3, ADR-0002 —
  and ``CAD_E_TIMEOUT`` — no time budgets in the in-process adapter)
- base_doc_version conflict: nothing applied (document serialize unchanged)
- transaction atomicity: a tool failing mid-way leaves the document BIT-IDENTICAL
- permission deny-by-default: full mode × class matrix per tool
- token enforcement: missing / malformed / unknown / revoked tokens
- capabilities honesty: advertised set == dispatchable set, no more
- one undo step per transactional call; undo reverts one group

INTEGRATION NOTE (honest): these tests import ``bcdoc``/``bcio`` (worker 3-b,
parallel M1 wave — m1-module-contracts §3/§7). Until that work lands, this module
is expectedly RED at collection time; the TL re-runs it after integration. No
bcdoc/bcio stubs are created here (forbidden by the mission).
"""

from __future__ import annotations

import math
import uuid

import pytest

from bcagent import (
    CAD_E_CODES,
    CAD_E_RETRYABLE,
    CAD_E_DOC_VERSION_CONFLICT,
    CAD_E_ENTITY_NOT_FOUND,
    CAD_E_INTERNAL,
    CAD_E_PERMISSION_DENIED,
    CAD_E_UNSUPPORTED_ENTITY,
    CAD_E_VALIDATION,
    APP_VERSION,
    CAPABILITIES_VERSION,
    CONTRACT_VERSION,
    METHOD_NOT_FOUND,
    CadToolAdapter,
    SessionManager,
    AppHandshakeReply,
    EventSequence,
    RuntimeHandshake,
    spawn_sidecar_spec,
)

from bcdoc.document import Document  # worker 3-b (m1-module-contracts §3)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def doc():
    return Document()  # doc_version == 0, layer "0", empty (m1 contracts §3.2)


@pytest.fixture()
def sessions():
    return SessionManager()


@pytest.fixture()
def adapter(doc, sessions):
    return CadToolAdapter(doc, sessions)


@pytest.fixture()
def ro(sessions):
    """Least-privilege session: read-only, ZERO classes (permissions doc §1)."""
    return sessions.issue_session()


@pytest.fixture()
def ro_fs(sessions):
    return sessions.issue_session(mode="read-only", classes=("filesystem",))


@pytest.fixture()
def prop(sessions):
    return sessions.issue_session(mode="propose", classes=("doc-edit",))


@pytest.fixture()
def prop_fs(sessions):
    return sessions.issue_session(
        mode="propose", classes=("doc-edit", "filesystem")
    )


@pytest.fixture()
def full(sessions):
    return sessions.issue_session(
        mode="autonomous",
        classes=("doc-edit", "terminal", "filesystem", "network",
                 "dependencies", "skill-install", "publish"),
    )


def call(adapter, session, tool, args=None):
    """dispatch() never raises — one call, one envelope."""
    return adapter.dispatch(
        {"tool": tool, "session_token": session.token, "args": args or {}}
    )


def is_ok(envelope):
    return envelope.get("status") == "ok"


def err_code(envelope):
    assert envelope.get("status") == "error", envelope
    return envelope["error"]["code"]


def create_line(adapter, session, x2=100.0, base=None, layer=None):
    args = {
        "type": "line",
        "params": {"from": [0, 0, 0], "to": [x2, 0, 0]},
        "base_doc_version": base if base is not None
        else adapter.document.doc_version,
    }
    if layer is not None:
        args["layer"] = layer
    return call(adapter, session, "cad.geometry.create", args)


# ---------------------------------------------------------------------------
# Envelope correctness
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_ok_envelope_shape(self, adapter, ro):
        env = call(adapter, ro, "cad.doc.status")
        assert set(env) == {"status", "doc_version", "result"}
        assert env["status"] == "ok"
        assert isinstance(env["doc_version"], int)
        assert isinstance(env["result"], dict)

    def test_error_envelope_shape(self, adapter, ro):
        env = call(adapter, ro, "cad.geometry.get", {"id": "nope"})
        assert set(env) == {"status", "doc_version", "error"}
        assert env["status"] == "error"
        err = env["error"]
        assert set(err) == {"code", "message", "details", "retryable"}
        assert isinstance(err["message"], str) and err["message"]
        assert isinstance(err["details"], dict)
        assert isinstance(err["retryable"], bool)

    def test_request_shape_errors(self, adapter, ro):
        assert err_code(adapter.dispatch("not a dict")) == CAD_E_VALIDATION
        assert err_code(adapter.dispatch({})) == CAD_E_VALIDATION
        env = adapter.dispatch({"tool": "cad.doc.status",
                                 "session_token": ro.token,
                                 "args": "nope"})
        assert err_code(env) == CAD_E_VALIDATION

    def test_doc_version_echo_on_read(self, adapter, ro):
        env = call(adapter, ro, "cad.doc.status")
        assert env["doc_version"] == adapter.document.doc_version == 0


# ---------------------------------------------------------------------------
# Capabilities honesty (advertised == dispatchable, no more)
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_advertised_equals_dispatchable(self, adapter):
        caps = adapter.capabilities()
        advertised = [t["id"] for t in caps["tools"]]
        assert set(advertised) == set(adapter.tool_ids)
        assert len(advertised) == len(adapter.tool_ids)
        assert set(advertised) == {
            "cad.doc.info", "cad.doc.status",
            "cad.select.get", "cad.select.set", "cad.select.count",
            "cad.select.filter",
            "cad.geometry.create", "cad.geometry.get", "cad.geometry.query",
            "cad.geometry.transform",
            "cad.layers.list", "cad.layers.set_props",
            "cad.io.export_dxf", "cad.io.import_dxf",
            "cad.system.capabilities",
        }
        assert caps["contract_version"] == CONTRACT_VERSION
        assert caps["version"] == CAPABILITIES_VERSION == "1.1-m2"
        assert caps["implemented_subset"] is True
        assert caps["product_version"] == APP_VERSION

    def test_transactional_flags_match_specs(self, adapter):
        caps = adapter.capabilities()
        by_id = {t["id"]: t for t in caps["tools"]}
        assert by_id["cad.geometry.create"]["transactional"] is True
        assert by_id["cad.geometry.transform"]["transactional"] is True
        assert by_id["cad.io.import_dxf"]["transactional"] is True
        for read_tool in ("cad.doc.info", "cad.geometry.get",
                          "cad.select.filter", "cad.layers.list",
                          "cad.io.export_dxf"):
            assert by_id[read_tool]["transactional"] is False

    def test_permission_columns_match_specs(self, adapter):
        caps = adapter.capabilities()
        by_id = {t["id"]: t for t in caps["tools"]}
        assert by_id["cad.geometry.create"]["permissions"] == {
            "classes": ["doc-edit"], "min_mode": "propose"}
        assert by_id["cad.io.export_dxf"]["permissions"] == {
            "classes": ["filesystem"], "min_mode": "read-only"}
        assert by_id["cad.io.import_dxf"]["permissions"] == {
            "classes": ["doc-edit", "filesystem"], "min_mode": "propose"}
        assert by_id["cad.select.set"]["permissions"] == {
            "classes": [], "min_mode": "propose"}
        assert by_id["cad.doc.status"]["permissions"] == {
            "classes": [], "min_mode": "read-only"}

    def test_every_advertised_tool_is_dispatchable(self, adapter, full):
        """Honesty drill: with a full-power session, EVERY advertised tool must be
        reachable (anything but method-not-found); zero unadvertised extras."""
        for tool_id in adapter.tool_ids:
            env = call(adapter, full, tool_id)
            assert env["status"] in ("ok", "error")
            if env["status"] == "error":
                assert env["error"]["code"] != METHOD_NOT_FOUND, tool_id

    def test_capabilities_via_dispatch_matches_method(self, adapter, full):
        env = call(adapter, full, "cad.system.capabilities")
        assert is_ok(env)
        assert env["result"] == adapter.capabilities()

    def test_unadvertised_contract_tool_is_method_not_found(self, adapter, full):
        # a REAL contract v1 tool id that is NOT in the M1 subset (contract §6.4):
        env = call(adapter, full, "cad.edit.set_properties")
        assert err_code(env) == METHOD_NOT_FOUND
        assert env["error"]["retryable"] is False
        # and a fully bogus id:
        assert err_code(call(adapter, full, "not.a.tool")) == METHOD_NOT_FOUND


# ---------------------------------------------------------------------------
# cad.doc
# ---------------------------------------------------------------------------


class TestDocTools:
    def test_info(self, adapter, ro):
        env = call(adapter, ro, "cad.doc.info")
        result = env["result"]
        assert result["name"] == adapter.document.name
        assert result["units"] == {"length": "mm", "angle": "deg"}
        assert result["coordinate_systems"][0]["name"] == "WCS"
        assert result["app_version"] == APP_VERSION

    def test_status_counts_and_epoch(self, adapter, prop):
        create_line(adapter, prop)  # v0 -> v1
        create_line(adapter, prop, x2=50)  # v1 -> v2
        env = call(adapter, prop, "cad.doc.status")
        result = env["result"]
        assert result["entity_counts"] == {"line": 2}
        assert result["undo_depth"] == 2  # one undo step per committed call
        assert result["modified"] is True  # v0 proxy: undo journal non-empty
        assert result["selection_epoch"] == adapter.document.selection.epoch

    def test_status_empty_document(self, adapter, ro):
        env = call(adapter, ro, "cad.doc.status")
        assert env["result"]["entity_counts"] == {}
        assert env["result"]["undo_depth"] == 0
        assert env["result"]["modified"] is False


# ---------------------------------------------------------------------------
# cad.select
# ---------------------------------------------------------------------------


class TestSelectTools:
    def _make_two(self, adapter, prop):
        id1 = create_line(adapter, prop)["result"]["ids"][0]
        id2 = create_line(adapter, prop, x2=10)["result"]["ids"][0]
        return id1, id2

    def test_get_empty_selection(self, adapter, ro):
        env = call(adapter, ro, "cad.select.get")
        result = env["result"]
        assert result["entities"] == []
        assert result["selection_epoch"] == 0
        # documented definition: digest of the empty selection == sha256 of ""
        import hashlib
        assert result["digest"] == "sha256:" + hashlib.sha256(b"").hexdigest()

    def test_set_get_count_epoch_and_no_doc_bump(self, adapter, prop, ro):
        id1, id2 = self._make_two(adapter, prop)
        before_version = adapter.document.doc_version
        env = call(adapter, prop, "cad.select.set",
                   {"ids": [id1], "mode": "replace"})
        assert is_ok(env)
        assert env["result"]["entities"] == [id1]
        epoch1 = env["result"]["selection_epoch"]
        assert epoch1 >= 1
        # selection is session state: doc_version NEVER bumps (contract §6.2)
        assert adapter.document.doc_version == before_version
        env = call(adapter, prop, "cad.select.set", {"ids": [id2], "mode": "add"})
        assert sorted(env["result"]["entities"]) == sorted([id1, id2])
        assert env["result"]["selection_epoch"] > epoch1
        assert call(adapter, ro, "cad.select.count")["result"]["count"] == 2
        env = call(adapter, prop, "cad.select.set", {"ids": [id1], "mode": "remove"})
        assert env["result"]["entities"] == [id2]
        assert adapter.document.doc_version == before_version  # still untouched

    def test_set_requires_propose_mode(self, adapter, ro, prop):
        _, id2 = self._make_two(adapter, prop)
        assert err_code(call(adapter, ro, "cad.select.set",
                             {"ids": [id2], "mode": "replace"})) == \
            CAD_E_PERMISSION_DENIED

    def test_set_unknown_id_is_entity_not_found(self, adapter, prop):
        assert err_code(call(adapter, prop, "cad.select.set",
                             {"ids": ["e-deadbeef"], "mode": "replace"})) == \
            CAD_E_ENTITY_NOT_FOUND

    def test_set_mode_validation(self, adapter, prop):
        id1, _ = self._make_two(adapter, prop)
        assert err_code(call(adapter, prop, "cad.select.set",
                             {"ids": [id1], "mode": "toggle"})) == CAD_E_VALIDATION

    def test_filter_query_predicates(self, adapter, prop):
        line_id = create_line(adapter, prop, x2=100)["result"]["ids"][0]
        create_line(adapter, prop, x2=5)
        # circle radius 7 (length = 2*pi*7 ≈ 43.98)
        call(adapter, prop, "cad.geometry.create", {
            "type": "circle", "params": {"center": [0, 0, 0], "radius": 7},
            "base_doc_version": adapter.document.doc_version,
        })
        env = call(adapter, prop, "cad.select.filter",
                   {"query": 'type == "line" && length > 10'})
        result = env["result"]
        assert result["ids"] == [line_id]
        assert result["total"] == 1
        env = call(adapter, prop, "cad.select.filter",
                   {"query": "radius == 7"})
        assert env["result"]["total"] == 1  # the circle only
        env = call(adapter, prop, "cad.select.filter",
                   {"by_type": ["line"]})
        assert env["result"]["total"] == 2
        env = call(adapter, prop, "cad.select.filter",
                   {"by_layer": ["0"], "query": "length < 10"})
        assert env["result"]["total"] == 1  # the 5-unit line

    def test_filter_pagination_walk(self, adapter, prop):
        for _ in range(5):
            create_line(adapter, prop)
        collected = []
        cursor = None
        pages = 0
        while True:
            args = {"limit": 2}
            if cursor:
                args["cursor"] = cursor
            result = call(adapter, prop, "cad.select.filter", args)["result"]
            collected.extend(result["ids"])
            pages += 1
            cursor = result.get("next_cursor")
            if cursor is None:
                break
        assert pages == 3  # 2 + 2 + 1
        assert len(collected) == 5
        assert len(set(collected)) == 5  # no dupes across the cursor walk
        assert collected == sorted(collected)  # canonical order across pages

    def test_filter_query_validation(self, adapter, ro):
        for bad in ('bogus == 1', 'type == "line" || layer == "0"',
                    'layer > "a"', 'type == 5', 'radius == "x"',
                    'type == "line" &&', 'type >= "line"', ''):
            assert err_code(call(adapter, ro, "cad.select.filter",
                                 {"query": bad})) == CAD_E_VALIDATION, bad

    def test_filter_bad_cursor(self, adapter, ro):
        assert err_code(call(adapter, ro, "cad.select.filter",
                             {"cursor": "!!!not-base64!!!"})) == CAD_E_VALIDATION

    def test_filter_limit_caps(self, adapter, ro):
        assert err_code(call(adapter, ro, "cad.select.filter",
                             {"limit": 1001})) == CAD_E_VALIDATION
        assert err_code(call(adapter, ro, "cad.select.filter",
                             {"limit": 0})) == CAD_E_VALIDATION


# ---------------------------------------------------------------------------
# cad.geometry
# ---------------------------------------------------------------------------


class TestGeometryCreate:
    @pytest.mark.parametrize("entity_type,params", [
        ("line", {"from": [0, 0, 0], "to": [10, 0, 0]}),
        ("circle", {"center": [1, 2, 0], "radius": 5}),
        ("arc", {"center": [0, 0, 0], "radius": 3,
                  "start_angle": 10, "end_angle": 90}),
    ])
    def test_create_shapes(self, adapter, prop, entity_type, params):
        before = adapter.document.doc_version
        env = call(adapter, prop, "cad.geometry.create", {
            "type": entity_type, "params": params,
            "base_doc_version": before,
        })
        assert is_ok(env)
        result = env["result"]
        assert len(result["ids"]) == 1
        entity = result["entities"][0]
        assert entity["id"] == result["ids"][0]
        assert entity["type"] == entity_type
        assert isinstance(entity["handle"], int)
        assert entity["layer"] == "0"
        assert adapter.document.doc_version == before + 1  # exactly one bump

    def test_create_one_undo_step_and_undo_reverts(self, adapter, prop):
        env = create_line(adapter, prop)
        line_id = env["result"]["ids"][0]
        v = adapter.document.doc_version
        assert adapter.document.undo_depth() == 1
        assert adapter.document.undo() is True  # ONE undo removes the agent group
        assert adapter.document.doc_version == v + 1  # undo commits (monotonic)
        assert call(adapter, prop, "cad.geometry.get",
                    {"id": line_id})["error"]["code"] == CAD_E_ENTITY_NOT_FOUND

    @pytest.mark.parametrize("args,fragment", [
        ({"params": {"from": [0, 0, 0], "to": [1, 0, 0]}}, "type"),
        ({"type": "line", "params": {"to": [1, 0, 0]}}, "from"),
        ({"type": "polyline", "params": {}}, "type"),
        ({"type": "circle", "params": {"center": [0, 0, 0], "radius": -1}}, "radius"),
        ({"type": "circle", "params": {"center": [0, 0], "radius": 1}}, "center"),
        ({"type": "arc", "params": {"center": [0, 0, 0], "radius": 1,
                                    "start_angle": 0}}, "end_angle"),
    ])
    def test_create_validation(self, adapter, prop, args, fragment):
        args["base_doc_version"] = adapter.document.doc_version
        env = call(adapter, prop, "cad.geometry.create", args)
        assert err_code(env) == CAD_E_VALIDATION
        assert fragment in env["error"]["message"] or \
            fragment in str(env["error"]["details"])

    def test_create_unknown_layer(self, adapter, prop):
        env = call(adapter, prop, "cad.geometry.create", {
            "type": "line", "params": {"from": [0, 0, 0], "to": [1, 0, 0]},
            "layer": "NOPE", "base_doc_version": 0,
        })
        assert err_code(env) == CAD_E_VALIDATION
        assert adapter.document.doc_version == 0  # nothing applied

    def test_create_requires_int_base_doc_version(self, adapter, prop):
        env = call(adapter, prop, "cad.geometry.create", {
            "type": "line", "params": {"from": [0, 0, 0], "to": [1, 0, 0]},
            "base_doc_version": "0",
        })
        assert err_code(env) == CAD_E_VALIDATION
        env = call(adapter, prop, "cad.geometry.create", {
            "type": "line", "params": {"from": [0, 0, 0], "to": [1, 0, 0]},
            "base_doc_version": True,
        })
        assert err_code(env) == CAD_E_VALIDATION  # bool is not an int here


class TestGeometryGetQuery:
    def _line(self, adapter, prop):
        return create_line(adapter, prop, x2=30.0)["result"]["ids"][0]

    def test_get_happy(self, adapter, prop, ro):
        line_id = self._line(adapter, prop)
        entity = call(adapter, ro, "cad.geometry.get",
                      {"id": line_id})["result"]["entity"]
        assert entity["type"] == "line"
        assert entity["from"] == [0.0, 0.0, 0.0]
        assert entity["to"] == [30.0, 0.0, 0.0]

    def test_get_not_found(self, adapter, ro):
        assert err_code(call(adapter, ro, "cad.geometry.get",
                             {"id": "missing"})) == CAD_E_ENTITY_NOT_FOUND
        assert err_code(call(adapter, ro, "cad.geometry.get",
                             {"id": 42})) == CAD_E_VALIDATION

    def test_query_per_kind_availability(self, adapter, prop, ro):
        line_id = self._line(adapter, prop)
        circle_id = call(adapter, prop, "cad.geometry.create", {
            "type": "circle", "params": {"center": [0, 0, 0], "radius": 2},
            "base_doc_version": adapter.document.doc_version,
        })["result"]["ids"][0]
        arc_id = call(adapter, prop, "cad.geometry.create", {
            "type": "arc", "params": {"center": [0, 0, 0], "radius": 2,
                                      "start_angle": 0, "end_angle": 90},
            "base_doc_version": adapter.document.doc_version,
        })["result"]["ids"][0]
        env = call(adapter, ro, "cad.geometry.query", {
            "ids": [line_id, circle_id, arc_id],
            "properties": ["length", "radius", "area", "start_angle", "end_angle"],
        })
        items = {item["id"]: item["properties"] for item in env["result"]["items"]}
        # line: length only (radius/area/angles omitted — never faked)
        assert items[line_id] == {"length": 30.0}
        # circle: length (circumference), radius, area
        assert items[circle_id] == pytest.approx({
            "length": 4 * math.pi, "radius": 2.0, "area": 4 * math.pi})
        # arc: length r*Δθ, radius, start/end angle (no area)
        assert items[arc_id] == pytest.approx({
            "length": math.pi, "radius": 2.0,
            "start_angle": 0.0, "end_angle": 90.0})

    def test_query_validation_before_lookup(self, adapter, ro):
        env = call(adapter, ro, "cad.geometry.query", {
            "ids": ["whatever"], "properties": ["mass_properties"]})
        assert err_code(env) == CAD_E_VALIDATION
        env = call(adapter, ro, "cad.geometry.query", {"ids": [], "properties": []})
        assert err_code(env) == CAD_E_VALIDATION

    def test_query_not_found(self, adapter, ro):
        assert err_code(call(adapter, ro, "cad.geometry.query", {
            "ids": ["gone"], "properties": ["length"]})) == CAD_E_ENTITY_NOT_FOUND


class TestGeometryTransform:
    def _two_lines(self, adapter, prop):
        id1 = create_line(adapter, prop, x2=10)["result"]["ids"][0]
        id2 = create_line(adapter, prop, x2=20)["result"]["ids"][0]
        return id1, id2

    def _transform(self, adapter, prop, ids, op, params):
        return call(adapter, prop, "cad.geometry.transform", {
            "ids": ids, "op": op, "params": params,
            "base_doc_version": adapter.document.doc_version,
        })

    def test_move(self, adapter, prop, ro):
        id1, _ = self._two_lines(adapter, prop)
        env = self._transform(adapter, prop, [id1], "move",
                              {"delta": [5, -2, 1]})
        entity = env["result"]["entities"][0]
        assert entity["from"] == [5.0, -2.0, 1.0]
        assert entity["to"] == [15.0, -2.0, 1.0]

    def test_rotate_90_ccw_about_origin(self, adapter, prop):
        id1, _ = self._two_lines(adapter, prop)
        env = self._transform(adapter, prop, [id1], "rotate", {"angle": 90})
        entity = env["result"]["entities"][0]
        # CCW about +Z: (10,0) -> (0,10); (0,0) -> (0,0)
        assert entity["from"] == pytest.approx([0.0, 0.0, 0.0])
        assert entity["to"] == pytest.approx([0.0, 10.0, 0.0])

    def test_rotate_about_center_and_axis_subset(self, adapter, prop):
        id1, _ = self._two_lines(adapter, prop)
        env = self._transform(adapter, prop, [id1], "rotate",
                              {"angle": 90, "center": [10, 0, 0], "axis": [0, 0, 1]})
        assert is_ok(env)
        # non-+Z axis is refused with a clear subset message
        env = self._transform(adapter, prop, [id1], "rotate",
                              {"angle": 90, "axis": [1, 0, 0]})
        assert err_code(env) == CAD_E_VALIDATION

    def test_scale_uniform_and_line_nonuniform(self, adapter, prop):
        id1, _ = self._two_lines(adapter, prop)
        env = self._transform(adapter, prop, [id1], "scale",
                              {"about": [0, 0, 0], "factors": [2, 2, 2]})
        entity = env["result"]["entities"][0]
        assert entity["to"] == [20.0, 0.0, 0.0]
        env = self._transform(adapter, prop, [id1], "scale",
                              {"factors": [3, 1, 1]})  # lines may stretch
        assert is_ok(env)

    def test_scale_circle_nonuniform_is_unsupported_entity(self, adapter, prop):
        circle_id = call(adapter, prop, "cad.geometry.create", {
            "type": "circle", "params": {"center": [0, 0, 0], "radius": 2},
            "base_doc_version": adapter.document.doc_version,
        })["result"]["ids"][0]
        env = self._transform(adapter, prop, [circle_id], "scale",
                              {"factors": [2, 1, 1]})
        assert err_code(env) == CAD_E_UNSUPPORTED_ENTITY

    def test_unknown_op_is_validation(self, adapter, prop):
        id1, _ = self._two_lines(adapter, prop)
        env = self._transform(adapter, prop, [id1], "mirror", {"plane": {}})
        assert err_code(env) == CAD_E_VALIDATION

    def test_unknown_id_nothing_applied(self, adapter, prop):
        id1, _ = self._two_lines(adapter, prop)
        before = adapter.document.serialize()
        env = self._transform(adapter, prop, [id1, "ghost"], "move",
                              {"delta": [1, 0, 0]})
        assert err_code(env) == CAD_E_ENTITY_NOT_FOUND
        assert adapter.document.serialize() == before  # nothing applied


# ---------------------------------------------------------------------------
# Conflict rule R1 + atomicity (the shared-document core guarantees)
# ---------------------------------------------------------------------------


class TestConflictAndAtomicity:
    def test_base_doc_version_conflict_nothing_applied(self, adapter, prop):
        create_line(adapter, prop)  # v1
        snapshot = adapter.document.serialize()
        env = call(adapter, prop, "cad.geometry.create", {
            "type": "line", "params": {"from": [0, 0, 0], "to": [9, 9, 0]},
            "base_doc_version": 0,  # STALE (current is 1)
        })
        assert err_code(env) == CAD_E_DOC_VERSION_CONFLICT
        err = env["error"]
        assert err["retryable"] is True  # contract §3: retryable after re-read
        assert err["details"] == {"current_doc_version": 1, "base_doc_version": 0}
        assert env["doc_version"] == 1  # unchanged
        assert adapter.document.serialize() == snapshot  # bit-identical
        assert adapter.document.undo_depth() == 1  # no new undo group

    def test_mid_tool_failure_leaves_document_bit_identical(self, adapter, prop,
                                                            monkeypatch):
        """Atomicity drill (contract §4): a transactional tool failing HALF-WAY
        must leave the document bit-identical — no partial application."""
        from bcagent.tools import geometry_tools as geometry_module

        id1 = create_line(adapter, prop, x2=10)["result"]["ids"][0]
        id2 = create_line(adapter, prop, x2=20)["result"]["ids"][0]
        snapshot = adapter.document.serialize()
        version = adapter.document.doc_version
        undo_depth = adapter.document.undo_depth()

        real_move = geometry_module._move_entity
        calls = []

        def exploding_move(doc, entity, delta):
            if len(calls) >= 1:
                raise RuntimeError("boom after the first entity moved")
            calls.append(entity.id)
            return real_move(doc, entity, delta)

        monkeypatch.setattr(geometry_module, "_move_entity", exploding_move)
        env = call(adapter, prop, "cad.geometry.transform", {
            "ids": [id1, id2], "op": "move", "params": {"delta": [5, 0, 0]},
            "base_doc_version": version,
        })
        assert err_code(env) == CAD_E_INTERNAL
        assert env["error"]["retryable"] is False
        # the document is BIT-IDENTICAL (full bcdoc rollback)
        assert adapter.document.serialize() == snapshot
        assert adapter.document.doc_version == version
        assert adapter.document.undo_depth() == undo_depth

    def test_conflict_checked_before_any_work(self, adapter, prop, monkeypatch):
        """R1 ordering: the precondition fires before the transaction opens, so
        even a tool whose implementation would explode applies nothing."""
        from bcagent.tools import geometry_tools as geometry_module

        def must_not_run(*args, **kwargs):  # pragma: no cover
            raise AssertionError("tool must not run on a stale base version")

        monkeypatch.setattr(geometry_module, "_move_entity", must_not_run)
        create_line(adapter, prop)  # v1
        env = call(adapter, prop, "cad.geometry.transform", {
            "ids": ["anything"], "op": "move", "params": {"delta": [1, 0, 0]},
            "base_doc_version": 0,
        })
        assert err_code(env) == CAD_E_DOC_VERSION_CONFLICT


# ---------------------------------------------------------------------------
# Permission matrix — deny by default (mission: mode/class matrix per tool)
# ---------------------------------------------------------------------------


class TestPermissionMatrix:
    """For every tool x representative session: is the permission gate passed?

    "Denied" means CAD_E_PERMISSION_DENIED with the document untouched. "Passed"
    means the dispatch reached the tool (ok, or any non-permission error such as
    CAD_E_VALIDATION for intentionally-empty args)."""

    SESSIONS = ("ro", "ro_fs", "prop", "prop_fs", "full")

    ALLOWED = {
        # read tools: every mode, no classes (ro, ro_fs, prop, prop_fs, full)
        "cad.doc.info": (True, True, True, True, True),
        "cad.doc.status": (True, True, True, True, True),
        "cad.select.get": (True, True, True, True, True),
        "cad.select.count": (True, True, True, True, True),
        "cad.select.filter": (True, True, True, True, True),
        "cad.geometry.get": (True, True, True, True, True),
        "cad.geometry.query": (True, True, True, True, True),
        "cad.layers.list": (True, True, True, True, True),
        "cad.system.capabilities": (True, True, True, True, True),
        # selection mutation: needs propose (no class)
        "cad.select.set": (False, False, True, True, True),
        # doc-edit transactional: propose + doc-edit
        "cad.geometry.create": (False, False, True, True, True),
        "cad.geometry.transform": (False, False, True, True, True),
        # export: filesystem class, read-only mode OK (contract §5)
        "cad.io.export_dxf": (False, True, False, True, True),
        # import: doc-edit + filesystem + propose (contract §6.9)
        "cad.io.import_dxf": (False, False, False, True, True),
    }

    @pytest.mark.parametrize("tool_id", sorted(ALLOWED))
    @pytest.mark.parametrize("session_name", SESSIONS)
    def test_matrix(self, adapter, request, tool_id, session_name):
        session = request.getfixturevalue(session_name)
        env = call(adapter, session, tool_id)
        expected = self.ALLOWED[tool_id][self.SESSIONS.index(session_name)]
        if expected:
            # permission gate passed: ok, or any NON-permission error
            if env["status"] == "error":
                assert env["error"]["code"] != CAD_E_PERMISSION_DENIED, (
                    tool_id, session_name, env)
        else:
            assert err_code(env) == CAD_E_PERMISSION_DENIED, (tool_id, session_name)
            assert env["doc_version"] == adapter.document.doc_version
            assert adapter.document.undo_depth() == 0  # denied = untouched

    def test_read_only_session_with_classes_still_cannot_edit(self, sessions):
        """Classes alone do not bypass mode: doc-edit granted at read-only mode
        still cannot run transactional tools (permissions doc §3: only doc-edit
        is mode-governed — the mode gate is checked first)."""
        session = sessions.issue_session(mode="read-only", classes=("doc-edit",))
        adapter = CadToolAdapter(Document(), sessions)
        env = call(adapter, session, "cad.geometry.create", {
            "type": "line", "params": {"from": [0, 0, 0], "to": [1, 0, 0]},
            "base_doc_version": 0,
        })
        assert err_code(env) == CAD_E_PERMISSION_DENIED

    def test_missing_classes_reported_in_details(self, sessions):
        session = sessions.issue_session(mode="autonomous")  # no classes at all
        adapter = CadToolAdapter(Document(), sessions)
        env = call(adapter, session, "cad.io.export_dxf", {"path": "/tmp/x.dxf"})
        details = env["error"]["details"]
        assert details["missing_classes"] == ["filesystem"]
        assert details["mode"] == "autonomous"

    def test_revocation_is_immediate(self, adapter, sessions):
        """Mid-run class revocation: new calls denied immediately (permissions
        doc §3 'revocable mid-session with immediate effect')."""
        session = sessions.issue_session(mode="propose", classes=("doc-edit",))
        assert is_ok(create_line(adapter, session))
        assert sessions.revoke_class(session.token, "doc-edit") is True
        env = call(adapter, session, "cad.geometry.create", {
            "type": "line", "params": {"from": [0, 0, 0], "to": [1, 0, 0]},
            "base_doc_version": adapter.document.doc_version,
        })
        assert err_code(env) == CAD_E_PERMISSION_DENIED

    def test_mode_downgrade_is_immediate(self, adapter, sessions):
        session = sessions.issue_session(mode="propose", classes=("doc-edit",))
        assert sessions.set_mode(session.token, "read-only") is True
        env = call(adapter, session, "cad.geometry.create", {
            "type": "line", "params": {"from": [0, 0, 0], "to": [1, 0, 0]},
            "base_doc_version": 0,
        })
        assert err_code(env) == CAD_E_PERMISSION_DENIED


# ---------------------------------------------------------------------------
# Token enforcement (never crash)
# ---------------------------------------------------------------------------


class TestTokenEnforcement:
    def test_missing_token(self, adapter):
        env = adapter.dispatch({"tool": "cad.doc.status", "args": {}})
        assert err_code(env) == CAD_E_PERMISSION_DENIED

    def test_malformed_token(self, adapter):
        env = adapter.dispatch({"tool": "cad.doc.status",
                                 "session_token": 12345, "args": {}})
        assert err_code(env) == CAD_E_PERMISSION_DENIED

    def test_unknown_token(self, adapter):
        env = adapter.dispatch({"tool": "cad.doc.status",
                                 "session_token": "st-" + uuid.uuid4().hex,
                                 "args": {}})
        assert err_code(env) == CAD_E_PERMISSION_DENIED

    def test_revoked_token(self, adapter, sessions):
        session = sessions.issue_session()
        assert is_ok(call(adapter, session, "cad.doc.status"))
        assert sessions.revoke(session.token) is True
        assert sessions.revoke(session.token) is False  # idempotent deny
        env = call(adapter, session, "cad.doc.status")
        assert err_code(env) == CAD_E_PERMISSION_DENIED
        assert adapter.document.doc_version == 0

    def test_token_is_opaque_and_session_backed(self, sessions):
        session = sessions.issue_session()
        assert session.token.startswith("st-")
        assert len(session.token) > 10
        assert session.mode == "read-only"
        assert session.granted == frozenset()
        assert sessions.get(session.token) is session
        assert sessions.get(None) is None
        assert sessions.get("") is None

    def test_denial_happens_even_for_valid_args(self, adapter, sessions, tmp_path):
        """Security drill: valid args + missing class => denied BEFORE execution
        (the file is never opened; the document is untouched)."""
        session = sessions.issue_session(mode="propose", classes=("doc-edit",))
        target = tmp_path / "never-written.dxf"
        env = call(adapter, session, "cad.io.export_dxf", {"path": str(target)})
        assert err_code(env) == CAD_E_PERMISSION_DENIED
        assert not target.exists()  # denied before execution


# ---------------------------------------------------------------------------
# Error model — every CAD_E code path
# ---------------------------------------------------------------------------


class TestErrorModel:
    def test_error_model_table(self):
        """The contract §3 table, verbatim, including the two M1-unreachable
        codes (KERNEL_FAILURE: no kernel until M3/ADR-0002; TIMEOUT: no
        time-budgeted in-process calls at M1 — both by design, documented in
        bcagent.contract)."""
        assert CAD_E_CODES == {
            "CAD_E_DOC_VERSION_CONFLICT", "CAD_E_PERMISSION_DENIED",
            "CAD_E_VALIDATION", "CAD_E_ENTITY_NOT_FOUND",
            "CAD_E_KERNEL_FAILURE", "CAD_E_UNSUPPORTED_ENTITY",
            "CAD_E_TIMEOUT", "CAD_E_INTERNAL",
        }
        assert CAD_E_RETRYABLE == {
            "CAD_E_DOC_VERSION_CONFLICT": True,
            "CAD_E_PERMISSION_DENIED": False,
            "CAD_E_VALIDATION": False,
            "CAD_E_ENTITY_NOT_FOUND": False,
            "CAD_E_KERNEL_FAILURE": True,
            "CAD_E_UNSUPPORTED_ENTITY": False,
            "CAD_E_TIMEOUT": True,
            "CAD_E_INTERNAL": False,
        }

    def test_every_reachable_code_path_exercised(self, adapter, prop):
        """Six CAD_E codes are reachable at M1 through real dispatches; the
        remaining two (KERNEL_FAILURE, TIMEOUT) are exercised at the mapping
        level in test_error_model_table (unreachable by design at M1)."""
        seen = set()
        # VALIDATION
        seen.add(err_code(call(adapter, prop, "cad.geometry.create",
                               {"type": "line"})))
        # PERMISSION_DENIED (mode + class gates)
        seen.add(err_code(call(adapter, adapter.session_manager.issue_session(),
                               "cad.geometry.create", {})))
        # ENTITY_NOT_FOUND
        create_line(adapter, prop)
        seen.add(err_code(call(adapter, prop, "cad.geometry.get",
                               {"id": "ghost"})))
        # DOC_VERSION_CONFLICT
        seen.add(err_code(call(adapter, prop, "cad.geometry.create", {
            "type": "line", "params": {"from": [0, 0, 0], "to": [1, 0, 0]},
            "base_doc_version": 999})))
        # UNSUPPORTED_ENTITY
        circle_id = call(adapter, prop, "cad.geometry.create", {
            "type": "circle", "params": {"center": [0, 0, 0], "radius": 1},
            "base_doc_version": adapter.document.doc_version,
        })["result"]["ids"][0]
        seen.add(err_code(call(adapter, prop, "cad.geometry.transform", {
            "ids": [circle_id], "op": "scale", "params": {"factors": [2, 1, 1]},
            "base_doc_version": adapter.document.doc_version})))
        # INTERNAL (induced mid-tool failure -> rollback)
        from bcagent.tools import geometry_tools as geometry_module
        real = geometry_module._scale_entity

        def boom(doc, entity, about, factors):
            raise RuntimeError("induced")
        geometry_module._scale_entity = boom
        try:
            seen.add(err_code(call(adapter, prop, "cad.geometry.transform", {
                "ids": [circle_id], "op": "scale", "params": {"factors": [2, 2, 2]},
                "base_doc_version": adapter.document.doc_version})))
        finally:
            geometry_module._scale_entity = real
        assert seen == {CAD_E_VALIDATION, CAD_E_PERMISSION_DENIED,
                        CAD_E_ENTITY_NOT_FOUND, CAD_E_DOC_VERSION_CONFLICT,
                        CAD_E_UNSUPPORTED_ENTITY, CAD_E_INTERNAL}


# ---------------------------------------------------------------------------
# cad.io round-trip (bcio integration; tmp_path only — testability rule §10.3)
# ---------------------------------------------------------------------------


class TestIoTools:
    def test_export_import_roundtrip(self, adapter, prop_fs, ro_fs, tmp_path):
        create_line(adapter, prop_fs)
        out = str(tmp_path / "roundtrip.dxf")
        env = call(adapter, ro_fs, "cad.io.export_dxf", {"path": out})
        assert is_ok(env)
        result = env["result"]
        assert result["path"] == out
        assert result["bytes"] > 0
        import os
        assert os.path.getsize(out) == result["bytes"]
        version_before = adapter.document.doc_version
        # import into CURRENT document (default) — transactional, one undo step
        env = call(adapter, prop_fs, "cad.io.import_dxf",
                   {"path": out, "base_doc_version": version_before})
        assert is_ok(env), env
        assert env["doc_version"] == version_before + 1
        assert adapter.document.undo_depth() == 2  # create + import groups
        counts = dict(adapter.document.count_by_kind())
        assert counts.get("line", 0) >= 2  # original + imported

    def test_export_version_restriction(self, adapter, ro_fs, tmp_path):
        env = call(adapter, ro_fs, "cad.io.export_dxf", {
            "path": str(tmp_path / "x.dxf"), "version": "R2018"})
        assert err_code(env) == CAD_E_VALIDATION

    def test_export_missing_directory_is_validation(self, adapter, ro_fs):
        env = call(adapter, ro_fs, "cad.io.export_dxf", {
            "path": "/definitely/not/a/directory/out.dxf"})
        assert err_code(env) == CAD_E_VALIDATION
        assert env["error"]["details"]["path"] == "/definitely/not/a/directory/out.dxf"

    def test_import_into_new_rejected(self, adapter, prop_fs, tmp_path):
        env = call(adapter, prop_fs, "cad.io.import_dxf", {
            "path": str(tmp_path / "whatever.dxf"), "into": "new",
            "base_doc_version": adapter.document.doc_version})
        assert err_code(env) == CAD_E_VALIDATION

    def test_import_missing_file_is_validation(self, adapter, prop_fs, tmp_path):
        env = call(adapter, prop_fs, "cad.io.import_dxf", {
            "path": str(tmp_path / "absent.dxf"),
            "base_doc_version": adapter.document.doc_version})
        assert err_code(env) == CAD_E_VALIDATION


# ---------------------------------------------------------------------------
# cad.layers
# ---------------------------------------------------------------------------


class TestLayersTools:
    def test_list_alphabetical_with_counts(self, adapter, prop, ro):
        create_line(adapter, prop)
        create_line(adapter, prop, x2=5)
        env = call(adapter, ro, "cad.layers.list")
        result = env["result"]
        assert result["names"] == ["0"]  # fresh v2 doc: only layer "0"
        layer = result["layers"][0]
        assert layer["name"] == "0"
        assert layer["entity_count"] == 2
        assert layer["state"] == {
            "on": True, "frozen": False, "locked": False, "plot": True,
        }
        # v2 records carry the real per-layer table (m2 contracts §8)
        assert layer["color"] == 7
        assert layer["linetype"] == "Continuous"
        assert layer["lineweight"] is None
        assert layer["current"] is True

    def test_layers_list_reports_table(self, adapter, prop, ro):
        """M2 §8: the full layer table is on the wire (records, not names)."""
        env = call(adapter, prop, "cad.layers.set_props", {
            "names": ["0"], "props": {"color": 3, "lineweight": 0.35,
                                      "on": False, "frozen": True},
            "base_doc_version": adapter.document.doc_version,
        })
        assert "error" not in env, env["error"]
        env = call(adapter, ro, "cad.layers.list")
        layer = env["result"]["layers"][0]
        assert layer["color"] == 3
        assert layer["lineweight"] == 0.35
        assert layer["state"] == {
            "on": False, "frozen": True, "locked": False, "plot": True,
        }

    def test_layers_set_props_gates_and_validates(self, adapter, prop, ro):
        """set_props: propose+ gated, structured validation, one tx."""
        env = call(adapter, ro, "cad.layers.set_props",
                   {"names": ["0"], "props": {"color": 5}})
        assert env["error"]["code"] == CAD_E_PERMISSION_DENIED
        # transactional tool: integer base_doc_version required (contract §2)
        env = call(adapter, prop, "cad.layers.set_props",
                   {"names": ["nope"], "props": {"color": 5},
                    "base_doc_version": adapter.document.doc_version})
        assert env["error"]["code"] == "CAD_E_ENTITY_NOT_FOUND"
        for bad in ({"color": 0}, {"colour": 1}, {"on": "yes"}, {}):
            env = call(adapter, prop, "cad.layers.set_props",
                       {"names": ["0"], "props": bad,
                        "base_doc_version": adapter.document.doc_version})
            assert env["error"]["code"] == "CAD_E_VALIDATION", bad
        assert call(adapter, ro, "cad.layers.list")["result"]["layers"][0]["color"] == 7
        env = call(adapter, prop, "cad.layers.set_props",
                   {"names": ["0"], "props": {"color": 5, "locked": True},
                    "base_doc_version": adapter.document.doc_version})
        assert env["result"]["applied"] == {"color": 5, "locked": True}
        layer = call(adapter, ro, "cad.layers.list")["result"]["layers"][0]
        assert layer["color"] == 5 and layer["state"]["locked"] is True

    def test_list_pagination(self, adapter, ro):
        env = call(adapter, ro, "cad.layers.list", {"limit": 1})
        assert env["result"]["names"] == ["0"]


# ---------------------------------------------------------------------------
# runtime_interface (DESIGN-ONLY at M1)
# ---------------------------------------------------------------------------


class TestRuntimeInterfaceDesign:
    """The M5 handshake shape, pinned now (ADR-0004 interface-first)."""

    def test_handshake_shapes(self):
        hs = RuntimeHandshake().to_dict()
        assert hs["interface"] == "agent-runtime-interface/v1"
        assert hs["runtime"]["upstream_ref"] == \
            "0a1fc56d279fd1001f78387bd81aec1c26767411"
        assert hs["contract_versions"] == ["cad-tool-contract/v1"]
        assert hs["capabilities"]["event_replay"] is True

        reply = AppHandshakeReply(session_token="st-x").to_dict()
        assert reply["session"]["mode"] == "read-only"       # binding default
        assert reply["session"]["permissions"] == []         # least privilege
        assert reply["doc"]["doc_version"] == 0

    def test_event_sequence_monotonic(self):
        seq = EventSequence()
        values = [seq.next_seq() for _ in range(5)]
        assert values == sorted(values) == [1, 2, 3, 4, 5]

    def test_spawn_spec_is_design_only(self):
        spec = spawn_sidecar_spec()
        assert spec["planned"] is True
        assert "server-cli.js" in spec["binary"]
        assert "proxy-stdio" in spec["argv_candidates"][0]
        assert "OPENROUTER_API_KEY" in spec["env_passthrough"]
        # the documented M1 rule: NOTHING spawns here
        import inspect
        source = inspect.getsource(spawn_sidecar_spec)
        assert "subprocess" not in source

    def test_restart_resync_checklist_constants(self):
        from bcagent.runtime_interface import (
            CONTROL_EVENT_TYPES,
            EVENT_TYPES,
            RESTART_RESYNC_CHECKLIST,
        )
        assert set(EVENT_TYPES) == {
            "doc.version_changed", "selection.changed",
            "approval.requested", "activity.appended"}
        assert set(CONTROL_EVENT_TYPES) == {
            "approval.resolved", "permission.changed", "shutdown.requested"}
        states = {row[0] for row in RESTART_RESYNC_CHECKLIST}
        assert {"doc_version", "selection_epoch", "pending_previews",
                "entity_locks", "activity_log"} <= states
