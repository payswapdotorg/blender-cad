# Python drivers — experiment-side tooling (NOT product code)

Drivers here run under the experiment environment(s):

- `.ocp-venv/` (gitignored): `cadquery-ocp==8.0.1.1.0` wheels — the OCCT/OCP side of
  the kernel comparison (experiment C). This venv is an evaluation artifact; it is NOT
  a product dependency and must never be referenced from `modules/` or requirements files.
- repo dev Python (3.12, pytest): for anything importing `bcdoc` — the document-model
  mapping probes. Imports use the same sys.path bootstrap the repo's `conftest.py`
  provides; drivers must never modify product code or fixtures outside
  `experiments/solidcraft/`.

Each driver writes its result JSON to `../results/` using the shared envelope.
