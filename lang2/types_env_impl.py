# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-05
"""
Simple testing implementation of the `TypeEnv` protocol.

This is **not** a real type system. It exists solely to let tests exercise the
type-aware FnResult checks in stage4 without pulling in a full checker/type
environment. Callers can populate it with opaque type handles (strings, tuples,
custom objects) and use the helpers to identify FnResult types.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from lang2.types_protocol import TypeEnv


class SimpleTypeEnv(TypeEnv):
	"""
	A minimal in-memory TypeEnv for tests.

	Types are opaque handles; by convention in tests we treat a FnResult type as
	a 2-tuple `(ok_type, error_type)`. Anything else is treated as a non-FnResult
	type. This keeps stage4 decoupled from concrete type representations.
	"""

	def __init__(self) -> None:
		# Map (function name, SSA value id) -> opaque type handle.
		self._types: Dict[tuple[str, str], Any] = {}

	def set_ssa_type(self, func_name: str, value_id: str, ty: Any) -> None:
		"""Install a type handle for the given SSA value (used in tests)."""
		self._types[(func_name, value_id)] = ty

	def type_of_ssa_value(self, func_name: str, value_id: str) -> Any:
		"""Return the previously stored type for `value_id` in `func_name`."""
		return self._types[(func_name, value_id)]

	def is_fnresult(self, ty: Any) -> bool:
		"""
		Treat a 2-tuple as a FnResult `(ok_type, error_type)`; everything else is
		non-FnResult. Tests can choose whatever handles they like for the inner
		types (strings, ints, sentinel objects, etc.).
		"""
		return isinstance(ty, tuple) and len(ty) == 2

	def fnresult_parts(self, ty: Any) -> Tuple[Any, Any]:
		"""Return the (ok_type, error_type) tuple for a FnResult type."""
		if not self.is_fnresult(ty):
			raise TypeError(f"fnresult_parts called on non-FnResult type {ty!r}")
		ok_ty, err_ty = ty
		return ok_ty, err_ty
