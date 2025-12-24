# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from lang2.driftc.core.diagnostics import Diagnostic
from lang2.driftc.core.span import Span
from lang2.driftc import stage1 as H
from lang2.driftc.parser import ast as parser_ast
from lang2.driftc.method_resolver import MethodResolution
from lang2.driftc.traits.solver import Env, ProofStatus, prove_expr
from lang2.driftc.core.function_id import FunctionId, function_symbol
from lang2.driftc.traits.world import TraitWorld, TypeKey, type_key_from_typeid
from lang2.driftc.core.type_resolve_common import resolve_opaque_type


@dataclass
class TraitEnforceResult:
	diagnostics: List[Diagnostic]


def _collect_exprs(expr: H.HExpr, out: List[H.HExpr]) -> None:
	out.append(expr)
	for field in getattr(expr, "__dataclass_fields__", {}) or {}:
		val = getattr(expr, field, None)
		if isinstance(val, H.HExpr):
			_collect_exprs(val, out)
		elif isinstance(val, list):
			for item in val:
				if isinstance(item, H.HExpr):
					_collect_exprs(item, out)


def _walk_block(block: H.HBlock, out: List[H.HExpr]) -> None:
	for stmt in block.statements:
		if isinstance(stmt, H.HExprStmt):
			_collect_exprs(stmt.expr, out)
		elif isinstance(stmt, H.HLet):
			_collect_exprs(stmt.value, out)
		elif isinstance(stmt, H.HAssign):
			_collect_exprs(stmt.value, out)
		elif isinstance(stmt, H.HAugAssign):
			_collect_exprs(stmt.value, out)
		elif isinstance(stmt, H.HIf):
			if isinstance(stmt.cond, H.HExpr):
				_collect_exprs(stmt.cond, out)
			_walk_block(stmt.then_block, out)
			if stmt.else_block:
				_walk_block(stmt.else_block, out)
		elif isinstance(stmt, H.HLoop):
			_walk_block(stmt.body, out)
		elif isinstance(stmt, H.HTry):
			_walk_block(stmt.body, out)
			for arm in stmt.catches:
				_walk_block(arm.block, out)
		elif isinstance(stmt, H.HReturn) and stmt.value is not None:
			_collect_exprs(stmt.value, out)


def collect_used_type_keys(
	typed_fns: Dict[FunctionId, object],
	type_table: object,
	signatures: Dict[FunctionId, object],
) -> Set[TypeKey]:
	used: Set[TypeKey] = set()
	for sig in signatures.values():
		for tid in getattr(sig, "param_type_ids", []) or []:
			if tid is None:
				continue
			used.add(type_key_from_typeid(type_table, tid))
		ret = getattr(sig, "return_type_id", None)
		if ret is not None:
			used.add(type_key_from_typeid(type_table, ret))
	for typed_fn in typed_fns.values():
		for tid in getattr(typed_fn, "binding_types", {}).values():
			if tid is None:
				continue
			used.add(type_key_from_typeid(type_table, tid))
		for tid in getattr(typed_fn, "expr_types", {}).values():
			if tid is None:
				continue
			used.add(type_key_from_typeid(type_table, tid))
	return used


def _normalize_type_key(key: TypeKey, *, module_name: str) -> TypeKey:
	if key.module is None:
		return TypeKey(module=module_name, name=key.name, args=key.args)
	return key


def _collect_trait_subjects(expr: parser_ast.TraitExpr, out: Set[object]) -> None:
	if isinstance(expr, parser_ast.TraitIs):
		out.add(expr.subject)
	elif isinstance(expr, (parser_ast.TraitAnd, parser_ast.TraitOr)):
		_collect_trait_subjects(expr.left, out)
		_collect_trait_subjects(expr.right, out)
	elif isinstance(expr, parser_ast.TraitNot):
		_collect_trait_subjects(expr.expr, out)


def enforce_struct_requires(
	world: TraitWorld,
	used_types: Iterable[TypeKey],
	*,
	module_name: str,
) -> TraitEnforceResult:
	diags: List[Diagnostic] = []
	env = Env(default_module=module_name)
	for ty in used_types:
		ty_norm = _normalize_type_key(ty, module_name=module_name)
		req = world.requires_by_struct.get(ty_norm)
		if req is None:
			continue
		subst = {"Self": ty_norm}
		res = prove_expr(world, env, subst, req)
		if res.status is not ProofStatus.PROVED:
			diags.append(
				Diagnostic(
					message=f"trait requirements not met for struct '{ty.name}'",
					severity="error",
					span=Span.from_loc(getattr(req, "loc", None)),
				)
			)
	return TraitEnforceResult(diags)


def enforce_fn_requires(
	world: TraitWorld,
	typed_fn: object,
	type_table: object,
	*,
	module_name: str,
	signatures: Dict[FunctionId, object],
) -> TraitEnforceResult:
	diags: List[Diagnostic] = []
	env = Env(default_module=module_name)
	exprs: List[H.HExpr] = []
	_walk_block(getattr(typed_fn, "body"), exprs)
	expr_types = getattr(typed_fn, "expr_types", {})
	call_resolutions = getattr(typed_fn, "call_resolutions", {}) or {}
	seen: Set[Tuple[FunctionId, Tuple[TypeKey, ...]]] = set()
	symbol_to_id = {function_symbol(fid): fid for fid in signatures.keys()}
	for expr in exprs:
		if not isinstance(expr, H.HCall) or not isinstance(expr.fn, H.HVar):
			continue
		decl_name = expr.fn.name
		resolution = call_resolutions.get(id(expr))
		if isinstance(resolution, MethodResolution):
			# Trait requires are currently declared on free functions only.
			continue
		fn_id = getattr(resolution, "fn_id", None)
		if fn_id is None:
			fn_id = symbol_to_id.get(decl_name)
		if fn_id is None:
			continue
		req = world.requires_by_fn.get(fn_id)
		if req is None:
			continue
		sig = signatures.get(fn_id)
		subst: Dict[object, TypeKey] = {}
		subjects: Set[object] = set()
		_collect_trait_subjects(req, subjects)
		arg_keys: List[TypeKey] = []
		for arg in expr.args:
			tid = expr_types.get(id(arg))
			if tid is None:
				continue
			arg_keys.append(_normalize_type_key(type_key_from_typeid(type_table, tid), module_name=module_name))
		if sig and getattr(sig, "type_params", None):
			type_params = list(getattr(sig, "type_params", []) or [])
			type_args = getattr(expr, "type_args", None) or []
			if type_args and len(type_args) == len(type_params):
				for idx, tp in enumerate(type_params):
					if tp.id in subjects:
						ty_id = resolve_opaque_type(type_args[idx], type_table, module_id=module_name)
						subst[tp.id] = _normalize_type_key(type_key_from_typeid(type_table, ty_id), module_name=module_name)
		subst_key = tuple(arg_keys)
		seen_key = (fn_id, subst_key)
		if seen_key in seen:
			continue
		seen.add(seen_key)
		res = prove_expr(world, env, subst, req)
		if res.status is not ProofStatus.PROVED:
			diags.append(
				Diagnostic(
					message=f"trait requirements not met for call to '{expr.fn.name}'",
					severity="error",
					span=getattr(expr, "loc", Span()),
				)
			)
	return TraitEnforceResult(diags)
