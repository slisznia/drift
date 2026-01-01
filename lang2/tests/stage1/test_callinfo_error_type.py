# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

from lang2.driftc.core.function_id import function_symbol
from lang2.driftc.core.types_core import TypeKind, TypeTable
from lang2.driftc.parser import parse_drift_workspace_to_hir
from lang2.driftc.module_lowered import flatten_modules
from lang2.driftc.stage1.normalize import normalize_hir
from lang2.driftc.type_checker import TypeChecker
from lang2.driftc.stage1.call_info import CallSig, call_abi_ret_type


def test_call_abi_error_type_is_canonical() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()

	sig_a = CallSig(param_types=(int_ty,), user_ret_type=int_ty, can_throw=True)
	sig_b = CallSig(param_types=(), user_ret_type=int_ty, can_throw=True)

	ret_a = call_abi_ret_type(sig_a, table)
	ret_b = call_abi_ret_type(sig_b, table)

	assert ret_a == ret_b
	td = table.get(ret_a)
	assert td.kind is TypeKind.FNRESULT
	assert td.param_types and td.param_types[1] == table.ensure_error()


def test_call_abi_error_type_is_canonical_across_modules(tmp_path: Path) -> None:
	mod_a = tmp_path / "a.drift"
	mod_b = tmp_path / "b.drift"
	mod_a.write_text(
		"""
module a
fn boom() returns Int { return 1; }
fn main() returns Int { return boom(); }
""".lstrip()
	)
	mod_b.write_text(
		"""
module b
fn boom() returns Int { return 2; }
fn main() returns Int { return boom(); }
""".lstrip()
	)

	modules, table, _exc, _exports, _deps, diags = parse_drift_workspace_to_hir([mod_a, mod_b])
	assert not diags
	func_hirs, sigs, _fn_ids = flatten_modules(modules)

	call_sigs_by_name: dict[str, list] = {}
	can_throw_by_name: dict[str, bool] = {}
	for fn_id, sig in sigs.items():
		if sig.is_method:
			continue
		sym = function_symbol(fn_id)
		call_sigs_by_name.setdefault(sym, []).append(sig)
		if fn_id.name == "boom":
			can_throw_by_name[sym] = True

	checker = TypeChecker(type_table=table)
	call_infos = []
	for fn_id, block in func_hirs.items():
		if fn_id.name != "main":
			continue
		normalized = normalize_hir(block)
		sig = sigs.get(fn_id)
		result = checker.check_function(
			fn_id,
			normalized,
			param_types={},
			return_type=sig.return_type_id if sig is not None else None,
			call_signatures=call_sigs_by_name,
			signatures_by_id=sigs,
			can_throw_by_name=can_throw_by_name,
		)
		call_infos.extend(result.typed_fn.call_info_by_node_id.values())

	assert len(call_infos) == 2
	ret_ids = [call_abi_ret_type(info.sig, table) for info in call_infos]
	assert ret_ids[0] == ret_ids[1]
	ret_def = table.get(ret_ids[0])
	assert ret_def.kind is TypeKind.FNRESULT
	assert ret_def.param_types and ret_def.param_types[1] == table.ensure_error()
