#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS_DIR = ROOT / "tests" / "programs"
EXPECTATIONS_DIR = ROOT / "tests" / "expectations"


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
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
