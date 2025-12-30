# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from lang2.driftc import stage1 as H
from lang2.driftc.checker import Checker, FnSignature
from lang2.driftc.core.types_core import TypeTable


def _catch_arm(result_expr: H.HExpr) -> H.HTryExprArm:
	return H.HTryExprArm(
		event_fqn=None,
		binder=None,
		block=H.HBlock(statements=[]),
		result=result_expr,
	)


def _try_expr(attempt: H.HExpr, result_expr: H.HExpr) -> H.HTryExpr:
	return H.HTryExpr(attempt=attempt, arms=[_catch_arm(result_expr)])


def test_try_expr_rejects_void_attempt() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	void_ty = table.ensure_void()

	sigs = {
		"v": FnSignature(name="v", param_type_ids=[], return_type_id=void_ty, declared_can_throw=False),
		"main": FnSignature(name="main", param_type_ids=[], return_type_id=int_ty, declared_can_throw=False),
	}
	funcs = {
		"v": H.HBlock(statements=[H.HReturn(value=None)]),
		"main": H.HBlock(
			statements=[
				H.HLet(
					name="x",
					value=_try_expr(
						H.HCall(fn=H.HVar(name="v"), args=[]),
						H.HLiteralInt(value=0),
					),
				),
				H.HReturn(value=H.HLiteralInt(value=0)),
			]
		),
	}

	checker = Checker(signatures=sigs, hir_blocks=funcs, type_table=table)
	checked = checker.check(funcs.keys())
	msgs = [d.message for d in checked.diagnostics]
	assert any("try/catch attempt must produce a value (not Void)" in m for m in msgs)


def test_try_expr_rejects_nothrow_ternary_attempt() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()

	sigs = {"main": FnSignature(name="main", param_type_ids=[], return_type_id=int_ty, declared_can_throw=False)}
	attempt = H.HTernary(
		cond=H.HLiteralBool(value=True),
		then_expr=H.HLiteralInt(value=1),
		else_expr=H.HLiteralInt(value=2),
	)
	funcs = {
		"main": H.HBlock(
			statements=[
				H.HLet(name="x", value=_try_expr(attempt, H.HLiteralInt(value=0))),
				H.HReturn(value=H.HLiteralInt(value=0)),
			]
		)
	}

	checker = Checker(signatures=sigs, hir_blocks=funcs, type_table=table)
	checked = checker.check(funcs.keys())
	msgs = [d.message for d in checked.diagnostics]
	assert any("'try' applied to a nothrow expression" in m for m in msgs)


def test_try_expr_allows_may_throw_ternary_attempt() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()

	sigs = {
		"may_fail": FnSignature(
			name="may_fail",
			param_type_ids=[int_ty],
			return_type_id=int_ty,
			declared_can_throw=True,
		),
		"main": FnSignature(name="main", param_type_ids=[], return_type_id=int_ty, declared_can_throw=False),
	}
	attempt = H.HTernary(
		cond=H.HLiteralBool(value=True),
		then_expr=H.HCall(fn=H.HVar(name="may_fail"), args=[H.HLiteralInt(value=1)]),
		else_expr=H.HLiteralInt(value=2),
	)
	funcs = {
		"may_fail": H.HBlock(statements=[H.HReturn(value=H.HLiteralInt(value=1))]),
		"main": H.HBlock(
			statements=[
				H.HLet(name="x", value=_try_expr(attempt, H.HLiteralInt(value=0))),
				H.HReturn(value=H.HLiteralInt(value=0)),
			]
		),
	}

	checker = Checker(signatures=sigs, hir_blocks=funcs, type_table=table)
	checked = checker.check(funcs.keys())
	assert not checked.diagnostics


def test_try_expr_allows_indexing_attempt() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()

	sigs = {"main": FnSignature(name="main", param_type_ids=[], return_type_id=int_ty, declared_can_throw=False)}
	arr_literal = H.HArrayLiteral(elements=[H.HLiteralInt(value=1), H.HLiteralInt(value=2)])
	attempt = H.HIndex(subject=H.HVar(name="arr"), index=H.HLiteralInt(value=0))
	funcs = {
		"main": H.HBlock(
			statements=[
				H.HLet(name="arr", value=arr_literal),
				H.HLet(name="x", value=_try_expr(attempt, H.HLiteralInt(value=0))),
				H.HReturn(value=H.HLiteralInt(value=0)),
			]
		)
	}

	checker = Checker(signatures=sigs, hir_blocks=funcs, type_table=table)
	checked = checker.check(funcs.keys())
	msgs = [d.message for d in checked.diagnostics]
	assert not [m for m in msgs if "'try' applied to a nothrow expression" in m]
