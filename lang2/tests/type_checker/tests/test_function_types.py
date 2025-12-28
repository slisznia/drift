# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

"""Unit tests for the type checker (not Stage-1 pipeline validation)."""
#
# TODO(function-ptr): add Stage-1 NodeId/CallSig/CallTarget assertions once
# typed HIR carries stable ids.

from lang2.driftc import stage1 as H
from lang2.driftc.core.function_id import FunctionId
from lang2.driftc.core.types_core import TypeTable
from lang2.driftc.method_registry import CallableRegistry, CallableSignature, Visibility
from lang2.driftc.type_checker import TypeChecker


def _fn_id(name: str) -> FunctionId:
	return FunctionId(module="main", name=name, ordinal=0)


def test_pretty_function_type_name():
	table = TypeTable()
	tc = TypeChecker(table)
	int_ty = table.ensure_int()
	fn_nothrow = table.ensure_function("fn", [int_ty], int_ty, can_throw=False)
	fn_can_throw = table.ensure_function("fn", [int_ty], int_ty, can_throw=True)

	assert tc._pretty_type_name(fn_nothrow, current_module="main") == "fn(Int) returns Int nothrow"
	assert tc._pretty_type_name(fn_can_throw, current_module="main") == "fn(Int) returns Int"


def test_call_resolution_respects_function_throw_mode():
	table = TypeTable()
	tc = TypeChecker(table)
	int_ty = table.ensure_int()
	bool_ty = table.ensure_bool()
	fn_nothrow = table.ensure_function("fn", [int_ty], int_ty, can_throw=False)
	fn_can_throw = table.ensure_function("fn", [int_ty], int_ty, can_throw=True)

	registry = CallableRegistry()
	registry.register_free_function(
		callable_id=1,
		name="takes",
		module_id=0,
		visibility=Visibility.public(),
		signature=CallableSignature(param_types=(fn_nothrow,), result_type=bool_ty),
	)
	registry.register_free_function(
		callable_id=2,
		name="takes",
		module_id=0,
		visibility=Visibility.public(),
		signature=CallableSignature(param_types=(fn_can_throw,), result_type=int_ty),
	)

	call = H.HCall(fn=H.HVar("takes"), args=[H.HVar("g")])
	block = H.HBlock(statements=[H.HExprStmt(expr=call)])
	res = tc.check_function(
		_fn_id("caller"),
		block,
		param_types={"g": fn_nothrow},
		callable_registry=registry,
		visible_modules=(0,),
		current_module=0,
	)
	assert res.diagnostics == []
	resolutions = list(res.typed_fn.call_resolutions.values())
	assert len(resolutions) == 1
	assert resolutions[0].signature.result_type == bool_ty


def test_call_resolution_respects_function_throw_mode_can_throw():
	table = TypeTable()
	tc = TypeChecker(table)
	int_ty = table.ensure_int()
	bool_ty = table.ensure_bool()
	fn_nothrow = table.ensure_function("fn", [int_ty], int_ty, can_throw=False)
	fn_can_throw = table.ensure_function("fn", [int_ty], int_ty, can_throw=True)

	registry = CallableRegistry()
	registry.register_free_function(
		callable_id=1,
		name="takes",
		module_id=0,
		visibility=Visibility.public(),
		signature=CallableSignature(param_types=(fn_nothrow,), result_type=bool_ty),
	)
	registry.register_free_function(
		callable_id=2,
		name="takes",
		module_id=0,
		visibility=Visibility.public(),
		signature=CallableSignature(param_types=(fn_can_throw,), result_type=int_ty),
	)

	call = H.HCall(fn=H.HVar("takes"), args=[H.HVar("g")])
	block = H.HBlock(statements=[H.HExprStmt(expr=call)])
	res = tc.check_function(
		_fn_id("caller"),
		block,
		param_types={"g": fn_can_throw},
		callable_registry=registry,
		visible_modules=(0,),
		current_module=0,
	)
	assert res.diagnostics == []
	resolutions = list(res.typed_fn.call_resolutions.values())
	assert len(resolutions) == 1
	assert resolutions[0].signature.result_type == int_ty
