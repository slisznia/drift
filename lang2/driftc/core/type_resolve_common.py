from __future__ import annotations

"""
Shared helpers for resolving raw/builtin type shapes into TypeIds.

This centralizes the knowledge of builtin names (`Int`, `Bool`, `String`,
`Uint`, `Void`, `Error`, `Array`, `FnResult`) so resolver and checker code
stay in sync as the language evolves.
"""

from lang2.driftc.core.types_core import TypeId, TypeTable


def resolve_opaque_type(raw: object, table: TypeTable) -> TypeId:
	"""
	Map a raw type shape (TypeExpr-like, string, tuple, or TypeId) to a TypeId.

	Supported inputs:
	- TypeExpr-like objects exposing `name` and `args`.
	- Strings naming builtins (Int/Bool/String/Uint/Void/Error), Array<...>,
	  and FnResult (by name or substring).
	- Tuples encoding FnResult, e.g. ("FnResult", ok, err) or (ok, err).
	Unknown shapes return the canonical Unknown TypeId for the table.
	"""
	if raw is None:
		return table.ensure_unknown()
	if isinstance(raw, TypeId):
		return raw

	# Parser TypeExpr-like object (duck typed on name/args).
	if hasattr(raw, "name") and hasattr(raw, "args"):
		name = getattr(raw, "name")
		args = getattr(raw, "args")
		if name == "Void":
			return table.ensure_void()
		if name == "FnResult":
			ok = resolve_opaque_type(args[0] if args else None, table)
			err = resolve_opaque_type(args[1] if len(args) > 1 else table.ensure_error(), table)
			return table.new_fnresult(ok, err)
		if name == "Array":
			elem = resolve_opaque_type(args[0] if args else None, table)
			return table.new_array(elem)
		if name == "Uint":
			return table.ensure_uint()
		if name == "Int":
			return table.ensure_int()
		if name == "Bool":
			return table.ensure_bool()
		if name == "String":
			return table.ensure_string()
		if name == "Error":
			return table.ensure_error()
		return table.new_scalar(str(name))

	# String forms.
	if isinstance(raw, str):
		if raw == "Void":
			return table.ensure_void()
		if raw == "Int":
			return table.ensure_int()
		if raw == "Bool":
			return table.ensure_bool()
		if raw == "String":
			return table.ensure_string()
		if raw == "Error":
			return table.ensure_error()
		if raw == "Uint":
			return table.ensure_uint()
		if "FnResult" in raw:
			return table.new_fnresult(table.ensure_int(), table.ensure_error())
		if raw.startswith("Array<") and raw.endswith(">"):
			inner = raw[len("Array<"):-1]
			elem_ty = resolve_opaque_type(inner, table)
			return table.new_array(elem_ty)
		return table.new_scalar(raw)

	# Tuple forms used by legacy call sites.
	if isinstance(raw, tuple):
		if len(raw) >= 3 and raw[0] == "FnResult":
			ok = resolve_opaque_type(raw[1], table)
			err = resolve_opaque_type(raw[2], table)
			return table.new_fnresult(ok, err)
		if len(raw) == 2:
			ok = resolve_opaque_type(raw[0], table)
			err = resolve_opaque_type(raw[1], table)
			return table.new_fnresult(ok, err)
		return table.ensure_unknown()

	return table.ensure_unknown()


__all__ = ["resolve_opaque_type"]
