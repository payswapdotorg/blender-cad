# Module: toolsets

- **Status:** planned (no code at M0)
- **Owner:** W1 (UX + libraries)
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M4+ (toolset libraries begin at M4 — glossary §11)

## Purpose

Specialist toolsets as mutually independent sub-packages: mechanical,
electrical, MEP, plant, civil, GIS and raster. Each toolset is a library of
domain content and behaviors on top of the shared drafting core — never a fork
of it.

## Owns

- Seven independent sub-packages (one per toolset: mechanical, electrical,
  mep, plant, civil, gis, raster)
- Toolset content: symbol libraries, catalogs, schedules, GIS/raster handling
- Toolset-specific drafting automation built on shared modules

## Does NOT own

- Shared drafting plumbing (belongs in `drafting`/`drawings`/`parametric` —
  shared code goes down, not sideways)
- Another toolset's internals (no toolset→toolset dependency, glossary §4)
- File I/O beyond delegating to `interchange`/GIS engines per adoption matrix

## FP areas

- TS — specialist toolsets (entries carry a `toolset:` field per glossary §5)

## Allowed dependencies

- `document`, `drafting`, `drawings`, `parametric`, `kernel`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `ToolsetRegistry` — discover/enable toolsets; registration into the shell
- `mechanical` — parts, holes, frames, standard profiles
- `electrical` — symbol libraries, panel schedules, wiring annotations
- `mep` — routing (duct/pipe/cable-tray) behaviors
- `plant` — equipment, piping, instrumentation content
- `civil` — surfaces/alignments (candidate surface; scoped at M4)
- `gis` — GDAL/PDAL-backed geospatial import and georeferencing
- `raster` — georeferenced raster and point-cloud handling

## Tests

- docs/30-process/test-plan.md: TP-CAT-05 (toolset sections; independence of
  sub-packages is asserted here). Suite home once code lands:
  `modules/toolsets/tests/`.
