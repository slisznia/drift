# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


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


class FunctionRefKind(Enum):
	WRAPPER = auto()
	IMPL = auto()
	THUNK_OK_WRAP = auto()


@dataclass(frozen=True)
class FunctionRefId:
	"""Canonical identity for a function *value* reference (wrapper vs impl)."""

	fn_id: FunctionId
	kind: FunctionRefKind
	has_wrapper: bool = False


def function_ref_symbol(ref: FunctionRefId) -> str:
	"""Return the symbol name for a function reference."""
	base = function_symbol(ref.fn_id)
	if ref.kind is FunctionRefKind.IMPL and ref.has_wrapper:
		return f"{base}__impl"
	return base


__all__ = ["FunctionId", "function_symbol", "FunctionRefId", "FunctionRefKind", "function_ref_symbol"]
