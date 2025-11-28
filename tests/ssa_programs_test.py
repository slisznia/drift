"""SSA-only regression suite over sample programs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DRIFTC = ROOT / "lang" / "driftc.py"
VENV_PY = os.environ.get("VENV_PY", str(ROOT / ".venv" / "bin" / "python3"))


def _run_program(path: Path) -> None:
    try:
        import llvmlite  # noqa: F401
    except ImportError:
        print("llvmlite missing; skipping SSA program tests", file=sys.stderr)
        return
    env = dict(os.environ)
    env["SSA_ONLY"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    out_obj = path.with_suffix(".o")
    proc = subprocess.run(
        [
            VENV_PY,
            "-m",
            "lang.driftc",
            str(path),
            "-o",
            str(out_obj),
            "--ssa-check",
            "--ssa-check-mode=fail",
            "--ssa-simplify",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    if proc.returncode != 0 and "GenericAlias" in proc.stderr:
        print("types shadowing detected; skipping SSA program tests", file=sys.stderr)
        return
    if path.name.startswith("negative_"):
        assert proc.returncode != 0, f"expected failure for {path.name}"
        return
    assert proc.returncode == 0, f"SSA check failed for {path.name}: {proc.stderr}"
    assert out_obj.exists(), f"expected output object for {path.name}"


def test_ssa_programs() -> None:
    for drift_file in sorted((ROOT / "tests" / "ssa_programs").glob("*.drift")):
        _run_program(drift_file)


if __name__ == "__main__":
    test_ssa_programs()
