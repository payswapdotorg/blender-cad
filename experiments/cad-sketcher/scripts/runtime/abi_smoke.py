"""ABI smoke test: import the pinned slvs cp313 manylinux wheel and solve a minimal sketch.

Run by Blender 5.2.2's bundled Python (3.13.13) with the wheel extracted to a
scratch --target dir (see run_phase1_runtime.py). NEVER installed into Blender's
site-packages; the target dir is scratch outside the repo.

Usage (exact line recorded in results/runtime-compat.json):
    PYTHONPATH=<scratch>/pytarget \
      <blender-runtime>/5.2/python/bin/python3.13 abi_smoke.py

Prints a JSON record on stdout; exit code 0 == all checks pass.
"""

import json
import sys

RECORD = {
    "driver": "abi_smoke.py",
    "python": sys.version,
}

checks = []


def record(name, passed, detail=""):
    checks.append({"check": name, "pass": bool(passed), "detail": detail})
    print(f"{'PASS' if passed else 'FAIL'} {name}  {detail}", file=sys.stderr)
    return bool(passed)


def main():
    import slvs  # noqa: F401  (the ABI check itself)

    record("import.slvs", True, f"slvs imported from {slvs.__path__[0]}")

    from slvs import (  # noqa: F401
        add_point_2d, add_point_3d, add_line_2d, add_normal_3d, add_workplane,
        coincident, horizontal, distance, clear_sketch, solve_sketch,
        get_param_value, ConstraintType, ResultFlag, E_FREE_IN_3D,
    )

    clear_sketch()
    # Workplane built exactly like the addon's CurveSolver._init_workplane()
    # (curve_solver.py): fixed origin point + normal in group 1, sketch entities
    # in group 3 (group_fixed=1, group_sketch=3).
    origin = add_point_3d(1, 0.0, 0.0, 0.0)
    normal = add_normal_3d(1, 1.0, 0.0, 0.0, 0.0)
    wp = add_workplane(1, origin, normal)
    p0 = add_point_2d(3, 0.0, 0.0, wp)
    p1 = add_point_2d(3, 5.0, 5.0, wp)
    line = add_line_2d(3, p0, p1, wp)
    # p0 pinned to the workplane origin, line horizontal, |p0 p1| = 10
    coincident(3, p0, origin, wp)
    horizontal(3, line, wp)
    distance(3, p0, p1, 10.0, wp)

    result = solve_sketch(3, calculateFaileds=False)
    dof = int(result["dof"])
    flag = int(result["result"])
    record("solve.sketch", flag == int(ResultFlag.OKAY),
           f"result flag {flag} (OKAY={int(ResultFlag.OKAY)}), dof {dof}")

    u0 = get_param_value(p0["param"][0]); v0 = get_param_value(p0["param"][1])
    u1 = get_param_value(p1["param"][0]); v1 = get_param_value(p1["param"][1])
    record("solve.p0_at_origin", abs(u0) < 1e-9 and abs(v0) < 1e-9, f"p0=({u0!r}, {v0!r})")
    record("solve.p1_at_distance10", abs(u1 - 10.0) < 1e-9 and abs(v1) < 1e-9,
           f"p1=({u1!r}, {v1!r})")
    record("solve.dof_zero", dof == 0, f"dof={dof}")

    clear_sketch()

    RECORD.update({
        "checks": checks,
        "solved": {"p0": [u0, v0], "p1": [u1, v1]},
        "solve_result": {"result": flag, "dof": dof, "rank": int(result.get("rank", -1))},
        "all_passed": all(c["pass"] for c in checks),
    })
    print(json.dumps(RECORD, indent=2))
    return 0 if RECORD["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
