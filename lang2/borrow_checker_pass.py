#!/usr/bin/env python3
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-09
"""
Minimal borrow-check pass (Phase 1): track moves per Place and report
use-after-move and move-from-val diagnostics on typed HIR.

Scope:
- Builds place_state per function (UNINIT/VALID/MOVED).
- Handles implicit moves for non-Copy values used by value.
- Leaves borrowing/loans/regions for later phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Mapping, Callable

from lang2 import stage1 as H
from lang2.borrow_checker import Place, PlaceBase, PlaceKind, PlaceState, place_from_expr
from lang2.core.diagnostics import Diagnostic
from lang2.core.types_core import TypeKind, TypeTable, TypeId


@dataclass
class BorrowChecker:
	"""
	Phase-1 borrow checker: move tracking on typed HIR.

	Inputs:
	- type_table: to answer Copy vs move-only.
	- fn_types: mapping var names to TypeId (params/locals as available).
	"""

	type_table: TypeTable
	fn_types: Mapping[str, TypeId]
	base_lookup: Callable[[str], Optional[PlaceBase]] = lambda n: PlaceBase(PlaceKind.LOCAL, -1, n)
	place_state: Dict[Place, PlaceState] = field(default_factory=dict)
	diagnostics: List[Diagnostic] = field(default_factory=list)

	def _is_copy(self, ty: Optional[TypeId]) -> bool:
		if ty is None:
			return False
		td = self.type_table.get(ty)
		# Conservatively treat scalars and unknowns as Copy; structs/arrays default to move-only.
		return td.kind is TypeKind.SCALAR

	def _state_for(self, place: Place) -> PlaceState:
		return self.place_state.get(place, PlaceState.UNINIT)

	def _set_state(self, place: Place, state: PlaceState) -> None:
		self.place_state[place] = state

	def _diagnostic(self, message: str) -> None:
		self.diagnostics.append(Diagnostic(message=message, severity="error", span=None))

	def _record_move(self, place: Place) -> None:
		state = self._state_for(place)
		if state is PlaceState.MOVED:
			self._diagnostic(f"use after move of '{place.base}'")
			return
		self._set_state(place, PlaceState.MOVED)

	def _record_assign(self, place: Place) -> None:
		# Assignment initializes/overwrites, making the place valid again.
		self._set_state(place, PlaceState.VALID)

	def _check_use(self, place: Place) -> None:
		state = self._state_for(place)
		if state is PlaceState.MOVED:
			self._diagnostic(f"use after move of '{place.base}'")

	def _maybe_move_expr(self, expr: H.HExpr) -> None:
		"""
		Implicit move: consuming a non-Copy lvalue by value.
		"""
		place = place_from_expr(expr)
		if place is None:
			return
		ty = self.fn_types.get(place.base)
		if self._is_copy(ty):
			return
		self._record_move(place)

	def check_block(self, block: H.HBlock) -> List[Diagnostic]:
		for stmt in block.statements:
			self._check_stmt(stmt)
		return self.diagnostics

	def _consume_expr(self, expr: H.HExpr) -> None:
		"""
		Consume an expression in value position:
		- If it's an lvalue of non-Copy type, this is a move (record it).
		- If it's an lvalue already moved, flag use-after-move.
		- Rvalues are ignored for move tracking.
		"""
		place = place_from_expr(expr, base_lookup=self.base_lookup)
		if place is None:
			return
		state = self._state_for(place)
		if state is PlaceState.MOVED:
			self._diagnostic(f"use after move of '{place.base.name}'")
			return
		ty = self.fn_types.get(place.base.name)
		if self._is_copy(ty):
			return
		self._record_move(place)

	def _check_stmt(self, stmt: H.HStmt) -> None:
		if isinstance(stmt, H.HLet):
			self._consume_expr(stmt.value)
			base = self.base_lookup(stmt.name)
			if base is None:
				return
			place = Place(base)
			self._record_assign(place)
		elif isinstance(stmt, H.HAssign):
			self._consume_expr(stmt.value)
			tgt = place_from_expr(stmt.target, base_lookup=self.base_lookup)
			if tgt is not None:
				self._record_assign(tgt)
			else:
				self._diagnostic("assignment target is not an lvalue")
		elif isinstance(stmt, H.HReturn):
			if stmt.value is not None:
				self._consume_expr(stmt.value)
		elif isinstance(stmt, H.HExprStmt):
			self._consume_expr(stmt.expr)
		elif isinstance(stmt, H.HIf):
			self._consume_expr(stmt.cond)
			self._check_block(stmt.then_block)
			if stmt.else_block:
				self._check_block(stmt.else_block)
		elif isinstance(stmt, H.HLoop):
			self._check_block(stmt.body)
		elif isinstance(stmt, H.HTry):
			self._check_block(stmt.body)
			for arm in stmt.catches:
				self._check_block(arm.block)
		elif isinstance(stmt, H.HThrow):
			self._consume_expr(stmt.value)
		# other stmts: continue

	def _check_block(self, block: H.HBlock) -> None:
		for st in block.statements:
			self._check_stmt(st)
