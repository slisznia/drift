#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
# Ensure project root is ahead of the script directory to avoid shadowing stdlib modules (e.g., types)
sys.path = [str(ROOT)] + [p for p in sys.path if p != str(SCRIPT_DIR)]

from lang import parser, checker  # type: ignore
from lang.lower_to_mir import lower_straightline
from lang.lower_to_mir_ssa import lower_function_ssa, LoweringError
from lang.mir_to_llvm import lower_function
from lang.runtime import builtin_signatures
from lang.mir_verifier import verify_program
from lang.mir_verifier_ssa_v2 import SSAVerifierV2


def _run_ssa_check(checked: checker.CheckedProgram) -> None:
    """Lower all user-defined functions through the SSA scaffold and verify structure."""
    for fn_def in checked.program.functions:
        if fn_def.name not in checked.functions:
            continue
        try:
            lowered = lower_function_ssa(fn_def, checked)
        except LoweringError as e:
            raise SystemExit(f"SSA lowering failed for {fn_def.name}: {e}")
        verifier_fn = type("F", (), {"blocks": lowered.blocks, "entry": lowered.entry})
        SSAVerifierV2(verifier_fn).verify()


def compile_file(
    source_path: Path, output_path: Path, emit_ir: bool, ssa_check: bool, ssa_mode: str
) -> int:
    source = source_path.read_text()
    prog = parser.parse_program(source)
    checked = checker.Checker(builtin_signatures()).check(prog)
    if ssa_check:
        try:
            _run_ssa_check(checked)
        except Exception as e:
            if ssa_mode == "warn":
                print(f"[ssa-check] warning: {e}", file=sys.stderr)
            else:
                raise
    mir_prog = lower_straightline(checked, source_name=str(source_path), module_name=checked.module or prog.module)
    verify_program(mir_prog)
    # TODO: handle multiple functions; currently only the first is emitted.
    fn = next(iter(mir_prog.functions.values()))
    llvm_ir, obj_bytes = lower_function(fn)
    if emit_ir:
        print(llvm_ir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(obj_bytes)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="driftc: minimal Drift -> MIR -> LLVM compiler (straight-line subset)")
    ap.add_argument("source", type=Path, help="Drift source file")
    ap.add_argument("-o", "--output", type=Path, help="Output object file (.o)", required=True)
    ap.add_argument("--emit-ir", action="store_true", help="Print the generated LLVM IR to stdout")
    ap.add_argument(
        "--ssa-check",
        action="store_true",
        help="Also run the strict SSA lowering + verifier; codegen still uses legacy MIR",
    )
    ap.add_argument(
        "--ssa-check-mode",
        choices=["fail", "warn"],
        default="fail",
        help="When --ssa-check is enabled: fail on SSA errors (default) or warn and continue",
    )
    args = ap.parse_args(argv)

    return compile_file(args.source, args.output, args.emit_ir, args.ssa_check, args.ssa_check_mode)


if __name__ == "__main__":
    raise SystemExit(main())
