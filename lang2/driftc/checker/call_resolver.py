from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Optional

from lang2.driftc.infer import InferContext, InferError, InferErrorKind, InferResult
from lang2.driftc.checker import FnSignature
from lang2.driftc.core.types_core import (
	FunctionId,
	GenericTypeExpr,
	TypeId,
	TypeKind,
	TypeParamId,
)
from lang2.driftc.core.type_subst import Subst, apply_subst
from lang2.driftc.checker import TypeParam
from lang2.driftc.stage1.call_info import CallInfo, CallSig, CallTarget, IntrinsicKind
from lang2.driftc.method_registry import CallableDecl, CallableSignature, CallableKind, Visibility, SelfMode
from lang2.driftc.checker.unsafe_gate import check_unsafe_call
from lang2.driftc.traits.linked_world import BOOL_TRUE
from lang2.driftc.traits.solver import Env as TraitEnv, Obligation, ObligationOrigin, ObligationOriginKind, ProofFailure, ProofFailureReason, ProofStatus, prove_expr, prove_obligation
from lang2.driftc.traits.world import TraitKey
from lang2.driftc.trait_index import TraitImplCandidate
from lang2.driftc.traits.world import trait_key_from_expr, type_key_from_typeid
from lang2.driftc.method_resolver import MethodResolution, ResolutionError
from lang2.driftc.parser import ast as parser_ast
from lang2.driftc.stage1 import hir_nodes as H
from lang2.driftc.stage1.place_expr import place_expr_from_lvalue_expr
from lang2.driftc.core.span import Span
from lang2.driftc.core.type_resolve_common import resolve_opaque_type

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


def _candidate_visible(cand: CallableDecl, *, visible_modules_set: set, current_module_id: int | None) -> bool:
	return (cand.module_id in visible_modules_set and cand.visibility.is_public) or (current_module_id is not None and cand.module_id == current_module_id)


@dataclass(frozen=True)
class VariantCtorResolveResult:
	inst_return: TypeId
	inst_params: list[TypeId]
	ctor_arg_field_indices: list[int]
	ctor_args: list[object]


@dataclass(frozen=True)
class StructCtorResolveResult:
	inst_return: TypeId
	inst_params: list[TypeId]
	ctor_arg_field_indices: list[int]
	ctor_args: list[object]


@dataclass(frozen=True)
class MethodCallResult:
	return_type: TypeId
	call_info: object | None = None
	resolution: object | None = None


@dataclass(frozen=True)
class MethodResolverContext:
	type_table: object
	diagnostics: list
	current_module_name: str
	current_module: int
	default_package: Optional[str]
	module_packages: dict
	type_param_map: Optional[dict]
	preseed_type_params: Optional[dict]
	type_param_names: dict
	current_fn_id: FunctionId | None
	int_ty: TypeId
	uint_ty: TypeId
	byte_ty: TypeId
	bool_ty: TypeId
	float_ty: TypeId
	string_ty: TypeId
	void_ty: TypeId
	error_ty: TypeId
	dv_ty: TypeId
	unknown_ty: TypeId
	signatures_by_id: dict
	callable_registry: object
	trait_index: object
	trait_impl_index: object
	impl_index: object
	visible_modules: tuple
	visible_trait_world: object
	global_trait_world: object
	trait_scope_by_module: dict
	require_env_local: object
	fn_require_assumed: set
	traits_in_scope: Callable[[], list[TraitKey]]
	trait_key_for_id: Callable[[int], TraitKey | None] | None
	tc_diag: Callable[..., object]
	type_expr: Callable[..., TypeId]
	optional_variant_type: Callable[[TypeId], TypeId]
	unwrap_ref_type: Callable[[TypeId], TypeId]
	struct_base_and_args: Callable[[TypeId], tuple[TypeId, list[TypeId]]]
	receiver_place: Callable[[object], object | None]
	receiver_can_mut_borrow: Callable[[object, object | None], bool]
	receiver_compat: Callable[[TypeId, TypeId, object], tuple[bool, bool]]
	receiver_preference: Callable[[object, bool, bool, bool], int | None]
	args_match_params: Callable[[list[TypeId], list[TypeId]], bool]
	coerce_args_for_params: Callable[[list[TypeId], list[TypeId]], list[TypeId]]
	infer_receiver_arg_type: Callable[[object, TypeId, bool, bool], TypeId]
	instantiate_sig_with_subst: Callable[..., InferResult]
	apply_autoborrow_args: Callable[..., tuple[list[TypeId], bool]]
	label_typeid: Callable[[TypeId], str]
	trait_label: Callable[[TraitKey], str]
	require_for_fn: Callable[[FunctionId | None], parser_ast.TraitExpr | None]
	extract_conjunctive_facts: Callable[[parser_ast.TraitExpr], list[parser_ast.TraitExpr]]
	subject_name: Callable[[object], str | None]
	normalize_type_key: Callable[[str], str]
	collect_trait_subjects: Callable[[parser_ast.TraitExpr, set], None]
	require_failure: Callable[..., object | None]
	format_failure_message: Callable[[object], str]
	failure_code: Callable[[object], str | None]
	pick_best_failure: Callable[[list], object | None]
	requirement_notes: Callable[[object], list[str]] | None
	param_scope_map: Callable[[FnSignature], dict]
	candidate_key_for_decl: Callable[[CallableDecl], object]
	visibility_note: Callable[[int], str]
	intrinsic_method_fn_id: Callable[[str], FunctionId]
	instantiate_sig: Callable[..., object]
	self_mode_from_sig: Callable[[FnSignature], object]
	match_impl_type_args: Callable[..., object]
	format_infer_failure: Callable[..., tuple[str, list[str]]]
	visibility_provenance: dict | None = None
	module_ids_by_name: dict | None = None
	record_instantiation: Callable[[int | None, FunctionId | None, tuple[TypeId, ...], tuple[TypeId, ...]], None] | None = None


@dataclass(frozen=True)
class ResolverContext:
	type_table: object
	diagnostics: list
	current_module_name: str
	default_package: Optional[str]
	module_packages: dict
	type_param_map: Optional[dict]
	preseed_type_params: Optional[dict]
	int_ty: TypeId
	uint_ty: TypeId
	uint64_ty: TypeId
	byte_ty: TypeId
	bool_ty: TypeId
	float_ty: TypeId
	string_ty: TypeId
	void_ty: TypeId
	error_ty: TypeId
	dv_ty: TypeId
	unknown_ty: TypeId
	tc_diag: Callable[..., object]
	fixed_width_allowed: Callable[[str], bool]
	reject_zst_array: Callable[[TypeId, Span], bool]
	pretty_type_name: Callable[[TypeId, str], str]
	format_ctor_signature_list: Callable[..., list[str]]
	instantiate_sig: Callable[..., object]
	enforce_struct_requires: Callable[[TypeId, Span], None]
	ensure_field_visible: Callable[[TypeId, str, Span], bool]
	visible_modules_for_free_call: Callable[[str | None], tuple[int, ...]]
	module_ids_by_name: dict
	visibility_provenance: dict
	infer: Callable[..., InferResult]
	format_infer_failure: Callable[..., tuple[str, list[str]]]
	lambda_can_throw: Callable[..., bool]
	allow_unsafe: bool
	unsafe_context: bool
	allow_unsafe_without_block: bool
	allow_rawbuffer: bool


@dataclass(frozen=True)
class CallResolverContext:
	type_table: object
	diagnostics: list
	current_module_name: str
	current_module: int
	default_package: Optional[str]
	module_packages: dict
	type_param_map: Optional[dict]
	preseed_type_params: Optional[dict]
	type_param_names: dict
	current_fn_id: FunctionId | None
	int_ty: TypeId
	uint_ty: TypeId
	uint64_ty: TypeId
	byte_ty: TypeId
	bool_ty: TypeId
	float_ty: TypeId
	string_ty: TypeId
	void_ty: TypeId
	error_ty: TypeId
	dv_ty: TypeId
	unknown_ty: TypeId
	signatures_by_id: dict
	callable_registry: object
	trait_index: object
	trait_impl_index: object
	impl_index: object
	visible_modules: tuple
	visible_trait_world: object
	global_trait_world: object
	trait_scope_by_module: dict
	require_env_local: object
	fn_require_assumed: set
	binding_mutable: dict[int, bool]
	traits_in_scope: Callable[[], list[TraitKey]]
	trait_key_for_id: Callable[[int], TraitKey | None] | None
	tc_diag: Callable[..., object]
	type_expr: Callable[..., TypeId]
	optional_variant_type: Callable[[TypeId], TypeId]
	unwrap_ref_type: Callable[[TypeId], TypeId]
	struct_base_and_args: Callable[[TypeId], tuple[TypeId, list[TypeId]]]
	receiver_place: Callable[[object], object | None]
	receiver_can_mut_borrow: Callable[[object, object | None], bool]
	receiver_compat: Callable[[TypeId, TypeId, object], tuple[bool, bool]]
	receiver_preference: Callable[[object, bool, bool, bool], int | None]
	args_match_params: Callable[[list[TypeId], list[TypeId]], bool]
	coerce_args_for_params: Callable[[list[TypeId], list[TypeId]], list[TypeId]]
	infer_receiver_arg_type: Callable[[object, TypeId, bool, bool], TypeId]
	instantiate_sig_with_subst: Callable[..., InferResult]
	apply_autoborrow_args: Callable[..., tuple[list[TypeId], bool]]
	label_typeid: Callable[[TypeId], str]
	trait_label: Callable[[TraitKey], str]
	require_for_fn: Callable[[FunctionId | None], parser_ast.TraitExpr | None]
	extract_conjunctive_facts: Callable[[parser_ast.TraitExpr], list[parser_ast.TraitExpr]]
	subject_name: Callable[[object], str | None]
	normalize_type_key: Callable[[str], str]
	collect_trait_subjects: Callable[[parser_ast.TraitExpr, set], None]
	require_failure: Callable[..., object | None]
	format_failure_message: Callable[[object], str]
	failure_code: Callable[[object], str | None]
	pick_best_failure: Callable[[list], object | None]
	requirement_notes: Callable[[object], list[str]] | None
	param_scope_map: Callable[[FnSignature], dict]
	candidate_key_for_decl: Callable[[CallableDecl], object]
	visibility_note: Callable[[int], str]
	intrinsic_method_fn_id: Callable[[str], FunctionId]
	instantiate_sig: Callable[..., object]
	self_mode_from_sig: Callable[[FnSignature], object]
	match_impl_type_args: Callable[..., object]
	fixed_width_allowed: Callable[[str], bool]
	reject_zst_array: Callable[[TypeId, Span], bool]
	pretty_type_name: Callable[[TypeId, str], str]
	format_ctor_signature_list: Callable[..., list[str]]
	enforce_struct_requires: Callable[[TypeId, Span], None]
	ensure_field_visible: Callable[[TypeId, str, Span], bool]
	visible_modules_for_free_call: Callable[[str | None], tuple[int, ...]]
	module_ids_by_name: dict
	visibility_provenance: dict
	infer: Callable[..., InferResult]
	format_infer_failure: Callable[..., tuple[str, list[str]]]
	lambda_can_throw: Callable[..., bool]
	allow_unsafe: bool
	unsafe_context: bool
	allow_unsafe_without_block: bool
	allow_rawbuffer: bool
	record_call_resolution: Callable[[object, object], None] | None
	record_instantiation: Callable[[int | None, FunctionId | None, tuple[TypeId, ...], tuple[TypeId, ...]], None] | None = None


def _require_preseed_type_params(ctx: CallResolverContext) -> dict:
	if ctx.preseed_type_params is None:
		raise AssertionError("preseed_type_params missing in CallResolverContext (checker bug)")
	return ctx.preseed_type_params


def _make_resolver_ctx(ctx: CallResolverContext, **overrides) -> ResolverContext:
	preseed_type_params = _require_preseed_type_params(ctx)
	base = dict(type_table=ctx.type_table, diagnostics=ctx.diagnostics, current_module_name=ctx.current_module_name, default_package=ctx.default_package, module_packages=ctx.module_packages, type_param_map=ctx.type_param_map, preseed_type_params=preseed_type_params, int_ty=ctx.int_ty, uint_ty=ctx.uint_ty, uint64_ty=ctx.uint64_ty, byte_ty=ctx.byte_ty, bool_ty=ctx.bool_ty, float_ty=ctx.float_ty, string_ty=ctx.string_ty, void_ty=ctx.void_ty, error_ty=ctx.error_ty, dv_ty=ctx.dv_ty, unknown_ty=ctx.unknown_ty, tc_diag=ctx.tc_diag, fixed_width_allowed=ctx.fixed_width_allowed, reject_zst_array=ctx.reject_zst_array, pretty_type_name=ctx.pretty_type_name, format_ctor_signature_list=ctx.format_ctor_signature_list, instantiate_sig=ctx.instantiate_sig, enforce_struct_requires=ctx.enforce_struct_requires, ensure_field_visible=ctx.ensure_field_visible, visible_modules_for_free_call=ctx.visible_modules_for_free_call, module_ids_by_name=ctx.module_ids_by_name, visibility_provenance=ctx.visibility_provenance, infer=ctx.infer, format_infer_failure=ctx.format_infer_failure, lambda_can_throw=ctx.lambda_can_throw, allow_unsafe=ctx.allow_unsafe, unsafe_context=ctx.unsafe_context, allow_unsafe_without_block=ctx.allow_unsafe_without_block, allow_rawbuffer=ctx.allow_rawbuffer)
	base.update(overrides)
	return ResolverContext(**base)


def _make_method_ctx(ctx: CallResolverContext, *, diagnostics: list, traits_in_scope: Callable[[], list[TraitKey]], trait_key: TraitKey | None) -> MethodResolverContext:
	preseed_type_params = _require_preseed_type_params(ctx)
	return MethodResolverContext(type_table=ctx.type_table, diagnostics=diagnostics, current_module_name=ctx.current_module_name, current_module=ctx.current_module, default_package=ctx.default_package, module_packages=ctx.module_packages, type_param_map=ctx.type_param_map, preseed_type_params=preseed_type_params, type_param_names=ctx.type_param_names, current_fn_id=ctx.current_fn_id, int_ty=ctx.int_ty, uint_ty=ctx.uint_ty, byte_ty=ctx.byte_ty, bool_ty=ctx.bool_ty, float_ty=ctx.float_ty, string_ty=ctx.string_ty, void_ty=ctx.void_ty, error_ty=ctx.error_ty, dv_ty=ctx.dv_ty, unknown_ty=ctx.unknown_ty, signatures_by_id=ctx.signatures_by_id, callable_registry=ctx.callable_registry, trait_index=ctx.trait_index, trait_impl_index=ctx.trait_impl_index, impl_index=ctx.impl_index, visible_modules=ctx.visible_modules, visible_trait_world=ctx.visible_trait_world, global_trait_world=ctx.global_trait_world, trait_scope_by_module=ctx.trait_scope_by_module, require_env_local=ctx.require_env_local, fn_require_assumed=ctx.fn_require_assumed, traits_in_scope=traits_in_scope, trait_key_for_id=ctx.trait_key_for_id, tc_diag=ctx.tc_diag, type_expr=ctx.type_expr, optional_variant_type=ctx.optional_variant_type, unwrap_ref_type=ctx.unwrap_ref_type, struct_base_and_args=ctx.struct_base_and_args, receiver_place=ctx.receiver_place, receiver_can_mut_borrow=ctx.receiver_can_mut_borrow, receiver_compat=ctx.receiver_compat, receiver_preference=ctx.receiver_preference, args_match_params=ctx.args_match_params, coerce_args_for_params=ctx.coerce_args_for_params, infer_receiver_arg_type=ctx.infer_receiver_arg_type, instantiate_sig_with_subst=ctx.instantiate_sig_with_subst, apply_autoborrow_args=ctx.apply_autoborrow_args, label_typeid=ctx.label_typeid, trait_label=ctx.trait_label, require_for_fn=ctx.require_for_fn, extract_conjunctive_facts=ctx.extract_conjunctive_facts, subject_name=ctx.subject_name, normalize_type_key=ctx.normalize_type_key, collect_trait_subjects=ctx.collect_trait_subjects, require_failure=ctx.require_failure, format_failure_message=ctx.format_failure_message, failure_code=ctx.failure_code, pick_best_failure=ctx.pick_best_failure, requirement_notes=ctx.requirement_notes, param_scope_map=ctx.param_scope_map, candidate_key_for_decl=ctx.candidate_key_for_decl, visibility_note=ctx.visibility_note, intrinsic_method_fn_id=ctx.intrinsic_method_fn_id, instantiate_sig=ctx.instantiate_sig, self_mode_from_sig=ctx.self_mode_from_sig, match_impl_type_args=ctx.match_impl_type_args, format_infer_failure=ctx.format_infer_failure, visibility_provenance=ctx.visibility_provenance, module_ids_by_name=ctx.module_ids_by_name, record_instantiation=ctx.record_instantiation)


def make_call_ctx(**kwargs) -> CallResolverContext:
	ctx = CallResolverContext(**kwargs)
	_require_preseed_type_params(ctx)
	return ctx


def make_resolver_ctx(ctx: CallResolverContext, **overrides) -> ResolverContext:
	return _make_resolver_ctx(ctx, **overrides)


def make_method_ctx(ctx: CallResolverContext, *, diagnostics: list, traits_in_scope: Callable[[], list[TraitKey]], trait_key: TraitKey | None) -> MethodResolverContext:
	return _make_method_ctx(ctx, diagnostics=diagnostics, traits_in_scope=traits_in_scope, trait_key=trait_key)


def resolve_qualified_member_call(
	ctx: ResolverContext,
	qm: object,
	*,
	arg_exprs: list[object],
	arg_types: list[TypeId],
	kw_pairs: list[object],
	expected_type: TypeId | None,
	type_arg_ids: list[TypeId] | None,
	allow_infer: bool,
	call_type_args_span: Span | None,
) -> VariantCtorResolveResult | StructCtorResolveResult | None:
	base_te = getattr(qm, "base_type_expr", None)
	if base_te is None:
		return None
	base_kind = None
	base_name = getattr(base_te, "name", None)
	base_module = getattr(base_te, "module_id", None) or ctx.current_module_name
	if isinstance(base_name, str):
		if ctx.type_table.get_nominal(kind=TypeKind.VARIANT, module_id=base_module, name=base_name) is not None or ctx.type_table.get_variant_base(module_id=base_module, name=base_name) is not None or ctx.type_table.get_variant_base(module_id="lang.core", name=base_name) is not None:
			base_kind = TypeKind.VARIANT
		elif ctx.type_table.get_nominal(kind=TypeKind.STRUCT, module_id=base_module, name=base_name) is not None or ctx.type_table.get_struct_base(module_id=base_module, name=base_name) is not None or ctx.type_table.get_struct_base(module_id="lang.core", name=base_name) is not None:
			base_kind = TypeKind.STRUCT
	if base_kind is None:
		try:
			base_tid = resolve_opaque_type(base_te, ctx.type_table, module_id=base_module, type_params=ctx.type_param_map, allow_generic_base=True)
		except Exception:
			base_tid = None
		if base_tid is not None:
			base_def = ctx.type_table.get(base_tid)
			if base_def.kind is TypeKind.VARIANT:
				base_kind = TypeKind.VARIANT
			elif base_def.kind is TypeKind.STRUCT:
				base_kind = TypeKind.STRUCT
	if base_kind is TypeKind.VARIANT:
		return resolve_variant_ctor(
			ctx,
			qm,
			arg_exprs=arg_exprs,
			arg_types=arg_types,
			kw_pairs=kw_pairs,
			expected_type=expected_type,
			type_arg_ids=type_arg_ids,
			allow_infer=allow_infer,
			call_type_args_span=call_type_args_span,
		)
	if base_kind is TypeKind.STRUCT:
		ctx.diagnostics.append(ctx.tc_diag(message="E-QMEM-NONVARIANT: qualified member base is not a variant type", severity="error", span=getattr(qm, "loc", Span())))
		return None
	return None


def resolve_variant_ctor(
	ctx: ResolverContext,
	qm: object,
	*,
	arg_exprs: list[object],
	arg_types: list[TypeId],
	kw_pairs: list[object],
	expected_type: TypeId | None,
	type_arg_ids: list[TypeId] | None,
	allow_infer: bool,
	call_type_args_span: Span | None,
) -> VariantCtorResolveResult | None:
	base_te = getattr(qm, "base_type_expr", None)
	if base_te is None:
		ctx.diagnostics.append(
			ctx.tc_diag(
				message="E-QMEM-NONVARIANT: qualified member base is not a variant type",
				severity="error",
				span=getattr(qm, "loc", Span()),
			)
		)
		return None
	base_tid = ctx.type_table.get_nominal(
		kind=TypeKind.VARIANT,
		module_id=getattr(base_te, "module_id", None) or ctx.current_module_name,
		name=getattr(base_te, "name", ""),
	)
	if base_tid is None:
		name = getattr(base_te, "name", None)
		if isinstance(name, str):
			base_tid = (
				ctx.type_table.get_variant_base(module_id=ctx.current_module_name, name=name)
				or ctx.type_table.get_variant_base(module_id="lang.core", name=name)
			)
	if base_tid is None:
		ctx.diagnostics.append(
			ctx.tc_diag(
				message="E-QMEM-NONVARIANT: qualified member base is not a variant type",
				severity="error",
				span=getattr(qm, "loc", Span()),
			)
		)
		return None
	schema = ctx.type_table.get_variant_schema(base_tid)
	if schema is None:
		ctx.diagnostics.append(
			ctx.tc_diag(
				message="internal: missing variant schema for qualified member base (compiler bug)",
				severity="error",
				span=getattr(qm, "loc", Span()),
			)
		)
		return None
	arm_schema = next((a for a in schema.arms if a.name == qm.member), None)
	if arm_schema is None:
		ctors = ctx.format_ctor_signature_list(schema=schema, instance=None, current_module=ctx.current_module_name)
		ctx.diagnostics.append(
			ctx.tc_diag(
				message=(
					f"E-QMEM-NO-CTOR: constructor '{qm.member}' not found in variant "
					f"'{ctx.pretty_type_name(base_tid, current_module=ctx.current_module_name)}'. "
					f"Available constructors: {', '.join(ctors)}"
				),
				severity="error",
				span=getattr(qm, "loc", Span()),
			)
		)
		return None
	type_params: list[TypeParam] = []
	typevar_ids: list[TypeId] = []
	if schema.type_params:
		owner = FunctionId(module="lang.__internal", name=f"__variant_{schema.module_id}::{schema.name}", ordinal=0)
		for idx, tp_name in enumerate(schema.type_params):
			param_id = TypeParamId(owner=owner, index=idx)
			type_params.append(TypeParam(id=param_id, name=tp_name, span=None))
			typevar_ids.append(ctx.type_table.ensure_typevar(param_id, name=tp_name))
		type_cache: dict[tuple[TypeId, tuple[TypeId, ...]], TypeId] = {}

	def _lower_generic_expr(expr: GenericTypeExpr) -> TypeId:
		if expr.param_index is not None:
			idx = int(expr.param_index)
			if 0 <= idx < len(typevar_ids):
				return typevar_ids[idx]
			return ctx.unknown_ty
		name = expr.name
		if name in FIXED_WIDTH_TYPE_NAMES:
			if ctx.fixed_width_allowed(expr.module_id or schema.module_id or ctx.current_module_name):
				return ctx.type_table.ensure_named(name, module_id=expr.module_id or schema.module_id)
			ctx.diagnostics.append(
				ctx.tc_diag(
					message=(
						f"fixed-width type '{name}' is reserved in v1; "
						"use Int/Uint/Float or Byte"
					),
					code="E_FIXED_WIDTH_RESERVED",
					severity="error",
					span=Span(),
				)
			)
			return ctx.unknown_ty
		if name == "Int":
			return ctx.int_ty
		if name == "Uint":
			return ctx.uint_ty
		if name in ("Uint64", "u64"):
			return ctx.uint64_ty
		if name == "Byte":
			return ctx.byte_ty
		if name == "Bool":
			return ctx.bool_ty
		if name == "Float":
			return ctx.float_ty
		if name == "String":
			return ctx.string_ty
		if name == "Void":
			return ctx.void_ty
		if name == "Error":
			return ctx.error_ty
		if name == "DiagnosticValue":
			return ctx.dv_ty
		if name == "Unknown":
			return ctx.unknown_ty
		if name in {"&", "&mut"} and expr.args:
			inner = _lower_generic_expr(expr.args[0])
			return ctx.type_table.ensure_ref_mut(inner) if name == "&mut" else ctx.type_table.ensure_ref(inner)
		if name == "Array" and expr.args:
			elem = _lower_generic_expr(expr.args[0])
			span = Span.from_loc(getattr(expr.args[0], "loc", None)) if expr.args else Span()
			if ctx.reject_zst_array(elem, span=span):
				return ctx.unknown_ty
			return ctx.type_table.new_array(elem)
		origin_mod = expr.module_id or schema.module_id
		base_id = (
			ctx.type_table.get_nominal(kind=TypeKind.STRUCT, module_id=origin_mod, name=name)
			or ctx.type_table.get_nominal(kind=TypeKind.VARIANT, module_id=origin_mod, name=name)
			or ctx.type_table.ensure_named(name, module_id=origin_mod)
		)
		if expr.args:
			if base_id in ctx.type_table.struct_bases:
				base_schema = ctx.type_table.struct_bases.get(base_id)
				if base_schema is not None and not base_schema.type_params:
					ctx.diagnostics.append(
						ctx.tc_diag(
							message=f"type '{name}' is not generic",
							code="E-TYPE-NOT-GENERIC",
							severity="error",
							span=Span.from_loc(getattr(expr, "loc", None)),
						)
					)
					return ctx.unknown_ty
			elif base_id in ctx.type_table.variant_schemas:
				base_schema = ctx.type_table.variant_schemas.get(base_id)
				if base_schema is not None and not base_schema.type_params:
					ctx.diagnostics.append(
						ctx.tc_diag(
							message=f"type '{name}' is not generic",
							code="E-TYPE-NOT-GENERIC",
							severity="error",
							span=Span.from_loc(getattr(expr, "loc", None)),
						)
					)
					return ctx.unknown_ty
			else:
				ctx.diagnostics.append(
					ctx.tc_diag(
						message=f"unknown generic type '{name}'",
						code="E-TYPE-UNKNOWN",
						severity="error",
						span=Span.from_loc(getattr(expr, "loc", None)),
					)
				)
				return ctx.unknown_ty
		if expr.args:
			arg_ids = [_lower_generic_expr(a) for a in expr.args]
			if base_id in ctx.type_table.variant_schemas:
				if any(ctx.type_table.get(a).kind is TypeKind.TYPEVAR for a in arg_ids):
					key = (base_id, tuple(arg_ids))
					if key not in type_cache:
						td = ctx.type_table.get(base_id)
						type_cache[key] = ctx.type_table._add(
							TypeKind.VARIANT,
							td.name,
							list(arg_ids),
							register_named=False,
							module_id=td.module_id,
						)
					return type_cache[key]
				return ctx.type_table.ensure_instantiated(base_id, arg_ids)
		return base_id

	param_type_ids: list[TypeId] = []
	for f in arm_schema.fields:
		param_type_ids.append(_lower_generic_expr(f.type_expr))
	ret_type_id = base_tid
	if schema.type_params:
		ret_type_id = _lower_generic_expr(
			GenericTypeExpr.named(
				schema.name,
				args=[GenericTypeExpr.param(i) for i in range(len(schema.type_params))],
				module_id=schema.module_id,
			)
		)
	if type_arg_ids is None and hasattr(base_te, "args") and getattr(base_te, "args"):
		try:
			type_arg_ids = [resolve_opaque_type(arg, ctx.type_table, module_id=ctx.current_module_name, type_params=ctx.type_param_map, allow_generic_base=True) for arg in getattr(base_te, "args", [])]
		except Exception:
			type_arg_ids = None
	if schema.type_params and expected_type is None and not type_arg_ids and not arg_exprs:
		hint = (
			"Hint: qualify the constructor (e.g., `Optional<T>::None()` or `Optional::None<type T>()`)."
		)
		ctx.diagnostics.append(
			ctx.tc_diag(
				message=f"E-QMEM-CANNOT-INFER: constructor '{qm.member}' needs an expected type to infer type parameters (underconstrained). {hint}",
				severity="error",
				span=getattr(qm, "loc", Span()),
				notes=[hint, "underconstrained"],
			)
		)
		return None
	ctor_sig = FnSignature(
		name=qm.member,
		param_type_ids=param_type_ids,
		return_type_id=ret_type_id,
		type_params=type_params,
		module=ctx.current_module_name,
	)
	if kw_pairs and arg_exprs:
		ctx.diagnostics.append(
			ctx.tc_diag(
				message="E-QMEM-MIXED-ARGS: constructor calls cannot mix positional and named arguments in MVP",
				severity="error",
				span=getattr(qm, "loc", Span()),
			)
		)
		return None
	inst_res = ctx.instantiate_sig(
		sig=ctor_sig,
		arg_types=arg_types,
		expected_type=expected_type,
		explicit_type_args=type_arg_ids,
		allow_infer=allow_infer,
		diag_span=call_type_args_span or getattr(qm, "loc", Span()),
		call_kind="ctor",
		call_name=qm.member,
	)
	if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT:
		ctx.diagnostics.append(
			ctx.tc_diag(
				message=(
					f"E-QMEM-TYPEARGS-ARITY: expected {len(schema.type_params)} type arguments, got {len(type_arg_ids or [])}"
				),
				severity="error",
				span=call_type_args_span or getattr(qm, "loc", Span()),
			)
		)
		return None
	if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS:
		ctx.diagnostics.append(
			ctx.tc_diag(
				message="constructor does not accept type arguments; use the non-generic form instead",
				severity="error",
				span=call_type_args_span or getattr(qm, "loc", Span()),
			)
		)
		return None
	if inst_res.error:
		return None
	if inst_res.inst_params is None or inst_res.inst_return is None:
		return None
	inst_return = inst_res.inst_return
	ctor_arg_field_indices: list[int] = []
	if kw_pairs:
		field_indices = {f.name: idx for idx, f in enumerate(arm_schema.fields)}
		ordered_args: list[object] = []
		for kw in kw_pairs:
			field_idx = field_indices.get(kw.name)
			if field_idx is None:
				ctx.diagnostics.append(
					ctx.tc_diag(
						message=f"E-QMEM-NO-FIELD: constructor field '{kw.name}' not found on '{qm.member}'",
						severity="error",
						span=getattr(kw, "loc", Span()),
					)
				)
				return None
			if field_idx in ctor_arg_field_indices:
				ctx.diagnostics.append(
					ctx.tc_diag(
						message=f"E-QMEM-DUP-FIELD: duplicate constructor field '{kw.name}' on '{qm.member}'",
						severity="error",
						span=getattr(kw, "loc", Span()),
					)
				)
				return None
			ctor_arg_field_indices.append(field_idx)
			ordered_args.append(kw.value)
		ctor_args = ordered_args
	else:
		ctor_arg_field_indices = list(range(len(arg_exprs)))
		ctor_args = arg_exprs
	return VariantCtorResolveResult(inst_return, list(inst_res.inst_params), ctor_arg_field_indices, ctor_args)


def resolve_struct_ctor(
	ctx: ResolverContext,
	*,
	struct_id: TypeId,
	struct_name: str,
	arg_exprs: list[object],
	arg_types: list[TypeId],
	kw_pairs: list[object],
	expected_type: TypeId | None,
	type_arg_ids: list[TypeId] | None,
	allow_infer: bool,
	call_type_args_span: Span | None,
	span: Span,
) -> StructCtorResolveResult | None:
	struct_def = ctx.type_table.get(struct_id)
	if struct_def.kind is not TypeKind.STRUCT:
		ctx.diagnostics.append(
			ctx.tc_diag(
				message=f"internal: struct schema '{struct_name}' is not a STRUCT TypeId",
				severity="error",
				span=span,
			)
		)
		return None
	struct_inst = ctx.type_table.get_struct_instance(struct_id)
	base_id = struct_inst.base_id if struct_inst is not None else struct_id
	schema = ctx.type_table.get_struct_schema(base_id)
	if schema is None:
		ctx.diagnostics.append(ctx.tc_diag(message=f"internal: missing schema for struct '{struct_name}'", severity="error", span=span))
		return None
	if expected_type is not None:
		exp_inst = ctx.type_table.get_struct_instance(expected_type)
		if exp_inst is not None and exp_inst.base_id == base_id:
			struct_id = expected_type
			struct_inst = exp_inst
	if struct_inst is not None:
		field_names = list(struct_inst.field_names)
		field_types = list(struct_inst.field_types)
	else:
		field_names = [f.name for f in schema.fields]
		field_types = list(struct_def.param_types)
	if struct_inst is None and schema.type_params:
		if (not type_arg_ids) and expected_type is not None:
			exp_inst = ctx.type_table.get_struct_instance(expected_type)
			if exp_inst is not None and exp_inst.base_id == base_id:
				type_arg_ids = list(exp_inst.type_args)
		param_ids = ctx.type_table.get_struct_type_param_ids(base_id) or []
		type_params: list[TypeParam] = []
		typevar_ids: list[TypeId] = []
		for idx, name in enumerate(schema.type_params):
			if idx < len(param_ids):
				param_id = param_ids[idx]
			else:
				param_id = TypeParamId(owner=FunctionId(module="lang.__internal", name=f"__struct_{schema.module_id}::{schema.name}", ordinal=0), index=idx)
			type_params.append(TypeParam(id=param_id, name=name, span=None))
			typevar_ids.append(ctx.type_table.ensure_typevar(param_id, name=name))
		local_type_param_map = {name: typevar_ids[idx] for idx, name in enumerate(schema.type_params) if idx < len(typevar_ids)}
		def _lower_generic_expr(expr: object) -> TypeId:
			if hasattr(expr, "param_index") and getattr(expr, "param_index", None) is not None:
				idx = int(getattr(expr, "param_index"))
				if 0 <= idx < len(typevar_ids):
					return typevar_ids[idx]
				return ctx.unknown_ty
			return resolve_opaque_type(expr, ctx.type_table, module_id=schema.module_id or ctx.current_module_name, type_params=local_type_param_map)
		field_types = [_lower_generic_expr(f.type_expr) for f in schema.fields]
		ret_type_id = ctx.type_table.ensure_struct_template(base_id, typevar_ids)
		ctor_sig = FnSignature(name=struct_name, param_type_ids=list(field_types), return_type_id=ret_type_id, type_params=list(type_params), param_names=list(field_names), module=schema.module_id or ctx.current_module_name)
		inst_res = ctx.instantiate_sig(sig=ctor_sig, arg_types=arg_types, expected_type=expected_type, explicit_type_args=type_arg_ids, allow_infer=allow_infer, diag_span=call_type_args_span or span, call_kind="ctor", call_name=struct_name)
		if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT:
			ctx.diagnostics.append(ctx.tc_diag(message=(f"type argument count mismatch for struct '{struct_name}': expected {len(schema.type_params)}, got {len(type_arg_ids or [])}"), severity="error", span=call_type_args_span or span))
			return None
		if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS:
			ctx.diagnostics.append(ctx.tc_diag(message=f"struct '{struct_name}' does not accept type arguments", severity="error", span=call_type_args_span or span))
			return None
		if inst_res.error:
			msg, notes = ctx.format_infer_failure(inst_res.context, inst_res)
			field_notes = [f"field '{n}'" for n in field_names]
			ctx.diagnostics.append(ctx.tc_diag(message=f"cannot infer type arguments for struct '{struct_name}'", severity="error", span=call_type_args_span or span, notes=[msg] + list(notes) + field_notes))
			return None
		if inst_res.inst_params is None or inst_res.inst_return is None:
			return None
		field_types = list(inst_res.inst_params)
		struct_id = inst_res.inst_return
	ctx.enforce_struct_requires(struct_id, span)
	for fname in field_names:
		ctx.ensure_field_visible(struct_id, fname, span)
	if len(field_names) != len(field_types):
		ctx.diagnostics.append(ctx.tc_diag(message=f"internal: struct '{struct_name}' schema/type mismatch", severity="error", span=span))
		return StructCtorResolveResult(struct_id, field_types, [], list(arg_exprs))
	if arg_exprs and kw_pairs:
		ctx.diagnostics.append(ctx.tc_diag(message=f"cannot mix positional and named arguments for struct '{struct_name}'", severity="error", span=span))
		return None
	ctor_arg_field_indices: list[int] = []
	ctor_args: list[object] = []
	if arg_exprs:
		if len(arg_exprs) != len(field_types):
			ctx.diagnostics.append(ctx.tc_diag(message=f"struct '{struct_name}' constructor expects {len(field_types)} args, got {len(arg_exprs)}", severity="error", span=span))
			return StructCtorResolveResult(struct_id, field_types, [], list(arg_exprs))
		ctor_arg_field_indices = list(range(len(arg_exprs)))
		ctor_args = list(arg_exprs)
		for idx, (have, want) in enumerate(zip(arg_types, field_types)):
			if have != want:
				ctx.diagnostics.append(ctx.tc_diag(message=(f"struct '{struct_name}' field '{field_names[idx]}' type mismatch (have {ctx.type_table.get(have).name}, expected {ctx.type_table.get(want).name})"), severity="error", span=getattr(arg_exprs[idx], "loc", Span())))
				return None
	else:
		seen: set[str] = set()
		for kw in kw_pairs:
			if kw.name not in field_names:
				ctx.diagnostics.append(ctx.tc_diag(message=f"unknown field '{kw.name}' for struct '{struct_name}'", severity="error", span=getattr(kw, "loc", Span())))
				return None
			if kw.name in seen:
				ctx.diagnostics.append(ctx.tc_diag(message=f"duplicate field '{kw.name}' for struct '{struct_name}'", severity="error", span=getattr(kw, "loc", Span())))
				return None
			seen.add(kw.name)
			ctor_arg_field_indices.append(field_names.index(kw.name))
			ctor_args.append(kw.value)
		if len(kw_pairs) != len(field_names):
			missing = [name for name in field_names if name not in seen]
			ctx.diagnostics.append(ctx.tc_diag(message=f"missing field(s) for struct '{struct_name}': {', '.join(missing)}", severity="error", span=Span()))
			return None
		for idx, (have, field_idx) in enumerate(zip(arg_types, ctor_arg_field_indices)):
			want = field_types[field_idx]
			if have != want:
				ctx.diagnostics.append(ctx.tc_diag(message=(f"struct '{struct_name}' field '{field_names[field_idx]}' type mismatch (have {ctx.type_table.get(have).name}, expected {ctx.type_table.get(want).name})"), severity="error", span=getattr(ctor_args[idx], "loc", Span())))
				return None
	return StructCtorResolveResult(struct_id, field_types, ctor_arg_field_indices, ctor_args)


def resolve_unqualified_variant_ctor(ctx: ResolverContext, *, ctor_name: str, expected_type: TypeId, arg_exprs: list[object], kw_pairs: list[object]) -> VariantCtorResolveResult | None:
	try:
		exp_def = ctx.type_table.get(expected_type)
	except Exception:
		exp_def = None
	if exp_def is None or exp_def.kind is not TypeKind.VARIANT:
		return None
	inst = ctx.type_table.get_variant_instance(expected_type)
	if inst is None or ctor_name not in inst.arms_by_name:
		return None
	arm_def = inst.arms_by_name[ctor_name]
	if kw_pairs and arg_exprs:
		ctx.diagnostics.append(ctx.tc_diag(message=f"constructor '{arm_def.name}' does not allow mixing positional and named arguments", severity="error", span=getattr(kw_pairs[0], "loc", Span())))
		return None
	field_names = list(getattr(arm_def, "field_names", []) or [])
	field_types = list(arm_def.field_types)
	if len(field_names) != len(field_types):
		ctx.diagnostics.append(ctx.tc_diag(message="internal: variant ctor schema/type mismatch (compiler bug)", severity="error", span=getattr(arg_exprs[0], "loc", Span()) if arg_exprs else Span()))
		return None
	ctor_arg_field_indices: list[int] = []
	ctor_args: list[object] = []
	if kw_pairs:
		for kw in kw_pairs:
			if kw.name not in field_names:
				ctx.diagnostics.append(ctx.tc_diag(message=f"unknown field '{kw.name}' for constructor '{arm_def.name}'", severity="error", span=getattr(kw, "loc", Span())))
				continue
			field_idx = field_names.index(kw.name)
			if field_idx in ctor_arg_field_indices:
				ctx.diagnostics.append(ctx.tc_diag(message=f"duplicate field '{kw.name}' for constructor '{arm_def.name}'", severity="error", span=getattr(kw, "loc", Span())))
				continue
			ctor_arg_field_indices.append(field_idx)
			ctor_args.append(kw.value)
		if len(ctor_arg_field_indices) != len(field_names):
			for idx, fname in enumerate(field_names):
				if idx not in ctor_arg_field_indices:
					ctx.diagnostics.append(ctx.tc_diag(message=f"missing field '{fname}' for constructor '{arm_def.name}'", severity="error", span=getattr(kw_pairs[0], "loc", Span()) if kw_pairs else Span()))
			return None
	else:
		if len(arg_exprs) != len(field_types):
			ctx.diagnostics.append(ctx.tc_diag(message=f"constructor '{arm_def.name}' expects {len(field_types)} arguments, got {len(arg_exprs)}", severity="error", span=getattr(arg_exprs[0], "loc", Span()) if arg_exprs else Span()))
			return None
		ctor_args = list(arg_exprs)
		ctor_arg_field_indices = list(range(len(field_types)))
	return VariantCtorResolveResult(expected_type, field_types, ctor_arg_field_indices, ctor_args)


def resolve_method_call(ctx: MethodResolverContext, expr: object, *, expected_type: TypeId | None) -> MethodCallResult:
	diagnostics = ctx.diagnostics
	_tc_diag = ctx.tc_diag
	type_expr = ctx.type_expr
	_optional_variant_type = ctx.optional_variant_type
	_unwrap_ref_type = ctx.unwrap_ref_type
	_struct_base_and_args = ctx.struct_base_and_args
	_receiver_place = ctx.receiver_place
	_receiver_can_mut_borrow = ctx.receiver_can_mut_borrow
	_receiver_compat = ctx.receiver_compat
	_receiver_preference = ctx.receiver_preference
	_label_typeid = ctx.label_typeid
	_trait_label = ctx.trait_label
	_require_for_fn = ctx.require_for_fn
	_extract_conjunctive_facts = ctx.extract_conjunctive_facts
	_subject_name = ctx.subject_name
	_normalize_type_key = ctx.normalize_type_key
	_collect_trait_subjects = ctx.collect_trait_subjects
	_require_failure = ctx.require_failure
	_format_failure_message = ctx.format_failure_message
	_failure_code = ctx.failure_code
	_pick_best_failure = ctx.pick_best_failure
	_param_scope_map = ctx.param_scope_map
	_candidate_key_for_decl = ctx.candidate_key_for_decl
	_visibility_note = ctx.visibility_note
	_intrinsic_method_fn_id = ctx.intrinsic_method_fn_id
	_instantiate_sig = ctx.instantiate_sig
	_self_mode_from_sig = ctx.self_mode_from_sig
	_match_impl_type_args = ctx.match_impl_type_args
	_format_infer_failure = ctx.format_infer_failure
	_infer_receiver_arg_type = ctx.infer_receiver_arg_type
	traits_in_scope = ctx.traits_in_scope
	call_type_args = list(getattr(expr, "type_args", None) or [])
	call_type_args_span = None
	if call_type_args:
		first_loc = getattr(call_type_args[0], "loc", None)
		if first_loc is not None:
			call_type_args_span = Span.from_loc(first_loc)
	type_arg_ids = [resolve_opaque_type(t, ctx.type_table, module_id=ctx.current_module_name, type_params=ctx.type_param_map) for t in call_type_args] if call_type_args else None

	def _call_info(param_types: list[TypeId], return_type: TypeId, can_throw: bool, target: FunctionId) -> CallInfo:
		return CallInfo(target=CallTarget.direct(target), sig=CallSig(param_types=tuple(param_types), user_ret_type=return_type, can_throw=bool(can_throw)))

	def _call_info_target(param_types: list[TypeId], return_type: TypeId, can_throw: bool, target: CallTarget) -> CallInfo:
		return CallInfo(target=target, sig=CallSig(param_types=tuple(param_types), user_ret_type=return_type, can_throw=bool(can_throw)))

	def _pick_most_specific_items(items: list[tuple], key_fn, require_info: dict[object, tuple[parser_ast.TraitExpr, dict[object, object], str, dict[TypeParamId, tuple[str, int]]]]) -> list[tuple]:
		if ctx.require_env_local is None:
			return items
		require_env_local = ctx.require_env_local
		formulas: dict[object, object] = {}
		for item in items:
			key = key_fn(item)
			info = require_info.get(key)
			if info is None:
				continue
			req_expr, subst, def_mod, scope_map = info
			formula = require_env_local.normalized(req_expr, subst=subst, default_module=def_mod, param_scope_map=scope_map)
			formulas[key] = formula
		winners: list[tuple] = []
		for item in items:
			key = key_fn(item)
			base = formulas.get(key)
			if base is None:
				winners.append(item)
				continue
			is_dominated = False
			for other in items:
				other_key = key_fn(other)
				if other_key == key:
					continue
				other_formula = formulas.get(other_key)
				if other_formula is None:
					continue
				if require_env_local.implies(other_formula, base) and not require_env_local.implies(base, other_formula):
					is_dominated = True
					break
			if not is_dominated:
				winners.append(item)
		return winners

	# Built-in DiagnosticValue helpers are reserved method names and take precedence.
	if getattr(expr, "method_name", None) in ("as_int", "as_bool", "as_string"):
		recv_ty = type_expr(expr.receiver, used_as_value=False)
		recv_def = ctx.type_table.get(recv_ty)
		if recv_def.kind is not TypeKind.DIAGNOSTICVALUE:
			diagnostics.append(_tc_diag(message=f"{expr.method_name} is only valid on DiagnosticValue", severity="error", span=getattr(expr, "loc", Span())))
			info = _call_info([recv_ty], ctx.unknown_ty, False, _intrinsic_method_fn_id(expr.method_name))
			return MethodCallResult(ctx.unknown_ty, info)
		if expr.method_name == "as_int":
			opt_int = _optional_variant_type(ctx.int_ty)
			info = _call_info([recv_ty], opt_int, False, _intrinsic_method_fn_id(expr.method_name))
			return MethodCallResult(opt_int, info)
		if expr.method_name == "as_bool":
			opt_bool = _optional_variant_type(ctx.bool_ty)
			info = _call_info([recv_ty], opt_bool, False, _intrinsic_method_fn_id(expr.method_name))
			return MethodCallResult(opt_bool, info)
		if expr.method_name == "as_string":
			opt_string = _optional_variant_type(ctx.string_ty)
			info = _call_info([recv_ty], opt_string, False, _intrinsic_method_fn_id(expr.method_name))
			return MethodCallResult(opt_string, info)
		info = _call_info([recv_ty], ctx.unknown_ty, False, _intrinsic_method_fn_id(expr.method_name))
		return MethodCallResult(ctx.unknown_ty, info)

	if getattr(expr, "kwargs", None):
		first = (getattr(expr, "kwargs", []) or [None])[0]
		diagnostics.append(_tc_diag(message="keyword arguments are not supported for method calls in MVP", severity="error", span=getattr(first, "loc", getattr(expr, "loc", Span()))))
		return MethodCallResult(ctx.unknown_ty, None)

	recv_ty = getattr(expr, "receiver_type_id", None)
	if recv_ty is None:
		recv_ty = type_expr(expr.receiver, used_as_value=False)
	arg_types = getattr(expr, "arg_type_ids", None)
	cur_sig = ctx.signatures_by_id.get(ctx.current_fn_id) if ctx.signatures_by_id is not None else None
	instantiation_mode = bool(cur_sig and getattr(cur_sig, "is_instantiation", False))
	is_generic_body = bool(cur_sig and ((getattr(cur_sig, "type_params", None) or []) or (getattr(cur_sig, "impl_type_params", None) or [])))
	if arg_types is None:
		arg_types = [type_expr(a, used_as_value=False) for a in expr.args]

	if expr.method_name == "dup" and not expr.args:
		recv_nominal = _unwrap_ref_type(recv_ty)
		recv_def = ctx.type_table.get(recv_nominal)
		if recv_def.kind is TypeKind.ARRAY and recv_def.param_types:
			elem_ty = recv_def.param_types[0]
			if not ctx.type_table.is_copy(elem_ty):
				diagnostics.append(_tc_diag(message="Array<T>.dup() requires element type to be Copy in MVP", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None)
			info = _call_info([recv_ty], recv_nominal, False, _intrinsic_method_fn_id(expr.method_name))
			return MethodCallResult(recv_nominal, info)

	if expr.method_name in ("push", "pop", "insert", "remove", "swap_remove", "swap", "clear", "reserve", "shrink_to_fit", "range", "range_mut", "get", "set"):
		recv_nominal = _unwrap_ref_type(recv_ty)
		recv_def = ctx.type_table.get(recv_nominal)
		if recv_def.kind is TypeKind.ARRAY and recv_def.param_types:
			elem_ty = recv_def.param_types[0]
			recv_place = _receiver_place(expr.receiver)
			needs_mut = expr.method_name in ("push", "insert", "remove", "swap_remove", "swap", "clear", "reserve", "shrink_to_fit", "range_mut", "set", "pop")
			if needs_mut and not _receiver_can_mut_borrow(expr.receiver, recv_place):
				diagnostics.append(_tc_diag(message=f"Array.{expr.method_name}() requires a mutable Array receiver", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None)
			if expr.method_name == "get" and recv_place is None:
				diagnostics.append(_tc_diag(message="Array.get() requires an lvalue Array receiver", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None)
			if expr.method_name in ("range", "range_mut") and recv_place is None:
				diagnostics.append(_tc_diag(message=f"Array.{expr.method_name}() requires an lvalue Array receiver", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None)
			expected_args = {"push": 1, "pop": 0, "insert": 2, "remove": 1, "swap_remove": 1, "swap": 2, "clear": 0, "reserve": 1, "shrink_to_fit": 0, "range": 0, "range_mut": 0, "get": 1, "set": 2}
			want = expected_args.get(expr.method_name)
			if want is not None and len(expr.args) != want:
				diagnostics.append(_tc_diag(message=f"Array.{expr.method_name}() expects {want} argument(s)", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None)
			if expr.method_name in ("push", "set"):
				arg_ty = arg_types[0] if arg_types else None
				if arg_ty is not None and arg_ty != elem_ty:
					diagnostics.append(_tc_diag(message="Array element type mismatch", severity="error", span=getattr(expr.args[0], "loc", getattr(expr, "loc", Span()))))
					return MethodCallResult(ctx.unknown_ty, None)
			if expr.method_name == "insert":
				if len(arg_types) == 2:
					idx_ty, val_ty = arg_types
					if idx_ty is not None:
						td_idx = ctx.type_table.get(idx_ty)
						if td_idx.kind is not TypeKind.TYPEVAR and idx_ty != ctx.int_ty:
							diagnostics.append(_tc_diag(message="array index must be an Int", severity="error", span=getattr(expr.args[0], "loc", getattr(expr, "loc", Span()))))
							return MethodCallResult(ctx.unknown_ty, None)
					if val_ty is not None and val_ty != elem_ty:
						diagnostics.append(_tc_diag(message="Array element type mismatch", severity="error", span=getattr(expr.args[1], "loc", getattr(expr, "loc", Span()))))
						return MethodCallResult(ctx.unknown_ty, None)
			if expr.method_name in ("remove", "swap_remove", "get"):
				if arg_types:
					idx_ty = arg_types[0]
					if idx_ty is not None:
						td_idx = ctx.type_table.get(idx_ty)
						if td_idx.kind is not TypeKind.TYPEVAR and idx_ty != ctx.int_ty:
							diagnostics.append(_tc_diag(message="array index must be an Int", severity="error", span=getattr(expr.args[0], "loc", getattr(expr, "loc", Span()))))
							return MethodCallResult(ctx.unknown_ty, None)
			if expr.method_name == "reserve" and arg_types:
				add_ty = arg_types[0]
				if add_ty is not None and add_ty != ctx.int_ty:
					diagnostics.append(_tc_diag(message="reserve expects an Int size", severity="error", span=getattr(expr.args[0], "loc", getattr(expr, "loc", Span()))))
					return MethodCallResult(ctx.unknown_ty, None)
			if expr.method_name in ("range", "range_mut"):
				range_name = "ArrayRangeMut" if expr.method_name == "range_mut" else "ArrayRange"
				range_base = ctx.type_table.get_nominal(kind=TypeKind.STRUCT, module_id="std.containers", name=range_name)
				if range_base is None:
					ret_ty = ctx.unknown_ty
				elif ctx.type_table.has_typevar(elem_ty):
					ret_ty = ctx.type_table.ensure_struct_template(range_base, [elem_ty])
				else:
					ret_ty = ctx.type_table.ensure_struct_instantiated(range_base, [elem_ty])
			elif expr.method_name == "get":
				ref_ty = ctx.type_table.ensure_ref(elem_ty)
				ret_ty = _optional_variant_type(ref_ty)
			elif expr.method_name == "pop":
				ret_ty = _optional_variant_type(elem_ty)
			elif expr.method_name in ("remove", "swap_remove"):
				ret_ty = elem_ty
			else:
				ret_ty = ctx.void_ty
			info = _call_info([recv_ty] + arg_types, ret_ty, False, _intrinsic_method_fn_id(expr.method_name))
			return MethodCallResult(ret_ty, info)

	# FnResult intrinsic methods.
	if expr.method_name in ("is_err", "unwrap", "unwrap_err") and not expr.args:
		recv_def = ctx.type_table.get(recv_ty)
		if recv_def.kind is TypeKind.FNRESULT and recv_def.param_types:
			ok_ty = recv_def.param_types[0] if len(recv_def.param_types) > 0 else ctx.unknown_ty
			err_ty = recv_def.param_types[1] if len(recv_def.param_types) > 1 else ctx.error_ty
			if expr.method_name == "is_err":
				ret_ty = ctx.bool_ty
			elif expr.method_name == "unwrap":
				ret_ty = ok_ty
			else:
				ret_ty = err_ty
			info = _call_info([recv_ty], ret_ty, False, _intrinsic_method_fn_id(expr.method_name))
			return MethodCallResult(ret_ty, info)

	if ctx.callable_registry:
		_require_for_fn = ctx.require_for_fn
		_require_failure = ctx.require_failure
		_format_failure_message = ctx.format_failure_message
		_failure_code = ctx.failure_code
		_pick_best_failure = ctx.pick_best_failure
		call_type_args = getattr(expr, "type_args", None) or []
		type_arg_ids: list[TypeId] | None = None
		call_type_args_span = None
		if call_type_args:
			first_loc = getattr(call_type_args[0], "loc", None)
			if first_loc is not None:
				call_type_args_span = Span.from_loc(first_loc)
		type_arg_ids = [resolve_opaque_type(t, ctx.type_table, module_id=ctx.current_module_name, type_params=ctx.type_param_map) for t in call_type_args]
		if ctx.type_param_names and ctx.type_param_map and not is_generic_body:
			_recv_def = ctx.type_table.get(recv_ty)
			if _recv_def.kind is TypeKind.TYPEVAR:
				_recv_name = ctx.type_param_names.get(_recv_def.type_param_id)
				if _recv_name is not None and _recv_name in ctx.type_param_map:
					recv_ty = ctx.type_param_map[_recv_name]
		if isinstance(recv_ty, TypeParamId):
			_tp_name = ctx.type_param_names.get(recv_ty) if ctx.type_param_names else None
			recv_ty = ctx.type_table.ensure_typevar(recv_ty, name=_tp_name)
		receiver_nominal = _unwrap_ref_type(recv_ty)
		receiver_base, receiver_args = _struct_base_and_args(receiver_nominal)
		recv_def = ctx.type_table.get(receiver_nominal)
		if receiver_args is None and recv_def.kind is TypeKind.ARRAY and recv_def.param_types:
			receiver_args = list(recv_def.param_types)
		recv_type_param_id = recv_def.type_param_id if recv_def.kind is TypeKind.TYPEVAR else None
		if recv_type_param_id is None and ctx.type_param_map and ctx.type_param_names:
			for _tp_id, _tp_name in ctx.type_param_names.items():
				if _tp_name in ctx.type_param_map and ctx.type_param_map[_tp_name] == receiver_nominal:
					recv_type_param_id = _tp_id
					break
		recv_type_key = None
		recv_tp_name = ctx.type_param_names.get(recv_type_param_id) if recv_type_param_id is not None and ctx.type_param_names else None
		if recv_tp_name is None and ctx.type_param_map:
			_recv_key = _normalize_type_key(type_key_from_typeid(ctx.type_table, receiver_nominal))
			for _name, _tid in ctx.type_param_map.items():
				if isinstance(_tid, TypeParamId):
					continue
				try:
					_mapped_key = _normalize_type_key(type_key_from_typeid(ctx.type_table, _tid))
				except KeyError:
					continue
				if _mapped_key == _recv_key:
					recv_tp_name = _name
					break
		if recv_tp_name is None and ctx.preseed_type_params:
			_recv_key = _normalize_type_key(type_key_from_typeid(ctx.type_table, receiver_nominal))
			for _name, _tid in ctx.preseed_type_params.items():
				if isinstance(_tid, TypeParamId):
					continue
				if _tid == receiver_nominal:
					recv_tp_name = _name
					break
				try:
					_recv_base, _recv_args = _struct_base_and_args(receiver_nominal)
					_map_base, _map_args = _struct_base_and_args(_tid)
				except Exception:
					_recv_base = None
					_map_base = None
				if _recv_base is not None and _map_base is not None and _recv_base == _map_base:
					recv_tp_name = _name
					break
				try:
					_mapped_key = _normalize_type_key(type_key_from_typeid(ctx.type_table, _tid))
				except KeyError:
					continue
				if _mapped_key == _recv_key:
					recv_tp_name = _name
					break
		if recv_tp_name is None and ctx.preseed_type_params:
			recv_def = ctx.type_table.get(receiver_nominal)
			for _name, _tid in ctx.preseed_type_params.items():
				if isinstance(_tid, TypeParamId):
					continue
				try:
					_def = ctx.type_table.get(_tid)
				except Exception:
					continue
				if _def.kind == recv_def.kind and _def.name == recv_def.name and getattr(_def, "module_id", None) == getattr(recv_def, "module_id", None):
					recv_tp_name = _name
					break
		receiver_is_type_param = recv_type_param_id is not None
		if receiver_is_type_param:
			recv_type_key = _normalize_type_key(type_key_from_typeid(ctx.type_table, receiver_nominal))
		receiver_place = _receiver_place(expr.receiver)
		receiver_is_lvalue = receiver_place is not None
		receiver_can_mut_borrow = _receiver_can_mut_borrow(expr.receiver, receiver_place)
		if receiver_is_type_param:
			if ctx.trait_index is None:
				diagnostics.append(_tc_diag(message=f"no matching method '{expr.method_name}' for receiver {_label_typeid(recv_ty)}", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None)
			req_expr = _require_for_fn(ctx.current_fn_id)
			recv_owner = getattr(recv_type_param_id, "owner", None)
			trait_type_args_by_key: dict[TraitKey, list[TypeId]] = {}
			if req_expr is not None:
				for atom in _extract_conjunctive_facts(req_expr):
					subj = atom.subject
					subj_name = _subject_name(subj)
					if subj_name is None and isinstance(subj, TypeParamId):
						subj_name = ctx.type_param_names.get(subj)
					if subj_name is None and isinstance(subj, TypeParamId) and recv_tp_name is not None and recv_tp_name in ctx.type_param_map and not ctx.type_param_names:
						subj_name = recv_tp_name
					if recv_type_param_id is not None and isinstance(subj, TypeParamId) and recv_owner is not None and subj.index == recv_type_param_id.index and getattr(subj.owner, "module", None) == getattr(recv_owner, "module", None) and getattr(subj.owner, "name", None) == getattr(recv_owner, "name", None) and getattr(subj.owner, "ordinal", None) == getattr(recv_owner, "ordinal", None):
						subj = recv_type_param_id
					if subj_name is not None and ctx.type_param_map and subj_name in ctx.type_param_map:
						subj = ctx.type_param_map[subj_name]
					if subj != recv_type_param_id and (subj_name is None or recv_tp_name is None or subj_name != recv_tp_name):
						continue
					trait_key_req = trait_key_from_expr(atom.trait, default_module=ctx.current_module_name, default_package=ctx.default_package, module_packages=ctx.module_packages)
					arg_exprs = list(getattr(atom.trait, "args", []) or [])
					if arg_exprs:
						arg_ids = [resolve_opaque_type(a, ctx.type_table, module_id=trait_key_req.module or ctx.current_module_name, type_params=ctx.type_param_map) for a in arg_exprs]
					else:
						arg_ids = []
					trait_type_args_by_key[trait_key_req] = arg_ids
					if recv_type_param_id is not None:
						ctx.fn_require_assumed.add((recv_type_param_id, trait_key_req))
					if recv_type_key is not None:
						ctx.fn_require_assumed.add((recv_type_key, trait_key_req))
			if ctx.require_env_local is not None and ctx.require_env_local.trait_requires and ctx.trait_index is not None:
				for _base_key, _base_args in list(trait_type_args_by_key.items()):
					_req = ctx.require_env_local.trait_requires.get(_base_key)
					if _req is None:
						continue
					_trait_def = ctx.trait_index.traits_by_id.get(_base_key)
					_param_names = list(getattr(_trait_def, "type_params", []) or []) if _trait_def is not None else []
					_local_map = {name: _base_args[idx] for idx, name in enumerate(_param_names) if idx < len(_base_args)}
					for _atom in _extract_conjunctive_facts(_req):
						_req_key = trait_key_from_expr(_atom.trait, default_module=_base_key.module or ctx.current_module_name, default_package=ctx.default_package, module_packages=ctx.module_packages)
						_arg_exprs = list(getattr(_atom.trait, "args", []) or [])
						if _arg_exprs:
							_arg_ids = [resolve_opaque_type(a, ctx.type_table, module_id=_req_key.module or ctx.current_module_name, type_params=_local_map) for a in _arg_exprs]
						else:
							_arg_ids = []
						if _req_key not in trait_type_args_by_key:
							trait_type_args_by_key[_req_key] = _arg_ids
							if recv_type_param_id is not None:
								ctx.fn_require_assumed.add((recv_type_param_id, _req_key))
							if recv_type_key is not None:
								ctx.fn_require_assumed.add((recv_type_key, _req_key))
			missing_require_trait: TraitKey | None = None
			saw_method_in_scope = False
			matching_traits: list[TraitKey] = []
			scope_traits = traits_in_scope()
			if instantiation_mode and not scope_traits and trait_type_args_by_key:
				scope_traits = list(trait_type_args_by_key.keys())
			for trait_key in scope_traits:
				if ctx.trait_index.is_missing(trait_key):
					raise ResolutionError(f"missing trait metadata for '{_trait_label(trait_key)}'", span=getattr(expr, "loc", Span()))
				if not ctx.trait_index.has_method(trait_key, expr.method_name):
					continue
				saw_method_in_scope = True
				has_require_trait = (recv_type_param_id, trait_key) in ctx.fn_require_assumed or (recv_type_key, trait_key) in ctx.fn_require_assumed
				if not has_require_trait and ctx.fn_require_assumed:
					for _subj, _key in ctx.fn_require_assumed:
						if getattr(_key, "name", None) == getattr(trait_key, "name", None) and getattr(_key, "module", None) == getattr(trait_key, "module", None):
							has_require_trait = True
							break
				if not has_require_trait and trait_type_args_by_key:
					for _key in trait_type_args_by_key.keys():
						if getattr(_key, "name", None) == getattr(trait_key, "name", None) and getattr(_key, "module", None) == getattr(trait_key, "module", None):
							has_require_trait = True
							break
				if not has_require_trait and req_expr is not None:
					for _atom in _extract_conjunctive_facts(req_expr):
						_key = trait_key_from_expr(_atom.trait, default_module=ctx.current_module_name, default_package=ctx.default_package, module_packages=ctx.module_packages)
						if getattr(_key, "name", None) == getattr(trait_key, "name", None) and getattr(_key, "module", None) == getattr(trait_key, "module", None):
							has_require_trait = True
							break
				if not has_require_trait and ctx.trait_index is not None and ctx.fn_require_assumed:
					for _subj, _key in ctx.fn_require_assumed:
						if recv_type_param_id is not None and _subj != recv_type_param_id and _subj != recv_type_key:
							continue
						if recv_tp_name is not None and _subj == recv_tp_name:
							pass
						_trait_def = ctx.trait_index.traits_by_id.get(_key)
						_req_expr = getattr(_trait_def, "require_expr", None) if _trait_def is not None else None
						if _req_expr is None:
							continue
						for _atom in _extract_conjunctive_facts(_req_expr):
							_key2 = trait_key_from_expr(_atom.trait, default_module=_key.module or ctx.current_module_name, default_package=ctx.default_package, module_packages=ctx.module_packages)
							if getattr(_key2, "name", None) == getattr(trait_key, "name", None) and getattr(_key2, "module", None) == getattr(trait_key, "module", None):
								has_require_trait = True
								break
						if has_require_trait:
							break
				if not has_require_trait and instantiation_mode and req_expr is None and not ctx.fn_require_assumed and not trait_type_args_by_key:
					has_require_trait = True
				if not has_require_trait:
					if missing_require_trait is None:
						missing_require_trait = trait_key
					continue
				matching_traits.append(trait_key)
			if not matching_traits and instantiation_mode and ctx.trait_index is not None:
				if trait_type_args_by_key:
					for _key in trait_type_args_by_key.keys():
						if ctx.trait_index.has_method(_key, expr.method_name):
							matching_traits.append(_key)
					if matching_traits:
						pass
				inst_candidates: list[TraitKey] = []
				for _key in ctx.trait_index.traits_by_id.keys():
					if ctx.trait_index.has_method(_key, expr.method_name):
						inst_candidates.append(_key)
				if len(inst_candidates) == 1:
					matching_traits.append(inst_candidates[0])
				if not matching_traits and ctx.trait_impl_index is not None and receiver_nominal is not None and hasattr(ctx.trait_impl_index, "candidates_for_target_method"):
					for impl_cand in ctx.trait_impl_index.candidates_for_target_method(receiver_nominal, expr.method_name):
						if getattr(impl_cand, "trait", None) is not None:
							matching_traits.append(impl_cand.trait)
					if len(matching_traits) > 1:
						matching_traits = _dedupe_by_key(list(matching_traits), lambda item: getattr(item, "name", None) or item)
			if not matching_traits:
				if missing_require_trait is not None:
					diagnostics.append(_tc_diag(message=f"requirement not satisfied: expected {_trait_label(missing_require_trait)}", severity="error", span=getattr(expr, "loc", Span()), notes=[f"requirement_trait={_trait_label(missing_require_trait)}"]))
					return MethodCallResult(ctx.unknown_ty, None)
				if saw_method_in_scope:
					diagnostics.append(_tc_diag(message=f"no matching method '{expr.method_name}' for receiver {_label_typeid(recv_ty)}", severity="error", span=getattr(expr, "loc", Span())))
					return MethodCallResult(ctx.unknown_ty, None)
				diagnostics.append(_tc_diag(message=f"no matching method '{expr.method_name}' for receiver {_label_typeid(recv_ty)}", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None)
			if len(matching_traits) > 1:
				names = ", ".join(sorted(_trait_label(tr) for tr in matching_traits))
				raise ResolutionError(f"ambiguous method '{expr.method_name}' for receiver {_label_typeid(recv_ty)}; candidates from traits: {names}", span=getattr(expr, "loc", Span()), code="E-METHOD-AMBIGUOUS")
			trait_key = matching_traits[0]
			trait_def = ctx.trait_index.traits_by_id.get(trait_key)
			method_sig = None
			if trait_def is not None:
				for method in getattr(trait_def, "methods", []) or []:
					if getattr(method, "name", None) == expr.method_name:
						method_sig = method
						break
			if method_sig is None:
				diagnostics.append(_tc_diag(message=f"no matching method '{expr.method_name}' for receiver {_label_typeid(recv_ty)}", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None)
			method_type_params = list(getattr(method_sig, "type_params", []) or [])
			local_type_param_map: dict[str, TypeId] = {"Self": receiver_nominal}
			trait_type_params = list(getattr(trait_def, "type_params", []) or []) if trait_def is not None else []
			trait_type_args = trait_type_args_by_key.get(trait_key, [])
			if not trait_type_args and trait_type_args_by_key:
				for key, vals in trait_type_args_by_key.items():
					if getattr(key, "name", None) == getattr(trait_key, "name", None) and getattr(key, "module", None) == getattr(trait_key, "module", None):
						trait_type_args = vals
						break
			if trait_type_params:
				if len(trait_type_args) != len(trait_type_params):
					diagnostics.append(_tc_diag(message=f"no matching method '{expr.method_name}' for receiver {_label_typeid(recv_ty)}", severity="error", span=getattr(expr, "loc", Span())))
					return MethodCallResult(ctx.unknown_ty, None)
				for idx, name in enumerate(trait_type_params):
					local_type_param_map[name] = trait_type_args[idx]
			if method_type_params:
				if not type_arg_ids or len(type_arg_ids) != len(method_type_params):
					diagnostics.append(_tc_diag(message=f"type argument count mismatch for method '{expr.method_name}'", severity="error", span=getattr(expr, "loc", Span())))
					return MethodCallResult(ctx.unknown_ty, None)
				for idx, name in enumerate(method_type_params):
					local_type_param_map[name] = type_arg_ids[idx]
			param_type_ids: list[TypeId] = []
			for param in list(getattr(method_sig, "params", []) or []):
				if param.type_expr is None:
					if param.name == "self":
						param_type_ids.append(receiver_nominal)
						continue
					diagnostics.append(_tc_diag(message="method parameter type missing", severity="error", span=getattr(expr, "loc", Span())))
					return MethodCallResult(ctx.unknown_ty, None)
				param_type_ids.append(resolve_opaque_type(param.type_expr, ctx.type_table, module_id=trait_key.module or ctx.current_module_name, type_params=local_type_param_map))
			ret_id = resolve_opaque_type(method_sig.return_type, ctx.type_table, module_id=trait_key.module or ctx.current_module_name, type_params=local_type_param_map)
			direct_fn_id = None
			concrete_receiver = None
			if recv_tp_name is not None and ctx.type_param_map and recv_tp_name in ctx.type_param_map:
				_mapped = ctx.type_param_map[recv_tp_name]
				if not isinstance(_mapped, TypeParamId) and not ctx.type_table.has_typevar(_mapped):
					concrete_receiver = _mapped
			if concrete_receiver is None and recv_tp_name is not None and ctx.preseed_type_params and recv_tp_name in ctx.preseed_type_params:
				_mapped = ctx.preseed_type_params[recv_tp_name]
				if not isinstance(_mapped, TypeParamId) and not ctx.type_table.has_typevar(_mapped):
					concrete_receiver = _mapped
			if instantiation_mode and concrete_receiver is None:
				diagnostics.append(_tc_diag(message=f"no implementation for method '{expr.method_name}' on receiver {_label_typeid(recv_ty)}", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None)
			if concrete_receiver is not None:
				_receiver_nominal_for_impl = _unwrap_ref_type(concrete_receiver)
				if ctx.trait_impl_index is not None and hasattr(ctx.trait_impl_index, "candidates_for_target_method"):
					for impl_cand in ctx.trait_impl_index.candidates_for_target_method(_receiver_nominal_for_impl, expr.method_name):
						if getattr(impl_cand, "trait", None) == trait_key:
							direct_fn_id = impl_cand.fn_id
							break
				if direct_fn_id is None and ctx.callable_registry is not None:
					diagnostics.append(_tc_diag(message=f"no implementation for method '{expr.method_name}' on receiver {_label_typeid(recv_ty)}", severity="error", span=getattr(expr, "loc", Span())))
					return MethodCallResult(ctx.unknown_ty, None)
			call_target = CallTarget.direct(direct_fn_id) if direct_fn_id is not None else CallTarget.trait(trait_key, expr.method_name)
			info = _call_info_target(list(param_type_ids), ret_id, not bool(getattr(method_sig, "declared_nothrow", False)), call_target)
			return MethodCallResult(ret_id, info)
		else:
			receiver_nominal_for_lookup = receiver_base if receiver_base is not None and receiver_args is not None else receiver_nominal
			visible_modules_for_methods = ctx.visible_modules or (ctx.current_module,)
			if instantiation_mode and ctx.module_ids_by_name:
				visible_modules_for_methods = tuple(ctx.module_ids_by_name.values())
			if ctx.module_ids_by_name is not None and any(isinstance(m, str) for m in visible_modules_for_methods):
				mapped: list[int] = []
				for m in visible_modules_for_methods:
					if isinstance(m, str):
						mid = ctx.module_ids_by_name.get(m)
						if mid is not None:
							mapped.append(mid)
					elif isinstance(m, int):
						mapped.append(m)
				visible_modules_for_methods = tuple(mapped)
			visible_modules_set = set(visible_modules_for_methods)
			candidates = ctx.callable_registry.get_method_candidates_unscoped(receiver_nominal_type_id=receiver_nominal_for_lookup, name=expr.method_name)
			trait_candidates: list[CallableDecl] = []
			inherent_candidates: list[CallableDecl] = []
			traits_in_scope_set = set(traits_in_scope()) if traits_in_scope is not None else set()
			trait_impl_fn_id_to_trait: dict[FunctionId, TraitKey] = {}
			trait_impl_fn_id_to_require: dict[FunctionId, object] = {}
			if ctx.trait_impl_index is not None and receiver_nominal_for_lookup is not None and hasattr(ctx.trait_impl_index, "candidates_for_target_method"):
				for impl_cand in ctx.trait_impl_index.candidates_for_target_method(receiver_nominal_for_lookup, expr.method_name):
					trait_impl_fn_id_to_trait[impl_cand.fn_id] = impl_cand.trait
					if getattr(impl_cand, "require_expr", None) is not None:
						trait_impl_fn_id_to_require[impl_cand.fn_id] = impl_cand.require_expr
			is_generic_context = receiver_base is not None and receiver_args is not None and any(ctx.type_table.has_typevar(t) for t in receiver_args)
			for cand in candidates:
				inst_subst_args: list[TypeId] | None = None
				trait_key_for_cand = None
				if ctx.trait_impl_index is not None and cand.fn_id is not None and hasattr(ctx.trait_impl_index, "trait_key_for_fn_id"):
					trait_key_for_cand = ctx.trait_impl_index.trait_key_for_fn_id(cand.fn_id)
				if trait_key_for_cand is None and cand.fn_id is not None:
					trait_key_for_cand = trait_impl_fn_id_to_trait.get(cand.fn_id)
				if trait_key_for_cand is None and cand.fn_id is not None and ctx.trait_index is not None:
					name_parts = str(cand.fn_id.name).split("::")
					if len(name_parts) >= 3:
						trait_name = name_parts[-2]
						for _tkey in ctx.trait_index.traits_by_id.keys():
							if getattr(_tkey, "name", None) == trait_name:
								trait_key_for_cand = _tkey
								break
				if trait_key_for_cand is not None and ctx.trait_index is not None and ctx.trait_index.is_missing(trait_key_for_cand):
					raise ResolutionError(f"missing trait metadata for '{_trait_label(trait_key_for_cand)}'", span=getattr(expr, "loc", Span()))
				if trait_key_for_cand is not None:
					if trait_key_for_cand in traits_in_scope_set:
						if _candidate_visible(cand, visible_modules_set=visible_modules_set, current_module_id=ctx.current_module):
							trait_candidates.append(cand)
					continue
				is_visible = _candidate_visible(cand, visible_modules_set=visible_modules_set, current_module_id=ctx.current_module)
				if cand.kind is CallableKind.METHOD_INHERENT:
					if is_visible:
						inherent_candidates.append(cand)
				else:
					if traits_in_scope_set and cand.kind is CallableKind.METHOD_TRAIT:
						if is_visible:
							trait_candidates.append(cand)
			if inherent_candidates:
				candidates = inherent_candidates
			elif trait_candidates:
				candidates = trait_candidates
			else:
				candidates = []
			require_failures: list[ProofFailure] = []
			require_info: dict[object, tuple[parser_ast.TraitExpr, dict[object, object], str, dict[TypeParamId, tuple[str, int]]]] = {}
			saw_require_failed = False
			require_missing_label: str | None = None
			if ctx.require_env_local is not None and candidates:
				filtered_candidates: list[CallableDecl] = []
				for cand in candidates:
					req_expr = trait_impl_fn_id_to_require.get(cand.fn_id) if cand.fn_id is not None else None
					if req_expr is None:
						req_expr = _require_for_fn(cand.fn_id if cand.fn_id is not None else None)
					if req_expr is None:
						filtered_candidates.append(cand)
						continue
					world = ctx.global_trait_world or ctx.visible_trait_world
					if world is None:
						filtered_candidates.append(cand)
						continue
					if receiver_args is not None and isinstance(req_expr, parser_ast.TraitIs):
						_req_key = trait_key_from_expr(req_expr.trait, default_module=ctx.current_module_name, default_package=ctx.default_package, module_packages=ctx.module_packages)
						if getattr(_req_key, "name", None) == "Copy" and ctx.type_table.is_copy(receiver_args[0]):
							filtered_candidates.append(cand)
							continue
					env = TraitEnv(default_module=(cand.fn_id.module if cand.fn_id is not None else ctx.current_module_name), default_package=ctx.default_package, module_packages=ctx.module_packages or {}, assumed_true=set(ctx.fn_require_assumed), type_table=ctx.type_table)
					subjects: set[object] = set()
					_collect_trait_subjects(req_expr, subjects)
					subst: dict[object, object] = {}
					sig_local = ctx.signatures_by_id.get(cand.fn_id) if cand.fn_id is not None and ctx.signatures_by_id is not None else None
					impl_subst_req = None
					if sig_local and receiver_args is not None:
						impl_params = list(getattr(sig_local, "impl_type_params", []) or [])
						impl_args = list(getattr(sig_local, "impl_target_type_args", None) or [])
						if impl_args and impl_params:
							impl_subst_req = _match_impl_type_args(template_args=impl_args, recv_args=list(receiver_args), impl_type_params=impl_params)
						if impl_subst_req is None and impl_params and len(impl_params) == len(receiver_args):
							impl_subst_req = Subst(owner=impl_params[0].id.owner, args=list(receiver_args))
						if impl_subst_req is not None:
							for idx, tp in enumerate(impl_params):
								if idx < len(impl_subst_req.args):
									key = _normalize_type_key(type_key_from_typeid(ctx.type_table, impl_subst_req.args[idx]))
									subst[tp.id] = key
									subst[tp.name] = key
					self_mode_for_infer = _self_mode_from_sig(sig_local) if sig_local is not None else None
					inferred_recv_ty = _infer_receiver_arg_type(self_mode_for_infer, recv_ty, receiver_is_lvalue=receiver_is_lvalue, receiver_can_mut_borrow=receiver_can_mut_borrow)
					arg_types_with_recv = [inferred_recv_ty] + list(arg_types)
					if sig_local and getattr(sig_local, "type_params", None) and receiver_args is not None:
						type_params = list(getattr(sig_local, "type_params", []) or [])
						for idx, tp in enumerate(type_params):
							if idx < len(receiver_args) and (tp.id in subjects or tp.name in subjects):
								key = _normalize_type_key(type_key_from_typeid(ctx.type_table, receiver_args[idx]))
								subst[tp.id] = key
								subst[tp.name] = key
					if sig_local is not None and getattr(sig_local, "type_params", None):
						inst_res = ctx.instantiate_sig_with_subst(sig=sig_local, arg_types=arg_types_with_recv, expected_type=expected_type, explicit_type_args=type_arg_ids, allow_infer=True, diag_span=call_type_args_span, call_kind="method", call_name=expr.method_name, receiver_type=inferred_recv_ty)
						if getattr(inst_res, "subst", None) is not None:
							inst_args = list(getattr(inst_res.subst, "args", []) or [])
							for idx, tp in enumerate(list(getattr(sig_local, "type_params", []) or [])):
								if idx < len(inst_args) and tp.id not in subst and tp.name not in subst:
									key = _normalize_type_key(type_key_from_typeid(ctx.type_table, inst_args[idx]))
									subst[tp.id] = key
									subst[tp.name] = key
					if sig_local and sig_local.param_names:
						for idx, pname in enumerate(sig_local.param_names):
							if pname in subst:
								continue
							if pname in subjects and idx < len(arg_types_with_recv):
								key = _normalize_type_key(type_key_from_typeid(ctx.type_table, arg_types_with_recv[idx]))
								subst[pname] = key
					res = prove_expr(world, env, subst, req_expr)
					if res.status is not ProofStatus.PROVED:
						saw_require_failed = True
						if require_missing_label is None:
							_atoms = _extract_conjunctive_facts(req_expr)
							_req_type = _atoms[0].trait if _atoms else req_expr
							_req_key = trait_key_from_expr(_req_type, default_module=ctx.current_module_name, default_package=ctx.default_package, module_packages=ctx.module_packages)
							require_missing_label = _trait_label(_req_key)
						origin = ObligationOrigin(kind=ObligationOriginKind.CALLEE_REQUIRE, label=f"method '{expr.method_name}'", span=Span.from_loc(getattr(req_expr, "loc", None)))
						failure = _require_failure(req_expr=req_expr, subst=subst, origin=origin, span=call_type_args_span or getattr(expr, "loc", Span()), env=env, world=world, result=res)
						if failure is not None:
							require_failures.append(failure)
						continue
					filtered_candidates.append(cand)
					cand_key = _candidate_key_for_decl(cand)
					if sig_local is not None:
						scope_map = _param_scope_map(sig_local)
					else:
						scope_map = {}
					req_mod = cand.fn_id.module if cand.fn_id is not None else ctx.current_module_name
					require_info[cand_key] = (req_expr, subst, req_mod, scope_map)
				candidates = filtered_candidates
			subst_for_receiver: Subst | None = None
			receiver_inst_args: list[TypeId] | None = None
			if receiver_nominal is not None:
				receiver_inst_ty = ctx.unwrap_ref_type(receiver_nominal)
				receiver_inst = ctx.type_table.get_struct_instance(receiver_inst_ty)
				if receiver_inst is not None:
					receiver_inst_args = list(receiver_inst.type_args)
			if receiver_base is not None and receiver_args is not None and receiver_args:
				param_ids = ctx.type_table.get_struct_type_param_ids(receiver_base)
				if param_ids and len(param_ids) == len(receiver_args):
					subst_for_receiver = Subst(owner=param_ids[0].owner, args=list(receiver_args))
			param_types_for_receiver: list[tuple[CallableDecl, CallableSignature, list[TypeId], Subst | None]] = []
			for cand in candidates:
				sig = cand.signature
				if sig is None:
					continue
				param_type_ids = list(sig.param_types or ())
				impl_subst: Subst | None = None
				if ctx.signatures_by_id is not None and cand.fn_id is not None and receiver_args is not None:
					fn_sig = ctx.signatures_by_id.get(cand.fn_id)
					impl_args = list(getattr(fn_sig, "impl_target_type_args", None) or [])
					impl_type_params = list(getattr(fn_sig, "impl_type_params", None) or [])
					if impl_args and impl_type_params:
						impl_subst = _match_impl_type_args(template_args=impl_args, recv_args=list(receiver_args), impl_type_params=impl_type_params)
					if impl_subst is None and impl_type_params and receiver_args is not None and len(impl_type_params) == len(receiver_args):
						impl_subst = Subst(owner=impl_type_params[0].id.owner, args=list(receiver_args))
					if impl_subst is None and impl_type_params and receiver_inst_args is not None and len(impl_type_params) == len(receiver_inst_args):
						impl_subst = Subst(owner=impl_type_params[0].id.owner, args=list(receiver_inst_args))
				if impl_subst is not None:
					param_type_ids = [apply_subst(p, impl_subst, ctx.type_table) for p in param_type_ids]
				if subst_for_receiver is not None:
					param_type_ids = [apply_subst(p, subst_for_receiver, ctx.type_table) for p in param_type_ids]
				param_types_for_receiver.append((cand, sig, param_type_ids, impl_subst))
			receiver_candidates: list[tuple[CallableDecl, CallableSignature, list[TypeId], bool, bool, int, Subst | None]] = []
			had_autoborrow_place_error = False
			saw_typed_nongeneric_with_type_args = False
			type_arg_counts: set[int] = set()
			for cand, sig, param_type_ids, impl_subst in param_types_for_receiver:
				if not param_type_ids:
					continue
				if type_arg_ids and sig is not None:
					fn_sig = ctx.signatures_by_id.get(cand.fn_id) if cand.fn_id is not None and ctx.signatures_by_id is not None else None
					if fn_sig is not None:
						if not list(getattr(fn_sig, "type_params", []) or []):
							saw_typed_nongeneric_with_type_args = True
							continue
						if type_arg_ids and len(type_arg_ids) != len(getattr(fn_sig, "type_params", []) or []):
							type_arg_counts.add(len(getattr(fn_sig, "type_params", []) or []))
							continue
				self_mode = _self_mode_from_sig(sig)
				compat_ok, needs_autoborrow = _receiver_compat(recv_ty, param_type_ids[0], self_mode)
				if not compat_ok:
					continue
				if needs_autoborrow is not None and not receiver_is_lvalue:
					if isinstance(expr, H.HMethodCall):
						had_autoborrow_place_error = True
					continue
				if self_mode is None:
					continue
				wants_mut_ref = self_mode.name == "SELF_BY_REF_MUT"
				pref = _receiver_preference(self_mode, receiver_is_lvalue=receiver_is_lvalue, receiver_can_mut_borrow=receiver_can_mut_borrow, autoborrow=needs_autoborrow)
				if pref is None:
					continue
				receiver_candidates.append((cand, sig, param_type_ids, needs_autoborrow, wants_mut_ref, pref, impl_subst))
			if not receiver_candidates:
				if had_autoborrow_place_error:
					diagnostics.append(
						_tc_diag(
							message="borrow requires an addressable place; bind to a local first",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return MethodCallResult(ctx.unknown_ty, None)
				if receiver_nominal_for_lookup is not None and ctx.callable_registry is not None:
					hidden = ctx.callable_registry.get_method_candidates_unscoped(receiver_nominal_type_id=receiver_nominal_for_lookup, name=expr.method_name)
					visible_modules = visible_modules_for_methods or ()
					visible_modules_set = set(visible_modules)
					hidden_not_visible = [
						cand for cand in hidden
						if not _candidate_visible(cand, visible_modules_set=visible_modules_set, current_module_id=ctx.current_module)
					]
					if hidden_not_visible:
						hidden_decl = hidden_not_visible[0]
						label = None
						visibility_provenance = getattr(ctx, "visibility_provenance", None)
						mod_chain = visibility_provenance.get(hidden_decl.module_id) if visibility_provenance is not None else None
						mod_name = None
						if mod_chain:
							mod_name = mod_chain[-1]
						elif hidden_decl.fn_id is not None and getattr(hidden_decl.fn_id, "module", None):
							mod_name = hidden_decl.fn_id.module
						elif ctx.module_ids_by_name is not None:
							for name, mid in ctx.module_ids_by_name.items():
								if mid == hidden_decl.module_id:
									mod_name = name
									break
						if mod_name is None:
							mod_name = str(hidden_decl.module_id)
						if hidden_decl.kind is CallableKind.METHOD_TRAIT and hidden_decl.trait_id is not None and ctx.trait_key_for_id is not None:
							trait_key = ctx.trait_key_for_id(hidden_decl.trait_id)
							label = f"{_trait_label(trait_key)}@{mod_name}"
						elif label is None and ctx.trait_impl_index is not None and hidden_decl.fn_id is not None and hasattr(ctx.trait_impl_index, "trait_key_for_fn_id"):
							trait_key = ctx.trait_impl_index.trait_key_for_fn_id(hidden_decl.fn_id)
							if trait_key is not None:
								label = f"{_trait_label(trait_key)}@{mod_name}"
						elif mod_name:
							label = mod_name
						note = _visibility_note(hidden_decl.module_id) if hidden_decl is not None else None
						notes = [note] if note else []
						msg = f"method '{expr.method_name}' exists but is not visible here"
						if label:
							msg = f"{msg} ({label})"
						diagnostics.append(_tc_diag(message=msg, severity="error", span=getattr(expr, "loc", Span()), notes=notes))
						return MethodCallResult(ctx.unknown_ty, None)
				if saw_require_failed:
					if require_failures:
						failure = _pick_best_failure(require_failures)
						msg = _format_failure_message(failure) if failure is not None else "requirement not satisfied"
						notes = ctx.requirement_notes(failure) if failure is not None and getattr(ctx, "requirement_notes", None) is not None else []
						diagnostics.append(_tc_diag(message=msg, severity="error", span=getattr(expr, "loc", Span()), code=_failure_code(failure) if failure is not None else None, notes=notes))
					else:
						if require_missing_label is not None:
							diagnostics.append(_tc_diag(message=f"requirement not satisfied: expected {require_missing_label}", severity="error", span=getattr(expr, "loc", Span()), notes=[f"requirement_trait={require_missing_label}"]))
						else:
							diagnostics.append(_tc_diag(message="requirement not satisfied", severity="error", span=getattr(expr, "loc", Span())))
					return MethodCallResult(ctx.unknown_ty, None)
				if type_arg_ids:
					if type_arg_counts:
						exp = ", ".join(str(n) for n in sorted(type_arg_counts))
						diagnostics.append(_tc_diag(message=f"type argument count mismatch for method '{expr.method_name}': expected one of ({exp}), got {len(type_arg_ids)}", severity="error", span=call_type_args_span or getattr(expr, "loc", Span())))
						return MethodCallResult(ctx.unknown_ty, None, None)
					if saw_typed_nongeneric_with_type_args:
						diagnostics.append(_tc_diag(message=f"type arguments require a generic signature for method '{expr.method_name}'", severity="error", span=call_type_args_span or getattr(expr, "loc", Span())))
						return MethodCallResult(ctx.unknown_ty, None, None)
				if ctx.trait_index is not None and traits_in_scope is not None:
					for _trait_key in traits_in_scope():
						if ctx.trait_index.is_missing(_trait_key):
							diagnostics.append(_tc_diag(message=f"missing trait metadata for '{_trait_label(_trait_key)}'", severity="error", span=getattr(expr, "loc", Span())))
							return MethodCallResult(ctx.unknown_ty, None)
				diagnostics.append(_tc_diag(message=f"no matching method '{expr.method_name}' for receiver {_label_typeid(recv_ty)}", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None)
			max_pref = max(item[5] for item in receiver_candidates)
			pref_candidates = [item for item in receiver_candidates if item[5] == max_pref]
			if len(pref_candidates) > 1:
				wants_mut = [item for item in pref_candidates if item[4]]
				if wants_mut and len(wants_mut) != len(pref_candidates):
					pref_candidates = wants_mut
			if len(pref_candidates) > 1:
				pref_candidates = _pick_most_specific_items(pref_candidates, lambda item: _candidate_key_for_decl(item[0]), require_info)
				keys = {_candidate_key_for_decl(item[0]) for item in pref_candidates}
				if len(keys) > 1:
					trait_labels: list[str] = []
					if ctx.trait_impl_index is not None or trait_impl_fn_id_to_trait:
						for cand, _sig, _param_type_ids, _needs_autoborrow, _wants_mut_ref, _pref, _impl_subst in pref_candidates:
							trait_key = None
							if cand.fn_id is not None and hasattr(ctx.trait_impl_index, "trait_key_for_fn_id"):
								trait_key = ctx.trait_impl_index.trait_key_for_fn_id(cand.fn_id)
							if trait_key is None and cand.fn_id is not None:
								trait_key = trait_impl_fn_id_to_trait.get(cand.fn_id)
							if trait_key is None and cand.trait_id is not None and ctx.trait_key_for_id is not None:
								trait_key = ctx.trait_key_for_id(cand.trait_id)
							mod_name = cand.fn_id.module if cand.fn_id is not None and getattr(cand.fn_id, "module", None) else None
							if trait_key is not None:
								if mod_name:
									trait_labels.append(f"{_trait_label(trait_key)}@{mod_name}")
								else:
									trait_labels.append(_trait_label(trait_key))
					if trait_labels:
						arg_label = ", ".join(_label_typeid(t) for t in arg_types)
						msg = f"ambiguous method '{expr.method_name}' for receiver {_label_typeid(recv_ty)} and args [{arg_label}]; candidates from traits: {', '.join(sorted(set(trait_labels)))}"
						diagnostics.append(_tc_diag(message=msg, severity="error", span=getattr(expr, "loc", Span()), code="E-METHOD-AMBIGUOUS"))
						return MethodCallResult(ctx.unknown_ty, None)
					mod_names: set[str] = set()
					notes: list[str] = []
					note_by_name: dict[str, str] = {}
					visibility_provenance = getattr(ctx, "visibility_provenance", None)
					for cand, _sig, _param_type_ids, _needs_autoborrow, _wants_mut_ref, _pref, _impl_subst in pref_candidates:
						mod_name = None
						if cand.fn_id is not None and getattr(cand.fn_id, "module", None):
							mod_name = cand.fn_id.module
						elif cand.fn_id is not None and getattr(cand.fn_id, "name", None) and "::" in cand.fn_id.name:
							mod_name = cand.fn_id.name.split("::", 1)[0]
						elif visibility_provenance is not None:
							mod_chain = visibility_provenance.get(cand.module_id)
							if mod_chain:
								mod_name = mod_chain[-1]
						if mod_name is None and cand.module_id is not None and ctx.module_ids_by_name is not None:
							for _n, _mid in ctx.module_ids_by_name.items():
								if _mid == cand.module_id:
									mod_name = _n
									break
						if mod_name:
							mod_names.add(mod_name)
							_note_mod_id = cand.module_id
							if _note_mod_id is None and cand.fn_id is not None and getattr(cand.fn_id, "module", None) and ctx.module_ids_by_name is not None:
								_note_mod_id = ctx.module_ids_by_name.get(cand.fn_id.module)
							note = _visibility_note(_note_mod_id) if _note_mod_id is not None else None
							if note is None and visibility_provenance is not None and mod_name is not None:
								for _mid, _chain in visibility_provenance.items():
									if _chain and _chain[-1] == mod_name:
										note = _visibility_note(_mid)
										break
							if note is None and visibility_provenance is not None and mod_name is not None:
								for _chain in visibility_provenance.values():
									if _chain and _chain[-1] == mod_name:
										_parts = [_chain[0]]
										for _idx in range(1, len(_chain)):
											_label = "import->" if _idx == 1 else "reexport->"
											_parts.append(f"{_label} {_chain[_idx]}")
										note = f"visible via: {' '.join(_parts)}"
										break
							if note is not None:
								note_by_name.setdefault(mod_name, f"{mod_name} {note}")
					if note_by_name:
						for name in sorted(note_by_name.keys()):
							notes.append(note_by_name[name])
					if mod_names:
						mod_list = ", ".join(sorted(mod_names))
						msg = f"ambiguous method '{expr.method_name}' for receiver {_label_typeid(recv_ty)} (candidates: {mod_list})"
					else:
						msg = f"ambiguous method '{expr.method_name}' for receiver {_label_typeid(recv_ty)}"
					diagnostics.append(_tc_diag(message=msg, severity="error", span=getattr(expr, "loc", Span()), notes=notes))
					return MethodCallResult(ctx.unknown_ty, None)
			cand, sig, param_type_ids, needs_autoborrow, wants_mut_ref, _pref, impl_subst = pref_candidates[0]
			ret_id = sig.result_type or ctx.unknown_ty
			fn_sig = ctx.signatures_by_id.get(cand.fn_id) if cand.fn_id is not None and ctx.signatures_by_id is not None else None
			if fn_sig is not None:
				if fn_sig.param_type_ids is None and fn_sig.param_types is not None:
					local_type_params = {p.name: p.id for p in fn_sig.type_params}
					fn_sig = replace(fn_sig, param_type_ids=[resolve_opaque_type(p, ctx.type_table, module_id=fn_sig.module, type_params=local_type_params) for p in fn_sig.param_types])
				if fn_sig.return_type_id is None and fn_sig.return_type is not None:
					local_type_params = {p.name: p.id for p in fn_sig.type_params}
					fn_sig = replace(fn_sig, return_type_id=resolve_opaque_type(fn_sig.return_type, ctx.type_table, module_id=fn_sig.module, type_params=local_type_params))
				if impl_subst is not None and fn_sig.param_type_ids is not None and fn_sig.return_type_id is not None:
					fn_sig = replace(fn_sig, param_type_ids=[apply_subst(p, impl_subst, ctx.type_table) for p in fn_sig.param_type_ids], return_type_id=apply_subst(fn_sig.return_type_id, impl_subst, ctx.type_table))
				self_mode_for_infer = _self_mode_from_sig(fn_sig)
				inferred_recv_ty = _infer_receiver_arg_type(self_mode_for_infer, recv_ty, receiver_is_lvalue=receiver_is_lvalue, receiver_can_mut_borrow=receiver_can_mut_borrow)
				inst_arg_types = [inferred_recv_ty] + list(arg_types)
				inst_res = ctx.instantiate_sig_with_subst(sig=fn_sig, arg_types=inst_arg_types, expected_type=expected_type, explicit_type_args=type_arg_ids, allow_infer=True, diag_span=call_type_args_span, call_kind="method", call_name=expr.method_name, receiver_type=inferred_recv_ty)
				if inst_res.error and inst_res.error.kind in {InferErrorKind.CANNOT_INFER, InferErrorKind.CONFLICT}:
					msg, notes = _format_infer_failure(inst_res.context, inst_res)
					diagnostics.append(_tc_diag(message=msg, severity="error", span=getattr(expr, "loc", Span()), notes=notes))
					return MethodCallResult(ctx.unknown_ty, None, None)
				if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPEPARAMS and type_arg_ids:
					diagnostics.append(_tc_diag(message=f"type arguments require a generic signature for method '{expr.method_name}'", severity="error", span=call_type_args_span or getattr(expr, "loc", Span())))
					return MethodCallResult(ctx.unknown_ty, None, None)
				if inst_res.error and inst_res.error.kind is InferErrorKind.TYPEARG_COUNT and type_arg_ids:
					exp = inst_res.error.expected_count if inst_res.error.expected_count is not None else len(type_arg_ids)
					diagnostics.append(_tc_diag(message=f"type argument count mismatch for method '{expr.method_name}': expected {exp}, got {len(type_arg_ids)}", severity="error", span=call_type_args_span or getattr(expr, "loc", Span())))
					return MethodCallResult(ctx.unknown_ty, None, None)
				if inst_res.error and inst_res.error.kind is InferErrorKind.NO_TYPES:
					return MethodCallResult(ctx.unknown_ty, None, None)
				if inst_res.error:
					return MethodCallResult(ctx.unknown_ty, None, None)
				if inst_res.inst_params is not None:
					param_type_ids = list(inst_res.inst_params)
				if inst_res.inst_return is not None:
					ret_id = inst_res.inst_return
				if getattr(inst_res, "subst", None) is not None:
					inst_subst_args = list(getattr(inst_res.subst, "args", []) or [])
				if fn_sig is not None and receiver_args is not None and getattr(fn_sig, "impl_type_params", None):
					impl_params = list(getattr(fn_sig, "impl_type_params", []) or [])
					impl_owner = impl_params[0].id.owner if impl_params else None
					if impl_owner is not None and receiver_args and not any(ctx.type_table.has_typevar(t) for t in receiver_args):
						def _has_owner_typevar(tid: TypeId) -> bool:
							td = ctx.type_table.get(tid)
							if td.kind is TypeKind.TYPEVAR and td.type_param_id is not None and td.type_param_id.owner == impl_owner:
								return True
							for sub in td.param_types or []:
								if _has_owner_typevar(sub):
									return True
							return False
						if any(_has_owner_typevar(t) for t in param_type_ids) or _has_owner_typevar(ret_id):
							fallback_subst = Subst(owner=impl_owner, args=list(receiver_args))
							param_type_ids = [apply_subst(p, fallback_subst, ctx.type_table) for p in param_type_ids]
							ret_id = apply_subst(ret_id, fallback_subst, ctx.type_table)
			if impl_subst is not None:
				ret_id = apply_subst(ret_id, impl_subst, ctx.type_table)
			if subst_for_receiver is not None:
				ret_id = apply_subst(ret_id, subst_for_receiver, ctx.type_table)
			all_args = [expr.receiver] + list(expr.args)
			updated_arg_types, had_autoborrow_error = ctx.apply_autoborrow_args(all_args, [recv_ty] + arg_types, param_type_ids, span=getattr(expr, "loc", Span()))
			expr.receiver = all_args[0]
			expr.args = list(all_args[1:])
			if had_autoborrow_error:
				return MethodCallResult(ctx.unknown_ty, None, None)
			param_type_ids = list(updated_arg_types)
			recv_ty = param_type_ids[0] if param_type_ids else recv_ty
			if not ctx.args_match_params([recv_ty] + arg_types, param_type_ids):
				diagnostics.append(_tc_diag(message=f"no matching method '{expr.method_name}' for receiver {_label_typeid(recv_ty)}", severity="error", span=getattr(expr, "loc", Span())))
				return MethodCallResult(ctx.unknown_ty, None, None)
			coerced_params = ctx.coerce_args_for_params([recv_ty] + arg_types, param_type_ids)
			ret_id = ret_id or ctx.unknown_ty
			call_target = CallTarget.direct(cand.fn_id)
			can_throw = True
			if cand.fn_id is not None and ctx.signatures_by_id is not None:
				fn_sig = ctx.signatures_by_id.get(cand.fn_id)
				if fn_sig is not None:
					if fn_sig.declared_can_throw is not None:
						can_throw = bool(fn_sig.declared_can_throw)
			info = _call_info_target(list(coerced_params), ret_id, can_throw, call_target)
			receiver_autoborrow = None
			if needs_autoborrow:
				receiver_autoborrow = SelfMode.SELF_BY_REF_MUT if wants_mut_ref else SelfMode.SELF_BY_REF
			if ctx.record_instantiation is not None and cand.fn_id is not None:
				impl_args = tuple(receiver_args or [])
				fn_args = tuple(inst_subst_args or [])
				if (impl_args or fn_args) and not any(ctx.type_table.has_typevar(t) for t in list(impl_args) + list(fn_args)):
					csid = getattr(expr, "callsite_id", None)
					ctx.record_instantiation(callsite_id=csid, target_fn_id=cand.fn_id, impl_args=impl_args, fn_args=fn_args)
			return MethodCallResult(ret_id, info, MethodResolution(decl=cand, receiver_autoborrow=receiver_autoborrow, result_type=ret_id))

	diagnostics.append(_tc_diag(message=f"no matching method '{expr.method_name}' for receiver {_label_typeid(recv_ty)}", severity="error", span=getattr(expr, "loc", Span())))
	return MethodCallResult(ctx.unknown_ty, None)


def resolve_qualified_member_ufcs(ctx: MethodResolverContext, expr: object, qm: object, *, expected_type: TypeId | None, type_arg_ids: list[TypeId] | None, call_type_args_span: Span | None, call_origin: str | None, recv_arg_type: TypeId | None, arg_type_ids: list[TypeId] | None) -> MethodCallResult | None:
	diagnostics = ctx.diagnostics
	_tc_diag = ctx.tc_diag
	base_te = getattr(qm, "base_type_expr", None)
	if base_te is None:
		return None
	trait_index = ctx.trait_index
	if trait_index is None:
		return None
	trait_key = trait_key_from_expr(base_te, default_module=ctx.current_module_name, default_package=ctx.default_package, module_packages=ctx.module_packages)
	if trait_key not in trait_index.traits_by_id:
		for _k in trait_index.traits_by_id:
			if getattr(_k, "module", None) == getattr(trait_key, "module", None) and getattr(_k, "name", None) == getattr(trait_key, "name", None):
				trait_key = _k
				break
	base_mod = getattr(base_te, "module_id", None) or getattr(base_te, "module_alias", None)
	base_name = getattr(base_te, "name", None)
	base_args = list(getattr(base_te, "args", []) or [])
	if base_args and type_arg_ids is None:
		if call_type_args_span is None:
			first_loc = getattr(base_args[0], "loc", None)
			if first_loc is not None:
				call_type_args_span = Span.from_loc(first_loc)
		type_arg_ids = [
			resolve_opaque_type(a, ctx.type_table, module_id=base_mod or ctx.current_module_name, type_params=ctx.type_param_map)
			for a in base_args
		]
	if trait_key not in trait_index.traits_by_id:
		if call_origin == "for_iter" and base_mod == "std.iter" and base_name == "Iterable" and qm.member == "iter":
			diagnostics.append(_tc_diag(message="type is not iterable", code="E-NOT-ITERABLE", severity="error", span=getattr(expr, "loc", Span())))
			return MethodCallResult(ctx.unknown_ty, None)
		if call_origin == "for_next" and base_mod == "std.iter" and base_name == "SinglePassIterator" and qm.member == "next":
			diagnostics.append(_tc_diag(message="iter() result is not an iterator", code="E-ITER-RESULT-NOT-ITERATOR", severity="error", span=getattr(expr, "loc", Span())))
			return MethodCallResult(ctx.unknown_ty, None)
		return MethodCallResult(ctx.unknown_ty, None)
	if not getattr(expr, "args", None):
		diagnostics.append(_tc_diag(message="UFCS call requires a receiver argument", severity="error", span=getattr(expr, "loc", Span())))
		return MethodCallResult(ctx.unknown_ty, None)
	trait_def = trait_index.traits_by_id.get(trait_key)
	method_sig = None
	if trait_def is not None:
		for method in getattr(trait_def, "methods", []) or []:
			if getattr(method, "name", None) == qm.member:
				method_sig = method
				break
	trait_type_params = list(getattr(trait_def, "type_params", []) or []) if trait_def is not None else []
	if method_sig is not None and (not trait_type_params or type_arg_ids):
		recv_ty = recv_arg_type if recv_arg_type is not None else ctx.type_expr(expr.args[0], used_as_value=False)
		recv_nominal = ctx.unwrap_ref_type(recv_ty)
		if trait_type_params and type_arg_ids and ctx.type_table.get(recv_nominal).kind is not TypeKind.TYPEVAR:
			world = ctx.global_trait_world or ctx.visible_trait_world
			if world is not None:
				subject_key = ctx.normalize_type_key(
					type_key_from_typeid(ctx.type_table, recv_nominal),
				)
				trait_args = tuple(
					ctx.normalize_type_key(type_key_from_typeid(ctx.type_table, tid))
					for tid in type_arg_ids
				)
				env = TraitEnv(
					assumed_true=set(),
					assumed_false=set(),
					default_module=trait_key.module or ctx.current_module_name,
					default_package=ctx.default_package,
					module_packages=ctx.module_packages,
					type_table=ctx.type_table,
				)
				obl = Obligation(
					subject=subject_key,
					trait=trait_key,
					trait_args=trait_args,
					origin=ObligationOrigin(kind=ObligationOriginKind.METHOD_CALL, label="trait call", span=getattr(expr, "loc", None)),
					span=getattr(expr, "loc", None),
				)
				if prove_obligation(world, env, obl) is not None:
					diagnostics.append(
						_tc_diag(
							message=f"no implementation for trait '{ctx.trait_label(trait_key)}' on receiver {ctx.label_typeid(recv_ty)}",
							severity="error",
							span=getattr(expr, "loc", Span()),
						)
					)
					return MethodCallResult(ctx.unknown_ty, None)
		if ctx.type_table.get(recv_nominal).kind is TypeKind.TYPEVAR:
			local_type_param_map: dict[str, TypeId] = {"Self": recv_nominal}
			if trait_type_params:
				if not type_arg_ids or len(type_arg_ids) != len(trait_type_params):
					diagnostics.append(_tc_diag(message="type argument count mismatch for trait call", severity="error", span=getattr(expr, "loc", Span())))
					return MethodCallResult(ctx.unknown_ty, None)
				for idx, name in enumerate(trait_type_params):
					local_type_param_map[name] = type_arg_ids[idx]
			param_type_ids: list[TypeId] = []
			for param in list(getattr(method_sig, "params", []) or []):
				if param.type_expr is None:
					if param.name == "self":
						param_type_ids.append(recv_nominal)
						continue
					diagnostics.append(_tc_diag(message="method parameter type missing", severity="error", span=getattr(expr, "loc", Span())))
					return MethodCallResult(ctx.unknown_ty, None)
				param_type_ids.append(resolve_opaque_type(param.type_expr, ctx.type_table, module_id=trait_key.module or ctx.current_module_name, type_params=local_type_param_map))
			ret_id = resolve_opaque_type(method_sig.return_type, ctx.type_table, module_id=trait_key.module or ctx.current_module_name, type_params=local_type_param_map)
			call_target = CallTarget.trait(trait_key, qm.member)
			info = CallInfo(target=call_target, sig=CallSig(param_types=tuple(param_type_ids), user_ret_type=ret_id, can_throw=not bool(getattr(method_sig, "declared_nothrow", False))))
			return MethodCallResult(ret_id, info)
	class _TmpMethodCall:
		def __init__(self, receiver: object, method_name: str, args: list[object], loc: Span, type_args: list[object] | None):
			self.receiver = receiver
			self.method_name = method_name
			self.args = args
			self.kwargs = []
			self.loc = loc
			self.type_args = type_args or []
			self.receiver_type_id = None
			self.arg_type_ids = None
	tmp_expr = _TmpMethodCall(expr.args[0], qm.member, list(expr.args[1:]), getattr(expr, "loc", Span()), getattr(expr, "type_args", None))
	tmp_expr.callsite_id = getattr(expr, "callsite_id", None)
	if recv_arg_type is not None:
		tmp_expr.receiver_type_id = recv_arg_type
	if arg_type_ids is not None:
		tmp_expr.arg_type_ids = list(arg_type_ids[1:])
	tmp_ctx = _make_method_ctx(ctx, diagnostics=diagnostics, traits_in_scope=lambda: [trait_key], trait_key=trait_key)
	method_res = resolve_method_call(tmp_ctx, tmp_expr, expected_type=expected_type)
	if call_origin == "for_iter" and method_res.call_info is None:
		diagnostics.append(_tc_diag(message="type is not iterable", code="E-NOT-ITERABLE", severity="error", span=getattr(expr, "loc", Span())))
		return MethodCallResult(ctx.unknown_ty, None)
	if call_origin == "for_next" and method_res.call_info is None:
		diagnostics.append(_tc_diag(message="iter() result is not an iterator", code="E-ITER-RESULT-NOT-ITERATOR", severity="error", span=getattr(expr, "loc", Span())))
		return MethodCallResult(ctx.unknown_ty, None)
	if method_res.call_info is not None:
		return method_res
	return method_res


def resolve_call_expr(
	ctx: CallResolverContext,
	expr: object,
	expected_type: TypeId | None,
	*,
	record_expr: Callable[[object, TypeId], TypeId],
	record_call_info: Callable[[object, list[TypeId], TypeId, bool, CallTarget], None],
	record_invoke_call_info: Callable[[object, list[TypeId], TypeId, bool], None],
) -> TypeId:
	diagnostics = ctx.diagnostics
	_tc_diag = ctx.tc_diag
	type_expr = ctx.type_expr
	_optional_variant_type = ctx.optional_variant_type
	_unwrap_ref_type = ctx.unwrap_ref_type
	_struct_base_and_args = ctx.struct_base_and_args
	_receiver_place = ctx.receiver_place
	_receiver_can_mut_borrow = ctx.receiver_can_mut_borrow
	_receiver_compat = ctx.receiver_compat
	_receiver_preference = ctx.receiver_preference
	_args_match_params = ctx.args_match_params
	_coerce_args_for_params = ctx.coerce_args_for_params
	_infer_receiver_arg_type = ctx.infer_receiver_arg_type
	_instantiate_sig_with_subst = ctx.instantiate_sig_with_subst
	_apply_autoborrow_args = ctx.apply_autoborrow_args
	_label_typeid = ctx.label_typeid
	_trait_label = ctx.trait_label
	_require_for_fn = ctx.require_for_fn
	_extract_conjunctive_facts = ctx.extract_conjunctive_facts
	_subject_name = ctx.subject_name
	_normalize_type_key = ctx.normalize_type_key
	_collect_trait_subjects = ctx.collect_trait_subjects
	_require_failure = ctx.require_failure
	_format_failure_message = ctx.format_failure_message
	_failure_code = ctx.failure_code
	_pick_best_failure = ctx.pick_best_failure
	_param_scope_map = ctx.param_scope_map
	_candidate_key_for_decl = ctx.candidate_key_for_decl
	_visibility_note = ctx.visibility_note
	_intrinsic_method_fn_id = ctx.intrinsic_method_fn_id
	_instantiate_sig = ctx.instantiate_sig
	_self_mode_from_sig = ctx.self_mode_from_sig
	_match_impl_type_args = ctx.match_impl_type_args
	_fixed_width_allowed = ctx.fixed_width_allowed
	_reject_zst_array = ctx.reject_zst_array
	_pretty_type_name = ctx.pretty_type_name
	_format_ctor_signature_list = ctx.format_ctor_signature_list
	_enforce_struct_requires = ctx.enforce_struct_requires
	_ensure_field_visible = ctx.ensure_field_visible
	_visible_modules_for_free_call = ctx.visible_modules_for_free_call
	_infer = ctx.infer
	_format_infer_failure = ctx.format_infer_failure
	_lambda_can_throw = ctx.lambda_can_throw
	module_ids_by_name = ctx.module_ids_by_name
	visibility_provenance = ctx.visibility_provenance
	current_module_name = ctx.current_module_name
	current_module = ctx.current_module
	default_package = ctx.default_package
	module_packages = ctx.module_packages
	type_param_map = ctx.type_param_map
	type_param_names = ctx.type_param_names
	fn_id = ctx.current_fn_id
	signatures_by_id = ctx.signatures_by_id
	callable_registry = ctx.callable_registry
	trait_index = ctx.trait_index
	trait_impl_index = ctx.trait_impl_index
	impl_index = ctx.impl_index
	visible_modules = ctx.visible_modules
	visible_trait_world = ctx.visible_trait_world
	global_trait_world = ctx.global_trait_world
	trait_scope_by_module = ctx.trait_scope_by_module
	require_env_local = ctx.require_env_local
	fn_require_assumed = ctx.fn_require_assumed
	_traits_in_scope = ctx.traits_in_scope

	if hasattr(H, "HTypeApp") and isinstance(expr.fn, getattr(H, "HTypeApp")):
		type_app = expr.fn
		if getattr(expr, "type_args", None):
			diagnostics.append(_tc_diag(message="E-TYPEARGS-DUP: duplicate type arguments on call", severity="error", span=getattr(expr, "loc", Span())))
			return record_expr(expr, ctx.unknown_ty)
		expr.type_args = list(type_app.type_args or [])
		expr.fn = type_app.fn
	if isinstance(expr.fn, H.HLambda):
		arg_types = [type_expr(a) for a in expr.args]
		kw_pairs = list(getattr(expr, "kwargs", []) or [])
		if getattr(expr, "type_args", None):
			diagnostics.append(_tc_diag(message="type arguments are not supported on lambda calls; apply them on the named function", severity="error", span=getattr(expr, "loc", Span())))
			return record_expr(expr, ctx.unknown_ty)
		if kw_pairs:
			diagnostics.append(_tc_diag(message="keyword arguments are not supported on lambda calls in MVP", severity="error", span=getattr(expr, "loc", Span())))
			return record_expr(expr, ctx.unknown_ty)
		fn_params = [t if t is not None else ctx.unknown_ty for t in arg_types]
		fn_ret = expected_type if expected_type is not None else ctx.unknown_ty
		callee_expected = ctx.type_table.ensure_function(fn_params, fn_ret, can_throw=True)
		expr.fn.allow_capture_invoke = True
		callee_ty = type_expr(expr.fn, expected_type=callee_expected)
		if callee_ty is None:
			return record_expr(expr, ctx.unknown_ty)
		callee_def = ctx.type_table.get(callee_ty)
		if callee_def.kind is not TypeKind.FUNCTION:
			diagnostics.append(_tc_diag(message="call target is not a function value", severity="error", span=getattr(expr, "loc", Span())))
			return record_expr(expr, ctx.unknown_ty)
		fn_sig_params = list(callee_def.param_types[:-1]) if callee_def.param_types else []
		fn_sig_ret = callee_def.param_types[-1] if callee_def.param_types else ctx.unknown_ty
		if len(fn_sig_params) != len(arg_types):
			diagnostics.append(_tc_diag(message=f"function value expects {len(fn_sig_params)} arguments, got {len(arg_types)}", severity="error", span=getattr(expr, "loc", Span())))
			return record_expr(expr, fn_sig_ret)
		for want, have in zip(fn_sig_params, arg_types):
			if have is not None and want != have:
				diagnostics.append(_tc_diag(message=(f"function value argument type mismatch (have {ctx.type_table.get(have).name}, expected {ctx.type_table.get(want).name})"), severity="error", span=getattr(expr, "loc", Span())))
		call_can_throw = callee_def.can_throw()
		if getattr(expr.fn, "can_throw_effective", None) is not None:
			call_can_throw = bool(expr.fn.can_throw_effective)
		record_call_info(expr, param_types=fn_sig_params, return_type=fn_sig_ret, can_throw=call_can_throw, target=CallTarget.indirect(expr.fn.node_id))
		return record_expr(expr, fn_sig_ret)
	if isinstance(expr.fn, H.HField) and isinstance(expr.fn.subject, H.HVar) and (expr.fn.subject.binding_id is None or expr.fn.subject.module_id is not None):
		_module_id = expr.fn.subject.module_id or expr.fn.subject.name
		expr.fn = H.HVar(name=expr.fn.name, binding_id=None, module_id=_module_id)
	if getattr(expr, "type_args", None) and not (isinstance(expr.fn, H.HVar) or (hasattr(H, "HQualifiedMember") and isinstance(expr.fn, getattr(H, "HQualifiedMember")))):
		diagnostics.append(_tc_diag(message="E-TYPEARGS-NOT-ALLOWED: type arguments are only supported on named call targets", severity="error", span=getattr(expr, "loc", Span())))
		return record_expr(expr, ctx.unknown_ty)
	def _is_std_mem_module(mod_name: str | None) -> bool:
		if mod_name is None:
			return False
		if isinstance(mod_name, int):
			std_mem_id = module_ids_by_name.get("std.mem")
			return std_mem_id is not None and mod_name == std_mem_id
		if mod_name == "std.mem":
			return True
		mod_id = module_ids_by_name.get(mod_name)
		if mod_id is None:
			return False
		std_mem_id = module_ids_by_name.get("std.mem")
		if std_mem_id is not None and mod_id == std_mem_id:
			return True
		chain = visibility_provenance.get(mod_id)
		if not chain:
			return False
		return "std.mem" in chain or chain[-1] == "std.mem"
	def _rawbuffer_elem_type(tid: TypeId | None) -> TypeId | None:
		if tid is None:
			return None
		td = ctx.type_table.get(tid)
		if td.kind is TypeKind.REF:
			inner = td.param_types[0] if td.param_types else None
			if inner is None:
				return None
			tid = inner
		base_id, args = ctx.struct_base_and_args(tid)
		if base_id is None:
			return None
		base_td = ctx.type_table.get(base_id)
		if base_td.kind is not TypeKind.STRUCT or base_td.module_id != "std.mem" or base_td.name != "RawBuffer":
			return None
		return args[0] if args else None
	def _raw_ptr_elem_type(tid: TypeId | None, table: object) -> TypeId | None:
		if tid is None:
			return None
		td = table.get(tid)
		if td.kind is not TypeKind.RAW_PTR or not td.param_types:
			return None
		return td.param_types[0]
	def _mut_ref_inner(tid: TypeId | None) -> TypeId | None:
		if tid is None:
			return None
		td = ctx.type_table.get(tid)
		if td.kind is TypeKind.REF and td.ref_mut and td.param_types:
			return td.param_types[0]
		return None
	def _maybe_uninit_inner(tid: TypeId | None) -> TypeId | None:
		if tid is None:
			return None
		td = ctx.type_table.get(tid)
		if td.kind is not TypeKind.REF or not td.param_types:
			return None
		inner = td.param_types[0]
		inner_td = ctx.type_table.get(inner)
		if inner_td.kind is not TypeKind.STRUCT or inner_td.name != "MaybeUninit" or inner_td.module_id != "std.mem":
			return None
		inst = ctx.type_table.get_struct_instance(inner)
		if inst is not None and inst.type_args:
			return inst.type_args[0]
		if inner_td.param_types:
			return inner_td.param_types[0]
		return None
	def _borrowed_place(arg: H.HExpr) -> H.HPlaceExpr | None:
		if isinstance(arg, H.HBorrow) and arg.is_mut:
			return place_expr_from_lvalue_expr(arg.subject)
		if isinstance(arg, H.HPlaceExpr):
			return arg
		return None
	def _canonical_tid(tid: TypeId | TypeParamId | None) -> TypeId | None:
		if tid is None:
			return None
		if isinstance(tid, TypeParamId):
			tp_name = ctx.type_param_names.get(tid) if ctx.type_param_names else None
			return ctx.type_table.ensure_typevar(tid, name=tp_name)
		return tid

	def _intrinsic_kind_for_decl(decl: CallableDecl, sig: object | None) -> IntrinsicKind | None:
		if sig is None or not getattr(sig, "is_intrinsic", False):
			return None
		return getattr(sig, "intrinsic_kind", None)

	if isinstance(expr.fn, H.HVar) and _is_std_mem_module(expr.fn.module_id) and expr.fn.name in ("alloc_uninit", "dealloc", "ptr_at_ref", "ptr_at_mut", "write", "read", "ptr_from_ref", "ptr_from_ref_mut", "ptr_offset", "ptr_read", "ptr_write", "ptr_is_null", "replace", "swap", "maybe_uninit", "maybe_write", "maybe_assume_init_ref", "maybe_assume_init_mut", "maybe_assume_init_read"):
		rawbuffer_allowed = bool(ctx.allow_rawbuffer)
		if getattr(expr, "kwargs", None):
			first_kw = (getattr(expr, "kwargs", []) or [None])[0]
			diagnostics.append(_tc_diag(message=f"{expr.fn.name} does not support keyword arguments", severity="error", span=getattr(first_kw, "loc", getattr(expr, "loc", Span()))))
			return record_expr(expr, ctx.unknown_ty)
		if expr.fn.name in ("alloc_uninit", "dealloc", "ptr_at_ref", "ptr_at_mut", "write", "read", "ptr_from_ref", "ptr_from_ref_mut", "ptr_offset", "ptr_read", "ptr_write", "ptr_is_null", "maybe_uninit", "maybe_write", "maybe_assume_init_ref", "maybe_assume_init_mut", "maybe_assume_init_read"):
			rawbuffer_only = expr.fn.name in ("alloc_uninit", "dealloc", "ptr_at_ref", "ptr_at_mut", "write", "read")
			if not check_unsafe_call(allow_unsafe=ctx.allow_unsafe, allow_unsafe_without_block=ctx.allow_unsafe_without_block, unsafe_context=ctx.unsafe_context, trusted_module=rawbuffer_allowed, rawbuffer_only=rawbuffer_only, diagnostics=diagnostics, tc_diag=_tc_diag, span=getattr(expr, "loc", Span())):
				return record_expr(expr, ctx.unknown_ty)
		call_type_args = getattr(expr, "type_args", None) or []
		type_arg_ids = [resolve_opaque_type(t, ctx.type_table, module_id=current_module_name, type_params=type_param_map) for t in call_type_args]
		arg_types_local = [type_expr(a, used_as_value=False) for a in expr.args]
		ret_ty: TypeId | None = None
		param_types: list[TypeId] = []
		intrinsic_kind: IntrinsicKind | None = None
		if expr.fn.name == "alloc_uninit":
			if len(type_arg_ids) != 1:
				diagnostics.append(_tc_diag(message="E-RAWBUFFER-TYPEARGS: alloc_uninit<T> requires exactly one type argument", severity="error", span=getattr(expr, "loc", Span())))
				return record_expr(expr, ctx.unknown_ty)
			t_elem = type_arg_ids[0]
			rawbuf_tid = ctx.type_table.ensure_named("RawBuffer", module_id="std.mem")
			rawbuf_inst = ctx.type_table.ensure_struct_template(rawbuf_tid, [t_elem]) if ctx.type_table.has_typevar(t_elem) else ctx.type_table.ensure_struct_instantiated(rawbuf_tid, [t_elem])
			param_types = [ctx.int_ty]
			ret_ty = rawbuf_inst
			intrinsic_kind = IntrinsicKind.RAW_ALLOC
		elif expr.fn.name in ("maybe_uninit", "maybe_write", "maybe_assume_init_ref", "maybe_assume_init_mut", "maybe_assume_init_read"):
			if len(type_arg_ids) > 1:
				diagnostics.append(_tc_diag(message=f"{expr.fn.name} accepts at most one type argument", severity="error", span=getattr(expr, "loc", Span())))
				return record_expr(expr, ctx.unknown_ty)
			t_elem = type_arg_ids[0] if type_arg_ids else None
			if expr.fn.name == "maybe_uninit":
				if len(expr.args) != 0:
					diagnostics.append(_tc_diag(message="maybe_uninit expects no arguments", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if t_elem is None:
					diagnostics.append(_tc_diag(message="maybe_uninit<T> requires a type argument", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				maybe_tid = ctx.type_table.ensure_named("MaybeUninit", module_id="std.mem")
				maybe_inst = ctx.type_table.ensure_struct_template(maybe_tid, [t_elem]) if ctx.type_table.has_typevar(t_elem) else ctx.type_table.ensure_struct_instantiated(maybe_tid, [t_elem])
				param_types = []
				ret_ty = maybe_inst
				intrinsic_kind = IntrinsicKind.MAYBE_UNINIT
			elif expr.fn.name == "maybe_write":
				if len(expr.args) != 2:
					diagnostics.append(_tc_diag(message="maybe_write expects two arguments", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if t_elem is None:
					t_elem = _maybe_uninit_inner(arg_types_local[0])
				if t_elem is None:
					diagnostics.append(_tc_diag(message="maybe_write expects &mut MaybeUninit<T> as the first argument", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				maybe_tid = ctx.type_table.ensure_named("MaybeUninit", module_id="std.mem")
				maybe_inst = ctx.type_table.ensure_struct_template(maybe_tid, [t_elem]) if ctx.type_table.has_typevar(t_elem) else ctx.type_table.ensure_struct_instantiated(maybe_tid, [t_elem])
				param_types = [ctx.type_table.ensure_ref_mut(maybe_inst), t_elem]
				if arg_types_local[0] is not None and arg_types_local[0] != param_types[0]:
					diagnostics.append(_tc_diag(message="maybe_write expects &mut MaybeUninit<T> as the first argument", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if arg_types_local[1] is not None and arg_types_local[1] != t_elem:
					diagnostics.append(_tc_diag(message="maybe_write value type does not match MaybeUninit<T>", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				ret_ty = ctx.type_table.ensure_ref_mut(t_elem)
				intrinsic_kind = IntrinsicKind.MAYBE_WRITE
			elif expr.fn.name in ("maybe_assume_init_ref", "maybe_assume_init_mut", "maybe_assume_init_read"):
				if len(expr.args) != 1:
					diagnostics.append(_tc_diag(message=f"{expr.fn.name} expects one argument", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if t_elem is None:
					t_elem = _maybe_uninit_inner(arg_types_local[0])
				if t_elem is None:
					diagnostics.append(_tc_diag(message=f"{expr.fn.name} expects a MaybeUninit<T> reference argument", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				maybe_tid = ctx.type_table.ensure_named("MaybeUninit", module_id="std.mem")
				maybe_inst = ctx.type_table.ensure_struct_template(maybe_tid, [t_elem]) if ctx.type_table.has_typevar(t_elem) else ctx.type_table.ensure_struct_instantiated(maybe_tid, [t_elem])
				if expr.fn.name == "maybe_assume_init_ref":
					param_types = [ctx.type_table.ensure_ref(maybe_inst)]
					ret_ty = ctx.type_table.ensure_ref(t_elem)
					intrinsic_kind = IntrinsicKind.MAYBE_ASSUME_INIT_REF
				elif expr.fn.name == "maybe_assume_init_mut":
					param_types = [ctx.type_table.ensure_ref_mut(maybe_inst)]
					ret_ty = ctx.type_table.ensure_ref_mut(t_elem)
					intrinsic_kind = IntrinsicKind.MAYBE_ASSUME_INIT_MUT
				else:
					param_types = [ctx.type_table.ensure_ref_mut(maybe_inst)]
					ret_ty = t_elem
					intrinsic_kind = IntrinsicKind.MAYBE_ASSUME_INIT_READ
				if arg_types_local[0] is not None and arg_types_local[0] != param_types[0]:
					diagnostics.append(_tc_diag(message=f"{expr.fn.name} expects a MaybeUninit<T> reference argument", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
		elif expr.fn.name in ("dealloc", "ptr_at_ref", "ptr_at_mut", "write", "read", "ptr_from_ref", "ptr_from_ref_mut", "ptr_offset", "ptr_read", "ptr_write", "ptr_is_null", "replace", "swap"):
			if len(arg_types_local) < 1:
				diagnostics.append(_tc_diag(message=f"{expr.fn.name} expects at least 1 argument", severity="error", span=getattr(expr, "loc", Span())))
				return record_expr(expr, ctx.unknown_ty)
			if expr.fn.name == "replace":
				mut_inner = _mut_ref_inner(arg_types_local[0])
				t_elem = _canonical_tid(type_arg_ids[0]) if type_arg_ids else _canonical_tid(mut_inner)
				if t_elem is None:
					diagnostics.append(_tc_diag(message="replace requires a concrete element type", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if len(arg_types_local) != 2:
					diagnostics.append(_tc_diag(message="replace expects two arguments", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if mut_inner is None:
					diagnostics.append(_tc_diag(message="replace expects &mut T as the first argument", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if arg_types_local[1] is not None and _canonical_tid(arg_types_local[1]) != _canonical_tid(t_elem):
					diagnostics.append(_tc_diag(message="cannot infer type arguments for 'replace': conflicting constraints", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				place_expr = _borrowed_place(expr.args[0])
				if place_expr is None:
					diagnostics.append(_tc_diag(message="replace expects &mut T as the first argument", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if any(isinstance(p, H.HPlaceDeref) for p in place_expr.projections) and isinstance(place_expr.base, H.HVar):
					base_ty = ctx.type_expr(place_expr.base, used_as_value=False)
					if base_ty is not None:
						base_def = ctx.type_table.get(base_ty)
						if base_def.kind is TypeKind.REF and not base_def.ref_mut:
							diagnostics.append(_tc_diag(message=f"cannot write through *{place_expr.base.name} unless {place_expr.base.name} is a mutable reference", severity="error", span=getattr(expr, "loc", Span())))
							return record_expr(expr, ctx.unknown_ty)
				param_types = [ctx.type_table.ensure_ref_mut(t_elem), t_elem]
				ret_ty = t_elem
				intrinsic_kind = IntrinsicKind.REPLACE
				record_call_info(expr, param_types=param_types, return_type=ret_ty, can_throw=False, target=CallTarget.intrinsic(intrinsic_kind))
				return record_expr(expr, ret_ty)
			if expr.fn.name == "swap":
				t_elem = _canonical_tid(type_arg_ids[0]) if type_arg_ids else _canonical_tid(_mut_ref_inner(arg_types_local[0]))
				if t_elem is None:
					diagnostics.append(_tc_diag(message="swap requires a concrete element type", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if len(arg_types_local) != 2:
					diagnostics.append(_tc_diag(message="swap expects two arguments", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if type_arg_ids and _canonical_tid(_mut_ref_inner(arg_types_local[0])) != _canonical_tid(t_elem):
					diagnostics.append(_tc_diag(message="cannot infer type arguments for 'swap': conflicting constraints", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if _mut_ref_inner(arg_types_local[0]) is None or _mut_ref_inner(arg_types_local[1]) is None:
					diagnostics.append(_tc_diag(message="swap expects &mut T arguments", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if _canonical_tid(_mut_ref_inner(arg_types_local[1])) != _canonical_tid(t_elem):
					diagnostics.append(_tc_diag(message="cannot infer type arguments for 'swap': conflicting constraints", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				left_place = _borrowed_place(expr.args[0])
				right_place = _borrowed_place(expr.args[1])
				if left_place is None or right_place is None:
					diagnostics.append(_tc_diag(message="swap expects &mut T arguments", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if left_place.base.binding_id == right_place.base.binding_id and left_place.projections == right_place.projections:
					diagnostics.append(_tc_diag(message="swap operands must be distinct non-overlapping places", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				if any(isinstance(p, H.HPlaceDeref) for p in left_place.projections) and isinstance(left_place.base, H.HVar):
					base_ty = ctx.type_expr(left_place.base, used_as_value=False)
					if base_ty is not None:
						base_def = ctx.type_table.get(base_ty)
						if base_def.kind is TypeKind.REF and not base_def.ref_mut:
							diagnostics.append(_tc_diag(message=f"cannot write through *{left_place.base.name} unless {left_place.base.name} is a mutable reference", severity="error", span=getattr(expr, "loc", Span())))
							return record_expr(expr, ctx.unknown_ty)
				if any(isinstance(p, H.HPlaceDeref) for p in right_place.projections) and isinstance(right_place.base, H.HVar):
					base_ty = ctx.type_expr(right_place.base, used_as_value=False)
					if base_ty is not None:
						base_def = ctx.type_table.get(base_ty)
						if base_def.kind is TypeKind.REF and not base_def.ref_mut:
							diagnostics.append(_tc_diag(message=f"cannot write through *{right_place.base.name} unless {right_place.base.name} is a mutable reference", severity="error", span=getattr(expr, "loc", Span())))
							return record_expr(expr, ctx.unknown_ty)
				param_types = [ctx.type_table.ensure_ref_mut(t_elem), ctx.type_table.ensure_ref_mut(t_elem)]
				ret_ty = ctx.void_ty
				intrinsic_kind = IntrinsicKind.SWAP
				record_call_info(expr, param_types=param_types, return_type=ret_ty, can_throw=False, target=CallTarget.intrinsic(intrinsic_kind))
				return record_expr(expr, ret_ty)
			if expr.fn.name in ("ptr_from_ref", "ptr_from_ref_mut", "ptr_offset", "ptr_read", "ptr_write", "ptr_is_null"):
				t_elem = None
				if expr.fn.name in ("ptr_from_ref", "ptr_from_ref_mut"):
					if len(arg_types_local) != 1:
						diagnostics.append(_tc_diag(message=f"{expr.fn.name} expects exactly one argument", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					t_elem = _ref_inner(arg_types_local[0]) if expr.fn.name == "ptr_from_ref" else _mut_ref_inner(arg_types_local[0])
					if t_elem is None:
						diagnostics.append(_tc_diag(message=f"{expr.fn.name} expects a reference argument", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					param_types = [ctx.type_table.ensure_ref(t_elem)] if expr.fn.name == "ptr_from_ref" else [ctx.type_table.ensure_ref_mut(t_elem)]
					ret_ty = ctx.type_table.new_ptr(t_elem, module_id="std.mem")
					intrinsic_kind = IntrinsicKind.PTR_FROM_REF if expr.fn.name == "ptr_from_ref" else IntrinsicKind.PTR_FROM_REF_MUT
				elif expr.fn.name == "ptr_offset":
					if len(arg_types_local) != 2:
						diagnostics.append(_tc_diag(message="ptr_offset expects two arguments", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					t_elem = _raw_ptr_elem_type(arg_types_local[0], ctx.type_table)
					if t_elem is None:
						diagnostics.append(_tc_diag(message="ptr_offset expects Ptr<T> as the first argument", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					param_types = [ctx.type_table.new_ptr(t_elem, module_id="std.mem"), ctx.int_ty]
					ret_ty = ctx.type_table.new_ptr(t_elem, module_id="std.mem")
					intrinsic_kind = IntrinsicKind.PTR_OFFSET
				elif expr.fn.name == "ptr_read":
					if len(arg_types_local) != 1:
						diagnostics.append(_tc_diag(message="ptr_read expects exactly one argument", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					t_elem = _raw_ptr_elem_type(arg_types_local[0], ctx.type_table)
					if t_elem is None:
						diagnostics.append(_tc_diag(message="ptr_read expects Ptr<T> as the first argument", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					param_types = [ctx.type_table.new_ptr(t_elem, module_id="std.mem")]
					ret_ty = t_elem
					intrinsic_kind = IntrinsicKind.PTR_READ
				elif expr.fn.name == "ptr_write":
					t_elem = _raw_ptr_elem_type(arg_types_local[0], ctx.type_table)
					if t_elem is None:
						diagnostics.append(_tc_diag(message="ptr_write expects Ptr<T> as the first argument", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					if len(arg_types_local) != 2:
						diagnostics.append(_tc_diag(message="ptr_write expects two arguments", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					if arg_types_local[1] is not None and _canonical_tid(arg_types_local[1]) != _canonical_tid(t_elem):
						diagnostics.append(_tc_diag(message="ptr_write value type does not match Ptr<T>", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					param_types = [ctx.type_table.new_ptr(t_elem, module_id="std.mem"), t_elem]
					ret_ty = ctx.void_ty
					intrinsic_kind = IntrinsicKind.PTR_WRITE
				elif expr.fn.name == "ptr_is_null":
					if len(arg_types_local) != 1:
						diagnostics.append(_tc_diag(message="ptr_is_null expects exactly one argument", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					t_elem = _raw_ptr_elem_type(arg_types_local[0], ctx.type_table)
					if t_elem is None:
						diagnostics.append(_tc_diag(message="ptr_is_null expects Ptr<T> as the first argument", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					param_types = [ctx.type_table.new_ptr(t_elem, module_id="std.mem")]
					ret_ty = ctx.bool_ty
					intrinsic_kind = IntrinsicKind.PTR_IS_NULL
			else:
				t_elem = _rawbuffer_elem_type(arg_types_local[0])
				if t_elem is None and type_arg_ids:
					t_elem = type_arg_ids[0]
				t_elem = _canonical_tid(t_elem)
				if t_elem is None:
					diagnostics.append(_tc_diag(message=f"{expr.fn.name} requires RawBuffer<T> receiver", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				rawbuf_tid = ctx.type_table.ensure_named("RawBuffer", module_id="std.mem")
				rawbuf_inst = ctx.type_table.ensure_struct_template(rawbuf_tid, [t_elem]) if ctx.type_table.has_typevar(t_elem) else ctx.type_table.ensure_struct_instantiated(rawbuf_tid, [t_elem])
				if expr.fn.name == "dealloc":
					param_types = [rawbuf_inst]
					ret_ty = ctx.void_ty
					intrinsic_kind = IntrinsicKind.RAW_DEALLOC
				elif expr.fn.name == "ptr_at_ref":
					param_types = [ctx.type_table.ensure_ref(rawbuf_inst), ctx.int_ty]
					ret_ty = ctx.type_table.ensure_ref(t_elem)
					intrinsic_kind = IntrinsicKind.RAW_PTR_AT_REF
				elif expr.fn.name == "ptr_at_mut":
					param_types = [ctx.type_table.ensure_ref_mut(rawbuf_inst), ctx.int_ty]
					ret_ty = ctx.type_table.ensure_ref_mut(t_elem)
					intrinsic_kind = IntrinsicKind.RAW_PTR_AT_MUT
				elif expr.fn.name == "write":
					if len(arg_types_local) != 3:
						diagnostics.append(_tc_diag(message="write expects three arguments", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					param_types = [ctx.type_table.ensure_ref_mut(rawbuf_inst), ctx.int_ty, t_elem]
					ret_ty = ctx.void_ty
					intrinsic_kind = IntrinsicKind.RAW_WRITE
					if arg_types_local[1] is not None and arg_types_local[1] != ctx.int_ty:
						diagnostics.append(_tc_diag(message="write expects Int as the index", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					if arg_types_local[2] is not None and _canonical_tid(arg_types_local[2]) != _canonical_tid(t_elem):
						diagnostics.append(_tc_diag(message="write value type does not match RawBuffer<T>", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
				elif expr.fn.name == "read":
					if len(arg_types_local) != 2:
						diagnostics.append(_tc_diag(message="read expects two arguments", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					param_types = [ctx.type_table.ensure_ref_mut(rawbuf_inst), ctx.int_ty]
					ret_ty = t_elem
					intrinsic_kind = IntrinsicKind.RAW_READ
					if arg_types_local[1] is not None and arg_types_local[1] != ctx.int_ty:
						diagnostics.append(_tc_diag(message="read expects Int as the index", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
		if ret_ty is None:
			return record_expr(expr, ctx.unknown_ty)
		if intrinsic_kind is None:
			diagnostics.append(_tc_diag(message=f"{expr.fn.name} intrinsic kind missing (checker bug)", severity="error", span=getattr(expr, "loc", Span())))
			return record_expr(expr, ctx.unknown_ty)
		record_call_info(expr, param_types=param_types, return_type=ret_ty, can_throw=False, target=CallTarget.intrinsic(intrinsic_kind))
		return record_expr(expr, ret_ty)

	if isinstance(expr.fn, H.HVar) and expr.fn.name in ("byte_length", "string_byte_at", "string_eq", "string_concat"):
		if getattr(expr, "kwargs", None):
			first_kw = (getattr(expr, "kwargs", []) or [None])[0]
			diagnostics.append(_tc_diag(message=f"{expr.fn.name} does not support keyword arguments", severity="error", span=getattr(first_kw, "loc", getattr(expr, "loc", Span()))))
			return record_expr(expr, ctx.unknown_ty)
		if getattr(expr, "type_args", None):
			diagnostics.append(_tc_diag(message=f"{expr.fn.name} does not accept type arguments", severity="error", span=getattr(expr, "loc", Span())))
			return record_expr(expr, ctx.unknown_ty)
		arg_types_local = [type_expr(a) for a in expr.args]
		if expr.fn.name == "byte_length":
			if len(arg_types_local) != 1:
				diagnostics.append(_tc_diag(message=f"{expr.fn.name} expects 1 argument", severity="error", span=getattr(expr, "loc", Span())))
				return record_expr(expr, ctx.unknown_ty)
			arg_ty = arg_types_local[0]
			if arg_ty == ctx.string_ty:
				place_expr = place_expr_from_lvalue_expr(expr.args[0])
				if place_expr is None:
					diagnostics.append(_tc_diag(message="borrow requires an addressable place; bind to a local first", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				expr.args[0] = H.HBorrow(subject=place_expr, is_mut=False)
				param_types = [ctx.type_table.ensure_ref(ctx.string_ty)]
			else:
				param_types = [arg_ty] if arg_ty is not None else []
				if arg_ty is None:
					return record_expr(expr, ctx.unknown_ty)
				td = ctx.type_table.get(arg_ty)
				if td.kind is not TypeKind.REF or not td.param_types or td.param_types[0] != ctx.string_ty:
					diagnostics.append(_tc_diag(message=f"no matching overload for function '{expr.fn.name}' with args {arg_types_local}", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
			record_call_info(expr, param_types=param_types, return_type=ctx.int_ty, can_throw=False, target=CallTarget.intrinsic(IntrinsicKind.BYTE_LENGTH))
			return record_expr(expr, ctx.int_ty)
		if expr.fn.name == "string_byte_at":
			if len(arg_types_local) != 2:
				diagnostics.append(_tc_diag(message=f"{expr.fn.name} expects 2 arguments", severity="error", span=getattr(expr, "loc", Span())))
				return record_expr(expr, ctx.unknown_ty)
			arg0_ty = arg_types_local[0]
			arg1_ty = arg_types_local[1]
			if arg0_ty == ctx.string_ty:
				place_expr = place_expr_from_lvalue_expr(expr.args[0])
				if place_expr is None:
					diagnostics.append(_tc_diag(message="borrow requires an addressable place; bind to a local first", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
				expr.args[0] = H.HBorrow(subject=place_expr, is_mut=False)
				arg0_ty = ctx.type_table.ensure_ref(ctx.string_ty)
			if arg0_ty is None or arg1_ty is None:
				return record_expr(expr, ctx.unknown_ty)
			td0 = ctx.type_table.get(arg0_ty)
			if td0.kind is not TypeKind.REF or not td0.param_types or td0.param_types[0] != ctx.string_ty:
				diagnostics.append(_tc_diag(message=f"no matching overload for function '{expr.fn.name}' with args {arg_types_local}", severity="error", span=getattr(expr, "loc", Span())))
				return record_expr(expr, ctx.unknown_ty)
			if arg1_ty != ctx.int_ty:
				diagnostics.append(_tc_diag(message=f"no matching overload for function '{expr.fn.name}' with args {arg_types_local}", severity="error", span=getattr(expr, "loc", Span())))
				return record_expr(expr, ctx.unknown_ty)
			record_call_info(expr, param_types=[arg0_ty, arg1_ty], return_type=ctx.byte_ty, can_throw=False, target=CallTarget.intrinsic(IntrinsicKind.STRING_BYTE_AT))
			return record_expr(expr, ctx.byte_ty)
		if expr.fn.name in ("string_eq", "string_concat"):
			if len(arg_types_local) != 2:
				diagnostics.append(_tc_diag(message=f"{expr.fn.name} expects 2 arguments", severity="error", span=getattr(expr, "loc", Span())))
				return record_expr(expr, ctx.unknown_ty)
			if arg_types_local[0] != ctx.string_ty or arg_types_local[1] != ctx.string_ty:
				diagnostics.append(_tc_diag(message=f"no matching overload for function '{expr.fn.name}' with args {arg_types_local}", severity="error", span=getattr(expr, "loc", Span())))
				return record_expr(expr, ctx.unknown_ty)
			ret_ty = ctx.string_ty if expr.fn.name == "string_concat" else ctx.bool_ty
			intrinsic = IntrinsicKind.STRING_CONCAT if expr.fn.name == "string_concat" else IntrinsicKind.STRING_EQ
			record_call_info(expr, param_types=[ctx.string_ty, ctx.string_ty], return_type=ret_ty, can_throw=False, target=CallTarget.intrinsic(intrinsic))
			return record_expr(expr, ret_ty)

	if isinstance(expr.fn, H.HLambda):
		lam = expr.fn
		if getattr(expr, "kwargs", None):
			diagnostics.append(_tc_diag(message="keyword arguments are only supported for struct constructors in MVP", severity="error", span=getattr(expr, "loc", Span())))
			return record_expr(expr, ctx.unknown_ty)
		arg_types = [type_expr(a) for a in expr.args]
		if len(arg_types) != len(lam.params):
			diagnostics.append(_tc_diag(message=f"lambda expects {len(lam.params)} arguments, got {len(arg_types)}", severity="error", span=getattr(expr, "loc", Span())))
			return record_expr(expr, ctx.unknown_ty)
		lambda_ret_type: TypeId | None = None
		if getattr(lam, "ret_type", None) is not None:
			try:
				lambda_ret_type = resolve_opaque_type(lam.ret_type, ctx.type_table, module_id=current_module_name)
			except Exception:
				lambda_ret_type = None
		if expected_type is not None:
			lambda_ret_type = expected_type
		call_ret = lambda_ret_type or ctx.unknown_ty
		can_throw = _lambda_can_throw(lam, None)
		lam.can_throw_effective = bool(can_throw)
		fn_ty = ctx.type_table.ensure_function(arg_types, call_ret, can_throw=bool(can_throw))
		record_call_info(expr, param_types=arg_types, return_type=call_ret, can_throw=can_throw, target=CallTarget.indirect(lam.node_id))
		return record_expr(expr, call_ret)

	if hasattr(H, "HQualifiedMember") and isinstance(expr.fn, getattr(H, "HQualifiedMember")):
		qm = expr.fn
		kw_pairs = getattr(expr, "kwargs", []) or []
		arg_exprs = list(expr.args)
		kw_value_types = [type_expr(kw.value, used_as_value=False) for kw in kw_pairs]
		call_type_args = getattr(expr, "type_args", None) or []
		call_type_args_span = None
		type_arg_ids: list[TypeId] | None = None
		if call_type_args:
			first_loc = getattr(call_type_args[0], "loc", None)
			if first_loc is not None:
				call_type_args_span = Span.from_loc(first_loc)
			type_arg_ids = [resolve_opaque_type(t, ctx.type_table, module_id=current_module_name, type_params=type_param_map) for t in call_type_args]
		arg_types = [type_expr(a, used_as_value=False) for a in arg_exprs]
		if kw_pairs and not arg_exprs:
			arg_types = list(kw_value_types)
		ctor_res = resolve_qualified_member_call(_make_resolver_ctx(ctx, diagnostics=diagnostics, current_module_name=current_module_name, default_package=default_package, module_packages=module_packages, type_param_map=type_param_map, tc_diag=_tc_diag, fixed_width_allowed=_fixed_width_allowed, reject_zst_array=_reject_zst_array, pretty_type_name=_pretty_type_name, format_ctor_signature_list=_format_ctor_signature_list, instantiate_sig=_instantiate_sig, enforce_struct_requires=_enforce_struct_requires, ensure_field_visible=_ensure_field_visible, visible_modules_for_free_call=_visible_modules_for_free_call, module_ids_by_name=module_ids_by_name, visibility_provenance=visibility_provenance, infer=_infer, format_infer_failure=_format_infer_failure, lambda_can_throw=_lambda_can_throw), qm, arg_exprs=list(arg_exprs), arg_types=arg_types, kw_pairs=kw_pairs, expected_type=expected_type, type_arg_ids=type_arg_ids, allow_infer=True, call_type_args_span=call_type_args_span)
		if ctor_res is not None:
			inst_params = list(ctor_res.inst_params)
			inst_return = ctor_res.inst_return
			expr.args = list(ctor_res.ctor_args)
			expr.kwargs = []
			expr.ctor_arg_field_indices = list(ctor_res.ctor_arg_field_indices)
			record_call_info(expr, param_types=inst_params, return_type=inst_return, can_throw=False, target=CallTarget.constructor(ctor_res.inst_return, qm.member, ctor_arg_field_indices=tuple(ctor_res.ctor_arg_field_indices)))
			return record_expr(expr, inst_return)
		method_ctx = _make_method_ctx(ctx, diagnostics=diagnostics, traits_in_scope=_traits_in_scope, trait_key=None)
		method_res = resolve_qualified_member_ufcs(method_ctx, expr, qm, expected_type=expected_type, type_arg_ids=type_arg_ids, call_type_args_span=call_type_args_span, call_origin=getattr(expr, "origin", None), recv_arg_type=arg_types[0] if arg_types else None, arg_type_ids=arg_types)
		if method_res is not None and method_res.call_info is not None:
			record_call_info(expr, param_types=list(method_res.call_info.sig.param_types), return_type=method_res.return_type, can_throw=bool(method_res.call_info.sig.can_throw), target=method_res.call_info.target)
			return record_expr(expr, method_res.return_type)
		return record_expr(expr, ctx.unknown_ty)
	if isinstance(expr.fn, H.HVar):
		kw_pairs = getattr(expr, "kwargs", []) or []
		kw_value_types = [type_expr(kw.value, used_as_value=False) for kw in kw_pairs]
		call_type_args = list(getattr(expr, "type_args", None) or [])
		call_type_args_span = None
		if call_type_args:
			first_loc = getattr(call_type_args[0], "loc", None)
			if first_loc is not None:
				call_type_args_span = Span.from_loc(first_loc)
		call_type_arg_ids = [resolve_opaque_type(t, ctx.type_table, module_id=current_module_name, type_params=type_param_map) for t in call_type_args] if call_type_args else None
		binding_id = getattr(expr.fn, "binding_id", None)
		if binding_id is not None:
			fn_val_ty = type_expr(expr.fn, used_as_value=True)
			if fn_val_ty is not None:
				fn_def = ctx.type_table.get(fn_val_ty)
				if fn_def.kind is TypeKind.FUNCTION and fn_def.param_types:
					if call_type_args:
						diagnostics.append(_tc_diag(message="type arguments are not supported on function values", severity="error", span=call_type_args_span or getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					param_types = list(fn_def.param_types[:-1])
					ret_type = fn_def.param_types[-1]
					if len(param_types) != len(expr.args):
						diagnostics.append(_tc_diag(message=f"no matching overload for function '{expr.fn.name}' with args {arg_types}", severity="error", span=getattr(expr, "loc", Span())))
						return record_expr(expr, ctx.unknown_ty)
					record_call_info(expr, param_types=param_types, return_type=ret_type, can_throw=fn_def.can_throw(), target=CallTarget.indirect(binding_id))
					return record_expr(expr, ret_type)
				diagnostics.append(_tc_diag(message="call target is not a function value", severity="error", span=getattr(expr, "loc", Span())))
				return record_expr(expr, ctx.unknown_ty)
		if expected_type is not None:
			ctor_res = resolve_unqualified_variant_ctor(_make_resolver_ctx(ctx, diagnostics=diagnostics, current_module_name=current_module_name, default_package=default_package, module_packages=module_packages, type_param_map=type_param_map, tc_diag=_tc_diag, fixed_width_allowed=_fixed_width_allowed, reject_zst_array=_reject_zst_array, pretty_type_name=_pretty_type_name, format_ctor_signature_list=_format_ctor_signature_list, instantiate_sig=_instantiate_sig, enforce_struct_requires=_enforce_struct_requires, ensure_field_visible=_ensure_field_visible, visible_modules_for_free_call=_visible_modules_for_free_call, module_ids_by_name=module_ids_by_name, visibility_provenance=visibility_provenance, infer=_infer, format_infer_failure=_format_infer_failure, lambda_can_throw=_lambda_can_throw), ctor_name=expr.fn.name, expected_type=expected_type, arg_exprs=list(expr.args), kw_pairs=kw_pairs)
			if ctor_res is not None:
				expr.args = list(ctor_res.ctor_args)
				expr.kwargs = []
				expr.ctor_arg_field_indices = list(ctor_res.ctor_arg_field_indices)
				record_call_info(expr, param_types=list(ctor_res.inst_params), return_type=ctor_res.inst_return, can_throw=False, target=CallTarget.constructor(ctor_res.inst_return, expr.fn.name, ctor_arg_field_indices=tuple(ctor_res.ctor_arg_field_indices)))
				return record_expr(expr, ctor_res.inst_return)
		if expected_type is None:
			schema_map = getattr(ctx.type_table, "variant_schemas", {})
			for _base_id, schema in getattr(schema_map, "items", lambda: [])():
				if getattr(schema, "module_id", None) not in (current_module_name, "lang.core"):
					continue
				if any(getattr(arm, "name", None) == expr.fn.name for arm in getattr(schema, "arms", []) or []):
					diagnostics.append(_tc_diag(message="E-CTOR-EXPECTED-TYPE: constructor calls require an expected variant type in MVP", severity="error", span=getattr(expr, "loc", Span())))
					return record_expr(expr, ctx.unknown_ty)
		struct_base = ctx.type_table.get_struct_base(module_id=expr.fn.module_id or current_module_name, name=expr.fn.name)
		if struct_base is None:
			struct_base = ctx.type_table.get_nominal(kind=TypeKind.STRUCT, module_id=expr.fn.module_id or current_module_name, name=expr.fn.name)
		if struct_base is not None:
			struct_id = struct_base
			if call_type_arg_ids:
				struct_id = ctx.type_table.ensure_struct_template(struct_base, call_type_arg_ids) if any(ctx.type_table.has_typevar(t) for t in call_type_arg_ids) else ctx.type_table.ensure_struct_instantiated(struct_base, call_type_arg_ids)
			arg_exprs = list(expr.args)
			arg_types = [type_expr(a, used_as_value=False) for a in arg_exprs]
			if kw_pairs and not arg_exprs:
				arg_types = list(kw_value_types)
			ctor_res = resolve_struct_ctor(_make_resolver_ctx(ctx, diagnostics=diagnostics, current_module_name=current_module_name, default_package=default_package, module_packages=module_packages, type_param_map=type_param_map, tc_diag=_tc_diag, fixed_width_allowed=_fixed_width_allowed, reject_zst_array=_reject_zst_array, pretty_type_name=_pretty_type_name, format_ctor_signature_list=_format_ctor_signature_list, instantiate_sig=_instantiate_sig, enforce_struct_requires=_enforce_struct_requires, ensure_field_visible=_ensure_field_visible, visible_modules_for_free_call=_visible_modules_for_free_call, module_ids_by_name=module_ids_by_name, visibility_provenance=visibility_provenance, infer=_infer, format_infer_failure=_format_infer_failure, lambda_can_throw=_lambda_can_throw), struct_id=struct_id, struct_name=expr.fn.name, arg_exprs=list(arg_exprs), arg_types=arg_types, kw_pairs=kw_pairs, expected_type=expected_type, type_arg_ids=call_type_arg_ids, allow_infer=True, call_type_args_span=call_type_args_span, span=getattr(expr, "loc", Span()))
			if ctor_res is not None:
				expr.args = list(ctor_res.ctor_args)
				expr.kwargs = []
				expr.ctor_arg_field_indices = list(ctor_res.ctor_arg_field_indices)
				record_call_info(expr, param_types=list(ctor_res.inst_params), return_type=ctor_res.inst_return, can_throw=False, target=CallTarget.constructor_struct(ctor_res.inst_return, ctor_arg_field_indices=tuple(ctor_res.ctor_arg_field_indices)))
				return record_expr(expr, ctor_res.inst_return)
		def _resolve_free_call_with_require_local(*, name: str, module_name: str | None, arg_types: list[TypeId], call_type_args: list[TypeId] | None = None, call_type_args_span: Span | None = None, expected_type: TypeId | None = None) -> tuple[CallableDecl, CallableSignature, Subst | None, ResolutionError | None]:
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
			def _pick_most_specific_items(items: list[tuple], key_fn, require_info: dict[object, tuple[parser_ast.TraitExpr, dict[object, object], str, dict[TypeParamId, tuple[str, int]]]]) -> list[tuple]:
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
						formula = require_env_local.normalized(req_expr, subst=subst, default_module=def_mod, param_scope_map=scope_map)
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
			if callable_registry is None:
				raise ResolutionError(f"no matching overload for function '{name}' with args {arg_types}")
			include_private = current_module if module_name is None else None
			candidates = callable_registry.get_free_candidates(name=name, visible_modules=_visible_modules_for_free_call(module_name), include_private_in=include_private)
			viable: list[tuple[CallableDecl, CallableSignature, Subst | None]] = []
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
						viable.append((decl, CallableSignature(param_types=tuple(params), result_type=result_type), None))
					continue
				if sig.param_type_ids is None and sig.param_types is not None:
					local_type_params = {p.name: p.id for p in sig.type_params}
					param_type_ids = [resolve_opaque_type(p, ctx.type_table, module_id=sig.module, type_params=local_type_params) for p in sig.param_types]
					sig = replace(sig, param_type_ids=param_type_ids)
				if sig.return_type_id is None and sig.return_type is not None:
					local_type_params = {p.name: p.id for p in sig.type_params}
					ret_id = resolve_opaque_type(sig.return_type, ctx.type_table, module_id=sig.module, type_params=local_type_params)
					sig = replace(sig, return_type_id=ret_id)
				if sig.param_type_ids is None or sig.return_type_id is None:
					continue
				inst_arg_types = _coerce_args_for_params(list(sig.param_type_ids), arg_types)
				inst_res = _instantiate_sig_with_subst(sig=sig, arg_types=inst_arg_types, expected_type=expected_type, explicit_type_args=call_type_args, allow_infer=True, diag_span=call_type_args_span, call_kind="free", call_name=name)
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
					viable.append((decl, CallableSignature(param_types=tuple(params), result_type=result_type), inst_subst))
			if not viable:
				if call_type_args:
					if type_arg_counts:
						exp = ", ".join(str(n) for n in sorted(type_arg_counts))
						raise ResolutionError(f"type argument count mismatch for '{name}': expected one of ({exp}), got {len(call_type_args)}", span=call_type_args_span)
					if saw_typed_nongeneric_with_type_args:
						raise ResolutionError(f"type arguments require a generic signature for function '{name}'", span=call_type_args_span)
					if saw_registry_only_with_type_args:
						raise ResolutionError(f"type arguments require a typed signature for function '{name}'", span=call_type_args_span)
					raise ResolutionError(f"no matching overload for function '{name}' with provided type arguments")
				if saw_infer_incomplete and infer_failures:
					failure = infer_failures[0]
					ctx_fail = failure.context or InferContext(call_kind="free", call_name=name, span=call_type_args_span or Span(), type_param_ids=[], type_param_names={}, param_types=[], param_names=None, return_type=None, arg_types=[])
					msg, notes = _format_infer_failure(ctx_fail, failure)
					raise ResolutionError(msg, span=call_type_args_span, notes=notes)
				if saw_infer_incomplete:
					ctx_fail = InferContext(call_kind="free", call_name=name, span=call_type_args_span or Span(), type_param_ids=[], type_param_names={}, param_types=[], param_names=None, return_type=None, arg_types=[])
					res = InferResult(ok=False, subst=None, inst_params=None, inst_return=None, error=InferError(kind=InferErrorKind.CANNOT_INFER), context=ctx_fail)
					msg, notes = _format_infer_failure(ctx_fail, res)
					raise ResolutionError(msg, span=call_type_args_span, notes=notes)
				raise ResolutionError(f"no matching overload for function '{name}' with args {arg_types}")
			world = None
			applicable: list[tuple[CallableDecl, CallableSignature, Subst | None]] = []
			require_rejected: list[tuple[CallableDecl, CallableSignature, Subst | None]] = []
			require_info: dict[object, tuple[parser_ast.TraitExpr, dict[object, object], str, dict[TypeParamId, tuple[str, int]]]] = {}
			require_failures: list[ProofFailure] = []
			for decl, sig_inst, inst_subst in viable:
				cand_key = decl.fn_id if decl.fn_id is not None else ("callable", decl.callable_id)
				fn_id_local = decl.fn_id
				if fn_id_local is None:
					applicable.append((decl, sig_inst, inst_subst))
					continue
				world = global_trait_world or visible_trait_world
				req = _require_for_fn(fn_id_local)
				if req is None:
					applicable.append((decl, sig_inst, inst_subst))
					continue
				subjects: set[object] = set()
				_collect_trait_subjects(req, subjects)
				subst: dict[object, object] = {}
				sig_local = signatures_by_id.get(decl.fn_id) if decl.fn_id is not None and signatures_by_id is not None else None
				if sig_local and getattr(sig_local, "type_params", None) and inst_subst is not None:
					type_params = list(getattr(sig_local, "type_params", []) or [])
					for idx, tp in enumerate(type_params):
						if tp.id in subjects or tp.name in subjects:
							if idx < len(inst_subst.args):
								key = _normalize_type_key(type_key_from_typeid(ctx.type_table, inst_subst.args[idx]))
								subst[tp.id] = key
								subst[tp.name] = key
				if sig_local and sig_local.param_names:
					for idx, pname in enumerate(sig_local.param_names):
						if pname in subst:
							continue
						if pname in subjects and idx < len(arg_types):
							key = _normalize_type_key(type_key_from_typeid(ctx.type_table, arg_types[idx]))
							subst[pname] = key
				if world is None:
					continue
				env = TraitEnv(default_module=fn_id_local.module or current_module_name, default_package=default_package, module_packages=module_packages or {}, assumed_true=set(fn_require_assumed), type_table=ctx.type_table)
				res = prove_expr(world, env, subst, req)
				if res.status is ProofStatus.PROVED:
					applicable.append((decl, sig_inst, inst_subst))
					scope_map = _param_scope_map(sig_local)
					require_info[cand_key] = (req, subst, fn_id_local.module or current_module_name, scope_map)
				else:
					saw_require_failed = True
					origin = ObligationOrigin(kind=ObligationOriginKind.CALLEE_REQUIRE, label=f"function '{name}'", span=Span.from_loc(getattr(req, "loc", None)))
					failure = _require_failure(req_expr=req, subst=subst, origin=origin, span=call_type_args_span or Span(), env=env, world=world, result=res)
					if failure is not None:
						require_failures.append(failure)
					require_rejected.append((decl, sig_inst, inst_subst))
			if not applicable:
				if saw_require_failed and require_rejected:
					require_failure_error: ResolutionError | None = None
					failure = _pick_best_failure(require_failures)
					if failure is not None:
						require_failure_error = ResolutionError(_format_failure_message(failure), code=_failure_code(failure), span=call_type_args_span, notes=ctx.requirement_notes(failure) if ctx.requirement_notes is not None else list(getattr(failure.obligation, "notes", []) or []))
					else:
						require_failure_error = ResolutionError(f"trait requirements not met for function '{name}'")
					winners = _pick_most_specific_items(require_rejected, lambda item: _candidate_key_for_decl(item[0]), require_info)
					if len(winners) != 1:
						return require_rejected[0][0], require_rejected[0][1], require_rejected[0][2], require_failure_error
					return winners[0][0], winners[0][1], winners[0][2], require_failure_error
				if saw_require_failed:
					failure = _pick_best_failure(require_failures)
					if failure is not None:
						raise ResolutionError(_format_failure_message(failure), code=_failure_code(failure), span=call_type_args_span, notes=ctx.requirement_notes(failure) if ctx.requirement_notes is not None else list(getattr(failure.obligation, "notes", []) or []))
					raise ResolutionError(f"trait requirements not met for function '{name}'")
				raise ResolutionError(f"no matching overload for function '{name}' with args {arg_types}")
			applicable = _dedupe_by_key(applicable, lambda item: _candidate_key_for_decl(item[0]))
			if len(applicable) == 1:
				return applicable[0][0], applicable[0][1], applicable[0][2], None
			winners = _pick_most_specific_items(applicable, lambda item: _candidate_key_for_decl(item[0]), require_info)
			if len(winners) != 1:
				raise ResolutionError(f"ambiguous call to function '{name}' with args {arg_types}")
			return winners[0][0], winners[0][1], winners[0][2], None
		if kw_pairs:
			first = (kw_pairs or [None])[0]
			diagnostics.append(_tc_diag(message="keyword arguments are only supported for constructors in MVP", severity="error", span=getattr(first, "loc", getattr(expr, "loc", Span()))))
			return record_expr(expr, ctx.unknown_ty)
		arg_types = [type_expr(a, used_as_value=False) for a in expr.args]
		try:
			decl, sig_inst, inst_subst, require_error = _resolve_free_call_with_require_local(name=expr.fn.name, module_name=expr.fn.module_id, arg_types=arg_types, call_type_args=call_type_arg_ids, call_type_args_span=call_type_args_span, expected_type=expected_type)
		except ResolutionError as err:
			diagnostics.append(_tc_diag(message=str(err), severity="error", span=getattr(expr, "loc", Span()), notes=list(getattr(err, "notes", []) or []), code=getattr(err, "code", None)))
			return record_expr(expr, ctx.unknown_ty)
		if require_error is not None:
			diagnostics.append(_tc_diag(message=str(require_error), severity="error", span=getattr(expr, "loc", Span()), notes=list(getattr(require_error, "notes", []) or []), code=getattr(require_error, "code", None)))
		if ctx.record_call_resolution is not None:
			ctx.record_call_resolution(expr, decl)
		if decl.fn_id is None:
			diagnostics.append(_tc_diag(message=f"internal: missing fn_id for function '{expr.fn.name}'", severity="error", span=getattr(expr, "loc", Span())))
			return record_expr(expr, ctx.unknown_ty)
		call_can_throw = True
		if signatures_by_id is not None:
			fn_sig = signatures_by_id.get(decl.fn_id)
			if fn_sig is not None and fn_sig.declared_can_throw is not None:
				call_can_throw = bool(fn_sig.declared_can_throw)
		intrinsic_kind = _intrinsic_kind_for_decl(decl, fn_sig if signatures_by_id is not None else None)
		if intrinsic_kind is not None:
			record_call_info(expr, param_types=list(sig_inst.param_types), return_type=sig_inst.result_type, can_throw=call_can_throw, target=CallTarget.intrinsic(intrinsic_kind))
			return record_expr(expr, sig_inst.result_type)
		record_call_info(expr, param_types=list(sig_inst.param_types), return_type=sig_inst.result_type, can_throw=call_can_throw, target=CallTarget.direct(decl.fn_id))
		if ctx.record_instantiation is not None and inst_subst is not None and decl.fn_id is not None:
			inst_args = tuple(inst_subst.args or [])
			if inst_args and not any(ctx.type_table.has_typevar(t) for t in inst_args):
				csid = getattr(expr, "callsite_id", None)
				ctx.record_instantiation(callsite_id=csid, target_fn_id=decl.fn_id, impl_args=tuple(), fn_args=inst_args)
		return record_expr(expr, sig_inst.result_type)

	return record_expr(expr, ctx.unknown_ty)
