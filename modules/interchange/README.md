# Module: interchange

- **Status:** in-progress — **M1 status: implemented (bcio v0)**; DXF read/write for the v0 entity set (LINE/CIRCLE/ARC + LAYER table + ACI colors + preserved handles) is coded and green under plain pytest. DWG/IFC/STEP/xrefs remain `planned`; no compatibility claim beyond the tested DXF path.
- **Owner:** W2
- **Date:** 2026-10-19 (UTC; M1 implementation added same date)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M1 (DXF read/write via ezdxf — glossary §11); M3–M4 (DWG read, then write; IFC/STEP); spec: docs/00-architecture/m1-module-contracts.md §7 (binding)

## Purpose

File compatibility: DXF/DWG/IFC/STEP import and export, external references
(xrefs), round-trip conformance, and the loss ledger that records every
fidelity deviation instead of hiding it (ADR-0003, DXF-first strategy).

## Owns

- DXF read/write (ezdxf candidate) — the first-class interchange path
- DWG read then write (LibreDWG candidate; license gate per adoption matrix)
- IFC and STEP bridges (with `bim` for IFC workflows)
- Xrefs (attach/reload/overlay semantics)
- Round-trip conformance machinery and the loss ledger

## Does NOT own

- Document persistence semantics (`document`)
- Geometry evaluation (`kernel`)
- BIM workflow semantics (`bim`)
- Any UI (`shell`)

## FP areas

- IO — interchange & file compatibility

## Allowed dependencies

- `document`, `kernel`, `drafting`, `drawings`

## M1 public API — IMPLEMENTED (bcio, `modules/interchange/bcio/`)

Pure Python, no `bpy`; depends on `bcdoc` (declared module dependency) and
OPTIONALLY on `ezdxf` — when ezdxf is importable it is the conformance
oracle (R2010 export, strict-read + `ezdxf.recover` fallback + audit);
without it the always-available pure-Python path runs. `stats["engine"]`
honestly reports which engine produced every result (`"ezdxf"` |
`"r12-minimal"`).

| Name | Summary (exact contract: m1-module-contracts.md §7; ADR-0003) |
|---|---|
| `export_dxf(path, doc, ledger=None) -> stats` | write a bcdoc document as ASCII DXF (ezdxf R2010 with `$INSUNITS` + layer table + handles in group code 5; fallback: pure-Python R12); stats: engine, per-kind entity counts, losses |
| `import_dxf(path, doc=None, ledger=None) -> (Document, stats)` | read a DXF file into a fresh (or given) document inside ONE committed transaction (single undo step); preserves DXF handles into the document handle space, re-allocates + ledgers on collision; maps DXF color 0/256 (ByBlock/ByLayer) → `None`, else ACI int; unknown entity types → loss ledger, never silently dropped; stats: engine, imported counts, layers, handle reallocations, losses |
| `LossLedger` | appendable list of `{kind, dxf_type, reason, at}` records (`to_json()`); the ADR-0003 honesty artifact — every unsupported entity/property/degradation is recorded on every path |
| `bcio.dxf_minimal` | in-product pure-Python DXF **R12 ASCII** writer + tolerant reader for the v0 entity set (LINE/CIRCLE/ARC, LAYER table, ACI 62, hex handles via group 5; `$ACADVER AC1009`; R12 predates `$INSUNITS` — recorded limitation) |
| `bcio.ezdxf_bridge` | the ezdxf oracle path: export (R2010, `$INSUNITS`, handles forced onto entities, `$HANDSEED` kept consistent) and import (`ezdxf.readfile`, `ezdxf.recover.readfile` fallback for imperfect files, `doc.audit()` results ledgered) |

Known v0 losses (recorded in the ledger at run time, not hidden): layer
color/linetype are names-only in bcdoc v0 (imported as names, exported as
color 7 / CONTINUOUS); true colors (group 420), TEXT/LWPOLYLINE and every
other non-LINE/CIRCLE/ARC entity, blocks, and paper-space content are out of
v0 scope and ledgered on import.

### How to run the tests

```
cd <repo root>
/home/z/.venv/bin/python3 -m pytest modules/interchange/tests -q         # engine + ledger + no-bpy suite (ezdxf installed = oracle path)
/home/z/.venv/bin/python3 -m pytest modules/testing/roundtrip -q          # cross-module TP-CAT-04 precursor
```

Plain pytest, no Blender. Fixture files are self-authored at runtime into
`tmp_path` (licensing-clean per test-plan §8; see
`modules/interchange/tests/fixtures/README.md`). The
`modules/interchange/__init__.py` / `tests/__init__.py` package markers exist
so the mandated `test_no_bpy.py` file name can also be used by other module
suites without pytest module-name collisions; the shipped package is `bcio`
only.

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `DxfIO` — read/write DXF with entity mapping tables (ezdxf-backed)
- `DwgIO` — DWG read (M3) then write (M4) via LibreDWG
- `IfcBridge` / `StepBridge` — schema mapping in/out
- `XrefManager` — attach/reload/clamp external references
- `RoundTripHarness` — the load→save→reload→compare machinery used by TP-CAT-04
- `LossLedger` — recorded deviations per file, queryable by test and review

## Tests

- docs/30-process/test-plan.md: TP-CAT-04 (round-trip conformance; engine
  suites here, golden corpus in `modules/testing/roundtrip/`). M1 suite
  (implemented, green): `modules/interchange/tests/` — `test_dxf_roundtrip.py`
  (ezdxf-engine round-trip incl. `doc.audit()` cleanliness, forced R12-minimal
  round-trip validated through `ezdxf.recover.readfile` + audit, loss-ledger
  honesty for TEXT/LWPOLYLINE/foreign layers, handle-collision reallocation,
  color mapping, engine reporting) and `test_no_bpy.py` (source scan +
  runtime + clean-subprocess no-bpy).
