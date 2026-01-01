# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

from lang2.driftc import stage1 as H
from lang2.driftc.core.function_id import FunctionRefKind, function_ref_symbol
from lang2.driftc.core.types_core import TypeKind
from lang2.driftc.parser import parse_drift_workspace_to_hir
from lang2.driftc.module_lowered import flatten_modules
from lang2.driftc.type_checker import TypeChecker


def _write_file(path: Path, content: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content)


def _parse_workspace(tmp_path: Path, files: dict[Path, str]):
	mod_root = tmp_path / "mods"
	for rel, content in files.items():
		_write_file(mod_root / rel, content)
	paths = sorted(mod_root.rglob("*.drift"))
	modules, type_table, exc_catalog, module_exports, module_deps, diagnostics = parse_drift_workspace_to_hir(
		paths,
		module_paths=[mod_root],
	)
	func_hirs, sigs, fn_ids_by_name = flatten_modules(modules)
	return func_hirs, sigs, fn_ids_by_name, type_table, exc_catalog, module_exports, module_deps, diagnostics


def _display_name_for_fn_id(module: str, name: str) -> str:
	return name if module == "main" else f"{module}::{name}"


def test_exported_function_reference_uses_wrapper_symbol(tmp_path: Path) -> None:
	files = {
		Path("mod_a/lib.drift"): """
module mod_a

export { id }

pub fn id(x: Int) returns Int { return x; }
""",
		Path("mod_b/main.drift"): """
module mod_b

import mod_a as A

fn main() nothrow returns Int{
\tval fp: fn(Int) returns Int = A.id;
\treturn 0;
}
""",
	}
	func_hirs, signatures, _fn_ids_by_name, type_table, _exc_catalog, _exports, _deps, diagnostics = _parse_workspace(
		tmp_path, files
	)
	assert diagnostics == []

	main_id = next(fid for fid in func_hirs if fid.module == "mod_b" and fid.name == "main")
	main_sig = signatures[main_id]
	main_block = func_hirs[main_id]
	id_fn_id = next(fid for fid in signatures if fid.module == "mod_a" and fid.name == "id")
	signatures[id_fn_id].declared_can_throw = False

	call_sigs_by_name: dict[str, list[object]] = {}
	for fn_id, sig in signatures.items():
		if getattr(sig, "is_method", False):
			continue
		name = _display_name_for_fn_id(fn_id.module or "main", fn_id.name)
		call_sigs_by_name.setdefault(name, []).append(sig)
		if fn_id.module == "lang.core":
			call_sigs_by_name.setdefault(fn_id.name, []).append(sig)

	param_types: dict[str, int] = {}
	if main_sig.param_names and main_sig.param_type_ids:
		param_types = {pname: pty for pname, pty in zip(main_sig.param_names, main_sig.param_type_ids)}

	res = TypeChecker(type_table).check_function(
		main_id,
		main_block,
		param_types=param_types,
		return_type=main_sig.return_type_id,
		call_signatures=call_sigs_by_name,
		signatures_by_id=signatures,
	)
	assert not res.diagnostics

	let_stmt = next(stmt for stmt in res.typed_fn.body.statements if isinstance(stmt, H.HLet))
	assert isinstance(let_stmt.value, H.HFnPtrConst)
	fnptr = let_stmt.value

	assert fnptr.fn_ref.kind is FunctionRefKind.WRAPPER
	assert fnptr.fn_ref.has_wrapper is True
	assert function_ref_symbol(fnptr.fn_ref) == "mod_a::id"
	assert fnptr.call_sig.can_throw is True
	fnptr_ty = res.typed_fn.expr_types[fnptr.node_id]
	td = type_table.get(fnptr_ty)
	assert td.kind is TypeKind.FUNCTION
	assert td.fn_throws is True
