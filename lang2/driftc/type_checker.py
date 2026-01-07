#!/usr/bin/env python3
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-09
"""
Minimal typed checker skeleton for lang2.

This is a real checker scaffold that:
- Allocates ParamId/LocalId/BindingId for bindings.
- Infers types for basic expressions (literals, vars, lets, borrows, calls).
- Produces a TypedFn record with expression TypeIds and binding identity.

It is intentionally small; it will grow to cover full Drift semantics. Borrow
checker integration will consume TypedFn once this matures.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace, fields, is_dataclass
from enum import Enum, auto
from typing import Dict, List, Optional, Mapping, Tuple

from lang2.driftc import stage1 as H
from lang2.driftc.stage1.call_info import CallInfo, CallSig, CallTarget, IntrinsicKind
from lang2.driftc.stage1.node_ids import assign_node_ids
from lang2.driftc.stage1.capture_discovery import discover_captures
from lang2.driftc.stage1.place_expr import place_expr_from_lvalue_expr
from lang2.driftc.checker import FnSignature, TypeParam
from lang2.driftc.core.diagnostics import Diagnostic


# Typecheck diagnostics should always carry phase.

FIXED_WIDTH_TYPE_NAMES = {
	"Int8",
	"Int16",
	"Int32",
	"Int64",
	"Uint8",
	"Uint16",
	"Uint32",
	"Uint64",
	"u64",
	"F32",
	"F64",
	"Float32",
	"Float64",
}
def _tc_diag(*args, **kwargs):
	if "phase" not in kwargs:
		if len(args) >= 3:
			args = list(args)
			if args[2] is None:
				args[2] = "typecheck"
			return Diagnostic(*args, **kwargs)
		kwargs["phase"] = "typecheck"
	elif kwargs.get("phase") is None:
		kwargs["phase"] = "typecheck"
	return Diagnostic(*args, **kwargs)

from lang2.driftc.core.span import Span
from lang2.driftc.core.types_core import (
	TypeId,
	TypeTable,
	TypeKind,
	VariantInstance,
	VariantSchema,
	TypeParamId,
	VariantArmSchema,
	VariantFieldSchema,
)
from lang2.driftc.core.function_id import (
	FunctionId,
	FunctionRefId,
	FunctionRefKind,
	FnNameKey,
	fn_name_key,
	function_symbol,
)
from lang2.driftc.core.function_key import FunctionKey
from lang2.driftc.core.type_resolve_common import resolve_opaque_type
from lang2.driftc.core.type_subst import Subst, apply_subst
from lang2.driftc.core.generic_type_expr import GenericTypeExpr
from lang2.driftc.borrow_checker import (
	DerefProj,
	FieldProj,
	IndexProj,
	Place,
	PlaceBase,
	PlaceKind,
	place_from_expr,
	places_overlap,
)
from lang2.driftc.method_registry import CallableDecl, CallableKind, CallableRegistry, CallableSignature, ModuleId, SelfMode, Visibility
from lang2.driftc.impl_index import GlobalImplIndex
from lang2.driftc.infer import (
	InferConstraint,
	InferConstraintOrigin,
	InferBindingEvidence,
	InferConflictEvidence,
	InferContext,
	InferError,
	InferErrorKind,
	InferResult,
	InferTrace,
	format_infer_failure,
)
from lang2.driftc.trait_index import GlobalTraitImplIndex, GlobalTraitIndex, TraitImplCandidate
from lang2.driftc.traits.world import (
	TraitKey,
	TraitWorld,
	TypeKey,
	normalize_type_key,
	trait_key_from_expr,
	type_key_from_typeid,
)
from lang2.driftc.traits.linked_world import (
	LinkedWorld,
	RequireEnv,
	BOOL_TRUE,
)
from lang2.driftc.method_resolver import MethodResolution, ResolutionError, resolve_method_call
from lang2.driftc.core.iter_intrinsics import ensure_array_iter_struct, is_array_iter_struct
from lang2.driftc.parser import ast as parser_ast
from lang2.driftc.traits.solver import (
	Env as TraitEnv,
	Obligation,
	ObligationOrigin,
	ObligationOriginKind,
	ProofFailure,
	ProofFailureReason,
	ProofStatus,
	prove_expr,
	prove_obligation,
)

# Identifier aliases for clarity.
ParamId = int
LocalId = int
GuardKey = int
DeferredGuardKey = Tuple[GuardKey, str]


@dataclass
class TypedFn:
	"""Typed view of a single function's HIR."""

	fn_id: FunctionId
	name: str
	params: List[ParamId]
	param_bindings: List[int]
	locals: List[LocalId]
	body: H.HBlock
	expr_types: Dict[int, TypeId]  # keyed by node_id
	binding_for_var: Dict[int, int]  # keyed by node_id
	binding_types: Dict[int, TypeId]  # binding_id -> TypeId
	binding_names: Dict[int, str]  # binding_id -> name
	binding_mutable: Dict[int, bool]  # binding_id -> declared var?
	binding_place_kind: Dict[int, PlaceKind] = field(default_factory=dict)  # binding_id -> place kind
	call_resolutions: Dict[int, CallableDecl | MethodResolution] = field(default_factory=dict)
	call_info_by_callsite_id: Dict[int, "CallInfo"] = field(default_factory=dict)
	instantiations_by_callsite_id: Dict[int, "CallInstantiation"] = field(default_factory=dict)


@dataclass(frozen=True)
class CallInstantiation:
	"""Resolved instantiation info for a call-site."""

	target_key: FunctionKey
	type_args: Tuple[TypeId, ...]


@dataclass
class TypeCheckResult:
	"""Result of type checking a function."""

	typed_fn: TypedFn
	diagnostics: List[Diagnostic] = field(default_factory=list)
	deferred_guard_diags: Dict[DeferredGuardKey, List[Diagnostic]] = field(default_factory=dict)
	guard_outcomes: Dict[GuardKey, ProofStatus] = field(default_factory=dict)


class ThunkKind(Enum):
	OK_WRAP = auto()
	BOUNDARY = auto()


@dataclass
class ThunkSpec:
	"""Synthetic thunk for function value lowering."""

	thunk_fn_id: FunctionId
	target_fn_id: FunctionId
	param_types: tuple[TypeId, ...]
	return_type: TypeId
	kind: ThunkKind


@dataclass(frozen=True)
class LambdaFnSpec:
	"""Synthetic function for a captureless lambda coerced to a fn pointer."""

	fn_id: FunctionId
	origin_fn_id: FunctionId | None
	lambda_expr: "H.HLambda"
	param_types: tuple[TypeId, ...]
	return_type: TypeId
	can_throw: bool
	call_info_by_callsite_id: dict[int, "CallInfo"]


class TypeChecker:
	"""
	Minimal HIR type checker that assigns binding IDs and basic types.

	This is a skeleton: it understands literals, vars, lets, borrows, calls, and
	a small set of builtin constructs (f-strings, exceptions, DiagnosticValue
	helpers).
	"""

	def __init__(self, type_table: Optional[TypeTable] = None):
		self.type_table = type_table or TypeTable()
		self._uint = self.type_table.ensure_uint()
		self._uint64 = self.type_table.ensure_uint64()
		self._int = self.type_table.ensure_int()
		self._float = self.type_table.ensure_float()
		self._bool = self.type_table.ensure_bool()
		self._string = self.type_table.ensure_string()
		self._void = self.type_table.ensure_void()
		self._error = self.type_table.ensure_error()
		self._dv = self.type_table.ensure_diagnostic_value()
		self._unknown = self.type_table.ensure_unknown()
		self._thunk_specs: dict[tuple[ThunkKind, FunctionId, tuple[TypeId, ...], TypeId], ThunkSpec] = {}
		self._lambda_fn_specs: dict[FunctionId, LambdaFnSpec] = {}
		# Binding ids (params and locals) share a single id-space.
		self._next_binding_id: int = 1
		self._defaulted_phase_count: int = 0

	def _stamp_diag_phase(self, diag: Diagnostic) -> None:
		if diag.phase is None:
			diag.phase = "typecheck"
			self._defaulted_phase_count += 1

	def defaulted_phase_count(self) -> int:
		return self._defaulted_phase_count

	def _optional_variant_type(self, inner_ty: TypeId) -> TypeId:
		opt_base = self.type_table.ensure_optional_base()
		return self.type_table.ensure_instantiated(opt_base, [inner_ty])

	def thunk_specs(self) -> list[ThunkSpec]:
		return list(self._thunk_specs.values())

	def lambda_fn_specs(self) -> list[LambdaFnSpec]:
		return list(self._lambda_fn_specs.values())

	def _pretty_type_name(self, ty: TypeId, *, current_module: str | None) -> str:
		"""
		Render a user-facing type name for diagnostics.

		This is intentionally small: enough for MVP error messages without
		committing to a full surface type renderer.
		"""
		td = self.type_table.get(ty)
		name = td.name
		if td.module_id and current_module and td.module_id not in {current_module, "lang.core"}:
			name = f"{td.module_id}.{name}"
		if td.kind is TypeKind.FUNCTION:
			param_types = list(td.param_types[:-1]) if td.param_types else []
			ret_type = td.param_types[-1] if td.param_types else self._unknown
			params = ", ".join(self._pretty_type_name(t, current_module=current_module) for t in param_types)
			ret = self._pretty_type_name(ret_type, current_module=current_module)
			if td.can_throw():
				return f"Fn({params}) -> {ret}"
			return f"Fn({params}) nothrow -> {ret}"
		if td.param_types:
			args = ", ".join(self._pretty_type_name(t, current_module=current_module) for t in td.param_types)
			return f"{name}<{args}>"
		return name

	def _seed_binding_id_counter(self, body: H.HBlock) -> None:
		"""
		Ensure new binding ids won't collide with ids already present in HIR.

		Stage1 may assign binding ids during parsing/normalization. The type
		checker also allocates ids for temps introduced in later rewrites (e.g.
		borrow materialization). We must avoid reusing ids that already appear in
		the input HIR.
		"""
		max_id = 0

		def bump(obj: object) -> None:
			nonlocal max_id
			bid = getattr(obj, "binding_id", None)
			if isinstance(bid, int) and bid > max_id:
				max_id = bid

		def walk_expr(expr: H.HExpr) -> None:
			bump(expr)
			if isinstance(expr, H.HVar):
				return
			if isinstance(expr, H.HUnary):
				walk_expr(expr.expr)
				return
			if isinstance(expr, H.HBinary):
				walk_expr(expr.left)
				walk_expr(expr.right)
				return
			if isinstance(expr, H.HTernary):
				walk_expr(expr.cond)
				walk_expr(expr.then_expr)
				walk_expr(expr.else_expr)
				return
			if isinstance(expr, H.HBorrow):
				walk_expr(expr.subject)
				return
			if isinstance(expr, getattr(H, "HMove", ())):
				walk_expr(expr.subject)
				return
			if isinstance(expr, getattr(H, "HCopy", ())):
				walk_expr(expr.subject)
				return
			if isinstance(expr, H.HCall):
				walk_expr(expr.fn)
				for arg in expr.args:
					walk_expr(arg)
				for kw in getattr(expr, "kwargs", []) or []:
					walk_expr(kw.value)
				return
			if isinstance(expr, getattr(H, "HInvoke", ())):
				walk_expr(expr.callee)
				for arg in expr.args:
					walk_expr(arg)
				for kw in getattr(expr, "kwargs", []) or []:
					walk_expr(kw.value)
				return
			if isinstance(expr, getattr(H, "HTypeApp", ())):
				walk_expr(expr.fn)
				return
			if isinstance(expr, H.HMethodCall):
				walk_expr(expr.receiver)
				for arg in expr.args:
					walk_expr(arg)
				for kw in getattr(expr, "kwargs", []) or []:
					walk_expr(kw.value)
				return
			if isinstance(expr, H.HField):
				walk_expr(expr.subject)
				return
			if isinstance(expr, H.HIndex):
				walk_expr(expr.subject)
				walk_expr(expr.index)
				return
			if isinstance(expr, getattr(H, "HPlaceExpr", ())):
				bump(expr.base)
				for proj in expr.projections:
					if isinstance(proj, H.HPlaceIndex):
						walk_expr(proj.index)
				return
			if isinstance(expr, H.HArrayLiteral):
				for elem in expr.elements:
					walk_expr(elem)
				return
			if isinstance(expr, H.HFString):
				for hole in expr.holes:
					walk_expr(hole.expr)
				return
			if isinstance(expr, H.HLambda):
				for param in expr.params:
					bump(param)
				for cap in expr.explicit_captures or []:
					bump(cap)
				if expr.body_expr is not None:
					walk_expr(expr.body_expr)
				if expr.body_block is not None:
					walk_block(expr.body_block)
				return
			if isinstance(expr, H.HResultOk):
				walk_expr(expr.value)
				return
			if isinstance(expr, H.HTryExpr):
				walk_expr(expr.attempt)
				for arm in expr.arms:
					walk_block(arm.block)
					if arm.result is not None:
						walk_expr(arm.result)
				return
			if isinstance(expr, H.HMatchExpr):
				walk_expr(expr.scrutinee)
				for arm in expr.arms:
					walk_block(arm.block)
					if arm.result is not None:
						walk_expr(arm.result)
				return

		def walk_stmt(stmt: H.HStmt) -> None:
			bump(stmt)
			if isinstance(stmt, H.HLet):
				walk_expr(stmt.value)
				return
			if isinstance(stmt, H.HAssign):
				walk_expr(stmt.target)
				walk_expr(stmt.value)
				return
			if hasattr(H, "HAugAssign") and isinstance(stmt, getattr(H, "HAugAssign")):
				walk_expr(stmt.target)
				walk_expr(stmt.value)
				return
			if isinstance(stmt, H.HExprStmt):
				walk_expr(stmt.expr)
				return
			if isinstance(stmt, H.HReturn):
				if stmt.value is not None:
					walk_expr(stmt.value)
				return
			if isinstance(stmt, H.HIf):
				walk_expr(stmt.cond)
				walk_block(stmt.then_block)
				if stmt.else_block is not None:
					walk_block(stmt.else_block)
				return
			if isinstance(stmt, H.HLoop):
				walk_block(stmt.body)
				return
			if isinstance(stmt, H.HBlock):
				walk_block(stmt)
				return
			if isinstance(stmt, H.HTry):
				walk_block(stmt.body)
				for arm in stmt.catches:
					walk_block(arm.block)
				return
			if isinstance(stmt, H.HThrow):
				walk_expr(stmt.value)
				return

		def walk_block(block: H.HBlock) -> None:
			for stmt in block.statements:
				walk_stmt(stmt)

		walk_block(body)
		self._next_binding_id = max_id + 1

	def _format_ctor_signature_list(
		self,
		*,
		schema: VariantSchema,
		instance: VariantInstance | None,
		current_module: str | None,
	) -> list[str]:
		"""
		Return a stable, user-facing list of constructor “signatures”.

		Pinned formatting rules (MVP):
		- Sort by constructor name, then arity.
		- Render as: `CtorName(arg1, arg2)` with no extra spaces.
		- If a payload type is unknown/unrenderable, show `_`.

		When `instance` is available we prefer concrete field types; otherwise we
		fall back to schema generic expressions (`T`, `Array<T>`, etc.).
		"""

		def _render_generic(g: GenericTypeExpr) -> str:
			if g.param_index is not None:
				idx = int(g.param_index)
				if 0 <= idx < len(schema.type_params):
					return schema.type_params[idx]
				return "_"
			name = g.name
			args = list(g.args or [])
			if not args:
				return name
			return f"{name}<{', '.join(_render_generic(a) for a in args)}>"

		arms = sorted(schema.arms, key=lambda a: (a.name, len(a.fields)))
		out: list[str] = []
		for arm in arms:
			field_parts: list[str] = []
			if instance is not None:
				inst_arm = instance.arms_by_name.get(arm.name)
				if inst_arm is not None:
					for ft in inst_arm.field_types:
						field_parts.append(self._pretty_type_name(ft, current_module=current_module))
			if not field_parts:
				for f in arm.fields:
					field_parts.append(_render_generic(f.type_expr))
			out.append(f"`{arm.name}({', '.join(field_parts)})`")
		return out

	def check_function(
		self,
		fn_id: FunctionId,
		body: H.HBlock,
		param_types: Mapping[str, TypeId] | None = None,
		param_mutable: Mapping[str, bool] | None = None,
		return_type: TypeId | None = None,
		preseed_binding_types: Mapping[int, TypeId] | None = None,
		preseed_binding_names: Mapping[int, str] | None = None,
		preseed_binding_mutable: Mapping[int, bool] | None = None,
		preseed_binding_place_kind: Mapping[int, PlaceKind] | None = None,
		preseed_scope_env: Mapping[str, TypeId] | None = None,
		preseed_scope_bindings: Mapping[str, int] | None = None,
		signatures_by_id: Mapping[FunctionId, FnSignature] | None = None,
		function_keys_by_fn_id: Mapping[FunctionId, FunctionKey] | None = None,
		callable_registry: CallableRegistry | None = None,
		impl_index: GlobalImplIndex | None = None,
		trait_index: GlobalTraitIndex | None = None,
		trait_impl_index: GlobalTraitImplIndex | None = None,
		trait_scope_by_module: Mapping[str, list[TraitKey]] | None = None,
		linked_world: LinkedWorld | None = None,
		require_env: RequireEnv | None = None,
		visible_modules: Optional[Tuple[ModuleId, ...]] = None,
		current_module: ModuleId = 0,
		visibility_provenance: Mapping[ModuleId, tuple[str, ...]] | None = None,
		visibility_imports: set[str] | None = None,
	) -> TypeCheckResult:
		# Best-effort current module id in canonical string form.
		#
		# This is required for correct module-scoped nominal type resolution
		# (e.g., `Point(...)` inside module `a.geom` must refer to `a.geom:Point`
		# even if another module also defines `Point`).
		current_module_name: str | None = None
		current_module_name = fn_id.module or "main"
		def _fixed_width_allowed(module_name: str | None) -> bool:
			if module_name is None:
				return False
			return module_name.startswith("lang.abi.")

		def _reject_fixed_width_type_expr(raw: object, module_name: str | None, span: Span | None) -> bool:
			# Return True if a fixed-width type was rejected.
			if raw is None:
				return False
			name = None
			args = None
			if hasattr(raw, "name") and hasattr(raw, "args"):
				name = getattr(raw, "name", None)
				args = getattr(raw, "args", None)
			elif isinstance(raw, str):
				name = raw
				args = None
			if name in FIXED_WIDTH_TYPE_NAMES and not _fixed_width_allowed(module_name):
				diagnostics.append(
					_tc_diag(
						message=f"fixed-width type '{name}' is reserved in v1; use Int/Uint/Float or Byte",
						code="E_FIXED_WIDTH_RESERVED",
						severity="error",
						span=span or Span(),
					)
				)
				return True
			if args:
				for arg in list(args):
					if _reject_fixed_width_type_expr(arg, module_name, span):
						return True
			return False
		visibility_provenance = visibility_provenance or {}
		visibility_imports = visibility_imports if visibility_imports is not None else None
		self._seed_binding_id_counter(body)
		if preseed_binding_types:
			max_preseed = max(preseed_binding_types)
			if self._next_binding_id <= max_preseed:
				self._next_binding_id = max_preseed + 1
		if callable_registry is not None:
			has_call = False
			has_callsite = False

			def _scan_expr(expr: H.HExpr) -> None:
				nonlocal has_call, has_callsite
				if isinstance(expr, (H.HCall, H.HMethodCall, H.HInvoke)):
					has_call = True
					if isinstance(getattr(expr, "callsite_id", None), int):
						has_callsite = True
				if isinstance(expr, H.HCall) and isinstance(expr.fn, H.HLambda):
					lam = expr.fn
					if getattr(lam, "body_expr", None) is not None:
						_scan_expr(lam.body_expr)
					if getattr(lam, "body_block", None) is not None:
						_scan_block(lam.body_block)
				for child in getattr(expr, "__dict__", {}).values():
					if isinstance(child, H.HExpr):
						_scan_expr(child)
					elif isinstance(child, H.HBlock):
						_scan_block(child)
					elif isinstance(child, list):
						for it in child:
							if isinstance(it, H.HExpr):
								_scan_expr(it)
							elif isinstance(it, H.HBlock):
								_scan_block(it)

			def _scan_block(block: H.HBlock) -> None:
				for st in block.statements:
					if isinstance(st, H.HExprStmt):
						_scan_expr(st.expr)
					elif isinstance(st, H.HReturn) and st.value is not None:
						_scan_expr(st.value)
					else:
						for child in getattr(st, "__dict__", {}).values():
							if isinstance(child, H.HExpr):
								_scan_expr(child)
							elif isinstance(child, H.HBlock):
								_scan_block(child)
							elif isinstance(child, list):
								for it in child:
									if isinstance(it, H.HExpr):
										_scan_expr(it)
									elif isinstance(it, H.HBlock):
										_scan_block(it)

			_scan_block(body)
			if has_call and not has_callsite:
				H.assign_callsite_ids(body)

		def _format_visibility_chain(chain: tuple[str, ...], max_hops: int = 4) -> str:
			if not chain:
				return "<unknown>"
			if len(chain) == 1:
				return f"{chain[0]} (self)"
			nodes = list(chain)
			if len(nodes) - 1 > max_hops:
				nodes = list(chain[: max_hops + 1])
				nodes.append("...")
			parts = [nodes[0]]
			for idx in range(1, len(nodes)):
				if idx == 1:
					if visibility_imports is None:
						label = "visible->"
					else:
						label = "import->" if nodes[idx] in visibility_imports else "reexport->"
				else:
					label = "reexport->"
				parts.append(f"{label} {nodes[idx]}")
			return " ".join(parts)

		def _visibility_note(module_id: ModuleId) -> str | None:
			chain = visibility_provenance.get(module_id)
			if not chain:
				return None
			return f"visible via: {_format_visibility_chain(chain)}"

		module_ids_by_name: dict[str, ModuleId] = {}
		for mod_id, chain in visibility_provenance.items():
			if chain:
				module_ids_by_name.setdefault(chain[-1], mod_id)
		prelude_module_id = module_ids_by_name.get("lang.core")

		def _visible_modules_for_free_call(module_name: str | None) -> tuple[ModuleId, ...]:
			if module_name is not None:
				mod_id = module_ids_by_name.get(module_name)
				if mod_id is not None:
					return (mod_id,)
				# When no provenance map exists (unit-test harness), fall back to
				# the provided visible module set instead of hard-failing.
				if not visibility_provenance:
					return tuple(visible_modules or (current_module,))
				return ()
			modules = [current_module]
			if prelude_module_id is not None and prelude_module_id != current_module:
				modules.append(prelude_module_id)
			return tuple(modules)

		next_node_id = assign_node_ids(body)
		def _assign_node_id(node: H.HNode) -> None:
			nonlocal next_node_id
			if getattr(node, "node_id", 0):
				return
			if is_dataclass(node) and getattr(node, "__dataclass_params__", None) and node.__dataclass_params__.frozen:
				object.__setattr__(node, "node_id", next_node_id)
			else:
				node.node_id = next_node_id
			next_node_id += 1

		def _assign_place_expr_ids(place_expr: H.HPlaceExpr) -> None:
			_assign_node_id(place_expr)
			for proj in place_expr.projections:
				_assign_node_id(proj)
		scope_env: List[Dict[str, TypeId]] = [dict()]
		scope_bindings: List[Dict[str, int]] = [dict()]
		expr_types: Dict[int, TypeId] = {}
		binding_for_var: Dict[int, int] = {}
		binding_types: Dict[int, TypeId] = {}
		binding_names: Dict[int, str] = {}
		# Binding mutability (val/var) keyed by binding id.
		#
		# MVP borrow rules depend on this:
		#   - `&mut x` requires `x` to be declared mutable (`var`).
		binding_mutable: Dict[int, bool] = {}
		# Binding identity kind (param vs local). Binding ids share a single counter,
		# but we still track the origin kind to keep place reasoning explicit.
		binding_place_kind: Dict[int, PlaceKind] = {}
		if preseed_binding_place_kind:
			for bid, kind in preseed_binding_place_kind.items():
				binding_place_kind[bid] = kind
		if preseed_binding_types:
			for bid, ty in preseed_binding_types.items():
				binding_types[bid] = ty
				binding_place_kind.setdefault(bid, PlaceKind.LOCAL)
		if preseed_binding_names:
			for bid, name in preseed_binding_names.items():
				binding_names[bid] = name
		if preseed_binding_mutable:
			for bid, is_mut in preseed_binding_mutable.items():
				binding_mutable[bid] = bool(is_mut)
		if preseed_scope_env:
			scope_env[-1].update(preseed_scope_env)
		if preseed_scope_bindings:
			scope_bindings[-1].update(preseed_scope_bindings)
		def _receiver_base_lookup(hv: object) -> Optional[PlaceBase]:
			bid = getattr(hv, "binding_id", None)
			if bid is None:
				return None
			kind = binding_place_kind.get(bid, PlaceKind.LOCAL)
			name = hv.name if hasattr(hv, "name") else str(hv)
			return PlaceBase(kind=kind, local_id=bid, name=name)

		def _receiver_place(expr: H.HExpr) -> Optional[Place]:
			return place_from_expr(expr, base_lookup=_receiver_base_lookup)

		def _receiver_can_mut_borrow(expr: H.HExpr, place: Optional[Place]) -> bool:
			if place is None:
				return False
			has_deref = any(isinstance(p, DerefProj) for p in place.projections)
			if not has_deref:
				if place.base.local_id is None:
					return False
				return bool(binding_mutable.get(place.base.local_id, False))
			if hasattr(H, "HPlaceExpr") and isinstance(expr, getattr(H, "HPlaceExpr")):
				cur = type_expr(expr.base)
				for pr in expr.projections:
					if isinstance(pr, H.HPlaceDeref):
						if cur is None:
							return False
						ptr_def = self.type_table.get(cur)
						if ptr_def.kind is not TypeKind.REF or not ptr_def.ref_mut:
							return False
						cur = ptr_def.param_types[0] if ptr_def.param_types else None
					elif isinstance(pr, H.HPlaceField):
						if cur is None:
							return False
						td = self.type_table.get(cur)
						if td.kind is TypeKind.STRUCT:
							info = self.type_table.struct_field(cur, pr.name)
							if info is not None:
								_, cur = info
					elif isinstance(pr, H.HPlaceIndex):
						if cur is None:
							return False
						td = self.type_table.get(cur)
						if td.kind is TypeKind.ARRAY and td.param_types:
							cur = td.param_types[0]
				return True
			if isinstance(expr, H.HUnary) and expr.op is H.UnaryOp.DEREF:
				ptr_ty = type_expr(expr.expr)
				if ptr_ty is None:
					return False
				ptr_def = self.type_table.get(ptr_ty)
				return ptr_def.kind is TypeKind.REF and ptr_def.ref_mut
			return True

		def _receiver_preference(
			self_mode: SelfMode | None,
			*,
			receiver_is_lvalue: bool,
			receiver_can_mut_borrow: bool,
			autoborrow: Optional[SelfMode],
		) -> int | None:
			if self_mode is None:
				return None
			if not receiver_is_lvalue:
				return 2 if self_mode is SelfMode.SELF_BY_VALUE else None
			if self_mode is SelfMode.SELF_BY_REF:
				return 0
			if self_mode is SelfMode.SELF_BY_REF_MUT:
				if autoborrow is SelfMode.SELF_BY_REF_MUT and not receiver_can_mut_borrow:
					return None
				return 1
			if self_mode is SelfMode.SELF_BY_VALUE:
				return 2
			return None

		def _infer_receiver_arg_type(
			self_mode: SelfMode | None,
			recv_ty: TypeId,
			*,
			receiver_is_lvalue: bool,
			receiver_can_mut_borrow: bool,
		) -> TypeId:
			if self_mode is None:
				return recv_ty
			td_recv = self.type_table.get(recv_ty)
			if self_mode is SelfMode.SELF_BY_REF:
				if td_recv.kind is TypeKind.REF and not td_recv.ref_mut:
					return recv_ty
				if receiver_is_lvalue:
					return self.type_table.ensure_ref(recv_ty)
				return recv_ty
			if self_mode is SelfMode.SELF_BY_REF_MUT:
				if td_recv.kind is TypeKind.REF and td_recv.ref_mut:
					return recv_ty
				if receiver_can_mut_borrow:
					return self.type_table.ensure_ref_mut(recv_ty)
				return recv_ty
			return recv_ty
		# Borrow exclusivity (MVP): tracked within a single statement/expression.
		#
		# Key by Place (not binding id) so this mechanism naturally extends to
		# projections once we support borrowing from `x.field`, `arr[i]`, `*p`.
		#
		# Value is "shared" or "mut". This is intentionally shallow (no lifetimes)
		# but prevents the worst footguns:
		#   - multiple `&x` in a statement is OK
		#   - `&mut x` conflicts with any other borrow of `x` in the same statement
		#   - `&x` conflicts with a prior `&mut x` in the same statement
		borrows_in_stmt: Dict[Place, str] = {}
		def _ref_param_info(param_ty: TypeId) -> tuple[bool, TypeId] | None:
			pdef = self.type_table.get(param_ty)
			if pdef.kind is not TypeKind.REF or not pdef.param_types:
				return None
			return bool(pdef.ref_mut), pdef.param_types[0]

		def _coerce_args_for_params(params: list[TypeId], args: list[TypeId]) -> list[TypeId]:
			if len(params) != len(args):
				return list(args)
			coerced = list(args)
			for idx, (param_ty, arg_ty) in enumerate(zip(params, args)):
				if arg_ty is None:
					continue
				ref_info = _ref_param_info(param_ty)
				if ref_info is None:
					continue
				ref_mut, _inner = ref_info
				arg_def = self.type_table.get(arg_ty)
				if arg_def.kind is TypeKind.REF:
					continue
				coerced[idx] = self.type_table.ensure_ref_mut(arg_ty) if ref_mut else self.type_table.ensure_ref(arg_ty)
			return coerced

		def _args_match_params(params: list[TypeId], args: list[TypeId]) -> bool:
			if len(params) != len(args):
				return False
			for param_ty, arg_ty in zip(params, args):
				if arg_ty is None:
					return False
				if param_ty == arg_ty:
					continue
				ref_info = _ref_param_info(param_ty)
				if ref_info is not None and arg_ty == ref_info[1]:
					continue
				return False
			return True

		def _apply_autoborrow_args(
			args: list[H.HExpr],
			arg_types: list[TypeId],
			param_types: list[TypeId],
			*,
			span: Span,
		) -> tuple[list[TypeId], bool]:
			def _can_autoborrow_mut(place_expr: H.HExpr, place: Place) -> bool:
				has_deref = any(isinstance(p, DerefProj) for p in place.projections)
				if not has_deref:
					if place.base.local_id is None:
						return False
					return bool(binding_mutable.get(place.base.local_id, False))
				if not hasattr(H, "HPlaceExpr") or not isinstance(place_expr, getattr(H, "HPlaceExpr")):
					return False
				cur = type_expr(place_expr.base, used_as_value=False)
				if cur is None:
					return False
				for pr in place_expr.projections:
					if isinstance(pr, H.HPlaceDeref):
						ptr_def = self.type_table.get(cur)
						if ptr_def.kind is not TypeKind.REF or not ptr_def.ref_mut:
							return False
						cur = ptr_def.param_types[0] if ptr_def.param_types else None
						if cur is None:
							return False
					elif isinstance(pr, H.HPlaceField):
						td = self.type_table.get(cur)
						if td.kind is not TypeKind.STRUCT:
							return False
						info = self.type_table.struct_field(cur, pr.name)
						if info is None:
							return False
						_, cur = info
					elif isinstance(pr, H.HPlaceIndex):
						td = self.type_table.get(cur)
						if td.kind is not TypeKind.ARRAY or not td.param_types:
							return False
						cur = td.param_types[0]
				return True

			if len(args) != len(param_types) or len(arg_types) != len(param_types):
				return list(arg_types), False
			updated_types = list(arg_types)
			had_error = False
			for idx, (param_ty, arg_ty, arg_expr) in enumerate(zip(param_types, arg_types, args)):
				if arg_ty is None:
					continue
				ref_info = _ref_param_info(param_ty)
				if ref_info is None:
					continue
				ref_mut, inner = ref_info
				if arg_ty == param_ty:
					continue
				if arg_ty != inner:
					continue
				place_expr = place_expr_from_lvalue_expr(arg_expr)
				if place_expr is None:
					diagnostics.append(
						_tc_diag(
							message="borrow requires an addressable place; bind to a local first",
							severity="error",
							phase="typecheck",
							span=getattr(arg_expr, "loc", span),
						)
					)
					had_error = True
					continue
				_assign_place_expr_ids(place_expr)
				if ref_mut:
					place = place_from_expr(place_expr, base_lookup=_receiver_base_lookup)
					if place is None or not _can_autoborrow_mut(place_expr, place):
						diagnostics.append(
							_tc_diag(
								message="cannot auto-borrow as &mut; argument is not mutable",
								severity="error",
								phase="typecheck",
								span=getattr(arg_expr, "loc", span),
							)
						)
						had_error = True
						continue
				borrow_expr = H.HBorrow(subject=place_expr, is_mut=ref_mut)
				_assign_node_id(borrow_expr)
				args[idx] = borrow_expr
				updated_types[idx] = type_expr(borrow_expr)
			return updated_types, had_error
		# Ref origin tracking (MVP escape policy):
		#
		# When a binding has a reference type, record whether it is ultimately
		# derived from a single reference *parameter* binding. This lets us enforce
		# "return refs only derived from a ref param" without a full lifetime model.
		#
		# Value is the binding_id of the originating ref param, or None when the
		# reference points at local/temporary storage.
		ref_origin_param: Dict[int, Optional[int]] = {}
		explicit_capture_stack: list[dict[int, str]] = []
		def _explicit_capture_kind(binding_id: int | None) -> str | None:
			if binding_id is None:
				return None
			for scope in reversed(explicit_capture_stack):
				kind = scope.get(binding_id)
				if kind is not None:
					return kind
			return None
		diagnostics: List[Diagnostic] = []
		deferred_guard_diags: Dict[DeferredGuardKey, List[Diagnostic]] = {}
		guard_outcomes: Dict[GuardKey, ProofStatus] = {}
		call_resolutions: Dict[int, CallableDecl | MethodResolution] = {}
		call_info_by_callsite_id: Dict[int, CallInfo] = {}
		fnptr_consts_by_node_id: Dict[int, tuple[FunctionRefId, CallSig]] = {}
		instantiations_by_callsite_id: Dict[int, CallInstantiation] = {}
		trait_worlds = getattr(self.type_table, "trait_worlds", {}) or {}
		def _world_has_trait_data(world: TraitWorld) -> bool:
			return bool(
				world.traits
				or world.impls
				or world.requires_by_struct
				or world.requires_by_fn
			)
		has_trait_worlds = isinstance(trait_worlds, dict) and any(
			_world_has_trait_data(world) for world in trait_worlds.values()
		)
		linked = linked_world
		if linked is None and has_trait_worlds:
			diagnostics.append(
				_tc_diag(
					message="internal: linked trait world missing for typecheck",
					severity="error",
					span=Span(),
				)
			)
		global_trait_world: TraitWorld | None = linked.global_world if linked is not None else None
		visible_trait_world: TraitWorld | None = None
		if linked is not None and visible_modules is not None:
			module_name_by_id: dict[ModuleId, str] = {}
			if callable_registry is not None and signatures_by_id is not None:
				for fn_key, sig in signatures_by_id.items():
					decl = callable_registry.get_by_fn_id(fn_key)
					mod_name = getattr(sig, "module", None)
					if decl is None or mod_name is None:
						continue
					prev = module_name_by_id.get(decl.module_id)
					if prev is None:
						module_name_by_id[decl.module_id] = mod_name
					elif prev != mod_name:
						# Keep the first mapping; conflicting module ids are a bug upstream.
						module_name_by_id[decl.module_id] = prev
			visible_names: list[str] = []
			missing_modules: list[ModuleId] = []
			for mid in visible_modules:
				chain = visibility_provenance.get(mid)
				if chain:
					visible_names.append(chain[-1])
				elif current_module_name is not None and mid == current_module:
					visible_names.append(current_module_name)
				elif mid in module_name_by_id:
					visible_names.append(module_name_by_id[mid])
				else:
					missing_modules.append(mid)
			if missing_modules:
				if visibility_provenance:
					diagnostics.append(
						_tc_diag(
							message=(
								"internal: missing visibility provenance for module ids "
								+ ", ".join(str(mid) for mid in missing_modules)
							),
							severity="error",
							span=Span(),
						)
					)
			if not visible_names and current_module_name is not None:
				visible_names.append(current_module_name)
			visible_trait_world = linked.visible_world(visible_names)
		require_env_local = require_env
		if require_env_local is None and has_trait_worlds:
			diagnostics.append(
				_tc_diag(
					message="internal: RequireEnv missing for typecheck",
					severity="error",
					span=Span(),
				)
			)
		type_param_map: dict[str, TypeParamId] = {}
		type_param_names: dict[TypeParamId, str] = {}
		fn_require_assumed: set[tuple[object, TraitKey]] = set()

		def _require_for_fn(fid: FunctionId) -> parser_ast.TraitExpr | None:
			if require_env_local is not None:
				return require_env_local.requires_by_fn.get(fid)
			return None

		def _require_for_struct(key: TypeKey) -> parser_ast.TraitExpr | None:
			if require_env_local is not None:
				return require_env_local.requires_by_struct.get(key)
			return None

		def _collect_trait_is(expr: parser_ast.TraitExpr, out: list[parser_ast.TraitIs]) -> None:
			if isinstance(expr, parser_ast.TraitIs):
				out.append(expr)
				return
			if isinstance(expr, (parser_ast.TraitAnd, parser_ast.TraitOr)):
				_collect_trait_is(expr.left, out)
				_collect_trait_is(expr.right, out)
				return
			if isinstance(expr, parser_ast.TraitNot):
				_collect_trait_is(expr.expr, out)

		def _extract_conjunctive_facts(expr: parser_ast.TraitExpr) -> list[parser_ast.TraitIs]:
			if isinstance(expr, parser_ast.TraitIs):
				return [expr]
			if isinstance(expr, parser_ast.TraitAnd):
				return _extract_conjunctive_facts(expr.left) + _extract_conjunctive_facts(expr.right)
			if isinstance(expr, (parser_ast.TraitOr, parser_ast.TraitNot)):
				return []
			return []

		def _subject_name(subject: object) -> str | None:
			if isinstance(subject, parser_ast.SelfRef):
				return "Self"
			if isinstance(subject, parser_ast.TypeNameRef):
				return subject.name
			if isinstance(subject, str):
				return subject
			return None

		def _subject_lookup_key(subject: object) -> object:
			name = _subject_name(subject)
			return name if name is not None else subject

		def _is_self_subject(subject: object) -> bool:
			return isinstance(subject, parser_ast.SelfRef) or subject == "Self"

		def _resolve_trait_subjects_for_type_params(
			expr: parser_ast.TraitExpr,
			map_by_name: dict[str, TypeParamId],
		) -> parser_ast.TraitExpr:
			if isinstance(expr, parser_ast.TraitIs):
				subj_name = _subject_name(expr.subject)
				if subj_name is not None and subj_name in map_by_name:
					return parser_ast.TraitIs(
						loc=expr.loc,
						subject=map_by_name[subj_name],
						trait=expr.trait,
					)
				return expr
			if isinstance(expr, parser_ast.TraitAnd):
				return parser_ast.TraitAnd(
					loc=expr.loc,
					left=_resolve_trait_subjects_for_type_params(expr.left, map_by_name),
					right=_resolve_trait_subjects_for_type_params(expr.right, map_by_name),
				)
			if isinstance(expr, parser_ast.TraitOr):
				return parser_ast.TraitOr(
					loc=expr.loc,
					left=_resolve_trait_subjects_for_type_params(expr.left, map_by_name),
					right=_resolve_trait_subjects_for_type_params(expr.right, map_by_name),
				)
			if isinstance(expr, parser_ast.TraitNot):
				return parser_ast.TraitNot(
					loc=expr.loc,
					expr=_resolve_trait_subjects_for_type_params(expr.expr, map_by_name),
				)
			return expr

		def _normalize_type_key(key: object) -> object:
			if isinstance(key, TypeKey):
				return normalize_type_key(
					key,
					module_name=current_module_name,
					default_package=getattr(self.type_table, "package_id", None),
					module_packages=getattr(self.type_table, "module_packages", None),
				)
			return key

		default_package = getattr(self.type_table, "package_id", None)
		module_packages = getattr(self.type_table, "module_packages", None)

		def _type_key_label(key: object) -> str:
			pkg = getattr(key, "package_id", None)
			module = getattr(key, "module", None)
			name = getattr(key, "name", "")
			base = f"{module}.{name}" if module else name
			if pkg:
				base = f"{pkg}::{base}"
			args = getattr(key, "args", None) or ()
			if not args:
				return base
			inner = ", ".join(_type_key_label(a) for a in args)
			return f"{base}<{inner}>"

		def _trait_label(trait_key: TraitKey) -> str:
			base = f"{trait_key.module}.{trait_key.name}" if trait_key.module else trait_key.name
			if trait_key.package_id:
				return f"{trait_key.package_id}::{base}"
			return base

		def _trait_expr_label(expr: parser_ast.TraitExpr) -> str:
			if isinstance(expr, parser_ast.TraitIs):
				subj = expr.subject
				subj_name = _subject_name(subj)
				if subj_name is None:
					if isinstance(subj, TypeParamId):
						subj_name = type_param_names.get(subj, "T")
					elif isinstance(subj, TypeKey):
						subj_name = _type_key_label(subj)
					else:
						subj_name = str(subj)
				trait_key = trait_key_from_expr(
					expr.trait,
					default_module=current_module_name,
					default_package=default_package,
					module_packages=module_packages,
				)
				return f"{subj_name} is {_trait_label(trait_key)}"
			if isinstance(expr, parser_ast.TraitAnd):
				return f"({_trait_expr_label(expr.left)} and {_trait_expr_label(expr.right)})"
			if isinstance(expr, parser_ast.TraitOr):
				return f"({_trait_expr_label(expr.left)} or {_trait_expr_label(expr.right)})"
			if isinstance(expr, parser_ast.TraitNot):
				return f"not ({_trait_expr_label(expr.expr)})"
			return "<trait expr>"

		def _type_has_typevar(ty_id: TypeId) -> bool:
			seen: set[TypeId] = set()
			stack = [ty_id]
			while stack:
				cur = stack.pop()
				if cur in seen:
					continue
				seen.add(cur)
				td = self.type_table.get(cur)
				if td.kind is TypeKind.TYPEVAR:
					return True
				inst = None
				if td.kind is TypeKind.STRUCT:
					inst = self.type_table.get_struct_instance(cur)
				elif td.kind is TypeKind.VARIANT:
					inst = self.type_table.get_variant_instance(cur)
				if inst is not None:
					stack.extend(list(inst.type_args))
				for child in getattr(td, "param_types", []) or []:
					stack.append(child)
			return False

		def _is_zero_sized_type(ty_id: TypeId) -> bool:
			seen: set[TypeId] = set()
			stack = [ty_id]
			while stack:
				cur = stack.pop()
				if cur in seen:
					continue
				seen.add(cur)
				td = self.type_table.get(cur)
				if td.kind in (TypeKind.TYPEVAR, TypeKind.SCALAR, TypeKind.REF, TypeKind.ARRAY, TypeKind.ERROR, TypeKind.VARIANT, TypeKind.FNRESULT):
					return False
				if td.kind is TypeKind.STRUCT:
					if not td.param_types:
						continue
					stack.extend(list(td.param_types))
					continue
				return False
			return True

		def _reject_zst_array(elem: TypeId, *, span: Span) -> bool:
			if _is_zero_sized_type(elem):
				diagnostics.append(
					_tc_diag(
						message="arrays of zero-sized element types are not supported in v1",
						code="E_ARRAY_ZST_UNSUPPORTED",
						severity="error",
						span=span,
					)
				)
				return True
			return False

		def _require_copy_value(
			ty_id: TypeId | None,
			*,
			span: Span,
			name: str | None = None,
			used_as_value: bool = True,
		) -> None:
			if not used_as_value:
				return
			if ty_id is None:
				return
			td = self.type_table.get(ty_id)
			if td.kind is TypeKind.TYPEVAR:
				# Defer Copy requirements for unresolved type parameters to instantiation.
				return
			if self.type_table.is_copy(ty_id):
				return
			pretty = self._pretty_type_name(ty_id, current_module=current_module_name)
			if name:
				msg = f"cannot copy '{name}': type '{pretty}' is not Copy (use move {name})"
			else:
				msg = f"cannot copy value of type '{pretty}' (use move <expr>)"
			diagnostics.append(
				_tc_diag(
					message=msg,
					severity="error",
					span=span,
				)
			)

		self_type_id: TypeId | None = None

		def _guard_assumptions(
			expr: parser_ast.TraitExpr,
			*,
			subst: dict[object, object],
		) -> set[tuple[object, TraitKey]]:
			out: set[tuple[object, TraitKey]] = set()
			for atom in _extract_conjunctive_facts(expr):
				subj = atom.subject
				trait_key = trait_key_from_expr(
					atom.trait,
					default_module=current_module_name,
					default_package=default_package,
					module_packages=module_packages,
				)
				if _is_self_subject(subj):
					if self_type_id is None:
						continue
					subj_type_id = self_type_id
					subj_def = self.type_table.get(subj_type_id)
					if subj_def.kind is TypeKind.REF and subj_def.param_types:
						subj_type_id = subj_def.param_types[0]
					self_def = self.type_table.get(subj_type_id)
					if self_def.kind is TypeKind.TYPEVAR and self_def.type_param_id is not None:
						out.add((self_def.type_param_id, trait_key))
						tp_name = type_param_names.get(self_def.type_param_id)
						ty_id = self.type_table.ensure_typevar(self_def.type_param_id, name=tp_name)
						key = _normalize_type_key(type_key_from_typeid(self.type_table, ty_id))
						out.add((key, trait_key))
					else:
						key = _normalize_type_key(type_key_from_typeid(self.type_table, subj_type_id))
						out.add((key, trait_key))
					continue
				if isinstance(subj, TypeParamId):
					out.add((subj, trait_key))
					tp_name = type_param_names.get(subj)
					ty_id = self.type_table.ensure_typevar(subj, name=tp_name)
					key = _normalize_type_key(type_key_from_typeid(self.type_table, ty_id))
					out.add((key, trait_key))
					continue
				lookup_key = _subject_lookup_key(subj)
				key = subst.get(lookup_key)
				if key is not None:
					out.add((key, trait_key))
				elif isinstance(subj, TypeKey):
					out.add((_normalize_type_key(subj), trait_key))
			return out

		guard_trait_scopes: list[list[TraitKey]] = []

		def _with_guard_assumptions(assumed: set[tuple[object, TraitKey]], block: H.HBlock) -> None:
			if not assumed:
				type_block(block)
				return
			added = {a for a in assumed if a not in fn_require_assumed}
			if added:
				fn_require_assumed.update(added)
			guard_traits = sorted({trait for _subj, trait in assumed}, key=_trait_label)
			if guard_traits:
				guard_trait_scopes.append(guard_traits)
			try:
				type_block(block)
			finally:
				for item in added:
					fn_require_assumed.discard(item)
				if guard_traits:
					guard_trait_scopes.pop()

		def _guard_key(expr: H.HTraitExpr) -> GuardKey:
			return int(getattr(expr, "node_id", 0) or 0)

		def _type_block_defer_diags(
			block: H.HBlock,
			*,
			guard_key: GuardKey,
			branch: str,
			assumed: set[tuple[object, TraitKey]] | None = None,
		) -> None:
			start = len(diagnostics)
			if assumed:
				_with_guard_assumptions(assumed, block)
			else:
				type_block(block)
			if len(diagnostics) > start:
				key = (guard_key, branch)
				deferred_guard_diags.setdefault(key, []).extend(diagnostics[start:])
				del diagnostics[start:]

		sig: FnSignature | None = None
		if signatures_by_id is not None:
			sig = signatures_by_id.get(fn_id)
			if sig is not None:
				type_param_map = {p.name: p.id for p in getattr(sig, "type_params", []) or []}
				type_param_names = {p.id: p.name for p in getattr(sig, "type_params", []) or []}

		def _traits_in_scope() -> list[TraitKey]:
			extra: list[TraitKey] = []
			for scope in guard_trait_scopes:
				extra.extend(scope)
			if trait_scope_by_module:
				traits = list(trait_scope_by_module.get(current_module_name, []))
				for trait in extra:
					if trait not in traits:
						traits.append(trait)
				return traits
			return extra

		def _resolve_self_type_id() -> TypeId | None:
			if param_types and "self" in param_types:
				return param_types.get("self")
			if sig is not None and sig.param_names and sig.param_type_ids:
				for name, ty_id in zip(sig.param_names, sig.param_type_ids):
					if name == "self":
						return ty_id
			if sig is not None and sig.is_method and sig.param_type_ids:
				return sig.param_type_ids[0]
			return None

		self_type_id = _resolve_self_type_id()
		req = _require_for_fn(fn_id)
		if req is not None:
			for atom in _extract_conjunctive_facts(req):
				subj = atom.subject
				subj_name = _subject_name(subj)
				if subj_name is not None and subj_name in type_param_map:
					subj = type_param_map[subj_name]
				if isinstance(subj, TypeParamId):
					trait_key = trait_key_from_expr(
						atom.trait,
						default_module=current_module_name,
						default_package=default_package,
						module_packages=module_packages,
					)
					fn_require_assumed.add((subj, trait_key))
					tp_name = type_param_names.get(subj)
					ty_id = self.type_table.ensure_typevar(subj, name=tp_name)
					key = _normalize_type_key(type_key_from_typeid(self.type_table, ty_id))
					fn_require_assumed.add((key, trait_key))

		def _function_ref_candidates(
			name: str,
			module_name: str | None,
		) -> list[tuple[FunctionId, FnSignature]]:
			if callable_registry is not None:
				candidates = callable_registry.get_free_candidates(
					name=name,
					visible_modules=_visible_modules_for_free_call(module_name),
					include_private_in=current_module if module_name is None else None,
				)
				sigs: list[tuple[FunctionId, FnSignature]] = []
				for cand in candidates:
					if cand.fn_id is None or signatures_by_id is None:
						continue
					sig = signatures_by_id.get(cand.fn_id)
					if sig is not None and not getattr(sig, "is_method", False):
						sigs.append((cand.fn_id, sig))
				return sigs
			return []

		def _expected_function_shape(expected_type: TypeId | None) -> tuple[list[TypeId], TypeId, bool] | None:
			if expected_type is None:
				return None
			td = self.type_table.get(expected_type)
			if td.kind is not TypeKind.FUNCTION or not td.param_types:
				return None
			params = list(td.param_types[:-1])
			ret = td.param_types[-1]
			can_throw = td.can_throw()
			return params, ret, can_throw

		def _force_boundary_can_throw(sig: FnSignature | None, fn_id: FunctionId | None) -> bool:
			if sig is None:
				return False
			if getattr(sig, "is_method", False):
				return False
			else:
				if not (getattr(sig, "is_exported_entrypoint", False) or getattr(sig, "is_extern", False)):
					return False
			callee_mod = fn_id.module if fn_id and fn_id.module else getattr(sig, "module", None)
			if callee_mod is None:
				return False
			return callee_mod != current_module_name

		def _method_boundary_visible(sig: FnSignature | None, fn_id: FunctionId | None) -> bool:
			if sig is None or not getattr(sig, "is_method", False):
				return False
			if not getattr(sig, "is_pub", False):
				return False
			callee_mod = fn_id.module if fn_id and fn_id.module else getattr(sig, "module", None)
			if callee_mod is None:
				return False
			return callee_mod != current_module_name

		def _apply_method_boundary(
			expr: H.HMethodCall,
			*,
			target_fn_id: FunctionId,
			sig_for_throw: FnSignature | None,
			call_can_throw: bool,
		) -> tuple[FunctionId, bool] | None:
			if not _method_boundary_visible(sig_for_throw, target_fn_id):
				return target_fn_id, call_can_throw
			wrapper_id = method_wrapper_by_target.get(target_fn_id)
			if wrapper_id is not None:
				return wrapper_id, True
			if call_can_throw:
				return target_fn_id, True
			if wrapper_id is None:
				diagnostics.append(
					_tc_diag(
						message=f"missing boundary wrapper for method '{expr.method_name}' (compiler bug)",
						severity="error",
						span=getattr(expr, "loc", Span()),
					)
				)
				return None
			return wrapper_id, True

		def _call_sig_for_fn_ref(sig: FnSignature) -> tuple[list[TypeId], TypeId, bool] | None:
			if getattr(sig, "type_params", None):
				return None
			if sig.param_type_ids is None or sig.return_type_id is None:
				return None
			if sig.declared_can_throw is None:
				diagnostics.append(
					_tc_diag(
						message="internal: signature missing declared_can_throw (checker bug)",
						severity="error",
						span=Span(),
					)
				)
				can_throw = True
			else:
				can_throw = bool(sig.declared_can_throw)
			if getattr(sig, "is_exported_entrypoint", False) or getattr(sig, "is_extern", False):
				can_throw = True
			return list(sig.param_type_ids), sig.return_type_id, can_throw

		def _ensure_ok_wrap_thunk(
			target_fn_id: FunctionId,
			params: list[TypeId],
			ret: TypeId,
		) -> FunctionRefId:
			key = (ThunkKind.OK_WRAP, target_fn_id, tuple(params), ret)
			spec = self._thunk_specs.get(key)
			if spec is not None:
				return FunctionRefId(fn_id=spec.thunk_fn_id, kind=FunctionRefKind.THUNK_OK_WRAP)
			thunk_fn_id = FunctionId(
				module="lang.__internal",
				name=f"__thunk_ok_wrap::{function_symbol(target_fn_id)}",
				ordinal=0,
			)
			spec = ThunkSpec(
				thunk_fn_id=thunk_fn_id,
				target_fn_id=target_fn_id,
				param_types=tuple(params),
				return_type=ret,
				kind=ThunkKind.OK_WRAP,
			)
			self._thunk_specs[key] = spec
			return FunctionRefId(fn_id=thunk_fn_id, kind=FunctionRefKind.THUNK_OK_WRAP)

		def _ensure_boundary_thunk(
			target_fn_id: FunctionId,
			params: list[TypeId],
			ret: TypeId,
		) -> FunctionRefId:
			key = (ThunkKind.BOUNDARY, target_fn_id, tuple(params), ret)
			spec = self._thunk_specs.get(key)
			if spec is not None:
				return FunctionRefId(fn_id=spec.thunk_fn_id, kind=FunctionRefKind.THUNK_BOUNDARY)
			thunk_fn_id = FunctionId(
				module="lang.__internal",
				name=f"__thunk_boundary::{function_symbol(target_fn_id)}",
				ordinal=0,
			)
			spec = ThunkSpec(
				thunk_fn_id=thunk_fn_id,
				target_fn_id=target_fn_id,
				param_types=tuple(params),
				return_type=ret,
				kind=ThunkKind.BOUNDARY,
			)
			self._thunk_specs[key] = spec
			return FunctionRefId(fn_id=thunk_fn_id, kind=FunctionRefKind.THUNK_BOUNDARY)

		@dataclass
		class _FnRefResolution:
			fn_ref: FunctionRefId | None
			call_sig: CallSig | None
			fn_type: TypeId | None

		def _resolve_function_reference_value(
			*,
			name: str,
			module_name: str | None,
			expected_type: TypeId | None,
			span: Span,
			diag_mode: str,
			allow_thunk: bool,
		) -> _FnRefResolution | None:
			fn_candidates = _function_ref_candidates(name, module_name)
			if not fn_candidates:
				return None
			expected_fn = _expected_function_shape(expected_type)
			candidate_labels: list[str] = []
			matches: list[tuple[FunctionId, FnSignature, tuple[list[TypeId], TypeId, bool]]] = []
			thunk_candidates: list[tuple[FunctionId, FnSignature, tuple[list[TypeId], TypeId, bool]]] = []
			throw_mismatch_only = False

			def _build_resolution(
				fn_id: FunctionId,
				sig: FnSignature,
				call_sig_tuple: tuple[list[TypeId], TypeId, bool],
			) -> _FnRefResolution:
				params, ret, can_throw = call_sig_tuple
				call_sig = CallSig(param_types=tuple(params), user_ret_type=ret, can_throw=bool(can_throw))
				is_exported = bool(getattr(sig, "is_exported_entrypoint", False))
				is_extern = bool(getattr(sig, "is_extern", False))
				if is_exported or is_extern:
					fn_ref = _ensure_boundary_thunk(fn_id, params, ret)
				else:
					fn_ref = FunctionRefId(fn_id=fn_id, kind=FunctionRefKind.IMPL, has_wrapper=False)
				fn_ty = self.type_table.ensure_function(params, ret, can_throw=bool(can_throw))
				return _FnRefResolution(fn_ref=fn_ref, call_sig=call_sig, fn_type=fn_ty)

			for fn_id, sig in fn_candidates:
				cs = _call_sig_for_fn_ref(sig)
				if cs is None:
					continue
				params, ret, can_throw = cs
				cand_ty = self.type_table.ensure_function(params, ret, can_throw=bool(can_throw))
				candidate_labels.append(self._pretty_type_name(cand_ty, current_module=current_module_name))
				if expected_fn is None:
					continue
				exp_params, exp_ret, exp_throw = expected_fn
				if params == exp_params and ret == exp_ret:
					if can_throw != exp_throw:
						throw_mismatch_only = True
						if exp_throw and not can_throw:
							thunk_candidates.append((fn_id, sig, cs))
					else:
						matches.append((fn_id, sig, cs))

			if expected_fn is None:
				if len(fn_candidates) > 1:
					diagnostics.append(
						_tc_diag(
							message=f"ambiguous function reference '{name}'; add a type annotation",
							severity="error",
							span=span,
						)
					)
					return _FnRefResolution(fn_ref=None, call_sig=None, fn_type=None)
				chosen_fn_id, chosen_sig = fn_candidates[0]
				call_sig_tuple = _call_sig_for_fn_ref(chosen_sig)
				if call_sig_tuple is None:
					diag = (
						f"function reference '{name}' requires explicit type arguments"
						if getattr(chosen_sig, "type_params", None)
						else "function reference lacks resolved parameter types (compiler bug)"
					)
					diagnostics.append(
						_tc_diag(
							message=diag,
							severity="error",
							span=span,
						)
					)
					return _FnRefResolution(fn_ref=None, call_sig=None, fn_type=None)
				return _build_resolution(chosen_fn_id, chosen_sig, call_sig_tuple)

			if not matches:
				if allow_thunk and expected_fn is not None and len(thunk_candidates) == 1:
					chosen_fn_id, chosen_sig, cs = thunk_candidates[0]
					params, ret, _can_throw = cs
					thunk_ref = _ensure_ok_wrap_thunk(chosen_fn_id, params, ret)
					call_sig = CallSig(param_types=tuple(params), user_ret_type=ret, can_throw=True)
					fn_ty = self.type_table.ensure_function(params, ret, can_throw=True)
					return _FnRefResolution(fn_ref=thunk_ref, call_sig=call_sig, fn_type=fn_ty)
				if diag_mode == "cast":
					pretty = self._pretty_type_name(expected_type, current_module=current_module_name)
					exp_params, exp_ret, exp_throw = expected_fn
					params_s = ", ".join(self._pretty_type_name(p, current_module=current_module_name) for p in exp_params)
					if not params_s:
						params_s = "()"
					ret_s = self._pretty_type_name(exp_ret, current_module=current_module_name)
					throw_label = "nothrow" if not exp_throw else "can-throw"
					notes: list[str] = []
					if candidate_labels:
						notes.append(f"candidates: {'; '.join(candidate_labels)}")
					if throw_mismatch_only:
						notes.append("note: throw-mode differs; thunking (nothrow -> can-throw) is not supported yet")
					diagnostics.append(
						_tc_diag(
							message=(
								f"cannot cast function '{name}' to {pretty}: no overload matches "
								f"(expected params: {params_s}, returns: {ret_s}, {throw_label})"
							),
							severity="error",
							span=span,
							notes=notes,
						)
					)
				else:
					pretty = self._pretty_type_name(expected_type, current_module=current_module_name)
					diagnostics.append(
						_tc_diag(
							message=f"no overload of '{name}' matches function type {pretty}",
							severity="error",
							span=span,
						)
					)
				return _FnRefResolution(fn_ref=None, call_sig=None, fn_type=None)

			if len(matches) > 1:
				if diag_mode == "cast":
					pretty = self._pretty_type_name(expected_type, current_module=current_module_name)
					notes = [f"candidates: {'; '.join(candidate_labels)}"] if candidate_labels else []
					diagnostics.append(
						_tc_diag(
							message=f"cannot cast function '{name}' to {pretty}: ambiguous overload resolution",
							severity="error",
							span=span,
							notes=notes,
						)
					)
				else:
					diagnostics.append(
						_tc_diag(
							message=f"ambiguous function reference '{name}'; add a type annotation to disambiguate",
							severity="error",
							span=span,
						)
					)
				return _FnRefResolution(fn_ref=None, call_sig=None, fn_type=None)

			chosen_fn_id, chosen_sig, call_sig_tuple = matches[0]
			return _build_resolution(chosen_fn_id, chosen_sig, call_sig_tuple)

		def _lambda_can_throw(lam: H.HLambda, call_info: Mapping[int, CallInfo]) -> bool:
			def expr_can_throw(expr: H.HExpr) -> bool:
				if isinstance(expr, H.HCall):
					info = call_info.get(getattr(expr, "callsite_id", None))
					if info is None:
						return True
					if info.sig.can_throw:
						return True
					if isinstance(expr.fn, H.HLambda):
						return _lambda_can_throw(expr.fn, call_info)
					return any(expr_can_throw(a) for a in expr.args)
				if isinstance(expr, H.HMethodCall):
					info = call_info.get(getattr(expr, "callsite_id", None))
					if info is None:
						return True
					if info.sig.can_throw:
						return True
					if expr_can_throw(expr.receiver):
						return True
					return any(expr_can_throw(a) for a in expr.args)
				if isinstance(expr, H.HInvoke):
					info = call_info.get(getattr(expr, "callsite_id", None))
					if info is None:
						return True
					if info.sig.can_throw:
						return True
					if isinstance(expr.callee, H.HLambda):
						return _lambda_can_throw(expr.callee, call_info)
					if expr_can_throw(expr.callee):
						return True
					return any(expr_can_throw(a) for a in expr.args)
				if isinstance(expr, H.HTryExpr):
					catch_all = any(arm.event_fqn is None for arm in expr.arms)
					if not catch_all and expr_can_throw(expr.attempt):
						return True
					for arm in expr.arms:
						if block_can_throw(arm.block):
							return True
						if arm.result is not None and expr_can_throw(arm.result):
							return True
					return False
				if isinstance(expr, H.HLambda):
					return _lambda_can_throw(expr, call_info)
				if isinstance(expr, H.HResultOk):
					return expr_can_throw(expr.value)
				if isinstance(expr, H.HTernary):
					return (
						expr_can_throw(expr.cond)
						or expr_can_throw(expr.then_expr)
						or expr_can_throw(expr.else_expr)
					)
				if isinstance(expr, H.HUnary):
					return expr_can_throw(expr.expr)
				if isinstance(expr, H.HBinary):
					return expr_can_throw(expr.left) or expr_can_throw(expr.right)
				if isinstance(expr, H.HField):
					return expr_can_throw(expr.subject)
				if isinstance(expr, H.HIndex):
					return expr_can_throw(expr.subject) or expr_can_throw(expr.index)
				if isinstance(expr, H.HPlaceExpr):
					for proj in expr.projections:
						if isinstance(proj, H.HPlaceIndex) and expr_can_throw(proj.index):
							return True
					return False
				if isinstance(expr, H.HArrayLiteral):
					return any(expr_can_throw(el) for el in expr.elements)
				if isinstance(expr, H.HDVInit):
					return any(expr_can_throw(a) for a in expr.args)
				return False

			def stmt_can_throw(stmt: H.HStmt) -> bool:
				if isinstance(stmt, (H.HThrow, H.HRethrow)):
					return True
				if isinstance(stmt, H.HExprStmt):
					return expr_can_throw(stmt.expr)
				if isinstance(stmt, H.HLet):
					return expr_can_throw(stmt.value)
				if isinstance(stmt, H.HAssign):
					return expr_can_throw(stmt.value)
				if isinstance(stmt, H.HAugAssign):
					return expr_can_throw(stmt.value) or expr_can_throw(stmt.target)
				if isinstance(stmt, H.HReturn):
					return expr_can_throw(stmt.value) if stmt.value is not None else False
				if isinstance(stmt, H.HIf):
					if expr_can_throw(stmt.cond):
						return True
					if block_can_throw(stmt.then_block):
						return True
					return block_can_throw(stmt.else_block) if stmt.else_block is not None else False
				if isinstance(stmt, H.HLoop):
					return block_can_throw(stmt.body)
				if isinstance(stmt, H.HTry):
					if block_can_throw(stmt.body):
						return True
					return any(block_can_throw(arm.block) for arm in stmt.catches)
				return False

			def block_can_throw(block: H.HBlock | None) -> bool:
				if block is None:
					return False
				return any(stmt_can_throw(stmt) for stmt in block.statements)

			if lam.body_expr is not None:
				return expr_can_throw(lam.body_expr)
			if lam.body_block is not None:
				return block_can_throw(lam.body_block)
			return False

		def _loc_from_span(span: Span) -> parser_ast.Located:
			return parser_ast.Located(line=span.line or 0, column=span.column or 0)

		def _trait_subject_to_parser(subject: object) -> object:
			if isinstance(subject, H.HSelfRef):
				return parser_ast.SelfRef(loc=_loc_from_span(subject.loc))
			if isinstance(subject, H.HTypeNameRef):
				return parser_ast.TypeNameRef(name=subject.name, loc=_loc_from_span(subject.loc))
			return subject

		def _trait_expr_to_parser(expr: H.HTraitExpr) -> parser_ast.TraitExpr:
			if isinstance(expr, H.HTraitIs):
				loc = _loc_from_span(expr.loc)
				return parser_ast.TraitIs(
					loc=loc,
					subject=_trait_subject_to_parser(expr.subject),
					trait=expr.trait,
				)
			if isinstance(expr, H.HTraitAnd):
				loc = _loc_from_span(expr.loc)
				return parser_ast.TraitAnd(loc=loc, left=_trait_expr_to_parser(expr.left), right=_trait_expr_to_parser(expr.right))
			if isinstance(expr, H.HTraitOr):
				loc = _loc_from_span(expr.loc)
				return parser_ast.TraitOr(loc=loc, left=_trait_expr_to_parser(expr.left), right=_trait_expr_to_parser(expr.right))
			if isinstance(expr, H.HTraitNot):
				loc = _loc_from_span(expr.loc)
				return parser_ast.TraitNot(loc=loc, expr=_trait_expr_to_parser(expr.expr))
			raise TypeError(f"unsupported trait expr node: {type(expr).__name__}")

		def _collect_trait_subjects(expr: parser_ast.TraitExpr, out: set[object]) -> None:
			if isinstance(expr, parser_ast.TraitIs):
				subj = expr.subject
				if isinstance(subj, TypeParamId):
					out.add(subj)
					return
				subj_name = _subject_name(subj)
				if subj_name is not None:
					out.add(subj_name)
					return
				out.add(subj)
			elif isinstance(expr, (parser_ast.TraitAnd, parser_ast.TraitOr)):
				_collect_trait_subjects(expr.left, out)
				_collect_trait_subjects(expr.right, out)
			elif isinstance(expr, parser_ast.TraitNot):
				_collect_trait_subjects(expr.expr, out)

		def _first_obligation_failure(
			*,
			req_expr: parser_ast.TraitExpr,
			subst: dict[object, object],
			origin: ObligationOrigin,
			span: Span,
			env: TraitEnv,
			world: TraitWorld | None,
		) -> ProofFailure | None:
			if world is None:
				return None
			atoms: list[parser_ast.TraitIs] = []
			_collect_trait_is(req_expr, atoms)
			for atom in atoms:
				trait_key = trait_key_from_expr(
					atom.trait,
					default_module=env.default_module,
					default_package=env.default_package,
					module_packages=env.module_packages,
				)
				lookup_key = _subject_lookup_key(atom.subject)
				subject_key = subst.get(lookup_key)
				if subject_key is None and isinstance(lookup_key, TypeParamId):
					subject_key = subst.get(lookup_key)
				if subject_key is None:
					continue
				obl = Obligation(
					subject=subject_key,
					trait=trait_key,
					origin=origin,
					span=span,
				)
				failure = prove_obligation(world, env, obl)
				if failure is not None:
					return failure
			return None

		def _failure_reason_for_status(status: ProofStatus) -> ProofFailureReason:
			if status is ProofStatus.AMBIGUOUS:
				return ProofFailureReason.AMBIGUOUS_IMPL
			if status is ProofStatus.UNKNOWN:
				return ProofFailureReason.UNKNOWN
			return ProofFailureReason.NO_IMPL

		def _require_failure(
			*,
			req_expr: parser_ast.TraitExpr,
			subst: dict[object, object],
			origin: ObligationOrigin,
			span: Span,
			env: TraitEnv,
			world: TraitWorld | None,
			result: ProofResult | None = None,
		) -> ProofFailure | None:
			if world is None:
				return None
			res = result or prove_expr(world, env, subst, req_expr)
			if res.status is ProofStatus.PROVED:
				return None
			reason = _failure_reason_for_status(res.status)
			if isinstance(req_expr, parser_ast.TraitOr):
				left_res = prove_expr(world, env, subst, req_expr.left)
				right_res = prove_expr(world, env, subst, req_expr.right)
				notes: list[str] = []
				left_failure = _require_failure(
					req_expr=req_expr.left,
					subst=subst,
					origin=origin,
					span=span,
					env=env,
					world=world,
					result=left_res,
				)
				if left_failure is not None:
					notes.append(_format_failure_message(left_failure))
				right_failure = _require_failure(
					req_expr=req_expr.right,
					subst=subst,
					origin=origin,
					span=span,
					env=env,
					world=world,
					result=right_res,
				)
				if right_failure is not None:
					notes.append(_format_failure_message(right_failure))
				base_failure = _first_obligation_failure(
					req_expr=req_expr,
					subst=subst,
					origin=origin,
					span=span,
					env=env,
					world=world,
				)
				message = f"requirement not satisfied: expected {_trait_expr_label(req_expr)}"
				if base_failure is not None:
					obl = Obligation(
						subject=base_failure.obligation.subject,
						trait=base_failure.obligation.trait,
						origin=origin,
						span=span,
						notes=notes,
					)
					return ProofFailure(
						obligation=obl,
						reason=reason,
						impl_ids=base_failure.impl_ids,
						details=tuple(res.reasons),
						message_override=message,
					)
				placeholder = Obligation(
					subject=TypeKey(package_id=None, module=None, name="<unknown>", args=()),
					trait=TraitKey(package_id=None, module=None, name="<unknown>"),
					origin=origin,
					span=span,
					notes=notes,
				)
				return ProofFailure(
					obligation=placeholder,
					reason=reason,
					details=tuple(res.reasons),
					message_override=message,
				)
			if isinstance(req_expr, parser_ast.TraitNot):
				message = f"requirement not satisfied: expected {_trait_expr_label(req_expr)}"
				notes = list(res.reasons)
				base_failure = _first_obligation_failure(
					req_expr=req_expr,
					subst=subst,
					origin=origin,
					span=span,
					env=env,
					world=world,
				)
				if base_failure is not None:
					obl = Obligation(
						subject=base_failure.obligation.subject,
						trait=base_failure.obligation.trait,
						origin=origin,
						span=span,
						notes=notes,
					)
					return ProofFailure(
						obligation=obl,
						reason=reason,
						impl_ids=base_failure.impl_ids,
						details=tuple(res.reasons),
						message_override=message,
					)
				placeholder = Obligation(
					subject=TypeKey(package_id=None, module=None, name="<unknown>", args=()),
					trait=TraitKey(package_id=None, module=None, name="<unknown>"),
					origin=origin,
					span=span,
					notes=notes,
				)
				return ProofFailure(
					obligation=placeholder,
					reason=reason,
					details=tuple(res.reasons),
					message_override=message,
				)
			failure = _first_obligation_failure(
				req_expr=req_expr,
				subst=subst,
				origin=origin,
				span=span,
				env=env,
				world=world,
			)
			if failure is not None:
				return ProofFailure(
					obligation=failure.obligation,
					reason=reason,
					impl_ids=failure.impl_ids,
					details=failure.details,
				)
			atoms: list[parser_ast.TraitIs] = []
			_collect_trait_is(req_expr, atoms)
			for atom in atoms:
				trait_key = trait_key_from_expr(
					atom.trait,
					default_module=env.default_module,
					default_package=env.default_package,
					module_packages=env.module_packages,
				)
				lookup_key = _subject_lookup_key(atom.subject)
				subject_key = subst.get(lookup_key)
				if subject_key is None and isinstance(lookup_key, TypeParamId):
					subject_key = subst.get(lookup_key)
				if subject_key is None:
					continue
				obl = Obligation(
					subject=subject_key,
					trait=trait_key,
					origin=origin,
					span=span,
					notes=list(res.reasons),
				)
				return ProofFailure(
					obligation=obl,
					reason=reason,
					details=tuple(res.reasons),
				)
			return None

		def _format_failure_message(failure: ProofFailure) -> str:
			if failure.message_override:
				msg = failure.message_override
			else:
				subj = _type_key_label(failure.obligation.subject)
				trait = _trait_label(failure.obligation.trait)
				if failure.reason is ProofFailureReason.AMBIGUOUS_IMPL:
					msg = f"requirement is ambiguous: {subj} is {trait}"
				elif failure.reason is ProofFailureReason.UNKNOWN:
					msg = f"requirement cannot be proven: {subj} is {trait}"
				else:
					msg = f"requirement not satisfied: {subj} is {trait}"
			label = failure.obligation.origin.label
			if label:
				msg = f"{msg} (required by {label})"
			return msg

		def _failure_code(failure: ProofFailure) -> str:
			if failure.reason is ProofFailureReason.AMBIGUOUS_IMPL:
				return "E_REQUIREMENT_AMBIGUOUS"
			if failure.reason is ProofFailureReason.UNKNOWN:
				return "E_REQUIREMENT_UNKNOWN"
			return "E_REQUIREMENT_NOT_SATISFIED"

		def _pick_best_failure(failures: list[ProofFailure]) -> ProofFailure | None:
			if not failures:
				return None
			priority = {
				ProofFailureReason.AMBIGUOUS_IMPL: 0,
				ProofFailureReason.UNKNOWN: 1,
				ProofFailureReason.NO_IMPL: 2,
			}
			def _key(f: ProofFailure) -> tuple[int, str, str, str]:
				return (
					priority.get(f.reason, 9),
					_trait_label(f.obligation.trait),
					_type_key_label(f.obligation.subject),
					f.obligation.origin.label or "",
				)
			return sorted(failures, key=_key)[0]

		def _candidate_key_for_decl(decl: CallableDecl) -> object:
			return decl.fn_id if decl.fn_id is not None else ("callable", decl.callable_id)

		def _param_scope_map(sig: FnSignature | None) -> dict[TypeParamId, tuple[str, int]]:
			scope: dict[TypeParamId, tuple[str, int]] = {}
			if sig is None:
				return scope
			for idx, tp in enumerate(getattr(sig, "impl_type_params", []) or []):
				scope[tp.id] = ("impl", idx)
			for idx, tp in enumerate(getattr(sig, "type_params", []) or []):
				scope[tp.id] = ("fn", idx)
			return scope

		def _dedupe_by_key(items: list[tuple], key_fn) -> list[tuple]:
			seen: set[object] = set()
			out: list[tuple] = []
			for item in items:
				key = key_fn(item)
				if key in seen:
					continue
				seen.add(key)
				out.append(item)
			return out

		def _pick_most_specific_items(
			items: list[tuple],
			key_fn,
			require_info: dict[object, tuple[parser_ast.TraitExpr, dict[object, object], str, dict[TypeParamId, tuple[str, int]]]],
		) -> list[tuple]:
			if len(items) <= 1:
				return items
			if require_env_local is None:
				return items
			formulas: dict[object, object] = {}
			for item in items:
				key = key_fn(item)
				info = require_info.get(key)
				if info is None:
					formula = BOOL_TRUE
				else:
					req_expr, subst, def_mod, scope_map = info
					formula = require_env_local.normalized(
						req_expr,
						subst=subst,
						default_module=def_mod,
						param_scope_map=scope_map,
					)
				formulas[key] = formula
			winners: list[tuple] = []
			for item in items:
				key = key_fn(item)
				base = formulas.get(key, BOOL_TRUE)
				is_dominated = False
				for other in items:
					other_key = key_fn(other)
					if other_key == key:
						continue
					other_formula = formulas.get(other_key, BOOL_TRUE)
					if require_env_local.implies(other_formula, base) and not require_env_local.implies(base, other_formula):
						is_dominated = True
						break
				if not is_dominated:
					winners.append(item)
			return winners

		def _combine_require(
			left: parser_ast.TraitExpr | None,
			right: parser_ast.TraitExpr | None,
		) -> parser_ast.TraitExpr | None:
			if left is None:
				return right
			if right is None:
				return left
			loc = getattr(left, "loc", None) or getattr(right, "loc", None)
			return parser_ast.TraitAnd(loc=loc, left=left, right=right)

		def _label_typeid(tid: TypeId) -> str:
			return _type_key_label(type_key_from_typeid(self.type_table, tid))

		def _format_infer_failure(ctx: InferContext, res: InferResult) -> tuple[str, list[str]]:
			return format_infer_failure(ctx, res, label_typeid=_label_typeid)

		def _infer(ctx: InferContext) -> InferResult:
			trace = InferTrace()
			type_param_ids = list(ctx.type_param_ids)
			if not type_param_ids:
				return InferResult(
					ok=True,
					subst=None,
					inst_params=list(ctx.param_types),
					inst_return=ctx.return_type,
					trace=trace,
					context=ctx,
				)
			type_param_set = set(type_param_ids)
			if len(ctx.param_types) != len(ctx.arg_types):
				return InferResult(
					ok=False,
					subst=None,
					inst_params=None,
					inst_return=None,
					trace=trace,
					error=InferError(kind=InferErrorKind.ARITY),
					context=ctx,
				)
			constraints: list[InferConstraint] = []
			for idx, (p, a) in enumerate(zip(ctx.param_types, ctx.arg_types)):
				origin = None
				if ctx.call_kind == "ctor" and ctx.param_names and idx < len(ctx.param_names):
					origin = InferConstraintOrigin(kind="ctor_field", name=ctx.param_names[idx])
				elif ctx.receiver_type is not None and idx == 0:
					origin = InferConstraintOrigin(kind="receiver")
				else:
					name = ctx.param_names[idx] if ctx.param_names and idx < len(ctx.param_names) else None
					origin = InferConstraintOrigin(kind="arg", index=idx, name=name)
				constraints.append(
					InferConstraint(lhs=p, rhs=a, origin=origin, span=ctx.span)
				)
			if ctx.expected_return is not None and ctx.return_type is not None:
				constraints.append(
					InferConstraint(
						lhs=ctx.return_type,
						rhs=ctx.expected_return,
						origin=InferConstraintOrigin(kind="expected_return"),
						span=ctx.span,
					)
				)

			bindings: dict[TypeParamId, TypeId] = {}

			def _record_binding(tp_id: TypeParamId, actual: TypeId, origin: InferConstraintOrigin, span: Span) -> None:
				trace.bindings.setdefault(tp_id, []).append(
					InferBindingEvidence(param_id=tp_id, bound_to=actual, origin=origin, span=span)
				)

			def _record_conflict(lhs: TypeId, rhs: TypeId, origin: InferConstraintOrigin, span: Span, param_id: TypeParamId | None = None) -> None:
				trace.conflicts.append(
					InferConflictEvidence(lhs=lhs, rhs=rhs, origin=origin, span=span, param_id=param_id)
				)

			def _bind_typevar(tp_id: TypeParamId, actual: TypeId, origin: InferConstraintOrigin, span: Span) -> bool:
				prev = bindings.get(tp_id)
				if prev is None:
					bindings[tp_id] = actual
					_record_binding(tp_id, actual, origin, span)
					return True
				if prev == actual:
					return True
				_record_conflict(prev, actual, origin, span, param_id=tp_id)
				return False

			def unify(param_ty: TypeId, actual_ty: TypeId, origin: InferConstraintOrigin, span: Span) -> bool:
				if param_ty == actual_ty:
					return True
				pd = self.type_table.get(param_ty)
				ad = self.type_table.get(actual_ty)
				if pd.kind is TypeKind.TYPEVAR and pd.type_param_id in type_param_set:
					return _bind_typevar(pd.type_param_id, actual_ty, origin, span)
				if ad.kind is TypeKind.TYPEVAR and ad.type_param_id in type_param_set:
					return _bind_typevar(ad.type_param_id, param_ty, origin, span)
				if pd.kind != ad.kind:
					_record_conflict(param_ty, actual_ty, origin, span)
					return False
				if pd.kind in (TypeKind.ARRAY, TypeKind.FNRESULT):
					if len(pd.param_types) != len(ad.param_types):
						_record_conflict(param_ty, actual_ty, origin, span)
						return False
					return all(unify(p, a, origin, span) for p, a in zip(pd.param_types, ad.param_types))
				if pd.kind is TypeKind.REF:
					if pd.ref_mut != ad.ref_mut or not pd.param_types or not ad.param_types:
						_record_conflict(param_ty, actual_ty, origin, span)
						return False
					return unify(pd.param_types[0], ad.param_types[0], origin, span)
				if pd.kind is TypeKind.STRUCT:
					p_inst = self.type_table.get_struct_instance(param_ty)
					a_inst = self.type_table.get_struct_instance(actual_ty)
					if p_inst is not None or a_inst is not None:
						p_base = p_inst.base_id if p_inst is not None else param_ty
						a_base = a_inst.base_id if a_inst is not None else actual_ty
						if p_base != a_base:
							_record_conflict(param_ty, actual_ty, origin, span)
							return False
						p_args = list(p_inst.type_args) if p_inst is not None else []
						a_args = list(a_inst.type_args) if a_inst is not None else []
						if len(p_args) != len(a_args):
							_record_conflict(param_ty, actual_ty, origin, span)
							return False
						return all(unify(p, a, origin, span) for p, a in zip(p_args, a_args))
					if pd.name != ad.name or pd.module_id != ad.module_id:
						_record_conflict(param_ty, actual_ty, origin, span)
						return False
					return True
				if pd.kind is TypeKind.VARIANT:
					p_inst = self.type_table.get_variant_instance(param_ty)
					a_inst = self.type_table.get_variant_instance(actual_ty)
					if p_inst is None and a_inst is not None and pd.param_types:
						base_id = self.type_table.get_variant_base(
							module_id=pd.module_id or "", name=pd.name
						)
						if base_id is None or base_id != a_inst.base_id:
							_record_conflict(param_ty, actual_ty, origin, span)
							return False
						p_args = list(pd.param_types)
						a_args = list(a_inst.type_args)
						if len(p_args) != len(a_args):
							_record_conflict(param_ty, actual_ty, origin, span)
							return False
						return all(unify(p, a, origin, span) for p, a in zip(p_args, a_args))
					if p_inst is not None and a_inst is None and ad.param_types:
						base_id = self.type_table.get_variant_base(
							module_id=ad.module_id or "", name=ad.name
						)
						if base_id is None or base_id != p_inst.base_id:
							_record_conflict(param_ty, actual_ty, origin, span)
							return False
						p_args = list(p_inst.type_args)
						a_args = list(ad.param_types)
						if len(p_args) != len(a_args):
							_record_conflict(param_ty, actual_ty, origin, span)
							return False
						return all(unify(p, a, origin, span) for p, a in zip(p_args, a_args))
					if p_inst is not None or a_inst is not None:
						p_base = p_inst.base_id if p_inst is not None else param_ty
						a_base = a_inst.base_id if a_inst is not None else actual_ty
						if p_base != a_base:
							_record_conflict(param_ty, actual_ty, origin, span)
							return False
						p_args = list(p_inst.type_args) if p_inst is not None else []
						a_args = list(a_inst.type_args) if a_inst is not None else []
						if len(p_args) != len(a_args):
							_record_conflict(param_ty, actual_ty, origin, span)
							return False
						return all(unify(p, a, origin, span) for p, a in zip(p_args, a_args))
					if pd.name != ad.name or pd.module_id != ad.module_id:
						_record_conflict(param_ty, actual_ty, origin, span)
						return False
					return True
				if pd.kind is TypeKind.FUNCTION:
					p_throw = pd.can_throw()
					a_throw = ad.can_throw()
					if p_throw != a_throw:
						_record_conflict(param_ty, actual_ty, origin, span)
						return False
					if len(pd.param_types) != len(ad.param_types):
						_record_conflict(param_ty, actual_ty, origin, span)
						return False
					return all(unify(p, a, origin, span) for p, a in zip(pd.param_types, ad.param_types))
				_record_conflict(param_ty, actual_ty, origin, span)
				return False

			for _ in range(2):
				for constraint in constraints:
					if not unify(constraint.lhs, constraint.rhs, constraint.origin, constraint.span):
						return InferResult(
							ok=False,
							subst=None,
							inst_params=None,
							inst_return=None,
							trace=trace,
							error=InferError(kind=InferErrorKind.CONFLICT, conflicts=trace.conflicts),
							context=ctx,
						)

			args: list[TypeId] = []
			missing: list[TypeParamId] = []
			for pid in type_param_ids:
				bound = bindings.get(pid)
				if bound is None:
					missing.append(pid)
					continue
				args.append(bound)
			if missing:
				return InferResult(
					ok=False,
					subst=None,
					inst_params=None,
					inst_return=None,
					trace=trace,
					error=InferError(kind=InferErrorKind.CANNOT_INFER, missing_params=missing),
					context=ctx,
				)

			subst = Subst(owner=type_param_ids[0].owner, args=args)
			inst_params = [apply_subst(p, subst, self.type_table) for p in ctx.param_types]
			inst_return = apply_subst(ctx.return_type, subst, self.type_table) if ctx.return_type is not None else None
			return InferResult(
				ok=True,
				subst=subst,
				inst_params=inst_params,
				inst_return=inst_return,
				trace=trace,
				context=ctx,
			)

		def _instantiate_sig_with_subst(
			*,
			sig: FnSignature,
			arg_types: list[TypeId],
			expected_type: TypeId | None,
			explicit_type_args: list[TypeId] | None,
			allow_infer: bool,
			diag_span: Span | None = None,
			call_kind: str = "call",
			call_name: str = "",
			receiver_type: TypeId | None = None,
		) -> InferResult:
			if sig.param_type_ids is None or sig.return_type_id is None:
				return InferResult(
					ok=False,
					subst=None,
					inst_params=None,
					inst_return=None,
					error=InferError(kind=InferErrorKind.NO_TYPES),
				)
			if explicit_type_args:
				if not sig.type_params:
					return InferResult(
						ok=False,
						subst=None,
						inst_params=None,
						inst_return=None,
						error=InferError(kind=InferErrorKind.NO_TYPEPARAMS),
					)
				if len(explicit_type_args) != len(sig.type_params):
					return InferResult(
						ok=False,
						subst=None,
						inst_params=None,
						inst_return=None,
						error=InferError(
							kind=InferErrorKind.TYPEARG_COUNT,
							expected_count=len(sig.type_params),
						),
					)
				subst = Subst(owner=sig.type_params[0].id.owner, args=list(explicit_type_args))
				for arg in subst.args:
					_enforce_struct_requires(arg, diag_span or Span())
				inst_params = [apply_subst(p, subst, self.type_table) for p in sig.param_type_ids]
				inst_return = apply_subst(sig.return_type_id, subst, self.type_table)
				return InferResult(
					ok=True,
					subst=subst,
					inst_params=inst_params,
					inst_return=inst_return,
					context=None,
				)
			if sig.type_params:
				if not allow_infer:
					return InferResult(
						ok=False,
						subst=None,
						inst_params=None,
						inst_return=None,
						error=InferError(kind=InferErrorKind.CANNOT_INFER),
					)
				type_param_names = {p.id: p.name for p in sig.type_params}
				ctx = InferContext(
					call_kind="method" if call_kind == "method" else call_kind,
					call_name=call_name or sig.name,
					span=diag_span or Span(),
					type_param_ids=[p.id for p in sig.type_params],
					type_param_names=type_param_names,
					param_types=list(sig.param_type_ids),
					param_names=list(sig.param_names) if sig.param_names else None,
					return_type=sig.return_type_id,
					arg_types=list(arg_types),
					receiver_type=receiver_type,
					expected_return=expected_type,
				)
				res = _infer(ctx)
				if not res.ok or res.subst is None:
					return res
				subst = res.subst
				inst_params = [apply_subst(p, subst, self.type_table) for p in sig.param_type_ids]
				inst_return = apply_subst(sig.return_type_id, subst, self.type_table)
				for arg in subst.args:
					_enforce_struct_requires(arg, diag_span or Span())
				res.inst_params = inst_params
				res.inst_return = inst_return
				return res
			return InferResult(
				ok=True,
				subst=None,
				inst_params=list(sig.param_type_ids),
				inst_return=sig.return_type_id,
			)

		def _instantiate_sig(
			*,
			sig: FnSignature,
			arg_types: list[TypeId],
			expected_type: TypeId | None,
			explicit_type_args: list[TypeId] | None,
			allow_infer: bool,
			diag_span: Span | None = None,
			call_kind: str = "call",
			call_name: str = "",
			receiver_type: TypeId | None = None,
		) -> InferResult:
			res = _instantiate_sig_with_subst(
				sig=sig,
				arg_types=arg_types,
				expected_type=expected_type,
				explicit_type_args=explicit_type_args,
				allow_infer=allow_infer,
				diag_span=diag_span,
				call_kind=call_kind,
				call_name=call_name,
				receiver_type=receiver_type,
			)
			return res

		def _receiver_compat(
			receiver_type: TypeId,
			param_self: TypeId,
			self_mode: SelfMode | None,
		) -> tuple[bool, Optional[SelfMode]]:
			if self_mode is None:
				return False, None
			if self_mode is SelfMode.SELF_BY_VALUE:
				return (receiver_type == param_self), None
			td_param = self.type_table.get(param_self)
			td_recv = self.type_table.get(receiver_type)
			if self_mode is SelfMode.SELF_BY_REF:
				if receiver_type == param_self and td_recv.kind is TypeKind.REF and td_recv.ref_mut is False:
					return True, None
				if td_param.kind is TypeKind.REF and td_param.ref_mut is False and td_param.param_types:
					if td_param.param_types[0] == receiver_type:
						return True, SelfMode.SELF_BY_REF
				return False, None
			if self_mode is SelfMode.SELF_BY_REF_MUT:
				if receiver_type == param_self and td_recv.kind is TypeKind.REF and td_recv.ref_mut is True:
					return True, None
				if td_param.kind is TypeKind.REF and td_param.ref_mut is True and td_param.param_types:
					if td_param.param_types[0] == receiver_type:
						return True, SelfMode.SELF_BY_REF_MUT
				return False, None
			return False, None

		def _unwrap_ref_type(ty: TypeId) -> TypeId:
			td = self.type_table.get(ty)
			if td.kind is TypeKind.REF and td.param_types:
				return td.param_types[0]
			return ty

		def _struct_base_and_args(ty: TypeId) -> tuple[TypeId, list[TypeId]]:
			inst = self.type_table.get_struct_instance(ty)
			if inst is not None:
				return inst.base_id, list(inst.type_args)
			return ty, []

		def _enforce_struct_requires(ty: TypeId, span: Span) -> None:
			base_id, args = _struct_base_and_args(ty)
			if any(_type_has_typevar(a) for a in args):
				return
			base_def = self.type_table.get(base_id)
			base_mod = getattr(base_def, "module_id", None)
			base_pkg = (
				getattr(self.type_table, "module_packages", {}).get(base_mod, getattr(self.type_table, "package_id", None))
				if base_mod is not None
				else None
			)
			struct_key = TypeKey(package_id=base_pkg, module=base_mod, name=getattr(base_def, "name", ""), args=())
			req = _require_for_struct(struct_key)
			if req is None:
				return
			param_ids = self.type_table.get_struct_type_param_ids(base_id) or []
			subst: dict[object, object] = {}
			if param_ids and len(param_ids) == len(args):
				for pid, arg in zip(param_ids, args):
					key = _normalize_type_key(type_key_from_typeid(self.type_table, arg))
					subst[pid] = key
			schema = self.type_table.get_struct_schema(base_id)
			if schema is not None and schema.type_params and args:
				for name, arg in zip(schema.type_params, args):
					subst.setdefault(name, _normalize_type_key(type_key_from_typeid(self.type_table, arg)))
			subst.setdefault("Self", _normalize_type_key(type_key_from_typeid(self.type_table, ty)))
			env = TraitEnv(
				default_module=struct_key.module or current_module_name,
				default_package=default_package,
				module_packages=module_packages or {},
				assumed_true=set(fn_require_assumed),
			)
			res = prove_expr(global_trait_world, env, subst, req) if global_trait_world is not None else None
			failure = _require_failure(
				req_expr=req,
				subst=subst,
				origin=ObligationOrigin(
					kind=ObligationOriginKind.CALLEE_REQUIRE,
					label=f"struct '{struct_key.name}'",
					span=Span.from_loc(getattr(req, "loc", None)),
				),
				span=span,
				env=env,
				world=global_trait_world,
				result=res,
			)
			if failure is not None:
				diagnostics.append(
					_tc_diag(
						message=_format_failure_message(failure),
						code=_failure_code(failure),
						severity="error",
						span=span,
						notes=list(getattr(failure.obligation, "notes", []) or []),
					)
				)

		sig_span = Span()
		if signatures_by_id is not None:
			fn_sig = signatures_by_id.get(fn_id)
			if fn_sig is not None:
				sig_span = Span.from_loc(getattr(fn_sig, "loc", None))
		if param_types:
			for ty in param_types.values():
				_enforce_struct_requires(ty, sig_span)
		if return_type is not None:
			_enforce_struct_requires(return_type, sig_span)

		def _match_impl_type_args(
			*,
			template_args: list[TypeId],
			recv_args: list[TypeId],
			impl_type_params: list[TypeParam],
		) -> Subst | None:
			if not impl_type_params:
				return None
			if len(template_args) != len(recv_args):
				return None
			owner = impl_type_params[0].id.owner
			bindings: list[TypeId | None] = [None] * len(impl_type_params)
			def _bind_typevar(param_id: TypeParamId, recv: TypeId) -> bool:
				if param_id.owner != owner:
					return False
				idx = int(param_id.index)
				if idx < 0 or idx >= len(bindings):
					return False
				if bindings[idx] is None:
					bindings[idx] = recv
					return True
				return bindings[idx] == recv

			def _match_type(tmpl: TypeId, recv: TypeId) -> bool:
				tdef = self.type_table.get(tmpl)
				if tdef.kind is TypeKind.TYPEVAR and tdef.type_param_id is not None:
					return _bind_typevar(tdef.type_param_id, recv)
				if tmpl == recv:
					return True
				rdef = self.type_table.get(recv)
				if tdef.kind is not rdef.kind:
					return False
				if tdef.kind is TypeKind.REF:
					if tdef.ref_mut != rdef.ref_mut:
						return False
					if len(tdef.param_types) != len(rdef.param_types):
						return False
					return _match_type(tdef.param_types[0], rdef.param_types[0])
				if tdef.kind in {TypeKind.ARRAY, TypeKind.FNRESULT, TypeKind.FUNCTION}:
					if tdef.kind is TypeKind.FUNCTION:
						t_throw = tdef.can_throw()
						r_throw = rdef.can_throw()
						if t_throw != r_throw:
							return False
					if len(tdef.param_types) != len(rdef.param_types):
						return False
					for sub_t, sub_r in zip(tdef.param_types, rdef.param_types):
						if not _match_type(sub_t, sub_r):
							return False
					return True
				if tdef.kind is TypeKind.STRUCT:
					tmpl_inst = self.type_table.get_struct_instance(tmpl)
					recv_inst = self.type_table.get_struct_instance(recv)
					if tmpl_inst is None and recv_inst is None:
						return tmpl == recv
					if tmpl_inst is None or recv_inst is None:
						return False
					if tmpl_inst.base_id != recv_inst.base_id:
						return False
					if len(tmpl_inst.type_args) != len(recv_inst.type_args):
						return False
					for sub_t, sub_r in zip(tmpl_inst.type_args, recv_inst.type_args):
						if not _match_type(sub_t, sub_r):
							return False
					return True
				if tdef.kind is TypeKind.VARIANT:
					tmpl_inst = self.type_table.get_variant_instance(tmpl)
					recv_inst = self.type_table.get_variant_instance(recv)
					if tmpl_inst is None and recv_inst is None:
						return tmpl == recv
					if tmpl_inst is None or recv_inst is None:
						return False
					if tmpl_inst.base_id != recv_inst.base_id:
						return False
					if len(tmpl_inst.type_args) != len(recv_inst.type_args):
						return False
					for sub_t, sub_r in zip(tmpl_inst.type_args, recv_inst.type_args):
						if not _match_type(sub_t, sub_r):
							return False
					return True
				return False

			for tmpl, recv in zip(template_args, recv_args):
				if not _match_type(tmpl, recv):
					return None
			if any(b is None for b in bindings):
				return None
			return Subst(owner=owner, args=[b for b in bindings if b is not None])

		def _fn_id_for_decl(decl: CallableDecl) -> FunctionId | None:
			return decl.fn_id

		def _resolve_free_call_with_require(
			*,
			name: str,
			module_name: str | None,
			arg_types: List[TypeId],
			call_type_args: List[TypeId] | None = None,
			call_type_args_span: Span | None = None,
			expected_type: TypeId | None = None,
		) -> tuple[CallableDecl, CallableSignature, Subst | None]:
			if callable_registry is None:
				raise ResolutionError(f"no matching overload for function '{name}' with args {arg_types}")
			include_private = current_module if module_name is None else None
			candidates = callable_registry.get_free_candidates(
				name=name,
				visible_modules=_visible_modules_for_free_call(module_name),
				include_private_in=include_private,
			)
			viable: List[tuple[CallableDecl, CallableSignature, Subst | None]] = []
			type_arg_counts: set[int] = set()
			saw_registry_only_with_type_args = False
			saw_typed_nongeneric_with_type_args = False
			saw_infer_incomplete = False
			saw_require_failed = False
			infer_failures: list[InferResult] = []
			for decl in candidates:
				sig = None
				if decl.fn_id is not None and signatures_by_id is not None:
					sig = signatures_by_id.get(decl.fn_id)

				if sig is None:
					if call_type_args:
						saw_registry_only_with_type_args = True
						continue
					params = list(decl.signature.param_types)
					result_type = decl.signature.result_type
					if len(params) != len(arg_types):
						continue
					if _args_match_params(list(params), arg_types):
						viable.append(
							(
								decl,
								CallableSignature(param_types=tuple(params), result_type=result_type),
								None,
							)
						)
					continue

				if sig.param_type_ids is None and sig.param_types is not None:
					local_type_params = {p.name: p.id for p in sig.type_params}
					param_type_ids = [
						resolve_opaque_type(p, self.type_table, module_id=sig.module, type_params=local_type_params)
						for p in sig.param_types
					]
					sig = replace(sig, param_type_ids=param_type_ids)

				if sig.return_type_id is None and sig.return_type is not None:
					local_type_params = {p.name: p.id for p in sig.type_params}
					ret_id = resolve_opaque_type(sig.return_type, self.type_table, module_id=sig.module, type_params=local_type_params)
					sig = replace(sig, return_type_id=ret_id)

				if sig.param_type_ids is None or sig.return_type_id is None:
					continue

				inst_arg_types = _coerce_args_for_params(list(sig.param_type_ids), arg_types)
				inst_res = _instantiate_sig_with_subst(
					sig=sig,
					arg_types=inst_arg_types,
					expected_type=expected_type,
					explicit_type_args=call_type_args,
					allow_infer=True,
					diag_span=call_type_args_span,
					call_kind="free",
					call_name=name,
				)
				if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS and call_type_args:
					saw_typed_nongeneric_with_type_args = True
					continue
				if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT and call_type_args:
					if inst_res.error.expected_count is not None:
						type_arg_counts.add(inst_res.error.expected_count)
					continue
				if inst_res.error and inst_res.error.kind in {InferErrorKind.CANNOT_INFER, InferErrorKind.CONFLICT}:
					saw_infer_incomplete = True
					infer_failures.append(inst_res)
					continue
				if inst_res.error:
					continue
				params = inst_res.inst_params
				result_type = inst_res.inst_return
				inst_subst = inst_res.subst

				if len(params) != len(arg_types):
					continue
				if _args_match_params(list(params), arg_types):
					viable.append(
						(
							decl,
							CallableSignature(param_types=tuple(params), result_type=result_type),
							inst_subst,
						)
					)
			if not viable:
				if call_type_args:
					if type_arg_counts:
						exp = ", ".join(str(n) for n in sorted(type_arg_counts))
						raise ResolutionError(
							f"type argument count mismatch for '{name}': expected one of ({exp}), got {len(call_type_args)}",
							span=call_type_args_span,
						)
					if saw_typed_nongeneric_with_type_args:
						raise ResolutionError(
							f"type arguments require a generic signature for function '{name}'",
							span=call_type_args_span,
						)
					if saw_registry_only_with_type_args:
						raise ResolutionError(
							f"type arguments require a typed signature for function '{name}'",
							span=call_type_args_span,
						)
					raise ResolutionError(f"no matching overload for function '{name}' with provided type arguments")
				if saw_infer_incomplete and infer_failures:
					failure = infer_failures[0]
					ctx = failure.context or InferContext(
						call_kind="free",
						call_name=name,
						span=call_type_args_span or Span(),
						type_param_ids=[],
						type_param_names={},
						param_types=[],
						param_names=None,
						return_type=None,
						arg_types=[],
					)
					msg, notes = _format_infer_failure(ctx, failure)
					raise ResolutionError(msg, span=call_type_args_span, notes=notes)
				if saw_infer_incomplete:
					ctx = InferContext(
						call_kind="free",
						call_name=name,
						span=call_type_args_span or Span(),
						type_param_ids=[],
						type_param_names={},
						param_types=[],
						param_names=None,
						return_type=None,
						arg_types=[],
					)
					res = InferResult(
						ok=False,
						subst=None,
						inst_params=None,
						inst_return=None,
						error=InferError(kind=InferErrorKind.CANNOT_INFER),
						context=ctx,
					)
					msg, notes = _format_infer_failure(ctx, res)
					raise ResolutionError(msg, span=call_type_args_span, notes=notes)
				raise ResolutionError(f"no matching overload for function '{name}' with args {arg_types}")
			world = None
			applicable: List[tuple[CallableDecl, CallableSignature, Subst | None]] = []
			require_info: dict[object, tuple[parser_ast.TraitExpr, dict[object, object], str, dict[TypeParamId, tuple[str, int]]]] = {}
			require_failures: list[ProofFailure] = []
			for decl, sig_inst, inst_subst in viable:
				cand_key = decl.fn_id if decl.fn_id is not None else ("callable", decl.callable_id)
				fn_id = _fn_id_for_decl(decl)
				if fn_id is None:
					applicable.append((decl, sig_inst, inst_subst))
					continue
				world = visible_trait_world or global_trait_world
				req = _require_for_fn(fn_id)
				if req is None:
					applicable.append((decl, sig_inst, inst_subst))
					continue
				subjects: set[object] = set()
				_collect_trait_subjects(req, subjects)
				subst: dict[object, object] = {}
				sig = None
				if decl.fn_id is not None and signatures_by_id is not None:
					sig = signatures_by_id.get(decl.fn_id)
				if sig and getattr(sig, "type_params", None) and inst_subst is not None:
					type_params = list(getattr(sig, "type_params", []) or [])
					for idx, tp in enumerate(type_params):
						if tp.id in subjects or tp.name in subjects:
							if idx < len(inst_subst.args):
								key = _normalize_type_key(type_key_from_typeid(self.type_table, inst_subst.args[idx]))
								subst[tp.id] = key
								subst[tp.name] = key
				if sig and sig.param_names:
					for idx, pname in enumerate(sig.param_names):
						if pname in subst:
							continue
						if pname in subjects and idx < len(arg_types):
							key = _normalize_type_key(type_key_from_typeid(self.type_table, arg_types[idx]))
							subst[pname] = key
				if world is None:
					continue
				env = TraitEnv(
					default_module=fn_id.module or current_module_name,
					default_package=default_package,
					module_packages=module_packages or {},
					assumed_true=set(fn_require_assumed),
				)
				res = prove_expr(world, env, subst, req)
				if res.status is ProofStatus.PROVED:
					applicable.append((decl, sig_inst, inst_subst))
					scope_map = _param_scope_map(sig)
					require_info[cand_key] = (
						req,
						subst,
						fn_id.module or current_module_name,
						scope_map,
					)
				else:
					saw_require_failed = True
					origin = ObligationOrigin(
						kind=ObligationOriginKind.CALLEE_REQUIRE,
						label=f"function '{name}'",
						span=Span.from_loc(getattr(req, "loc", None)),
					)
					failure = _require_failure(
						req_expr=req,
						subst=subst,
						origin=origin,
						span=call_type_args_span or Span(),
						env=env,
						world=world,
						result=res,
					)
					if failure is not None:
						require_failures.append(failure)
			if not applicable:
				if saw_require_failed:
					failure = _pick_best_failure(require_failures)
					if failure is not None:
						raise ResolutionError(
							_format_failure_message(failure),
							code=_failure_code(failure),
							span=call_type_args_span,
							notes=list(getattr(failure.obligation, "notes", []) or []),
						)
					raise ResolutionError(f"trait requirements not met for function '{name}'")
				raise ResolutionError(f"no matching overload for function '{name}' with args {arg_types}")
			applicable = _dedupe_by_key(applicable, lambda item: _candidate_key_for_decl(item[0]))
			if len(applicable) == 1:
				return applicable[0][0], applicable[0][1], applicable[0][2]
			winners = _pick_most_specific_items(
				applicable,
				lambda item: _candidate_key_for_decl(item[0]),
				require_info,
			)
			if len(winners) != 1:
				raise ResolutionError(f"ambiguous call to function '{name}' with args {arg_types}")
			return winners[0]

		params: List[ParamId] = []
		param_bindings: List[int] = []
		locals: List[LocalId] = []
		param_binding_ids: dict[str, int] = {}
		if param_types:
			wanted = set(param_types.keys())

			def _scan_param_binds(obj: object) -> None:
				if isinstance(obj, H.HVar) and obj.binding_id is not None and obj.name in wanted:
					prev = param_binding_ids.get(obj.name)
					if prev is None or obj.binding_id < prev:
						param_binding_ids[obj.name] = obj.binding_id
				if isinstance(obj, H.HNode):
					for v in obj.__dict__.values():
						_scan_param_binds(v)
				elif isinstance(obj, list):
					for v in obj:
						_scan_param_binds(v)
				elif isinstance(obj, dict):
					for v in obj.values():
						_scan_param_binds(v)

			_scan_param_binds(body)

		# Seed parameters if provided.
		for pname, pty in (param_types or {}).items():
			pid = param_binding_ids.get(pname) or self._alloc_param_id()
			params.append(pid)
			param_bindings.append(pid)
			scope_env[-1][pname] = pty
			scope_bindings[-1][pname] = pid
			binding_types[pid] = pty
			binding_names[pid] = pname
			binding_mutable[pid] = bool(param_mutable.get(pname, False)) if param_mutable else False
			binding_place_kind[pid] = PlaceKind.PARAM
			if pty is not None and self.type_table.get(pty).kind is TypeKind.REF:
				ref_origin_param[pid] = pid

		def record_expr(expr: H.HExpr, ty: TypeId) -> TypeId:
			expr_types[expr.node_id] = ty
			return ty

		def record_call_info(
			expr: H.HCall,
			*,
			param_types: List[TypeId],
			return_type: TypeId,
			can_throw: bool,
			target: CallTarget,
		) -> None:
			info = CallInfo(
				target=target,
				sig=CallSig(param_types=tuple(param_types), user_ret_type=return_type, can_throw=bool(can_throw)),
			)
			csid = getattr(expr, "callsite_id", None)
			if isinstance(csid, int):
				call_info_by_callsite_id[csid] = info
			elif callable_registry is not None:
				diagnostics.append(
					_tc_diag(
						message="internal: missing callsite_id on call node",
						severity="error",
						span=getattr(expr, "span", Span()),
					)
				)

		def record_invoke_call_info(
			expr: "H.HInvoke",
			*,
			param_types: List[TypeId],
			return_type: TypeId,
			can_throw: bool,
		) -> None:
			info = CallInfo(
				target=CallTarget.indirect(expr.callee.node_id),
				sig=CallSig(
					param_types=tuple(param_types),
					user_ret_type=return_type,
					can_throw=bool(can_throw),
					includes_callee=False,
				),
			)
			csid = getattr(expr, "callsite_id", None)
			if isinstance(csid, int):
				call_info_by_callsite_id[csid] = info
			elif callable_registry is not None:
				diagnostics.append(
					_tc_diag(
						message="internal: missing callsite_id on invoke node",
						severity="error",
						span=getattr(expr, "span", Span()),
					)
				)

		def record_method_call_info(
			expr: H.HMethodCall,
			*,
			param_types: List[TypeId],
			return_type: TypeId,
			can_throw: bool,
			target: FunctionId,
		) -> None:
			info = CallInfo(
				target=CallTarget.direct(target),
				sig=CallSig(param_types=tuple(param_types), user_ret_type=return_type, can_throw=bool(can_throw)),
			)
			csid = getattr(expr, "callsite_id", None)
			if isinstance(csid, int):
				call_info_by_callsite_id[csid] = info
			elif callable_registry is not None:
				diagnostics.append(
					_tc_diag(
						message="internal: missing callsite_id on method call node",
						severity="error",
						span=getattr(expr, "span", Span()),
					)
				)

		def record_instantiation(
			*,
			callsite_id: int | None,
			target_fn_id: FunctionId | None,
			impl_args: Tuple[TypeId, ...],
			fn_args: Tuple[TypeId, ...],
		) -> None:
			if target_fn_id is None or function_keys_by_fn_id is None:
				return
			key = function_keys_by_fn_id.get(target_fn_id)
			if key is None:
				return
			type_args = tuple(impl_args) + tuple(fn_args)
			if not type_args:
				return
			if isinstance(callsite_id, int):
				instantiations_by_callsite_id[callsite_id] = CallInstantiation(target_key=key, type_args=type_args)
			elif callable_registry is not None:
				diagnostics.append(
					_tc_diag(
						message="internal: missing callsite_id on instantiation call node",
						severity="error",
						span=Span(),
					)
				)

		_intrinsic_method_fn_ids: dict[str, FunctionId] = {}

		def _intrinsic_method_fn_id(method_name: str) -> FunctionId:
			fn_id = _intrinsic_method_fn_ids.get(method_name)
			if fn_id is None:
				fn_id = FunctionId(module="lang.__intrinsic", name=f"__method::{method_name}", ordinal=0)
				_intrinsic_method_fn_ids[method_name] = fn_id
			return fn_id

		method_wrapper_by_target: dict[FunctionId, FunctionId] = {}
		if signatures_by_id is not None:
			for sig_id, sig in signatures_by_id.items():
				if getattr(sig, "is_wrapper", False) and getattr(sig, "wraps_target_fn_id", None) is not None:
					method_wrapper_by_target[sig.wraps_target_fn_id] = sig_id

		# Precompute constructor-name visibility for diagnostics.
		#
		# MVP constructor resolution rule (work/variant/work-progress.md):
		# - Constructors are unqualified identifiers.
		# - Constructor calls in expression position require an *expected variant type*.
		# - Without an expected type, the compiler diagnoses instead of guessing.
		ctor_to_variant_bases: dict[str, list[TypeId]] = {}
		visible_ctor_module_ids = set(visible_modules or ())
		visible_ctor_module_ids.add(current_module)
		if prelude_module_id is not None:
			visible_ctor_module_ids.add(prelude_module_id)

		def _ctor_module_visible(module_name: str | None) -> bool:
			if module_name is None:
				return False
			if visibility_provenance:
				mod_id = module_ids_by_name.get(module_name)
				if mod_id is None:
					return False
				return mod_id in visible_ctor_module_ids
			# Best-effort fallback when no provenance is available: current module only.
			return module_name == current_module_name

		items = list(getattr(self.type_table, "variant_schemas", {}).items())
		items.sort(key=lambda kv: (kv[1].module_id, kv[1].name))
		for base_id, schema in items:
			if not _ctor_module_visible(schema.module_id):
				continue
			for arm in schema.arms:
				ctor_to_variant_bases.setdefault(arm.name, []).append(base_id)

		def type_expr(
			expr: H.HExpr,
			*,
			allow_exception_init: bool = False,
			used_as_value: bool = True,
			expected_type: TypeId | None = None,
		) -> TypeId:
			nonlocal return_type
			nonlocal catch_depth
			# Literals.
			if isinstance(expr, H.HLiteralInt):
				if expected_type == self._uint:
					return record_expr(expr, self._uint)
				if expected_type == self._uint64:
					return record_expr(expr, self._uint64)
				if expected_type == self.type_table.ensure_byte():
					return record_expr(expr, expected_type)
				return record_expr(expr, self._int)
			if hasattr(H, "HLiteralFloat") and isinstance(expr, getattr(H, "HLiteralFloat")):
				return record_expr(expr, self._float)
			if isinstance(expr, H.HLiteralBool):
				return record_expr(expr, self._bool)
			if isinstance(expr, H.HTraitExpr):
				diagnostics.append(
					_tc_diag(
						message="trait propositions are only allowed in require clauses or if guards",
						code="E-TRAIT-PROP-VALUE-POS",
						severity="error",
						span=getattr(expr, "loc", Span()),
					)
				)
				return record_expr(expr, self._unknown)
			if isinstance(expr, H.HLiteralString):
				return record_expr(expr, self._string)
			if isinstance(expr, H.HFString):
				# f-strings are sugar that ultimately produce a String.
				#
				# MVP rules (from spec-change request):
				# - Each hole expression must be one of {Bool, Int, Uint, Float, String}.
				# - `:spec` is supported syntactically, but only the empty spec is
				#   accepted for now (future work will validate a richer subset).
				for hole in expr.holes:
					hole_ty = type_expr(hole.expr)
					if hole.spec:
						diagnostics.append(
							_tc_diag(
								message="E-FSTR-BAD-SPEC: non-empty :spec is not supported yet (MVP: empty only)",
								severity="error",
								span=getattr(hole, "loc", Span()),
							)
						)
					if hole_ty not in (self._bool, self._int, self._uint, self._float, self._string):
						pretty = self.type_table.get(hole_ty).name if hole_ty is not None else "Unknown"
						diagnostics.append(
							_tc_diag(
								message=f"E-FSTR-UNSUPPORTED-TYPE: f-string hole value is not formattable in MVP (have {pretty})",
								severity="error",
								span=getattr(hole, "loc", Span()),
							)
						)
				return record_expr(expr, self._string)

			if isinstance(expr, H.HCast):
				target_ty: TypeId | None = None
				try:
					_reject_fixed_width_type_expr(
						expr.target_type_expr,
						getattr(expr.target_type_expr, "module_id", None) or current_module_name,
						getattr(expr, "loc", Span()),
					)
					target_ty = resolve_opaque_type(expr.target_type_expr, self.type_table, module_id=current_module_name)
				except Exception:
					target_ty = None
				if target_ty is None:
					diagnostics.append(
						_tc_diag(
							message="cast<T>(...) has an invalid target type",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				target_def = self.type_table.get(target_ty)
				if target_def.kind is not TypeKind.FUNCTION:
					pretty = self._pretty_type_name(target_ty, current_module=current_module_name)
					diagnostics.append(
						_tc_diag(
							message=(
								"cast<T>(...) is only supported for function types in this build "
								f"(requested T = {pretty})"
							),
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				expected_fn = _expected_function_shape(target_ty)
				if expected_fn is None:
					return record_expr(expr, self._unknown)
				if isinstance(expr.value, H.HVar) and expr.value.binding_id is None:
					name = expr.value.name
					is_bound = any(name in scope for scope in scope_env)
					is_const = False
					if not is_bound:
						const_mod = expr.value.module_id or current_module_name
						if const_mod is not None:
							is_const = self.type_table.lookup_const(f"{const_mod}::{name}") is not None
					if not is_bound and not is_const:
						resolution = _resolve_function_reference_value(
							name=name,
							module_name=expr.value.module_id,
							expected_type=target_ty,
							span=getattr(expr, "loc", Span()),
							diag_mode="cast",
							allow_thunk=False,
						)
						if resolution is not None:
							if resolution.fn_ref is None:
								return record_expr(expr, self._unknown)
							fnptr_consts_by_node_id[expr.node_id] = (resolution.fn_ref, resolution.call_sig)
							return record_expr(expr, target_ty)
				inner_ty = type_expr(expr.value, expected_type=None)
				if inner_ty != target_ty:
					inner_pretty = self._pretty_type_name(inner_ty, current_module=current_module_name) if inner_ty is not None else "Unknown"
					target_pretty = self._pretty_type_name(target_ty, current_module=current_module_name)
					diagnostics.append(
						_tc_diag(
							message=f"cannot cast expression of type {inner_pretty} to {target_pretty}",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				return record_expr(expr, target_ty)

			# Names and bindings.
			if isinstance(expr, H.HVar):
				if expr.binding_id is not None:
					bound = binding_types.get(expr.binding_id)
					if bound is not None:
						binding_for_var[expr.node_id] = expr.binding_id
						_require_copy_value(bound, span=getattr(expr, "loc", Span()), name=expr.name, used_as_value=used_as_value)
						return record_expr(expr, bound)
				# Module-scoped compile-time constants.
				#
				# Consts live outside local scope bindings. We resolve them here so
				# later stages can:
				# - type-check `CONST` like a literal of its declared type,
				# - lower it to an immediate MIR/LLVM constant at each use site.
				#
				# Resolution order:
				#   1) local/param bindings (lexical scopes),
				#   2) module-qualified const symbols (`mod::NAME`) present in the TypeTable,
				#   3) unqualified const names resolved within the current module id.
				if expr.binding_id is None:
					const_mod = expr.module_id if expr.module_id is not None else current_module_name
					if const_mod is not None:
						cv = self.type_table.lookup_const(f"{const_mod}::{expr.name}")
						if cv is not None:
							ty_id, _val = cv
							_require_copy_value(ty_id, span=getattr(expr, "loc", Span()), name=expr.name, used_as_value=used_as_value)
							return record_expr(expr, ty_id)
				if expr.module_id is None and expr.binding_id is None:
					for scope in reversed(scope_bindings):
						if expr.name in scope:
							expr.binding_id = scope[expr.name]
							break
				if expr.module_id is None:
					for scope in reversed(scope_env):
						if expr.name in scope:
							if expr.binding_id is not None:
								binding_for_var[expr.node_id] = expr.binding_id
							ty_id = scope[expr.name]
							_require_copy_value(ty_id, span=getattr(expr, "loc", Span()), name=expr.name, used_as_value=used_as_value)
							return record_expr(expr, ty_id)
				# Function reference in value position (typed context preferred).
				resolution = _resolve_function_reference_value(
					name=expr.name,
					module_name=expr.module_id,
					expected_type=expected_type,
					span=getattr(expr, "loc", Span()),
					diag_mode="value",
					allow_thunk=True,
				)
				if resolution is not None:
					if resolution.fn_ref is None:
						return record_expr(expr, self._unknown)
					fnptr_consts_by_node_id[expr.node_id] = (resolution.fn_ref, resolution.call_sig)
					return record_expr(expr, resolution.fn_type)
				diagnostics.append(
					_tc_diag(
						message=f"unknown variable '{expr.name}'",
						severity="error",
						span=getattr(expr, "loc", Span()),
					)
				)
				return record_expr(expr, self._unknown)

			if isinstance(expr, H.HLambda):
				expected_fn = _expected_function_shape(expected_type) if expected_type is not None else None
				lambda_type_error = False
				if expected_fn is not None and len(expr.params) != len(expected_fn[0]):
					pretty = self._pretty_type_name(expected_type, current_module=current_module_name)
					diagnostics.append(
						_tc_diag(
							message=(
								f"lambda parameter count does not match expected function type {pretty} "
								f"(expected {len(expected_fn[0])}, got {len(expr.params)})"
							),
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				lambda_ret_type: TypeId | None = None
				if getattr(expr, "ret_type", None) is not None:
					try:
						lambda_ret_type = resolve_opaque_type(expr.ret_type, self.type_table, module_id=current_module_name)
					except Exception:
						lambda_ret_type = None
				if expected_fn is not None:
					exp_params, exp_ret, _exp_throw = expected_fn
					if lambda_ret_type is None:
						lambda_ret_type = exp_ret
					elif lambda_ret_type != exp_ret:
						ret_pretty = self._pretty_type_name(lambda_ret_type, current_module=current_module_name)
						exp_pretty = self._pretty_type_name(exp_ret, current_module=current_module_name)
						diagnostics.append(
							_tc_diag(
								message=f"lambda return type {ret_pretty} does not match expected {exp_pretty}",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						lambda_type_error = True
				scope_env.append({})
				scope_bindings.append({})
				lambda_param_types: list[TypeId] = []
				for param in expr.params:
					if getattr(param, "binding_id", None) is None:
						param.binding_id = self._alloc_param_id()
					param_type: TypeId = self._unknown
					if getattr(param, "type", None) is not None:
						try:
							param_type = resolve_opaque_type(param.type, self.type_table, module_id=current_module_name)
						except Exception:
							param_type = self._unknown
					if expected_fn is not None:
						exp_params, _exp_ret, _exp_throw = expected_fn
						exp_param = exp_params[len(lambda_param_types)]
						if getattr(param, "type", None) is None:
							param_type = exp_param
						elif param_type != exp_param:
							param_pretty = self._pretty_type_name(param_type, current_module=current_module_name)
							exp_pretty = self._pretty_type_name(exp_param, current_module=current_module_name)
							diagnostics.append(
								_tc_diag(
									message=(
										f"lambda parameter '{param.name}' has type {param_pretty} "
										f"but expected {exp_pretty}"
									),
									severity="error",
									span=getattr(param, "loc", Span()),
								)
							)
							lambda_type_error = True
						scope_env[-1][param.name] = param_type
						scope_bindings[-1][param.name] = param.binding_id
						binding_types[param.binding_id] = param_type
						binding_names[param.binding_id] = param.name
						binding_mutable[param.binding_id] = bool(getattr(param, "is_mutable", False))
						binding_place_kind[param.binding_id] = PlaceKind.PARAM
						lambda_param_types.append(param_type)
				capture_kinds: dict[int, str] = {}
				if expr.explicit_captures is not None:
					for cap in expr.explicit_captures:
						root_id = getattr(cap, "binding_id", None)
						if root_id is None:
							continue
						capture_kinds[int(root_id)] = cap.kind
						root_ty = binding_types.get(root_id, self._unknown)
						if cap.kind == "ref_mut":
							cap_ty = self.type_table.ensure_ref_mut(root_ty)
						elif cap.kind == "ref":
							cap_ty = self.type_table.ensure_ref(root_ty)
						else:
							cap_ty = root_ty
						scope_env[-1][cap.name] = cap_ty
						scope_bindings[-1][cap.name] = root_id
				if capture_kinds:
					explicit_capture_stack.append(capture_kinds)
				saved_return_type = return_type
				return_type = lambda_ret_type
				if expr.body_expr is not None:
					type_expr(expr.body_expr, expected_type=lambda_ret_type)
				if expr.body_block is not None:
					type_block(expr.body_block)
				return_type = saved_return_type
				if capture_kinds:
					explicit_capture_stack.pop()
				scope_env.pop()
				scope_bindings.pop()
				actual_can_throw = _lambda_can_throw(expr, call_info_by_callsite_id)
				expr.can_throw_effective = bool(actual_can_throw)
				if expected_fn is not None:
					# Captureless lambda -> function pointer coercion.
					if lambda_type_error:
						return record_expr(expr, self._unknown)
					captures = list(getattr(expr, "captures", []) or [])
					if expr.explicit_captures:
						diagnostics.append(
							_tc_diag(
								message="capturing lambdas cannot be coerced to function pointers",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					if not captures:
						res = discover_captures(expr)
						diagnostics.extend(res.diagnostics)
						captures = res.captures
						expr.captures = res.captures
					if captures:
						diagnostics.append(
							_tc_diag(
								message="capturing lambdas cannot be coerced to function pointers",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					exp_params, exp_ret, exp_throw = expected_fn
					if not exp_throw and actual_can_throw:
						pretty = self._pretty_type_name(expected_type, current_module=current_module_name)
						diagnostics.append(
							_tc_diag(
								message=f"lambda can throw but is expected to be nothrow for {pretty}",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					enclosing = function_symbol(fn_id).replace("::", "_").replace("#", "_")
					name = f"__lambda_fn_{enclosing}_{expr.node_id}"
					lambda_fn_id = FunctionId(module=current_module_name, name=name, ordinal=0)
					if lambda_fn_id not in self._lambda_fn_specs:
						self._lambda_fn_specs[lambda_fn_id] = LambdaFnSpec(
							fn_id=lambda_fn_id,
							origin_fn_id=fn_id,
							lambda_expr=expr,
							param_types=tuple(lambda_param_types),
							return_type=exp_ret,
							can_throw=exp_throw,
							call_info_by_callsite_id=call_info_by_callsite_id,
						)
					fn_ref = FunctionRefId(fn_id=lambda_fn_id, kind=FunctionRefKind.IMPL, has_wrapper=False)
					call_sig = CallSig(param_types=tuple(exp_params), user_ret_type=exp_ret, can_throw=bool(exp_throw))
					fnptr_consts_by_node_id[expr.node_id] = (fn_ref, call_sig)
					return record_expr(expr, expected_type)
				return record_expr(expr, self._unknown)

			if hasattr(H, "HQualifiedMember") and isinstance(expr, getattr(H, "HQualifiedMember")):
				base_te = getattr(expr, "base_type_expr", None)
				if base_te is None or not getattr(base_te, "args", None):
					diagnostics.append(
						_tc_diag(
							message=(
								"E-QMEM-NOT-CALLABLE: qualified member reference is not a first-class value in MVP; "
								"call it directly (e.g. `Type::Ctor(...)`)"
							),
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)

				base_tid = resolve_opaque_type(base_te, self.type_table, module_id=current_module_name, allow_generic_base=True)
				try:
					base_def = self.type_table.get(base_tid)
				except Exception:
					base_def = None
				if base_def is None or base_def.kind is not TypeKind.VARIANT:
					name = getattr(base_te, "name", None)
					if isinstance(name, str):
						vb = self.type_table.get_variant_base(module_id=current_module_name, name=name) or self.type_table.get_variant_base(
							module_id="lang.core", name=name
						)
						if vb is not None:
							base_tid = vb
							base_def = self.type_table.get(base_tid)
				if base_def is None or base_def.kind is not TypeKind.VARIANT:
					diagnostics.append(
						_tc_diag(
							message="E-QMEM-NONVARIANT: qualified member base is not a variant type",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)

				schema = self.type_table.get_variant_schema(base_tid)
				if schema is None:
					diagnostics.append(
						_tc_diag(
							message="internal: missing variant schema for qualified member base (compiler bug)",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				arm_schema = next((a for a in schema.arms if a.name == expr.member), None)
				if arm_schema is None:
					ctors = self._format_ctor_signature_list(schema=schema, instance=None, current_module=current_module_name)
					diagnostics.append(
						_tc_diag(
							message=(
								f"E-QMEM-NO-CTOR: constructor '{expr.member}' not found in variant "
								f"'{self._pretty_type_name(base_tid, current_module=current_module_name)}'. "
								f"Available constructors: {', '.join(ctors)}"
							),
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)

				type_params: list[TypeParam] = []
				typevar_ids: list[TypeId] = []
				if schema.type_params:
					owner = FunctionId(module="lang.__internal", name=f"__variant_{schema.module_id}::{schema.name}", ordinal=0)
					for idx, tp_name in enumerate(schema.type_params):
						param_id = TypeParamId(owner=owner, index=idx)
						type_params.append(TypeParam(id=param_id, name=tp_name, span=None))
						typevar_ids.append(self.type_table.ensure_typevar(param_id, name=tp_name))

				type_cache: dict[tuple[TypeId, tuple[TypeId, ...]], TypeId] = {}

				def _lower_generic_expr(expr: GenericTypeExpr) -> TypeId:
					if expr.param_index is not None:
						idx = int(expr.param_index)
						if 0 <= idx < len(typevar_ids):
							return typevar_ids[idx]
						return self._unknown
					name = expr.name
					if name in FIXED_WIDTH_TYPE_NAMES:
						if _fixed_width_allowed(expr.module_id or schema.module_id or current_module_name):
							return self.type_table.ensure_named(name, module_id=expr.module_id or schema.module_id)
						diagnostics.append(
							_tc_diag(
								message=(
									f"fixed-width type '{name}' is reserved in v1; "
									"use Int/Uint/Float or Byte"
								),
								code="E_FIXED_WIDTH_RESERVED",
								severity="error",
								span=Span(),
							)
						)
						return self._unknown
						if name == "Int":
							return self._int
						if name == "Uint":
							return self._uint
						if name == "Byte":
							return self.type_table.ensure_byte()
						if name == "Bool":
							return self._bool
					if name == "Float":
						return self._float
					if name == "String":
						return self._string
					if name == "Void":
						return self._void
					if name == "Error":
						return self._error
					if name == "DiagnosticValue":
						return self._dv
					if name == "Unknown":
						return self._unknown
					if name in {"&", "&mut"} and expr.args:
						inner = _lower_generic_expr(expr.args[0])
						return self.type_table.ensure_ref_mut(inner) if name == "&mut" else self.type_table.ensure_ref(inner)
					if name == "Array" and expr.args:
						elem = _lower_generic_expr(expr.args[0])
						span = Span.from_loc(getattr(expr.args[0], "loc", None)) if expr.args else Span()
						if _reject_zst_array(elem, span=span):
							return self._unknown
						return self.type_table.new_array(elem)
					origin_mod = expr.module_id or schema.module_id
					base_id = (
						self.type_table.get_nominal(kind=TypeKind.STRUCT, module_id=origin_mod, name=name)
						or self.type_table.get_nominal(kind=TypeKind.VARIANT, module_id=origin_mod, name=name)
						or self.type_table.ensure_named(name, module_id=origin_mod)
					)
					if expr.args:
						if base_id in self.type_table.struct_bases:
							schema = self.type_table.struct_bases.get(base_id)
							if schema is not None and not schema.type_params:
								diagnostics.append(
									_tc_diag(
										message=f"type '{name}' is not generic",
										code="E-TYPE-NOT-GENERIC",
										severity="error",
										span=Span.from_loc(getattr(expr, "loc", None)),
									)
								)
								return self._unknown
						elif base_id in self.type_table.variant_schemas:
							schema = self.type_table.variant_schemas.get(base_id)
							if schema is not None and not schema.type_params:
								diagnostics.append(
									_tc_diag(
										message=f"type '{name}' is not generic",
										code="E-TYPE-NOT-GENERIC",
										severity="error",
										span=Span.from_loc(getattr(expr, "loc", None)),
									)
								)
								return self._unknown
						else:
							diagnostics.append(
								_tc_diag(
									message=f"unknown generic type '{name}'",
									code="E-TYPE-UNKNOWN",
									severity="error",
									span=Span.from_loc(getattr(expr, "loc", None)),
								)
							)
							return self._unknown
					if expr.args:
						arg_ids = [_lower_generic_expr(a) for a in expr.args]
						if base_id in self.type_table.variant_schemas:
							if any(self.type_table.get(a).kind is TypeKind.TYPEVAR for a in arg_ids):
								key = (base_id, tuple(arg_ids))
								if key not in type_cache:
									td = self.type_table.get(base_id)
									type_cache[key] = self.type_table._add(
										TypeKind.VARIANT,
										td.name,
										list(arg_ids),
										register_named=False,
										module_id=td.module_id,
									)
								return type_cache[key]
							return self.type_table.ensure_instantiated(base_id, arg_ids)
					return base_id

				param_type_ids: list[TypeId] = []
				for f in arm_schema.fields:
					param_type_ids.append(_lower_generic_expr(f.type_expr))
				ret_type_id = base_tid
				if schema.type_params:
					ret_type_id = _lower_generic_expr(
						GenericTypeExpr.named(schema.name, args=[GenericTypeExpr.param(i) for i in range(len(schema.type_params))], module_id=schema.module_id)
					)
				ctor_sig = FnSignature(
					name=expr.member,
					param_type_ids=param_type_ids,
					return_type_id=ret_type_id,
					type_params=type_params,
					module=current_module_name,
				)

				explicit_type_args = [
					resolve_opaque_type(t, self.type_table, module_id=current_module_name)
					for t in (base_te.args or [])
				]
				first_loc = getattr((base_te.args or [None])[0], "loc", None)
				call_type_args_span = Span.from_loc(first_loc) if first_loc is not None else None
				inst_res = _instantiate_sig(
					sig=ctor_sig,
					arg_types=[],
					expected_type=None,
					explicit_type_args=explicit_type_args,
					allow_infer=False,
					diag_span=call_type_args_span or getattr(expr, "loc", Span()),
					call_kind="ctor",
					call_name=expr.member,
				)
				if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT:
					diagnostics.append(
						_tc_diag(
							message=(
								f"E-QMEM-TYPEARGS-ARITY: expected {len(schema.type_params)} type arguments, got {len(explicit_type_args)}"
							),
							severity="error",
							span=call_type_args_span or getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS:
					diagnostics.append(
						_tc_diag(
							message="constructor does not accept type arguments; use the non-generic form instead",
							severity="error",
							span=call_type_args_span or getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				if inst_res.error:
					return record_expr(expr, self._unknown)
				if inst_res.inst_params is None or inst_res.inst_return is None:
					return record_expr(expr, self._unknown)
				inst_return = inst_res.inst_return

				return record_expr(expr, self.type_table.new_function(list(inst_res.inst_params), inst_res.inst_return))

			if hasattr(H, "HTypeApp") and isinstance(expr, getattr(H, "HTypeApp")):
				call_type_args_span = None
				if getattr(expr, "type_args", None):
					first_loc = getattr((expr.type_args or [None])[0], "loc", None)
					call_type_args_span = Span.from_loc(first_loc)
				type_arg_ids = [
					resolve_opaque_type(t, self.type_table, module_id=current_module_name)
					for t in (expr.type_args or [])
				]

				if isinstance(expr.fn, H.HVar):
					if callable_registry is not None:
						include_private = current_module if expr.fn.module_id is None else None
						candidates = callable_registry.get_free_candidates(
							name=expr.fn.name,
							visible_modules=_visible_modules_for_free_call(expr.fn.module_id),
							include_private_in=include_private,
						)
						viable: list[tuple[CallableDecl, list[TypeId], TypeId]] = []
						type_arg_counts: set[int] = set()
						saw_registry_only = False
						saw_typed_nongeneric = False
						for decl in candidates:
							sig = None
							if decl.fn_id is not None and signatures_by_id is not None:
								sig = signatures_by_id.get(decl.fn_id)
							if sig is None:
								saw_registry_only = True
								continue
							if sig.param_type_ids is None and sig.param_types is not None:
								local_type_params = {p.name: p.id for p in sig.type_params}
								param_type_ids = [
									resolve_opaque_type(p, self.type_table, module_id=sig.module, type_params=local_type_params)
									for p in sig.param_types
								]
								sig = replace(sig, param_type_ids=param_type_ids)
							if sig.return_type_id is None and sig.return_type is not None:
								local_type_params = {p.name: p.id for p in sig.type_params}
								ret_id = resolve_opaque_type(sig.return_type, self.type_table, module_id=sig.module, type_params=local_type_params)
								sig = replace(sig, return_type_id=ret_id)
							if sig.param_type_ids is None or sig.return_type_id is None:
								continue
							inst_res = _instantiate_sig(
								sig=sig,
								arg_types=[],
								expected_type=None,
								explicit_type_args=type_arg_ids,
								allow_infer=False,
								diag_span=call_type_args_span or getattr(expr, "loc", Span()),
								call_kind="free",
								call_name=decl.name,
							)
							if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS:
								saw_typed_nongeneric = True
								continue
							if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT:
								if inst_res.error.expected_count is not None:
									type_arg_counts.add(inst_res.error.expected_count)
								continue
							if inst_res.error:
								continue
							if inst_res.inst_params is None or inst_res.inst_return is None:
								continue
							viable.append((decl, list(inst_res.inst_params), inst_res.inst_return))

						if len(viable) == 1:
							decl, params, ret = viable[0]
							return record_expr(expr, self.type_table.new_function(params, ret))
						if saw_registry_only:
							diagnostics.append(
								_tc_diag(
									message=f"type arguments require a typed signature for '{expr.fn.name}'",
									severity="error",
									span=call_type_args_span or getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						if saw_typed_nongeneric:
							diagnostics.append(
								_tc_diag(
									message=f"type arguments require a generic signature for '{expr.fn.name}'",
									severity="error",
									span=call_type_args_span or getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						if type_arg_counts:
							diagnostics.append(
								_tc_diag(
									message=(
										f"type argument count mismatch for '{expr.fn.name}': expected {sorted(type_arg_counts)}, "
										f"got {len(type_arg_ids)}"
									),
									severity="error",
									span=call_type_args_span or getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						if len(viable) > 1:
							diagnostics.append(
								_tc_diag(
									message=f"ambiguous callable reference to '{expr.fn.name}'",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
					diagnostics.append(
						_tc_diag(
							message=f"unknown function '{expr.fn.name}'",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)

				if hasattr(H, "HQualifiedMember") and isinstance(expr.fn, getattr(H, "HQualifiedMember")):
					qm = expr.fn
					base_te = getattr(qm, "base_type_expr", None)
					if base_te is not None and getattr(base_te, "args", None):
						diagnostics.append(
							_tc_diag(
								message="E-QMEM-DUP-TYPEARGS: qualified member may specify type arguments only once",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					base_tid = resolve_opaque_type(base_te, self.type_table, module_id=current_module_name, allow_generic_base=True)
					try:
						base_def = self.type_table.get(base_tid)
					except Exception:
						base_def = None
					if base_def is None or base_def.kind is not TypeKind.VARIANT:
						name = getattr(base_te, "name", None)
						if isinstance(name, str):
							vb = self.type_table.get_variant_base(module_id=current_module_name, name=name) or self.type_table.get_variant_base(
								module_id="lang.core", name=name
							)
							if vb is not None:
								base_tid = vb
								base_def = self.type_table.get(base_tid)
					if base_def is None or base_def.kind is not TypeKind.VARIANT:
						diagnostics.append(
							_tc_diag(
								message="E-QMEM-NONVARIANT: qualified member base is not a variant type",
								severity="error",
								span=getattr(qm, "loc", getattr(expr, "loc", Span())),
							)
						)
						return record_expr(expr, self._unknown)
					schema = self.type_table.get_variant_schema(base_tid)
					if schema is None:
						diagnostics.append(
							_tc_diag(
								message="internal: missing variant schema for qualified member base (compiler bug)",
								severity="error",
								span=getattr(qm, "loc", getattr(expr, "loc", Span())),
							)
						)
						return record_expr(expr, self._unknown)
					arm_schema = next((a for a in schema.arms if a.name == qm.member), None)
					if arm_schema is None:
						ctors = self._format_ctor_signature_list(schema=schema, instance=None, current_module=current_module_name)
						diagnostics.append(
							_tc_diag(
								message=(
									f"E-QMEM-NO-CTOR: constructor '{qm.member}' not found in variant "
									f"'{self._pretty_type_name(base_tid, current_module=current_module_name)}'. "
									f"Available constructors: {', '.join(ctors)}"
								),
								severity="error",
								span=getattr(qm, "loc", getattr(expr, "loc", Span())),
							)
						)
						return record_expr(expr, self._unknown)

					type_params: list[TypeParam] = []
					typevar_ids: list[TypeId] = []
					if schema.type_params:
						owner = FunctionId(module="lang.__internal", name=f"__variant_{schema.module_id}::{schema.name}", ordinal=0)
						for idx, tp_name in enumerate(schema.type_params):
							param_id = TypeParamId(owner=owner, index=idx)
							type_params.append(TypeParam(id=param_id, name=tp_name, span=None))
							typevar_ids.append(self.type_table.ensure_typevar(param_id, name=tp_name))

					type_cache: dict[tuple[TypeId, tuple[TypeId, ...]], TypeId] = {}

					def _lower_generic_expr(expr: GenericTypeExpr) -> TypeId:
						if expr.param_index is not None:
							idx = int(expr.param_index)
							if 0 <= idx < len(typevar_ids):
								return typevar_ids[idx]
							return self._unknown
						name = expr.name
						if name in FIXED_WIDTH_TYPE_NAMES:
							if _fixed_width_allowed(expr.module_id or schema.module_id or current_module_name):
								return self.type_table.ensure_named(name, module_id=expr.module_id or schema.module_id)
							diagnostics.append(
								_tc_diag(
									message=(
										f"fixed-width type '{name}' is reserved in v1; "
										"use Int/Uint/Float or Byte"
									),
									code="E_FIXED_WIDTH_RESERVED",
									severity="error",
									span=Span(),
								)
							)
							return self._unknown
						if name == "Int":
							return self._int
						if name == "Uint":
							return self._uint
						if name in ("Uint64", "u64"):
							return self._uint64
						if name == "Byte":
							return self.type_table.ensure_byte()
						if name == "Bool":
							return self._bool
						if name == "Float":
							return self._float
						if name == "String":
							return self._string
						if name == "Void":
							return self._void
						if name == "Error":
							return self._error
						if name == "DiagnosticValue":
							return self._dv
						if name == "Unknown":
							return self._unknown
						if name in {"&", "&mut"} and expr.args:
							inner = _lower_generic_expr(expr.args[0])
							return self.type_table.ensure_ref_mut(inner) if name == "&mut" else self.type_table.ensure_ref(inner)
						if name == "Array" and expr.args:
							elem = _lower_generic_expr(expr.args[0])
							span = Span.from_loc(getattr(expr.args[0], "loc", None)) if expr.args else Span()
							if _reject_zst_array(elem, span=span):
								return self._unknown
							return self.type_table.new_array(elem)
						origin_mod = expr.module_id or schema.module_id
						base_id = (
							self.type_table.get_nominal(kind=TypeKind.STRUCT, module_id=origin_mod, name=name)
							or self.type_table.get_nominal(kind=TypeKind.VARIANT, module_id=origin_mod, name=name)
							or self.type_table.ensure_named(name, module_id=origin_mod)
						)
						if expr.args:
							if base_id in self.type_table.struct_bases:
								schema = self.type_table.struct_bases.get(base_id)
								if schema is not None and not schema.type_params:
									diagnostics.append(
										_tc_diag(
											message=f"type '{name}' is not generic",
											code="E-TYPE-NOT-GENERIC",
											severity="error",
											span=Span.from_loc(getattr(expr, "loc", None)),
										)
									)
									return self._unknown
							elif base_id in self.type_table.variant_schemas:
								schema = self.type_table.variant_schemas.get(base_id)
								if schema is not None and not schema.type_params:
									diagnostics.append(
										_tc_diag(
											message=f"type '{name}' is not generic",
											code="E-TYPE-NOT-GENERIC",
											severity="error",
											span=Span.from_loc(getattr(expr, "loc", None)),
										)
									)
									return self._unknown
							else:
								diagnostics.append(
									_tc_diag(
										message=f"unknown generic type '{name}'",
										code="E-TYPE-UNKNOWN",
										severity="error",
										span=Span.from_loc(getattr(expr, "loc", None)),
									)
								)
								return self._unknown
						if expr.args:
							arg_ids = [_lower_generic_expr(a) for a in expr.args]
							if base_id in self.type_table.variant_schemas:
								if any(self.type_table.get(a).kind is TypeKind.TYPEVAR for a in arg_ids):
									key = (base_id, tuple(arg_ids))
									if key not in type_cache:
										td = self.type_table.get(base_id)
										type_cache[key] = self.type_table._add(
											TypeKind.VARIANT,
											td.name,
											list(arg_ids),
											register_named=False,
											module_id=td.module_id,
										)
									return type_cache[key]
								return self.type_table.ensure_instantiated(base_id, arg_ids)
						return base_id

					param_type_ids: list[TypeId] = []
					for f in arm_schema.fields:
						param_type_ids.append(_lower_generic_expr(f.type_expr))
					ret_type_id = base_tid
					if schema.type_params:
						ret_type_id = _lower_generic_expr(
							GenericTypeExpr.named(schema.name, args=[GenericTypeExpr.param(i) for i in range(len(schema.type_params))], module_id=schema.module_id)
						)
					ctor_sig = FnSignature(
						name=qm.member,
						param_type_ids=param_type_ids,
						return_type_id=ret_type_id,
						type_params=type_params,
						module=current_module_name,
					)

					inst_res = _instantiate_sig(
						sig=ctor_sig,
						arg_types=[],
						expected_type=None,
						explicit_type_args=type_arg_ids,
						allow_infer=False,
						diag_span=call_type_args_span or getattr(expr, "loc", Span()),
						call_kind="ctor",
						call_name=qm.member,
					)
					if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT:
						diagnostics.append(
							_tc_diag(
								message=(
									f"E-QMEM-TYPEARGS-ARITY: expected {len(schema.type_params)} type arguments, got {len(type_arg_ids)}"
								),
								severity="error",
								span=call_type_args_span or getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS:
						diagnostics.append(
							_tc_diag(
								message=(
									"constructor does not accept type arguments; use the non-generic form instead"
								),
								severity="error",
								span=call_type_args_span or getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					if inst_res.error:
						return record_expr(expr, self._unknown)
					if inst_res.inst_params is None or inst_res.inst_return is None:
						return record_expr(expr, self._unknown)
					inst_return = inst_res.inst_return

					return record_expr(expr, self.type_table.new_function(list(inst_res.inst_params), inst_res.inst_return))

				diagnostics.append(
					_tc_diag(
						message="E-TYPEAPP-TARGET: type application requires a named callable target",
						severity="error",
						span=getattr(expr, "loc", Span()),
					)
				)
				return record_expr(expr, self._unknown)

			# `match` expression (statement-form match is parsed separately; this
			# branch only handles expression-form matches).
			if hasattr(H, "HMatchExpr") and isinstance(expr, getattr(H, "HMatchExpr")):
				scrut_ty = type_expr(expr.scrutinee, used_as_value=False)
				inst = None
				if scrut_ty is not None:
					try:
						td_scrut = self.type_table.get(scrut_ty)
					except Exception:
						td_scrut = None
					if td_scrut is not None and td_scrut.kind is not TypeKind.VARIANT:
						diagnostics.append(
							_tc_diag(
								message="match scrutinee must be a variant type",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
					if td_scrut is not None and td_scrut.kind is TypeKind.VARIANT:
						inst = self.type_table.get_variant_instance(scrut_ty)

				seen_default = False
				seen_default_span: Span | None = None
				seen_ctors: set[str] = set()
				result_ty: TypeId | None = None

				for idx, arm in enumerate(expr.arms):
					if arm.ctor is None:
						# default arm
						if seen_default:
							diagnostics.append(
								_tc_diag(
									message="match default arm may appear at most once",
									severity="error",
									span=getattr(arm, "loc", Span()),
								)
							)
						seen_default = True
						seen_default_span = getattr(arm, "loc", Span())
					else:
						if seen_default:
							diagnostics.append(
								_tc_diag(
									message="match arms after default are unreachable",
									severity="error",
									span=getattr(arm, "loc", Span()),
								)
							)
						if arm.ctor in seen_ctors:
							diagnostics.append(
								_tc_diag(
									message=f"duplicate match arm for constructor '{arm.ctor}'",
									severity="error",
									span=getattr(arm, "loc", Span()),
								)
							)
						seen_ctors.add(arm.ctor)

					# Type-check arm body under a scope that includes constructor binders.
					scope_env.append(dict())
					scope_bindings.append(dict())
					try:
						if arm.ctor is not None and inst is not None:
							arm_def = inst.arms_by_name.get(arm.ctor)
							if arm_def is None:
								diagnostics.append(
									_tc_diag(
										message=f"unknown constructor '{arm.ctor}' for this variant",
										severity="error",
										span=getattr(arm, "loc", Span()),
									)
								)
							else:
								form = getattr(arm, "pattern_arg_form", "positional")
								field_names = list(getattr(arm_def, "field_names", []) or [])
								field_types = list(arm_def.field_types)
								field_indices: list[int] = []

								if form == "bare":
									# Bare ctor patterns (`Ctor`) are allowed only for zero-field ctors.
									if field_types:
										diagnostics.append(
											_tc_diag(
												message=(
													f"E-MATCH-PAT-BARE: constructor pattern '{arm.ctor}' requires parentheses; "
													"use `Ctor()` to ignore payload fields"
												),
												severity="error",
												span=getattr(arm, "loc", Span()),
											)
										)
									if arm.binders:
										diagnostics.append(
											_tc_diag(
												message=f"E-MATCH-PAT-BARE: bare constructor pattern '{arm.ctor}' cannot bind fields",
												severity="error",
												span=getattr(arm, "loc", Span()),
											)
										)
								elif form == "paren":
									# `Ctor()` matches the tag only and ignores payload; it binds nothing.
									if arm.binders:
										diagnostics.append(
											_tc_diag(
												message=f"E-MATCH-PAT-PAREN: '{arm.ctor}()' pattern must not bind fields",
												severity="error",
												span=getattr(arm, "loc", Span()),
											)
										)
								elif form == "named":
									binder_fields = getattr(arm, "binder_fields", None)
									if binder_fields is None or len(binder_fields) != len(arm.binders):
										diagnostics.append(
											_tc_diag(
												message=f"internal: named constructor pattern missing binder field list (compiler bug)",
												severity="error",
												span=getattr(arm, "loc", Span()),
											)
										)
									else:
										seen_fields: set[str] = set()
										for fname, bname in zip(binder_fields, arm.binders):
											if fname in seen_fields:
												diagnostics.append(
													_tc_diag(
														message=f"duplicate field '{fname}' in constructor pattern '{arm.ctor}'",
														severity="error",
														span=getattr(arm, "loc", Span()),
													)
												)
												continue
											seen_fields.add(fname)
											if fname not in field_names:
												diagnostics.append(
													_tc_diag(
														message=(
															f"unknown field '{fname}' in constructor pattern '{arm.ctor}'; "
															f"available fields: {', '.join(field_names)}"
														),
														severity="error",
														span=getattr(arm, "loc", Span()),
													)
												)
												continue
											field_indices.append(field_names.index(fname))
								else:
									# Positional binders (exact arity in MVP).
									if len(arm.binders) != len(field_types):
										diagnostics.append(
											_tc_diag(
												message=(
													f"constructor pattern '{arm.ctor}' expects {len(field_types)} binders, got {len(arm.binders)}"
												),
												severity="error",
												span=getattr(arm, "loc", Span()),
											)
										)
									field_indices = list(range(min(len(arm.binders), len(field_types))))

								# Store normalized binder→field-index mapping for stage2 lowering.
								if hasattr(arm, "binder_field_indices"):
									arm.binder_field_indices = list(field_indices)

								# Bind only the fields requested by the pattern form.
								for bname, fidx in zip(arm.binders, field_indices):
									if fidx < 0 or fidx >= len(field_types):
										continue
									bty = field_types[fidx]
									bid = self._alloc_local_id()
									locals.append(bid)
									scope_env[-1][bname] = bty
									scope_bindings[-1][bname] = bid
									binding_types[bid] = bty
									binding_names[bid] = bname
									binding_mutable[bid] = False
									binding_place_kind[bid] = PlaceKind.LOCAL

						type_block_in_scope(arm.block)

						arm_value_ty: TypeId | None = None
						if arm.result is not None:
							arm_value_ty = type_expr(arm.result)
						elif used_as_value:
							# Allow diverging arms to omit a value in MVP. We treat a block as
							# diverging when it ends with a terminator statement.
							last = arm.block.statements[-1] if arm.block.statements else None
							diverges = isinstance(last, (H.HReturn, H.HBreak, H.HContinue, H.HThrow, H.HRethrow))
							if not diverges:
								diagnostics.append(
									_tc_diag(
										message="E-MATCH-ARM-NO-VALUE: match arm must end with an expression when match result is used",
										severity="error",
										span=getattr(arm, "loc", Span()),
									)
								)
						if used_as_value and arm_value_ty is not None:
							if result_ty is None:
								result_ty = arm_value_ty
							elif result_ty != arm_value_ty:
								diagnostics.append(
									_tc_diag(
										message=(
											"E-MATCH-ARM-TYPE: match arms must produce the same type when match result is used "
											f"(have {self.type_table.get(arm_value_ty).name}, expected {self.type_table.get(result_ty).name})"
										),
										severity="error",
										span=getattr(arm, "loc", Span()),
									)
								)
					finally:
						scope_env.pop()
						scope_bindings.pop()

				# Non-exhaustive matches require a default arm (MVP rule).
				if inst is not None and not seen_default:
					all_ctors = set(inst.arms_by_name.keys())
					if seen_ctors != all_ctors:
						missing = ", ".join(sorted(all_ctors - seen_ctors))
						diagnostics.append(
							_tc_diag(
								message=f"E-MATCH-NONEXHAUSTIVE: non-exhaustive match must include default arm (missing: {missing})",
								severity="error",
								span=getattr(expr, "loc", Span()) if seen_default_span is None else seen_default_span,
							)
						)

				if not used_as_value:
					return record_expr(expr, self._void)
				if result_ty is None:
					diagnostics.append(
						_tc_diag(
							message="E-MATCH-NO-VALUE: match result is used but no arm produces a value",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				return record_expr(expr, result_ty)

			# Borrow.
			if isinstance(expr, H.HBorrow):
				# Guardrail: do not materialize `&mut (move x)` into a temp. This would
				# turn an explicit ownership transfer into an implicit "store then
				# borrow" pattern, which is a semantic expansion we want to avoid.
				#
				# Instead, reject at type-check time with a targeted diagnostic.
				def _contains_move(node: H.HExpr) -> bool:
					if hasattr(H, "HMove") and isinstance(node, getattr(H, "HMove")):
						return True
					if isinstance(node, H.HUnary):
						return _contains_move(node.expr)
					if isinstance(node, H.HBinary):
						return _contains_move(node.left) or _contains_move(node.right)
					if isinstance(node, H.HTernary):
						return _contains_move(node.cond) or _contains_move(node.then_expr) or _contains_move(node.else_expr)
					if isinstance(node, H.HCall):
						return (
							_contains_move(node.fn)
							or any(_contains_move(a) for a in node.args)
							or any(_contains_move(k.value) for k in getattr(node, "kwargs", []) or [])
						)
					if isinstance(node, H.HMethodCall):
						return (
							_contains_move(node.receiver)
							or any(_contains_move(a) for a in node.args)
							or any(_contains_move(k.value) for k in getattr(node, "kwargs", []) or [])
						)
					if isinstance(node, H.HField):
						return _contains_move(node.subject)
					if isinstance(node, H.HIndex):
						return _contains_move(node.subject) or _contains_move(node.index)
					if isinstance(node, getattr(H, "HPlaceExpr", ())):
						# Canonical places cannot contain moves in their base/projections.
						return False
					if isinstance(node, H.HArrayLiteral):
						return any(_contains_move(e) for e in node.elements)
					if isinstance(node, H.HDVInit):
						return any(_contains_move(a) for a in node.args)
					if isinstance(node, H.HExceptionInit):
						return any(_contains_move(a) for a in node.pos_args) or any(_contains_move(k.value) for k in node.kw_args)
					if isinstance(node, getattr(H, "HTryExpr", ())):
						if _contains_move(node.attempt):
							return True
						for arm in node.arms:
							if any(_contains_move(s.expr) for s in arm.block.statements if isinstance(s, H.HExprStmt)):
								return True
							if arm.result is not None and _contains_move(arm.result):
								return True
						return False
					return False

				if expr.is_mut and _contains_move(expr.subject):
					diagnostics.append(
						_tc_diag(
							message="cannot take &mut of an expression containing move; assign to a var first",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)

				inner_ty = type_expr(expr.subject, used_as_value=False)
				# MVP: borrowing is only supported from addressable places.
				#
				# Current support:
				# - locals/params: `&x`, `&mut x`
				# - reborrow through a reference: `&*p`, `&mut *p`
				#
				# Future work: field/index borrows and temporary materialization of rvalues.
				def _base_lookup(hv: object) -> Optional[PlaceBase]:
					bid = getattr(hv, "binding_id", None)
					if bid is None:
						return None
					kind = binding_place_kind.get(bid, PlaceKind.LOCAL)
					name = hv.name if hasattr(hv, "name") else str(hv)
					return PlaceBase(kind=kind, local_id=bid, name=name)

				place = place_from_expr(expr.subject, base_lookup=_base_lookup)
				if place is None:
					diagnostics.append(
						_tc_diag(
							message="borrow operand must be an addressable place in MVP (local/param or deref place)",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)

				# MVP: we accept borrowing from nested projections (`x.field`, `arr[i]`,
				# `(*p).field`, etc.) as long as the operand is a real place.
				#
				# Note: rvalues are rejected above by `place_from_expr` returning None.
				# Auto-borrow is applied only at call sites; explicit `&x` is still
				# required when writing a borrow expression directly.

				if expr.is_mut:
					# `&mut x` requires `x` to be `var`.
					#
					# We enforce two invariants:
					#  - If the borrow is from owned storage (no deref projections), the base
					#    binding must be `var`. (Example: `&mut p.x` where `p` is a local.)
					#  - If the borrow goes through a deref projection (reborrow), mutability
					#    comes from the reference being dereferenced (Example: `&mut (*p).x`
					#    where `p: &mut Point`). In that case, the base binding does not need
					#    to be `var` (params are effectively `val`), but the dereferenced
					#    reference must be `&mut`.
					#  - If the place includes a deref projection, the reference being dereferenced
					#    must itself be mutable (`&mut`), i.e. a mutable reborrow.
					has_deref = any(isinstance(p, DerefProj) for p in place.projections)
					if (not has_deref) and place.base.local_id is not None and not binding_mutable.get(
						place.base.local_id, False
					):
						diagnostics.append(
							_tc_diag(
								message="cannot take &mut of an immutable binding; declare it with `var`",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
					# Detect a deref projection anywhere in the place and validate the corresponding
					# reference expression is `&mut`.
					#
					# We do a conservative check:
					#  - For canonical `HPlaceExpr` operands, walk projections and ensure each deref
					#    happens through `&mut`.
					#  - For legacy tree-shaped operands (`HUnary(DEREF, ...)`), walk the tree.
					def _validate_mutable_derefs(node: H.HExpr) -> None:
						if hasattr(H, "HPlaceExpr") and isinstance(node, getattr(H, "HPlaceExpr")):
							cur = type_expr(node.base, used_as_value=False)
							for pr in node.projections:
								if isinstance(pr, H.HPlaceDeref):
									ptr_def = self.type_table.get(cur)
									if ptr_def.kind is not TypeKind.REF or not ptr_def.ref_mut:
										diagnostics.append(
											_tc_diag(
												message="cannot take &mut through *p unless p is a mutable reference (&mut T)",
												severity="error",
												span=getattr(expr, "loc", Span()),
											)
										)
										return
									if ptr_def.param_types:
										cur = ptr_def.param_types[0]
								elif isinstance(pr, H.HPlaceField):
									td = self.type_table.get(cur)
									if td.kind is TypeKind.STRUCT:
										info = self.type_table.struct_field(cur, pr.name)
										if info is not None:
											_, cur = info
								elif isinstance(pr, H.HPlaceIndex):
									td = self.type_table.get(cur)
									if td.kind is TypeKind.ARRAY and td.param_types:
										cur = td.param_types[0]
							return
						if isinstance(node, H.HUnary) and node.op is H.UnaryOp.DEREF:
							ptr_ty = type_expr(node.expr, used_as_value=False)
							ptr_def = self.type_table.get(ptr_ty)
							if ptr_def.kind is not TypeKind.REF or not ptr_def.ref_mut:
								diagnostics.append(
									_tc_diag(
										message="cannot take &mut through *p unless p is a mutable reference (&mut T)",
										severity="error",
										span=getattr(expr, "loc", Span()),
									)
								)
							_validate_mutable_derefs(node.expr)
						elif isinstance(node, H.HField):
							_validate_mutable_derefs(node.subject)
						elif isinstance(node, H.HIndex):
							_validate_mutable_derefs(node.subject)
							_validate_mutable_derefs(node.index)

					_validate_mutable_derefs(expr.subject)
					conflict = False
					for existing, kind in borrows_in_stmt.items():
						if not places_overlap(place, existing):
							continue
						conflict = True
						diagnostics.append(
							_tc_diag(
								message="conflicting borrows in the same statement: cannot take &mut while borrowed",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						break
					borrows_in_stmt[place] = "mut"
				else:
					conflict = False
					for existing, kind in borrows_in_stmt.items():
						if not places_overlap(place, existing):
							continue
						if kind == "mut":
							conflict = True
							diagnostics.append(
								_tc_diag(
									message="conflicting borrows in the same statement: cannot take & while mutably borrowed",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							break
					borrows_in_stmt.setdefault(place, "shared")

				ref_ty = self.type_table.ensure_ref_mut(inner_ty) if expr.is_mut else self.type_table.ensure_ref(inner_ty)
				return record_expr(expr, ref_ty)

			# Explicit move.
			#
			# `move <place>` is a surface marker for ownership transfer. For MVP we
			# keep it deliberately strict:
			# - the operand must be an addressable place (same as borrow),
			# - the operand must be a *plain* binding (no projections) to avoid
			#   partial-move semantics before we have a real lifetime/ownership model.
			#
			# The borrow checker enforces:
			# - no moving while borrowed, and
			# - use-after-move until reinitialization.
			if hasattr(H, "HMove") and isinstance(expr, getattr(H, "HMove")):
				def _base_lookup(hv: object) -> Optional[PlaceBase]:
					bid = getattr(hv, "binding_id", None)
					if bid is None:
						return None
					kind = binding_place_kind.get(bid, PlaceKind.LOCAL)
					name = hv.name if hasattr(hv, "name") else str(hv)
					return PlaceBase(kind=kind, local_id=bid, name=name)

				place = place_from_expr(expr.subject, base_lookup=_base_lookup)
				if place is None:
					diagnostics.append(
						_tc_diag(
							message="move operand must be an addressable place in MVP (local/param)",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				if place.projections:
					diagnostics.append(
						_tc_diag(
							message="move of a projected place is not supported in MVP; move a local/param or use swap/replace",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				if place.base.local_id is not None and not binding_mutable.get(place.base.local_id, False):
					diagnostics.append(
						_tc_diag(
							message="move requires an owned mutable binding declared with var",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				inner_ty = type_expr(expr.subject, used_as_value=False)
				if inner_ty is not None:
					td = self.type_table.get(inner_ty)
					if td.kind is TypeKind.REF:
						diagnostics.append(
							_tc_diag(
								message="cannot move from a reference type; move requires owned storage",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
				return record_expr(expr, inner_ty)

			# Explicit copy.
			if hasattr(H, "HCopy") and isinstance(expr, getattr(H, "HCopy")):
				def _base_lookup(hv: object) -> Optional[PlaceBase]:
					bid = getattr(hv, "binding_id", None)
					if bid is None:
						return None
					kind = binding_place_kind.get(bid, PlaceKind.LOCAL)
					name = hv.name if hasattr(hv, "name") else str(hv)
					return PlaceBase(kind=kind, local_id=bid, name=name)

				place = place_from_expr(expr.subject, base_lookup=_base_lookup)
				if place is None:
					diagnostics.append(
						_tc_diag(
							message="copy operand must be an addressable place in MVP (local/param/field/index)",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				inner_ty = type_expr(expr.subject, used_as_value=False, expected_type=expected_type)
				if inner_ty is not None and not self.type_table.is_copy(inner_ty):
					pretty = self._pretty_type_name(inner_ty, current_module=current_module_name)
					diagnostics.append(
						_tc_diag(
							message=f"cannot copy value of type '{pretty}': type is not Copy",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				return record_expr(expr, inner_ty)

			# Calls.
			if isinstance(expr, H.HCall):
				if getattr(expr, "type_args", None) and not (
					isinstance(expr.fn, H.HVar)
					or (hasattr(H, "HQualifiedMember") and isinstance(expr.fn, getattr(H, "HQualifiedMember")))
				):
					diagnostics.append(
						_tc_diag(
							message="E-TYPEARGS-NOT-ALLOWED: type arguments are only supported on named call targets",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				# Immediate-call lambda: typecheck the lambda body against the
				# argument types and any expected return type.
				if isinstance(expr.fn, H.HLambda):
					lam = expr.fn
					if getattr(expr, "kwargs", None):
						diagnostics.append(
							_tc_diag(
								message="keyword arguments are only supported for struct constructors in MVP",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					arg_types = [type_expr(a) for a in expr.args]
					if len(arg_types) != len(lam.params):
						diagnostics.append(
							_tc_diag(
								message=f"lambda expects {len(lam.params)} arguments, got {len(arg_types)}",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					lambda_ret_type: TypeId | None = None
					if getattr(lam, "ret_type", None) is not None:
						try:
							lambda_ret_type = resolve_opaque_type(lam.ret_type, self.type_table, module_id=current_module_name)
						except Exception:
							lambda_ret_type = None
					if expected_type is not None:
						lambda_ret_type = expected_type
					scope_env.append({})
					scope_bindings.append({})
					lambda_param_types: list[TypeId] = []
					for idx, param in enumerate(lam.params):
						if getattr(param, "binding_id", None) is None:
							param.binding_id = self._alloc_param_id()
						param_type: TypeId = self._unknown
						if getattr(param, "type", None) is not None:
							try:
								param_type = resolve_opaque_type(param.type, self.type_table, module_id=current_module_name)
							except Exception:
								param_type = self._unknown
							arg_ty = arg_types[idx]
							if arg_ty is not None and param_type != arg_ty:
								param_pretty = self._pretty_type_name(param_type, current_module=current_module_name)
								arg_pretty = self._pretty_type_name(arg_ty, current_module=current_module_name)
								diagnostics.append(
									_tc_diag(
										message=(
											f"lambda parameter '{param.name}' has type {param_pretty} "
											f"but argument is {arg_pretty}"
										),
										severity="error",
										span=getattr(param, "loc", Span()),
									)
								)
						else:
							arg_ty = arg_types[idx]
							if arg_ty is not None:
								param_type = arg_ty
						scope_env[-1][param.name] = param_type
						scope_bindings[-1][param.name] = param.binding_id
						binding_types[param.binding_id] = param_type
						binding_names[param.binding_id] = param.name
						binding_mutable[param.binding_id] = bool(getattr(param, "is_mutable", False))
						binding_place_kind[param.binding_id] = PlaceKind.PARAM
						lambda_param_types.append(param_type)
					capture_kinds: dict[int, str] = {}
					if lam.explicit_captures is not None:
						for cap in lam.explicit_captures:
							root_id = getattr(cap, "binding_id", None)
							if root_id is None:
								continue
							capture_kinds[int(root_id)] = cap.kind
							root_ty = binding_types.get(root_id, self._unknown)
							if cap.kind == "ref_mut":
								cap_ty = self.type_table.ensure_ref_mut(root_ty)
							elif cap.kind == "ref":
								cap_ty = self.type_table.ensure_ref(root_ty)
							else:
								cap_ty = root_ty
							scope_env[-1][cap.name] = cap_ty
							scope_bindings[-1][cap.name] = root_id
					if capture_kinds:
						explicit_capture_stack.append(capture_kinds)
					saved_return_type = return_type
					return_type = lambda_ret_type
					if lam.body_expr is not None:
						type_expr(lam.body_expr, expected_type=lambda_ret_type)
					if lam.body_block is not None:
						type_block(lam.body_block)
					return_type = saved_return_type
					if capture_kinds:
						explicit_capture_stack.pop()
					if not lam.captures:
						res = discover_captures(lam)
						diagnostics.extend(res.diagnostics)
						lam.captures = res.captures
					scope_env.pop()
					scope_bindings.pop()
					call_ret = lambda_ret_type or self._unknown
					can_throw = _lambda_can_throw(lam, call_info_by_callsite_id)
					lam.can_throw_effective = bool(can_throw)
					fn_ty = self.type_table.ensure_function(
						lambda_param_types,
						call_ret,
						can_throw=bool(can_throw),
					)
					expr_types[lam.node_id] = fn_ty
					record_call_info(
						expr,
						param_types=lambda_param_types,
						return_type=call_ret,
						can_throw=can_throw,
						target=CallTarget.indirect(lam.node_id),
					)
					return record_expr(expr, call_ret)
				# Qualified type member call: `TypeRef::member(args...)`.
				#
				# MVP: only variant constructors are supported, and the qualified
				# member must be called (bare `TypeRef::member` is rejected above).
				if hasattr(H, "HQualifiedMember") and isinstance(expr.fn, getattr(H, "HQualifiedMember")):
					qm = expr.fn
					kw_pairs = getattr(expr, "kwargs", []) or []

					base_te = getattr(qm, "base_type_expr", None)
					call_type_args = getattr(expr, "type_args", None) or []
					call_type_args_span = None
					type_arg_ids: list[TypeId] | None = None
					if call_type_args:
						first_loc = getattr(call_type_args[0], "loc", None)
						if first_loc is not None:
							call_type_args_span = Span.from_loc(first_loc)
						type_arg_ids = [
							resolve_opaque_type(t, self.type_table, module_id=current_module_name)
							for t in call_type_args
						]
					if (
						trait_index is not None
						and trait_impl_index is not None
						and base_te is not None
						and not (getattr(base_te, "args", None) or [])
					):
						trait_key = trait_key_from_expr(
							base_te,
							default_module=current_module_name,
							default_package=default_package,
							module_packages=module_packages,
						)
						if trait_key in trait_index.traits_by_id:
							if kw_pairs:
								diagnostics.append(
									_tc_diag(
										message="keyword arguments are not supported for UFCS method calls in MVP",
										severity="error",
										span=getattr(kw_pairs[0], "loc", getattr(expr, "loc", Span())),
									)
								)
								return record_expr(expr, self._unknown)
							if not expr.args:
								diagnostics.append(
									_tc_diag(
										message="UFCS call requires a receiver argument",
										severity="error",
										span=getattr(expr, "loc", Span()),
									)
								)
								return record_expr(expr, self._unknown)
							recv_ty = type_expr(expr.args[0])
							arg_types = [type_expr(a) for a in expr.args[1:]]
							receiver_place = _receiver_place(expr.args[0])
							receiver_is_lvalue = receiver_place is not None
							receiver_can_mut_borrow = _receiver_can_mut_borrow(expr.args[0], receiver_place)
							receiver_nominal = _unwrap_ref_type(recv_ty)
							receiver_base, receiver_args = _struct_base_and_args(receiver_nominal)
							recv_def = self.type_table.get(receiver_nominal)
							recv_type_param_id = recv_def.type_param_id if recv_def.kind is TypeKind.TYPEVAR else None
							recv_type_key = None
							if recv_type_param_id is not None:
								recv_type_key = _normalize_type_key(
									type_key_from_typeid(self.type_table, receiver_nominal)
								)
							visible_set = set(visible_modules or (current_module,))
							missing_visible = set()
							if trait_impl_index.missing_modules:
								missing_visible = trait_impl_index.missing_modules & visible_set
							if missing_visible:
								mod_names = [
									trait_impl_index.module_names_by_id.get(mid, str(mid))
									for mid in sorted(missing_visible)
								]
								raise ResolutionError(
									"missing impl metadata for visible modules: " + ", ".join(mod_names),
									span=getattr(expr, "loc", Span()),
								)
							trait_candidates: list[
								tuple[
									MethodResolution,
									TraitImplCandidate,
									Tuple[TypeId, ...],
									Tuple[TypeId, ...],
									Tuple[TypeId, ...],
									int,
								]
							] = []
							trait_require_info: dict[object, tuple[parser_ast.TraitExpr, dict[object, object], str, dict[TypeParamId, tuple[str, int]]]] = {}
							trait_hidden: list[tuple[CallableDecl, TraitImplCandidate, TraitKey]] = []
							trait_require_failures: list[ProofFailure] = []
							trait_type_arg_counts: set[int] = set()
							trait_saw_typed_nongeneric = False
							trait_saw_infer_incomplete = False
							trait_infer_failures: list[InferResult] = []
							if trait_index.is_missing(trait_key):
								raise ResolutionError(
									f"missing trait metadata for '{_trait_label(trait_key)}'",
									span=getattr(expr, "loc", Span()),
								)
							if trait_index.has_method(trait_key, qm.member):
								if recv_type_param_id is not None:
									if (
										(recv_type_param_id, trait_key) in fn_require_assumed
										or (recv_type_key, trait_key) in fn_require_assumed
									):
										trait_def = trait_index.traits_by_id.get(trait_key)
										method_sig = None
										if trait_def is not None:
											for method in getattr(trait_def, "methods", []) or []:
												if getattr(method, "name", None) == qm.member:
													method_sig = method
													break
										if method_sig is not None:
											type_param_map = {"Self": recv_type_param_id}
											param_type_ids: list[TypeId] = []
											param_names: list[str] = []
											for param in list(getattr(method_sig, "params", []) or []):
												param_names.append(param.name)
												if param.type_expr is None:
													if param.name != "self":
														param_type_ids = []
														break
													param_type_ids.append(receiver_nominal)
													continue
												param_type_ids.append(
													resolve_opaque_type(
														param.type_expr,
														self.type_table,
														module_id=trait_key.module or current_module_name,
														type_params=type_param_map,
													)
												)
											if param_type_ids:
												ret_id = resolve_opaque_type(
													method_sig.return_type,
													self.type_table,
													module_id=trait_key.module or current_module_name,
													type_params=type_param_map,
												)
												self_mode = SelfMode.SELF_BY_VALUE
												if param_type_ids:
													param0 = self.type_table.get(param_type_ids[0])
													if param0.kind is TypeKind.REF:
														self_mode = (
															SelfMode.SELF_BY_REF_MUT
															if param0.ref_mut
															else SelfMode.SELF_BY_REF
														)
												trait_sig = FnSignature(
													name=method_sig.name,
													method_name=method_sig.name,
													param_type_ids=param_type_ids,
													return_type_id=ret_id,
													param_names=param_names if param_names else None,
													is_method=True,
													self_mode={SelfMode.SELF_BY_VALUE: "value", SelfMode.SELF_BY_REF: "ref", SelfMode.SELF_BY_REF_MUT: "ref_mut"}[
														self_mode
													],
													module=trait_key.module or current_module_name,
												)
												inst_arg_types = [recv_ty, *arg_types]
												if trait_sig.param_type_ids:
													inst_arg_types = [
														recv_ty,
														*_coerce_args_for_params(
															list(trait_sig.param_type_ids[1:]),
															arg_types,
														),
													]
												inst_res = _instantiate_sig_with_subst(
													sig=trait_sig,
													arg_types=inst_arg_types,
													expected_type=expected_type,
													explicit_type_args=type_arg_ids,
													allow_infer=True,
													diag_span=call_type_args_span or getattr(expr, "loc", Span()),
													call_kind="method",
													call_name=method_sig.name,
													receiver_type=recv_ty,
												)
												if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS and type_arg_ids:
													trait_saw_typed_nongeneric = True
												elif inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT and type_arg_ids:
													if inst_res.error.expected_count is not None:
														trait_type_arg_counts.add(inst_res.error.expected_count)
												elif inst_res.error and inst_res.error.kind in {InferErrorKind.CANNOT_INFER, InferErrorKind.CONFLICT}:
													trait_saw_infer_incomplete = True
													trait_infer_failures.append(inst_res)
												elif not inst_res.error and inst_res.inst_params and inst_res.inst_return is not None:
													trait_decl = CallableDecl(
														callable_id=-1,
														name=method_sig.name,
														kind=CallableKind.METHOD_TRAIT,
														module_id=0,
														visibility=Visibility.public(),
														signature=CallableSignature(
															param_types=tuple(param_type_ids),
															result_type=ret_id,
														),
														fn_id=FunctionId(
															module=trait_key.module or current_module_name,
															name=method_sig.name,
															ordinal=0,
														),
														impl_target_type_id=None,
														self_mode=self_mode,
													)
													ok, autoborrow = _receiver_compat(recv_ty, inst_res.inst_params[0], self_mode)
													if ok and _args_match_params(list(inst_res.inst_params[1:]), arg_types):
														pref = _receiver_preference(
															self_mode,
															receiver_is_lvalue=receiver_is_lvalue,
															receiver_can_mut_borrow=receiver_can_mut_borrow,
															autoborrow=autoborrow,
														)
														if pref is not None:
															trait_candidates.append(
																(
																	MethodResolution(
																		decl=trait_decl,
																		receiver_autoborrow=autoborrow,
																		result_type=inst_res.inst_return,
																	),
																	TraitImplCandidate(
																		fn_id=trait_decl.fn_id,
																		name=method_sig.name,
																		trait=trait_key,
																		def_module_id=0,
																		is_pub=True,
																		impl_id=-1,
																		impl_loc=None,
																		method_loc=Span.from_loc(getattr(method_sig, "loc", None)),
																		require_expr=None,
																	),
																	(),
																	tuple(inst_res.subst.args) if inst_res.subst is not None else (),
																	tuple(inst_res.inst_params),
																	pref,
																)
															)
								for cand in trait_impl_index.get_candidates(trait_key, receiver_base, qm.member):
									decl = callable_registry.get_by_fn_id(cand.fn_id) if callable_registry else None
									if decl is None:
										continue
									if cand.def_module_id not in visible_set:
										trait_hidden.append((decl, cand, trait_key))
										continue
									if not cand.is_pub and cand.def_module_id != current_module:
										trait_hidden.append((decl, cand, trait_key))
										continue
									sig = signatures_by_id.get(decl.fn_id) if signatures_by_id is not None else None
									if sig is None:
										continue
									if sig.param_type_ids is None and sig.param_types is not None:
										local_type_params = {p.name: p.id for p in sig.type_params}
										param_type_ids = [
											resolve_opaque_type(
												p,
												self.type_table,
												module_id=sig.module,
												type_params=local_type_params,
											)
											for p in sig.param_types
										]
										sig = replace(sig, param_type_ids=param_type_ids)
									if sig.return_type_id is None and sig.return_type is not None:
										local_type_params = {p.name: p.id for p in sig.type_params}
										ret_id = resolve_opaque_type(
											sig.return_type,
											self.type_table,
											module_id=sig.module,
											type_params=local_type_params,
										)
										sig = replace(sig, return_type_id=ret_id)
									if sig.param_type_ids is None or sig.return_type_id is None:
										continue
									impl_subst: Subst | None = None
									impl_req_expr: parser_ast.TraitExpr | None = None
									impl_subst_map: dict[object, object] = {}
									if sig.impl_target_type_args:
										impl_type_params = list(getattr(sig, "impl_type_params", []) or [])
										if not impl_type_params:
											if receiver_args != sig.impl_target_type_args:
												continue
											impl_subst = None
										else:
											impl_subst = _match_impl_type_args(
												template_args=sig.impl_target_type_args,
												recv_args=receiver_args,
												impl_type_params=impl_type_params,
											)
											if impl_subst is None:
												continue
										if impl_subst is not None:
											inst_param_ids = [
												apply_subst(t, impl_subst, self.type_table) for t in sig.param_type_ids
											]
											inst_return_id = apply_subst(sig.return_type_id, impl_subst, self.type_table)
											sig = replace(sig, param_type_ids=inst_param_ids, return_type_id=inst_return_id)
										if cand.require_expr is not None:
											def_mod = (
												decl.fn_id.module
												if decl.fn_id is not None and decl.fn_id.module
												else current_module_name
											)
											world = visible_trait_world or global_trait_world
											if world is None:
												continue
											subjects: set[object] = set()
											_collect_trait_subjects(cand.require_expr, subjects)
											subst: dict[object, object] = {}
											if impl_subst is not None and impl_type_params:
												for tp in impl_type_params:
													idx = int(tp.id.index)
													if idx < len(impl_subst.args):
														key = _normalize_type_key(
															type_key_from_typeid(self.type_table, impl_subst.args[idx])
														)
														subst[tp.id] = key
														subst[tp.name] = key
											for subj in subjects:
												if subj in subst:
													continue
												if isinstance(subj, str):
													try:
														ty_expr = parser_ast.TypeExpr(
															name=subj,
															args=[],
															module_alias=None,
															module_id=None,
															loc=getattr(cand.require_expr, "loc", None),
														)
														ty_id = resolve_opaque_type(
															ty_expr, self.type_table, module_id=def_mod
														)
														subst[subj] = _normalize_type_key(
															type_key_from_typeid(self.type_table, ty_id)
														)
													except Exception:
														continue
											env = TraitEnv(
												default_module=def_mod,
												default_package=default_package,
												module_packages=module_packages or {},
												assumed_true=set(fn_require_assumed),
											)
											res = prove_expr(world, env, subst, cand.require_expr)
											if res.status is not ProofStatus.PROVED:
												failure = _require_failure(
													req_expr=cand.require_expr,
													subst=subst,
													origin=ObligationOrigin(
														kind=ObligationOriginKind.IMPL_REQUIRE,
														label=f"impl for trait '{trait_key.name}'",
														span=cand.impl_loc,
													),
													span=getattr(expr, "loc", Span()),
													env=env,
													world=world,
													result=res,
												)
												if failure is not None:
													trait_require_failures.append(failure)
												continue
											impl_req_expr = cand.require_expr
											impl_subst_map = subst

									inst_arg_types = [recv_ty, *arg_types]
									if sig.param_type_ids:
										inst_arg_types = [
											recv_ty,
											*_coerce_args_for_params(
												list(sig.param_type_ids[1:]),
												arg_types,
											),
										]
									inst_res = _instantiate_sig_with_subst(
										sig=sig,
										arg_types=inst_arg_types,
										expected_type=expected_type,
										explicit_type_args=type_arg_ids,
										allow_infer=True,
										diag_span=call_type_args_span or getattr(expr, "loc", Span()),
										call_kind="method",
										call_name=qm.member,
										receiver_type=recv_ty,
									)
									if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS and type_arg_ids:
										trait_saw_typed_nongeneric = True
										continue
									if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT and type_arg_ids:
										if inst_res.error.expected_count is not None:
											trait_type_arg_counts.add(inst_res.error.expected_count)
										continue
									if inst_res.error and inst_res.error.kind in {InferErrorKind.CANNOT_INFER, InferErrorKind.CONFLICT}:
										trait_saw_infer_incomplete = True
										trait_infer_failures.append(inst_res)
										continue
									if inst_res.error:
										continue

									if inst_res.inst_params is None or inst_res.inst_return is None:
										continue
									inst_subst = inst_res.subst
									inst_params = inst_res.inst_params
									inst_return = inst_res.inst_return
									method_req_expr: parser_ast.TraitExpr | None = None
									method_subst_map: dict[object, object] = {}
									if decl.fn_id is not None:
										world = visible_trait_world or global_trait_world
										req = _require_for_fn(decl.fn_id)
										if req is not None:
											subjects = set()
											_collect_trait_subjects(req, subjects)
											subst = {}
											if inst_subst is not None and sig.type_params:
												for idx, tp in enumerate(sig.type_params):
													if tp.id in subjects or tp.name in subjects:
														if idx < len(inst_subst.args):
															key = _normalize_type_key(
																type_key_from_typeid(self.type_table, inst_subst.args[idx])
															)
															subst[tp.id] = key
															subst[tp.name] = key
											env = TraitEnv(
												default_module=decl.fn_id.module or current_module_name,
												default_package=default_package,
												module_packages=module_packages or {},
												assumed_true=set(fn_require_assumed),
											)
											res = prove_expr(world, env, subst, req)
											if res.status is not ProofStatus.PROVED:
												failure = _require_failure(
													req_expr=req,
													subst=subst,
													origin=ObligationOrigin(
														kind=ObligationOriginKind.CALLEE_REQUIRE,
														label=f"method '{qm.member}'",
														span=Span.from_loc(getattr(req, "loc", None)),
													),
													span=getattr(expr, "loc", Span()),
													env=env,
													world=world,
													result=res,
												)
												if failure is not None:
													trait_require_failures.append(failure)
												continue
											method_req_expr = req
											method_subst_map = subst
									if len(inst_params) - 1 != len(arg_types):
										continue
									ok, autoborrow = _receiver_compat(recv_ty, inst_params[0], decl.self_mode)
									if not ok:
										continue
									if _args_match_params(list(inst_params[1:]), arg_types):
										pref = _receiver_preference(
											decl.self_mode,
											receiver_is_lvalue=receiver_is_lvalue,
											receiver_can_mut_borrow=receiver_can_mut_borrow,
											autoborrow=autoborrow,
										)
										if pref is None:
											continue
										impl_args = tuple(impl_subst.args) if impl_subst is not None else ()
										fn_args = tuple(inst_subst.args) if inst_subst is not None else ()
										trait_candidates.append(
											(
												MethodResolution(
													decl=decl,
													receiver_autoborrow=autoborrow,
													result_type=inst_return,
												),
												cand,
												impl_args,
												fn_args,
												tuple(inst_params),
												pref,
											)
										)
										cand_req = _combine_require(impl_req_expr, method_req_expr)
										if cand_req is not None:
											merged_subst = dict(impl_subst_map)
											merged_subst.update(method_subst_map)
											cand_key = _candidate_key_for_decl(decl)
											scope_map = _param_scope_map(sig)
											trait_require_info[cand_key] = (
												cand_req,
												merged_subst,
												decl.fn_id.module or current_module_name,
												scope_map,
											)

								if trait_candidates:
									best_pref = min(pref for _res, _cand, _impl_args, _fn_args, _inst_params, pref in trait_candidates)
									best = [item for item in trait_candidates if item[5] == best_pref]
									best = _dedupe_by_key(
										best,
										lambda item: _candidate_key_for_decl(item[0].decl),
									)
									if len(best) > 1:
										best = _pick_most_specific_items(
											best,
											lambda item: _candidate_key_for_decl(item[0].decl),
											trait_require_info,
										)
									if len(best) > 1:
										labels: list[str] = []
										notes: list[str] = []
										seen_labels: set[str] = set()

										def _trait_ambig_key(
											item: tuple[
												MethodResolution,
												TraitImplCandidate,
												Tuple[TypeId, ...],
												Tuple[TypeId, ...],
												Tuple[TypeId, ...],
												int,
											],
										) -> tuple[str, str, int]:
											res, cand, _impl_args, _fn_args, _inst_params, _pref = item
											trait_label = (
												f"{cand.trait.module}.{cand.trait.name}"
												if cand.trait.module
												else cand.trait.name
											)
											mod_label = (
												res.decl.fn_id.module
												if res.decl.fn_id and res.decl.fn_id.module
												else str(res.decl.module_id)
											)
											return (trait_label, mod_label, int(cand.impl_id))

										for res, cand, _impl_args, _fn_args, _inst_params, _pref in sorted(
											best, key=_trait_ambig_key
										):
											trait_label = (
												f"{cand.trait.module}.{cand.trait.name}"
												if cand.trait.module
												else cand.trait.name
											)
											mod_label = (
												res.decl.fn_id.module
												if res.decl.fn_id and res.decl.fn_id.module
												else str(res.decl.module_id)
											)
											label = f"{trait_label}@{mod_label}"
											if label not in seen_labels:
												labels.append(label)
												seen_labels.add(label)
											chain_note = _visibility_note(cand.def_module_id)
											if chain_note:
												notes.append(f"{label} {chain_note}")
										label_str = ", ".join(labels)
										recv_label = _label_typeid(recv_ty)
										raise ResolutionError(
											f"ambiguous method '{qm.member}' for receiver {recv_label} and args {arg_types}; candidates from traits: {label_str}",
											span=getattr(expr, "loc", Span()),
											notes=notes,
											code="E-METHOD-AMBIGUOUS",
										)
									resolution, _cand, impl_args, fn_args, inst_params, _pref = best[0]
									call_resolutions[expr.node_id] = resolution
									result_type = resolution.result_type or resolution.decl.signature.result_type
									target_fn_id = resolution.decl.fn_id
									if target_fn_id is None:
										raise ResolutionError(
											f"missing function id for method '{expr.method_name}' (compiler bug)",
											span=getattr(expr, "loc", Span()),
										)
									sig_for_throw = signatures_by_id.get(target_fn_id) if signatures_by_id is not None else None
									if sig_for_throw is None:
										call_can_throw = True
									elif sig_for_throw.declared_can_throw is None:
										diagnostics.append(
											_tc_diag(
												message="internal: signature missing declared_can_throw (checker bug)",
												severity="error",
												span=Span(),
											)
										)
										call_can_throw = True
									else:
										call_can_throw = bool(sig_for_throw.declared_can_throw)
									applied = _apply_method_boundary(
										expr,
										target_fn_id=target_fn_id,
										sig_for_throw=sig_for_throw,
										call_can_throw=call_can_throw,
									)
									if applied is None:
										return record_expr(expr, self._unknown)
									target_fn_id, call_can_throw = applied
									updated_arg_types, had_autoborrow_error = _apply_autoborrow_args(
										expr.args,
										arg_types,
										list(inst_params[1:]),
										span=getattr(expr, "loc", Span()),
									)
									arg_types = updated_arg_types
									if had_autoborrow_error:
										record_method_call_info(
											expr,
											param_types=list(inst_params),
											return_type=result_type or self._unknown,
											can_throw=call_can_throw,
											target=target_fn_id,
										)
										return record_expr(expr, self._unknown)
									record_method_call_info(
										expr,
										param_types=list(inst_params),
										return_type=result_type or self._unknown,
										can_throw=call_can_throw,
										target=target_fn_id,
									)
									record_instantiation(
										callsite_id=getattr(expr, "callsite_id", None),
										target_fn_id=resolution.decl.fn_id,
										impl_args=impl_args,
										fn_args=fn_args,
									)
									return record_expr(expr, result_type)
							if trait_hidden:
								mod_names: list[str] = []
								notes: list[str] = []
								for decl, cand, _ in trait_hidden:
									mod = (
										decl.fn_id.module
										if decl.fn_id is not None and decl.fn_id.module
										else str(cand.def_module_id)
									)
									trait_name = f"{trait_key.module}.{trait_key.name}" if trait_key.module else trait_key.name
									mod_names.append(f"{trait_name}@{mod}")
									span = cand.method_loc or cand.impl_loc
									chain_note = _visibility_note(cand.def_module_id)
									if span and span.line is not None:
										loc = f"{span.file}:{span.line}:{span.column}" if span.file else f"line {span.line}"
										note = f"candidate in trait '{trait_name}' at {loc}"
									else:
										note = f"candidate in trait '{trait_name}'"
									if chain_note:
										note = f"{note}; {chain_note}"
									notes.append(note)
								mod_list = ", ".join(sorted(set(mod_names)))
								diagnostics.append(
									_tc_diag(
										message=(
											f"method '{qm.member}' exists but is not visible here; "
											f"candidates from traits: {mod_list}"
										),
										severity="error",
										span=getattr(expr, "loc", Span()),
										notes=notes,
									)
								)
								return record_expr(expr, self._unknown)
							if type_arg_ids and trait_type_arg_counts:
								exp = ", ".join(str(n) for n in sorted(trait_type_arg_counts))
								raise ResolutionError(
									f"type argument count mismatch for method '{qm.member}': expected one of ({exp}), got {len(type_arg_ids)}",
									span=call_type_args_span,
								)
							if type_arg_ids and trait_saw_typed_nongeneric:
								raise ResolutionError(
									f"type arguments require a generic method signature for '{qm.member}'",
									span=call_type_args_span,
								)
							if trait_saw_infer_incomplete:
								failure = trait_infer_failures[0] if trait_infer_failures else None
								ctx = failure.context if failure and failure.context is not None else InferContext(
									call_kind="method",
									call_name=qm.member,
									span=call_type_args_span or getattr(expr, "loc", Span()),
									type_param_ids=[],
									type_param_names={},
									param_types=[],
									param_names=None,
									return_type=None,
									arg_types=[],
								)
								res = failure if failure is not None else InferResult(
									ok=False,
									subst=None,
									inst_params=None,
									inst_return=None,
									error=InferError(kind=InferErrorKind.CANNOT_INFER),
									context=ctx,
								)
								msg, notes = _format_infer_failure(ctx, res)
								raise ResolutionError(msg, span=call_type_args_span, notes=notes)
							if trait_require_failures:
								failure = _pick_best_failure(trait_require_failures)
								diagnostics.append(
									_tc_diag(
										message=_format_failure_message(failure) if failure is not None else "trait requirements not met",
										code=_failure_code(failure) if failure is not None else None,
										severity="error",
										span=(failure.obligation.span if failure is not None else None)
										or getattr(expr, "loc", Span()),
										notes=list(getattr(failure.obligation, "notes", []) or []) if failure is not None else None,
									)
								)
								return record_expr(expr, self._unknown)
							recv_label = _label_typeid(recv_ty)
							raise ResolutionError(
								f"no matching method '{qm.member}' for receiver {recv_label} and args {arg_types}",
								span=getattr(expr, "loc", Span()),
							)
					if base_te is not None and call_type_args:
						if getattr(base_te, "args", []) or []:
							diagnostics.append(
								_tc_diag(
									message="E-QMEM-DUP-TYPEARGS: qualified member may specify type arguments only once",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						base_te = replace(base_te, args=list(call_type_args))
					base_tid = resolve_opaque_type(base_te, self.type_table, module_id=current_module_name, allow_generic_base=True)
					# TypeRef without explicit module context may refer to lang.core
					# variants (e.g., `Optional`). Prefer that base when present.
					try:
						base_def = self.type_table.get(base_tid)
					except Exception:
						base_def = None
					if base_def is None or base_def.kind is not TypeKind.VARIANT:
						name = getattr(base_te, "name", None)
						if isinstance(name, str):
							vb = self.type_table.get_variant_base(module_id=current_module_name, name=name) or self.type_table.get_variant_base(
								module_id="lang.core", name=name
							)
							if vb is not None:
								base_tid = vb
								base_def = self.type_table.get(base_tid)

					if base_def is None or base_def.kind is not TypeKind.VARIANT:
						diagnostics.append(
							_tc_diag(
								message="E-QMEM-NONVARIANT: qualified member base is not a variant type",
								severity="error",
								span=getattr(qm, "loc", getattr(expr, "loc", Span())),
							)
						)
						return record_expr(expr, self._unknown)

					schema = self.type_table.get_variant_schema(base_tid)
					if schema is None:
						diagnostics.append(
							_tc_diag(
								message="internal: missing variant schema for qualified member base (compiler bug)",
								severity="error",
								span=getattr(qm, "loc", getattr(expr, "loc", Span())),
							)
						)
						return record_expr(expr, self._unknown)

					# Validate and map ctor arguments. For MVP:
					# - positional args require exact arity
					# - named args require all fields, no mixing, no unknown/dup/missing
					arm_schema = next((a for a in schema.arms if a.name == qm.member), None)
					if arm_schema is None:
						ctors = self._format_ctor_signature_list(schema=schema, instance=None, current_module=current_module_name)
						diagnostics.append(
							_tc_diag(
								message=(
									f"E-QMEM-NO-CTOR: constructor '{qm.member}' not found in variant "
									f"'{self._pretty_type_name(base_tid, current_module=current_module_name)}'. "
									f"Available constructors: {', '.join(ctors)}"
								),
								severity="error",
								span=getattr(qm, "loc", getattr(expr, "loc", Span())),
							)
						)
						return record_expr(expr, self._unknown)

					field_names = [f.name for f in arm_schema.fields]
					mapped_types: list[TypeId | None] = [None] * len(field_names)
					mapped_spans: list[Span] = [getattr(expr, "loc", Span())] * len(field_names)

					if kw_pairs and expr.args:
						diagnostics.append(
							_tc_diag(
								message=(
									f"E-QMEM-MIXED-ARGS: constructor '{qm.member}' does not allow mixing positional "
									"and named arguments"
								),
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)

					if kw_pairs:
						# Typecheck keyword values (in written order) and place them in field order.
						for kw in kw_pairs:
							try:
								field_idx = field_names.index(kw.name)
							except ValueError:
								diagnostics.append(
									_tc_diag(
										message=f"unknown field '{kw.name}' for constructor '{qm.member}'",
										severity="error",
										span=getattr(kw, "loc", getattr(expr, "loc", Span())),
									)
								)
								continue
							if mapped_types[field_idx] is not None:
								diagnostics.append(
									_tc_diag(
										message=f"duplicate field '{kw.name}' for constructor '{qm.member}'",
										severity="error",
										span=getattr(kw, "loc", getattr(expr, "loc", Span())),
									)
								)
								continue
							mapped_types[field_idx] = type_expr(kw.value)
							mapped_spans[field_idx] = getattr(kw.value, "loc", getattr(expr, "loc", Span()))
					else:
						# Positional arguments in declaration order.
						if len(expr.args) != len(field_names):
							diagnostics.append(
								_tc_diag(
									message=f"E-QMEM-ARITY: constructor '{qm.member}' expects {len(field_names)} arguments, got {len(expr.args)}",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						for idx, a in enumerate(expr.args):
							mapped_types[idx] = type_expr(a)
							mapped_spans[idx] = getattr(a, "loc", getattr(expr, "loc", Span()))

					for idx, ty in enumerate(mapped_types):
						if ty is None:
							diagnostics.append(
								_tc_diag(
									message=f"missing field '{field_names[idx]}' for constructor '{qm.member}'",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)

					arg_types = [t if t is not None else self._unknown for t in mapped_types]

					# Build a constructor template and instantiate via the shared helper.
					type_params: list[TypeParam] = []
					typevar_ids: list[TypeId] = []
					if schema.type_params:
						owner = FunctionId(module="lang.__internal", name=f"__variant_{schema.module_id}::{schema.name}", ordinal=0)
						for idx, tp_name in enumerate(schema.type_params):
							param_id = TypeParamId(owner=owner, index=idx)
							type_params.append(TypeParam(id=param_id, name=tp_name, span=None))
							typevar_ids.append(self.type_table.ensure_typevar(param_id, name=tp_name))

					type_cache: dict[tuple[TypeId, tuple[TypeId, ...]], TypeId] = {}

					def _lower_generic_expr(expr: GenericTypeExpr) -> TypeId:
						if expr.param_index is not None:
							idx = int(expr.param_index)
							if 0 <= idx < len(typevar_ids):
								return typevar_ids[idx]
							return self._unknown
						name = expr.name
						if name in FIXED_WIDTH_TYPE_NAMES:
							if _fixed_width_allowed(expr.module_id or schema.module_id or current_module_name):
								return self.type_table.ensure_named(name, module_id=expr.module_id or schema.module_id)
							diagnostics.append(
								_tc_diag(
									message=(
										f"fixed-width type '{name}' is reserved in v1; "
										"use Int/Uint/Float or Byte"
									),
									code="E_FIXED_WIDTH_RESERVED",
									severity="error",
									span=Span(),
								)
							)
							return self._unknown
						if name == "Int":
							return self._int
						if name == "Uint":
							return self._uint
						if name == "Byte":
							return self.type_table.ensure_byte()
						if name == "Bool":
							return self._bool
						if name == "Float":
							return self._float
						if name == "String":
							return self._string
						if name == "Void":
							return self._void
						if name == "Error":
							return self._error
						if name == "DiagnosticValue":
							return self._dv
						if name == "Unknown":
							return self._unknown
						if name in {"&", "&mut"} and expr.args:
							inner = _lower_generic_expr(expr.args[0])
							return self.type_table.ensure_ref_mut(inner) if name == "&mut" else self.type_table.ensure_ref(inner)
						if name == "Array" and expr.args:
							elem = _lower_generic_expr(expr.args[0])
							span = Span.from_loc(getattr(expr.args[0], "loc", None)) if expr.args else Span()
							if _reject_zst_array(elem, span=span):
								return self._unknown
							return self.type_table.new_array(elem)
						origin_mod = expr.module_id or schema.module_id
						base_id = (
							self.type_table.get_nominal(kind=TypeKind.STRUCT, module_id=origin_mod, name=name)
							or self.type_table.get_nominal(kind=TypeKind.VARIANT, module_id=origin_mod, name=name)
							or self.type_table.ensure_named(name, module_id=origin_mod)
						)
						if expr.args:
							if base_id in self.type_table.struct_bases:
								schema = self.type_table.struct_bases.get(base_id)
								if schema is not None and not schema.type_params:
									diagnostics.append(
										_tc_diag(
											message=f"type '{name}' is not generic",
											code="E-TYPE-NOT-GENERIC",
											severity="error",
											span=Span.from_loc(getattr(expr, "loc", None)),
										)
									)
									return self._unknown
							elif base_id in self.type_table.variant_schemas:
								schema = self.type_table.variant_schemas.get(base_id)
								if schema is not None and not schema.type_params:
									diagnostics.append(
										_tc_diag(
											message=f"type '{name}' is not generic",
											code="E-TYPE-NOT-GENERIC",
											severity="error",
											span=Span.from_loc(getattr(expr, "loc", None)),
										)
									)
									return self._unknown
							else:
								diagnostics.append(
									_tc_diag(
										message=f"unknown generic type '{name}'",
										code="E-TYPE-UNKNOWN",
										severity="error",
										span=Span.from_loc(getattr(expr, "loc", None)),
									)
								)
								return self._unknown
						if expr.args:
							arg_ids = [_lower_generic_expr(a) for a in expr.args]
							if base_id in self.type_table.variant_schemas:
								if any(self.type_table.get(a).kind is TypeKind.TYPEVAR for a in arg_ids):
									key = (base_id, tuple(arg_ids))
									if key not in type_cache:
										td = self.type_table.get(base_id)
										type_cache[key] = self.type_table._add(
											TypeKind.VARIANT,
											td.name,
											list(arg_ids),
											register_named=False,
											module_id=td.module_id,
										)
									return type_cache[key]
								return self.type_table.ensure_instantiated(base_id, arg_ids)
						return base_id

					param_type_ids: list[TypeId] = []
					for f in arm_schema.fields:
						param_type_ids.append(_lower_generic_expr(f.type_expr))
					ret_type_id = base_tid
					if schema.type_params:
						ret_type_id = _lower_generic_expr(
							GenericTypeExpr.named(schema.name, args=[GenericTypeExpr.param(i) for i in range(len(schema.type_params))], module_id=schema.module_id)
						)
					ctor_sig = FnSignature(
						name=qm.member,
						param_type_ids=param_type_ids,
						return_type_id=ret_type_id,
						type_params=type_params,
						module=current_module_name,
					)

					explicit_type_args: list[TypeId] | None = None
					if getattr(base_te, "args", []) or []:
						explicit_type_args = [
							resolve_opaque_type(t, self.type_table, module_id=current_module_name)
							for t in (base_te.args or [])
						]
					elif call_type_args:
						explicit_type_args = [
							resolve_opaque_type(t, self.type_table, module_id=current_module_name)
							for t in call_type_args
						]
					inst_res = _instantiate_sig(
						sig=ctor_sig,
						arg_types=arg_types,
						expected_type=expected_type,
						explicit_type_args=explicit_type_args,
						allow_infer=True,
						diag_span=call_type_args_span or getattr(expr, "loc", Span()),
						call_kind="ctor",
						call_name=qm.member,
					)
					if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT:
						span = call_type_args_span or getattr(expr, "loc", Span())
						diagnostics.append(
							_tc_diag(
								message=(
									f"E-QMEM-TYPEARGS-ARITY: expected {len(schema.type_params)} type arguments, got {len(explicit_type_args or [])}"
								),
								severity="error",
								span=span,
							)
						)
						return record_expr(expr, self._unknown)
					if inst_res.error and inst_res.error.kind in {InferErrorKind.CANNOT_INFER, InferErrorKind.CONFLICT}:
						msg, notes = _format_infer_failure(
							inst_res.context
							or InferContext(
								call_kind="ctor",
								call_name=qm.member,
								span=getattr(expr, "loc", Span()),
								type_param_ids=[],
								type_param_names={},
								param_types=[],
								param_names=None,
								return_type=None,
								arg_types=[],
							),
							inst_res,
						)
						hint = (
							"Hint: qualify the constructor (e.g., `Optional<T>::None()` or `Optional::None<type T>()`)."
						)
						notes = [*notes, hint, "underconstrained"]
						diagnostics.append(
							_tc_diag(
								message=f"E-QMEM-CANNOT-INFER: {msg} (underconstrained). {hint}",
								severity="error",
								span=getattr(expr, "loc", Span()),
								notes=notes,
							)
						)
						return record_expr(expr, self._unknown)
					if inst_res.error:
						msg, notes = _format_infer_failure(
							inst_res.context
							or InferContext(
								call_kind="ctor",
								call_name=qm.member,
								span=getattr(expr, "loc", Span()),
								type_param_ids=[],
								type_param_names={},
								param_types=[],
								param_names=None,
								return_type=None,
								arg_types=[],
							),
							inst_res,
						)
						diagnostics.append(
							_tc_diag(message=msg, severity="error", span=getattr(expr, "loc", Span()), notes=notes)
						)
						return record_expr(expr, self._unknown)
					if inst_res.inst_params is None or inst_res.inst_return is None:
						return record_expr(expr, self._unknown)
					inst_return = inst_res.inst_return

					if len(inst_res.inst_params) != len(field_names):
						diagnostics.append(
							_tc_diag(
								message=f"E-QMEM-ARITY: constructor '{qm.member}' expects {len(field_names)} arguments, got {len(inst_res.inst_params)}",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)

					for idx, want in enumerate(inst_res.inst_params):
						arg_expr: H.HExpr | None = None
						if kw_pairs:
							for kw in kw_pairs:
								if kw.name == field_names[idx]:
									arg_expr = kw.value
									break
						else:
							arg_expr = expr.args[idx] if idx < len(expr.args) else None
						have = mapped_types[idx]
						if arg_expr is not None:
							have = type_expr(arg_expr, expected_type=want)
						if have is not None and have != want:
							diagnostics.append(
								_tc_diag(
									message=(
										f"constructor '{qm.member}' field '{field_names[idx]}' type mismatch "
										f"(have {self.type_table.get(have).name}, expected {self.type_table.get(want).name})"
									),
									severity="error",
									span=mapped_spans[idx],
								)
							)

					inst_tid = inst_return
					td_ret = self.type_table.get(inst_tid)
					if td_ret.kind is TypeKind.VARIANT and schema.type_params:
						args = list(td_ret.param_types)
						if all(self.type_table.get(a).kind is not TypeKind.TYPEVAR for a in args):
							base_inst = self.type_table.variant_instances.get(base_tid)
							base_id = base_inst.base_id if base_inst is not None else base_tid
							inst_tid = self.type_table.ensure_instantiated(base_id, args)
					inst = self.type_table.get_variant_instance(inst_tid)
					if inst is None:
						diagnostics.append(
							_tc_diag(
								message="internal: variant instance missing for qualified member base (compiler bug)",
								severity="error",
								span=getattr(qm, "loc", getattr(expr, "loc", Span())),
							)
						)
						return record_expr(expr, self._unknown)
					arm_def = inst.arms_by_name.get(qm.member)
					if arm_def is None:
						ctors = self._format_ctor_signature_list(
							schema=schema, instance=inst, current_module=current_module_name
						)
						diagnostics.append(
							_tc_diag(
								message=(
									f"E-QMEM-NO-CTOR: constructor '{qm.member}' not found in variant "
									f"'{self._pretty_type_name(inst_tid, current_module=current_module_name)}'. "
									f"Available constructors: {', '.join(ctors)}"
								),
								severity="error",
								span=getattr(qm, "loc", getattr(expr, "loc", Span())),
							)
						)
						return record_expr(expr, self._unknown)
					if len(arm_def.field_types) != len(field_names):
						diagnostics.append(
							_tc_diag(
								message="internal: variant ctor schema/type mismatch (compiler bug)",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, inst_tid)
					for idx, want in enumerate(arm_def.field_types):
						arg_expr: H.HExpr | None = None
						# Re-typecheck with expected field types for better diagnostics.
						if kw_pairs:
							# Find the kw expression for this field (if any) for span.
							for kw in kw_pairs:
								if kw.name == field_names[idx]:
									arg_expr = kw.value
									break
						else:
							arg_expr = expr.args[idx] if idx < len(expr.args) else None
						have = mapped_types[idx]
						if arg_expr is not None:
							have = type_expr(arg_expr, expected_type=want)
						if have is not None and have != want:
							diagnostics.append(
								_tc_diag(
									message=(
										f"constructor '{qm.member}' field '{field_names[idx]}' type mismatch "
										f"(have {self.type_table.get(have).name}, expected {self.type_table.get(want).name})"
									),
									severity="error",
									span=mapped_spans[idx],
								)
							)
					record_call_info(
						expr,
						param_types=list(arm_def.field_types),
						return_type=inst_tid,
						can_throw=False,
						target=CallTarget.indirect(expr.node_id),
					)
					return record_expr(expr, inst_tid)

				# Variant constructor call in expression position.
				#
				# MVP rule: constructor calls require an *expected* variant type from
				# context (annotation, parameter type, return type, etc.). Without an
				# expected type we do not guess which variant the constructor belongs to.
				if isinstance(expr.fn, H.HVar) and expected_type is not None:
					try:
						exp_def = self.type_table.get(expected_type)
					except Exception:
						exp_def = None
					if exp_def is not None and exp_def.kind is TypeKind.VARIANT:
						inst = self.type_table.get_variant_instance(expected_type)
						if inst is not None and expr.fn.name in inst.arms_by_name:
							arm_def = inst.arms_by_name[expr.fn.name]
							kw_pairs = getattr(expr, "kwargs", []) or []
							if kw_pairs and expr.args:
								diagnostics.append(
									_tc_diag(
										message=(
											f"constructor '{arm_def.name}' does not allow mixing positional and named arguments"
										),
										severity="error",
										span=getattr(expr, "loc", Span()),
									)
								)
								return record_expr(expr, self._unknown)

							field_names = list(getattr(arm_def, "field_names", []) or [])
							field_types = list(arm_def.field_types)
							if len(field_names) != len(field_types):
								diagnostics.append(
									_tc_diag(
										message="internal: variant ctor schema/type mismatch (compiler bug)",
										severity="error",
										span=getattr(expr, "loc", Span()),
									)
								)
								return record_expr(expr, expected_type)

							mapped_types: list[TypeId | None] = [None] * len(field_names)
							mapped_spans: list[Span] = [getattr(expr, "loc", Span())] * len(field_names)

							if kw_pairs:
								for kw in kw_pairs:
									try:
										field_idx = field_names.index(kw.name)
									except ValueError:
										diagnostics.append(
											_tc_diag(
												message=f"unknown field '{kw.name}' for constructor '{arm_def.name}'",
												severity="error",
												span=getattr(kw, "loc", getattr(expr, "loc", Span())),
											)
										)
										continue
									if mapped_types[field_idx] is not None:
										diagnostics.append(
											_tc_diag(
												message=f"duplicate field '{kw.name}' for constructor '{arm_def.name}'",
												severity="error",
												span=getattr(kw, "loc", getattr(expr, "loc", Span())),
											)
										)
										continue
									mapped_types[field_idx] = type_expr(kw.value, expected_type=field_types[field_idx])
									mapped_spans[field_idx] = getattr(kw.value, "loc", getattr(expr, "loc", Span()))
							else:
								if len(expr.args) != len(field_types):
									diagnostics.append(
										_tc_diag(
											message=(
												f"constructor '{arm_def.name}' expects {len(field_types)} arguments, got {len(expr.args)}"
											),
											severity="error",
											span=getattr(expr, "loc", Span()),
										)
									)
									return record_expr(expr, self._unknown)
								for idx, (arg, want) in enumerate(zip(expr.args, field_types)):
									mapped_types[idx] = type_expr(arg, expected_type=want)
									mapped_spans[idx] = getattr(arg, "loc", getattr(expr, "loc", Span()))

							for idx, want in enumerate(field_types):
								if mapped_types[idx] is None:
									diagnostics.append(
										_tc_diag(
											message=f"missing field '{field_names[idx]}' for constructor '{arm_def.name}'",
											severity="error",
											span=getattr(expr, "loc", Span()),
										)
									)
									continue
								have = mapped_types[idx]
								if have is not None and have != want:
									diagnostics.append(
										_tc_diag(
											message=(
												f"constructor '{arm_def.name}' field '{field_names[idx]}' type mismatch "
												f"(have {self.type_table.get(have).name}, expected {self.type_table.get(want).name})"
											),
											severity="error",
											span=mapped_spans[idx],
										)
									)
							record_call_info(
								expr,
								param_types=field_types,
								return_type=expected_type,
								can_throw=False,
								target=CallTarget.indirect(expr.node_id),
							)
							return record_expr(expr, expected_type)

				# Always type fn and args first for side-effects/subexpressions.
				#
				# Special-case struct constructors: `Point(1, 2)` uses a call-like
				# surface form but is not a function call. In that case we must *not*
				# type-check `expr.fn` as a normal expression (`Point` is a type name,
				# not a value), otherwise we'd emit a misleading "unknown variable"
				# diagnostic before the constructor path has a chance to fire.
				should_type_fn = True
				if isinstance(expr.fn, H.HVar):
					# Builtins that look like calls but are not normal function values.
					# We must not type-check `expr.fn` as a variable, otherwise we'd emit
					# misleading "unknown variable" diagnostics before the builtin path
					# fires.
					if expr.fn.name in ("byte_length",):
						should_type_fn = False
					struct_ctor_tid: TypeId | None = None
					if expr.fn.module_id is not None:
						struct_ctor_tid = self.type_table.get_nominal(
							kind=TypeKind.STRUCT, module_id=expr.fn.module_id, name=expr.fn.name
						)
					else:
						struct_ctor_tid = self.type_table.get_nominal(
							kind=TypeKind.STRUCT, module_id=current_module_name, name=expr.fn.name
						) or self.type_table.find_unique_nominal_by_name(kind=TypeKind.STRUCT, name=expr.fn.name)
					known_callable = False
					if callable_registry is not None:
						candidates = callable_registry.get_free_candidates(
							name=expr.fn.name,
							visible_modules=_visible_modules_for_free_call(expr.fn.module_id),
							include_private_in=current_module if expr.fn.module_id is None else None,
						)
						known_callable = bool(candidates)
					is_struct_ctor = struct_ctor_tid is not None and not known_callable
					if is_struct_ctor:
						should_type_fn = False
					if callable_registry is not None:
						should_type_fn = False
				if should_type_fn:
					type_expr(expr.fn)
				kw_pairs = getattr(expr, "kwargs", []) or []
				# When a call signature is known by name, use its parameter types as
				# expected types for arguments. This enables constructor calls inside
				# arguments, e.g. `takes_opt(Some(1))` where `takes_opt` expects
				# `Optional<Int>`.
				arg_types: list[TypeId] = []
				arg_types = [type_expr(a) for a in expr.args]
				kw_types = [type_expr(k.value) for k in kw_pairs]
				def _std_mem_intrinsic_kind(fn_id: FunctionId | None) -> IntrinsicKind | None:
					if fn_id is None or fn_id.module != "std.mem":
						return None
					if fn_id.name == "swap":
						return IntrinsicKind.SWAP
					if fn_id.name == "replace":
						return IntrinsicKind.REPLACE
					return None

				if isinstance(expr.fn, H.HVar) and expr.fn.name == "byte_length" and len(expr.args) == 1:
					if kw_pairs:
						diagnostics.append(
							_tc_diag(
								message=f"{expr.fn.name} does not support keyword arguments",
								severity="error",
								span=kw_pairs[0].loc if hasattr(kw_pairs[0], "loc") else getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					param_type = self.type_table.ensure_ref(self._string)
					updated_arg_types, had_autoborrow_error = _apply_autoborrow_args(
						expr.args,
						arg_types,
						[param_type],
						span=getattr(expr, "loc", Span()),
					)
					if had_autoborrow_error:
						record_call_info(
							expr,
							param_types=[param_type],
							return_type=self._uint,
							can_throw=False,
							target=CallTarget.intrinsic(IntrinsicKind.BYTE_LENGTH),
						)
						return record_expr(expr, self._unknown)
					arg_ty = updated_arg_types[0] if updated_arg_types else None
					if arg_ty is None:
						return record_expr(expr, self._unknown)
					if arg_ty != param_type:
						td_arg = self.type_table.get(arg_ty)
						pretty = td_arg.name if arg_ty is not None else "Unknown"
						diagnostics.append(
							_tc_diag(
								message=f"{expr.fn.name}(x) requires &String operands (have '{pretty}')",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					ret_ty = self._uint
					intrinsic_kind = IntrinsicKind.BYTE_LENGTH
					record_call_info(
						expr,
						param_types=[param_type],
						return_type=ret_ty,
						can_throw=False,
						target=CallTarget.intrinsic(intrinsic_kind),
					)
					return record_expr(expr, ret_ty)

				if isinstance(expr.fn, H.HVar) and expr.fn.name in ("string_eq", "string_concat") and len(expr.args) == 2:
					if kw_pairs:
						diagnostics.append(
							_tc_diag(
								message=f"{expr.fn.name} does not support keyword arguments",
								severity="error",
								span=kw_pairs[0].loc if hasattr(kw_pairs[0], "loc") else getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					if len(arg_types) != 2:
						diagnostics.append(
							_tc_diag(
								message=f"{expr.fn.name} expects 2 arguments, got {len(arg_types)}",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					if any(t is None or t != self._string for t in arg_types):
						diagnostics.append(
							_tc_diag(
								message=f"{expr.fn.name} requires String operands",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					if expr.fn.name == "string_eq":
						ret_ty = self._bool
						intrinsic_kind = IntrinsicKind.STRING_EQ
					else:
						ret_ty = self._string
						intrinsic_kind = IntrinsicKind.STRING_CONCAT
					record_call_info(
						expr,
						param_types=[self._string, self._string],
						return_type=ret_ty,
						can_throw=False,
						target=CallTarget.intrinsic(intrinsic_kind),
					)
					return record_expr(expr, ret_ty)

				# Struct constructor: `Point(1, 2)` constructs a `struct Point`.
				#
				# In v1, struct initialization uses a call-like surface form. This is a
				# language-level construct (not a function call) and must work even when
				# a callable registry is present.
				#
				# We only treat the call as a constructor when there is no known callable
				# signature for the same name (to avoid ambiguity if user code later
				# allows a free function named `Point`).
				def _resolve_struct_ctor_type_id(name: str, module_name: str | None) -> TypeId | None:
					if module_name is not None:
						return self.type_table.get_nominal(kind=TypeKind.STRUCT, module_id=module_name, name=name)
					# Unqualified constructor: resolve in the current module first.
					local = self.type_table.get_nominal(kind=TypeKind.STRUCT, module_id=current_module_name, name=name)
					if local is not None:
						return local
					# Fallback: accept only when the name is unique across all modules.
					return self.type_table.find_unique_nominal_by_name(kind=TypeKind.STRUCT, name=name)

				struct_id: TypeId | None = None
				struct_name: str | None = None
				call_type_args = getattr(expr, "type_args", None) or []
				type_arg_ids: list[TypeId] | None = None
				call_type_args_span = None
				if call_type_args:
					first_loc = getattr(call_type_args[0], "loc", None)
					if first_loc is not None:
						call_type_args_span = Span.from_loc(first_loc)
					type_arg_ids = [
						resolve_opaque_type(t, self.type_table, module_id=current_module_name)
						for t in call_type_args
					]
				if isinstance(expr.fn, H.HVar):
					struct_id = _resolve_struct_ctor_type_id(expr.fn.name, getattr(expr.fn, "module_id", None))
					struct_name = expr.fn.name

				known_callable = False
				if callable_registry is not None and isinstance(expr.fn, H.HVar):
					candidates = callable_registry.get_free_candidates(
						name=expr.fn.name,
						visible_modules=_visible_modules_for_free_call(expr.fn.module_id),
						include_private_in=current_module if expr.fn.module_id is None else None,
					)
					known_callable = bool(candidates)
				if not known_callable and isinstance(expr.fn, H.HVar) and struct_id is not None:
					struct_schema = self.type_table.get_struct_schema(struct_id)
					if struct_schema is not None and struct_schema.type_params:
						if not type_arg_ids:
							inferred: list[TypeId] | None = None
							if expected_type is not None:
								exp_inst = self.type_table.get_struct_instance(expected_type)
								if exp_inst is not None and exp_inst.base_id == struct_id:
									inferred = list(exp_inst.type_args)
							if inferred is None:
								field_names: list[str] = []
								field_types: list[TypeId] = []
								param_ids = self.type_table.get_struct_type_param_ids(struct_id) or []
								typevar_ids: list[TypeId] = []
								for idx, tp_name in enumerate(struct_schema.type_params):
									if idx < len(param_ids):
										typevar_ids.append(self.type_table.ensure_typevar(param_ids[idx], name=tp_name))

								type_cache: dict[tuple[TypeId, tuple[TypeId, ...]], TypeId] = {}

								def _lower_generic_expr(expr: GenericTypeExpr) -> TypeId:
									if expr.param_index is not None:
										idx = int(expr.param_index)
										if 0 <= idx < len(typevar_ids):
											return typevar_ids[idx]
										return self._unknown
									name = expr.name
									if name in FIXED_WIDTH_TYPE_NAMES:
										if _fixed_width_allowed(expr.module_id or struct_schema.module_id or current_module_name):
											return self.type_table.ensure_named(name, module_id=expr.module_id or struct_schema.module_id)
										diagnostics.append(
											_tc_diag(
												message=(
													f"fixed-width type '{name}' is reserved in v1; "
													"use Int/Uint/Float or Byte"
												),
												code="E_FIXED_WIDTH_RESERVED",
												severity="error",
												span=Span(),
											)
										)
										return self._unknown
									if name == "Int":
										return self._int
									if name == "Uint":
										return self._uint
									if name == "Byte":
										return self.type_table.ensure_byte()
									if name == "Bool":
										return self._bool
									if name == "Float":
										return self._float
									if name == "String":
										return self._string
									if name == "Void":
										return self._void
									if name == "Error":
										return self._error
									if name == "DiagnosticValue":
										return self._dv
									if name == "Unknown":
										return self._unknown
									if name in {"&", "&mut"} and expr.args:
										inner = _lower_generic_expr(expr.args[0])
										return self.type_table.ensure_ref_mut(inner) if name == "&mut" else self.type_table.ensure_ref(inner)
									if name == "Array" and expr.args:
										elem = _lower_generic_expr(expr.args[0])
										span = Span.from_loc(getattr(expr.args[0], "loc", None)) if expr.args else Span()
										if _reject_zst_array(elem, span=span):
											return self._unknown
										return self.type_table.new_array(elem)
									origin_mod = expr.module_id or struct_schema.module_id
									base_id = (
										self.type_table.get_nominal(kind=TypeKind.STRUCT, module_id=origin_mod, name=name)
										or self.type_table.get_nominal(kind=TypeKind.VARIANT, module_id=origin_mod, name=name)
										or self.type_table.ensure_named(name, module_id=origin_mod)
									)
									if expr.args:
										if base_id in self.type_table.struct_bases:
											base_schema = self.type_table.struct_bases.get(base_id)
											if base_schema is not None and not base_schema.type_params:
												diagnostics.append(
													_tc_diag(
														message=f"type '{name}' is not generic",
														code="E-TYPE-NOT-GENERIC",
														severity="error",
														span=Span.from_loc(getattr(expr, "loc", None)),
													)
												)
												return self._unknown
										elif base_id in self.type_table.variant_schemas:
											base_schema = self.type_table.variant_schemas.get(base_id)
											if base_schema is not None and not base_schema.type_params:
												diagnostics.append(
													_tc_diag(
														message=f"type '{name}' is not generic",
														code="E-TYPE-NOT-GENERIC",
														severity="error",
														span=Span.from_loc(getattr(expr, "loc", None)),
													)
												)
												return self._unknown
										else:
											diagnostics.append(
												_tc_diag(
													message=f"unknown generic type '{name}'",
													code="E-TYPE-UNKNOWN",
													severity="error",
													span=Span.from_loc(getattr(expr, "loc", None)),
												)
											)
											return self._unknown
									if expr.args:
										arg_ids = [_lower_generic_expr(a) for a in expr.args]
										if base_id in self.type_table.variant_schemas:
											if any(self.type_table.get(a).kind is TypeKind.TYPEVAR for a in arg_ids):
												key = (base_id, tuple(arg_ids))
												if key not in type_cache:
													td = self.type_table.get(base_id)
													type_cache[key] = self.type_table._add(
														TypeKind.VARIANT,
														td.name,
														list(arg_ids),
														register_named=False,
														module_id=td.module_id,
													)
												return type_cache[key]
											return self.type_table.ensure_instantiated(base_id, arg_ids)
										if base_id in self.type_table.struct_bases:
											if any(self.type_table.get(a).kind is TypeKind.TYPEVAR for a in arg_ids):
												key = (base_id, tuple(arg_ids))
												if key not in type_cache:
													td = self.type_table.get(base_id)
													type_cache[key] = self.type_table._add(
														TypeKind.STRUCT,
														td.name,
														list(arg_ids),
														register_named=False,
														module_id=td.module_id,
													)
												return type_cache[key]
											return self.type_table.ensure_struct_instantiated(base_id, arg_ids)
									return base_id

								field_names = [f.name for f in struct_schema.fields]
								field_types = [_lower_generic_expr(f.type_expr) for f in struct_schema.fields]
								mapped_types: list[Optional[TypeId]] = [None] * len(field_types)
								for idx, ty in enumerate(arg_types):
									if idx < len(mapped_types):
										mapped_types[idx] = ty
								for kw, kw_ty in zip(kw_pairs, kw_types):
									if kw.name in field_names:
										field_idx = field_names.index(kw.name)
										mapped_types[field_idx] = kw_ty
								template_types: list[TypeId] = []
								template_field_names: list[str] = []
								actual_types: list[TypeId] = []
								for field_name, tmpl, have in zip(field_names, field_types, mapped_types):
									if have is None:
										continue
									template_types.append(tmpl)
									template_field_names.append(field_name)
									actual_types.append(have)
								if template_types:
									type_params: list[TypeParam] = []
									for idx, tp_name in enumerate(struct_schema.type_params):
										if idx < len(param_ids):
											type_params.append(TypeParam(id=param_ids[idx], name=tp_name, span=None))
									if type_params:
										ctx = InferContext(
											call_kind="ctor",
											call_name=struct_name or "<struct>",
											span=call_type_args_span or getattr(expr, "loc", Span()),
											type_param_ids=[p.id for p in type_params],
											type_param_names={p.id: p.name for p in type_params},
											param_types=template_types,
											param_names=template_field_names,
											return_type=None,
											arg_types=actual_types,
										)
										res = _infer(ctx)
										if res.ok and res.subst is not None:
											inferred = list(res.subst.args)
										elif res.error is not None:
											msg, notes = _format_infer_failure(ctx, res)
											diagnostics.append(
												_tc_diag(
													message=msg,
													severity="error",
													span=call_type_args_span or getattr(expr, "loc", Span()),
													notes=notes,
												)
											)
											return record_expr(expr, self._unknown)
							if inferred:
								type_arg_ids = inferred
							else:
								type_param_names = {
									pid: name for pid, name in zip(param_ids, struct_schema.type_params)
								}
								ctx = InferContext(
									call_kind="ctor",
									call_name=struct_name or "<struct>",
									span=call_type_args_span or getattr(expr, "loc", Span()),
									type_param_ids=list(param_ids),
									type_param_names=type_param_names,
									param_types=[],
									param_names=None,
									return_type=None,
									arg_types=[],
								)
								res = InferResult(
									ok=False,
									subst=None,
									inst_params=None,
									inst_return=None,
									error=InferError(
										kind=InferErrorKind.CANNOT_INFER,
										missing_params=list(param_ids),
									),
									context=ctx,
								)
								msg, notes = _format_infer_failure(ctx, res)
								diagnostics.append(
									_tc_diag(
										message=msg,
										severity="error",
										span=call_type_args_span or getattr(expr, "loc", Span()),
										notes=notes,
									)
								)
								return record_expr(expr, self._unknown)
						try:
							struct_id = self.type_table.ensure_struct_instantiated(struct_id, type_arg_ids)
						except ValueError as err:
							diagnostics.append(
								_tc_diag(
									message=str(err),
									severity="error",
									span=call_type_args_span or getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						_enforce_struct_requires(struct_id, call_type_args_span or getattr(expr, "loc", Span()))
					elif type_arg_ids:
						diagnostics.append(
							_tc_diag(
								message=f"type arguments require a generic struct for '{struct_name}'",
								severity="error",
								span=call_type_args_span or getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					struct_def = self.type_table.get(struct_id)
					if struct_def.kind is not TypeKind.STRUCT:
						diagnostics.append(
							_tc_diag(
								message=f"internal: struct schema '{struct_name}' is not a STRUCT TypeId",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					struct_inst = self.type_table.get_struct_instance(struct_id)
					if struct_inst is not None:
						field_names = list(struct_inst.field_names)
						field_types = list(struct_inst.field_types)
					else:
						field_names = list(struct_def.field_names or [])
						field_types = list(struct_def.param_types)
					record_call_info(
						expr,
						param_types=field_types,
						return_type=struct_id,
						can_throw=False,
						target=CallTarget.indirect(expr.node_id),
					)
					if len(field_names) != len(field_types):
						diagnostics.append(
							_tc_diag(
								message=f"internal: struct '{struct_name}' schema/type mismatch",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, struct_id)
					if len(arg_types) > len(field_types):
						diagnostics.append(
							_tc_diag(
								message=f"struct '{struct_name}' constructor expects {len(field_types)} args, got {len(arg_types)}",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, struct_id)

					# Map positional + keyword args to fields in declaration order.
					mapped_types: list[Optional[TypeId]] = [None] * len(field_types)
					mapped_spans: list[Span] = [getattr(expr, "loc", Span())] * len(field_types)

					for idx, (ty, arg_expr) in enumerate(zip(arg_types, expr.args)):
						mapped_types[idx] = ty
						mapped_spans[idx] = getattr(arg_expr, "loc", getattr(expr, "loc", Span()))

					for kw, kw_ty in zip(kw_pairs, kw_types):
						try:
							field_idx = field_names.index(kw.name)
						except ValueError:
							diagnostics.append(
								_tc_diag(
									message=f"unknown field '{kw.name}' for struct '{struct_name}'",
									severity="error",
									span=getattr(kw, "loc", getattr(expr, "loc", Span())),
								)
							)
							continue
						if field_idx < len(arg_types):
							diagnostics.append(
								_tc_diag(
									message=f"duplicate field '{kw.name}' for struct '{struct_name}' (already provided positionally)",
									severity="error",
									span=getattr(kw, "loc", getattr(expr, "loc", Span())),
								)
							)
							continue
						if mapped_types[field_idx] is not None:
							diagnostics.append(
								_tc_diag(
									message=f"duplicate field '{kw.name}' for struct '{struct_name}'",
									severity="error",
									span=getattr(kw, "loc", getattr(expr, "loc", Span())),
								)
							)
							continue
						mapped_types[field_idx] = kw_ty
						mapped_spans[field_idx] = getattr(kw.value, "loc", getattr(expr, "loc", Span()))

					for idx, (have, want) in enumerate(zip(mapped_types, field_types)):
						if have is None:
							diagnostics.append(
								_tc_diag(
									message=f"missing field '{field_names[idx]}' for struct '{struct_name}' constructor",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							continue
						if have != want:
							diagnostics.append(
								_tc_diag(
									message=(
										f"struct '{struct_name}' field '{field_names[idx]}' type mismatch "
										f"(have {self.type_table.get(have).name}, expected {self.type_table.get(want).name})"
									),
									severity="error",
									span=mapped_spans[idx],
								)
							)
					return record_expr(expr, struct_id)

				# Call through a function-typed local value.
				if isinstance(expr.fn, H.HVar) and expr.fn.binding_id is not None:
					fn_ty = binding_types.get(expr.fn.binding_id)
					if fn_ty is not None and self.type_table.get(fn_ty).kind is TypeKind.FUNCTION:
						if getattr(expr, "type_args", None):
							diagnostics.append(
								_tc_diag(
									message="type arguments are not supported on function values; apply them on the named function",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						if kw_pairs:
							diagnostics.append(
								_tc_diag(
									message="keyword arguments are not supported on function values in MVP",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						td_fn = self.type_table.get(fn_ty)
						fn_params = list(td_fn.param_types[:-1]) if td_fn.param_types else []
						fn_ret = td_fn.param_types[-1] if td_fn.param_types else self._unknown
						if len(fn_params) != len(arg_types):
							diagnostics.append(
								_tc_diag(
									message=f"function value expects {len(fn_params)} arguments, got {len(arg_types)}",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, fn_ret)
						updated_arg_types, had_autoborrow_error = _apply_autoborrow_args(
							expr.args,
							arg_types,
							fn_params,
							span=getattr(expr, "loc", Span()),
						)
						arg_types = updated_arg_types
						if had_autoborrow_error:
							record_call_info(
								expr,
								param_types=fn_params,
								return_type=fn_ret,
								can_throw=td_fn.can_throw(),
								target=CallTarget.indirect(expr.fn.node_id),
							)
							return record_expr(expr, fn_ret)
						for want, have in zip(fn_params, arg_types):
							if have is not None and want != have:
								diagnostics.append(
									_tc_diag(
										message=(
											f"function value argument type mismatch (have {self.type_table.get(have).name}, "
											f"expected {self.type_table.get(want).name})"
										),
										severity="error",
										span=getattr(expr, "loc", Span()),
								)
							)
						record_call_info(
							expr,
							param_types=fn_params,
							return_type=fn_ret,
							can_throw=td_fn.can_throw(),
							target=CallTarget.indirect(expr.fn.node_id),
						)
						return record_expr(expr, fn_ret)

				if kw_pairs:
					diagnostics.append(
						_tc_diag(
							message="keyword arguments are only supported for struct constructors in MVP",
							severity="error",
							span=getattr(kw_pairs[0], "loc", getattr(expr, "loc", Span())),
						)
					)
					return record_expr(expr, self._unknown)

				# Try registry-based resolution when available.
				if callable_registry and isinstance(expr.fn, H.HVar):
					try:
						type_arg_ids: List[TypeId] | None = None
						call_type_args_span = None
						if getattr(expr, "type_args", None):
							type_arg_ids = [
								resolve_opaque_type(t, self.type_table, module_id=current_module_name)
								for t in (expr.type_args or [])
							]
							first_loc = getattr((expr.type_args or [None])[0], "loc", None)
							call_type_args_span = Span.from_loc(first_loc)
						decl, inst_sig, inst_subst = _resolve_free_call_with_require(
							name=expr.fn.name,
							module_name=getattr(expr.fn, "module_id", None),
							arg_types=arg_types,
							call_type_args=type_arg_ids,
							call_type_args_span=call_type_args_span or getattr(expr, "loc", Span()),
							expected_type=expected_type,
						)
						updated_arg_types, had_autoborrow_error = _apply_autoborrow_args(
							expr.args,
							arg_types,
							list(inst_sig.param_types),
							span=getattr(expr, "loc", Span()),
						)
						arg_types = updated_arg_types
						if had_autoborrow_error:
							call_can_throw = True
							if decl.fn_id is not None and signatures_by_id is not None:
								sig_for_throw = signatures_by_id.get(decl.fn_id)
								if sig_for_throw is not None:
									if sig_for_throw.declared_can_throw is None:
										diagnostics.append(
											_tc_diag(
												message="internal: signature missing declared_can_throw (checker bug)",
												severity="error",
												span=Span(),
											)
										)
										call_can_throw = True
									else:
										call_can_throw = bool(sig_for_throw.declared_can_throw)
							target = (
								CallTarget.direct(decl.fn_id)
								if decl.fn_id is not None
								else CallTarget.indirect(expr.fn.node_id)
							)
							record_call_info(
								expr,
								param_types=list(inst_sig.param_types),
								return_type=inst_sig.result_type,
								can_throw=call_can_throw,
								target=target,
							)
							return record_expr(expr, inst_sig.result_type or self._unknown)
						if decl.fn_id is not None:
							expr.fn.module_id = decl.fn_id.module
						call_resolutions[expr.node_id] = decl
						intrinsic_kind = _std_mem_intrinsic_kind(decl.fn_id)
						if intrinsic_kind is not None:
							diag_start = len(diagnostics)
							if kw_pairs:
								diagnostics.append(
									_tc_diag(
										message=f"{decl.fn_id.name} does not support keyword arguments",
										severity="error",
										span=kw_pairs[0].loc if hasattr(kw_pairs[0], "loc") else getattr(expr, "loc", Span()),
									)
								)
							def _base_lookup(hv: object) -> Optional[PlaceBase]:
								bid = getattr(hv, "binding_id", None)
								if bid is None:
									return None
								kind = binding_place_kind.get(bid, PlaceKind.LOCAL)
								name = hv.name if hasattr(hv, "name") else str(hv)
								return PlaceBase(kind=kind, local_id=bid, name=name)

							def _require_writable_place(place_expr: H.HExpr, span: Span) -> None:
								place = place_from_expr(place_expr, base_lookup=_base_lookup)
								if place is None:
									return
								# If the place includes a deref projection, mutability is provided by
								# the reference type (`&mut`) rather than the base binding being `var`.
								has_deref = any(isinstance(p, DerefProj) for p in place.projections)
								if not has_deref and place.base.local_id is not None and not binding_mutable.get(
									place.base.local_id, False
								):
									diagnostics.append(
										_tc_diag(
											message="write requires an owned mutable binding declared with var",
											severity="error",
											span=span,
										)
									)
								# Validate deref projections are through `&mut` refs.
								if has_deref and hasattr(H, "HPlaceExpr") and isinstance(place_expr, getattr(H, "HPlaceExpr")):
									cur = type_expr(place_expr.base)
									for pr in place_expr.projections:
										if isinstance(pr, H.HPlaceDeref):
											if cur is None:
												break
											ptr_def = self.type_table.get(cur)
											if ptr_def.kind is not TypeKind.REF or not ptr_def.ref_mut:
												diagnostics.append(
													_tc_diag(
														message=(
															"cannot write through *p unless p is a mutable reference (&mut T)"
														),
														severity="error",
														span=span,
													)
												)
												return
											if ptr_def.param_types:
												cur = ptr_def.param_types[0]
											continue
										if isinstance(pr, H.HPlaceField):
											if cur is None:
												break
											td = self.type_table.get(cur)
											if td.kind is TypeKind.STRUCT:
												info = self.type_table.struct_field(cur, pr.name)
												if info is not None:
													_, cur = info
											continue
										if isinstance(pr, H.HPlaceIndex):
											if cur is None:
												break
											td = self.type_table.get(cur)
											if td.kind is TypeKind.ARRAY and td.param_types:
												cur = td.param_types[0]
											continue
							arg0 = arg_types[0] if len(arg_types) > 0 else None
							arg1 = arg_types[1] if len(arg_types) > 1 else None
							if intrinsic_kind is IntrinsicKind.SWAP:
								if len(expr.args) != 2:
									diagnostics.append(
										_tc_diag(
											message="swap expects exactly 2 arguments",
											severity="error",
											span=getattr(expr, "loc", Span()),
										)
									)
									return record_expr(expr, self._void)
								a, b = expr.args
								pa = place_from_expr(a, base_lookup=_base_lookup)
								pb = place_from_expr(b, base_lookup=_base_lookup)
								if pa is None:
									diagnostics.append(
										_tc_diag(
											message="swap argument 0 must be an addressable place",
											severity="error",
											span=getattr(a, "loc", getattr(expr, "loc", Span())),
										)
									)
								if pb is None:
									diagnostics.append(
										_tc_diag(
											message="swap argument 1 must be an addressable place",
											severity="error",
											span=getattr(b, "loc", getattr(expr, "loc", Span())),
										)
									)
								if pa is not None:
									_require_writable_place(a, getattr(a, "loc", getattr(expr, "loc", Span())))
								if pb is not None:
									_require_writable_place(b, getattr(b, "loc", getattr(expr, "loc", Span())))
								if arg0 is not None and arg1 is not None and arg0 != arg1:
									diagnostics.append(
										_tc_diag(
											message="swap requires both places to have the same type",
											severity="error",
											span=getattr(expr, "loc", Span()),
										)
									)
								if pa is not None and pb is not None and places_overlap(pa, pb):
									diagnostics.append(
										_tc_diag(
											message="swap operands must be distinct non-overlapping places",
											severity="error",
											span=getattr(expr, "loc", Span()),
										)
									)
								if len(diagnostics) > diag_start:
									return record_expr(expr, self._void)
								param_types = (
									arg0 if arg0 is not None else self._unknown,
									arg1 if arg1 is not None else self._unknown,
								)
								record_call_info(
									expr,
									param_types=list(param_types),
									return_type=self._void,
									can_throw=False,
									target=CallTarget.intrinsic(intrinsic_kind),
								)
								return record_expr(expr, self._void)
							if intrinsic_kind is IntrinsicKind.REPLACE:
								if len(expr.args) != 2:
									diagnostics.append(
										_tc_diag(
											message="replace expects exactly 2 arguments",
											severity="error",
											span=getattr(expr, "loc", Span()),
										)
									)
									return record_expr(expr, self._unknown)
								place_expr, new_val_expr = expr.args
								place = place_from_expr(place_expr, base_lookup=_base_lookup)
								if place is None:
									diagnostics.append(
										_tc_diag(
											message="replace argument 0 must be an addressable place",
											severity="error",
											span=getattr(place_expr, "loc", getattr(expr, "loc", Span())),
										)
									)
									return record_expr(expr, self._unknown)
								_require_writable_place(place_expr, getattr(place_expr, "loc", getattr(expr, "loc", Span())))
								place_ty = arg0
								new_ty = arg1
								if place_ty is not None and new_ty is not None and place_ty != new_ty:
									diagnostics.append(
										_tc_diag(
											message="replace requires the new value to have the same type as the place",
											severity="error",
											span=getattr(new_val_expr, "loc", getattr(expr, "loc", Span())),
										)
									)
								if len(diagnostics) > diag_start:
									return record_expr(expr, place_ty if place_ty is not None else self._unknown)
								param_types = (
									arg0 if arg0 is not None else self._unknown,
									arg1 if arg1 is not None else self._unknown,
								)
								record_call_info(
									expr,
									param_types=list(param_types),
									return_type=place_ty if place_ty is not None else self._unknown,
									can_throw=False,
									target=CallTarget.intrinsic(intrinsic_kind),
								)
								return record_expr(expr, place_ty if place_ty is not None else self._unknown)
						sig_for_throw = signatures_by_id.get(decl.fn_id) if decl.fn_id and signatures_by_id else None
						if decl.fn_id is None:
							diagnostics.append(
								_tc_diag(
									message=(
										f"internal: resolved callable '{expr.fn.name}' missing FunctionId "
										"(checker bug)"
									),
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						target_fn_id = decl.fn_id
						if sig_for_throw is None:
							call_can_throw = True
						elif sig_for_throw.declared_can_throw is None:
							diagnostics.append(
								_tc_diag(
									message="internal: signature missing declared_can_throw (checker bug)",
									severity="error",
									span=Span(),
								)
							)
							call_can_throw = True
						else:
							call_can_throw = bool(sig_for_throw.declared_can_throw)
						if _force_boundary_can_throw(sig_for_throw, target_fn_id):
							call_can_throw = True
						record_call_info(
							expr,
							param_types=list(inst_sig.param_types),
							return_type=inst_sig.result_type,
							can_throw=call_can_throw,
							target=CallTarget.direct(target_fn_id),
						)
						record_instantiation(
							callsite_id=getattr(expr, "callsite_id", None),
							target_fn_id=target_fn_id,
							impl_args=(),
							fn_args=tuple(inst_subst.args) if inst_subst is not None else (),
						)
						return record_expr(expr, inst_sig.result_type)
					except ResolutionError as err:
						# If this call looks like a variant constructor invocation (unqualified
						# constructor name) but we have no expected variant type, prefer a
						# targeted diagnostic over a generic "no overload" message.
						#
						# We only do this when there are *no* visible free-function candidates
						# with the same name. If user code declares a real function named
						# `Some`, we should report overload errors for that function instead.
						if expected_type is None and expr.fn.name in ctor_to_variant_bases:
							include_private = current_module if expr.fn.module_id is None else None
							candidates = callable_registry.get_free_candidates(
								name=expr.fn.name,
								visible_modules=_visible_modules_for_free_call(expr.fn.module_id),
								include_private_in=include_private,
							)
							if not candidates:
								diagnostics.append(
											_tc_diag(
												message=(
													"E-CTOR-EXPECTED-TYPE: constructor call requires an expected variant type; "
													"add a type annotation or call a function that expects this variant. "
													"Hint: qualify the constructor (e.g., `Optional::None()` or `Optional<T>::None()` or `Optional::None<type T>()`)."
												),
												severity="error",
												span=getattr(expr, "loc", Span()),
											)
								)
								return record_expr(expr, self._unknown)
						diag_span = getattr(err, "span", None) or getattr(expr, "loc", Span())
						diagnostics.append(
							_tc_diag(
								message=str(err),
								code=getattr(err, "code", None),
								severity="error",
								span=diag_span,
								notes=list(getattr(err, "notes", []) or []),
							)
						)
						return record_expr(expr, self._unknown)

				# Constructor calls without an expected variant type are rejected in MVP.
				if isinstance(expr.fn, H.HVar) and expected_type is None:
					if expr.fn.name in ctor_to_variant_bases:
						diagnostics.append(
							_tc_diag(
								message=(
									"E-CTOR-EXPECTED-TYPE: constructor call requires an expected variant type; "
									"add a type annotation or call a function that expects this variant. "
									"Hint: qualify the constructor (e.g., `Optional::None()` or `Optional<T>::None()` or `Optional::None<type T>()`)."
								),
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
				return record_expr(expr, self._unknown)

			if isinstance(expr, getattr(H, "HInvoke", ())):
				callee_ty = type_expr(expr.callee)
				arg_types = [type_expr(a) for a in expr.args]
				kw_pairs = list(getattr(expr, "kwargs", []) or [])
				if getattr(expr, "type_args", None):
					diagnostics.append(
						_tc_diag(
							message="type arguments are not supported on function values; apply them on the named function",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				if kw_pairs:
					diagnostics.append(
						_tc_diag(
							message="keyword arguments are not supported on function values in MVP",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				if callee_ty is None:
					return record_expr(expr, self._unknown)
				callee_def = self.type_table.get(callee_ty)
				if callee_def.kind is TypeKind.FUNCTION:
					fn_params = list(callee_def.param_types[:-1]) if callee_def.param_types else []
					fn_ret = callee_def.param_types[-1] if callee_def.param_types else self._unknown
					if len(fn_params) != len(arg_types):
						diagnostics.append(
							_tc_diag(
								message=f"function value expects {len(fn_params)} arguments, got {len(arg_types)}",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, fn_ret)
					for want, have in zip(fn_params, arg_types):
						if have is not None and want != have:
							diagnostics.append(
								_tc_diag(
									message=(
										f"function value argument type mismatch (have {self.type_table.get(have).name}, "
										f"expected {self.type_table.get(want).name})"
									),
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
					record_invoke_call_info(
						expr,
						param_types=fn_params,
						return_type=fn_ret,
						can_throw=callee_def.can_throw(),
					)
					return record_expr(expr, fn_ret)
				if callee_def.kind in (TypeKind.CALLABLE, TypeKind.CALLABLE_DYN):
					diagnostics.append(
						_tc_diag(
							message="calling Callable values is not supported yet; use Fn(...) values in MVP",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				diagnostics.append(
					_tc_diag(
						message="call target is not a function value",
						severity="error",
						span=getattr(expr, "loc", Span()),
					)
				)
				return record_expr(expr, self._unknown)

			if isinstance(expr, H.HTryExpr):
				attempt_ty = type_expr(expr.attempt)
				result_ty = attempt_ty
				if attempt_ty is not None:
					td_attempt = self.type_table.get(attempt_ty)
					if td_attempt.kind is TypeKind.FNRESULT and td_attempt.param_types:
						result_ty = td_attempt.param_types[0]
				for arm in expr.arms:
					catch_depth += 1
					scope_env.append(dict())
					scope_bindings.append(dict())
					try:
						if arm.binder:
							bid = self._alloc_local_id()
							locals.append(bid)
							scope_env[-1][arm.binder] = self._error
							scope_bindings[-1][arm.binder] = bid
							binding_types[bid] = self._error
							binding_names[bid] = arm.binder
							binding_mutable[bid] = False
							binding_place_kind[bid] = PlaceKind.LOCAL
						type_block_in_scope(arm.block)
						if arm.result is not None:
							type_expr(arm.result, expected_type=result_ty)
					finally:
						scope_env.pop()
						scope_bindings.pop()
						catch_depth -= 1
				return record_expr(expr, result_ty or self._unknown)

			if isinstance(expr, H.HMethodCall):
				# Built-in DiagnosticValue helpers are reserved method names and take precedence.
				if expr.method_name in ("as_int", "as_bool", "as_string"):
					recv_ty = type_expr(expr.receiver, used_as_value=False)
					recv_def = self.type_table.get(recv_ty)
					if recv_def.kind is not TypeKind.DIAGNOSTICVALUE:
						diagnostics.append(
							_tc_diag(
								message=f"{expr.method_name} is only valid on DiagnosticValue",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						# Record a non-throwing intrinsic call so nothrow analysis can proceed.
						record_method_call_info(
							expr,
							param_types=[recv_ty],
							return_type=self._unknown,
							can_throw=False,
							target=_intrinsic_method_fn_id(expr.method_name),
						)
						return record_expr(expr, self._unknown)
					if expr.method_name == "as_int":
						opt_int = self._optional_variant_type(self._int)
						record_method_call_info(
							expr,
							param_types=[recv_ty],
							return_type=opt_int,
							can_throw=False,
							target=_intrinsic_method_fn_id(expr.method_name),
						)
						return record_expr(expr, opt_int)
					if expr.method_name == "as_bool":
						opt_bool = self._optional_variant_type(self._bool)
						record_method_call_info(
							expr,
							param_types=[recv_ty],
							return_type=opt_bool,
							can_throw=False,
							target=_intrinsic_method_fn_id(expr.method_name),
						)
						return record_expr(expr, opt_bool)
					if expr.method_name == "as_string":
						opt_string = self._optional_variant_type(self._string)
						record_method_call_info(
							expr,
							param_types=[recv_ty],
							return_type=opt_string,
							can_throw=False,
							target=_intrinsic_method_fn_id(expr.method_name),
						)
						return record_expr(expr, opt_string)
					record_method_call_info(
						expr,
						param_types=[recv_ty],
						return_type=self._unknown,
						can_throw=False,
						target=_intrinsic_method_fn_id(expr.method_name),
					)
					return record_expr(expr, self._unknown)

				if getattr(expr, "kwargs", None):
					first = (getattr(expr, "kwargs", []) or [None])[0]
					diagnostics.append(
						_tc_diag(
							message="keyword arguments are not supported for method calls in MVP",
							severity="error",
							span=getattr(first, "loc", getattr(expr, "loc", Span())),
						)
					)
					return record_expr(expr, self._unknown)

				recv_ty = type_expr(expr.receiver, used_as_value=False)
				arg_types = [type_expr(a) for a in expr.args]

				if expr.method_name == "dup" and not expr.args:
					recv_nominal = _unwrap_ref_type(recv_ty)
					recv_def = self.type_table.get(recv_nominal)
					if recv_def.kind is TypeKind.ARRAY and recv_def.param_types:
						elem_ty = recv_def.param_types[0]
						if not self.type_table.is_copy(elem_ty):
							diagnostics.append(
								_tc_diag(
									message="Array<T>.dup() requires element type to be Copy in MVP",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						record_method_call_info(
							expr,
							param_types=[recv_ty],
							return_type=recv_nominal,
							can_throw=False,
							target=_intrinsic_method_fn_id(expr.method_name),
						)
						return record_expr(expr, recv_nominal)

				# Iterator protocol intrinsics for `for` desugaring (MVP).
				#
				# The stage1 lowering desugars:
				#   for x in expr { body }
				# into:
				#   let it = expr.iter()
				#   loop { match it.next() { Some(x) => { body } default => { break } } }
				#
				# Modules/traits are not implemented yet, so `.iter()` / `.next()` are
				# compiler intrinsics on arrays.
				if expr.method_name == "iter" and not expr.args:
					recv_def = self.type_table.get(recv_ty)
					if recv_def.kind is TypeKind.REF and recv_def.param_types:
						recv_nominal = recv_def.param_types[0]
						nominal_def = self.type_table.get(recv_nominal)
						if nominal_def.kind is TypeKind.ARRAY:
							iter_ty = ensure_array_iter_struct(recv_nominal, self.type_table)
							record_method_call_info(
								expr,
								param_types=[recv_ty],
								return_type=iter_ty,
								can_throw=False,
								target=_intrinsic_method_fn_id(expr.method_name),
							)
							return record_expr(expr, iter_ty)
					if recv_def.kind is TypeKind.ARRAY:
						is_place = (
							(hasattr(H, "HPlaceExpr") and isinstance(expr.receiver, getattr(H, "HPlaceExpr")))
							or isinstance(expr.receiver, H.HVar)
						)
						if not is_place:
							diagnostics.append(
								_tc_diag(
									message="iter() requires an addressable Array value in MVP",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						iter_ty = ensure_array_iter_struct(recv_ty, self.type_table)
						param_ty = self.type_table.ensure_ref(recv_ty)
						record_method_call_info(
							expr,
							param_types=[param_ty],
							return_type=iter_ty,
							can_throw=False,
							target=_intrinsic_method_fn_id(expr.method_name),
						)
						return record_expr(expr, iter_ty)
				if expr.method_name == "next" and not expr.args:
					if is_array_iter_struct(recv_ty, self.type_table):
						if not (
							(hasattr(H, "HPlaceExpr") and isinstance(expr.receiver, getattr(H, "HPlaceExpr")))
							or isinstance(expr.receiver, H.HVar)
						):
							diagnostics.append(
								_tc_diag(
									message="next() requires a mutable iterator place in MVP",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						iter_def = self.type_table.get(recv_ty)
						if not iter_def.param_types or len(iter_def.param_types) != 2:
							diagnostics.append(
								_tc_diag(
									message="internal array iterator type is malformed (compiler bug)",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							record_method_call_info(
								expr,
								param_types=[recv_ty],
								return_type=self._unknown,
								can_throw=False,
								target=_intrinsic_method_fn_id(expr.method_name),
							)
							return record_expr(expr, self._unknown)
						arr_ty = iter_def.param_types[0]
						arr_def = self.type_table.get(arr_ty)
						if arr_def.kind is not TypeKind.REF or not arr_def.param_types:
							diagnostics.append(
								_tc_diag(
									message="internal array iterator type does not contain &Array<T> (compiler bug)",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							record_method_call_info(
								expr,
								param_types=[recv_ty],
								return_type=self._unknown,
								can_throw=False,
								target=_intrinsic_method_fn_id(expr.method_name),
							)
							return record_expr(expr, self._unknown)
						array_ty = arr_def.param_types[0]
						array_def = self.type_table.get(array_ty)
						if array_def.kind is not TypeKind.ARRAY or not array_def.param_types:
							diagnostics.append(
								_tc_diag(
									message="internal array iterator type does not contain &Array<T> (compiler bug)",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							record_method_call_info(
								expr,
								param_types=[recv_ty],
								return_type=self._unknown,
								can_throw=False,
								target=_intrinsic_method_fn_id(expr.method_name),
							)
							return record_expr(expr, self._unknown)
						elem_ty = array_def.param_types[0]
						opt_base = self.type_table.ensure_optional_base()
						opt_ty = self.type_table.ensure_instantiated(opt_base, [elem_ty])
						record_method_call_info(
							expr,
							param_types=[recv_ty],
							return_type=opt_ty,
							can_throw=False,
							target=_intrinsic_method_fn_id(expr.method_name),
						)
						return record_expr(expr, opt_ty)

				# FnResult intrinsic methods.
				if expr.method_name in ("is_err", "unwrap", "unwrap_err") and not expr.args:
					recv_def = self.type_table.get(recv_ty)
					if recv_def.kind is TypeKind.FNRESULT and recv_def.param_types:
						ok_ty = recv_def.param_types[0] if len(recv_def.param_types) > 0 else self._unknown
						err_ty = recv_def.param_types[1] if len(recv_def.param_types) > 1 else self._error
						if expr.method_name == "is_err":
							ret_ty = self._bool
						elif expr.method_name == "unwrap":
							ret_ty = ok_ty
						else:
							ret_ty = err_ty
						record_method_call_info(
							expr,
							param_types=[recv_ty],
							return_type=ret_ty,
							can_throw=False,
							target=_intrinsic_method_fn_id(expr.method_name),
						)
						return record_expr(expr, ret_ty)

				if callable_registry:
					try:
						call_type_args = getattr(expr, "type_args", None) or []
						type_arg_ids: List[TypeId] | None = None
						call_type_args_span = None
						if call_type_args:
							first_loc = getattr(call_type_args[0], "loc", None)
							if first_loc is not None:
								call_type_args_span = Span.from_loc(first_loc)
							type_arg_ids = [
								resolve_opaque_type(t, self.type_table, module_id=current_module_name)
								for t in call_type_args
							]
						receiver_nominal = _unwrap_ref_type(recv_ty)
						receiver_base, receiver_args = _struct_base_and_args(receiver_nominal)
						recv_def = self.type_table.get(receiver_nominal)
						recv_type_param_id = recv_def.type_param_id if recv_def.kind is TypeKind.TYPEVAR else None
						recv_type_key = None
						if recv_type_param_id is not None:
							recv_type_key = _normalize_type_key(type_key_from_typeid(self.type_table, receiver_nominal))
						receiver_place = _receiver_place(expr.receiver)
						receiver_is_lvalue = receiver_place is not None
						receiver_can_mut_borrow = _receiver_can_mut_borrow(expr.receiver, receiver_place)
						hidden_candidates: list[tuple[CallableDecl, ImplMethodCandidate]] = []
						if impl_index is not None:
							candidates: list[CallableDecl] = []
							visible_set = set(visible_modules or (current_module,))
							for cand in impl_index.get_candidates(receiver_base, expr.method_name):
								decl = callable_registry.get_by_fn_id(cand.fn_id)
								if decl is None:
									continue
								if cand.is_pub:
									if cand.def_module_id in visible_set:
										candidates.append(decl)
									else:
										hidden_candidates.append((decl, cand))
								elif cand.def_module_id == current_module:
									candidates.append(decl)
								else:
									hidden_candidates.append((decl, cand))
						else:
							candidates = callable_registry.get_method_candidates(
								receiver_nominal_type_id=receiver_base,
								name=expr.method_name,
								visible_modules=visible_modules or (current_module,),
								include_private_in=current_module,
							)
						viable: List[tuple[MethodResolution, Tuple[TypeId, ...], Tuple[TypeId, ...], Tuple[TypeId, ...], int]] = []
						require_info: dict[object, tuple[parser_ast.TraitExpr, dict[object, object], str, dict[TypeParamId, tuple[str, int]]]] = {}
						require_failures: list[ProofFailure] = []
						trait_require_failures: list[ProofFailure] = []
						type_arg_counts: set[int] = set()
						saw_registry_only_with_type_args = False
						saw_typed_nongeneric_with_type_args = False
						saw_infer_incomplete = False
						infer_failures: list[InferResult] = []
						for decl in candidates:
							sig = None
							if decl.fn_id is not None and signatures_by_id is not None:
								sig = signatures_by_id.get(decl.fn_id)
							if sig is None:
								if type_arg_ids:
									saw_registry_only_with_type_args = True
									continue
								params = decl.signature.param_types
								if len(params) - 1 != len(arg_types):
									continue
								ok, autoborrow = _receiver_compat(recv_ty, params[0], decl.self_mode)
								if not ok:
									continue
								pref = _receiver_preference(
									decl.self_mode,
									receiver_is_lvalue=receiver_is_lvalue,
									receiver_can_mut_borrow=receiver_can_mut_borrow,
									autoborrow=autoborrow,
								)
								if pref is None:
									continue
								if _args_match_params(list(params[1:]), arg_types):
									viable.append(
										(
											MethodResolution(
												decl=decl,
												receiver_autoborrow=autoborrow,
												result_type=decl.signature.result_type,
											),
											(),
											(),
											tuple(params),
											pref,
										)
									)
								continue
							if sig.param_type_ids is None and sig.param_types is not None:
								local_type_params = {p.name: p.id for p in sig.type_params}
								param_type_ids = [
									resolve_opaque_type(p, self.type_table, module_id=sig.module, type_params=local_type_params)
									for p in sig.param_types
								]
								sig = replace(sig, param_type_ids=param_type_ids)
							if sig.return_type_id is None and sig.return_type is not None:
								local_type_params = {p.name: p.id for p in sig.type_params}
								ret_id = resolve_opaque_type(sig.return_type, self.type_table, module_id=sig.module, type_params=local_type_params)
								sig = replace(sig, return_type_id=ret_id)
							if sig.param_type_ids is None or sig.return_type_id is None:
								continue
							impl_subst: Subst | None = None
							if sig.impl_target_type_args:
								impl_type_params = list(getattr(sig, "impl_type_params", []) or [])
								if not impl_type_params:
									if receiver_args != sig.impl_target_type_args:
										continue
								else:
									impl_subst = _match_impl_type_args(
										template_args=sig.impl_target_type_args,
										recv_args=receiver_args,
										impl_type_params=impl_type_params,
									)
									if impl_subst is None:
										continue
									inst_param_ids = [apply_subst(t, impl_subst, self.type_table) for t in sig.param_type_ids]
									inst_return_id = apply_subst(sig.return_type_id, impl_subst, self.type_table)
									sig = replace(sig, param_type_ids=inst_param_ids, return_type_id=inst_return_id)

							infer_recv_ty = _infer_receiver_arg_type(
								decl.self_mode,
								recv_ty,
								receiver_is_lvalue=receiver_is_lvalue,
								receiver_can_mut_borrow=receiver_can_mut_borrow,
							)
							inst_arg_types = [infer_recv_ty, *arg_types]
							if sig.param_type_ids:
								inst_arg_types = [
									infer_recv_ty,
									*_coerce_args_for_params(
										list(sig.param_type_ids[1:]),
										arg_types,
									),
								]
							inst_res = _instantiate_sig_with_subst(
								sig=sig,
								arg_types=inst_arg_types,
								expected_type=expected_type,
								explicit_type_args=type_arg_ids,
								allow_infer=True,
								diag_span=call_type_args_span or getattr(expr, "loc", Span()),
								call_kind="method",
								call_name=expr.method_name,
								receiver_type=recv_ty,
							)
							if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS and type_arg_ids:
								saw_typed_nongeneric_with_type_args = True
								continue
							if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT and type_arg_ids:
								if inst_res.error.expected_count is not None:
									type_arg_counts.add(inst_res.error.expected_count)
								continue
							if inst_res.error and inst_res.error.kind in {InferErrorKind.CANNOT_INFER, InferErrorKind.CONFLICT}:
								saw_infer_incomplete = True
								infer_failures.append(inst_res)
								continue
							if inst_res.error:
								continue

							if inst_res.inst_params is None or inst_res.inst_return is None:
								continue
							inst_params = inst_res.inst_params
							inst_return = inst_res.inst_return
							inst_subst = inst_res.subst
							method_req: parser_ast.TraitExpr | None = None
							method_subst: dict[object, object] = {}
							method_def_mod = current_module_name
							# Enforce method-level requirements after instantiation.
							if decl.fn_id is not None:
								world = visible_trait_world or global_trait_world
								req = _require_for_fn(decl.fn_id)
								if req is not None:
									subjects: set[object] = set()
									_collect_trait_subjects(req, subjects)
									subst: dict[object, object] = {}
									if inst_subst is not None and sig.type_params:
										for idx, tp in enumerate(sig.type_params):
											if tp.id in subjects or tp.name in subjects:
												if idx < len(inst_subst.args):
													key = _normalize_type_key(
														type_key_from_typeid(self.type_table, inst_subst.args[idx])
													)
													subst[tp.id] = key
													subst[tp.name] = key
									env = TraitEnv(
										default_module=decl.fn_id.module or current_module_name,
										default_package=default_package,
										module_packages=module_packages or {},
										assumed_true=set(fn_require_assumed),
									)
									res = prove_expr(world, env, subst, req)
									if res.status is not ProofStatus.PROVED:
										failure = _require_failure(
											req_expr=req,
											subst=subst,
											origin=ObligationOrigin(
												kind=ObligationOriginKind.CALLEE_REQUIRE,
												label=f"method '{expr.method_name}'",
												span=Span.from_loc(getattr(req, "loc", None)),
											),
											span=getattr(expr, "loc", Span()),
											env=env,
											world=world,
											result=res,
										)
										if failure is not None:
											require_failures.append(failure)
										continue
									method_req = req
									method_subst = subst
									method_def_mod = decl.fn_id.module or current_module_name
							if len(inst_params) - 1 != len(arg_types):
								continue
							ok, autoborrow = _receiver_compat(recv_ty, inst_params[0], decl.self_mode)
							if not ok:
								continue
							pref = _receiver_preference(
								decl.self_mode,
								receiver_is_lvalue=receiver_is_lvalue,
								receiver_can_mut_borrow=receiver_can_mut_borrow,
								autoborrow=autoborrow,
							)
							if pref is None:
								continue
							if _args_match_params(list(inst_params[1:]), arg_types):
								impl_args = tuple(impl_subst.args) if impl_subst is not None else ()
								fn_args = tuple(inst_subst.args) if inst_subst is not None else ()
								viable.append(
									(
										MethodResolution(
											decl=decl,
											receiver_autoborrow=autoborrow,
											result_type=inst_return,
										),
										impl_args,
										fn_args,
										tuple(inst_params),
										pref,
									)
								)
								if method_req is not None:
									cand_key = _candidate_key_for_decl(decl)
									scope_map = _param_scope_map(sig)
									require_info[cand_key] = (
										method_req,
										method_subst,
										method_def_mod,
										scope_map,
									)

						if not viable:
							if not candidates and hidden_candidates:
								mod_names: list[str] = []
								notes: list[str] = []
								for decl, cand in hidden_candidates:
									mod = (
										decl.fn_id.module
										if decl.fn_id is not None and decl.fn_id.module
										else str(cand.def_module_id)
									)
									mod_names.append(mod)
									span = cand.method_loc or cand.impl_loc
									chain_note = _visibility_note(cand.def_module_id)
									if span and span.line is not None:
										loc = f"{span.file}:{span.line}:{span.column}" if span.file else f"line {span.line}"
										note = f"candidate in module '{mod}' at {loc}"
									else:
										note = f"candidate in module '{mod}'"
									if chain_note:
										note = f"{note}; {chain_note}"
									notes.append(note)
								mod_list = ", ".join(sorted(set(mod_names)))
								diagnostics.append(
									_tc_diag(
										message=(
											f"method '{expr.method_name}' exists but is not visible here; "
											f"candidates from modules: {mod_list}"
										),
										severity="error",
										span=getattr(expr, "loc", Span()),
										notes=notes,
									)
								)
								return record_expr(expr, self._unknown)
						if not viable and trait_index and trait_impl_index and trait_scope_by_module:
							visible_set = set(visible_modules or (current_module,))
							missing_visible = set()
							if trait_impl_index.missing_modules:
								missing_visible = trait_impl_index.missing_modules & visible_set
							if missing_visible:
								mod_names = [
									trait_impl_index.module_names_by_id.get(mid, str(mid))
									for mid in sorted(missing_visible)
								]
								raise ResolutionError(
									"missing impl metadata for visible modules: " + ", ".join(mod_names),
									span=getattr(expr, "loc", Span()),
								)
							trait_candidates: list[
								tuple[
									MethodResolution,
									TraitImplCandidate,
									Tuple[TypeId, ...],
									Tuple[TypeId, ...],
									Tuple[TypeId, ...],
									int,
								]
							] = []
							trait_require_info: dict[object, tuple[parser_ast.TraitExpr, dict[object, object], str, dict[TypeParamId, tuple[str, int]]]] = {}
							trait_hidden: list[tuple[CallableDecl, TraitImplCandidate, TraitKey]] = []
							trait_type_arg_counts: set[int] = set()
							trait_saw_typed_nongeneric = False
							trait_saw_infer_incomplete = False
							trait_infer_failures: list[InferResult] = []
							traits_in_scope = _traits_in_scope()
							for trait_key in traits_in_scope:
								if trait_index.is_missing(trait_key):
									raise ResolutionError(
										f"missing trait metadata for '{_trait_label(trait_key)}'",
										span=getattr(expr, "loc", Span()),
									)
								if not trait_index.has_method(trait_key, expr.method_name):
									continue
								if recv_type_param_id is not None:
									if (
										(recv_type_param_id, trait_key) not in fn_require_assumed
										and (recv_type_key, trait_key) not in fn_require_assumed
									):
										continue
									trait_def = trait_index.traits_by_id.get(trait_key)
									method_sig = None
									if trait_def is not None:
										for method in getattr(trait_def, "methods", []) or []:
											if getattr(method, "name", None) == expr.method_name:
												method_sig = method
												break
									if method_sig is not None:
										method_type_params = list(getattr(method_sig, "type_params", []) or [])
										method_type_param_ids: list[TypeParam] = []
										type_param_map = {"Self": recv_type_param_id}
										if method_type_params:
											owner = FunctionId(
												module=trait_key.module or current_module_name,
												name=f"{trait_key.name}::{method_sig.name}",
												ordinal=0,
											)
											for idx, name in enumerate(method_type_params):
												param_id = TypeParamId(owner=owner, index=idx)
												method_type_param_ids.append(TypeParam(id=param_id, name=name, span=None))
												type_param_map[name] = param_id
										param_type_ids: list[TypeId] = []
										param_names: list[str] = []
										for param in list(getattr(method_sig, "params", []) or []):
											param_names.append(param.name)
											if param.type_expr is None:
												if param.name != "self":
													param_type_ids = []
													break
												param_type_ids.append(receiver_nominal)
												continue
											param_type_ids.append(
												resolve_opaque_type(
													param.type_expr,
													self.type_table,
													module_id=trait_key.module or current_module_name,
													type_params=type_param_map,
												)
											)
										if param_type_ids:
											ret_id = resolve_opaque_type(
												method_sig.return_type,
												self.type_table,
												module_id=trait_key.module or current_module_name,
												type_params=type_param_map,
											)
											self_mode = SelfMode.SELF_BY_VALUE
											if param_type_ids:
												param0 = self.type_table.get(param_type_ids[0])
												if param0.kind is TypeKind.REF:
													self_mode = (
														SelfMode.SELF_BY_REF_MUT
														if param0.ref_mut
														else SelfMode.SELF_BY_REF
													)
											trait_sig = FnSignature(
												name=method_sig.name,
												method_name=method_sig.name,
												param_type_ids=param_type_ids,
												return_type_id=ret_id,
												param_names=param_names if param_names else None,
												type_params=method_type_param_ids,
												is_method=True,
												self_mode={SelfMode.SELF_BY_VALUE: "value", SelfMode.SELF_BY_REF: "ref", SelfMode.SELF_BY_REF_MUT: "ref_mut"}[
													self_mode
												],
												module=trait_key.module or current_module_name,
											)
											infer_recv_ty = _infer_receiver_arg_type(
												self_mode,
												recv_ty,
												receiver_is_lvalue=receiver_is_lvalue,
												receiver_can_mut_borrow=receiver_can_mut_borrow,
											)
											inst_arg_types = [infer_recv_ty, *arg_types]
											if trait_sig.param_type_ids:
												inst_arg_types = [
													infer_recv_ty,
													*_coerce_args_for_params(
														list(trait_sig.param_type_ids[1:]),
														arg_types,
													),
												]
											inst_res = _instantiate_sig_with_subst(
												sig=trait_sig,
												arg_types=inst_arg_types,
												expected_type=expected_type,
												explicit_type_args=type_arg_ids,
												allow_infer=True,
												diag_span=call_type_args_span or getattr(expr, "loc", Span()),
												call_kind="method",
												call_name=method_sig.name,
												receiver_type=recv_ty,
											)
											if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS and type_arg_ids:
												trait_saw_typed_nongeneric = True
											elif inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT and type_arg_ids:
												if inst_res.error.expected_count is not None:
													trait_type_arg_counts.add(inst_res.error.expected_count)
											elif inst_res.error and inst_res.error.kind in {InferErrorKind.CANNOT_INFER, InferErrorKind.CONFLICT}:
												trait_saw_infer_incomplete = True
												trait_infer_failures.append(inst_res)
											elif not inst_res.error and inst_res.inst_params and inst_res.inst_return is not None:
												trait_decl = CallableDecl(
													callable_id=-1,
													name=method_sig.name,
													kind=CallableKind.METHOD_TRAIT,
													module_id=0,
													visibility=Visibility.public(),
													signature=CallableSignature(
														param_types=tuple(param_type_ids),
														result_type=ret_id,
													),
													fn_id=FunctionId(
														module=trait_key.module or current_module_name,
														name=method_sig.name,
														ordinal=0,
													),
													impl_target_type_id=None,
													self_mode=self_mode,
												)
												ok, autoborrow = _receiver_compat(recv_ty, inst_res.inst_params[0], self_mode)
												if ok and _args_match_params(list(inst_res.inst_params[1:]), arg_types):
													pref = _receiver_preference(
														self_mode,
														receiver_is_lvalue=receiver_is_lvalue,
														receiver_can_mut_borrow=receiver_can_mut_borrow,
														autoborrow=autoborrow,
													)
													if pref is None:
														continue
													trait_candidates.append(
														(
															MethodResolution(
																decl=trait_decl,
																receiver_autoborrow=autoborrow,
																result_type=inst_res.inst_return,
															),
															TraitImplCandidate(
																fn_id=trait_decl.fn_id,
																name=method_sig.name,
																trait=trait_key,
																def_module_id=0,
																is_pub=True,
																impl_id=-1,
																impl_loc=None,
																method_loc=Span.from_loc(getattr(method_sig, "loc", None)),
																require_expr=None,
															),
															(),
															tuple(inst_res.subst.args) if inst_res.subst is not None else (),
															tuple(inst_res.inst_params),
															pref,
														)
													)
								for cand in trait_impl_index.get_candidates(trait_key, receiver_base, expr.method_name):
									decl = callable_registry.get_by_fn_id(cand.fn_id) if callable_registry else None
									if decl is None:
										continue
									if cand.def_module_id not in visible_set:
										trait_hidden.append((decl, cand, trait_key))
										continue
									if not cand.is_pub and cand.def_module_id != current_module:
										trait_hidden.append((decl, cand, trait_key))
										continue
									sig = signatures_by_id.get(decl.fn_id) if signatures_by_id is not None else None
									if sig is None:
										continue
									if sig.param_type_ids is None and sig.param_types is not None:
										local_type_params = {p.name: p.id for p in sig.type_params}
										param_type_ids = [
											resolve_opaque_type(
												p,
												self.type_table,
												module_id=sig.module,
												type_params=local_type_params,
											)
											for p in sig.param_types
										]
										sig = replace(sig, param_type_ids=param_type_ids)
									if sig.return_type_id is None and sig.return_type is not None:
										local_type_params = {p.name: p.id for p in sig.type_params}
										ret_id = resolve_opaque_type(
											sig.return_type,
											self.type_table,
											module_id=sig.module,
											type_params=local_type_params,
										)
										sig = replace(sig, return_type_id=ret_id)
									if sig.param_type_ids is None or sig.return_type_id is None:
										continue
									impl_subst: Subst | None = None
									impl_req_expr: parser_ast.TraitExpr | None = None
									impl_subst_map: dict[object, object] = {}
									if sig.impl_target_type_args:
										impl_type_params = list(getattr(sig, "impl_type_params", []) or [])
										if not impl_type_params:
											if receiver_args != sig.impl_target_type_args:
												continue
											impl_subst = None
										else:
											impl_subst = _match_impl_type_args(
												template_args=sig.impl_target_type_args,
												recv_args=receiver_args,
												impl_type_params=impl_type_params,
											)
											if impl_subst is None:
												continue
										if impl_subst is not None:
											inst_param_ids = [
												apply_subst(t, impl_subst, self.type_table) for t in sig.param_type_ids
											]
											inst_return_id = apply_subst(sig.return_type_id, impl_subst, self.type_table)
											sig = replace(sig, param_type_ids=inst_param_ids, return_type_id=inst_return_id)
										# Enforce impl-level requirements after impl substitution.
										if cand.require_expr is not None:
											def_mod = (
												decl.fn_id.module
												if decl.fn_id is not None and decl.fn_id.module
												else current_module_name
											)
											world = visible_trait_world or global_trait_world
											if world is None:
												continue
											subjects: set[object] = set()
											_collect_trait_subjects(cand.require_expr, subjects)
											subst: dict[object, object] = {}
											if impl_subst is not None and impl_type_params:
												for tp in impl_type_params:
													idx = int(tp.id.index)
													if idx < len(impl_subst.args):
														key = _normalize_type_key(
															type_key_from_typeid(self.type_table, impl_subst.args[idx])
														)
														subst[tp.id] = key
														subst[tp.name] = key
											for subj in subjects:
												if subj in subst:
													continue
												if isinstance(subj, str):
													try:
														ty_expr = parser_ast.TypeExpr(
															name=subj,
															args=[],
															module_alias=None,
															module_id=None,
															loc=getattr(cand.require_expr, "loc", None),
														)
														ty_id = resolve_opaque_type(
															ty_expr, self.type_table, module_id=def_mod
														)
														subst[subj] = _normalize_type_key(
															type_key_from_typeid(self.type_table, ty_id)
														)
													except Exception:
														continue
											env = TraitEnv(
												default_module=def_mod,
												default_package=default_package,
												module_packages=module_packages or {},
												assumed_true=set(fn_require_assumed),
											)
											res = prove_expr(world, env, subst, cand.require_expr)
											if res.status is not ProofStatus.PROVED:
												failure = _require_failure(
													req_expr=cand.require_expr,
													subst=subst,
													origin=ObligationOrigin(
														kind=ObligationOriginKind.IMPL_REQUIRE,
														label=f"impl for trait '{trait_key.name}'",
														span=cand.impl_loc,
													),
													span=getattr(expr, "loc", Span()),
													env=env,
													world=world,
													result=res,
												)
												if failure is not None:
													trait_require_failures.append(failure)
												continue
											impl_req_expr = cand.require_expr
											impl_subst_map = subst

									infer_recv_ty = _infer_receiver_arg_type(
										decl.self_mode,
										recv_ty,
										receiver_is_lvalue=receiver_is_lvalue,
										receiver_can_mut_borrow=receiver_can_mut_borrow,
									)
									inst_arg_types = [infer_recv_ty, *arg_types]
									if sig.param_type_ids:
										inst_arg_types = [
											infer_recv_ty,
											*_coerce_args_for_params(
												list(sig.param_type_ids[1:]),
												arg_types,
											),
										]
									inst_res = _instantiate_sig_with_subst(
										sig=sig,
										arg_types=inst_arg_types,
										expected_type=expected_type,
										explicit_type_args=type_arg_ids,
										allow_infer=True,
										diag_span=call_type_args_span or getattr(expr, "loc", Span()),
										call_kind="method",
										call_name=expr.method_name,
										receiver_type=recv_ty,
									)
									if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS and type_arg_ids:
										trait_saw_typed_nongeneric = True
										continue
									if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT and type_arg_ids:
										if inst_res.error.expected_count is not None:
											trait_type_arg_counts.add(inst_res.error.expected_count)
										continue
									if inst_res.error and inst_res.error.kind in {InferErrorKind.CANNOT_INFER, InferErrorKind.CONFLICT}:
										trait_saw_infer_incomplete = True
										trait_infer_failures.append(inst_res)
										continue
									if inst_res.error:
										continue

									if inst_res.inst_params is None or inst_res.inst_return is None:
										continue
									inst_params = inst_res.inst_params
									inst_return = inst_res.inst_return
									inst_subst = inst_res.subst
									# Enforce method-level requirements after instantiation.
									method_req_expr: parser_ast.TraitExpr | None = None
									method_subst_map: dict[object, object] = {}
									if decl.fn_id is not None:
										world = visible_trait_world or global_trait_world
										req = _require_for_fn(decl.fn_id)
										if req is not None:
											subjects: set[object] = set()
											_collect_trait_subjects(req, subjects)
											subst: dict[object, object] = {}
											if inst_subst is not None and sig.type_params:
												for idx, tp in enumerate(sig.type_params):
													if tp.id in subjects or tp.name in subjects:
														if idx < len(inst_subst.args):
															key = _normalize_type_key(
																type_key_from_typeid(self.type_table, inst_subst.args[idx])
															)
															subst[tp.id] = key
															subst[tp.name] = key
											env = TraitEnv(
												default_module=decl.fn_id.module or current_module_name,
												default_package=default_package,
												module_packages=module_packages or {},
												assumed_true=set(fn_require_assumed),
											)
											res = prove_expr(world, env, subst, req)
											if res.status is not ProofStatus.PROVED:
												failure = _require_failure(
													req_expr=req,
													subst=subst,
													origin=ObligationOrigin(
														kind=ObligationOriginKind.CALLEE_REQUIRE,
														label=f"method '{expr.method_name}'",
														span=Span.from_loc(getattr(req, "loc", None)),
													),
													span=getattr(expr, "loc", Span()),
													env=env,
													world=world,
													result=res,
												)
												if failure is not None:
													trait_require_failures.append(failure)
												continue
											method_req_expr = req
											method_subst_map = subst
									if len(inst_params) - 1 != len(arg_types):
										continue
									ok, autoborrow = _receiver_compat(recv_ty, inst_params[0], decl.self_mode)
									if not ok:
										continue
									if _args_match_params(list(inst_params[1:]), arg_types):
										pref = _receiver_preference(
											decl.self_mode,
											receiver_is_lvalue=receiver_is_lvalue,
											receiver_can_mut_borrow=receiver_can_mut_borrow,
											autoborrow=autoborrow,
										)
										if pref is None:
											continue
										impl_args = tuple(impl_subst.args) if impl_subst is not None else ()
										fn_args = tuple(inst_subst.args) if inst_subst is not None else ()
										trait_candidates.append(
											(
												MethodResolution(
													decl=decl,
													receiver_autoborrow=autoborrow,
													result_type=inst_return,
												),
												cand,
												impl_args,
												fn_args,
												tuple(inst_params),
												pref,
											)
										)
										cand_req = _combine_require(impl_req_expr, method_req_expr)
										if cand_req is not None:
											merged_subst = dict(impl_subst_map)
											merged_subst.update(method_subst_map)
											cand_key = _candidate_key_for_decl(decl)
											scope_map = _param_scope_map(sig)
											trait_require_info[cand_key] = (
												cand_req,
												merged_subst,
												decl.fn_id.module or current_module_name,
												scope_map,
											)

							if trait_candidates:
								best_pref = min(pref for _res, _cand, _impl_args, _fn_args, _inst_params, pref in trait_candidates)
								best = [item for item in trait_candidates if item[5] == best_pref]
								best = _dedupe_by_key(
									best,
									lambda item: _candidate_key_for_decl(item[0].decl),
								)
								if len(best) > 1:
									best = _pick_most_specific_items(
										best,
										lambda item: _candidate_key_for_decl(item[0].decl),
										trait_require_info,
									)
								if len(best) > 1:
									labels: list[str] = []
									notes: list[str] = []
									seen_labels: set[str] = set()

									def _trait_ambig_key(
										item: tuple[
											MethodResolution,
											TraitImplCandidate,
											Tuple[TypeId, ...],
											Tuple[TypeId, ...],
											Tuple[TypeId, ...],
											int,
										],
									) -> tuple[str, str, int]:
										res, cand, _impl_args, _fn_args, _inst_params, _pref = item
										trait_label = f"{cand.trait.module}.{cand.trait.name}" if cand.trait.module else cand.trait.name
										mod_label = (
											res.decl.fn_id.module
											if res.decl.fn_id and res.decl.fn_id.module
											else str(res.decl.module_id)
										)
										return (trait_label, mod_label, int(cand.impl_id))

									for res, cand, _impl_args, _fn_args, _inst_params, _pref in sorted(
										best, key=_trait_ambig_key
									):
										trait_label = f"{cand.trait.module}.{cand.trait.name}" if cand.trait.module else cand.trait.name
										mod_label = (
											res.decl.fn_id.module
											if res.decl.fn_id and res.decl.fn_id.module
											else str(res.decl.module_id)
										)
										label = f"{trait_label}@{mod_label}"
										if label not in seen_labels:
											labels.append(label)
											seen_labels.add(label)
										chain_note = _visibility_note(cand.def_module_id)
										if chain_note:
											notes.append(f"{label} {chain_note}")
									label_str = ", ".join(labels)
									recv_label = _label_typeid(recv_ty)
									raise ResolutionError(
										f"ambiguous method '{expr.method_name}' for receiver {recv_label} and args {arg_types}; candidates from traits: {label_str}",
										span=getattr(expr, "loc", Span()),
										notes=notes,
										code="E-METHOD-AMBIGUOUS",
									)
								resolution, _cand, impl_args, fn_args, inst_params, _pref = best[0]
								call_resolutions[expr.node_id] = resolution
								result_type = resolution.result_type or resolution.decl.signature.result_type
								target_fn_id = resolution.decl.fn_id
								if target_fn_id is None:
									raise ResolutionError(
										f"missing function id for method '{expr.method_name}' (compiler bug)",
										span=getattr(expr, "loc", Span()),
									)
								sig_for_throw = signatures_by_id.get(target_fn_id) if signatures_by_id is not None else None
								if sig_for_throw is None:
									call_can_throw = True
								elif sig_for_throw.declared_can_throw is None:
									diagnostics.append(
										_tc_diag(
											message="internal: signature missing declared_can_throw (checker bug)",
											severity="error",
											span=Span(),
										)
									)
									call_can_throw = True
								else:
									call_can_throw = bool(sig_for_throw.declared_can_throw)
								applied = _apply_method_boundary(
									expr,
									target_fn_id=target_fn_id,
									sig_for_throw=sig_for_throw,
									call_can_throw=call_can_throw,
								)
								if applied is None:
									return record_expr(expr, self._unknown)
								target_fn_id, call_can_throw = applied
								updated_arg_types, had_autoborrow_error = _apply_autoborrow_args(
									expr.args,
									arg_types,
									list(inst_params[1:]),
									span=getattr(expr, "loc", Span()),
								)
								arg_types = updated_arg_types
								if had_autoborrow_error:
									record_method_call_info(
										expr,
										param_types=list(inst_params),
										return_type=result_type or self._unknown,
										can_throw=call_can_throw,
										target=target_fn_id,
									)
									return record_expr(expr, self._unknown)
								record_method_call_info(
									expr,
									param_types=list(inst_params),
									return_type=result_type or self._unknown,
									can_throw=call_can_throw,
									target=target_fn_id,
								)
								record_instantiation(
									callsite_id=getattr(expr, "callsite_id", None),
									target_fn_id=resolution.decl.fn_id,
									impl_args=impl_args,
									fn_args=fn_args,
								)
								return record_expr(expr, result_type)
							if trait_hidden:
								mod_names: list[str] = []
								notes: list[str] = []
								for decl, cand, trait_key in trait_hidden:
									mod = (
										decl.fn_id.module
										if decl.fn_id is not None and decl.fn_id.module
										else str(cand.def_module_id)
									)
									trait_name = f"{trait_key.module}.{trait_key.name}" if trait_key.module else trait_key.name
									mod_names.append(f"{trait_name}@{mod}")
									span = cand.method_loc or cand.impl_loc
									chain_note = _visibility_note(cand.def_module_id)
									if span and span.line is not None:
										loc = f"{span.file}:{span.line}:{span.column}" if span.file else f"line {span.line}"
										note = f"candidate in trait '{trait_name}' at {loc}"
									else:
										note = f"candidate in trait '{trait_name}'"
									if chain_note:
										note = f"{note}; {chain_note}"
									notes.append(note)
								mod_list = ", ".join(sorted(set(mod_names)))
								diagnostics.append(
									_tc_diag(
										message=(
											f"method '{expr.method_name}' exists but is not visible here; "
											f"candidates from traits: {mod_list}"
										),
										severity="error",
										span=getattr(expr, "loc", Span()),
										notes=notes,
									)
								)
								return record_expr(expr, self._unknown)
							if type_arg_ids and trait_type_arg_counts:
								exp = ", ".join(str(n) for n in sorted(trait_type_arg_counts))
								raise ResolutionError(
									f"type argument count mismatch for method '{expr.method_name}': expected one of ({exp}), got {len(type_arg_ids)}",
									span=call_type_args_span,
								)
							if type_arg_ids and trait_saw_typed_nongeneric:
								raise ResolutionError(
									f"type arguments require a generic method signature for '{expr.method_name}'",
									span=call_type_args_span,
								)
							if trait_saw_infer_incomplete:
								failure = trait_infer_failures[0] if trait_infer_failures else None
								ctx = failure.context if failure and failure.context is not None else InferContext(
									call_kind="method",
									call_name=expr.method_name,
									span=call_type_args_span or getattr(expr, "loc", Span()),
									type_param_ids=[],
									type_param_names={},
									param_types=[],
									param_names=None,
									return_type=None,
									arg_types=[],
								)
								res = failure if failure is not None else InferResult(
									ok=False,
									subst=None,
									inst_params=None,
									inst_return=None,
									error=InferError(kind=InferErrorKind.CANNOT_INFER),
									context=ctx,
								)
								msg, notes = _format_infer_failure(ctx, res)
								raise ResolutionError(msg, span=call_type_args_span, notes=notes)
						if not viable:
							if type_arg_ids and type_arg_counts:
								exp = ", ".join(str(n) for n in sorted(type_arg_counts))
								raise ResolutionError(
									f"type argument count mismatch for method '{expr.method_name}': expected one of ({exp}), got {len(type_arg_ids)}",
									span=call_type_args_span,
								)
							if type_arg_ids and saw_typed_nongeneric_with_type_args:
								raise ResolutionError(
									f"type arguments require a generic method signature for '{expr.method_name}'",
									span=call_type_args_span,
								)
							if type_arg_ids and saw_registry_only_with_type_args:
								raise ResolutionError(
									f"type arguments require a typed signature for method '{expr.method_name}'",
									span=call_type_args_span,
								)
							if saw_infer_incomplete:
								failure = infer_failures[0] if infer_failures else None
								ctx = failure.context if failure and failure.context is not None else InferContext(
									call_kind="method",
									call_name=expr.method_name,
									span=call_type_args_span or getattr(expr, "loc", Span()),
									type_param_ids=[],
									type_param_names={},
									param_types=[],
									param_names=None,
									return_type=None,
									arg_types=[],
								)
								res = failure if failure is not None else InferResult(
									ok=False,
									subst=None,
									inst_params=None,
									inst_return=None,
									error=InferError(kind=InferErrorKind.CANNOT_INFER),
									context=ctx,
								)
								msg, notes = _format_infer_failure(ctx, res)
								raise ResolutionError(msg, span=call_type_args_span, notes=notes)
							if trait_require_failures:
								failure = _pick_best_failure(trait_require_failures)
								raise ResolutionError(
									_format_failure_message(failure) if failure is not None else "trait requirements not met",
									code=_failure_code(failure) if failure is not None else None,
									span=(failure.obligation.span if failure is not None else None)
									or getattr(expr, "loc", Span()),
									notes=list(getattr(failure.obligation, "notes", []) or []) if failure is not None else None,
								)
							if require_failures:
								failure = _pick_best_failure(require_failures)
								raise ResolutionError(
									_format_failure_message(failure) if failure is not None else "trait requirements not met",
									code=_failure_code(failure) if failure is not None else None,
									span=(failure.obligation.span if failure is not None else None)
									or getattr(expr, "loc", Span()),
									notes=list(getattr(failure.obligation, "notes", []) or []) if failure is not None else None,
								)
							raise ResolutionError(
								f"no matching method '{expr.method_name}' for receiver {recv_ty} and args {arg_types}",
								span=getattr(expr, "loc", Span()),
							)
						best = viable
						if viable:
							best_pref = min(pref for _res, _impl_args, _fn_args, _inst_params, pref in viable)
							best = [item for item in viable if item[4] == best_pref]
							best = _dedupe_by_key(
								best,
								lambda item: _candidate_key_for_decl(item[0].decl),
							)
							if len(best) > 1:
								best = _pick_most_specific_items(
									best,
									lambda item: _candidate_key_for_decl(item[0].decl),
									require_info,
								)
							if len(best) > 1:
								mod_names: list[str] = []
								notes: list[str] = []
								seen_mods: set[str] = set()

								def _module_ambig_key(
									item: tuple[
										MethodResolution,
										Tuple[TypeId, ...],
										Tuple[TypeId, ...],
										Tuple[TypeId, ...],
										int,
									],
								) -> tuple[str, str, int]:
									res, _impl_args, _fn_args, _inst_params, _pref = item
									mod_label = (
										res.decl.fn_id.module
										if res.decl.fn_id is not None and res.decl.fn_id.module
										else str(res.decl.module_id)
									)
									fn_name = res.decl.fn_id.name if res.decl.fn_id is not None else ""
									fn_ord = res.decl.fn_id.ordinal if res.decl.fn_id is not None else 0
									return (mod_label, fn_name, int(fn_ord))

								for res, _impl_args, _fn_args, _inst_params, _pref in sorted(best, key=_module_ambig_key):
									mod_label = (
										res.decl.fn_id.module
										if res.decl.fn_id is not None and res.decl.fn_id.module
										else str(res.decl.module_id)
									)
									if mod_label not in seen_mods:
										mod_names.append(mod_label)
										seen_mods.add(mod_label)
									chain_note = _visibility_note(res.decl.module_id)
									if chain_note:
										notes.append(f"{mod_label} {chain_note}")
								if trait_index and trait_scope_by_module:
									traits_in_scope = _traits_in_scope()
									if any(trait_index.has_method(tr, expr.method_name) for tr in traits_in_scope):
										notes.append("inherent methods took precedence; use UFCS to call a trait method")
								mod_list = ", ".join(mod_names)
								recv_label = _label_typeid(recv_ty)
								raise ResolutionError(
									f"ambiguous method '{expr.method_name}' for receiver {recv_label} and args {arg_types}; candidates from modules: {mod_list}",
									span=getattr(expr, "loc", Span()),
									notes=notes,
									code="E-METHOD-AMBIGUOUS",
								)
						resolution, impl_args, fn_args, inst_params, _pref = best[0]
						call_resolutions[expr.node_id] = resolution
						result_type = resolution.result_type or resolution.decl.signature.result_type
						target_fn_id = resolution.decl.fn_id
						if target_fn_id is None:
							raise ResolutionError(
								f"missing function id for method '{expr.method_name}' (compiler bug)",
								span=getattr(expr, "loc", Span()),
							)
						sig_for_throw = signatures_by_id.get(target_fn_id) if signatures_by_id is not None else None
						if sig_for_throw is None:
							call_can_throw = True
						elif sig_for_throw.declared_can_throw is None:
							diagnostics.append(
								_tc_diag(
									message="internal: signature missing declared_can_throw (checker bug)",
									severity="error",
									span=Span(),
								)
							)
							call_can_throw = True
						else:
							call_can_throw = bool(sig_for_throw.declared_can_throw)
						applied = _apply_method_boundary(
							expr,
							target_fn_id=target_fn_id,
							sig_for_throw=sig_for_throw,
							call_can_throw=call_can_throw,
						)
						if applied is None:
							return record_expr(expr, self._unknown)
						target_fn_id, call_can_throw = applied
						updated_arg_types, had_autoborrow_error = _apply_autoborrow_args(
							expr.args,
							arg_types,
							list(inst_params[1:]),
							span=getattr(expr, "loc", Span()),
						)
						arg_types = updated_arg_types
						if had_autoborrow_error:
							record_method_call_info(
								expr,
								param_types=list(inst_params),
								return_type=result_type or self._unknown,
								can_throw=call_can_throw,
								target=target_fn_id,
							)
							return record_expr(expr, self._unknown)
						record_method_call_info(
							expr,
							param_types=list(inst_params),
							return_type=result_type or self._unknown,
							can_throw=call_can_throw,
							target=target_fn_id,
						)
						record_instantiation(
							callsite_id=getattr(expr, "callsite_id", None),
							target_fn_id=resolution.decl.fn_id,
							impl_args=impl_args,
							fn_args=fn_args,
						)
						return record_expr(expr, result_type)
					except ResolutionError as err:
						diag_span = getattr(err, "span", None) or getattr(expr, "loc", Span())
						diagnostics.append(
							_tc_diag(
								message=str(err),
								code=getattr(err, "code", None),
								severity="error",
								span=diag_span,
								notes=list(getattr(err, "notes", []) or []),
							)
						)
						return record_expr(expr, self._unknown)

				return record_expr(expr, self._unknown)

			# Field access and indexing.
			#
			# Canonical place expressions (`HPlaceExpr`) denote addressable storage
			# locations. In expression position they behave like lvalues: their type is
			# the type of the referenced storage location.
			if hasattr(H, "HPlaceExpr") and isinstance(expr, getattr(H, "HPlaceExpr")):
				current_ty = type_expr(expr.base, used_as_value=False)
				for proj in expr.projections:
					if isinstance(proj, H.HPlaceDeref):
						td = self.type_table.get(current_ty)
						if td.kind is not TypeKind.REF or not td.param_types:
							diagnostics.append(
								_tc_diag(
									message="deref requires a reference value",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						current_ty = td.param_types[0]
						continue
					if isinstance(proj, H.HPlaceField):
						td = self.type_table.get(current_ty)
						if td.kind is not TypeKind.STRUCT:
							diagnostics.append(
								_tc_diag(
									message="field access requires a struct value",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						info = self.type_table.struct_field(current_ty, proj.name)
						if info is None:
							diagnostics.append(
								_tc_diag(
									message=f"unknown field '{proj.name}' on struct '{td.name}'",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						_, field_ty = info
						current_ty = field_ty
						continue
					if isinstance(proj, H.HPlaceIndex):
						idx_ty = type_expr(proj.index)
						if idx_ty is not None and idx_ty != self._int:
							diagnostics.append(
								_tc_diag(
									message="array index must be an Int",
									severity="error",
									span=getattr(proj.index, "loc", getattr(expr, "loc", Span())),
								)
							)
							return record_expr(expr, self._unknown)
						td = self.type_table.get(current_ty)
						if td.kind is not TypeKind.ARRAY or not td.param_types:
							diagnostics.append(
								_tc_diag(
									message="indexing requires an Array value",
									severity="error",
									span=getattr(expr, "loc", Span()),
								)
							)
							return record_expr(expr, self._unknown)
						current_ty = td.param_types[0]
						continue
					diagnostics.append(
						_tc_diag(
							message="unsupported place projection",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				_require_copy_value(current_ty, span=getattr(expr, "loc", Span()), used_as_value=used_as_value)
				return record_expr(expr, current_ty)

			if isinstance(expr, H.HField):
				sub_ty = type_expr(expr.subject, used_as_value=False)
				if expr.name in ("len", "cap", "capacity"):
					# Array/String length/capacity sugar returns Uint.
					inner_ty = sub_ty
					inner_def = self.type_table.get(inner_ty)
					if inner_def.kind is TypeKind.REF and inner_def.param_types:
						inner_ty = inner_def.param_types[0]
						inner_def = self.type_table.get(inner_ty)
					if inner_def.kind is TypeKind.ARRAY:
						return record_expr(expr, self._uint)
					if expr.name == "len" and inner_ty == self._string:
						return record_expr(expr, self._uint)
					if expr.name in ("cap", "capacity"):
						diagnostics.append(
							_tc_diag(
								message="cap is only supported on Array values",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
					else:
						diagnostics.append(
							_tc_diag(
								message="len(x): unsupported argument type",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
					return record_expr(expr, self._unknown)
				if expr.name == "attrs":
					diagnostics.append(
						_tc_diag(
							message='attrs must be indexed: use error.attrs["key"]',
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				# Struct fields: `x.field`
				sub_def = self.type_table.get(sub_ty)
				if sub_def.kind is TypeKind.STRUCT:
					info = self.type_table.struct_field(sub_ty, expr.name)
					if info is None:
						diagnostics.append(
							_tc_diag(
								message=f"unknown field '{expr.name}' on struct '{sub_def.name}'",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					_, field_ty = info
					_require_copy_value(field_ty, span=getattr(expr, "loc", Span()), used_as_value=used_as_value)
					return record_expr(expr, field_ty)
				return record_expr(expr, self._unknown)

			if isinstance(expr, H.HIndex):
				# Special-case Error.attrs["key"] → DiagnosticValue.
				if isinstance(expr.subject, H.HField) and expr.subject.name == "attrs":
					sub_ty = type_expr(expr.subject.subject, used_as_value=False)
					key_ty = type_expr(expr.index)
					if self.type_table.get(sub_ty).kind is not TypeKind.ERROR:
						diagnostics.append(
							_tc_diag(
								message="attrs access is only supported on Error values",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					if self.type_table.get(key_ty).name != "String":
						diagnostics.append(
							_tc_diag(
								message="Error.attrs expects a String key",
								severity="error",
								span=getattr(expr, "loc", Span()),
								code="E-ERROR-ATTR-KEY-NOT-STRING",
							)
						)
					return record_expr(expr, self._dv)

				sub_ty = type_expr(expr.subject, used_as_value=False)
				idx_ty = type_expr(expr.index)
				td = self.type_table.get(sub_ty)
				if idx_ty is not None:
					td_idx = self.type_table.get(idx_ty)
					if td_idx.kind is not TypeKind.TYPEVAR and idx_ty != self._int:
						diagnostics.append(
							_tc_diag(
								message="array index must be an Int",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
				if td.kind is TypeKind.ARRAY and td.param_types:
					elem_ty = td.param_types[0]
					_require_copy_value(elem_ty, span=getattr(expr, "loc", Span()), used_as_value=used_as_value)
					return record_expr(expr, elem_ty)
				diagnostics.append(
					_tc_diag(
						message="indexing requires an Array value",
						severity="error",
						span=getattr(expr, "loc", Span()),
					)
				)
				return record_expr(expr, self._unknown)

			# Disallow implicit setters; attrs require explicit runtime helpers in MIR.
			if isinstance(expr, H.HCall) and isinstance(expr.fn, H.HField) and expr.fn.name == "attrs":
				diagnostics.append(
					_tc_diag(
						message="attrs values must be DiagnosticValue; implicit setters are not supported",
						severity="error",
						span=getattr(expr, "loc", Span()),
					)
				)
				return record_expr(expr, self._unknown)

			# Unary/binary ops (MVP).
			if isinstance(expr, H.HUnary):
				sub_ty = type_expr(expr.expr, used_as_value=(expr.op is not H.UnaryOp.DEREF))
				if expr.op is H.UnaryOp.NEG:
					return record_expr(expr, sub_ty if sub_ty in (self._int, self._float) else self._unknown)
				if expr.op in (H.UnaryOp.NOT,):
					return record_expr(expr, self._bool)
				if expr.op is H.UnaryOp.BIT_NOT:
					return record_expr(expr, sub_ty if sub_ty in (self._uint,) else self._unknown)
				if expr.op is H.UnaryOp.DEREF:
					if sub_ty is None:
						return record_expr(expr, self._unknown)
					td = self.type_table.get(sub_ty)
					if td.kind is not TypeKind.REF or not td.param_types:
						diagnostics.append(
							_tc_diag(
								message="deref requires a reference value",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					inner = td.param_types[0]
					_require_copy_value(inner, span=getattr(expr, "loc", Span()), used_as_value=used_as_value)
					return record_expr(expr, inner)
				return record_expr(expr, self._unknown)

			if isinstance(expr, H.HBinary):
				left_expr = expr.left
				right_expr = expr.right
				if isinstance(left_expr, H.HLiteralInt) and not isinstance(right_expr, H.HLiteralInt):
					right_ty = type_expr(right_expr)
					left_ty = type_expr(left_expr, expected_type=right_ty)
				elif isinstance(right_expr, H.HLiteralInt) and not isinstance(left_expr, H.HLiteralInt):
					left_ty = type_expr(left_expr)
					right_ty = type_expr(right_expr, expected_type=left_ty)
				else:
					left_ty = type_expr(left_expr)
					right_ty = type_expr(right_expr)
				if left_ty == self._string and right_ty == self._string:
					if expr.op is H.BinaryOp.ADD:
						return record_expr(expr, self._string)
					if expr.op in (
						H.BinaryOp.EQ,
						H.BinaryOp.NE,
						H.BinaryOp.LT,
						H.BinaryOp.LE,
						H.BinaryOp.GT,
						H.BinaryOp.GE,
					):
						return record_expr(expr, self._bool)
				if expr.op in (
					H.BinaryOp.ADD,
					H.BinaryOp.SUB,
					H.BinaryOp.MUL,
					H.BinaryOp.MOD,
				):
					# Arithmetic on Int/Float; MOD also on Uint.
					if left_ty == self._int and right_ty == self._int:
						return record_expr(expr, self._int)
					if left_ty == self._uint and right_ty == self._uint:
						return record_expr(expr, self._uint)
					if left_ty == self._float and right_ty == self._float:
						return record_expr(expr, self._float)
					if expr.op is H.BinaryOp.MOD and left_ty == self._uint and right_ty == self._uint:
						return record_expr(expr, self._uint)
					return record_expr(expr, self._unknown)
				if expr.op in (H.BinaryOp.DIV,):
					if left_ty == self._int and right_ty == self._int:
						return record_expr(expr, self._int)
					if left_ty == self._uint and right_ty == self._uint:
						return record_expr(expr, self._uint)
					if left_ty == self._float and right_ty == self._float:
						return record_expr(expr, self._float)
					return record_expr(expr, self._unknown)
				if expr.op in (
					H.BinaryOp.BIT_AND,
					H.BinaryOp.BIT_OR,
					H.BinaryOp.BIT_XOR,
					H.BinaryOp.SHL,
					H.BinaryOp.SHR,
				):
					if left_ty == self._uint and right_ty == self._uint:
						return record_expr(expr, self._uint)
					diagnostics.append(
						_tc_diag(
							message="bitwise operators require Uint operands",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				if expr.op in (
					H.BinaryOp.EQ,
					H.BinaryOp.NE,
					H.BinaryOp.LT,
					H.BinaryOp.LE,
					H.BinaryOp.GT,
					H.BinaryOp.GE,
				):
					if left_ty is not None and right_ty is not None and left_ty != right_ty:
						if self.type_table.get(left_ty).kind is TypeKind.TYPEVAR:
							return record_expr(expr, self._bool)
						if self.type_table.get(right_ty).kind is TypeKind.TYPEVAR:
							return record_expr(expr, self._bool)
						diagnostics.append(
							_tc_diag(
								message="comparison requires matching operand types",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					return record_expr(expr, self._bool)
				if expr.op in (H.BinaryOp.AND, H.BinaryOp.OR):
					return record_expr(expr, self._bool)
				return record_expr(expr, self._unknown)

			# Arrays/ternary.
			if isinstance(expr, H.HArrayLiteral):
				elem_types = [type_expr(e) for e in expr.elements]
				if elem_types and all(t == elem_types[0] for t in elem_types):
					if _reject_zst_array(elem_types[0], span=getattr(expr, "loc", Span())):
						return record_expr(expr, self._unknown)
					return record_expr(expr, self.type_table.new_array(elem_types[0]))
				return record_expr(expr, self._unknown)

			if isinstance(expr, H.HTernary):
				type_expr(expr.cond)
				then_ty = type_expr(expr.then_expr)
				else_ty = type_expr(expr.else_expr)
				return record_expr(expr, then_ty if then_ty == else_ty else self._unknown)

			# Exception constructors are only legal as throw payloads.
			if isinstance(expr, H.HExceptionInit):
				if not allow_exception_init:
					diagnostics.append(
						_tc_diag(
							message="exception constructors are only valid as throw payloads",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return record_expr(expr, self._unknown)
				from lang2.driftc.core.exception_ctor_args import KwArg as _KwArg, resolve_exception_ctor_args

				schemas: dict[str, tuple[str, list[str]]] = getattr(self.type_table, "exception_schemas", {}) or {}
				schema = schemas.get(expr.event_fqn)
				decl_fields: list[str] | None
				if schema is None:
					decl_fields = None
				else:
					_decl_fqn, decl_fields = schema

				resolved, diags = resolve_exception_ctor_args(
					event_fqn=expr.event_fqn,
					declared_fields=decl_fields,
					pos_args=[(a, getattr(a, "loc", Span())) for a in expr.pos_args],
					kw_args=[
						_KwArg(name=kw.name, value=kw.value, name_span=getattr(kw, "loc", Span()))
						for kw in expr.kw_args
					],
					span=getattr(expr, "loc", Span()),
				)
				diagnostics.extend(diags)

				values_to_validate = [v for _name, v in resolved]
				if decl_fields is None:
					# Unknown schema: we cannot map positional args to names, but we
					# still validate that provided values are DV or supported literals.
					values_to_validate = list(expr.pos_args) + [kw.value for kw in expr.kw_args]

				for val_expr in values_to_validate:
					val_ty = type_expr(val_expr)
					is_primitive_literal = isinstance(val_expr, (H.HLiteralInt, H.HLiteralBool, H.HLiteralString))
					if val_ty != self._dv and not is_primitive_literal:
						diagnostics.append(
							_tc_diag(
								message=(
									"exception field value must be a DiagnosticValue or a primitive literal "
									"(Int/Bool/String)"
								),
								severity="error",
								span=getattr(val_expr, "loc", Span()),
							)
						)
				return record_expr(expr, self._dv)

			# DiagnosticValue constructors.
			if isinstance(expr, H.HDVInit):
				arg_types = [type_expr(a) for a in expr.args]
				if expr.args:
					# Only zero-arg (missing) or single-arg primitive DV ctors are supported in v1.
					if len(expr.args) > 1:
						diagnostics.append(
							_tc_diag(
								message="DiagnosticValue constructors support at most one argument in v1",
								severity="error",
								span=getattr(expr, "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
					inner_ty = arg_types[0]
					if inner_ty not in (self._int, self._bool, self._string):
						diagnostics.append(
							_tc_diag(
								message="unsupported DiagnosticValue constructor argument type",
								severity="error",
								span=getattr(expr.args[0], "loc", Span()),
							)
						)
						return record_expr(expr, self._unknown)
				return record_expr(expr, self._dv)

			# Result/try sugar.
			if isinstance(expr, H.HResultOk):
				ok_ty = type_expr(expr.value)
				err_ty = self._unknown
				return record_expr(expr, self.type_table.new_fnresult(ok_ty, err_ty))

			# Fallback: unknown type.
			return record_expr(expr, self._unknown)

		catch_depth = 0

		def type_stmt(stmt: H.HStmt) -> None:
			nonlocal catch_depth
			# Borrow conflicts are diagnosed within a single statement.
			borrows_in_stmt.clear()
			if isinstance(stmt, H.HLet):
				if stmt.binding_id is None:
					stmt.binding_id = self._alloc_local_id()
				locals.append(stmt.binding_id)
				declared_ty: TypeId | None = None
				if getattr(stmt, "declared_type_expr", None) is not None:
					try:
						_reject_fixed_width_type_expr(
							stmt.declared_type_expr,
							getattr(stmt.declared_type_expr, "module_id", None) or current_module_name,
							Span.from_loc(getattr(stmt.declared_type_expr, "loc", None)),
						)
						declared_ty = resolve_opaque_type(stmt.declared_type_expr, self.type_table, module_id=current_module_name)
					except Exception:
						declared_ty = None
					if declared_ty is not None:
						_enforce_struct_requires(
							declared_ty,
							Span.from_loc(getattr(stmt.declared_type_expr, "loc", None)),
						)
				# If the user provides a type annotation, treat it as the expected type
				# for the initializer. This enables constructor calls like:
				#   val x: Optional<Int> = Some(1)
				inferred_ty = type_expr(stmt.value, expected_type=declared_ty)
				val_ty = inferred_ty
				if declared_ty is not None:
					# MVP: treat the declared type as authoritative for the binding.
					# If the initializer is obviously incompatible, emit a diagnostic.
					# Numeric literals are allowed to flow into Int/Uint without requiring
					# an explicit cast.
					if inferred_ty is not None and inferred_ty != declared_ty:
						is_int_lit = isinstance(stmt.value, H.HLiteralInt)
						decl_name = self.type_table.get(declared_ty).name
						inf_name = self.type_table.get(inferred_ty).name
						if not (is_int_lit and decl_name in ("Int", "Uint") and inf_name == "Int"):
							diagnostics.append(
								_tc_diag(
									message=f"initializer type '{inf_name}' does not match declared type '{decl_name}'",
									severity="error",
									span=getattr(stmt, "loc", Span()),
								)
							)
					val_ty = declared_ty
				scope_env[-1][stmt.name] = val_ty
				scope_bindings[-1][stmt.name] = stmt.binding_id
				binding_types[stmt.binding_id] = val_ty
				binding_names[stmt.binding_id] = stmt.name
				binding_mutable[stmt.binding_id] = bool(getattr(stmt, "is_mutable", False))
				binding_place_kind[stmt.binding_id] = PlaceKind.LOCAL
				# Track origin for ref-typed locals: allow propagation from an existing
				# ref binding, otherwise treat as local/temporary.
				if val_ty is not None and self.type_table.get(val_ty).kind is TypeKind.REF:
					origin: Optional[int] = None
					# val r = p;  (p is a ref param or a local ref derived from param)
					if isinstance(stmt.value, H.HVar) and getattr(stmt.value, "binding_id", None) is not None:
						origin = ref_origin_param.get(stmt.value.binding_id)
					# val r = &(*p).x;  (reborrow through a ref that derives from param)
					if isinstance(stmt.value, H.HBorrow):
						def _base_lookup(hv: object) -> Optional[PlaceBase]:
							bid = getattr(hv, "binding_id", None)
							if bid is None:
								return None
							kind = binding_place_kind.get(bid, PlaceKind.LOCAL)
							name = hv.name if hasattr(hv, "name") else str(hv)
							return PlaceBase(kind=kind, local_id=bid, name=name)

						sub_place = place_from_expr(stmt.value.subject, base_lookup=_base_lookup)
						if sub_place is not None and any(isinstance(p, DerefProj) for p in sub_place.projections):
							origin = ref_origin_param.get(sub_place.base.local_id)
					ref_origin_param[stmt.binding_id] = origin
			elif isinstance(stmt, H.HBlock):
				# Block statements introduce a nested lexical scope.
				#
				# This is used by desugarings like `for` which need to introduce hidden
				# temporaries without leaking them to the surrounding scope.
				scope_env.append(dict())
				scope_bindings.append(dict())
				try:
					for s in stmt.statements:
						type_stmt(s)
				finally:
					scope_env.pop()
					scope_bindings.pop()
			elif isinstance(stmt, H.HAssign):
				cap_bid = None
				cap_name = None
				if hasattr(H, "HPlaceExpr") and isinstance(stmt.target, getattr(H, "HPlaceExpr")) and not stmt.target.projections:
					if isinstance(stmt.target.base, H.HVar):
						cap_bid = getattr(stmt.target.base, "binding_id", None)
						cap_name = stmt.target.base.name
				elif isinstance(stmt.target, H.HVar):
					cap_bid = getattr(stmt.target, "binding_id", None)
					cap_name = stmt.target.name
				if cap_bid is not None and cap_name is not None:
					cap_kind = _explicit_capture_kind(cap_bid)
					if cap_kind == "ref":
						diagnostics.append(
							_tc_diag(
								message=f"capture '{cap_name}' is shared; capture &mut {cap_name} to mutate",
								severity="error",
								span=getattr(stmt, "loc", Span()),
							)
						)
						return
				type_expr(stmt.value)
				type_expr(stmt.target, used_as_value=False)
				# Assignment target must be an addressable place.
				def _base_lookup(hv: object) -> Optional[PlaceBase]:
					bid = getattr(hv, "binding_id", None)
					if bid is None:
						return None
					kind = binding_place_kind.get(bid, PlaceKind.LOCAL)
					name = hv.name if hasattr(hv, "name") else str(hv)
					return PlaceBase(kind=kind, local_id=bid, name=name)

				if place_from_expr(stmt.target, base_lookup=_base_lookup) is None:
					diagnostics.append(
						_tc_diag(
							message="assignment target must be an addressable place",
							severity="error",
							span=getattr(stmt, "loc", Span()),
							)
						)
				# If assigning to a ref-typed binding, track origin (simple propagation).
				if isinstance(stmt.target, H.HVar) and getattr(stmt.target, "binding_id", None) is not None:
					tgt_bid = stmt.target.binding_id
					tgt_ty = binding_types.get(tgt_bid)
					if tgt_ty is not None and self.type_table.get(tgt_ty).kind is TypeKind.REF:
						origin: Optional[int] = None
						if isinstance(stmt.value, H.HVar) and getattr(stmt.value, "binding_id", None) is not None:
							origin = ref_origin_param.get(stmt.value.binding_id)
						ref_origin_param[tgt_bid] = origin
			elif hasattr(H, "HAugAssign") and isinstance(stmt, getattr(H, "HAugAssign")):
				"""
				Augmented assignment (`+=`) type rules (MVP).

				- Target must be an addressable place (same as `=`).
				- Operand types must match.
				- Currently supported for numeric scalars only (Int/Float).

				We enforce *writability* here as well:
				- Writes to owned storage require a `var` base binding.
				- Writes through deref require a mutable reference (`&mut`) at each deref.
				"""
				cap_bid = None
				cap_name = None
				if hasattr(H, "HPlaceExpr") and isinstance(stmt.target, getattr(H, "HPlaceExpr")) and not stmt.target.projections:
					if isinstance(stmt.target.base, H.HVar):
						cap_bid = getattr(stmt.target.base, "binding_id", None)
						cap_name = stmt.target.base.name
				elif isinstance(stmt.target, H.HVar):
					cap_bid = getattr(stmt.target, "binding_id", None)
					cap_name = stmt.target.name
				if cap_bid is not None and cap_name is not None:
					cap_kind = _explicit_capture_kind(cap_bid)
					if cap_kind == "ref":
						diagnostics.append(
							_tc_diag(
								message=f"capture '{cap_name}' is shared; capture &mut {cap_name} to mutate",
								severity="error",
								span=getattr(stmt, "loc", Span()),
							)
						)
						return
				tgt_ty = type_expr(stmt.target, used_as_value=False)
				val_ty = type_expr(stmt.value)

				def _base_lookup(hv: object) -> Optional[PlaceBase]:
					bid = getattr(hv, "binding_id", None)
					if bid is None:
						return None
					kind = binding_place_kind.get(bid, PlaceKind.LOCAL)
					name = hv.name if hasattr(hv, "name") else str(hv)
					return PlaceBase(kind=kind, local_id=bid, name=name)

				tgt_place = place_from_expr(stmt.target, base_lookup=_base_lookup)
				if tgt_place is None:
					diagnostics.append(
						_tc_diag(
							message="assignment target must be an addressable place",
							severity="error",
							span=getattr(stmt, "loc", Span()),
						)
					)
					return

				# Writability: owned storage requires `var`; reborrow writes require `&mut`.
				has_deref = any(isinstance(p, DerefProj) for p in tgt_place.projections)
				if not has_deref and tgt_place.base.local_id is not None and not binding_mutable.get(tgt_place.base.local_id, False):
					diagnostics.append(
						_tc_diag(
							message="cannot assign through an immutable binding; declare it with `var`",
							severity="error",
							span=getattr(stmt, "loc", Span()),
						)
					)
				if has_deref and hasattr(H, "HPlaceExpr") and isinstance(stmt.target, getattr(H, "HPlaceExpr")):
					cur = type_expr(stmt.target.base)
					for pr in stmt.target.projections:
						if isinstance(pr, H.HPlaceDeref):
							ptr_def = self.type_table.get(cur)
							if ptr_def.kind is not TypeKind.REF or not ptr_def.ref_mut:
								diagnostics.append(
									_tc_diag(
										message="cannot assign through *p unless p is a mutable reference (&mut T)",
										severity="error",
										span=getattr(stmt, "loc", Span()),
									)
								)
								break
							if ptr_def.param_types:
								cur = ptr_def.param_types[0]
						elif isinstance(pr, H.HPlaceField):
							td = self.type_table.get(cur)
							if td.kind is TypeKind.STRUCT:
								info = self.type_table.struct_field(cur, pr.name)
								if info is not None:
									_, cur = info
						elif isinstance(pr, H.HPlaceIndex):
							td = self.type_table.get(cur)
							if td.kind is TypeKind.ARRAY and td.param_types:
								cur = td.param_types[0]

				arith_ops = {"+=", "-=", "*=", "/="}
				bit_ops = {"&=", "|=", "^=", "<<=", ">>="}
				mod_ops = {"%="}
				# Type check: supported augmented assignment operators.
				if stmt.op not in (arith_ops | bit_ops | mod_ops):
					diagnostics.append(
						_tc_diag(
							message=f"unsupported augmented assignment operator '{stmt.op}'",
							severity="error",
							span=getattr(stmt, "loc", Span()),
						)
					)
				if tgt_ty != val_ty:
					diagnostics.append(
						_tc_diag(
							message="augmented assignment requires matching operand types",
							severity="error",
							span=getattr(stmt, "loc", Span()),
						)
					)
				if stmt.op in arith_ops:
					if tgt_ty not in (self._int, self._float):
						pretty = self.type_table.get(tgt_ty).name if tgt_ty is not None else "Unknown"
						diagnostics.append(
							_tc_diag(
								message=f"augmented assignment '{stmt.op}' is not supported for type '{pretty}' in MVP",
								severity="error",
								span=getattr(stmt, "loc", Span()),
							)
						)
				elif stmt.op in mod_ops:
					if tgt_ty not in (self._int, self._uint):
						pretty = self.type_table.get(tgt_ty).name if tgt_ty is not None else "Unknown"
						diagnostics.append(
							_tc_diag(
								message=f"augmented assignment '{stmt.op}' is not supported for type '{pretty}' in MVP",
								severity="error",
								span=getattr(stmt, "loc", Span()),
							)
						)
				elif stmt.op in bit_ops:
					if tgt_ty != self._uint:
						pretty = self.type_table.get(tgt_ty).name if tgt_ty is not None else "Unknown"
						diagnostics.append(
							_tc_diag(
								message=f"bitwise augmented assignment requires Uint operands (have '{pretty}')",
								severity="error",
								span=getattr(stmt, "loc", Span()),
							)
						)
			elif isinstance(stmt, H.HExprStmt):
				type_expr(stmt.expr, used_as_value=False)
			elif isinstance(stmt, H.HReturn):
				if stmt.value is not None:
					type_expr(stmt.value, expected_type=return_type)
			elif isinstance(stmt, H.HIf):
				if isinstance(stmt.cond, H.HTraitExpr):
					parser_expr = _trait_expr_to_parser(stmt.cond)
					guard_key = _guard_key(stmt.cond)
					if type_param_map:
						parser_expr = _resolve_trait_subjects_for_type_params(parser_expr, type_param_map)
					subst: dict[object, object] = {}
					subjects: set[object] = set()
					_collect_trait_subjects(parser_expr, subjects)
					for subj in subjects:
						if subj == "Self":
							if self_type_id is None:
								continue
							subj_type_id = self_type_id
							subj_def = self.type_table.get(subj_type_id)
							if subj_def.kind is TypeKind.REF and subj_def.param_types:
								subj_type_id = subj_def.param_types[0]
								subj_def = self.type_table.get(subj_type_id)
							key = _normalize_type_key(type_key_from_typeid(self.type_table, subj_type_id))
							subst["Self"] = key
							if subj_def.kind is TypeKind.TYPEVAR and subj_def.type_param_id is not None:
								subst.setdefault(subj_def.type_param_id, key)
							continue
						for scope in reversed(scope_env):
							if subj in scope:
								subst[subj] = _normalize_type_key(type_key_from_typeid(self.type_table, scope[subj]))
								break
					world = visible_trait_world or global_trait_world
					if world is None:
						diagnostics.append(
							_tc_diag(
								message="trait guard cannot be evaluated without a trait world",
								severity="error",
								span=getattr(stmt.cond, "loc", Span()),
							)
						)
						type_block(stmt.then_block)
						if stmt.else_block:
							type_block(stmt.else_block)
					else:
						env = TraitEnv(
							default_module=current_module_name,
							default_package=default_package,
							module_packages=module_packages or {},
							assumed_true=set(fn_require_assumed),
						)
						res = prove_expr(world, env, subst, parser_expr)
						if res.status is ProofStatus.PROVED:
							guard_outcomes[guard_key] = res.status
							assumed = _guard_assumptions(parser_expr, subst=subst)
							_with_guard_assumptions(assumed, stmt.then_block)
						elif res.status is ProofStatus.REFUTED:
							guard_outcomes[guard_key] = res.status
							if stmt.else_block:
								type_block(stmt.else_block)
						else:
							if res.status is ProofStatus.AMBIGUOUS:
								guard_outcomes[guard_key] = res.status
								diagnostics.append(
									_tc_diag(
										message="trait guard is ambiguous at compile time",
										severity="error",
										span=getattr(stmt.cond, "loc", Span()),
									)
								)
								type_block(stmt.then_block)
								if stmt.else_block:
									type_block(stmt.else_block)
							else:
								is_generic_guard = False
								for subj in subjects:
									if isinstance(subj, TypeParamId):
										is_generic_guard = True
										break
									if isinstance(subj, str) and subj in type_param_map:
										is_generic_guard = True
										break
									if subj == "Self":
										if self_type_id is None:
											continue
										subj_type_id = self_type_id
										subj_def = self.type_table.get(subj_type_id)
										if subj_def.kind is TypeKind.REF and subj_def.param_types:
											subj_type_id = subj_def.param_types[0]
										if _type_has_typevar(subj_type_id):
											is_generic_guard = True
											break
								if not is_generic_guard:
									diagnostics.append(
										_tc_diag(
											message="internal: trait guard is not decidable for a concrete type",
											severity="error",
											span=getattr(stmt.cond, "loc", Span()),
											code="E-TRAIT-GUARD-NOT-DECIDABLE",
										)
									)
									type_block(stmt.then_block)
									if stmt.else_block:
										type_block(stmt.else_block)
								else:
									assumed = _guard_assumptions(parser_expr, subst=subst)
									_type_block_defer_diags(
										stmt.then_block,
										guard_key=guard_key,
										branch="then",
										assumed=assumed,
									)
									if stmt.else_block:
										_type_block_defer_diags(
											stmt.else_block,
											guard_key=guard_key,
											branch="else",
										)
				else:
					type_expr(stmt.cond)
					type_block(stmt.then_block)
					if stmt.else_block:
						type_block(stmt.else_block)
			elif isinstance(stmt, H.HLoop):
				type_block(stmt.body)
			elif isinstance(stmt, H.HTry):
				type_block(stmt.body)
				for arm in stmt.catches:
					catch_depth += 1
					scope_env.append(dict())
					scope_bindings.append(dict())
					try:
						if arm.binder:
							bid = self._alloc_local_id()
							locals.append(bid)
							scope_env[-1][arm.binder] = self._error
							scope_bindings[-1][arm.binder] = bid
							binding_types[bid] = self._error
							binding_names[bid] = arm.binder
							binding_mutable[bid] = False
							binding_place_kind[bid] = PlaceKind.LOCAL
						type_block(arm.block)
					finally:
						scope_env.pop()
						scope_bindings.pop()
						catch_depth -= 1
			elif isinstance(stmt, H.HThrow):
				if isinstance(stmt.value, H.HMethodCall) and stmt.value.method_name == "unwrap_err":
					type_expr(stmt.value)
				elif not isinstance(stmt.value, H.HExceptionInit):
					diagnostics.append(
						_tc_diag(
							message="throw payload must be an exception constructor",
							severity="error",
							span=getattr(stmt, "loc", Span()),
						)
					)
					type_expr(stmt.value)
				else:
					type_expr(stmt.value, allow_exception_init=True)
			elif isinstance(stmt, H.HRethrow):
				# Valid only inside a catch; outside catches it is reported here.
				if catch_depth == 0:
					diagnostics.append(
						_tc_diag(
							message="rethrow is only valid inside a catch block",
							severity="error",
							span=getattr(stmt, "loc", Span()),
						)
					)
			# HBreak/HContinue are typeless here.

		def type_block(block: H.HBlock) -> None:
			scope_env.append(dict())
			scope_bindings.append(dict())
			try:
				for s in block.statements:
					type_stmt(s)
			finally:
				scope_env.pop()
				scope_bindings.pop()

		def type_block_in_scope(block: H.HBlock) -> None:
			for s in block.statements:
				type_stmt(s)

		type_block(body)

		def _apply_fnptr_consts(obj: object) -> object:
			if isinstance(obj, H.HNode):
				entry = fnptr_consts_by_node_id.get(obj.node_id)
				if entry is not None and not isinstance(obj, H.HFnPtrConst):
					fn_ref, call_sig = entry
					repl = H.HFnPtrConst(fn_ref=fn_ref, call_sig=call_sig)
					repl.node_id = obj.node_id
					return repl
			if is_dataclass(obj):
				updates: dict[str, object] = {}
				for f in fields(obj):
					val = getattr(obj, f.name)
					new_val = _apply_fnptr_consts(val)
					if new_val is not val:
						updates[f.name] = new_val
				if updates:
					if getattr(obj, "__dataclass_params__", None) and obj.__dataclass_params__.frozen:
						new_obj = replace(obj, **updates)
						if isinstance(obj, H.HNode):
							object.__setattr__(new_obj, "node_id", obj.node_id)
						return new_obj
					for name, val in updates.items():
						setattr(obj, name, val)
				return obj
			if isinstance(obj, list):
				for idx, val in enumerate(obj):
					new_val = _apply_fnptr_consts(val)
					if new_val is not val:
						obj[idx] = new_val
				return obj
			if isinstance(obj, dict):
				for key, val in list(obj.items()):
					new_val = _apply_fnptr_consts(val)
					if new_val is not val:
						obj[key] = new_val
				return obj
			return obj

		if fnptr_consts_by_node_id:
			_apply_fnptr_consts(body)

		typed = TypedFn(
			fn_id=fn_id,
			name=fn_id.name,
			params=params,
			param_bindings=param_bindings,
			locals=locals,
			body=body,
			expr_types={ref: ty for ref, ty in expr_types.items()},
			binding_for_var=binding_for_var,
			binding_types=binding_types,
			binding_names=binding_names,
			binding_mutable=binding_mutable,
			binding_place_kind=binding_place_kind,
			call_resolutions=call_resolutions,
			call_info_by_callsite_id=call_info_by_callsite_id,
			instantiations_by_callsite_id=instantiations_by_callsite_id,
		)

		if callable_registry is not None:
			missing_callsite_nodes: list[int] = []
			missing_info: list[int] = []

			def _collect_callsite_ids(block: H.HBlock) -> set[int]:
				ids: set[int] = set()
				seen: set[int] = set()

				def walk(obj: object) -> None:
					obj_id = id(obj)
					if obj_id in seen:
						return
					seen.add(obj_id)

					if isinstance(obj, (H.HCall, H.HMethodCall, H.HInvoke)):
						csid = getattr(obj, "callsite_id", None)
						if isinstance(csid, int):
							ids.add(csid)
						else:
							missing_callsite_nodes.append(getattr(obj, "node_id", -1))

					if not _should_descend(obj):
						return
					if is_dataclass(obj):
						for f in fields(obj):
							walk_value(getattr(obj, f.name))
					else:
						for val in vars(obj).values():
							walk_value(val)

				def walk_value(val: object) -> None:
					if val is None:
						return
					if isinstance(val, (list, tuple)):
						for item in val:
							walk_value(item)
						return
					if isinstance(val, dict):
						for key in sorted(val.keys(), key=repr):
							walk_value(val[key])
						return
					walk(val)

				def _should_descend(obj: object) -> bool:
					if isinstance(obj, H.HNode):
						return True
					if is_dataclass(obj) and obj.__class__.__module__.startswith("lang2.driftc.stage1"):
						return True
					return False

				walk(block)
				return ids

			callsite_ids = _collect_callsite_ids(body)
			for csid in sorted(callsite_ids):
				if csid not in call_info_by_callsite_id:
					missing_info.append(csid)
			if (
				not any(getattr(d, "severity", None) == "error" for d in diagnostics)
				and not deferred_guard_diags
			):
				if missing_callsite_nodes:
					diagnostics.append(
						_tc_diag(
							message=(
								"internal: missing callsite_id on call nodes "
								f"in '{function_symbol(fn_id)}' (nodes: {sorted(missing_callsite_nodes)[:5]})"
							),
							severity="error",
							span=Span(),
						)
					)
				if missing_info:
					diagnostics.append(
						_tc_diag(
							message=(
								"internal: missing CallInfo for callsite_id "
								f"in '{function_symbol(fn_id)}' (ids: {sorted(missing_info)[:5]})"
							),
							severity="error",
							span=Span(),
						)
					)

		# MVP escape policy: reference returns must be derived from a single
		# reference parameter.
		if return_type is not None and self.type_table.get(return_type).kind is TypeKind.REF:
			# Seed origin for reference parameters.
			for bid in param_bindings:
				pty = binding_types.get(bid)
				if pty is not None and self.type_table.get(pty).kind is TypeKind.REF:
					ref_origin_param[bid] = bid

			def _return_origin(expr: H.HExpr) -> Optional[int]:
				# Returning an existing reference value (param or local ref).
				if isinstance(expr, H.HVar) and getattr(expr, "binding_id", None) is not None:
					return ref_origin_param.get(expr.binding_id)
				if hasattr(H, "HPlaceExpr") and isinstance(expr, getattr(H, "HPlaceExpr")):
					if isinstance(expr.base, H.HVar) and getattr(expr.base, "binding_id", None) is not None:
						return ref_origin_param.get(expr.base.binding_id)
				# Returning a borrow is only allowed when it reborrows through a ref
				# that originates from a reference parameter (e.g. &(*p).x).
				if isinstance(expr, H.HBorrow):
					def _base_lookup(hv: object) -> Optional[PlaceBase]:
						bid = getattr(hv, "binding_id", None)
						if bid is None:
							return None
						kind = binding_place_kind.get(bid, PlaceKind.LOCAL)
						name = hv.name if hasattr(hv, "name") else str(hv)
						return PlaceBase(kind=kind, local_id=bid, name=name)

					sub_place = place_from_expr(expr.subject, base_lookup=_base_lookup)
					if sub_place is None:
						return None
					if not any(isinstance(p, DerefProj) for p in sub_place.projections):
						return None
					return ref_origin_param.get(sub_place.base.local_id)
				return None

			def _walk_returns(block: H.HBlock, out: List[tuple[Optional[int], Span]]) -> None:
				for s in block.statements:
					if isinstance(s, H.HReturn) and s.value is not None:
						out.append((_return_origin(s.value), getattr(s, "loc", getattr(s.value, "loc", Span()))))
					elif isinstance(s, H.HIf):
						_walk_returns(s.then_block, out)
						if s.else_block:
							_walk_returns(s.else_block, out)
					elif isinstance(s, H.HLoop):
						_walk_returns(s.body, out)
					elif isinstance(s, H.HTry):
						_walk_returns(s.body, out)
						for arm in s.catches:
							_walk_returns(arm.block, out)

			returns: List[tuple[Optional[int], Span]] = []
			_walk_returns(body, returns)

			# Determine the single allowed origin param (if any).
			origin_param: Optional[int] = None
			for origin, span in returns:
				if origin is None:
					diagnostics.append(
						_tc_diag(
							message="reference return must be derived from a reference parameter (MVP escape rule)",
							severity="error",
							span=span,
						)
					)
					continue
				if origin_param is None:
					origin_param = origin
				elif origin != origin_param:
					diagnostics.append(
						_tc_diag(
							message="reference return must derive from a single reference parameter (cannot return from different params)",
							severity="error",
							span=span,
						)
					)

		for d in diagnostics:
			self._stamp_diag_phase(d)
		return TypeCheckResult(
			typed_fn=typed,
			diagnostics=diagnostics,
			deferred_guard_diags=deferred_guard_diags,
			guard_outcomes=guard_outcomes,
		)

	def _alloc_param_id(self) -> ParamId:
		pid = self._next_binding_id
		self._next_binding_id += 1
		return pid

	def _alloc_local_id(self) -> LocalId:
		lid = self._next_binding_id
		self._next_binding_id += 1
		return lid


def validate_entrypoint_main(
	signatures_by_id: Mapping[FunctionId, FnSignature],
	type_table: TypeTable,
	diagnostics: list[Diagnostic],
) -> None:
	main_defs: list[tuple[FunctionId, FnSignature]] = []
	for fn_id, sig in signatures_by_id.items():
		if sig.is_method:
			continue
		if fn_id.name == "main":
			main_defs.append((fn_id, sig))

	if not main_defs:
		diagnostics.append(
			_tc_diag(
				message="missing entry point 'main' for code generation",
				severity="error",
				phase="typecheck",
				span=Span(),
			)
		)
		return

	def _span_for_sig(sig: FnSignature) -> Span:
		return Span.from_loc(getattr(sig, "loc", None))

	if len(main_defs) > 1:
		first_id, first_sig = main_defs[0]
		first_span = _span_for_sig(first_sig)
		for fn_id, sig in main_defs[1:]:
			diagnostics.append(
				_tc_diag(
					message="duplicate entry point definition for 'main'",
					severity="error",
					phase="typecheck",
					span=_span_for_sig(sig),
				)
			)
			diagnostics.append(
				_tc_diag(
					message="previous definition of 'main' is here",
					severity="note",
					phase="typecheck",
					span=first_span,
				)
			)
		return

	fn_id, sig = main_defs[0]
	int_id = type_table.ensure_int()
	string_id = type_table.ensure_string()

	ret_id = sig.return_type_id
	if ret_id is None and sig.return_type is not None:
		ret_id = resolve_opaque_type(sig.return_type, type_table, module_id=sig.module)
	param_ids = sig.param_type_ids
	if param_ids is None and sig.param_types is not None:
		param_ids = [resolve_opaque_type(p, type_table, module_id=sig.module) for p in sig.param_types]
	if param_ids is None:
		param_ids = []

	if ret_id != int_id:
		diagnostics.append(
			_tc_diag(
				message="entrypoint main must return Int",
				severity="error",
				phase="typecheck",
				span=_span_for_sig(sig),
			)
		)

	params = list(param_ids or [])
	param_names = list(sig.param_names or [])
	if params:
		valid = False
		if len(params) == 1 and len(param_names) == 1 and param_names[0] == "argv":
			td = type_table.get(params[0])
			if td.kind is TypeKind.ARRAY and td.param_types and td.param_types[0] == string_id:
				valid = True
		if not valid:
			diagnostics.append(
				_tc_diag(
					message="entrypoint main has invalid signature; expected main() or main(argv: Array<String>)",
					severity="error",
					phase="typecheck",
					span=_span_for_sig(sig),
				)
			)

	if sig.declared_can_throw is not False:
		diagnostics.append(
			_tc_diag(
				message="entrypoint main must be declared nothrow (uncaught exceptions are not supported yet)",
				severity="error",
				phase="typecheck",
				span=_span_for_sig(sig),
				notes=["add 'nothrow' to main or handle failures explicitly"],
			)
		)
