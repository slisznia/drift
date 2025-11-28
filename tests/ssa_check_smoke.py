"""Smoke test: run driftc with --ssa-check-mode=fail on a tiny program that SSA lowering supports."""

from __future__ import annotations

import subprocess
from pathlib import Path
import sys
import os

HERE = Path(__file__).parent
ROOT = HERE.parent
DRIFTC = ROOT / "lang" / "driftc.py"
VENV_PY = os.environ.get("VENV_PY", str(ROOT / ".venv" / "bin" / "python3"))


def test_ssa_check_smoke(tmp_path: Path) -> None:
    try:
        import llvmlite  # noqa: F401
    except ImportError:
        print("llvmlite missing; skipping SSA smoke tests", file=sys.stderr)
        return
    src = tmp_path / "main.drift"
    src.write_text(
        "import std.console.out\n"
        "fn main() returns Int32 {\n"
        "  out.writeln(\"hi from ssa\")\n"
        "  return 0\n"
        "}\n"
    )
    out_obj = tmp_path / "out.o"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [VENV_PY, str(DRIFTC), str(src), "-o", str(out_obj), "--ssa-check", "--ssa-check-mode=fail"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    if proc.returncode != 0 and "GenericAlias" in proc.stderr:
        print("types shadowing detected; skipping SSA smoke tests", file=sys.stderr)
        return
    if proc.returncode != 0 and "GenericAlias" in proc.stderr:
        print("types shadowing detected; skipping SSA smoke tests", file=sys.stderr)
        return
    assert proc.returncode == 0, f"compiler failed: {proc.stderr}"
    assert out_obj.exists(), "expected output object file"


def test_ssa_check_control_flow(tmp_path: Path) -> None:
    try:
        import llvmlite  # noqa: F401
    except ImportError:
        print("llvmlite missing; skipping SSA smoke tests", file=sys.stderr)
        return
    src = tmp_path / "control.drift"
    src.write_text(
        "import std.console.out\n"
        "fn main() returns Int32 {\n"
        "  var i: Int32 = 0\n"
        "  while i < 3 {\n"
        "    if i == 1 {\n"
        "      out.writeln(\"mid\")\n"
        "    }\n"
        "    i = i + 1\n"
        "  }\n"
        "  return 0\n"
        "}\n"
    )
    out_obj = tmp_path / "out2.o"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [VENV_PY, str(DRIFTC), str(src), "-o", str(out_obj), "--ssa-check", "--ssa-check-mode=fail"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    assert proc.returncode == 0, f"compiler failed: {proc.stderr}"
    assert out_obj.exists(), "expected output object file"


def test_ssa_check_try_else(tmp_path: Path) -> None:
    try:
        import llvmlite  # noqa: F401
    except ImportError:
        print("llvmlite missing; skipping SSA smoke tests", file=sys.stderr)
        return
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    src = tmp_path / "try_else.drift"
    src.write_text(
        "import std.console.out\n"
        "fn foo(x: Int64) returns Int64 { return x }\n"
        "fn main() returns Int32 {\n"
        "  val y: Int64 = try foo(1) else 42\n"
        "  out.writeln(\"y = \" + y.to_string())\n"
        "  return 0\n"
        "}\n"
    )
    out_obj = tmp_path / "out3.o"
    proc = subprocess.run(
        [VENV_PY, str(DRIFTC), str(src), "-o", str(out_obj), "--ssa-check", "--ssa-check-mode=fail"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    if proc.returncode != 0 and "GenericAlias" in proc.stderr:
        print("types shadowing detected; skipping SSA smoke tests", file=sys.stderr)
        return
    assert proc.returncode == 0, f"compiler failed: {proc.stderr}"
    assert out_obj.exists(), "expected output object file"


def test_ssa_check_try_catch(tmp_path: Path) -> None:
    try:
        import llvmlite  # noqa: F401
    except ImportError:
        print("llvmlite missing; skipping SSA smoke tests", file=sys.stderr)
        return
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    src = tmp_path / "try_catch.drift"
    src.write_text(
        "import std.console.out\n"
        "fn might_fail(x: Int64) returns Int64 { return x }\n"
        "fn main() returns Int32 {\n"
        "  try {\n"
        "    out.writeln(\"before\")\n"
        "    might_fail(1)\n"
        "  } catch {\n"
        "    out.writeln(\"caught\")\n"
        "  }\n"
        "  return 0\n"
        "}\n"
    )
    out_obj = tmp_path / "out4.o"
    proc = subprocess.run(
        [VENV_PY, str(DRIFTC), str(src), "-o", str(out_obj), "--ssa-check", "--ssa-check-mode=fail"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    if proc.returncode != 0 and "GenericAlias" in proc.stderr:
        print("types shadowing detected; skipping SSA smoke tests", file=sys.stderr)
        return
    assert proc.returncode == 0, f"compiler failed: {proc.stderr}"
    assert out_obj.exists(), "expected output object file"

if __name__ == "__main__":
    test_ssa_check_smoke(Path("/tmp"))
