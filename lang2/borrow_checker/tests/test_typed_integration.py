#!/usr/bin/env python3
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-09
"""Integration of TypeChecker + BorrowChecker on TypedFn."""

from lang2 import stage1 as H
from lang2.type_checker import TypeChecker
from lang2.borrow_checker_pass import BorrowChecker
from lang2.core.types_core import TypeTable


def _borrow_checker_for_typed_fn(typed_fn, table: TypeTable) -> BorrowChecker:
	return BorrowChecker.from_typed_fn(typed_fn, table)


def test_use_after_move_via_typed_checker():
	table = TypeTable()
	tc = TypeChecker(table)
	block = H.HBlock(
		statements=[
			H.HLet(name="x", value=H.HArrayLiteral(elements=[H.HLiteralInt(1)]), declared_type_expr=None),
			H.HExprStmt(expr=H.HVar("x")),  # move
			H.HExprStmt(expr=H.HVar("x")),  # use after move
		]
	)
	tres = tc.check_function("f", block, param_types={})
	assert tres.diagnostics == []
	bc = _borrow_checker_for_typed_fn(tres.typed_fn, table)
	diags = bc.check_block(tres.typed_fn.body)
	assert any("use after move" in d.message for d in diags)
