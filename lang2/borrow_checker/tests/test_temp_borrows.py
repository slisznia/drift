#!/usr/bin/env python3
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-09
"""Temporary borrow/NLL-approximation tests."""

from lang2 import stage1 as H
from lang2.borrow_checker_pass import BorrowChecker
from lang2.borrow_checker import PlaceBase, PlaceKind
from lang2.core.types_core import TypeTable


def _checker() -> BorrowChecker:
	table = TypeTable()
	type_ids = {"x": table.ensure_int()}
	base_lookup = lambda n: PlaceBase(PlaceKind.LOCAL, 0, n)
	return BorrowChecker(type_table=table, fn_types=type_ids, base_lookup=base_lookup)


def test_temp_borrow_in_expr_stmt_does_not_block_later_mut_borrow():
	"""
	A borrow used only in an expression statement should end immediately,
	allowing a later borrow on the same place.
	"""
	block = H.HBlock(
		statements=[
			H.HLet(name="x", value=H.HLiteralInt(1), declared_type_expr=None),
			H.HExprStmt(expr=H.HBorrow(subject=H.HVar("x"), is_mut=False)),
			H.HExprStmt(expr=H.HBorrow(subject=H.HVar("x"), is_mut=True)),
		]
	)
	diags = _checker().check_block(block)
	assert diags == []


def test_condition_borrow_does_not_block_later_mut_borrow():
	"""Borrow in an if condition is temporary and should not block later mut borrow."""
	block = H.HBlock(
		statements=[
			H.HLet(name="x", value=H.HLiteralInt(1), declared_type_expr=None),
			H.HIf(
				cond=H.HBorrow(subject=H.HVar("x"), is_mut=False),
				then_block=H.HBlock(statements=[]),
				else_block=H.HBlock(statements=[]),
			),
			H.HExprStmt(expr=H.HBorrow(subject=H.HVar("x"), is_mut=True)),
		]
	)
	diags = _checker().check_block(block)
	assert diags == []
