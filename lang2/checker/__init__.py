# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Minimal checker stub for lang2.

This module exists solely to give the driver a place to hang checker-provided
metadata (currently: `declared_can_throw`). It is *not* a full type checker and
should be replaced by a real implementation once the type system is wired in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable


@dataclass
class FnInfo:
	"""
	Per-function checker metadata.

	For now we only track whether the function is *declared* to throw (e.g.,
	via a FnResult return type or an explicit `throws` clause in the real
	checker). A real implementation will replace this stub and populate
	`declared_can_throw` from the type environment.
	"""
	name: str
	declared_can_throw: bool


@dataclass
class CheckedProgram:
	"""
	Container returned by the stub Checker.

	Attributes:
	  fn_infos: map of function name -> FnInfo produced by the checker
	"""
	fn_infos: Dict[str, FnInfo]


class Checker:
	"""
	Placeholder checker.

	Accepts a sequence of function declarations and an optional declared_can_throw
	map (defaults to False for all). This input is strictly a testing shim; a real
	checker will compute declared_can_throw from signatures (FnResult/throws) and
	the type system.
	"""

	def __init__(self, declared_can_throw: Dict[str, bool] | None = None) -> None:
		self._declared = declared_can_throw or {}

	def check(self, fn_decls: Iterable[str]) -> CheckedProgram:
		"""
		Produce a CheckedProgram with FnInfo for each fn name in `fn_decls`.
		"""
		fn_infos: Dict[str, FnInfo] = {}
		for name in fn_decls:
			fn_infos[name] = FnInfo(name=name, declared_can_throw=self._declared.get(name, False))
		return CheckedProgram(fn_infos=fn_infos)
