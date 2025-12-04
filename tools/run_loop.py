#!/usr/bin/env python3
"""
Run a binary repeatedly and optionally compare stdout to an expected string.

Usage:
  tools/run_loop.py --exe build/tests/e2e/exception_args_dot/a.out --runs 1000 --expect-file tests/e2e/exception_args_dot/expected.json

If --expect-file is provided and contains a JSON object with a "stdout" key,
the script will fail on the first mismatch and report the run number.
"""

import argparse
import json
import pathlib
import sys
import subprocess


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Loop-run a binary to catch flakiness")
    ap.add_argument("--exe", required=True, help="Path to executable to run")
    ap.add_argument("--runs", type=int, default=1000, help="Number of iterations")
    ap.add_argument("--expect-file", help="expected.json with stdout to compare")
    args = ap.parse_args(argv)

    expected = None
    if args.expect_file:
        p = pathlib.Path(args.expect_file)
        if p.exists():
            with p.open() as f:
                data = json.load(f)
            expected = data.get("stdout", "")

    ok = 0
    fail = 0
    for i in range(1, args.runs + 1):
        proc = subprocess.run([args.exe], capture_output=True, text=True)
        if expected is not None and proc.stdout != expected:
            sys.stderr.write(f"mismatch at run {i}:\n{proc.stdout}\n<<EOF>>\n")
            fail += 1
            break
        ok += 1
    print(f"runs ok: {ok}, fails: {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

