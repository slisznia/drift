# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
"""
Link-time TypeTable unification for package consumption (v0).

Goal
----
When consuming packages, we must not require identical TypeId assignment across
independently-produced artifacts. Instead, we:

1) Merge imported type definitions into the host `TypeTable` deterministically.
2) Build a `pkg_type_id -> host_type_id` mapping.
3) Remap all TypeId references in:
   - package signatures
   - package MIR nodes
   - schema tables (struct/exception/variant schemas)

This makes package consumption scale without pinning everything to a single
`type_table_fingerprint`.

Pinned rules (MVP)
------------------
- Builtins are toolchain-owned and must unify to the host builtins:
  Int/Uint/Bool/Float/String/Void/Error/DiagnosticValue/Unknown.
- Packages may import new user-defined nominal types into the host TypeTable
  as long as there are no semantic collisions.
- Collisions are hard errors:
  - same nominal identity but different schema
  - attempts to redefine builtins / reserved namespaces
- Merge is deterministic: inputs with the same content yield the same host
  TypeIds independent of package discovery order.

Notes
-----
This module operates on the *encoded* type table object stored in provisional
package payloads (`payload["type_table"]`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from lang2.driftc.core.generic_type_expr import GenericTypeExpr
from lang2.driftc.core.types_core import (
	NominalKey,
	TypeDef,
	TypeId,
	TypeKind,
	TypeTable,
	VariantArmSchema,
	VariantFieldSchema,
	VariantSchema,
)


@dataclass(frozen=True)
class DecodedTypeDef:
	kind: TypeKind
	name: str
	param_types: list[TypeId]
	module_id: str | None
	ref_mut: bool | None
	field_names: list[str] | None


@dataclass(frozen=True)
class DecodedTypeTable:
	defs: dict[TypeId, DecodedTypeDef]
	struct_schemas: dict[NominalKey, tuple[str, list[str]]]
	exception_schemas: dict[str, tuple[str, list[str]]]
	variant_schemas: dict[TypeId, VariantSchema]


def _decode_kind(name: str) -> TypeKind:
	try:
		return TypeKind[name]
	except KeyError as err:
		raise ValueError(f"unknown TypeKind '{name}' in package type table") from err


def _decode_generic_type_expr(obj: Any) -> GenericTypeExpr:
	"""
	Decode a GenericTypeExpr as encoded by `provisional_dmir_v0.encode_type_table`.
	"""
	if not isinstance(obj, dict):
		raise ValueError("invalid GenericTypeExpr encoding")
	name = obj.get("name")
	if not isinstance(name, str):
		raise ValueError("invalid GenericTypeExpr.name")
	module_id = obj.get("module_id")
	if module_id is not None and not isinstance(module_id, str):
		raise ValueError("invalid GenericTypeExpr.module_id")
	args_obj = obj.get("args")
	args: list[GenericTypeExpr] = []
	if args_obj is not None:
		if not isinstance(args_obj, list):
			raise ValueError("invalid GenericTypeExpr.args")
		args = [_decode_generic_type_expr(a) for a in args_obj]
	param_index = obj.get("param_index")
	if param_index is not None and not isinstance(param_index, int):
		raise ValueError("invalid GenericTypeExpr.param_index")
	return GenericTypeExpr(name=name, args=args, param_index=param_index, module_id=module_id)


def decode_type_table_obj(obj: Mapping[str, Any]) -> DecodedTypeTable:
	"""
	Decode a `type_table` JSON object from a package payload.
	"""
	defs_obj = obj.get("defs")
	if not isinstance(defs_obj, dict):
		raise ValueError("package type_table missing defs")
	defs: dict[TypeId, DecodedTypeDef] = {}
	for tid_s, td_obj in defs_obj.items():
		try:
			tid = int(tid_s)
		except Exception as err:
			raise ValueError("invalid TypeId key in package type_table.defs") from err
		if not isinstance(td_obj, dict):
			raise ValueError("invalid type_table.defs entry")
		kind_s = td_obj.get("kind")
		name = td_obj.get("name")
		param_types = td_obj.get("param_types")
		module_id = td_obj.get("module_id")
		ref_mut = td_obj.get("ref_mut")
		field_names = td_obj.get("field_names")
		if not isinstance(kind_s, str) or not isinstance(name, str) or not isinstance(param_types, list):
			raise ValueError("invalid type_table.defs entry fields")
		if module_id is not None and not isinstance(module_id, str):
			raise ValueError("invalid type_table.defs module_id")
		if ref_mut is not None and not isinstance(ref_mut, bool):
			raise ValueError("invalid type_table.defs ref_mut")
		if field_names is not None and not isinstance(field_names, list):
			raise ValueError("invalid type_table.defs field_names")
		defs[tid] = DecodedTypeDef(
			kind=_decode_kind(kind_s),
			name=name,
			param_types=[int(x) for x in param_types],
			module_id=module_id,
			ref_mut=ref_mut,
			field_names=[str(x) for x in field_names] if field_names is not None else None,
		)

	struct_schemas_obj = obj.get("struct_schemas")
	struct_schemas: dict[NominalKey, tuple[str, list[str]]] = {}
	if struct_schemas_obj is not None:
		if not isinstance(struct_schemas_obj, list):
			raise ValueError("invalid type_table.struct_schemas")
		for entry in struct_schemas_obj:
			if not isinstance(entry, dict):
				raise ValueError("invalid struct_schemas entry")
			module_id = entry.get("module_id")
			name = entry.get("name")
			fields = entry.get("fields")
			if not isinstance(module_id, str) or not isinstance(name, str) or not isinstance(fields, list):
				raise ValueError("invalid struct_schemas entry fields")
			if not isinstance(fields, list):
				raise ValueError("invalid struct_schemas field list")
			key = NominalKey(module_id=module_id, name=name, kind=TypeKind.STRUCT)
			struct_schemas[key] = (name, [str(x) for x in fields])

	exc_schemas_obj = obj.get("exception_schemas")
	exception_schemas: dict[str, tuple[str, list[str]]] = {}
	if exc_schemas_obj is not None:
		if not isinstance(exc_schemas_obj, dict):
			raise ValueError("invalid type_table.exception_schemas")
		for k, v in exc_schemas_obj.items():
			if not isinstance(k, str) or not isinstance(v, list) or len(v) != 2:
				raise ValueError("invalid exception_schemas entry")
			fqn = str(v[0])
			fields = v[1]
			if not isinstance(fields, list):
				raise ValueError("invalid exception_schemas field list")
			exception_schemas[k] = (fqn, [str(x) for x in fields])

	variant_schemas_obj = obj.get("variant_schemas")
	variant_schemas: dict[TypeId, VariantSchema] = {}
	if variant_schemas_obj is not None:
		if not isinstance(variant_schemas_obj, dict):
			raise ValueError("invalid type_table.variant_schemas")
		for base_id_s, schema_obj in variant_schemas_obj.items():
			base_id = int(base_id_s)
			if not isinstance(schema_obj, dict):
				raise ValueError("invalid variant schema entry")
			schema_mid = schema_obj.get("module_id")
			name = schema_obj.get("name")
			type_params = schema_obj.get("type_params")
			arms_obj = schema_obj.get("arms")
			if not isinstance(schema_mid, str) or not isinstance(name, str) or not isinstance(type_params, list) or not isinstance(arms_obj, list):
				raise ValueError("invalid variant schema fields")
			arms: list[VariantArmSchema] = []
			for arm_obj in arms_obj:
				if not isinstance(arm_obj, dict):
					raise ValueError("invalid variant arm schema")
				arm_name = arm_obj.get("name")
				fields_obj = arm_obj.get("fields")
				if not isinstance(arm_name, str) or not isinstance(fields_obj, list):
					raise ValueError("invalid variant arm schema fields")
				fields: list[VariantFieldSchema] = []
				for fobj in fields_obj:
					if not isinstance(fobj, dict):
						raise ValueError("invalid variant field schema")
					fname = fobj.get("name")
					fty = fobj.get("type_expr")
					if not isinstance(fname, str):
						raise ValueError("invalid variant field name")
					fields.append(VariantFieldSchema(name=fname, type_expr=_decode_generic_type_expr(fty)))
				arms.append(VariantArmSchema(name=arm_name, fields=fields))
			variant_schemas[base_id] = VariantSchema(module_id=schema_mid, name=name, type_params=[str(x) for x in type_params], arms=arms)

	return DecodedTypeTable(
		defs=defs,
		struct_schemas=struct_schemas,
		exception_schemas=exception_schemas,
		variant_schemas=variant_schemas,
	)


def _builtin_type_id(host: TypeTable, td: DecodedTypeDef) -> TypeId | None:
	"""
	Map a package TypeDef to a canonical host builtin TypeId if it is a builtin.
	"""
	if td.kind is TypeKind.SCALAR:
		if td.name == "Int":
			return host.ensure_int()
		if td.name == "Uint":
			return host.ensure_uint()
		if td.name == "Bool":
			return host.ensure_bool()
		if td.name == "Float":
			return host.ensure_float()
		if td.name == "String":
			return host.ensure_string()
	if td.kind is TypeKind.VOID:
		return host.ensure_void()
	if td.kind is TypeKind.ERROR and td.name == "Error":
		return host.ensure_error()
	if td.kind is TypeKind.DIAGNOSTICVALUE and td.name == "DiagnosticValue":
		return host.ensure_diagnostic_value()
	if td.kind is TypeKind.UNKNOWN and td.name == "Unknown":
		return host.ensure_unknown()
	return None


def import_type_table_and_build_typeid_map(pkg_tt_obj: Mapping[str, Any], host: TypeTable) -> dict[TypeId, TypeId]:
	"""
	Backwards-compatible single-package wrapper for the deterministic multi-linker.

	Do not add new logic here. All production behavior must live in
	`import_type_tables_and_build_typeid_maps(...)` so package type linking has a
	single source of truth.
	"""
	return import_type_tables_and_build_typeid_maps([pkg_tt_obj], host)[0]


TypeKey = tuple


def import_type_tables_and_build_typeid_maps(pkg_tt_objs: list[Mapping[str, Any]], host: TypeTable) -> list[dict[TypeId, TypeId]]:
	"""
	Two-phase, order-independent type linking for package consumption.

	Pinned determinism contract:
	- The resulting host TypeIds and per-package `TypeId -> TypeId` maps must not
	  depend on package discovery order, filesystem ordering, or `--package-root`
	  ordering.
	- Allocation is driven only by canonical type keys derived from package
	  contents (builtins, nominal identities, and structural constructors).
	"""
	pkgs = [decode_type_table_obj(obj) for obj in pkg_tt_objs]

	# Phase A: compute canonical keys for every package TypeId.
	#
	# Keys must cover all types that can appear in signatures/MIR/schemas:
	# - builtins (by kind+name),
	# - nominal types (module_id, kind, name),
	# - derived/structural types (constructor + param keys),
	# - variant instantiations (base nominal key + arg keys).
	pkg_tid_to_key: list[dict[TypeId, TypeKey]] = []
	for pkg in pkgs:
		memo: dict[TypeId, TypeKey] = {}

		def key_for_tid(tid: TypeId) -> TypeKey:
			if tid in memo:
				return memo[tid]
			td = pkg.defs.get(tid)
			if td is None:
				raise ValueError(f"unknown TypeId {tid} referenced by package type table")
			# Builtins: identified by kind+name (toolchain-owned).
			if _builtin_type_id(host, td) is not None:
				k = ("builtin", td.kind.name, td.name)
				memo[tid] = k
				return k
			# Nominal identities: (kind,module_id,name).
			mid = td.module_id or ""
			if td.kind in (TypeKind.STRUCT, TypeKind.SCALAR):
				k = ("nominal", td.kind.name, mid, td.name)
				memo[tid] = k
				return k
			if td.kind is TypeKind.VARIANT:
				base_key = ("nominal", TypeKind.VARIANT.name, mid, td.name)
				# Distinguish base vs instantiated variant types.
				if tid in pkg.variant_schemas and not td.param_types:
					memo[tid] = base_key
					return base_key
				if td.param_types:
					arg_keys = tuple(key_for_tid(x) for x in td.param_types)
					k = ("inst", base_key, arg_keys)
					memo[tid] = k
					return k
				memo[tid] = base_key
				return base_key

			# Structural / derived types.
			sub_keys = tuple(key_for_tid(x) for x in td.param_types)
			if td.kind is TypeKind.OPTIONAL:
				k = ("optional", sub_keys[0])
			elif td.kind is TypeKind.ARRAY:
				k = ("array", sub_keys[0])
			elif td.kind is TypeKind.REF:
				k = ("ref", bool(td.ref_mut), sub_keys[0])
			elif td.kind is TypeKind.FNRESULT:
				k = ("fnresult", sub_keys[0], sub_keys[1])
			elif td.kind is TypeKind.FUNCTION:
				k = ("function", td.name, sub_keys)
			else:
				k = ("kind", td.kind.name, td.name, sub_keys, bool(td.ref_mut))
			memo[tid] = k
			return k

		m: dict[TypeId, TypeKey] = {}
		for tid in pkg.defs.keys():
			m[tid] = key_for_tid(tid)
		pkg_tid_to_key.append(m)

	# Phase A: merge/validate exception schemas (keyed by canonical event fqn).
	for pkg in pkgs:
		for fqn, schema in sorted(pkg.exception_schemas.items()):
			prev = host.exception_schemas.get(fqn)
			if prev is None:
				host.exception_schemas[fqn] = schema
			elif prev != schema:
				raise ValueError(f"exception schema collision for '{fqn}'")

	# Phase A: merge/validate variant schemas by nominal identity.
	merged_variant_schemas: dict[NominalKey, VariantSchema] = {}
	for pkg in pkgs:
		for _base_id, schema in pkg.variant_schemas.items():
			key = NominalKey(module_id=schema.module_id, name=schema.name, kind=TypeKind.VARIANT)
			prev = merged_variant_schemas.get(key)
			if prev is None:
				merged_variant_schemas[key] = schema
			elif prev != schema:
				raise ValueError(f"variant schema collision for '{schema.module_id}:{schema.name}'")

	# Phase A: merge/validate struct schemas with full field typing.
	merged_struct_schemas: dict[NominalKey, tuple[list[str], list[TypeKey]]] = {}
	for pkg_idx, pkg in enumerate(pkgs):
		pkg_struct_ids: dict[NominalKey, TypeId] = {}
		for tid, td in pkg.defs.items():
			if td.kind is TypeKind.STRUCT:
				if td.module_id is None:
					raise ValueError(f"package STRUCT '{td.name}' missing module_id")
				pkg_struct_ids[NominalKey(module_id=td.module_id, name=td.name, kind=TypeKind.STRUCT)] = tid
		for key, (_n, field_names) in pkg.struct_schemas.items():
			pkg_tid = pkg_struct_ids.get(key)
			if pkg_tid is None:
				raise ValueError(f"struct schema '{key.module_id}:{key.name}' missing STRUCT TypeDef in package type table")
			pkg_def = pkg.defs[pkg_tid]
			field_type_keys = [pkg_tid_to_key[pkg_idx][x] for x in pkg_def.param_types]
			schema_key = (list(field_names), list(field_type_keys))
			prev = merged_struct_schemas.get(key)
			if prev is None:
				merged_struct_schemas[key] = schema_key
			elif prev != schema_key:
				raise ValueError(f"struct schema collision for '{key.module_id}:{key.name}'")

	# Phase B: allocate/import host TypeIds in canonical order (no discovery dependence).
	key_to_host: dict[TypeKey, TypeId] = {}

	def ensure_builtin(k: TypeKey) -> TypeId:
		_, kind_s, name = k
		kind = TypeKind[kind_s]
		if kind is TypeKind.SCALAR:
			if name == "Int":
				return host.ensure_int()
			if name == "Uint":
				return host.ensure_uint()
			if name == "Bool":
				return host.ensure_bool()
			if name == "Float":
				return host.ensure_float()
			if name == "String":
				return host.ensure_string()
		if kind is TypeKind.VOID:
			return host.ensure_void()
		if kind is TypeKind.ERROR and name == "Error":
			return host.ensure_error()
		if kind is TypeKind.DIAGNOSTICVALUE and name == "DiagnosticValue":
			return host.ensure_diagnostic_value()
		if kind is TypeKind.UNKNOWN and name == "Unknown":
			return host.ensure_unknown()
		raise ValueError(f"unsupported builtin type in package: {k!r}")

	# Declare nominal types deterministically.
	nominal_keys: list[NominalKey] = []
	nominal_keys.extend(list(merged_struct_schemas.keys()))
	nominal_keys.extend(list(merged_variant_schemas.keys()))
	for pkg in pkgs:
		for _tid, td in pkg.defs.items():
			if td.kind is TypeKind.SCALAR and _builtin_type_id(host, td) is None:
				nominal_keys.append(NominalKey(module_id=td.module_id, name=td.name, kind=TypeKind.SCALAR))
	nominal_keys = sorted(set(nominal_keys), key=lambda nk: (nk.module_id or "", nk.kind.name, nk.name))

	for nk in nominal_keys:
		mid = nk.module_id or ""
		if nk.kind is TypeKind.STRUCT:
			field_names, _field_type_keys = merged_struct_schemas[nk]
			prev = host.struct_schemas.get(nk)
			if prev is not None:
				_h_name, h_fields = prev
				if list(h_fields) != list(field_names):
					raise ValueError(f"struct field name mismatch for '{mid}:{nk.name}'")
			else:
				host.declare_struct(mid, nk.name, list(field_names))
		elif nk.kind is TypeKind.VARIANT:
			schema = merged_variant_schemas[nk]
			host_base = host.get_variant_base(module_id=schema.module_id, name=schema.name)
			if host_base is not None:
				host_schema = host.get_variant_schema(host_base)
				if host_schema is None or host_schema != schema:
					raise ValueError(f"variant schema collision for '{schema.module_id}:{schema.name}'")
			else:
				host.declare_variant(schema.module_id, schema.name, schema.type_params, schema.arms)
		elif nk.kind is TypeKind.SCALAR:
			host.ensure_named(nk.name, module_id=nk.module_id)

	# Seed nominal keys into key_to_host.
	for nk in nominal_keys:
		mid = nk.module_id or ""
		if nk.kind is TypeKind.STRUCT:
			key_to_host[("nominal", TypeKind.STRUCT.name, mid, nk.name)] = host.require_nominal(
				kind=TypeKind.STRUCT,
				module_id=mid,
				name=nk.name,
			)
		elif nk.kind is TypeKind.VARIANT:
			key_to_host[("nominal", TypeKind.VARIANT.name, mid, nk.name)] = host.require_nominal(
				kind=TypeKind.VARIANT,
				module_id=mid,
				name=nk.name,
			)
		elif nk.kind is TypeKind.SCALAR:
			key_to_host[("nominal", TypeKind.SCALAR.name, mid, nk.name)] = host.require_nominal(
				kind=TypeKind.SCALAR,
				module_id=nk.module_id,
				name=nk.name,
			)

	all_keys: set[TypeKey] = set()
	for tid_keys in pkg_tid_to_key:
		all_keys.update(tid_keys.values())

	def depth_of_key(k: TypeKey, memo: dict[TypeKey, int]) -> int:
		if k in memo:
			return memo[k]
		tag = k[0]
		if tag in ("builtin", "nominal"):
			memo[k] = 0
			return 0
		if tag == "inst":
			base_key = k[1]
			arg_keys = k[2]
			d = 1 + max([depth_of_key(base_key, memo)] + [depth_of_key(x, memo) for x in arg_keys])
			memo[k] = d
			return d
		sub: list[TypeKey] = []
		if tag == "optional":
			sub = [k[1]]
		elif tag == "array":
			sub = [k[1]]
		elif tag == "ref":
			sub = [k[2]]
		elif tag == "fnresult":
			sub = [k[1], k[2]]
		elif tag == "function":
			sub = list(k[2])
		elif tag == "kind":
			sub = list(k[3])
		d = 1 + max([depth_of_key(x, memo) for x in sub], default=0)
		memo[k] = d
		return d

	depth_memo: dict[TypeKey, int] = {}
	remaining_keys = [k for k in all_keys if k not in key_to_host]
	remaining_keys.sort(key=lambda k: (depth_of_key(k, depth_memo), k))

	for k in remaining_keys:
		tag = k[0]
		if tag == "builtin":
			key_to_host[k] = ensure_builtin(k)
		elif tag == "nominal":
			# Must have been seeded by nominal_keys.
			if k not in key_to_host:
				_kind, kind_s, mid, name = k
				key_to_host[k] = host.require_nominal(kind=TypeKind[kind_s], module_id=(mid or None), name=name)
		elif tag == "optional":
			key_to_host[k] = host.new_optional(key_to_host[k[1]])
		elif tag == "array":
			key_to_host[k] = host.new_array(key_to_host[k[1]])
		elif tag == "ref":
			is_mut = bool(k[1])
			inner = key_to_host[k[2]]
			key_to_host[k] = host.ensure_ref_mut(inner) if is_mut else host.ensure_ref(inner)
		elif tag == "fnresult":
			ok = key_to_host[k[1]]
			err = key_to_host[k[2]]
			key_to_host[k] = host.ensure_fnresult(ok, err)
		elif tag == "function":
			name = str(k[1])
			pts = [key_to_host[x] for x in k[2]]
			if not pts:
				raise ValueError("invalid function type key (no return type)")
			key_to_host[k] = host.new_function(name, pts[:-1], pts[-1])
		elif tag == "inst":
			base_tid = key_to_host[k[1]]
			args = [key_to_host[x] for x in list(k[2])]
			key_to_host[k] = host.ensure_instantiated(base_tid, args)
		else:
			raise ValueError(f"unsupported type key in package linker: {k!r}")

	# Finalize struct field types deterministically (names + types).
	for nk in sorted(merged_struct_schemas.keys(), key=lambda k: (k.module_id or "", k.name)):
		mid = nk.module_id or ""
		host_tid = host.require_nominal(kind=TypeKind.STRUCT, module_id=mid, name=nk.name)
		h_td = host.get(host_tid)
		if h_td.kind is not TypeKind.STRUCT:
			raise ValueError(f"expected STRUCT for '{mid}:{nk.name}' after import")
		field_names, field_type_keys = merged_struct_schemas[nk]
		field_types = [key_to_host[k] for k in field_type_keys]
		# If host struct already had field types defined, require exact match.
		if any(t != host.ensure_unknown() for t in h_td.param_types):
			if list(h_td.param_types) != field_types:
				raise ValueError(f"struct field type mismatch for '{mid}:{nk.name}'")
		else:
			host.define_struct_fields(host_tid, field_types)

	# Ensure non-generic variants have concrete instances available.
	host.finalize_variants()

	# Phase C: per-package tid maps.
	out_maps: list[dict[TypeId, TypeId]] = []
	for tid_keys in pkg_tid_to_key:
		m: dict[TypeId, TypeId] = {}
		for tid, k in tid_keys.items():
			host_tid = key_to_host.get(k)
			if host_tid is None:
				raise ValueError(f"failed to map package TypeId {tid} to host TypeId (key {k!r})")
			m[tid] = host_tid
		out_maps.append(m)
	return out_maps
