"""
Drift-source end-to-end runner (clang-based).

Each case lives under `lang2/codegen/e2e/<case>/` and must provide:
  - main.drift   (currently a very small subset: single fn returning a literal)
  - expected.json with exit_code/stdout/stderr fields

The runner:
  1) Reads and minimally parses main.drift (fn name, return type, return literal).
  2) Builds an AST block -> HIR via AstToHIR.
  3) Runs the full stubbed pipeline to LLVM IR (`compile_to_llvm_ir_for_tests`).
  4) Compiles IR with clang and executes the binary.
  5) Compares exit/stdout/stderr to expected.json.

Artifacts are written to `build/tests/lang2/codegen/e2e/<case>/`.

Notes:
  - Parsing is intentionally minimal and only supports the simple shapes used in
    these smoke tests until a full parser is wired.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional

from lang2.stage0 import ast
from lang2.stage1 import AstToHIR
from lang2.checker import FnSignature
from lang2.driftc import compile_to_llvm_ir_for_tests


ROOT = Path(__file__).resolve().parents[3]
BUILD_ROOT = ROOT / "build" / "tests" / "lang2" / "codegen" / "e2e"


def _parse_main_drift(text: str) -> tuple[str, str, ast.ReturnStmt]:
	"""
	Minimal parser for the first smoke cases: expects

	fn <name>() returns <RetTy> { return <int_literal>; }

	Returns (fn_name, return_type_str, ReturnStmt).
	"""
	fn_match = re.search(r"fn\s+([A-Za-z_][A-Za-z0-9_]*)", text)
	name = fn_match.group(1) if fn_match else "drift_main"

	ret_match = re.search(r"returns\s+([A-Za-z0-9_<>,\s]+)", text)
	return_type = ret_match.group(1).strip() if ret_match else "Int"

	ret_lit = re.search(r"return\s+(-?\d+)\s*;", text)
	if not ret_lit:
		raise ValueError("Unsupported main.drift shape: expected `return <int>;`")
	value = int(ret_lit.group(1))
	return name, return_type, ast.ReturnStmt(value=ast.Literal(value=value))


def _build_hir_block(ret_stmt: ast.ReturnStmt) -> object:
	"""Lower a simple AST block with a single return into HIR."""
	ast_block = [ret_stmt]
	return AstToHIR().lower_block(ast_block)


def _run_ir_with_clang(ir: str, build_dir: Path) -> tuple[int, str, str]:
	"""Compile the provided LLVM IR with clang and return (exit, stdout, stderr)."""
	clang = shutil.which("clang-15") or shutil.which("clang")
	if clang is None:
		return -999, "", "clang not available"

	build_dir.mkdir(parents=True, exist_ok=True)
	ir_path = build_dir / "ir.ll"
	bin_path = build_dir / "a.out"
	ir_path.write_text(ir)

	compile_res = subprocess.run(
		[clang, "-x", "ir", str(ir_path), "-o", str(bin_path)],
		capture_output=True,
		text=True,
		cwd=ROOT,
	)
	if compile_res.returncode != 0:
		return compile_res.returncode, "", compile_res.stderr

	run_res = subprocess.run(
		[str(bin_path)],
		capture_output=True,
		text=True,
		cwd=ROOT,
	)
	return run_res.returncode, run_res.stdout, run_res.stderr


def _run_case(case_dir: Path) -> str:
	expected_path = case_dir / "expected.json"
	source_path = case_dir / "main.drift"
	if not expected_path.exists() or not source_path.exists():
		return "skipped (missing expected.json or main.drift)"

	expected = json.loads(expected_path.read_text())
	source_text = source_path.read_text()

	try:
		fn_name, ret_type, ret_stmt = _parse_main_drift(source_text)
	except ValueError as e:
		return f"FAIL (parse error: {e})"

	hir_block = _build_hir_block(ret_stmt)
	signatures = {fn_name: FnSignature(name=fn_name, return_type=ret_type)}

	ir = compile_to_llvm_ir_for_tests(
		func_hirs={fn_name: hir_block},
		signatures=signatures,
		entry=fn_name,
	)

	build_dir = BUILD_ROOT / case_dir.name
	exit_code, stdout, stderr = _run_ir_with_clang(ir, build_dir)
	if exit_code == -999:
		return "skipped (clang not available)"

	if exit_code != expected.get("exit_code", 0):
		return f"FAIL (exit {exit_code}, expected {expected.get('exit_code', 0)})"
	if stdout != expected.get("stdout", ""):
		return "FAIL (stdout mismatch)"
	if stderr != expected.get("stderr", ""):
		return "FAIL (stderr mismatch)"
	return "ok"


def main(argv: Iterable[str] | None = None) -> int:
	ap = argparse.ArgumentParser(description="Run Drift-source codegen e2e cases (clang-based)")
	ap.add_argument(
		"cases",
		nargs="*",
		help="Specific test case names to run (directories under lang2/codegen/e2e)",
	)
	args = ap.parse_args(argv)

	case_root = ROOT / "lang2" / "codegen" / "e2e"
	case_dirs = sorted(case_root.iterdir()) if case_root.exists() else []
	if args.cases:
		names = set(args.cases)
		case_dirs = [d for d in case_dirs if d.name in names]

	failures: list[tuple[Path, str]] = []
	for case_dir in case_dirs:
		status = _run_case(case_dir)
		print(f"{case_dir.name}: {status}")
		if status.startswith("FAIL"):
			failures.append((case_dir, status))

	if failures:
		for case, status in failures:
			print(f"[codegen e2e] {case.name}: {status}", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
