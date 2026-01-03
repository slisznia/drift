from __future__ import annotations

import re
from pathlib import Path

from lang2.driftc.driftc import compile_to_llvm_ir_for_tests
from lang2.driftc.parser import parse_drift_workspace_to_hir
from lang2.driftc.module_lowered import flatten_modules


def _extract_llvm_function(ir: str, fn: str) -> str:
	"""
	Extract the textual LLVM IR for a single function definition.

	This is intentionally simple and stable for tests: locate `define ... @<fn>`
	and return everything up to (but not including) the next `define` line.
	"""
	lines = ir.splitlines()
	start = None
	for i, line in enumerate(lines):
		if line.startswith("define ") and re.search(rf"@{re.escape(fn)}\b", line):
			start = i
			break
	if start is None:
		raise AssertionError(f"missing LLVM function definition for {fn}")
	end = len(lines)
	for i in range(start + 1, len(lines)):
		if lines[i].startswith("define "):
			end = i
			break
	return "\n".join(lines[start:end])


def test_cross_module_exported_call_uses_wrapper_not_impl(tmp_path: Path) -> None:
	"""
	Cross-module calls to exported entrypoints must call the public wrapper symbol,
	not the private `__impl` body.
	"""
	(tmp_path / "acme" / "point").mkdir(parents=True)
	(tmp_path / "acme" / "point" / "lib.drift").write_text(
		"\n".join(
			[
				"module acme.point",
				"",
				"export { Point, make_point };",
				"",
				"pub struct Point(x: Int, y: Int)",
				"",
				"pub fn make_point() -> Point {",
				"\treturn Point(x = 1, y = 2);",
				"}",
				"",
			]
		)
	)
	(tmp_path / "main.drift").write_text(
		"\n".join(
			[
				"module main",
				"",
				"import acme.point as ap;",
				"",
				"fn main() nothrow -> Int {",
				"\tval p: ap.Point = try ap.make_point() catch { ap.Point(x = 0, y = 0) };",
				"\treturn p.x + p.y;",
				"}",
				"",
			]
		)
	)

	drift_files = sorted(tmp_path.rglob("*.drift"))
	modules, type_table, exception_catalog, module_exports, module_deps, diags = parse_drift_workspace_to_hir(
		drift_files,
		module_paths=[tmp_path],
	)
	assert not diags
	func_hirs, signatures, _fn_ids_by_name = flatten_modules(modules)

	ir, checked = compile_to_llvm_ir_for_tests(
		func_hirs=func_hirs,
		signatures=signatures,
		exc_env=exception_catalog,
		entry="main",
		type_table=type_table,
		module_exports=module_exports,
		module_deps=module_deps,
	)
	assert not checked.diagnostics

	main_ir = _extract_llvm_function(ir, "main")
	assert '@"acme.point::make_point"' in main_ir
	assert "__impl" not in main_ir
