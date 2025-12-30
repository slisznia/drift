# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

from lang2.driftc import stage1 as H
from lang2.driftc.checker import FnSignature
from lang2.driftc.core.function_id import FunctionId
from lang2.driftc.core.types_core import TypeTable, TypeKind
from lang2.driftc.parser import parse_drift_to_hir
from lang2.driftc.stage1.call_info import CallTargetKind, call_abi_ret_type
from lang2.driftc.stage1.node_ids import assign_node_ids
from lang2.driftc.type_checker import TypeChecker


def _write_file(path: Path, content: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content)


def _dump_node_ids(block: H.HBlock) -> list[str]:
	assign_node_ids(block)
	nodes: list[tuple[int, str]] = []

	def walk(obj: object) -> None:
		if isinstance(obj, H.HNode):
			nodes.append((obj.node_id, type(obj).__name__))
		for field in getattr(obj, "__dataclass_fields__", {}) or {}:
			val = getattr(obj, field, None)
			if isinstance(val, list):
				for item in val:
					walk(item)
			else:
				walk(val)

	walk(block)
	nodes.sort(key=lambda pair: pair[0])
	return [f"{nid}:{name}" for nid, name in nodes]


def _collect_node_ids(block: H.HBlock) -> set[int]:
	assign_node_ids(block)
	ids: set[int] = set()

	def walk(obj: object) -> None:
		if isinstance(obj, H.HNode):
			ids.add(obj.node_id)
		for field in getattr(obj, "__dataclass_fields__", {}) or {}:
			val = getattr(obj, field, None)
			if isinstance(val, list):
				for item in val:
					walk(item)
			else:
				walk(val)

	walk(block)
	return ids


def _collect_direct_calls(block: H.HBlock) -> list[H.HCall]:
	calls: list[H.HCall] = []

	def walk_expr(expr: H.HExpr) -> None:
		if isinstance(expr, H.HCall):
			calls.append(expr)
			walk_expr(expr.fn)
			for arg in expr.args:
				walk_expr(arg)
			for kw in getattr(expr, "kwargs", []) or []:
				if getattr(kw, "value", None) is not None:
					walk_expr(kw.value)
			return
		for child in getattr(expr, "__dict__", {}).values():
			if isinstance(child, H.HExpr):
				walk_expr(child)
			elif isinstance(child, H.HBlock):
				walk_block(child)
			elif isinstance(child, list):
				for it in child:
					if isinstance(it, H.HExpr):
						walk_expr(it)
					elif isinstance(it, H.HBlock):
						walk_block(it)

	def walk_block(b: H.HBlock) -> None:
		for st in b.statements:
			if isinstance(st, H.HExprStmt):
				walk_expr(st.expr)
			elif isinstance(st, H.HReturn) and st.value is not None:
				walk_expr(st.value)
			else:
				for child in getattr(st, "__dict__", {}).values():
					if isinstance(child, H.HExpr):
						walk_expr(child)
					elif isinstance(child, H.HBlock):
						walk_block(child)
					elif isinstance(child, list):
						for it in child:
							if isinstance(it, H.HExpr):
								walk_expr(it)
							elif isinstance(it, H.HBlock):
								walk_block(it)

	walk_block(block)
	return [c for c in calls if isinstance(c.fn, H.HVar)]


def _collect_invokes(block: H.HBlock) -> list[H.HInvoke]:
	invokes: list[H.HInvoke] = []

	def walk_expr(expr: H.HExpr) -> None:
		if isinstance(expr, H.HInvoke):
			invokes.append(expr)
			walk_expr(expr.callee)
			for arg in expr.args:
				walk_expr(arg)
			for kw in getattr(expr, "kwargs", []) or []:
				if getattr(kw, "value", None) is not None:
					walk_expr(kw.value)
			return
		for child in getattr(expr, "__dict__", {}).values():
			if isinstance(child, H.HExpr):
				walk_expr(child)
			elif isinstance(child, H.HBlock):
				walk_block(child)
			elif isinstance(child, list):
				for it in child:
					if isinstance(it, H.HExpr):
						walk_expr(it)
					elif isinstance(it, H.HBlock):
						walk_block(it)

	def walk_block(b: H.HBlock) -> None:
		for st in b.statements:
			if isinstance(st, H.HExprStmt):
				walk_expr(st.expr)
			elif isinstance(st, H.HReturn) and st.value is not None:
				walk_expr(st.value)
			else:
				for child in getattr(st, "__dict__", {}).values():
					if isinstance(child, H.HExpr):
						walk_expr(child)
					elif isinstance(child, H.HBlock):
						walk_block(child)
					elif isinstance(child, list):
						for it in child:
							if isinstance(it, H.HExpr):
								walk_expr(it)
							elif isinstance(it, H.HBlock):
								walk_block(it)

	walk_block(block)
	return invokes


def test_node_ids_deterministic(tmp_path: Path) -> None:
	path = tmp_path / "main.drift"
	_write_file(
		path,
		"""
fn foo(x: Int) returns Int { return x + 1; }
fn bar() returns Int { return foo(1) + foo(2); }
""",
	)
	funcs1, _sigs1, _fn_ids1, _table1, _excs1, _diags1 = parse_drift_to_hir(path)
	funcs2, _sigs2, _fn_ids2, _table2, _excs2, _diags2 = parse_drift_to_hir(path)
	block1 = next(iter(funcs1.values()))
	block2 = next(iter(funcs2.values()))
	assert _dump_node_ids(block1) == _dump_node_ids(block2)


def test_typed_tables_keyed_by_node_id() -> None:
	table = TypeTable()
	tc = TypeChecker(table)
	int_ty = table.ensure_int()
	block = H.HBlock(
		statements=[
			H.HLet(name="x", value=H.HLiteralInt(1), binding_id=1),
			H.HExprStmt(expr=H.HCall(fn=H.HVar("f"), args=[H.HVar("x", binding_id=1)])),
		]
	)
	fn_id = FunctionId(module="main", name="main", ordinal=0)
	sig = FnSignature(name="f", param_type_ids=[int_ty], return_type_id=int_ty, declared_can_throw=False)
	res = tc.check_function(fn_id, block, call_signatures={"f": [sig]})
	node_ids = _collect_node_ids(block)
	for key in res.typed_fn.expr_types.keys():
		assert key in node_ids
	for key in res.typed_fn.binding_for_var.keys():
		assert key in node_ids
	for key in res.typed_fn.call_resolutions.keys():
		assert key in node_ids
	for key in res.typed_fn.call_info_by_node_id.keys():
		assert key in node_ids


def test_call_info_emitted_for_direct_calls() -> None:
	table = TypeTable()
	tc = TypeChecker(table)
	int_ty = table.ensure_int()
	block = H.HBlock(
		statements=[
			H.HExprStmt(expr=H.HCall(fn=H.HVar("abs"), args=[H.HLiteralInt(1)])),
			H.HExprStmt(
				expr=H.HCall(
					fn=H.HVar("foo"),
					args=[H.HCall(fn=H.HVar("bar"), args=[H.HLiteralInt(2)])],
				)
			),
		]
	)
	fn_id = FunctionId(module="main", name="main", ordinal=0)
	signatures = {
		"abs": [FnSignature(name="abs", param_type_ids=[int_ty], return_type_id=int_ty, declared_can_throw=False)],
		"foo": [FnSignature(name="foo", param_type_ids=[int_ty], return_type_id=int_ty, declared_can_throw=False)],
		"bar": [FnSignature(name="bar", param_type_ids=[int_ty], return_type_id=int_ty, declared_can_throw=False)],
	}
	res = tc.check_function(fn_id, block, call_signatures=signatures)
	calls = _collect_direct_calls(block)
	assert calls
	for call in calls:
		info = res.typed_fn.call_info_by_node_id.get(call.node_id)
		assert info is not None
		assert info.target.kind is CallTargetKind.DIRECT
		assert info.target.symbol


def test_call_info_emitted_for_invoke() -> None:
	table = TypeTable()
	tc = TypeChecker(table)
	int_ty = table.ensure_int()
	fn_ty = table.ensure_function("fn", [int_ty], int_ty, can_throw=False)
	block = H.HBlock(
		statements=[
			H.HExprStmt(expr=H.HInvoke(callee=H.HVar("fp"), args=[H.HLiteralInt(1)])),
		]
	)
	fn_id = FunctionId(module="main", name="main", ordinal=0)
	res = tc.check_function(fn_id, block, param_types={"fp": fn_ty})
	invokes = _collect_invokes(block)
	assert invokes
	for call in invokes:
		info = res.typed_fn.call_info_by_node_id.get(call.node_id)
		assert info is not None
		assert info.target.kind is CallTargetKind.INDIRECT


def test_invoke_rejects_kwargs() -> None:
	table = TypeTable()
	tc = TypeChecker(table)
	int_ty = table.ensure_int()
	fn_ty = table.ensure_function("fn", [int_ty], int_ty, can_throw=False)
	call = H.HInvoke(
		callee=H.HVar("fp"),
		args=[],
		kwargs=[H.HKwArg(name="x", value=H.HLiteralInt(1))],
	)
	block = H.HBlock(statements=[H.HExprStmt(expr=call)])
	fn_id = FunctionId(module="main", name="main", ordinal=0)
	res = tc.check_function(fn_id, block, param_types={"fp": fn_ty})
	assert res.diagnostics


def test_call_sig_abi_return_type() -> None:
	table = TypeTable()
	tc = TypeChecker(table)
	int_ty = table.ensure_int()
	fn_id = FunctionId(module="main", name="main", ordinal=0)
	block = H.HBlock(
		statements=[
			H.HExprStmt(expr=H.HCall(fn=H.HVar("nothrow"), args=[H.HLiteralInt(1)])),
			H.HExprStmt(expr=H.HCall(fn=H.HVar("may_throw"), args=[H.HLiteralInt(2)])),
		]
	)
	signatures = {
		"nothrow": [FnSignature(name="nothrow", param_type_ids=[int_ty], return_type_id=int_ty, declared_can_throw=False)],
		"may_throw": [FnSignature(name="may_throw", param_type_ids=[int_ty], return_type_id=int_ty, declared_can_throw=True)],
	}
	res = tc.check_function(fn_id, block, call_signatures=signatures)
	calls = {call.fn.name: call for call in _collect_direct_calls(block)}
	info_no = res.typed_fn.call_info_by_node_id[calls["nothrow"].node_id]
	info_yes = res.typed_fn.call_info_by_node_id[calls["may_throw"].node_id]
	assert call_abi_ret_type(info_no.sig, table) == int_ty
	abi_yes = call_abi_ret_type(info_yes.sig, table)
	assert table.get(abi_yes).kind is TypeKind.FNRESULT
	assert abi_yes == table.ensure_fnresult(int_ty, table.ensure_error())
