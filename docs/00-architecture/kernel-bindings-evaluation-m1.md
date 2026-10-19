# Kernel bindings evaluation — M1 evidence record (OCP distribution level)

- **Status:** Evaluation record (M1 deliverable) — **not** an adoption decision. The binding decision remains an M3-entry gate per ADR-0002; this document fills in the distribution/packaging evidence rows only.
- **Owner:** W2 (kernel/document/interchange); gate owner TL
- **Date:** 2026-10-19 (UTC); PyPI evidence captured 2026-10-19 from `https://pypi.org/pypi/cadquery-ocp/json`
- **Vocabulary:** docs/GLOSSARY.md (binding); ADR-0002 (kernel + binding strategy)

## 1. Scope and method

ADR-0002 defers the kernel binding choice (OCP / pythonocc-core / in-tree
pybind11) to M3 entry and fixes four evaluation criteria: performance,
packaging, binding stability, OCCT-module coverage. At M1 nothing kernel-side
is implemented; what CAN be honestly verified today is the **distribution
level**: which OCP wheels exist, for which Python versions and platforms, at
what binary size, under which license. This document records exactly that.

Method: a live query of the PyPI JSON API for the `cadquery-ocp` project
(`curl -s https://pypi.org/pypi/cadquery-ocp/json`), parsed for the latest
release metadata: per-file `requires_python`, wheel tag matrix and sizes.
No package was installed, vendored or shipped; the query is read-only.

## 2. Findings (PyPI, 2026-10-19)

### 2.1 Release facts

| Fact | Value | Source |
|---|---|---|
| Project | `cadquery-ocp` ("also known as OCP") | PyPI JSON `info` |
| Latest version | **8.0.1.1.0** (uploaded 2026-10-05) | `releases`/`info.version` |
| OCCT version wrapped | 8.0.1 — inferred from the OCP version scheme `<occt-MAJOR.MINOR.PATCH>.<build>.<pkg>` (project convention; PyPI description does not state it explicitly) | inference, tag `(verify)` at M3 gate |
| License | Apache-2.0 (PyPI classifier `License :: OSI Approved :: Apache Software License`) | glossary §9 confidence: high |
| `requires_python` (all files) | `>=3.11, <3.15` | per-file `requires_python` |
| Description facts | "Python wrapper for OCCT generated using pywrap"; goals: thin bindings, wrap all OCCT modules (if practical), react quickly to new OCCT releases, cater primarily to CadQuery; non-goal: added functionality beyond OCCT; typing stubs ship separately as `cadquery-ocp-stubs` | `info.description` |

### 2.2 Wheel matrix for 8.0.1.1.0 (20 files = 4 CPython ABIs × 5 platforms)

| Platform | cp311 | cp312 | cp313 | cp314 |
|---|---|---|---|---|
| `macosx_11_0_arm64` | 59.8 MB | 60.4 MB | **60.4 MB** | 60.4 MB |
| `macosx_11_0_x86_64` | 64.3 MB | 65.0 MB | **65.0 MB** | 65.0 MB |
| `manylinux_2_28_aarch64` | 58.7 MB | 58.9 MB | **58.9 MB** | 59.1 MB |
| `manylinux_2_28_x86_64` | 63.9 MB | 64.1 MB | **64.1 MB** | 64.1 MB |
| `win_amd64` | 45.5 MB | 45.7 MB | **45.7 MB** | 45.9 MB |

**cp313 availability: YES — 5 wheels.** This is the decisive M1 finding:
Blender 5.2.2 (the pinned M1 build, m1-module-contracts §6.1) bundles
Python 3.13.13, and stock OCP 8.0.1.1.0 wheels already target `cp313` on all
five platforms. **No version gap exists at the distribution level** — the
honest-gap branch (sidecar-only or custom wheel builds) is NOT required by
wheel availability. The development venv in this repo runs Python 3.12
(cp312 wheels exist) so kernel prototyping is possible today without
touching the extension packaging.

Caveats recorded with equal honesty:

- wheel sizes are **45.7–65.0 MB per platform** — bundling all five platforms
  per release is a ~285 MB artifact weight before compression; the ADR-0002
  packaging criterion (size budget accepted, extension-platform policy
  verified) remains **open**, not answered by this evidence;
- Linux wheels require `manylinux_2_28` (glibc ≥ 2.28) — fine for current
  mainstream distributions; older enterprise baselines would need checking at
  the first packaging milestone;
- CPython ABI tags are version-specific: an in-process extension for the
  Blender 5.2.2 build must use the `cp313` wheels specifically (Blender's
  bundled interpreter is 3.13.13 and wheels are ABI-tagged, not
  stable-ABI);

## 3. Mapping to the ADR-0002 evaluation criteria

| ADR-0002 criterion | Status after this M1 record |
|---|---|
| (a) performance on hot paths | **Open** — no kernel code exists at M1; benchmark suite is an M3 deliverable (TP-CAT-02). |
| (b) packaging under extension-platform constraints | **Partially filled** — wheel existence, Python-ABI coverage (incl. cp313) and size evidence recorded here; the Blender extension-platform policy on bundled native libraries is still unverified (first-packaging-milestone item). |
| (c) binding stability across OCCT upgrades | **Open** — upgrade test (one OCCT minor) is an M3-entry item; the PyPI release cadence (7.8.1 → 7.9.3 → 8.0.1 in ~18 months) suggests an active, quick-moving upstream (a positive signal, not evidence of stability). |
| (d) OCCT module coverage | **Partially filled** — the project states the goal "wrap all OCCT modules (if practical)"; a concrete kernel capability matrix is an M3-entry item. |

Fallback implications (ADR-0002 "Consequences"): because cp313 wheels exist,
the sidecar-process binding fallback would be straightforward even if the
extension platform forbids bundled native libraries (a versioned sidecar per
ADR-0004's interface pattern can install ordinary wheels); the in-tree
pybind11 fallback with a deliberately reduced OCCT surface remains the
last resort and is not triggered by today's findings.

## 4. Conclusion

**OCP remains the leading candidate binding (no blocker found at the
distribution level).** All five target platforms have current `cp313` wheels
matching the pinned Blender 5.2.2 Python (3.13.13), the license is Apache-2.0
(glossary §9, high confidence), and the project's stated goal is exactly the
thin, complete OCCT surface the `kernel` module needs. The open items are the
ones that were always M3 work: performance benchmarks, OCCT-upgrade
stability, capability coverage, and — the one risk this evidence makes MORE
concrete, not less — binary weight (45.7–65.0 MB per platform) under the
still-unverified extension-platform policy for bundled native libraries.

This record changes no adoption state: OCCT stays `candidate` and OCP stays
`evaluate` in the component adoption matrix (§4); the M3-entry decision
record must fill in every remaining row of the ADR-0002 criteria table.

## 5. References

- ADR-0002 (OCCT kernel + binding strategy; criteria table quoted in §3)
- ADR-0004 (sidecar runtime interface — the packaging fallback pattern)
- docs/00-architecture/document-model-and-geometry-kernel.md §5.2 (binding
  options), §5.3 (threading), §8 (performance budgets — the M3 benchmark bars)
- docs/00-architecture/component-adoption-matrix.md §4 (OCCT/OCP rows),
  §7 (milestone gate calendar: M3 entry)
- docs/30-process/test-plan.md TP-CAT-02 (kernel/constraint evidence vehicle)
- PyPI JSON API evidence: `https://pypi.org/pypi/cadquery-ocp/json`
  (captured 2026-10-19; release 8.0.1.1.0, 20 files)
