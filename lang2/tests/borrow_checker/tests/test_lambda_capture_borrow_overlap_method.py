# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from lang2.driftc import stage1 as H
from lang2.driftc.borrow_checker_pass import BorrowChecker
from lang2.driftc.checker import FnSignature
from lang2.driftc.core.types_core import TypeTable
from lang2.driftc.method_registry import CallableDecl, CallableKind, CallableSignature, SelfMode, Visibility
from lang2.driftc.method_resolver import MethodResolution
from lang2.driftc.type_checker import TypedFn


def _typed_fn_with_method_call(
	*,
	lambda_arg: H.HLambda,
	other_arg: H.HExpr,
	self_mode: SelfMode = SelfMode.SELF_BY_REF,
	receiver_autoborrow: SelfMode | None = None,
) -> tuple[TypedFn, dict[str, FnSignature], dict[int, object], TypeTable]:
	table = TypeTable()
	int_ty = table.ensure_int()
	unknown_ty = table.ensure_unknown()
	point_ty = table.declare_struct(module_id="main", name="Point", field_names=["x"])
	table.define_struct_fields(point_ty, [int_ty])
	if self_mode is SelfMode.SELF_BY_REF_MUT:
		recv_ty = table.ensure_ref_mut(point_ty)
	elif self_mode is SelfMode.SELF_BY_REF:
		recv_ty = table.ensure_ref(point_ty)
	else:
		recv_ty = point_ty

	x_id = 1
	s_id = 2
	y_id = 3
	x_let = H.HLet(name="x", value=H.HLiteralInt(1), binding_id=x_id, is_mutable=True)
	s_let = H.HLet(name="s", value=H.HLiteralInt(0), binding_id=s_id, is_mutable=True)
	y_let = H.HLet(name="y", value=H.HLiteralInt(2), binding_id=y_id, is_mutable=True)

	call = H.HMethodCall(
		receiver=H.HVar(name="s", binding_id=s_id),
		method_name="for_each",
		args=[lambda_arg, other_arg],
		kwargs=[],
	)
	body = H.HBlock(statements=[x_let, s_let, y_let, H.HExprStmt(expr=call)])

	signatures = {
		"Point::for_each": FnSignature(
			name="Point::for_each",
			method_name="for_each",
			is_method=True,
			impl_target_type_id=point_ty,
			param_nonescaping=[False, True, False],
			param_names=["self", "f", "y"],
			param_type_ids=[recv_ty, unknown_ty, int_ty],
		),
	}

	decl = CallableDecl(
		callable_id=1,
		name="for_each",
		kind=CallableKind.METHOD_INHERENT,
		module_id=0,
		visibility=Visibility.public(),
		signature=CallableSignature(param_types=(recv_ty, unknown_ty, int_ty), result_type=int_ty),
		impl_id=1,
		impl_target_type_id=point_ty,
		self_mode=SelfMode.SELF_BY_REF,
	)
	call_resolutions = {id(call): MethodResolution(decl=decl, receiver_autoborrow=receiver_autoborrow)}

	typed_fn = TypedFn(
		name="main",
		params=[],
		param_bindings=[],
		locals=[x_id, s_id, y_id],
		body=body,
		expr_types={},
		binding_for_var={},
		binding_types={x_id: int_ty, s_id: point_ty, y_id: int_ty},
		binding_names={x_id: "x", s_id: "s", y_id: "y"},
		binding_mutable={x_id: True, s_id: True, y_id: True},
		call_resolutions=call_resolutions,
	)
	return typed_fn, signatures, call_resolutions, table


def test_method_nonescaping_lambda_capture_conflicts_with_mut_arg() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	other = H.HBorrow(subject=H.HVar(name="x", binding_id=1), is_mut=True)
	typed_fn, sigs, _res, table = _typed_fn_with_method_call(lambda_arg=lam, other_arg=other)
	bc = BorrowChecker.from_typed_fn(typed_fn, type_table=table, signatures=sigs, enable_auto_borrow=True)
	diags = bc.check_block(typed_fn.body)
	assert any("mutable borrow" in d.message for d in diags)


def test_method_nonescaping_lambda_capture_allows_disjoint_mut_arg() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	other = H.HBorrow(subject=H.HVar(name="y", binding_id=3), is_mut=True)
	typed_fn, sigs, _res, table = _typed_fn_with_method_call(lambda_arg=lam, other_arg=other)
	bc = BorrowChecker.from_typed_fn(typed_fn, type_table=table, signatures=sigs, enable_auto_borrow=True)
	diags = bc.check_block(typed_fn.body)
	assert diags == []


def test_method_nonescaping_lambda_capture_conflicts_with_mut_arg_autoborrow_receiver() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	other = H.HBorrow(subject=H.HVar(name="x", binding_id=1), is_mut=True)
	typed_fn, sigs, _res, table = _typed_fn_with_method_call(
		lambda_arg=lam,
		other_arg=other,
		self_mode=SelfMode.SELF_BY_REF_MUT,
		receiver_autoborrow=SelfMode.SELF_BY_REF_MUT,
	)
	bc = BorrowChecker.from_typed_fn(typed_fn, type_table=table, signatures=sigs, enable_auto_borrow=True)
	diags = bc.check_block(typed_fn.body)
	assert any("mutable borrow" in d.message for d in diags)
