from lang2.driftc.core.function_id import FunctionId
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-10
"""
LLVM lowering for Array<String> allocations and indexing.
"""

from lang2.driftc.checker import FnInfo, FnSignature
from lang2.driftc.core.types_core import TypeTable
from lang2.driftc.stage2 import (
	ArrayAlloc,
	ArrayLit,
	ArrayElemAssign,
	ArrayElemInitUnchecked,
	ArrayIndexLoad,
	ArrayLen,
	ArraySetLen,
	BasicBlock,
	CopyValue,
	ConstInt,
	ConstUint,
	ConstString,
	MirFunc,
	Return,
)
from lang2.driftc.stage4.ssa import MirToSSA
from lang2.codegen.llvm import lower_module_to_llvm
from lang2.codegen.llvm.test_utils import host_word_bits


def _types():
    table = TypeTable()
    int_ty = table.new_scalar("Int")
    uint_ty = table.new_scalar("Uint")
    str_ty = table.new_scalar("String")
    table._int_type = int_ty  # type: ignore[attr-defined]
    table._uint_type = uint_ty  # type: ignore[attr-defined]
    table._string_type = str_ty  # type: ignore[attr-defined]
    return table, int_ty, uint_ty, str_ty


def test_array_string_literal_and_index_ir():
	table, int_ty, uint_ty, str_ty = _types()

	block = BasicBlock(
		name="entry",
		instructions=[
			ConstString(dest="t0", value="a"),
			ConstString(dest="t1", value="bb"),
			ConstInt(dest="i0", value=0),
			ConstInt(dest="i1", value=1),
			ConstUint(dest="tlen0", value=0),
			ConstUint(dest="tlen", value=2),
			ConstUint(dest="tcap", value=2),
			ArrayAlloc(dest="t2", elem_ty=str_ty, length="tlen0", cap="tcap"),
			ArrayElemInitUnchecked(elem_ty=str_ty, array="t2", index="i0", value="t0"),
			ArrayElemInitUnchecked(elem_ty=str_ty, array="t2", index="i1", value="t1"),
			ArraySetLen(dest="t2_len", array="t2", length="tlen"),
			ConstInt(dest="idx", value=1),
			ArrayIndexLoad(dest="t3", elem_ty=str_ty, array="t2_len", index="idx"),
			CopyValue(dest="t3_copy", ty=str_ty, value="t3"),
		],
		terminator=Return(value="t3_copy"),
	)
	fn_id = FunctionId(module="main", name="main", ordinal=0)
	func = MirFunc(
		fn_id=fn_id,
		name="main",
		params=[],
		locals=["t0", "t1", "t2", "t2_len", "t3", "t3_copy", "idx", "i0", "i1", "tlen0", "tlen", "tcap"],
		blocks={"entry": block},
		entry="entry",
	)
	ssa = MirToSSA().run(func)
	sig = FnSignature(name="main", param_type_ids=[], return_type_id=str_ty)
	info = FnInfo(fn_id=fn_id, name="main", declared_can_throw=False, signature=sig, return_type_id=str_ty)

	mod = lower_module_to_llvm({fn_id: func}, {fn_id: ssa}, {fn_id: info}, type_table=table, word_bits=host_word_bits())
	ir = mod.render()

	assert "declare i8* @drift_alloc_array" in ir
	assert "%drift.usize = type i" in ir
	assert "%drift.isize = type i" in ir
	assert "%DriftString = type { %drift.usize, i8*" in ir
	assert "getelementptr %DriftString" in ir
	assert "call void @drift_bounds_check" in ir
	assert "call %DriftString @drift_string_retain" in ir


def test_array_string_lit_retains_elements():
	table, int_ty, uint_ty, str_ty = _types()
	arr_ty = table.new_array(str_ty)

	block = BasicBlock(
		name="entry",
		instructions=[
			ConstString(dest="t0", value="a"),
			ConstString(dest="t1", value="bb"),
			ArrayLit(dest="arr", elem_ty=str_ty, elements=["t0", "t1"]),
			ArrayLen(dest="len", array="arr"),
		],
		terminator=Return(value="len"),
	)
	fn_id = FunctionId(module="main", name="main", ordinal=0)
	func = MirFunc(
		fn_id=fn_id,
		name="main",
		params=[],
		locals=["t0", "t1", "arr", "len"],
		blocks={"entry": block},
		entry="entry",
	)
	ssa = MirToSSA().run(func)
	sig = FnSignature(name="main", param_type_ids=[], return_type_id=uint_ty)
	info = FnInfo(fn_id=fn_id, name="main", declared_can_throw=False, signature=sig, return_type_id=uint_ty)

	mod = lower_module_to_llvm({fn_id: func}, {fn_id: ssa}, {fn_id: info}, type_table=table, word_bits=host_word_bits())
	ir = mod.render()

	assert "call %DriftString @drift_string_retain" in ir


def test_array_string_store_ir():
	table, int_ty, uint_ty, str_ty = _types()

	block = BasicBlock(
		name="entry",
		instructions=[
			ConstString(dest="t0", value="a"),
			ConstString(dest="t1", value="bb"),
			ConstInt(dest="i0", value=0),
			ConstInt(dest="i1", value=1),
			ConstUint(dest="tlen0", value=0),
			ConstUint(dest="tlen", value=2),
			ConstUint(dest="tcap", value=2),
			ArrayAlloc(dest="t2", elem_ty=str_ty, length="tlen0", cap="tcap"),
			ArrayElemInitUnchecked(elem_ty=str_ty, array="t2", index="i0", value="t0"),
			ArrayElemInitUnchecked(elem_ty=str_ty, array="t2", index="i1", value="t1"),
			ArraySetLen(dest="t2_len", array="t2", length="tlen"),
			ConstInt(dest="idx", value=0),
			ConstString(dest="t3", value="ccc"),
			CopyValue(dest="t3_copy", ty=str_ty, value="t3"),
			ArrayElemAssign(elem_ty=str_ty, array="t2_len", index="idx", value="t3_copy"),
		],
		terminator=Return(value="t3"),
	)
	fn_id = FunctionId(module="main", name="main", ordinal=0)
	func = MirFunc(
		fn_id=fn_id,
		name="main",
		params=[],
		locals=["t0", "t1", "t2", "t2_len", "t3", "t3_copy", "idx", "i0", "i1", "tlen0", "tlen", "tcap"],
		blocks={"entry": block},
		entry="entry",
	)
	ssa = MirToSSA().run(func)
	sig = FnSignature(name="main", param_type_ids=[], return_type_id=str_ty)
	info = FnInfo(fn_id=fn_id, name="main", declared_can_throw=False, signature=sig, return_type_id=str_ty)

	mod = lower_module_to_llvm({fn_id: func}, {fn_id: ssa}, {fn_id: info}, type_table=table, word_bits=host_word_bits())
	ir = mod.render()

	assert "%drift.usize = type i" in ir
	assert "%drift.isize = type i" in ir
	assert "%DriftString = type { %drift.usize, i8*" in ir
	assert "declare i8* @drift_alloc_array" in ir
	assert "call i8* @drift_alloc_array" in ir
	assert "getelementptr %DriftString" in ir
	assert "call %DriftString @drift_string_retain" in ir
	assert "call void @drift_string_release" in ir
	assert "store %DriftString %t3_copy" in ir or "store %DriftString" in ir
	assert "call void @drift_bounds_check" in ir
