# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

import pytest

import lang2.driftc.stage1.hir_nodes as H
from lang2.driftc.stage2 import HIRToMIR, MirBuilder, mir_nodes as M
from lang2.driftc.core.types_core import TypeTable


def test_lambda_immediate_call_lowered_inline_with_param_and_capture() -> None:
	builder = MirBuilder("main")
	type_table = TypeTable()
	lower = HIRToMIR(builder, type_table=type_table)
	# let x = 1; (outer capture)
	let_outer = H.HLet(name="x", value=H.HLiteralInt(1), declared_type_expr=None, binding_id=1)
	# (|x| => x + outer_x)(2) where parameter x shadows outer x
	lambda_expr = H.HLambda(
		params=[H.HParam(name="x", binding_id=10)],
		body_expr=H.HBinary(
			op=H.BinaryOp.ADD,
			left=H.HVar(name="x", binding_id=1),
			right=H.HVar(name="x", binding_id=10),
		),
	)
	call_expr = H.HCall(fn=lambda_expr, args=[H.HLiteralInt(2)], kwargs=[])
	ret = H.HReturn(value=call_expr)
	block = H.HBlock(statements=[let_outer, H.HExprStmt(expr=call_expr), ret])

	lower.lower_block(block)
	instrs = builder.func.blocks["entry"].instructions
	assert any(isinstance(i, M.ConstructStruct) for i in instrs)
	call_instrs = [i for i in instrs if isinstance(i, M.Call)]
	assert call_instrs
	assert call_instrs[-1].fn.startswith("__lambda_")
	assert getattr(builder, "extra_funcs", [])
	hidden = builder.extra_funcs[0]
	assert hidden.params and hidden.params[0] == "__env"
	hidden_instrs = hidden.blocks["entry"].instructions
	assert any(isinstance(i, M.StructGetField) for i in hidden_instrs)
	assert any(isinstance(i, M.BinaryOpInstr) and i.op is H.BinaryOp.ADD for i in hidden_instrs)


def test_lambda_block_body_returns_trailing_expr() -> None:
	builder = MirBuilder("main")
	type_table = TypeTable()
	lower = HIRToMIR(builder, type_table=type_table)
	block_body = H.HBlock(statements=[H.HExprStmt(expr=H.HLiteralInt(7))])
	lambda_expr = H.HLambda(params=[], body_expr=None, body_block=block_body)
	call_expr = H.HCall(fn=lambda_expr, args=[], kwargs=[])
	lower.lower_block(H.HBlock(statements=[H.HExprStmt(expr=call_expr)]))

	assert getattr(builder, "extra_funcs", [])
	hidden = builder.extra_funcs[-1]
	assert isinstance(hidden.blocks["entry"].terminator, M.Return)


def test_lambda_block_body_explicit_return_is_respected() -> None:
	builder = MirBuilder("main")
	type_table = TypeTable()
	lower = HIRToMIR(builder, type_table=type_table)
	block_body = H.HBlock(statements=[H.HReturn(value=H.HLiteralInt(3))])
	lambda_expr = H.HLambda(params=[], body_expr=None, body_block=block_body)
	call_expr = H.HCall(fn=lambda_expr, args=[], kwargs=[])
	lower.lower_block(H.HBlock(statements=[H.HExprStmt(expr=call_expr)]))

	hidden = builder.extra_funcs[-1]
	assert isinstance(hidden.blocks["entry"].terminator, M.Return)
