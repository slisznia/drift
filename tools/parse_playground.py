#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

from lark import UnexpectedInput

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lang import parser


def main() -> int:
    files = sorted(Path("playground").glob("*.drift"))
    if not files:
        print("no playground files found", file=sys.stderr)
        return 1

    failed = False
    for path in files:
        try:
            parser.parse_program(path.read_text())
            print(f"[ok] {path}")
        except UnexpectedInput as exc:
            failed = True
            print(f"[parse error] {path}: {exc}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
