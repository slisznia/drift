# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from lang2.driftc.core.diagnostics import Diagnostic
from lang2.driftc.core.function_id import FunctionId
from lang2.driftc.core.span import Span
from lang2.driftc.parser import ast as parser_ast


@dataclass(frozen=True)
class TraitKey:
	module: Optional[str]
	name: str


@dataclass(frozen=True)
class TypeKey:
	module: Optional[str]
	name: str
	args: Tuple["TypeKey", ...] = ()

	def head(self) -> "TypeHeadKey":
		return TypeHeadKey(module=self.module, name=self.name)


@dataclass(frozen=True)
class TypeHeadKey:
	module: Optional[str]
	name: str


@dataclass(frozen=True)
class FnKey:
	module: Optional[str]
	name: str


@dataclass
class TraitDef:
	key: TraitKey
	name: str
	methods: List[parser_ast.TraitMethodSig]
	require: Optional[parser_ast.TraitExpr]
	loc: Optional[object] = None


@dataclass
class ImplDef:
	trait: TraitKey
	target: TypeKey
	target_head: TypeHeadKey
	methods: List[parser_ast.FunctionDef]
	require: Optional[parser_ast.TraitExpr]
	loc: Optional[object] = None


@dataclass
class TraitWorld:
	traits: Dict[TraitKey, TraitDef] = field(default_factory=dict)
	impls: List[ImplDef] = field(default_factory=list)
	impls_by_trait: Dict[TraitKey, List[int]] = field(default_factory=dict)
	impls_by_target_head: Dict[TypeHeadKey, List[int]] = field(default_factory=dict)
	impls_by_trait_target: Dict[Tuple[TraitKey, TypeHeadKey], List[int]] = field(default_factory=dict)
	requires_by_struct: Dict[TypeKey, parser_ast.TraitExpr] = field(default_factory=dict)
	requires_by_fn: Dict[FunctionId, parser_ast.TraitExpr] = field(default_factory=dict)
	diagnostics: List[Diagnostic] = field(default_factory=list)


def _qual_from_type_expr(typ: parser_ast.TypeExpr) -> Optional[str]:
	return getattr(typ, "module_id", None) or getattr(typ, "module_alias", None)


def type_key_from_expr(typ: parser_ast.TypeExpr, *, default_module: Optional[str] = None) -> TypeKey:
	return TypeKey(
		module=_qual_from_type_expr(typ) or default_module,
		name=typ.name,
		args=tuple(type_key_from_expr(a, default_module=default_module) for a in getattr(typ, "args", []) or []),
	)


def type_key_from_typeid(type_table: object, tid: int) -> TypeKey:
	td = type_table.get(tid)
	args = tuple(type_key_from_typeid(type_table, t) for t in getattr(td, "param_types", []) or [])
	return TypeKey(module=getattr(td, "module_id", None), name=getattr(td, "name", ""), args=args)


def trait_key_from_expr(typ: parser_ast.TypeExpr, *, default_module: Optional[str] = None) -> TraitKey:
	return TraitKey(module=_qual_from_type_expr(typ) or default_module, name=typ.name)


def _type_key_str(key: TypeKey | TypeHeadKey) -> str:
	module = getattr(key, "module", None)
	name = getattr(key, "name", "")
	base = f"{module}.{name}" if module else name
	if isinstance(key, TypeKey) and key.args:
		args = ", ".join(_type_key_str(a) for a in key.args)
		return f"{base}<{args}>"
	return base


def _trait_key_str(key: TraitKey) -> str:
	return f"{key.module}.{key.name}" if key.module else key.name


def _diag(message: str, loc: object | None) -> Diagnostic:
	return Diagnostic(message=message, severity="error", span=Span.from_loc(loc))


def _collect_trait_is(expr: parser_ast.TraitExpr) -> List[parser_ast.TraitIs]:
	out: List[parser_ast.TraitIs] = []
	if isinstance(expr, parser_ast.TraitIs):
		out.append(expr)
	elif isinstance(expr, (parser_ast.TraitAnd, parser_ast.TraitOr)):
		out.extend(_collect_trait_is(expr.left))
		out.extend(_collect_trait_is(expr.right))
	elif isinstance(expr, parser_ast.TraitNot):
		out.extend(_collect_trait_is(expr.expr))
	return out


def build_trait_world(prog: parser_ast.Program, *, diagnostics: Optional[List[Diagnostic]] = None) -> TraitWorld:
	diags: List[Diagnostic] = list(diagnostics or [])
	world = TraitWorld(diagnostics=diags)
	module_id = getattr(prog, "module", None) or "main"

	# Collect trait declarations.
	method_seen: Dict[Tuple[TraitKey, str], object | None] = {}
	for tr in getattr(prog, "traits", []) or []:
		key = TraitKey(module=module_id, name=tr.name)
		if key in world.traits:
			world.diagnostics.append(_diag(f"duplicate trait definition '{_trait_key_str(key)}'", tr.loc))
			continue
		require_expr = getattr(tr, "require", None).expr if getattr(tr, "require", None) is not None else None
		world.traits[key] = TraitDef(
			key=key,
			name=tr.name,
			methods=list(getattr(tr, "methods", []) or []),
			require=require_expr,
			loc=getattr(tr, "loc", None),
		)
		if require_expr is not None:
			for atom in _collect_trait_is(require_expr):
				if atom.subject != "Self":
					world.diagnostics.append(
						_diag("trait require clause must use 'Self is Trait'", getattr(atom, "loc", None))
					)
					continue
				trait_key = trait_key_from_expr(atom.trait, default_module=module_id)
				if trait_key not in world.traits:
					world.diagnostics.append(
						_diag(
							f"unknown trait '{_trait_key_str(trait_key)}' in require clause",
							getattr(atom, "loc", None),
						)
					)
		for m in getattr(tr, "methods", []) or []:
			mkey = (key, m.name)
			if mkey in method_seen:
				world.diagnostics.append(
					_diag(
						f"duplicate method '{m.name}' in trait '{_trait_key_str(key)}'",
						getattr(m, "loc", None),
					)
				)
			else:
				method_seen[mkey] = getattr(m, "loc", None)

	# Collect require clauses for structs and functions.
	for s in getattr(prog, "structs", []) or []:
		if getattr(s, "require", None) is None:
			continue
		type_key = TypeKey(module=module_id, name=s.name, args=())
		req_expr = s.require.expr
		world.requires_by_struct[type_key] = req_expr
		for atom in _collect_trait_is(req_expr):
			if atom.subject == "Self":
				trait_key = trait_key_from_expr(atom.trait, default_module=module_id)
				if trait_key not in world.traits:
					world.diagnostics.append(
						_diag(
							f"unknown trait '{_trait_key_str(trait_key)}' in require clause",
							getattr(atom, "loc", None),
						)
					)
			else:
				world.diagnostics.append(
					_diag("require clause on struct must use 'Self is Trait'", getattr(atom, "loc", None))
				)

	name_ord: Dict[str, int] = {}
	for fn in getattr(prog, "functions", []) or []:
		ordinal = name_ord.get(fn.name, 0)
		name_ord[fn.name] = ordinal + 1
		if getattr(fn, "require", None) is None:
			continue
		req_expr = fn.require.expr
		fn_id = FunctionId(module=module_id, name=fn.name, ordinal=ordinal)
		world.requires_by_fn[fn_id] = req_expr
		for atom in _collect_trait_is(req_expr):
			if atom.subject == "Self":
				world.diagnostics.append(
					_diag("function require clause cannot use 'Self'", getattr(atom, "loc", None))
				)
				continue
			trait_key = trait_key_from_expr(atom.trait, default_module=module_id)
			if trait_key not in world.traits:
				world.diagnostics.append(
					_diag(
						f"unknown trait '{_trait_key_str(trait_key)}' in require clause",
						getattr(atom, "loc", None),
					)
				)

	# Collect impls (trait impls only).
	for impl in getattr(prog, "implements", []) or []:
		if getattr(impl, "trait", None) is None:
			continue
		trait_key = trait_key_from_expr(impl.trait, default_module=module_id)
		if trait_key not in world.traits:
			world.diagnostics.append(
				_diag(f"unknown trait '{_trait_key_str(trait_key)}' in implement block", getattr(impl, "loc", None))
			)
			continue
		target_key = type_key_from_expr(impl.target, default_module=module_id)
		head_key = target_key.head()
		req_expr = impl.require.expr if getattr(impl, "require", None) is not None else None
		impl_id = len(world.impls)
		world.impls.append(
			ImplDef(
				trait=trait_key,
				target=target_key,
				target_head=head_key,
				methods=list(getattr(impl, "methods", []) or []),
				require=req_expr,
				loc=getattr(impl, "loc", None),
			)
		)
		world.impls_by_trait.setdefault(trait_key, []).append(impl_id)
		world.impls_by_target_head.setdefault(head_key, []).append(impl_id)
		world.impls_by_trait_target.setdefault((trait_key, head_key), []).append(impl_id)
		if req_expr is not None:
			for atom in _collect_trait_is(req_expr):
				trait_dep = trait_key_from_expr(atom.trait, default_module=module_id)
				if trait_dep not in world.traits:
					world.diagnostics.append(
						_diag(
							f"unknown trait '{_trait_key_str(trait_dep)}' in require clause",
							getattr(atom, "loc", None),
						)
					)

	# Coherence/overlap checks.
	for (trait_key, head_key), impl_ids in world.impls_by_trait_target.items():
		if len(impl_ids) <= 1:
			continue
		first = world.impls[impl_ids[0]]
		for other_id in impl_ids[1:]:
			other = world.impls[other_id]
			if other.target == first.target:
				msg = f"duplicate impl for trait '{_trait_key_str(trait_key)}' on '{_type_key_str(head_key)}'"
			else:
				msg = f"overlapping impls for trait '{_trait_key_str(trait_key)}' on '{_type_key_str(head_key)}'"
			world.diagnostics.append(_diag(msg, other.loc))

	return world


__all__ = [
	"TraitWorld",
	"TraitKey",
	"TypeKey",
	"TypeHeadKey",
	"ImplDef",
	"TraitDef",
	"FnKey",
	"build_trait_world",
	"type_key_from_typeid",
]
