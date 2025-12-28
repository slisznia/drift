# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

import pytest

from lang2.driftc import stage1 as H
from lang2.driftc.checker import FnSignature
from lang2.driftc.core.function_id import FunctionId
from lang2.driftc.core.types_core import TypeTable, TypeKind
from lang2.driftc.stage1.call_info import CallInfo, CallSig, CallTarget, call_abi_ret_type
from lang2.driftc.stage1.node_ids import assign_node_ids
from lang2.driftc.stage2 import HIRToMIR, MirBuilder, Call, CallIndirect


def _fn_id(name: str) -> FunctionId:
	return FunctionId(module="main", name=name, ordinal=0)


def _lower(
	block: H.HBlock,
	*,
	call_info_by_node_id: dict[int, CallInfo] | None,
	type_table: TypeTable | None = None,
	signatures: dict[str, FnSignature] | None = None,
) -> HIRToMIR:
	builder = MirBuilder("test_func")
	table = type_table or TypeTable()
	hir_norm = block
	assign_node_ids(hir_norm)
	lower = HIRToMIR(
		builder,
		type_table=table,
		call_info_by_node_id=call_info_by_node_id,
		signatures=signatures or {},
	)
	lower.lower_block(hir_norm)
	return lower


def _call_info(
	*,
	fn_id: FunctionId,
	param_types: tuple[int, ...],
	return_type: int,
	can_throw: bool,
) -> CallInfo:
	return CallInfo(
		target=CallTarget.direct(fn_id),
		sig=CallSig(param_types=param_types, user_ret_type=return_type, can_throw=can_throw),
	)


def test_direct_call_requires_call_info() -> None:
	block = H.HBlock(statements=[H.HExprStmt(expr=H.HCall(fn=H.HVar("f"), args=[H.HLiteralInt(1)]))])
	assign_node_ids(block)
	with pytest.raises(AssertionError, match=r"missing call info for HCall node_id="):
		_lower(block, call_info_by_node_id={})


def test_method_call_requires_call_info() -> None:
	call = H.HMethodCall(receiver=H.HVar("obj"), method_name="m", args=[])
	block = H.HBlock(statements=[H.HExprStmt(expr=call)])
	assign_node_ids(block)
	with pytest.raises(AssertionError, match=r"missing call info for HMethodCall node_id="):
		_lower(block, call_info_by_node_id={})


def test_invoke_requires_call_info() -> None:
	call = H.HInvoke(callee=H.HVar("fp"), args=[H.HLiteralInt(1)])
	block = H.HBlock(statements=[H.HExprStmt(expr=call)])
	assign_node_ids(block)
	with pytest.raises(AssertionError, match=r"missing call info for HInvoke node_id="):
		_lower(block, call_info_by_node_id={})


def test_missing_call_info_in_control_flow_and_lambda() -> None:
	call_if = H.HCall(fn=H.HVar("f"), args=[H.HLiteralInt(1)])
	call_loop = H.HCall(fn=H.HVar("g"), args=[])
	call_inner = H.HCall(fn=H.HVar("h"), args=[])
	lam = H.HLambda(
		params=[],
		body_block=H.HBlock(
			statements=[
				H.HExprStmt(expr=call_inner),
				H.HReturn(value=H.HLiteralInt(0)),
			]
		),
	)
	block = H.HBlock(
		statements=[
			H.HIf(
				cond=H.HLiteralBool(True),
				then_block=H.HBlock(statements=[H.HExprStmt(expr=call_if)]),
				else_block=None,
			),
			H.HLoop(body=H.HBlock(statements=[H.HExprStmt(expr=call_loop), H.HBreak()])),
			H.HExprStmt(expr=H.HCall(fn=lam, args=[])),
		]
	)
	table = TypeTable()
	int_ty = table.ensure_int()
	assign_node_ids(block)
	call_info_by_node_id = {
		call_if.node_id: _call_info(fn_id=_fn_id("f"), param_types=(int_ty,), return_type=int_ty, can_throw=False),
		call_loop.node_id: _call_info(fn_id=_fn_id("g"), param_types=(), return_type=int_ty, can_throw=False),
	}
	with pytest.raises(AssertionError, match=rf"missing call info for HCall node_id={call_inner.node_id}"):
		_lower(block, call_info_by_node_id=call_info_by_node_id, type_table=table)


def test_direct_call_abi_return_types() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	block = H.HBlock(
		statements=[
			H.HExprStmt(expr=H.HCall(fn=H.HVar("may_throw"), args=[H.HLiteralInt(1)])),
			H.HExprStmt(expr=H.HCall(fn=H.HVar("nothrow"), args=[H.HLiteralInt(2)])),
		]
	)
	assign_node_ids(block)
	call_info_by_node_id = {}
	info_by_name = {}
	for stmt in block.statements:
		expr = getattr(stmt, "expr", None)
		if not isinstance(expr, H.HCall):
			continue
		is_throw = expr.fn.name == "may_throw"
		info = CallInfo(
			target=CallTarget.direct(_fn_id(expr.fn.name)),
			sig=CallSig(param_types=(int_ty,), user_ret_type=int_ty, can_throw=is_throw),
		)
		call_info_by_node_id[expr.node_id] = info
		info_by_name[expr.fn.name] = info
	builder = MirBuilder("test_func")
	lower = HIRToMIR(builder, type_table=table, call_info_by_node_id=call_info_by_node_id)
	lower.lower_block(block)
	calls = []
	for block in builder.func.blocks.values():
		for instr in block.instructions:
			if isinstance(instr, Call):
				calls.append(instr)
	assert len(calls) >= 2
	for instr in calls:
		ret_ty = lower._local_types.get(instr.dest)
		if instr.fn == "may_throw":
			assert ret_ty == call_abi_ret_type(info_by_name["may_throw"].sig, table)
			assert table.get(ret_ty).kind is TypeKind.FNRESULT
		elif instr.fn == "nothrow":
			assert ret_ty == int_ty


def test_call_abi_return_types_extended() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	void_ty = table.ensure_void()
	obj_init = H.HLet(name="obj", value=H.HLiteralInt(0))
	call_throw = H.HCall(fn=H.HVar("may_throw"), args=[H.HLiteralInt(1)])
	call_void = H.HCall(fn=H.HVar("nothrow_void"), args=[])
	call_throw_void = H.HCall(fn=H.HVar("may_throw_void"), args=[])
	call_inner = H.HCall(fn=H.HVar("inner"), args=[])
	call_outer = H.HCall(fn=H.HVar("outer"), args=[call_inner])
	method_call = H.HMethodCall(receiver=H.HVar("obj"), method_name="m", args=[])
	block = H.HBlock(
		statements=[
			obj_init,
			H.HExprStmt(expr=call_throw),
			H.HExprStmt(expr=call_void),
			H.HExprStmt(expr=call_throw_void),
			H.HExprStmt(expr=method_call),
			H.HExprStmt(expr=call_outer),
		]
	)
	assign_node_ids(block)
	call_info_by_node_id = {
		call_throw.node_id: _call_info(fn_id=_fn_id("may_throw"), param_types=(int_ty,), return_type=int_ty, can_throw=True),
		call_void.node_id: _call_info(fn_id=_fn_id("nothrow_void"), param_types=(), return_type=void_ty, can_throw=False),
		call_throw_void.node_id: _call_info(
			fn_id=_fn_id("may_throw_void"), param_types=(), return_type=void_ty, can_throw=True
		),
		call_inner.node_id: _call_info(fn_id=_fn_id("inner"), param_types=(), return_type=int_ty, can_throw=True),
		call_outer.node_id: _call_info(fn_id=_fn_id("outer"), param_types=(int_ty,), return_type=int_ty, can_throw=False),
		method_call.node_id: _call_info(
			fn_id=FunctionId(module="mod", name="m", ordinal=0),
			param_types=(int_ty,),
			return_type=int_ty,
			can_throw=True,
		),
	}
	signatures = {
		"mod::m": FnSignature(
			name="mod::m",
			method_name="m",
			param_type_ids=[int_ty],
			return_type_id=int_ty,
			is_method=True,
			self_mode="value",
		)
	}
	lower = _lower(
		block,
		call_info_by_node_id=call_info_by_node_id,
		type_table=table,
		signatures=signatures,
	)
	calls = []
	for b in lower.b.func.blocks.values():
		for instr in b.instructions:
			if isinstance(instr, Call):
				calls.append(instr)
	calls_by_fn = {instr.fn: instr for instr in calls}
	assert calls_by_fn["may_throw"].can_throw is True
	assert calls_by_fn["nothrow_void"].can_throw is False
	assert calls_by_fn["may_throw_void"].can_throw is True
	assert calls_by_fn["inner"].can_throw is True
	assert calls_by_fn["outer"].can_throw is False
	assert calls_by_fn["mod::m"].can_throw is True

	assert lower._local_types[calls_by_fn["may_throw"].dest] == call_abi_ret_type(
		call_info_by_node_id[call_throw.node_id].sig, table
	)
	assert lower._local_types[calls_by_fn["may_throw_void"].dest] == call_abi_ret_type(
		call_info_by_node_id[call_throw_void.node_id].sig, table
	)
	assert lower._local_types[calls_by_fn["inner"].dest] == call_abi_ret_type(
		call_info_by_node_id[call_inner.node_id].sig, table
	)
	assert lower._local_types[calls_by_fn["outer"].dest] == int_ty
	assert calls_by_fn["nothrow_void"].dest is None


def test_invoke_call_abi_return_types() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	void_ty = table.ensure_void()
	call_throw = H.HInvoke(callee=H.HVar("fp1"), args=[H.HLiteralInt(1)])
	call_void = H.HInvoke(callee=H.HVar("fp2"), args=[])
	block = H.HBlock(
		statements=[
			H.HExprStmt(expr=call_throw),
			H.HExprStmt(expr=call_void),
		]
	)
	assign_node_ids(block)
	call_info_by_node_id = {
		call_throw.node_id: CallInfo(
			target=CallTarget.indirect(call_throw.callee.node_id),
			sig=CallSig(param_types=(int_ty,), user_ret_type=int_ty, can_throw=True),
		),
		call_void.node_id: CallInfo(
			target=CallTarget.indirect(call_void.callee.node_id),
			sig=CallSig(param_types=(), user_ret_type=void_ty, can_throw=False),
		),
	}
	lower = _lower(block, call_info_by_node_id=call_info_by_node_id, type_table=table)
	calls = []
	for b in lower.b.func.blocks.values():
		for instr in b.instructions:
			if isinstance(instr, CallIndirect):
				calls.append(instr)
	assert len(calls) == 2
	for instr in calls:
		if instr.can_throw:
			assert lower._local_types[instr.dest] == call_abi_ret_type(
				call_info_by_node_id[call_throw.node_id].sig, table
			)
		else:
			assert instr.dest is None


def test_call_target_uses_canonical_symbol() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	obj_init = H.HLet(name="obj", value=H.HLiteralInt(0))
	free_call = H.HCall(fn=H.HVar("foo"), args=[H.HLiteralInt(1)])
	method_call = H.HMethodCall(receiver=H.HVar("obj"), method_name="m", args=[])
	block = H.HBlock(statements=[obj_init, H.HExprStmt(expr=free_call), H.HExprStmt(expr=method_call)])
	assign_node_ids(block)
	call_info_by_node_id = {
		free_call.node_id: _call_info(
			fn_id=FunctionId(module="mod", name="foo", ordinal=2),
			param_types=(int_ty,),
			return_type=int_ty,
			can_throw=False,
		),
		method_call.node_id: _call_info(
			fn_id=FunctionId(module="mod2", name="m", ordinal=1),
			param_types=(int_ty,),
			return_type=int_ty,
			can_throw=False,
		),
	}
	signatures = {
		"mod2::m#1": FnSignature(
			name="mod2::m#1",
			method_name="m",
			param_type_ids=[int_ty],
			return_type_id=int_ty,
			is_method=True,
			self_mode="value",
		)
	}
	lower = _lower(
		block,
		call_info_by_node_id=call_info_by_node_id,
		type_table=table,
		signatures=signatures,
	)
	call_targets = set()
	for b in lower.b.func.blocks.values():
		for instr in b.instructions:
			if isinstance(instr, Call):
				call_targets.add(instr.fn)
	assert "mod::foo#2" in call_targets
	assert "mod2::m#1" in call_targets
