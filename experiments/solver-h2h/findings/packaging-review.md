# Packaging review — both remaining PAR-solver candidates (h2h lane)

- **Owner:** TL1 (h2h-5)
- **Date:** 2026-10-20 (UTC)
- **Scope:** m3-eval §8 item 3 + solidcraft-evaluation §4.1 gate (b): the
  packaging reviews of **PlaneGCS vendored C++/LGPL** and **SolidCraft Rust
  cdylib** under the still-unverified extension-platform policy — the same
  gate that constrains ADR-0002's OCCT/OCP binding (license-inventory §3).

## 1. The shared, unresolved gate: the extension-platform policy (verify)

Both candidates bundle a **native artifact** into a Blender extension, and
the extension platform's policy on bundled native libraries, binary size and
metadata licensing fields is **(verify)** at the first packaging milestone
(ADR-0005; license-inventory §3, recorded verbatim: *"platform rules (e.g. on
bundled native libraries, binary size, metadata licensing fields) constrain
both ADR-0002's binding choice and this inventory's shipping obligations …
ADR-0005 and this document are amended through review — never improvised at
packaging time"*). This lane does NOT resolve that policy; it records what
each candidate's packaging path looks like so the gate can be exercised
against facts when the policy is verified.

**Headline symmetry:** the platform policy gate binds BOTH candidates
EQUALLY — it cannot prefer one over the other unless it forbids native
bundling outright (which would also reject the ADR-0002 OCCT binding and
reopen the kernel question, per the license-inventory's own note).

## 2. SolidCraft Rust cdylib (MIT OR Apache-2.0; 12-crate closure)

- **Artifact:** a Rust cdylib built from the sketch-crate closure — **12
  crates, all permissive, zero GPL, no native code** (TL2 W3-b supply-chain
  audit; per-crate `license.workspace = true` verified at `3b4db52`).
- **License obligations (verified):** MIT OR Apache-2.0 — retain LICENSE +
  NOTICE + upstream's THIRD-PARTY-LICENSES.txt; permissive; no library-
  boundary duties. TL2's only pre-ship `(verify)` for the closure is
  `unicode-ident`'s Unicode-3.0 FSF listing (a metadata text item, not a
  license conflict — tracked by the solidcraft record §4.1 gate (c)).
- **Toolchain at packaging time:** a Rust cross-compilation toolchain for the
  platform matrix. The 5-target matrix includes linux-aarch64 — **Rust
  cross-compiles to aarch64 natively** (no wheel gap of the slvs kind; that
  gap was an slvs rejection reason, m3-eval §4.1).
- **Integration shape:** cdylib + a thin FFI at the experiment-B seam
  (bcdoc-first, stateless compute service); port-vs-FFI is a follow-up
  decision the solidcraft record already gates (§4.1 (d)).
- **Risks recorded:** Rust compiler version pinning for reproducible builds;
  cdylib symbol surface discipline; the 4 GiB-class build constraint noted
  by TL2 applies to BUILDS not to the shipped artifact.

## 3. PlaneGCS vendored C++/LGPL (FreeCAD 1.1.4 + Eigen 3.4.0 + boost)

- **Artifact:** the 11 planegcs files (13,142 lines) compiled into the
  extension's native bundle. This lane PROVED they build standalone with
  g++ 14 `-std=c++20 -O2` against eigen 3.4.0 + boost 1.83 + 3 tiny compat
  shims (null-sink Console, FCGlobal/FCConfig stubs — 74 lines total,
  this lane, never product code as-is).
- **License obligations (all verified at the pins this lane, see
  [license-planegcs-eigen.md](license-planegcs-eigen.md)):**
  - planegcs: LGPL-family "or later" (per-file legacy wording recorded
    verbatim; project-level LGPL-2.1) — retain license texts, keep the
    library boundary (user relinking for the vendored object), notice
    retention. Compatible with GPL-3.0-or-later combined distribution.
  - Eigen 3.4.0: **MPL-2.0, verified at the release artifact AND at
    solvespace's `3147391d` pin** (this lane CLEARED the m3-eval §9
    blocker — byte-identical COPYING.MPL2). `-DEIGEN_MPL2_ONLY` is
    upstream's own enforcement mechanism if we want to *guarantee*
    MPL2-only includes (upstream's recommendation, quoted in the findings).
  - boost (graph/math headers): system-packaged 1.83 in this sandbox; at
    packaging time the version + its notices must be pinned and recorded.
- **Toolchain at packaging time:** a C++ toolchain per platform target
  (the OCCT/OCP binding already requires this class of toolchain — the same
  packaging skillset; ADR-0002 synergy).
- **Risks recorded:** the eigen canonical repo is intermittently
  unreachable from this sandbox class (403s — recorded twice in this lane
  after m3-eval's first record); the release-artifact pin used here is
  reproducible and sha256-verified, and that pinning discipline must hold
  through packaging. LGPL §4-style boundary discipline for the vendored
  object is a real (but ordinary) obligation slvs's GPLv3 would not have
  allowed at all.

## 4. Comparative reading (facts, not verdicts)

| packaging dimension | SolidCraft cdylib | PlaneGCS vendored C++ |
|---|---|---|
| license family (verified) | MIT OR Apache-2.0 (permissive) | LGPL-2.1-family + MPL-2.0 Eigen + boost |
| obligations kind | notices only | notices + library-boundary/relink discipline |
| closure size | 12 crates, no native code | 11 source files + Eigen headers + boost headers |
| build toolchain | Rust cross (incl. aarch64) | C++ per-target (same class as OCCT/OCP) |
| platform policy (verify) | binds equally | binds equally |
| extra blockers | unicode-ident FSF-listing (verify) — metadata-level | none NEW (this lane cleared the last license (verify) on this path) |
| scale of shipped artifact | cdylib (small; measured by W3-b) | .so with statically-linked Eigen (header-only, no extra binary) |

**The packaging dimension does not break the tie in either direction on
license grounds** — both are compatible-with-shipping under GPL-3.0-or-later;
SolidCraft is administratively lighter (permissive, no boundary duties,
no LGPL discipline), PlaneGCS carries ordinary LGPL obligations and has the
OCCT-toolchain synergy. The unresolved platform policy (verify) remains the
shared gate for both, exactly as it is for the kernel binding.
