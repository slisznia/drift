# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

import lang2.driftc.stage1.hir_nodes as H
from lang2.driftc.checker import FnSignature
from lang2.driftc.method_registry import CallableDecl, CallableKind, CallableSignature, Visibility
from lang2.driftc.method_resolver import MethodResolution
from lang2.driftc.stage1.lambda_validate import validate_lambdas_non_escaping


def test_immediate_call_lambda_allowed() -> None:
	lam = H.HLambda(params=[], body_expr=H.HLiteralInt(1), body_block=None)
	call = H.HCall(fn=lam, args=[], kwargs=[])
	res = validate_lambdas_non_escaping(call)
	assert res.diagnostics == []


def test_lambda_non_call_rejected() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	res = validate_lambdas_non_escaping(lam)
	assert any("only immediate invocation" in d.message for d in res.diagnostics)


def test_lambda_nested_in_loop_rejected() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	loop = H.HLoop(body=H.HBlock(statements=[H.HExprStmt(expr=lam)]))
	res = validate_lambdas_non_escaping(loop)
	assert any("only immediate invocation" in d.message for d in res.diagnostics)


def test_lambda_in_call_arg_rejected() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	call = H.HCall(fn=H.HVar(name="f"), args=[lam], kwargs=[])
	res = validate_lambdas_non_escaping(call)
	assert any("only immediate invocation" in d.message for d in res.diagnostics)


def test_lambda_in_call_arg_allowed_for_nonescaping_param() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	call = H.HCall(fn=H.HVar(name="f"), args=[lam], kwargs=[])
	signatures = {
		"f": FnSignature(name="f", param_nonescaping=[True]),
	}
	res = validate_lambdas_non_escaping(call, signatures=signatures)
	assert res.diagnostics == []


def test_lambda_immediate_call_nested_in_expr_allowed() -> None:
	inner = H.HCall(fn=H.HLambda(params=[], body_expr=H.HLiteralInt(1), body_block=None), args=[], kwargs=[])
	outer = H.HCall(fn=H.HVar(name="g"), args=[inner], kwargs=[])
	res = validate_lambdas_non_escaping(outer)
	assert res.diagnostics == []


def test_lambda_nested_in_try_body_rejected() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	try_stmt = H.HTry(body=H.HBlock(statements=[H.HExprStmt(expr=lam)]), catches=[])
	res = validate_lambdas_non_escaping(H.HBlock(statements=[try_stmt]))
	assert any("only immediate invocation" in d.message for d in res.diagnostics)


def test_lambda_nested_in_catch_body_rejected() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	catch = H.HCatchArm(event_fqn=None, binder=None, block=H.HBlock(statements=[H.HExprStmt(expr=lam)]))
	try_stmt = H.HTry(body=H.HBlock(statements=[]), catches=[catch])
	res = validate_lambdas_non_escaping(H.HBlock(statements=[try_stmt]))
	assert any("only immediate invocation" in d.message for d in res.diagnostics)


def test_lambda_nested_in_match_arm_rejected() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	arm = H.HMatchArm(ctor=None, binders=[], block=H.HBlock(statements=[H.HExprStmt(expr=lam)]), result=None)
	match_expr = H.HMatchExpr(scrutinee=H.HVar(name="x"), arms=[arm])
	res = validate_lambdas_non_escaping(match_expr)
	assert any("only immediate invocation" in d.message for d in res.diagnostics)


def test_lambda_inside_place_projection_rejected() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	place = H.HPlaceExpr(base=H.HVar(name="x"), projections=[H.HPlaceIndex(index=lam)])
	expr = H.HBorrow(subject=place, is_mut=False)
	res = validate_lambdas_non_escaping(expr)
	assert any("only immediate invocation" in d.message for d in res.diagnostics)


def _method_resolution(method_name: str, *, impl_target_type_id: int = 1) -> MethodResolution:
	decl = CallableDecl(
		callable_id=1,
		name=method_name,
		kind=CallableKind.METHOD_INHERENT,
		module_id=0,
		visibility=Visibility.public(),
		signature=CallableSignature(param_types=(), result_type=0),
		impl_id=1,
		impl_target_type_id=impl_target_type_id,
	)
	return MethodResolution(decl=decl, receiver_autoborrow=None)


def test_lambda_in_method_call_arg_allowed_for_nonescaping_param() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	call = H.HMethodCall(receiver=H.HVar(name="xs"), method_name="for_each", args=[lam], kwargs=[])
	signatures = {
		"Vec::for_each": FnSignature(
			name="Vec::for_each",
			method_name="for_each",
			is_method=True,
			impl_target_type_id=1,
			param_nonescaping=[False, True],
			param_names=["self", "f"],
		),
	}
	call_resolutions = {id(call): _method_resolution("for_each", impl_target_type_id=1)}
	res = validate_lambdas_non_escaping(call, signatures=signatures, call_resolutions=call_resolutions)
	assert res.diagnostics == []


def test_lambda_in_method_call_arg_rejected_when_not_nonescaping() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	call = H.HMethodCall(receiver=H.HVar(name="xs"), method_name="for_each", args=[lam], kwargs=[])
	signatures = {
		"Vec::for_each": FnSignature(
			name="Vec::for_each",
			method_name="for_each",
			is_method=True,
			impl_target_type_id=1,
			param_nonescaping=[False, False],
			param_names=["self", "f"],
		),
	}
	call_resolutions = {id(call): _method_resolution("for_each", impl_target_type_id=1)}
	res = validate_lambdas_non_escaping(call, signatures=signatures, call_resolutions=call_resolutions)
	assert any("only immediate invocation" in d.message for d in res.diagnostics)


def test_lambda_in_method_call_arg_rejected_when_unresolved() -> None:
	lam = H.HLambda(params=[], body_expr=H.HVar(name="x", binding_id=1), body_block=None)
	call = H.HMethodCall(receiver=H.HVar(name="xs"), method_name="for_each", args=[lam], kwargs=[])
	res = validate_lambdas_non_escaping(call, signatures={}, call_resolutions={})
	assert any("only immediate invocation" in d.message for d in res.diagnostics)


def test_lambda_non_call_allowed_without_borrow_capture() -> None:
	lam = H.HLambda(params=[], body_expr=H.HLiteralInt(1), body_block=None)
	res = validate_lambdas_non_escaping(lam)
	assert res.diagnostics == []
