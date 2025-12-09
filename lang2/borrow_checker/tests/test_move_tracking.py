#!/usr/bin/env python3
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-09

from lang2 import stage1 as H
from lang2.borrow_checker_pass import BorrowChecker
from lang2.borrow_checker import PlaceBase, PlaceKind
from lang2.core.types_core import TypeTable


def _checker_with_types(var_types: dict[str, str]) -> BorrowChecker:
	table = TypeTable()
	type_ids = {}
	for name, kind in var_types.items():
		if kind == "Int":
			type_ids[name] = table.ensure_int()
		elif kind == "Bool":
			type_ids[name] = table.ensure_bool()
		else:
			type_ids[name] = table.ensure_unknown()
	base_lookup = lambda n: PlaceBase(PlaceKind.LOCAL, 0, n)
	return BorrowChecker(type_table=table, fn_types=type_ids, base_lookup=base_lookup)


def test_use_after_move_reports_diagnostic():
	block = H.HBlock(
		statements=[
			H.HLet(name="x", value=H.HLiteralInt(1), declared_type_expr=None),
			H.HExprStmt(expr=H.HVar("x")),  # move (non-Copy)
			H.HExprStmt(expr=H.HVar("x")),  # use after move
		]
	)
	bc = _checker_with_types({"x": "Unknown"})
	diags = bc.check_block(block)
	assert any("use after move" in d.message for d in diags)


def test_move_from_val_reports_diagnostic():
	block = H.HBlock(
		statements=[
			H.HLet(name="x", value=H.HLiteralInt(1), declared_type_expr=None),
			H.HAssign(target=H.HVar("x"), value=H.HLiteralInt(2)),  # overwrite -> valid
			H.HExprStmt(expr=H.HVar("x")),
			H.HExprStmt(expr=H.HVar("x")),  # use after move
		]
	)
	bc = _checker_with_types({"x": "Unknown"})
	diags = bc.check_block(block)
	assert any("use after move" in d.message for d in diags)


def test_copy_type_is_not_moved():
	block = H.HBlock(
		statements=[
			H.HLet(name="b", value=H.HLiteralBool(True), declared_type_expr=None),
			H.HExprStmt(expr=H.HVar("b")),  # Bool is Copy => no move
			H.HExprStmt(expr=H.HVar("b")),
		]
	)
	bc = _checker_with_types({"b": "Bool"})
	diags = bc.check_block(block)
	assert diags == []
