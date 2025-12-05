# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
AST→HIR lowering tests for try/throw.
"""

import pytest

from lang2.stage0 import ast
from lang2.stage1 import AstToHIR, HThrow, HTry, HBlock, HExprStmt, HVar


def test_throw_stmt_to_hthrow():
	l = AstToHIR()
	stmt = ast.ThrowStmt(value=ast.Name("err"))
	hir = l.lower_stmt(stmt)
	assert isinstance(hir, HThrow)
	assert isinstance(hir.value, HVar)
	assert hir.value.name == "err"


def test_try_stmt_to_htry():
	l = AstToHIR()
	stmt = ast.TryStmt(
		body=[ast.ExprStmt(expr=ast.Name("body"))],
		catches=[
			ast.CatchExprArm(event=None, binder="e", block=[ast.ExprStmt(expr=ast.Name("handler"))])
		],
	)
	hir = l.lower_stmt(stmt)
	assert isinstance(hir, HTry)
	assert hir.catch_name == "e"
	assert isinstance(hir.body, HBlock)
	assert isinstance(hir.catch_block, HBlock)
	assert isinstance(hir.body.statements[0], HExprStmt)
	assert isinstance(hir.catch_block.statements[0], HExprStmt)


def test_raise_stmt_still_not_supported():
	l = AstToHIR()
	stmt = ast.RaiseStmt(value=ast.Name("x"))
	with pytest.raises(NotImplementedError):
		l.lower_stmt(stmt)
