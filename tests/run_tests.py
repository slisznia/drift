#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROGRAMS_DIR = ROOT / "tests" / "programs"
EXPECTATIONS_DIR = ROOT / "tests" / "expectations"
MIR_CASES_DIR = ROOT / "tests" / "mir_lowering"


def load_expectation(name: str) -> Dict[str, object]:
    path = EXPECTATIONS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"missing expectation file for {name}: {path}")
    return json.loads(path.read_text())


def run_program(path: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "drift.py"), str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def main() -> int:
    failures = 0
    failures += _run_runtime_tests()
    failures += _run_mir_tests()
    return 1 if failures else 0


def _run_runtime_tests() -> int:
    failures = 0
    for program in sorted(PROGRAMS_DIR.glob("*.drift")):
        name = program.stem
        try:
            expected = load_expectation(name)
        except FileNotFoundError as exc:
            print(f"[missing] {program}: {exc}", file=sys.stderr)
            failures += 1
            continue
        exit_code, stdout, stderr = run_program(program)
        exp_exit = expected.get("exit")
        exp_stdout = expected.get("stdout")
        exp_stderr = expected.get("stderr")

        ok = True
        if exp_exit is not None and exit_code != exp_exit:
            ok = False
            print(f"[fail] {program}: exit {exit_code} != expected {exp_exit}", file=sys.stderr)
        if exp_stdout is not None and stdout != exp_stdout:
            ok = False
            print(f"[fail] {program}: stdout mismatch", file=sys.stderr)
            print("=== expected ===", file=sys.stderr)
            print(exp_stdout, end="", file=sys.stderr)
            print("=== got ===", file=sys.stderr)
            print(stdout, end="", file=sys.stderr)
        if exp_stderr is not None and stderr != exp_stderr:
            ok = False
            print(f"[fail] {program}: stderr mismatch", file=sys.stderr)
            print("=== expected ===", file=sys.stderr)
            print(exp_stderr, end="", file=sys.stderr)
            print("=== got ===", file=sys.stderr)
            print(stderr, end="", file=sys.stderr)

        if ok:
            print(f"[ok] {program}")
        else:
            failures += 1
    return failures


def _run_mir_tests() -> int:
    from lang import parser, checker
    from lang.runtime import builtin_signatures
    from lang.lower_to_mir import lower_straightline
    from lang.mir_printer import format_program
    from lang.mir_verifier import verify_program

    failures = 0
    for source_path in sorted(MIR_CASES_DIR.glob("*.drift")):
        name = source_path.stem
        expected_path = MIR_CASES_DIR / f"{name}.mir"
        if not expected_path.exists():
            print(f"[missing] {source_path}: expected MIR {expected_path} not found", file=sys.stderr)
            failures += 1
            continue
        source = source_path.read_text()
        prog = parser.parse_program(source)
        checked = checker.Checker(builtin_signatures()).check(prog)
        mir_prog = lower_straightline(checked)
        try:
            verify_program(mir_prog)
        except Exception as exc:
            failures += 1
            print(f"[fail] MIR {name}: verification error {exc}", file=sys.stderr)
            continue
        # Emit MIR text
        rendered = format_program(mir_prog)
        expected = expected_path.read_text().rstrip()
        if rendered.strip() != expected.strip():
            failures += 1
            print(f"[fail] MIR {name}: mismatch", file=sys.stderr)
            print("=== expected ===", file=sys.stderr)
            print(expected, file=sys.stderr)
            print("=== got ===", file=sys.stderr)
            print(rendered, file=sys.stderr)
        else:
            print(f"[ok] MIR {name}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
