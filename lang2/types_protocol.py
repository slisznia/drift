# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Minimal type-environment protocol for future type-aware checks.

Stage4 throw checks will eventually use this to assert that return values in
can-throw functions are real `FnResult<_, Error>` values. For now it is a stub;
the real checker/type system will provide a concrete implementation.
"""

from __future__ import annotations

from typing import Protocol


class TypeEnv(Protocol):
	"""Protocol for querying SSA value types (placeholder until real type env exists)."""

	def type_of_ssa_value(self, func_name: str, value_id: str) -> object:
		"""Return the type of the given SSA value in the named function."""
		...
