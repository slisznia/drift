# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from lang2.driftc import stage1 as H
from lang2.driftc.checker import FnSignature
from lang2.driftc.core.function_id import FunctionId, FunctionRefKind
from lang2.driftc.core.types_core import TypeTable, TypeKind
from lang2.driftc.parser.ast import TypeExpr
from lang2.driftc.type_checker import TypeChecker


def _fn_type_expr(param_names: list[str], ret_name: str, *, nothrow: bool | None = None) -> TypeExpr:
	args = [TypeExpr(name=p) for p in param_names]
	args.append(TypeExpr(name=ret_name))
	return TypeExpr(name="fn", args=args, fn_throws=(not bool(nothrow)))


def test_typed_function_reference_emits_fnptr_const() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	fn_id_add1 = FunctionId(module="main", name="add1", ordinal=0)
	fn_id_main = FunctionId(module="main", name="main", ordinal=0)
	add1_sig = FnSignature(
		name="add1",
		param_type_ids=[int_ty],
		return_type_id=int_ty,
		declared_can_throw=False,
	)
	block = H.HBlock(
		statements=[
			H.HLet(
				name="f",
				value=H.HVar("add1"),
				declared_type_expr=_fn_type_expr(["Int"], "Int", nothrow=True),
			),
		]
	)
	res = TypeChecker(table).check_function(
		fn_id_main,
		block,
		call_signatures={"add1": [add1_sig]},
		signatures_by_id={fn_id_add1: add1_sig},
	)
	assert not res.diagnostics
	let_stmt = next(stmt for stmt in block.statements if isinstance(stmt, H.HLet))
	assert isinstance(let_stmt.value, H.HFnPtrConst)
	assert let_stmt.value.fn_ref.fn_id == fn_id_add1
	assert let_stmt.value.fn_ref.kind is FunctionRefKind.IMPL
	assert let_stmt.value.fn_ref.has_wrapper is False
	assert let_stmt.value.call_sig.can_throw is False


def test_ambiguous_function_reference_requires_annotation() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	str_ty = table.ensure_string()
	fn_id_main = FunctionId(module="main", name="main", ordinal=0)
	foo_int = FnSignature(
		name="foo",
		param_type_ids=[int_ty],
		return_type_id=int_ty,
		declared_can_throw=False,
	)
	foo_str = FnSignature(
		name="foo",
		param_type_ids=[str_ty],
		return_type_id=int_ty,
		declared_can_throw=False,
	)
	block = H.HBlock(statements=[H.HLet(name="f", value=H.HVar("foo"))])
	res = TypeChecker(table).check_function(
		fn_id_main,
		block,
		call_signatures={"foo": [foo_int, foo_str]},
		signatures_by_id={
			FunctionId(module="main", name="foo", ordinal=0): foo_int,
			FunctionId(module="main", name="foo", ordinal=1): foo_str,
		},
	)
	assert any("ambiguous function reference 'foo'" in d.message for d in res.diagnostics)


def test_exported_function_reference_is_can_throw() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	fn_id_id = FunctionId(module="main", name="id", ordinal=0)
	fn_id_main = FunctionId(module="main", name="main", ordinal=0)
	id_sig = FnSignature(
		name="id",
		param_type_ids=[int_ty],
		return_type_id=int_ty,
		declared_can_throw=False,
	)
	id_sig.is_exported_entrypoint = True
	block = H.HBlock(
		statements=[
			H.HLet(
				name="f",
				value=H.HVar("id"),
				declared_type_expr=_fn_type_expr(["Int"], "Int"),
			),
		]
	)
	res = TypeChecker(table).check_function(
		fn_id_main,
		block,
		call_signatures={"id": [id_sig]},
		signatures_by_id={fn_id_id: id_sig},
	)
	let_stmt = next(stmt for stmt in block.statements if isinstance(stmt, H.HLet))
	assert isinstance(let_stmt.value, H.HFnPtrConst)
	assert let_stmt.value.call_sig.can_throw is True
	assert let_stmt.value.fn_ref.kind is FunctionRefKind.WRAPPER
	assert let_stmt.value.fn_ref.has_wrapper is True
	fn_ty = res.typed_fn.expr_types[let_stmt.value.node_id]
	td = table.get(fn_ty)
	assert td.kind is TypeKind.FUNCTION
	assert td.fn_throws is True


def test_nothrow_value_coerces_to_can_throw_with_thunk() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	fn_id_add1 = FunctionId(module="main", name="add1", ordinal=0)
	fn_id_main = FunctionId(module="main", name="main", ordinal=0)
	add1_sig = FnSignature(
		name="add1",
		param_type_ids=[int_ty],
		return_type_id=int_ty,
		declared_can_throw=False,
	)
	block = H.HBlock(
		statements=[
			H.HLet(
				name="f",
				value=H.HVar("add1"),
				declared_type_expr=_fn_type_expr(["Int"], "Int"),
			),
		]
	)
	res = TypeChecker(table).check_function(
		fn_id_main,
		block,
		call_signatures={"add1": [add1_sig]},
		signatures_by_id={fn_id_add1: add1_sig},
	)
	assert not res.diagnostics
	let_stmt = next(stmt for stmt in block.statements if isinstance(stmt, H.HLet))
	assert isinstance(let_stmt.value, H.HFnPtrConst)
	assert let_stmt.value.fn_ref.kind is FunctionRefKind.THUNK_OK_WRAP
	assert let_stmt.value.call_sig.can_throw is True


def test_captureless_lambda_coerces_to_fn_pointer() -> None:
	table = TypeTable()
	fn_id_main = FunctionId(module="main", name="main", ordinal=0)
	lam = H.HLambda(
		params=[H.HParam(name="x")],
		body_expr=H.HVar(name="x"),
		body_block=None,
	)
	block = H.HBlock(
		statements=[
			H.HLet(
				name="f",
				value=lam,
				declared_type_expr=_fn_type_expr(["Int"], "Int", nothrow=True),
			),
		]
	)
	res = TypeChecker(table).check_function(fn_id_main, block, call_signatures={}, signatures_by_id={})
	assert not res.diagnostics
	let_stmt = next(stmt for stmt in block.statements if isinstance(stmt, H.HLet))
	assert isinstance(let_stmt.value, H.HFnPtrConst)
	assert let_stmt.value.call_sig.can_throw is False


def test_capturing_lambda_rejected_for_fn_pointer() -> None:
	table = TypeTable()
	fn_id_main = FunctionId(module="main", name="main", ordinal=0)
	lam = H.HLambda(
		params=[H.HParam(name="x")],
		body_expr=H.HVar(name="y"),
		body_block=None,
	)
	block = H.HBlock(
		statements=[
			H.HLet(name="y", value=H.HLiteralInt(1)),
			H.HLet(
				name="f",
				value=lam,
				declared_type_expr=_fn_type_expr(["Int"], "Int", nothrow=True),
			),
		]
	)
	res = TypeChecker(table).check_function(fn_id_main, block, call_signatures={}, signatures_by_id={})
	assert any("capturing lambdas cannot be coerced" in d.message for d in res.diagnostics)


def test_cast_function_reference_disambiguates_overload() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	float_ty = table.ensure_float()
	fn_id_abs_i = FunctionId(module="main", name="abs", ordinal=0)
	fn_id_abs_f = FunctionId(module="main", name="abs", ordinal=1)
	abs_int = FnSignature(
		name="abs",
		param_type_ids=[int_ty],
		return_type_id=int_ty,
		declared_can_throw=False,
	)
	abs_float = FnSignature(
		name="abs",
		param_type_ids=[float_ty],
		return_type_id=float_ty,
		declared_can_throw=False,
	)
	block = H.HBlock(
		statements=[
			H.HLet(
				name="f",
				value=H.HCast(
					target_type_expr=_fn_type_expr(["Int"], "Int", nothrow=True),
					value=H.HVar("abs"),
				),
			),
		]
	)
	res = TypeChecker(table).check_function(
		FunctionId(module="main", name="main", ordinal=0),
		block,
		call_signatures={"abs": [abs_int, abs_float]},
		signatures_by_id={fn_id_abs_i: abs_int, fn_id_abs_f: abs_float},
	)
	assert not res.diagnostics
	let_stmt = next(stmt for stmt in block.statements if isinstance(stmt, H.HLet))
	assert isinstance(let_stmt.value, H.HFnPtrConst)
	assert let_stmt.value.call_sig.can_throw is False


def test_cast_function_reference_reports_no_match() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	float_ty = table.ensure_float()
	fn_id_abs_i = FunctionId(module="main", name="abs", ordinal=0)
	fn_id_abs_f = FunctionId(module="main", name="abs", ordinal=1)
	abs_int = FnSignature(
		name="abs",
		param_type_ids=[int_ty],
		return_type_id=int_ty,
		declared_can_throw=False,
	)
	abs_float = FnSignature(
		name="abs",
		param_type_ids=[float_ty],
		return_type_id=float_ty,
		declared_can_throw=False,
	)
	block = H.HBlock(
		statements=[
			H.HLet(
				name="f",
				value=H.HCast(
					target_type_expr=_fn_type_expr(["String"], "Int", nothrow=True),
					value=H.HVar("abs"),
				),
			),
		]
	)
	res = TypeChecker(table).check_function(
		FunctionId(module="main", name="main", ordinal=0),
		block,
		call_signatures={"abs": [abs_int, abs_float]},
		signatures_by_id={fn_id_abs_i: abs_int, fn_id_abs_f: abs_float},
	)
	assert any("cannot cast function 'abs'" in d.message and "no overload matches" in d.message for d in res.diagnostics)
	assert any("candidates:" in note for d in res.diagnostics for note in (d.notes or []))


def test_cast_function_reference_throw_mode_note() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	fn_id_abs_i = FunctionId(module="main", name="abs", ordinal=0)
	abs_int = FnSignature(
		name="abs",
		param_type_ids=[int_ty],
		return_type_id=int_ty,
		declared_can_throw=False,
	)
	block = H.HBlock(
		statements=[
			H.HLet(
				name="f",
				value=H.HCast(
					target_type_expr=_fn_type_expr(["Int"], "Int"),
					value=H.HVar("abs"),
				),
			),
		]
	)
	res = TypeChecker(table).check_function(
		FunctionId(module="main", name="main", ordinal=0),
		block,
		call_signatures={"abs": [abs_int]},
		signatures_by_id={fn_id_abs_i: abs_int},
	)
	assert any("throw-mode differs" in note for d in res.diagnostics for note in (d.notes or []))


def test_cast_rejects_non_function_target() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	fn_id_main = FunctionId(module="main", name="main", ordinal=0)
	block = H.HBlock(
		statements=[
			H.HLet(
				name="x",
				value=H.HCast(
					target_type_expr=TypeExpr(name="Int"),
					value=H.HLiteralInt(1),
				),
			),
		]
	)
	res = TypeChecker(table).check_function(
		fn_id_main,
		block,
		call_signatures={},
		signatures_by_id={},
	)
	assert any("cast<T>(...) is only supported for function types" in d.message for d in res.diagnostics)
