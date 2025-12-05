# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Stage 3: MIR pre-analyses (address-taken, may-fail flags).

Pipeline placement:
  stage0 (AST) → stage1 (HIR) → stage2 (MIR) → stage3 (pre-analysis) → SSA → LLVM/obj

This module walks a MIR function and computes side tables that later stages
(SSA construction, storage allocation) can consult. The intent is to keep MIR→SSA
purely structural: all semantic flags are computed here.

Current analyses:
  - address_taken: locals whose address is observed (AddrOfLocal)
  - may_fail: instruction sites that can fail/throw (calls, method calls,
    ConstructDV)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Set

from lang2.stage2 import (
	MirFunc,
	MInstr,
	MTerminator,
	AddrOfLocal,
	Call,
	MethodCall,
	ConstructDV,
)


@dataclass
class MirAnalysisResult:
	"""Holds pre-analysis results for a single MirFunc."""

	address_taken: Set[str]
	may_fail: Set[tuple[str, int]]  # (block_name, instruction_index)


class MirPreAnalysis:
	"""
	Run MIR pre-analyses:
	  - address_taken: which locals have their address observed
	  - may_fail: which instruction sites can fail (conservative)

	Entry point:
	  analyze(func: MirFunc) -> MirAnalysisResult
	"""

	def analyze(self, func: MirFunc) -> MirAnalysisResult:
		addr_taken: Set[str] = set()
		may_fail: Set[tuple[str, int]] = set()

		for block_name, block in func.blocks.items():
			for idx, instr in enumerate(block.instructions):
				self._visit_instr(block_name, idx, instr, addr_taken, may_fail)
			if block.terminator is not None:
				self._visit_term(block_name, block.terminator, may_fail)

		return MirAnalysisResult(address_taken=addr_taken, may_fail=may_fail)

	def _visit_instr(
		self,
		block_name: str,
		idx: int,
		instr: MInstr,
		addr_taken: Set[str],
		may_fail: Set[tuple[str, int]],
	) -> None:
		"""Inspect a MIR instruction and update analysis sets."""
		if isinstance(instr, AddrOfLocal):
			addr_taken.add(instr.local)

		may_fail_ops = (
			Call,
			MethodCall,
			ConstructDV,
			# Conservatively include field/index ops if you treat them as potentially failing.
			# This can be refined later.
			# LoadField, StoreField, LoadIndex, StoreIndex, ...
		)
		if isinstance(instr, may_fail_ops):
			may_fail.add((block_name, idx))

	def _visit_term(self, block_name: str, term: MTerminator, may_fail: Set[tuple[str, int]]) -> None:
		"""Inspect a MIR terminator. Currently no-op; reserved for future."""
		return
