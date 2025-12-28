# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
"""
Provisional DMIR payload (v0).

This is an intentionally unstable, compiler-internal IR encoding used for
package artifacts.

Goals:
- deterministic JSON encoding (stable keys, stable ordering),
- sufficiently rich to reconstruct the current stage2 MIR for all functions in a
  module (and the TypeTable required to lower MIR to LLVM later),
- explicit versioning so we can replace this with real DMIR without rewriting
  the package container format.
"""

from __future__ import annotations

import dataclasses
import struct
from enum import Enum
from typing import Any, Mapping

from lang2.driftc.checker import FnSignature
from lang2.driftc.core.generic_type_expr import GenericTypeExpr
from lang2.driftc.core.span import Span
from lang2.driftc.core.types_core import TypeDef, TypeId, TypeParamId, TypeTable
from lang2.driftc.parser import ast as parser_ast
from lang2.driftc.packages.dmir_pkg_v0 import canonical_json_bytes, sha256_hex


def _float64_bits_hex(value: float) -> str:
	"""Encode a Python float as IEEE754 bits for deterministic JSON."""
	bits = struct.unpack("<Q", struct.pack("<d", value))[0]
	return f"0x{bits:016x}"


def _to_jsonable(obj: Any) -> Any:
	"""
	Convert an arbitrary compiler object into JSONable structures.

	Rules:
	- dataclasses become dicts with a `_type` discriminator,
	- Enums are encoded by `name`,
	- floats are encoded by their IEEE754 bits (hex string),
	- dict keys are converted to strings (and callers must sort when serializing).
	"""
	if obj is None or isinstance(obj, (bool, int, str)):
		return obj
	if isinstance(obj, float):
		return {"_float64": _float64_bits_hex(obj)}
	if isinstance(obj, Enum):
		return {"_enum": type(obj).__name__, "name": obj.name}
	if dataclasses.is_dataclass(obj):
		out: dict[str, Any] = {"_type": type(obj).__name__}
		for f in dataclasses.fields(obj):
			out[f.name] = _to_jsonable(getattr(obj, f.name))
		return out
	if isinstance(obj, (list, tuple)):
		return [_to_jsonable(x) for x in obj]
	if isinstance(obj, dict):
		return {str(k): _to_jsonable(v) for k, v in obj.items()}
	return {"_unsupported": type(obj).__name__, "repr": repr(obj)}


def _float64_from_bits_hex(text: str) -> float:
	"""Decode a float encoded by `_float64_bits_hex`."""
	if text.startswith("0x"):
		text = text[2:]
	bits = int(text, 16)
	return struct.unpack("<d", struct.pack("<Q", bits))[0]


def build_dataclass_registry(*modules: Any) -> dict[str, type]:
	"""
	Build a dataclass name -> class registry.

	This is used to reconstruct stage2 MIR nodes and other internal dataclasses from
	the provisional JSON encoding.
	"""
	out: dict[str, type] = {}
	for mod in modules:
		for v in vars(mod).values():
			if dataclasses.is_dataclass(v):
				out[v.__name__] = v
	return out


def build_enum_registry(*modules: Any) -> dict[str, type[Enum]]:
	"""Build an Enum name -> class registry."""
	out: dict[str, type[Enum]] = {}
	for mod in modules:
		for v in vars(mod).values():
			if isinstance(v, type) and issubclass(v, Enum):
				out[v.__name__] = v
	return out


def from_jsonable(obj: Any, *, dataclasses_by_name: Mapping[str, type], enums_by_name: Mapping[str, type[Enum]]) -> Any:
	"""Reconstruct Python objects encoded by `_to_jsonable`."""
	if obj is None or isinstance(obj, (bool, int, str)):
		return obj
	if isinstance(obj, list):
		return [from_jsonable(x, dataclasses_by_name=dataclasses_by_name, enums_by_name=enums_by_name) for x in obj]
	if isinstance(obj, dict):
		if "_float64" in obj:
			return _float64_from_bits_hex(str(obj["_float64"]))
		if "_enum" in obj:
			enum_name = str(obj.get("_enum"))
			member_name = str(obj.get("name"))
			cls = enums_by_name.get(enum_name)
			if cls is None:
				raise ValueError(f"unknown enum '{enum_name}' in provisional payload")
			return cls[member_name]
		if "_type" in obj:
			type_name = str(obj.get("_type"))
			cls = dataclasses_by_name.get(type_name)
			if cls is None:
				raise ValueError(f"unknown dataclass '{type_name}' in provisional payload")
			kwargs: dict[str, Any] = {}
			for f in dataclasses.fields(cls):
				if f.name in obj:
					kwargs[f.name] = from_jsonable(obj[f.name], dataclasses_by_name=dataclasses_by_name, enums_by_name=enums_by_name)
			return cls(**kwargs)  # type: ignore[misc]
		return {str(k): from_jsonable(v, dataclasses_by_name=dataclasses_by_name, enums_by_name=enums_by_name) for k, v in obj.items()}
	return obj


_BUILTIN_TYPE_NAMES = {
	"Int",
	"Uint",
	"Bool",
	"Float",
	"String",
	"Void",
	"Error",
	"DiagnosticValue",
	"Array",
	"Optional",
	"FnResult",
	"&",
	"&mut",
}


def encode_span(span: Span | None) -> dict[str, Any] | None:
	if span is None:
		return None
	if not isinstance(span, Span):
		span = Span.from_loc(span)
	if span.file is None and span.line is None and span.column is None and span.end_line is None and span.end_column is None:
		return None
	return {
		"file": span.file,
		"line": span.line,
		"column": span.column,
		"end_line": span.end_line,
		"end_column": span.end_column,
	}


def decode_span(obj: Any) -> Span | None:
	if not isinstance(obj, dict):
		return None
	file = obj.get("file")
	line = obj.get("line")
	column = obj.get("column")
	end_line = obj.get("end_line")
	end_column = obj.get("end_column")
	if file is not None and not isinstance(file, str):
		return None
	if line is not None and not isinstance(line, int):
		return None
	if column is not None and not isinstance(column, int):
		return None
	if end_line is not None and not isinstance(end_line, int):
		return None
	if end_column is not None and not isinstance(end_column, int):
		return None
	return Span(file=file, line=line, column=column, end_line=end_line, end_column=end_column)


def encode_type_expr(
	expr: parser_ast.TypeExpr | None,
	*,
	default_module: str | None,
	type_param_names: set[str] | None = None,
) -> dict[str, Any] | None:
	if expr is None:
		return None
	name = getattr(expr, "name", None)
	if not isinstance(name, str) or not name:
		return None
	if name == "Self" or (type_param_names and name in type_param_names):
		return {"param": name}
	module_id = getattr(expr, "module_id", None)
	if module_id is None and default_module and name not in _BUILTIN_TYPE_NAMES:
		module_id = default_module
	args_obj = []
	for arg in list(getattr(expr, "args", []) or []):
		args_obj.append(
			encode_type_expr(
				arg,
				default_module=default_module,
				type_param_names=type_param_names,
			)
		)
	out: dict[str, Any] = {"name": name}
	if module_id:
		out["module"] = module_id
	if name == "fn":
		out["can_throw"] = bool(expr.can_throw())
	if args_obj:
		out["args"] = args_obj
	return out


def decode_type_expr(obj: Any) -> parser_ast.TypeExpr | None:
	if obj is None:
		return None
	if not isinstance(obj, dict):
		return None
	if "param" in obj:
		name = obj.get("param")
		if not isinstance(name, str) or not name:
			return None
		return parser_ast.TypeExpr(name=name, args=[], module_alias=None, module_id=None, loc=None)
	name = obj.get("name")
	if not isinstance(name, str) or not name:
		return None
	module_id = obj.get("module")
	if module_id is not None and not isinstance(module_id, str):
		return None
	args: list[parser_ast.TypeExpr] = []
	raw_args = obj.get("args")
	if raw_args is not None:
		if not isinstance(raw_args, list):
			return None
		for raw in raw_args:
			arg = decode_type_expr(raw)
			if arg is None:
				return None
			args.append(arg)
	fn_throws = False
	if name == "fn":
		if "can_throw" in obj:
			can_throw = obj.get("can_throw")
			if can_throw is None or not isinstance(can_throw, bool):
				return None
			fn_throws = bool(can_throw)
		else:
			fn_throws = True
	return parser_ast.TypeExpr(
		name=name,
		args=args,
		fn_throws=fn_throws,
		module_alias=None,
		module_id=module_id,
		loc=None,
	)


def encode_trait_expr(
	expr: parser_ast.TraitExpr | None,
	*,
	default_module: str | None,
	type_param_names: list[str] | None = None,
) -> dict[str, Any] | None:
	if expr is None:
		return None
	if isinstance(expr, parser_ast.TraitIs):
		subject = expr.subject
		if isinstance(subject, TypeParamId) and type_param_names is not None:
			idx = int(subject.index)
			if 0 <= idx < len(type_param_names):
				subject = type_param_names[idx]
		if not isinstance(subject, str):
			subject = str(subject)
		return {
			"kind": "is",
			"subject": subject,
			"trait": encode_type_expr(expr.trait, default_module=default_module, type_param_names=set(type_param_names or [])),
		}
	if isinstance(expr, parser_ast.TraitAnd):
		return {
			"kind": "and",
			"left": encode_trait_expr(expr.left, default_module=default_module, type_param_names=type_param_names),
			"right": encode_trait_expr(expr.right, default_module=default_module, type_param_names=type_param_names),
		}
	if isinstance(expr, parser_ast.TraitOr):
		return {
			"kind": "or",
			"left": encode_trait_expr(expr.left, default_module=default_module, type_param_names=type_param_names),
			"right": encode_trait_expr(expr.right, default_module=default_module, type_param_names=type_param_names),
		}
	if isinstance(expr, parser_ast.TraitNot):
		return {
			"kind": "not",
			"expr": encode_trait_expr(expr.expr, default_module=default_module, type_param_names=type_param_names),
		}
	return None


def decode_trait_expr(obj: Any) -> parser_ast.TraitExpr | None:
	if obj is None:
		return None
	if not isinstance(obj, dict):
		return None
	kind = obj.get("kind")
	if kind == "is":
		subject = obj.get("subject")
		if not isinstance(subject, str) or not subject:
			return None
		trait_obj = obj.get("trait")
		trait = decode_type_expr(trait_obj)
		if trait is None:
			return None
		return parser_ast.TraitIs(loc=None, subject=subject, trait=trait)
	if kind == "and":
		left = decode_trait_expr(obj.get("left"))
		right = decode_trait_expr(obj.get("right"))
		if left is None or right is None:
			return None
		return parser_ast.TraitAnd(loc=None, left=left, right=right)
	if kind == "or":
		left = decode_trait_expr(obj.get("left"))
		right = decode_trait_expr(obj.get("right"))
		if left is None or right is None:
			return None
		return parser_ast.TraitOr(loc=None, left=left, right=right)
	if kind == "not":
		inner = decode_trait_expr(obj.get("expr"))
		if inner is None:
			return None
		return parser_ast.TraitNot(loc=None, expr=inner)
	return None


def encode_type_table(table: TypeTable) -> dict[str, Any]:
	"""Encode the TypeTable deterministically."""

	def _def_to_obj(td: TypeDef) -> dict[str, Any]:
		return {
			"kind": td.kind.name,
			"name": td.name,
			"param_types": list(td.param_types),
			"module_id": td.module_id,
			"ref_mut": td.ref_mut,
			"fn_throws": td.fn_throws_raw(),
			"field_names": list(td.field_names) if td.field_names is not None else None,
		}

	def _encode_generic_type_expr(expr: GenericTypeExpr) -> dict[str, Any]:
		return {
			"name": expr.name,
			"args": [_encode_generic_type_expr(a) for a in expr.args],
			"param_index": expr.param_index,
			"module_id": expr.module_id,
			"fn_throws": expr.fn_throws_raw(),
		}

	def _encode_variant_schema(schema: Any) -> dict[str, Any]:
		# `VariantSchema` / `VariantArmSchema` / `VariantFieldSchema` are dataclasses,
		# but we encode them manually so the payload stays stable even if we later
		# refactor internal Python class names.
		return {
			"module_id": schema.module_id,
			"name": schema.name,
			"type_params": list(schema.type_params),
			"arms": [
				{
					"name": arm.name,
					"fields": [{"name": f.name, "type_expr": _encode_generic_type_expr(f.type_expr)} for f in arm.fields],
				}
				for arm in schema.arms
			],
		}

	defs: dict[str, Any] = {}
	for tid in sorted(table._defs.keys()):  # type: ignore[attr-defined]
		defs[str(tid)] = _def_to_obj(table._defs[tid])  # type: ignore[attr-defined]
	variant_schemas: dict[str, Any] = {}
	for base_id in sorted(table.variant_schemas.keys()):
		variant_schemas[str(base_id)] = _encode_variant_schema(table.variant_schemas[base_id])
	return {
		"defs": defs,
		"struct_schemas": [
			{
				"module_id": key.module_id,
				"name": key.name,
				"fields": list(fields),
			}
			for key, (_n, fields) in sorted(
				table.struct_schemas.items(),
				key=lambda kv: ((kv[0].module_id or ""), kv[0].name),
			)
		],
		"exception_schemas": {k: v for k, v in sorted(table.exception_schemas.items())},
		"variant_schemas": variant_schemas,
	}


def type_table_fingerprint(table_obj: Mapping[str, Any]) -> str:
	"""
	Hash a TypeTable JSON object deterministically.

	This is a compatibility guardrail for package consumption: packages produced
	independently must have matching fingerprints, otherwise their TypeIds are not
	comparable and embedding IR would be unsafe.
	"""
	return sha256_hex(canonical_json_bytes(dict(table_obj)))


def encode_signatures(signatures: Mapping[str, FnSignature], *, module_id: str) -> dict[str, Any]:
	"""Encode module-local signatures (deterministic ordering)."""
	out: dict[str, Any] = {}
	for name in sorted(signatures.keys()):
		sig = signatures[name]
		if getattr(sig, "module", None) not in (module_id, None):
			continue
		sig_module = getattr(sig, "module", None) or module_id
		type_param_names = [p.name for p in getattr(sig, "type_params", []) or []]
		impl_type_param_names = [p.name for p in getattr(sig, "impl_type_params", []) or []]
		type_param_name_set = set(type_param_names) | set(impl_type_param_names)
		param_types_obj = None
		if sig.param_types is not None:
			param_types_obj = [
				encode_type_expr(p, default_module=sig_module, type_param_names=type_param_name_set)
				for p in list(sig.param_types)
			]
		return_type_obj = None
		if sig.return_type is not None:
			return_type_obj = encode_type_expr(
				sig.return_type,
				default_module=sig_module,
				type_param_names=type_param_name_set,
			)
		out[name] = {
			"name": sig.name,
			"module": sig_module,
			"is_method": sig.is_method,
			"method_name": getattr(sig, "method_name", None),
			"impl_target_type_id": getattr(sig, "impl_target_type_id", None),
			"self_mode": getattr(sig, "self_mode", None),
			"is_pub": bool(getattr(sig, "is_pub", False)),
			"param_names": list(sig.param_names or []),
			"param_type_ids": list(sig.param_type_ids or []) if sig.param_type_ids is not None else None,
			"return_type_id": sig.return_type_id,
			"is_exported_entrypoint": bool(getattr(sig, "is_exported_entrypoint", False)),
			"type_params": type_param_names,
			"impl_type_params": impl_type_param_names,
			"param_types": param_types_obj,
			"return_type": return_type_obj,
		}
	return out


def encode_module_payload_v0(
	*,
	module_id: str,
	type_table: TypeTable,
	signatures: Mapping[str, FnSignature],
	mir_funcs: Mapping[str, Any],
	exported_values: list[str],
	exported_types: dict[str, list[str]],
	exported_traits: list[str] | None = None,
	exported_consts: list[str] | None = None,
	reexports: dict[str, Any] | None = None,
	trait_metadata: list[dict[str, Any]] | None = None,
	impl_headers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
	"""Build the provisional payload object (not yet canonical-JSON encoded)."""
	tt_obj = encode_type_table(type_table)
	consts: list[str] = list(exported_consts or [])
	const_table: dict[str, Any] = {}
	for name in consts:
		sym = f"{module_id}::{name}"
		entry = type_table.lookup_const(sym)
		if entry is None:
			raise ValueError(f"internal: exported const '{sym}' missing from TypeTable const table")
		ty_id, val = entry
		if isinstance(val, bool):
			enc_val: Any = bool(val)
		elif isinstance(val, int):
			enc_val = int(val)
		elif isinstance(val, float):
			enc_val = float(val)
		elif isinstance(val, str):
			enc_val = str(val)
		else:
			raise ValueError(f"internal: unsupported const value type for '{sym}': {type(val).__name__}")
		const_table[name] = {"type_id": int(ty_id), "value": enc_val}
	types_obj = {
		"structs": list(exported_types.get("structs", [])),
		"variants": list(exported_types.get("variants", [])),
		"exceptions": list(exported_types.get("exceptions", [])),
	}
	reexports_obj = reexports if isinstance(reexports, dict) else {}
	trait_meta_obj = list(trait_metadata or [])
	impl_headers_obj = list(impl_headers or [])
	return {
		"payload_kind": "provisional-dmir",
		"payload_version": 0,
		"unstable_format": True,
		"module_id": module_id,
		"exports": {
			"values": list(exported_values),
			"types": types_obj,
			"consts": consts,
			"traits": list(exported_traits or []),
		},
		"reexports": _to_jsonable(reexports_obj),
		"trait_metadata": _to_jsonable(trait_meta_obj),
		"impl_headers": _to_jsonable(impl_headers_obj),
		"consts": const_table,
		"type_table": tt_obj,
		"type_table_fingerprint": type_table_fingerprint(tt_obj),
		"signatures": encode_signatures(signatures, module_id=module_id),
		"mir_funcs": {name: _to_jsonable(mir_funcs[name]) for name in sorted(mir_funcs.keys())},
	}


def decode_mir_funcs(mir_funcs_obj: Mapping[str, Any]) -> dict[str, Any]:
	"""
	Decode `mir_funcs` as encoded by `encode_module_payload_v0`.

	This returns a dict of `name -> M.MirFunc` objects (stage2 dataclasses).
	"""
	from lang2.driftc.stage2 import mir_nodes as M  # local import to avoid heavy import at module init

	dc = build_dataclass_registry(M)
	enums = build_enum_registry(M)
	out: dict[str, Any] = {}
	for name, obj in mir_funcs_obj.items():
		out[str(name)] = from_jsonable(obj, dataclasses_by_name=dc, enums_by_name=enums)
	return out
