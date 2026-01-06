# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-07
"""
HIR → MIR lowering for array literals and indexing.
"""

from lang2.driftc.core.types_core import TypeTable
from lang2.driftc.core.function_id import FunctionId
from lang2.driftc.stage1 import (
	HArrayLiteral,
	HAssign,
	HBlock,
	HExprStmt,
	HField,
	HIndex,
	HLet,
	HLiteralInt,
	HLiteralString,
	HVar,
)
from lang2.driftc.stage1.normalize import normalize_hir
from lang2.driftc.stage2 import (
	ArrayAlloc,
	ArrayElemAssign,
	ArrayElemInitUnchecked,
	ArrayIndexLoad,
	ArrayLen,
	ArraySetLen,
	CopyValue,
	HIRToMIR,
	make_builder,
)


def _make_type_table():
	table = TypeTable()
	int_ty = table.ensure_int()
	table.ensure_bool()
	table.ensure_string()
	table.ensure_unknown()
	return table, int_ty


def test_array_literal_and_index_lowering():
	table, int_ty = _make_type_table()
	block = HBlock(
		statements=[
			HLet(name="xs", value=HArrayLiteral(elements=[HLiteralInt(1), HLiteralInt(2)])),
			HExprStmt(expr=HIndex(subject=HVar("xs"), index=HLiteralInt(1))),
			HExprStmt(expr=HField(subject=HVar("xs"), name="len")),
		]
	)
	builder = make_builder(FunctionId(module="main", name="f", ordinal=0))
	HIRToMIR(builder, type_table=table).lower_block(normalize_hir(block))
	entry = builder.func.blocks[builder.func.entry]
	kinds = {type(instr) for instr in entry.instructions}
	assert ArrayAlloc in kinds
	assert ArrayElemInitUnchecked in kinds
	assert ArraySetLen in kinds
	assert ArrayIndexLoad in kinds
	assert ArrayLen in kinds
	array_allocs = [instr for instr in entry.instructions if isinstance(instr, ArrayAlloc)]
	assert array_allocs and array_allocs[0].elem_ty == int_ty
	loads = [instr for instr in entry.instructions if isinstance(instr, ArrayIndexLoad)]
	assert loads and loads[0].elem_ty == int_ty


def test_array_index_store_lowering():
	table, int_ty = _make_type_table()
	block = HBlock(
		statements=[
			HLet(name="xs", value=HArrayLiteral(elements=[HLiteralInt(1), HLiteralInt(2)])),
			HAssign(
				target=HIndex(subject=HVar("xs"), index=HLiteralInt(0)),
				value=HLiteralInt(5),
			),
		]
	)
	builder = make_builder(FunctionId(module="main", name="f", ordinal=0))
	HIRToMIR(builder, type_table=table).lower_block(normalize_hir(block))
	entry = builder.func.blocks[builder.func.entry]
	assigns = [instr for instr in entry.instructions if isinstance(instr, ArrayElemAssign)]
	assert assigns and assigns[0].elem_ty == int_ty


def test_array_index_load_inserts_copyvalue_for_copy_elems():
	table, _int_ty = _make_type_table()
	string_ty = table._string_type  # type: ignore[attr-defined]
	block = HBlock(
		statements=[
			HLet(name="xs", value=HArrayLiteral(elements=[HLiteralInt(1), HLiteralInt(2)])),
			HExprStmt(expr=HIndex(subject=HVar("xs"), index=HLiteralInt(1))),
		]
	)
	builder = make_builder(FunctionId(module="main", name="f", ordinal=0))
	lowerer = HIRToMIR(builder, type_table=table)
	lowerer._local_types["xs"] = table.new_array(string_ty)
	lowerer.lower_block(normalize_hir(block))
	entry = builder.func.blocks[builder.func.entry]
	load_idx = None
	copy_idx = None
	for idx, instr in enumerate(entry.instructions):
		if isinstance(instr, ArrayIndexLoad):
			load_idx = idx
		if isinstance(instr, CopyValue):
			copy_idx = idx
	if load_idx is None or copy_idx is None:
		raise AssertionError("expected ArrayIndexLoad followed by CopyValue for Copy element type")
	assert copy_idx > load_idx


def test_array_literal_reuses_copy_value_for_string_lvalues():
	table, _int_ty = _make_type_table()
	string_ty = table._string_type  # type: ignore[attr-defined]
	block = HBlock(
		statements=[
			HLet(name="s", value=HLiteralString(value="a")),
			HLet(
				name="xs",
				value=HArrayLiteral(elements=[HVar("s"), HVar("s")]),
			),
		]
	)
	builder = make_builder(FunctionId(module="main", name="f", ordinal=0))
	lowerer = HIRToMIR(builder, type_table=table)
	lowerer.lower_block(normalize_hir(block))
	entry = builder.func.blocks[builder.func.entry]
	copy_vals = [instr for instr in entry.instructions if isinstance(instr, CopyValue)]
	assert len(copy_vals) == 2
	for instr in copy_vals:
		assert instr.ty == string_ty


def test_array_literal_single_string_lvalue_emits_copyvalue():
	table, _int_ty = _make_type_table()
	string_ty = table._string_type  # type: ignore[attr-defined]
	block = HBlock(
		statements=[
			HLet(name="s", value=HLiteralString(value="a")),
			HLet(
				name="xs",
				value=HArrayLiteral(elements=[HVar("s")]),
			),
		]
	)
	builder = make_builder(FunctionId(module="main", name="f", ordinal=0))
	lowerer = HIRToMIR(builder, type_table=table)
	lowerer.lower_block(normalize_hir(block))
	entry = builder.func.blocks[builder.func.entry]
	copy_vals = [instr for instr in entry.instructions if isinstance(instr, CopyValue)]
	assert len(copy_vals) == 1
	assert copy_vals[0].ty == string_ty
