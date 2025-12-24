# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple

from lang2.driftc.parser import ast as parser_ast
from .world import TraitWorld, TraitKey, TypeKey, ImplDef, trait_key_from_expr


class ProofStatus(Enum):
	PROVED = auto()
	REFUTED = auto()
	UNKNOWN = auto()
	AMBIGUOUS = auto()


@dataclass
class ProofResult:
	status: ProofStatus
	reasons: List[str] = field(default_factory=list)
	used_impls: List[int] = field(default_factory=list)


@dataclass
class Env:
	assumed_true: Set[Tuple[object, TraitKey]] = field(default_factory=set)
	assumed_false: Set[Tuple[object, TraitKey]] = field(default_factory=set)
	default_module: Optional[str] = None


CacheKey = Tuple[object, str, Optional[TypeKey]]


def _type_key_str(key: TypeKey) -> str:
	module = key.module
	base = f"{module}.{key.name}" if module else key.name
	if not key.args:
		return base
	args = ", ".join(_type_key_str(a) for a in key.args)
	return f"{base}<{args}>"


def _trait_key_str(key: TraitKey) -> str:
	return f"{key.module}.{key.name}" if key.module else key.name


def _impl_sort_key(impl: ImplDef) -> Tuple[str, str, int, int]:
	trait_str = _trait_key_str(impl.trait)
	target_str = _type_key_str(impl.target)
	loc = getattr(impl.loc, "loc", None) if hasattr(impl.loc, "loc") else impl.loc
	line = getattr(loc, "line", 0) or 0
	col = getattr(loc, "column", 0) or 0
	return (trait_str, target_str, line, col)


def prove_expr(
	world: TraitWorld,
	env: Env,
	subst: Dict[object, TypeKey],
	expr: parser_ast.TraitExpr,
	*,
	_cache: Optional[Dict[CacheKey, ProofResult]] = None,
	_in_progress: Optional[Set[Tuple[str, TraitKey, Optional[TypeKey]]]] = None,
) -> ProofResult:
	if isinstance(expr, parser_ast.TraitIs):
		trait_key = trait_key_from_expr(expr.trait, default_module=env.default_module)
		return prove_is(world, env, subst, expr.subject, trait_key, _cache=_cache, _in_progress=_in_progress)
	if isinstance(expr, parser_ast.TraitAnd):
		left = prove_expr(world, env, subst, expr.left, _cache=_cache, _in_progress=_in_progress)
		if left.status is ProofStatus.REFUTED:
			return left
		right = prove_expr(world, env, subst, expr.right, _cache=_cache, _in_progress=_in_progress)
		if right.status is ProofStatus.REFUTED:
			return right
		if left.status is ProofStatus.UNKNOWN or right.status is ProofStatus.UNKNOWN:
			return ProofResult(status=ProofStatus.UNKNOWN, reasons=left.reasons + right.reasons)
		if left.status is ProofStatus.AMBIGUOUS or right.status is ProofStatus.AMBIGUOUS:
			return ProofResult(status=ProofStatus.AMBIGUOUS, reasons=left.reasons + right.reasons)
		return ProofResult(status=ProofStatus.PROVED, reasons=left.reasons + right.reasons, used_impls=left.used_impls + right.used_impls)
	if isinstance(expr, parser_ast.TraitOr):
		left = prove_expr(world, env, subst, expr.left, _cache=_cache, _in_progress=_in_progress)
		right = prove_expr(world, env, subst, expr.right, _cache=_cache, _in_progress=_in_progress)
		if left.status is ProofStatus.PROVED and right.status is ProofStatus.PROVED:
			return ProofResult(status=ProofStatus.PROVED, reasons=left.reasons + right.reasons, used_impls=left.used_impls + right.used_impls)
		if left.status is ProofStatus.PROVED:
			return left
		if right.status is ProofStatus.PROVED:
			return right
		if left.status is ProofStatus.REFUTED and right.status is ProofStatus.REFUTED:
			return ProofResult(status=ProofStatus.REFUTED, reasons=left.reasons + right.reasons)
		if left.status is ProofStatus.AMBIGUOUS or right.status is ProofStatus.AMBIGUOUS:
			return ProofResult(status=ProofStatus.AMBIGUOUS, reasons=left.reasons + right.reasons)
		return ProofResult(status=ProofStatus.UNKNOWN, reasons=left.reasons + right.reasons)
	if isinstance(expr, parser_ast.TraitNot):
		return deny_expr(world, env, subst, expr.expr, _cache=_cache, _in_progress=_in_progress)
	return ProofResult(status=ProofStatus.UNKNOWN, reasons=["unsupported trait expression"])


def deny_expr(
	world: TraitWorld,
	env: Env,
	subst: Dict[object, TypeKey],
	expr: parser_ast.TraitExpr,
	*,
	_cache: Optional[Dict[CacheKey, ProofResult]] = None,
	_in_progress: Optional[Set[Tuple[str, TraitKey, Optional[TypeKey]]]] = None,
) -> ProofResult:
	if isinstance(expr, parser_ast.TraitIs):
		trait_key = trait_key_from_expr(expr.trait, default_module=env.default_module)
		res = prove_is(world, env, subst, expr.subject, trait_key, _cache=_cache, _in_progress=_in_progress)
		if res.status is ProofStatus.PROVED:
			return ProofResult(status=ProofStatus.REFUTED, reasons=res.reasons)
		if res.status is ProofStatus.REFUTED:
			return ProofResult(status=ProofStatus.PROVED, reasons=res.reasons)
		return ProofResult(status=ProofStatus.UNKNOWN, reasons=res.reasons)
	if isinstance(expr, parser_ast.TraitAnd):
		left = deny_expr(world, env, subst, expr.left, _cache=_cache, _in_progress=_in_progress)
		right = deny_expr(world, env, subst, expr.right, _cache=_cache, _in_progress=_in_progress)
		if left.status is ProofStatus.PROVED or right.status is ProofStatus.PROVED:
			return ProofResult(status=ProofStatus.PROVED, reasons=left.reasons + right.reasons)
		if left.status is ProofStatus.REFUTED and right.status is ProofStatus.REFUTED:
			return ProofResult(status=ProofStatus.REFUTED, reasons=left.reasons + right.reasons)
		return ProofResult(status=ProofStatus.UNKNOWN, reasons=left.reasons + right.reasons)
	if isinstance(expr, parser_ast.TraitOr):
		left = deny_expr(world, env, subst, expr.left, _cache=_cache, _in_progress=_in_progress)
		if left.status is ProofStatus.REFUTED:
			return left
		right = deny_expr(world, env, subst, expr.right, _cache=_cache, _in_progress=_in_progress)
		if right.status is ProofStatus.REFUTED:
			return right
		if left.status is ProofStatus.UNKNOWN or right.status is ProofStatus.UNKNOWN:
			return ProofResult(status=ProofStatus.UNKNOWN, reasons=left.reasons + right.reasons)
		return ProofResult(status=ProofStatus.PROVED, reasons=left.reasons + right.reasons)
	if isinstance(expr, parser_ast.TraitNot):
		return prove_expr(world, env, subst, expr.expr, _cache=_cache, _in_progress=_in_progress)
	return ProofResult(status=ProofStatus.UNKNOWN, reasons=["unsupported trait expression"])


def prove_is(
	world: TraitWorld,
	env: Env,
	subst: Dict[object, TypeKey],
	subject: object,
	trait_key: TraitKey,
	*,
	_cache: Optional[Dict[CacheKey, ProofResult]] = None,
	_in_progress: Optional[Set[Tuple[str, TraitKey, Optional[TypeKey]]]] = None,
) -> ProofResult:
	cache = _cache if _cache is not None else {}
	in_progress = _in_progress if _in_progress is not None else set()
	subject_ty = subst.get(subject)
	cache_key: CacheKey = (subject, _trait_key_str(trait_key), subject_ty)
	if cache_key in cache:
		return cache[cache_key]
	if (subject, trait_key) in env.assumed_true:
		res = ProofResult(status=ProofStatus.PROVED, reasons=["assumed true"])
		cache[cache_key] = res
		return res
	if (subject, trait_key) in env.assumed_false:
		res = ProofResult(status=ProofStatus.REFUTED, reasons=["assumed false"])
		cache[cache_key] = res
		return res
	if subject_ty is None:
		res = ProofResult(status=ProofStatus.UNKNOWN, reasons=["unknown subject type"])
		cache[cache_key] = res
		return res
	if trait_key not in world.traits:
		res = ProofResult(status=ProofStatus.REFUTED, reasons=["unknown trait"])
		cache[cache_key] = res
		return res

	cycle_key = (subject, trait_key, subject_ty)
	if cycle_key in in_progress:
		res = ProofResult(status=ProofStatus.UNKNOWN, reasons=["cycle in trait requirements"])
		cache[cache_key] = res
		return res
	in_progress.add(cycle_key)
	try:
		head = subject_ty.head()
		candidates = world.impls_by_trait_target.get((trait_key, head), [])
		ordered = [(impl_id, world.impls[impl_id]) for impl_id in candidates]
		ordered.sort(key=lambda item: (_impl_sort_key(item[1]), item[0]))

		applicable: List[int] = []
		reasons: List[str] = []
		for impl_id, impl in ordered:
			if impl.target != subject_ty:
				continue
			if impl.require is not None:
				req = prove_expr(world, env, subst, impl.require, _cache=cache, _in_progress=in_progress)
				if req.status is ProofStatus.PROVED:
					applicable.append(impl_id)
					continue
				if req.status is ProofStatus.AMBIGUOUS:
					reasons.append("ambiguous impl requirement")
					continue
				if req.status is ProofStatus.UNKNOWN:
					reasons.append("impl requirement unknown")
					continue
				reasons.append("impl requirement refuted")
				continue
			applicable.append(impl_id)

		if len(applicable) == 0:
			res = ProofResult(status=ProofStatus.REFUTED, reasons=reasons or ["no applicable impls"])
		elif len(applicable) == 1:
			res = ProofResult(status=ProofStatus.PROVED, used_impls=applicable)
		else:
			res = ProofResult(status=ProofStatus.AMBIGUOUS, reasons=["multiple applicable impls"], used_impls=applicable)
		cache[cache_key] = res
		return res
	finally:
		in_progress.remove(cycle_key)


__all__ = ["Env", "ProofResult", "ProofStatus", "prove_expr", "prove_is", "deny_expr", "CacheKey"]
