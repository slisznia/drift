# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
"""
Signature-level can-throw invariants: declared can-throw functions must return
FnResult<_, Error> in their signatures. This guards the ABI before codegen.
"""

from __future__ import annotations

from lang2.driftc.stage2 import BasicBlock, MirFunc, Return
from lang2.driftc.stage3 import ThrowSummary
from lang2.driftc.stage4 import run_throw_checks
from lang2.driftc.checker import FnInfo, FnSignature
from lang2.driftc.core.types_core import TypeKind, TypeTable


class TableTypeEnv:
	"""
	Minimal TypeEnv for testing that understands TypeTable TypeIds.

	Only is_fnresult/fnresult_parts are used by these tests; type_of_ssa_value
	is deliberately unsupported so failures are obvious if the test wiring
	changes.
	"""

	def __init__(self, table: TypeTable) -> None:
		self._table = table

	def type_of_ssa_value(self, func_name: str, value_id: str):  # pragma: no cover - not used here
		raise RuntimeError("type_of_ssa_value should not be called in signature-shape tests")

	def is_fnresult(self, ty) -> bool:
		try:
			return self._table.get(ty).kind is TypeKind.FNRESULT
		except Exception:
			return False

	def fnresult_parts(self, ty):
		td = self._table.get(ty)
		if td.kind is not TypeKind.FNRESULT or len(td.param_types) < 2:
			raise TypeError(f"not a FnResult type id: {ty!r}")
		return td.param_types[0], td.param_types[1]


def _make_simple_func(name: str) -> MirFunc:
	"""Single-block MIR function that returns a placeholder value."""
	entry = BasicBlock(name="entry", instructions=[], terminator=Return(value="r0"))
	return MirFunc(name=name, params=[], locals=[], blocks={"entry": entry}, entry="entry")


def _empty_summary() -> ThrowSummary:
	return ThrowSummary(
		constructs_error=False,
		exception_types=set(),
		may_fail_sites=set(),
		call_sites=set(),
	)


def test_can_throw_signature_must_be_fnresult():
	table = TypeTable()
	int_ty = table.ensure_int()
	fn_name = "f_sig"
	fn_info = FnInfo(
		name=fn_name,
		declared_can_throw=True,
		signature=FnSignature(name=fn_name, return_type_id=int_ty),
		return_type_id=int_ty,
	)
	diagnostics = []
	run_throw_checks(
		funcs={fn_name: _make_simple_func(fn_name)},
		summaries={fn_name: _empty_summary()},
		declared_can_throw={fn_name: True},
		fn_infos={fn_name: fn_info},
		ssa_funcs={},  # type-aware path selected but no SSA needed for signature check
		type_env=TableTypeEnv(table),
		diagnostics=diagnostics,
	)
	assert any("return type is not FnResult" in d.message for d in diagnostics)


def test_can_throw_signature_error_part_must_be_error():
	table = TypeTable()
	int_ty = table.ensure_int()
	bool_ty = table.ensure_bool()
	fnresult_bad_err = table.new_fnresult(int_ty, bool_ty)
	fn_name = "f_err"
	fn_info = FnInfo(
		name=fn_name,
		declared_can_throw=True,
		signature=FnSignature(name=fn_name, return_type_id=fnresult_bad_err),
		return_type_id=fnresult_bad_err,
	)
	diagnostics = []
	run_throw_checks(
		funcs={fn_name: _make_simple_func(fn_name)},
		summaries={fn_name: _empty_summary()},
		declared_can_throw={fn_name: True},
		fn_infos={fn_name: fn_info},
		ssa_funcs={},
		type_env=TableTypeEnv(table),
		diagnostics=diagnostics,
	)
	assert any("error type is" in d.message for d in diagnostics)


def test_can_throw_signature_fnresult_error_passes():
	table = TypeTable()
	int_ty = table.ensure_int()
	err_ty = table.ensure_error()
	fnres = table.new_fnresult(int_ty, err_ty)
	fn_name = "f_ok"
	fn_info = FnInfo(
		name=fn_name,
		declared_can_throw=True,
		signature=FnSignature(name=fn_name, return_type_id=fnres),
		return_type_id=fnres,
	)
	diagnostics = []
	run_throw_checks(
		funcs={fn_name: _make_simple_func(fn_name)},
		summaries={fn_name: _empty_summary()},
		declared_can_throw={fn_name: True},
		fn_infos={fn_name: fn_info},
		ssa_funcs={},
		type_env=TableTypeEnv(table),
		diagnostics=diagnostics,
	)
	assert diagnostics == []
