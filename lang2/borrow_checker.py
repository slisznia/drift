#!/usr/bin/env python3
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-09
"""
Borrow-checker scaffolding: place representation and basic lvalue detection.

This models the "where" of values (locals + projections) so later passes can
track moves/borrows per place. It intentionally avoids policy (no diagnostics
or CFG yet) and just answers:
  * Is this HIR expression an lvalue (borrowable/moveable place)?
  * If so, what place does it identify?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Tuple, Optional

from lang2 import stage1 as H


class IndexKind(Enum):
	"""Coarse-grained index classification to keep Place hashable."""

	ANY = auto()       # Unknown / non-constant index; conservatively overlaps.
	CONST = auto()     # Known constant index.


@dataclass(frozen=True)
class FieldProj:
	"""Field access projection (e.g., `.name`)."""

	name: str


@dataclass(frozen=True)
class IndexProj:
	"""
	Index projection (e.g., `[i]`).

	Hashability: we classify indices instead of storing raw HIR to keep Place
	hashable. `value` is only set for CONST indices.
	"""

	kind: IndexKind
	value: Optional[int] = None


Projection = FieldProj | IndexProj


@dataclass(frozen=True)
class Place:
	"""
	A borrowable/moveable storage location.

	`base` is typically a local/param name. `projections` capture field/index
	accesses, so `foo.bar[0]` becomes base `foo` with projections `.bar`, `[0]`.
	"""

	base: str
	projections: Tuple[Projection, ...] = field(default_factory=tuple)

	def with_projection(self, proj: Projection) -> "Place":
		"""Return a new Place with an additional projection appended."""
		return Place(self.base, self.projections + (proj,))


def is_lvalue(expr: H.HExpr) -> bool:
	"""
	Decide if a HIR expression denotes a storage location (`Place`) per spec:
	- Locals/params (`HVar`) are lvalues.
	- Field/index access of an lvalue is an lvalue.
	- Everything else is an rvalue (temporaries, literals, calls, binops, etc.).
	"""
	return place_from_expr(expr) is not None


def place_from_expr(expr: H.HExpr) -> Optional[Place]:
	"""
	Construct a `Place` from a HIR expression when the expression is an lvalue.

	Returns None for rvalues.
	"""
	if isinstance(expr, H.HVar):
		return Place(expr.name)
	if isinstance(expr, H.HField):
		base = place_from_expr(expr.subject)
		if base is None:
			return None
		return base.with_projection(FieldProj(expr.name))
	if isinstance(expr, H.HIndex):
		base = place_from_expr(expr.subject)
		if base is None:
			return None
		const_val: Optional[int] = None
		if isinstance(expr.index, H.HLiteralInt):
			try:
				const_val = int(expr.index.value)
			except Exception:
				const_val = None
		kind = IndexKind.CONST if const_val is not None else IndexKind.ANY
		return base.with_projection(IndexProj(kind=kind, value=const_val))
	# Other expressions are rvalues: calls, literals, binops, method calls, etc.
	return None
