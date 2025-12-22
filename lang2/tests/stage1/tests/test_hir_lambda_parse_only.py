# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from lang2.driftc.stage1 import AstToHIR, HCall, HLambda
from lang2.driftc.stage0 import ast as s0


def test_hir_lower_lambda_immediate_call_structure() -> None:
	expr = s0.Call(
		func=s0.Lambda(
			params=[s0.Param(name="x", type_expr=None, loc=None)],
			body_expr=s0.Name(ident="x"),
			body_block=None,
			loc=None,
		),
		args=[s0.Literal(value=1)],
		kwargs=[],
		loc=None,
	)
	hir = AstToHIR().lower_expr(expr)
	assert isinstance(hir, HCall)
	assert isinstance(hir.fn, HLambda)
	assert hir.fn.params[0].name == "x"
	assert hir.fn.body_expr is not None


def test_hir_lower_lambda_standalone_structural() -> None:
	lam = s0.Lambda(
		params=[],
		body_expr=s0.Literal(value=1),
		body_block=None,
		loc=None,
	)
	hir = AstToHIR().lower_expr(lam)
	assert isinstance(hir, HLambda)
	assert hir.body_expr is not None
