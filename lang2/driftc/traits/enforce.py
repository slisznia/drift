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
from lang2.driftc.core.types_core import TypeKind, TypeParamId
from lang2.driftc.traits.world import TraitWorld, TypeKey, normalize_type_key, type_key_from_typeid
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
		ty_norm = normalize_type_key(ty, module_name=module_name)
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
	trait_worlds: Dict[str, TraitWorld],
	typed_fn: object,
	type_table: object,
	*,
	module_name: str,
	signatures: Dict[FunctionId, object],
) -> TraitEnforceResult:
	diags: List[Diagnostic] = []
	exprs: List[H.HExpr] = []
	_walk_block(getattr(typed_fn, "body"), exprs)
	expr_types = getattr(typed_fn, "expr_types", {})
	call_resolutions = getattr(typed_fn, "call_resolutions", {}) or {}
	seen: Set[Tuple[FunctionId, Tuple[TypeKey, ...], Tuple[TypeKey, ...]]] = set()
	symbol_to_id = {function_symbol(fid): fid for fid in signatures.keys()}

	def _infer_type_args_from_call(sig: object, arg_type_ids: List[object]) -> Dict[TypeParamId, object] | None:
		type_params = list(getattr(sig, "type_params", []) or [])
		if not type_params:
			return {}
		param_types = list(getattr(sig, "param_type_ids", []) or [])
		if not param_types or len(param_types) != len(arg_type_ids):
			return None
		owner = type_params[0].id.owner
		bindings: Dict[TypeParamId, object] = {}

		def _bind(tp_id: TypeParamId, actual: object) -> bool:
			if tp_id.owner != owner:
				return False
			cur = bindings.get(tp_id)
			if cur is None:
				bindings[tp_id] = actual
				return True
			return cur == actual

		def _unify(param: object, actual: object) -> bool:
			if param == actual:
				return True
			pdef = type_table.get(param)
			if pdef.kind is TypeKind.TYPEVAR and pdef.type_param_id is not None:
				return _bind(pdef.type_param_id, actual)
			adef = type_table.get(actual)
			if pdef.kind is not adef.kind:
				return False
			if pdef.kind is TypeKind.REF:
				if pdef.ref_mut != adef.ref_mut or not pdef.param_types or not adef.param_types:
					return False
				return _unify(pdef.param_types[0], adef.param_types[0])
			if pdef.kind in (TypeKind.ARRAY, TypeKind.OPTIONAL, TypeKind.FNRESULT, TypeKind.FUNCTION):
				if len(pdef.param_types) != len(adef.param_types):
					return False
				return all(_unify(p, a) for p, a in zip(pdef.param_types, adef.param_types))
			if pdef.kind is TypeKind.STRUCT:
				pinst = type_table.get_struct_instance(param)
				ainst = type_table.get_struct_instance(actual)
				if pinst is None and ainst is None:
					return param == actual
				if pinst is None or ainst is None or pinst.base_id != ainst.base_id:
					return False
				if len(pinst.type_args) != len(ainst.type_args):
					return False
				return all(_unify(p, a) for p, a in zip(pinst.type_args, ainst.type_args))
			if pdef.kind is TypeKind.VARIANT:
				pinst = type_table.get_variant_instance(param)
				ainst = type_table.get_variant_instance(actual)
				if pinst is None and ainst is None:
					return param == actual
				if pinst is None or ainst is None or pinst.base_id != ainst.base_id:
					return False
				if len(pinst.type_args) != len(ainst.type_args):
					return False
				return all(_unify(p, a) for p, a in zip(pinst.type_args, ainst.type_args))
			return False

		for p, a in zip(param_types, arg_type_ids):
			if not _unify(p, a):
				return None

		for tp in type_params:
			if tp.id not in bindings:
				return None
		return bindings

	for expr in exprs:
		if not isinstance(expr, H.HCall) or not isinstance(expr.fn, H.HVar):
			continue
		decl_name = expr.fn.name
		resolution = call_resolutions.get(expr.node_id)
		if isinstance(resolution, MethodResolution):
			# Trait requires are currently declared on free functions only.
			continue
		fn_id = getattr(resolution, "fn_id", None)
		if fn_id is None:
			fn_id = symbol_to_id.get(decl_name)
		if fn_id is None:
			continue
		callee_mod = getattr(fn_id, "module", None) or module_name
		world = trait_worlds.get(callee_mod)
		if world is None:
			continue
		req = world.requires_by_fn.get(fn_id)
		if req is None:
			continue
		env = Env(default_module=callee_mod)
		sig = signatures.get(fn_id)
		subst: Dict[object, TypeKey] = {}
		subjects: Set[object] = set()
		_collect_trait_subjects(req, subjects)
		arg_keys: List[TypeKey] = []
		type_arg_keys: List[TypeKey] = []
		arg_type_ids: List[object] = []
		for arg in expr.args:
			tid = expr_types.get(arg.node_id)
			if tid is None:
				continue
			arg_type_ids.append(tid)
			arg_keys.append(normalize_type_key(type_key_from_typeid(type_table, tid), module_name=module_name))
		if sig and getattr(sig, "type_params", None):
			type_params = list(getattr(sig, "type_params", []) or [])
			type_args = getattr(expr, "type_args", None) or []
			bindings: Dict[TypeParamId, object] | None = None
			if type_args and len(type_args) == len(type_params):
				bindings = {}
				for idx, tp in enumerate(type_params):
					ty_id = resolve_opaque_type(type_args[idx], type_table, module_id=module_name)
					bindings[tp.id] = ty_id
			else:
				bindings = _infer_type_args_from_call(sig, arg_type_ids)
			if bindings:
				for tp_id, ty_id in bindings.items():
					if tp_id in subjects:
						subst[tp_id] = normalize_type_key(type_key_from_typeid(type_table, ty_id), module_name=module_name)
				for tp in type_params:
					ty_id = bindings.get(tp.id)
					if ty_id is None:
						continue
					type_arg_keys.append(normalize_type_key(type_key_from_typeid(type_table, ty_id), module_name=module_name))
			if getattr(sig, "param_names", None):
				for idx, pname in enumerate(sig.param_names or []):
					if pname in subjects and idx < len(arg_keys):
						subst[pname] = arg_keys[idx]
		seen_key = (fn_id, tuple(arg_keys), tuple(type_arg_keys))
		if seen_key in seen:
			continue
		seen.add(seen_key)
		res = prove_expr(world, env, subst, req)
		if res.status is not ProofStatus.PROVED:
			diags.append(
				Diagnostic(
					message=f"trait requirements not met for call to '{expr.fn.name}'",
					code="E_REQUIREMENT_NOT_SATISFIED",
					severity="error",
					span=getattr(expr, "loc", Span()),
				)
			)
	return TraitEnforceResult(diags)
