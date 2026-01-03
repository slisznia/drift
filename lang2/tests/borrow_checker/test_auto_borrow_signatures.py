#!/usr/bin/env python3
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-09
"""Signature-driven auto-borrow tests."""

from lang2.driftc import stage1 as H
from lang2.driftc.borrow_checker_pass import BorrowChecker
from lang2.driftc.borrow_checker import PlaceBase, PlaceKind
from lang2.driftc.checker import FnSignature
from lang2.driftc.core.function_id import FunctionId
from lang2.driftc.core.types_core import TypeTable, TypeId
from lang2.driftc.method_registry import CallableDecl, CallableSignature, CallableKind, Visibility, SelfMode
from lang2.driftc.method_resolver import MethodResolution
from lang2.driftc.stage1.node_ids import assign_node_ids


def _bc_with_sig(
	table: TypeTable, sig: FnSignature, *, fn_id: FunctionId | None = None, call_resolutions=None
):
	unk: TypeId = table.ensure_unknown()
	fn_types = {PlaceBase(PlaceKind.LOCAL, 1, "x"): unk}
	base_lookup = lambda hv: PlaceBase(
		PlaceKind.LOCAL,
		getattr(hv, "binding_id", -1) if getattr(hv, "binding_id", None) is not None else -1,
		hv.name if hasattr(hv, "name") else str(hv),
	)
	if fn_id is None:
		fn_id = FunctionId(module="main", name=sig.name, ordinal=0)
	return BorrowChecker(
		type_table=table,
		fn_types=fn_types,
		binding_types=None,
		base_lookup=base_lookup,
		enable_auto_borrow=True,
		signatures_by_id={fn_id: sig},
		call_resolutions=call_resolutions,
	)


def test_hcall_signature_driven_auto_borrow_prevents_move():
	# Without auto-borrow, the call would move x (Unknown is move-only) and the later use would be use-after-move.
	block = H.HBlock(
		statements=[
			H.HLet(name="x", value=H.HLiteralString("s"), declared_type_expr=None, binding_id=1),
			H.HExprStmt(expr=H.HCall(fn=H.HVar("foo"), args=[H.HVar("x", binding_id=1)])),
			H.HExprStmt(expr=H.HVar("x", binding_id=1)),
		]
	)
	table = TypeTable()
	ref_param = table.ensure_ref(table.ensure_unknown())
	ref_sig = FnSignature(name="foo", param_type_ids=[ref_param])
	fn_id = FunctionId(module="main", name="foo", ordinal=0)
	assign_node_ids(block)
	call_expr = block.statements[1].expr
	call_resolutions = {}
	if isinstance(call_expr, H.HCall):
		call_resolutions[call_expr.node_id] = CallableDecl(
			callable_id=1,
			name="foo",
			kind=CallableKind.FREE_FUNCTION,
			module_id=0,
			visibility=Visibility.public(),
			signature=CallableSignature(param_types=(ref_param,), result_type=table.ensure_unknown()),
			fn_id=fn_id,
		)
	diags = _bc_with_sig(table, ref_sig, fn_id=fn_id, call_resolutions=call_resolutions).check_block(block)
	assert diags == []


def test_hmethod_signature_driven_auto_borrow_prevents_move():
	table = TypeTable()
	recv_ref = table.ensure_ref(table.ensure_unknown())
	ref_sig = FnSignature(name="m", param_type_ids=[recv_ref])
	fn_id = FunctionId(module="main", name="m", ordinal=0)
	call_expr = H.HMethodCall(receiver=H.HVar("x", binding_id=1), method_name="m", args=[])
	block = H.HBlock(
		statements=[
			H.HLet(name="x", value=H.HLiteralString("s"), declared_type_expr=None, binding_id=1),
			H.HExprStmt(expr=call_expr),
			H.HExprStmt(expr=H.HVar("x", binding_id=1)),
		]
	)
	decl = CallableDecl(
		callable_id=1,
		name="m",
		kind=CallableKind.METHOD_INHERENT,
		module_id=0,
		visibility=Visibility.public(),
		signature=CallableSignature(param_types=(recv_ref,), result_type=table.ensure_unknown()),
		impl_id=1,
		impl_target_type_id=table.ensure_unknown(),
		self_mode=SelfMode.SELF_BY_REF,
		fn_id=fn_id,
	)
	assign_node_ids(block)
	call_resolutions = {call_expr.node_id: MethodResolution(decl=decl, receiver_autoborrow=SelfMode.SELF_BY_REF)}
	diags = _bc_with_sig(table, ref_sig, fn_id=fn_id, call_resolutions=call_resolutions).check_block(block)
	assert diags == []


def test_method_value_receiver_moves_and_later_use_errors():
	table = TypeTable()
	int_ty = table.ensure_int()
	call_expr = H.HMethodCall(receiver=H.HVar("x", binding_id=1), method_name="m", args=[])
	block = H.HBlock(
		statements=[
			H.HLet(name="x", value=H.HLiteralInt(1), declared_type_expr=None, binding_id=1),
			H.HExprStmt(expr=call_expr),
			H.HExprStmt(expr=H.HVar("x", binding_id=1)),
		]
	)
	fn_id = FunctionId(module="main", name="m", ordinal=0)
	decl = CallableDecl(
		callable_id=10,
		name="m",
		kind=CallableKind.METHOD_INHERENT,
		module_id=0,
		visibility=Visibility.public(),
		signature=CallableSignature(param_types=(int_ty,), result_type=int_ty),
		impl_id=10,
		impl_target_type_id=int_ty,
		self_mode=SelfMode.SELF_BY_VALUE,
		fn_id=fn_id,
	)
	assign_node_ids(block)
	call_resolutions = {call_expr.node_id: MethodResolution(decl=decl, receiver_autoborrow=None)}
	ref_sig = FnSignature(name="m", param_type_ids=[int_ty])
	diags = _bc_with_sig(table, ref_sig, fn_id=fn_id, call_resolutions=call_resolutions).check_block(block)
	assert diags
	assert any("use after move" in d.message for d in diags)
