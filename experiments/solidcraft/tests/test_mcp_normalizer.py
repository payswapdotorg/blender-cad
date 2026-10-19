"""Regression tests for the w3-mcp cross-run comparison normalizer.

Close-out context (issue #1 / PR #2, TL2): the known temporary-path
normalization discrepancy is handled HERE, with tests, and classified
explicitly:

* The upstream runtime scratch-dir form at pin ``3b4db52`` is ALWAYS
  ``solidcraft-mcp-<pid>-<seed-hex>`` — ``crates/mcp/src/lib.rs``:
  ``format!("solidcraft-mcp-{}-{:x}", std::process::id(), seed)``; the pid is
  a u32 decimal and never empty, so the digit-less variant cannot occur at
  this pin. Any residual temp-path variance is therefore an ENVIRONMENT-ONLY
  difference: it is redacted before comparison and never affects a recorded
  outcome.
* The normalizer ALSO accepts the digit-less defensive form
  ``solidcraft-mcp--<seed-hex>`` so that a future upstream pin cannot silently
  reintroduce a spurious "observed-differs" diff (upstream churn is a recorded
  risk: 80 commits between our pin and the nearest tag).
* Determinism claims are scoped to the normalized comparison (pass flags +
  normalized verbatim evidence; geometry and error strings compared exactly) —
  these tests keep that scoping honest: the pre-closeout regex would have
  FAILED ``test_compare_runs_digitless_vs_digitful``.

Runs under plain pytest from the repo root (self-contained import; no bpy, no
upstream checkout, no release binary needed).
"""

import json
import sys
from pathlib import Path

_PROBE_DIR = Path(__file__).resolve().parents[1] / "python"
if str(_PROBE_DIR) not in sys.path:
    sys.path.insert(0, str(_PROBE_DIR))

from mcp_client_probe import compare_runs, normalize_verbatim  # noqa: E402


# ---------------------------------------------------------------------------
# normalize_verbatim unit coverage
# ---------------------------------------------------------------------------
def test_runtime_pid_seed_form_redacted():
    """The only runtime-real form at pin 3b4db52 (digit-ful pid-seed)."""
    s = 'save ok: /tmp/solidcraft-mcp-2190-17a4866c/designs/base.solidcraft'
    out = normalize_verbatim(s, run_dir="/irrelevant")
    assert "2190" not in out and "17a4866c" not in out
    assert "solidcraft-mcp-<PID>" in out
    assert out.endswith("/designs/base.solidcraft")


def test_digitless_pid_seed_form_redacted():
    """Defensive form: empty pid component (double dash) must NOT leak.

    Regression: the pre-closeout regex ``solidcraft-mcp-\\d+-[0-9a-f]+``
    required at least one pid digit and left this form untouched, which would
    surface as a spurious cross-run 'observed-differs' diff.
    """
    s = "scratch at /tmp/solidcraft-mcp--3ff2ab01/scene.png"
    out = normalize_verbatim(s, run_dir="/irrelevant")
    assert "3ff2ab01" not in out
    assert "solidcraft-mcp-<PID>" in out


def test_both_forms_collapse_to_same_token():
    a = normalize_verbatim("/tmp/solidcraft-mcp-2190-17a4866c/x", "/none")
    b = normalize_verbatim("/tmp/solidcraft-mcp--17a4866c/x", "/none")
    assert a == b == "/tmp/solidcraft-mcp-<PID>/x"


def test_run_dir_replaced():
    s = "wrote /x/run1/designs/a.solidcraft (1024 bytes)"
    out = normalize_verbatim(s, run_dir="/x/run1")
    assert out == "wrote <RUNDIR>/designs/a.solidcraft (1024 bytes)"


def test_ms_fields_redacted_raw_and_escaped():
    raw = '{"ms": 12.5, "ok": true}'
    esc = '{"verbatim_reply": "{\\"ms\\": 7.25, \\"ok\\": true}"}'
    for s in (raw, esc):
        out = normalize_verbatim(s, run_dir="/none")
        assert "12.5" not in out and "7.25" not in out
        assert "<T>" in out
    # normalization must be stable across differing values only
    assert (normalize_verbatim(raw, "/none")
            == normalize_verbatim('{"ms": 999.0, "ok": true}', "/none"))


def test_truncated_marker_normalized():
    a = normalize_verbatim("…[truncated, 12345 chars total]", "/none")
    b = normalize_verbatim("…[truncated, 678 chars total]", "/none")
    assert a == b == "…[truncated, N chars total]"


def test_upstream_test_fixture_names_not_touched():
    """Precision guard: upstream test-suite scratch names (never seen on the
    MCP wire, but sharing the solidcraft-mcp- prefix) must not be mangled —
    an over-broad regex could silently redact real evidence differences."""
    for name in ("solidcraft-mcp-urdf-41", "solidcraft-mcp-test-41",
                 "solidcraft-mcp-encodings-41", "solidcraft-mcp-scope-41"):
        out = normalize_verbatim(f"/tmp/{name}/f", "/none")
        assert name in out, out


def test_geometry_values_never_redacted():
    """The determinism claim depends on geometry being compared exactly."""
    s = "volume_mm3 = 24000.0, area_mm2 = 3400.0, faces = 6"
    out = normalize_verbatim(s, run_dir="/none")
    assert out == s


# ---------------------------------------------------------------------------
# compare_runs end-to-end on synthetic runs
# ---------------------------------------------------------------------------
def _case(cid, observed, pass_=True):
    return {"id": cid, "pass": pass_, "observed": observed}


def _run(run_dir, temp_form):
    path = f"/tmp/{temp_form}/designs/base.solidcraft"
    return {
        "run_id": "test", "duration_s": 1.0, "blockers": [], "log": {},
        "run_dir": run_dir,
        "cases": [
            _case("C1", {"verbatim_reply": f'saved {path}',
                         "volume_mm3": 24000.0, "ms": 12.5}),
            _case("C2", {"err": "edges [[999, 999, 999]] not found"}, pass_=False),
        ],
    }


def test_compare_runs_digitless_vs_digitful():
    """THE regression: run1 uses the runtime-real digit-ful pid-seed form,
    run2 the digit-less form; comparison must stay identical (pre-closeout
    regex => spurious 'observed-differs' diff)."""
    run1 = _run("/x/run1", "solidcraft-mcp-2190-17a4866c")
    run2 = _run("/x/run2", "solidcraft-mcp--17a4866c")
    result = compare_runs(run1, run2)
    assert result["identical"] is True, result["diffs"]
    assert result["diffs"] == []


def test_compare_runs_flags_real_differences():
    """Guard against over-normalization: a real geometry difference must
    still be reported (determinism claims must not become vacuous)."""
    run1 = _run("/x/run1", "solidcraft-mcp-2190-17a4866c")
    run2 = _run("/x/run2", "solidcraft-mcp-2203-33ffcfab")
    run2["cases"][0]["observed"]["volume_mm3"] = 30000.0
    result = compare_runs(run1, run2)
    assert result["identical"] is False
    assert any(d["id"] == "C1" and d["kind"].startswith("observed-differs")
               for d in result["diffs"]), result["diffs"]


def test_committed_envelope_renormalizes_to_same_verdict():
    """Ties the hardened normalizer to the committed evidence: re-running the
    comparison over the committed w3-mcp.json run1/run2 case sets must yield
    the same verdict the envelope records (identical, no diffs). The run-dir
    values are extracted from the committed evidence itself (the S0A case's
    recorded save path), so the test is independent of where the checkout
    lives."""
    results = Path(__file__).resolve().parents[1] / "results" / "w3-mcp.json"
    if not results.exists():  # pragma: no cover - committed evidence required
        raise AssertionError(f"committed evidence missing: {results}")
    env = json.loads(results.read_text())

    def _run_dir_from_s0a(cases):
        for c in cases:
            if c.get("id") == "S0A":
                inner = json.loads(c["observed"]["verbatim_reply"])
                return inner["path"].rsplit("/designs/", 1)[0]
        raise AssertionError("S0A case missing from committed evidence")

    run1 = {"run_id": "run1", "cases": env["cases"], "blockers": env.get("blockers", []),
            "log": {}, "run_dir": _run_dir_from_s0a(env["cases"])}
    run2 = {"run_id": "run2", "cases": env["reproducibility_run2"]["cases"],
            "blockers": env["reproducibility_run2"].get("blockers", []),
            "log": {}, "run_dir": _run_dir_from_s0a(env["reproducibility_run2"]["cases"])}
    result = compare_runs(run1, run2)
    recorded = env["summary"]["reproducibility"]["identical_to_run1"]
    assert result["identical"] is True, result["diffs"]
    assert recorded is True
    assert result["diffs"] == []
    assert result["case_count_run1"] == result["case_count_run2"] == 58
