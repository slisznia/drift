# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-10
"""
LLVM lowering for String literals and returns.
"""

from lang2.checker import FnInfo, FnSignature
from lang2.core.types_core import TypeTable
from lang2.stage2 import BasicBlock, ConstString, MirFunc, Return
from lang2.stage4.ssa import MirToSSA
from lang2.codegen.llvm import lower_ssa_func_to_llvm, lower_module_to_llvm


def _string_type(table: TypeTable):
	str_ty = table.new_scalar("String")
	table._string_type = str_ty  # type: ignore[attr-defined]
	return str_ty


def test_string_literal_return_ir():
	table = TypeTable()
	str_ty = _string_type(table)

	block = BasicBlock(
		name="entry",
		instructions=[
			ConstString(dest="t0", value="abc"),
		],
		terminator=Return(value="t0"),
	)
	func = MirFunc(name="f", params=[], locals=[], blocks={"entry": block}, entry="entry")
	ssa = MirToSSA().run(func)
	sig = FnSignature(name="f", return_type_id=str_ty, param_type_ids=[])
	fn_info = FnInfo(name="f", declared_can_throw=False, signature=sig, return_type_id=str_ty)

	ir = lower_ssa_func_to_llvm(func, ssa, fn_info, {"f": fn_info}, type_table=table)

	assert "%DriftString = type { %drift.size, i8*" in ir
	assert '@.str0 = private unnamed_addr constant [4 x i8] c"abc\\00"' in ir
	assert "define %DriftString @f()" in ir
	assert "ret %DriftString" in ir


def test_string_pass_through_call_ir():
	table = TypeTable()
	str_ty = _string_type(table)

	# callee: return its string argument
	caller_block = BasicBlock(
		name="entry",
		instructions=[
			ConstString(dest="t0", value="abc"),
		],
		terminator=Return(value="t0"),
	)
	caller = MirFunc(name="main", params=[], locals=[], blocks={"entry": caller_block}, entry="entry")
	caller_ssa = MirToSSA().run(caller)
	caller_sig = FnSignature(name="main", param_type_ids=[], return_type_id=str_ty)
	caller_info = FnInfo(name="main", declared_can_throw=False, signature=caller_sig, return_type_id=str_ty)

	mod = lower_module_to_llvm(
		{"main": caller},
		{"main": caller_ssa},
		{"main": caller_info},
		type_table=table,
	)
	ir = mod.render()

	assert "%DriftString = type { %drift.size, i8*" in ir
	assert '@.str0 = private unnamed_addr constant [4 x i8] c"abc\\00"' in ir
	assert "define %DriftString @main()" in ir
	assert "ret %DriftString" in ir
