#!/usr/bin/env python3
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-09
"""
Minimal borrow-check pass (Phase 1): track moves per Place and report
use-after-move diagnostics on typed HIR.

Scope:
- Operates as a forward dataflow over a CFG derived from HIR.
- Tracks place states (UNINIT/VALID/MOVED) and flags use-after-move.
- Handles implicit moves for non-Copy values used by value.
- Leaves borrowing/loans/regions/mutability for later phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Mapping, Callable, Tuple

from lang2 import stage1 as H
from lang2.borrow_checker import Place, PlaceBase, PlaceKind, PlaceState, place_from_expr, merge_place_state
from lang2.core.diagnostics import Diagnostic
from lang2.core.types_core import TypeKind, TypeTable, TypeId


@dataclass
class Terminator:
	"""CFG terminator describing control-flow edges out of a basic block."""

	kind: str  # "jump", "branch", "return", "throw"
	targets: List[int]
	cond: Optional[H.HExpr] = None
	value: Optional[H.HExpr] = None


@dataclass
class BasicBlock:
	"""Basic block of HIR statements with a single terminator."""

	id: int
	statements: List[H.HStmt] = field(default_factory=list)
	terminator: Optional[Terminator] = None


@dataclass
class BorrowChecker:
	"""
	Phase-1 borrow checker: move tracking on typed HIR (CFG/dataflow).

	Inputs:
	- type_table: to answer Copy vs move-only.
	- fn_types: mapping var names to TypeId (params/locals as available).
	"""

	type_table: TypeTable
	fn_types: Mapping[str, TypeId]
	base_lookup: Callable[[str], Optional[PlaceBase]] = lambda n: PlaceBase(PlaceKind.LOCAL, -1, n)
	diagnostics: List[Diagnostic] = field(default_factory=list)

	def _is_copy(self, ty: Optional[TypeId]) -> bool:
		"""Return True if the type is Copy per the core type table."""
		if ty is None:
			return False
		td = self.type_table.get(ty)
		# Conservatively treat scalars as Copy; everything else (incl. Unknown) is move-only.
		return td.kind is TypeKind.SCALAR

	def _state_for(self, state: Dict[Place, PlaceState], place: Place) -> PlaceState:
		"""Lookup helper with UNINIT default for missing places."""
		return state.get(place, PlaceState.UNINIT)

	def _set_state(self, state: Dict[Place, PlaceState], place: Place, value: PlaceState) -> None:
		"""Mutate the local state map for a given place."""
		state[place] = value

	def _diagnostic(self, message: str) -> None:
		"""Append an error-level diagnostic with no span."""
		self.diagnostics.append(Diagnostic(message=message, severity="error", span=None))

	def _consume_place_use(self, state: Dict[Place, PlaceState], place: Place) -> None:
		"""Consume a place in value position, marking moves and flagging use-after-move."""
		curr = self._state_for(state, place)
		if curr is PlaceState.MOVED:
			self._diagnostic(f"use after move of '{place.base.name}'")
			return
		ty = self.fn_types.get(place.base.name)
		if self._is_copy(ty):
			return
		self._set_state(state, place, PlaceState.MOVED)

	def _visit_expr(self, state: Dict[Place, PlaceState], expr: H.HExpr, *, as_value: bool = True) -> None:
		"""
		Traverse expressions and consume moves for lvalues in value position.

		This is the single place to extend when new HIR forms appear (e.g.,
		dereference or pattern matching). The walker must visit all
		subexpressions so that moves through calls, arithmetic, literals, etc.
		are properly tracked.
		"""
		if isinstance(expr, (H.HVar, H.HField, H.HIndex)):
			if as_value:
				place = place_from_expr(expr, base_lookup=self.base_lookup)
				if place is not None:
					self._consume_place_use(state, place)
			return
		if isinstance(expr, H.HCall):
			self._visit_expr(state, expr.fn, as_value=True)
			for arg in expr.args:
				self._visit_expr(state, arg, as_value=True)
			return
		if isinstance(expr, H.HMethodCall):
			self._visit_expr(state, expr.receiver, as_value=True)
			for arg in expr.args:
				self._visit_expr(state, arg, as_value=True)
			return
		if isinstance(expr, H.HBinary):
			self._visit_expr(state, expr.left, as_value=True)
			self._visit_expr(state, expr.right, as_value=True)
			return
		if isinstance(expr, H.HUnary):
			self._visit_expr(state, expr.expr, as_value=True)
			return
		if isinstance(expr, H.HTernary):
			self._visit_expr(state, expr.cond, as_value=True)
			self._visit_expr(state, expr.then_expr, as_value=True)
			self._visit_expr(state, expr.else_expr, as_value=True)
			return
		if isinstance(expr, H.HResultOk):
			self._visit_expr(state, expr.value, as_value=True)
			return
		if isinstance(expr, H.HTryResult):
			self._visit_expr(state, expr.expr, as_value=True)
			return
		if isinstance(expr, H.HArrayLiteral):
			for el in expr.elements:
				self._visit_expr(state, el, as_value=True)
			return
		if isinstance(expr, H.HDVInit):
			for a in expr.args:
				self._visit_expr(state, a, as_value=True)
			return
		# Literals and other rvalues need no action.

	def _transfer_block(self, block: BasicBlock, in_state: Dict[Place, PlaceState]) -> Dict[Place, PlaceState]:
		"""
		Transfer function for a single basic block: walk statements and mutate
		state to produce the outgoing place-state map.
		"""
		state = dict(in_state)
		for stmt in block.statements:
			if isinstance(stmt, H.HLet):
				self._visit_expr(state, stmt.value, as_value=True)
				base = self.base_lookup(stmt.name)
				if base is not None:
					self._set_state(state, Place(base), PlaceState.VALID)
			elif isinstance(stmt, H.HAssign):
				self._visit_expr(state, stmt.value, as_value=True)
				tgt = place_from_expr(stmt.target, base_lookup=self.base_lookup)
				if tgt is not None:
					self._set_state(state, tgt, PlaceState.VALID)
				else:
					self._diagnostic("assignment target is not an lvalue")
			elif isinstance(stmt, H.HReturn):
				if stmt.value is not None:
					self._visit_expr(state, stmt.value, as_value=True)
			elif isinstance(stmt, H.HExprStmt):
				self._visit_expr(state, stmt.expr, as_value=True)
			elif isinstance(stmt, H.HThrow):
				self._visit_expr(state, stmt.value, as_value=True)
			elif isinstance(stmt, H.HIf):
				# Handled via CFG; still visit condition.
				self._visit_expr(state, stmt.cond, as_value=True)
			elif isinstance(stmt, H.HLoop):
				# Loop structure handled in CFG; body handled in child blocks.
				pass
			elif isinstance(stmt, H.HTry):
				# Structure handled in CFG; body/catches handled in child blocks.
				pass
			# other stmts: continue

		# Terminator expressions
		term = block.terminator
		if term and term.kind == "branch" and term.cond is not None:
			self._visit_expr(state, term.cond, as_value=True)
		if term and term.kind in ("return", "throw") and term.value is not None:
			self._visit_expr(state, term.value, as_value=True)

		return state

	def check_block(self, block: H.HBlock) -> List[Diagnostic]:
		"""Run move tracking on a HIR block by building a CFG and flowing states."""
		self.diagnostics.clear()
		blocks, entry_id = self._build_cfg(block)
		in_states: Dict[int, Dict[Place, PlaceState]] = {b.id: {} for b in blocks}
		worklist = [entry_id]
		while worklist:
			bid = worklist.pop()
			blk = blocks[bid]
			in_state = in_states[bid]
			out_state = self._transfer_block(blk, in_state)
			succs = blk.terminator.targets if blk.terminator else []
			for succ in succs:
				prev = in_states.get(succ, {})
				merged = self._merge_states(prev, out_state)
				if merged != prev:
					in_states[succ] = merged
					worklist.append(succ)
		return self.diagnostics

	def _merge_states(self, a: Dict[Place, PlaceState], b: Dict[Place, PlaceState]) -> Dict[Place, PlaceState]:
		"""Join two place-state maps using merge_place_state as the meet operator."""
		result = dict(a)
		for place, state_b in b.items():
			state_a = result.get(place, PlaceState.UNINIT)
			if state_a is state_b:
				continue
			result[place] = merge_place_state(state_a, state_b)
		return result

	def _build_cfg(self, block: H.HBlock) -> Tuple[List[BasicBlock], int]:
		"""
		Lower a structured HIR block into a rudimentary CFG.

		Each HIf/HLoop/HTry introduces new blocks with branch/jump terminators.
		Tail statements after a control construct are placed in a continuation
		block so successors join correctly. Return/throw terminate a block with
		no successors.
		"""
		blocks: List[BasicBlock] = []

		def new_block() -> BasicBlock:
			bb = BasicBlock(id=len(blocks))
			blocks.append(bb)
			return bb

		exit_block = new_block()
		exit_block.terminator = Terminator(kind="jump", targets=[])
		exit_id = exit_block.id

		def add_backedge(body_ids: List[int], body_entry: int, exit_id: int) -> None:
			for bid in body_ids:
				bb = blocks[bid]
				if bb.terminator and exit_id in bb.terminator.targets and bb.terminator.kind == "jump":
					if body_entry not in bb.terminator.targets:
						bb.terminator.targets.append(body_entry)

		def build(stmts: List[H.HStmt], cont: int) -> Tuple[int, List[int]]:
			bb = new_block()
			ids = [bb.id]
			idx = 0
			while idx < len(stmts):
				stmt = stmts[idx]
				if isinstance(stmt, H.HIf):
					tail = stmts[idx + 1 :]
					cont_entry, cont_ids = (cont, [])
					if tail:
						cont_entry, cont_ids = build(tail, cont)
					then_entry, then_ids = build(stmt.then_block.statements, cont_entry)
					else_entry, else_ids = build(stmt.else_block.statements if stmt.else_block else [], cont_entry)
					bb.terminator = Terminator(kind="branch", targets=[then_entry, else_entry], cond=stmt.cond)
					ids.extend(then_ids + else_ids + cont_ids)
					return bb.id, ids
				if isinstance(stmt, H.HLoop):
					tail = stmts[idx + 1 :]
					cont_entry, cont_ids = (cont, [])
					if tail:
						cont_entry, cont_ids = build(tail, cont)
					body_entry, body_ids = build(stmt.body.statements, cont_entry)
					bb.terminator = Terminator(kind="branch", targets=[body_entry, cont_entry], cond=None)
					add_backedge(body_ids, body_entry, cont_entry)
					ids.extend(body_ids + cont_ids)
					return bb.id, ids
				if isinstance(stmt, H.HTry):
					tail = stmts[idx + 1 :]
					cont_entry, cont_ids = (cont, [])
					if tail:
						cont_entry, cont_ids = build(tail, cont)
					body_entry, body_ids = build(stmt.body.statements, cont_entry)
					catch_entries = []
					catch_ids: List[int] = []
					for arm in stmt.catches:
						entry, ids_arm = build(arm.block.statements, cont_entry)
						catch_entries.append(entry)
						catch_ids.extend(ids_arm)
					targets = [body_entry] + catch_entries
					bb.terminator = Terminator(kind="branch", targets=targets, cond=None)
					ids.extend(body_ids + catch_ids + cont_ids)
					return bb.id, ids
				if isinstance(stmt, (H.HReturn, H.HThrow)):
					bb.statements.append(stmt)
					bb.terminator = Terminator(kind="return" if isinstance(stmt, H.HReturn) else "throw", targets=[], value=stmt.value)
					return bb.id, ids
				bb.statements.append(stmt)
				idx += 1
			if bb.terminator is None:
				bb.terminator = Terminator(kind="jump", targets=[cont])
			return bb.id, ids

		entry, _ = build(block.statements, exit_id)
		return blocks, entry
