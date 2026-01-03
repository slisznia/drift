# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

import pytest

from lang2.driftc import stage1 as H
from lang2.driftc.core.function_id import FunctionId
from lang2.driftc.core.types_core import TypeTable
from lang2.driftc.parser import ast as parser_ast
from lang2.driftc.stage1.node_ids import assign_node_ids
from lang2.driftc.stage2 import HIRToMIR, make_builder


def test_stage2_rejects_hcast() -> None:
	table = TypeTable()
	cast_expr = H.HCast(
		target_type_expr=parser_ast.TypeExpr(name="Int"),
		value=H.HLiteralInt(1),
	)
	block = H.HBlock(statements=[H.HExprStmt(expr=cast_expr)])
	assign_node_ids(block)

	builder = make_builder(FunctionId(module="main", name="test_func", ordinal=0))
	lower = HIRToMIR(builder, type_table=table)
	with pytest.raises(AssertionError) as excinfo:
		lower.lower_block(block)
	msg = str(excinfo.value)
	assert "HCast must be eliminated during typecheck" in msg
	assert "node_id=" in msg
	assert "target=" in msg
