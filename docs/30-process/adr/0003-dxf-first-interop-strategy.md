# ADR-0003: DXF-first interchange strategy

- **Status:** Proposed — binding planning baseline for the interchange module.
- **Owner:** TL (Technical Lead)
- **Date:** 2026-10-19
- **Vocabulary:** docs/GLOSSARY.md (binding)

## Context

- Target users live in an AutoCAD ecosystem: DXF (documented format) and DWG (undocumented, evolving, proprietary specification).
- M1 (glossary §11) requires DXF read/write via ezdxf; DWG is mandatory for the target user base but carries dependency risk (write-path maturity, undocumented format).
- Honesty rules bind: no compatibility claims without recorded conformance evidence.

## Decision

1. **DXF is the first-class interchange path.** ezdxf (MIT, high confidence) is the first adopted-track dependency for DXF read/write at M1 (file compatibility work, IO area).
2. **DWG via LibreDWG (GPL-3.0, high confidence) is gated separately**: read at M3, write at M4; each gate requires round-trip conformance evidence (TP-CAT-04) before the corresponding capability is claimed anywhere. LibreDWG write-path maturity is an explicitly recorded risk (component-adoption-matrix.md).
3. **Loss-ledger honesty policy**: the interchange module maintains a loss ledger recording every unsupported entity, property or degradation on every round-trip path (DXF, DWG, IFC, STEP). Compatibility claims cite the ledger plus conformance runs; blanket "full DWG support" claims are prohibited.
4. **STEP is the neutral 3D exchange format for solids** (via OCCT, ADR-0002): DWG 3D solids are stored as ACIS SAT/ASM data, whose fidelity through LibreDWG is a risk (verify at M3); STEP avoids that risk wherever the workflow permits.
5. **ODA File Converter is dev-fixture tooling only** — used offline to generate reference fixtures for TP-CAT-04; it is never shipped, never linked, never a product dependency.

Conformance gates and the claims they unlock (a claim without its gate is an honesty-rule violation):

| Gate | Milestone | Evidence required | Claim unlocked |
|---|---|---|---|
| DXF read/write acceptance | M1 | TP-CAT-04 DXF suite green; loss-ledger entries for gaps | "DXF read/write (supported versions as tested)" |
| DWG read conformance | M3 | TP-CAT-04 DWG read suite green; 3D-solids loss-ledger entries | "DWG read" |
| DWG write conformance | M4 | TP-CAT-04 DWG write suite green; write-path stability review | "DWG write" |
| IFC round-trip | M4 | TP-CAT-04/05 IFC suite green | "IFC round-trip (BIM)" |
| STEP round-trip | M3+ | TP-CAT-04 STEP suite green | "STEP exchange for 3D solids" |

Loss-ledger entry fields (per gap, per format version): entity class / property affected, direction (read or write), severity (blocked / degraded / cosmetic), workaround, conformance-test reference. The ledger is maintained by the interchange module owner (W2) and reviewed at each milestone gate.

## Consequences

- M1 ships DXF-only interchange; milestone reporting states exactly that.
- DWG capabilities phase in behind conformance gates; the loss ledger is the honest user-facing interface for gaps.
- ezdxf entity-coverage gaps surface as loss-ledger entries, never as silent drops.
- A file-compatibility matrix (task 1-b1) is the per-version capability record; the loss ledger is its fine-grained companion.

## Alternatives

1. **ODA SDKs for DWG** — rejected for the product: proprietary licensing is incompatible with a GPL-3.0-or-later open extension and with the honesty posture; the free File Converter remains fixture-only tooling.
2. **Reverse-engineer DWG alone** — rejected: duplicates LibreDWG's work with worse odds and unbounded maintenance.
3. **DXF-only forever** — rejected: DWG is mandatory for the target user base (mission criterion 1, engineering feature parity).
