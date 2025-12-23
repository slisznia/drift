# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FunctionId:
	"""
Stable identity for a function definition within a module.

`ordinal` is the declaration order within the module after merge.
"""

	module: str
	name: str
	ordinal: int


def function_symbol(fn_id: FunctionId) -> str:
	"""Return a stable, unique symbol name for the function."""
	if fn_id.module == "main":
		base = fn_id.name
	else:
		base = f"{fn_id.module}::{fn_id.name}"
	if fn_id.ordinal == 0:
		return base
	return f"{base}#{fn_id.ordinal}"


__all__ = ["FunctionId", "function_symbol"]
