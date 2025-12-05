# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Stage 4: MIR dominator analysis.

Pipeline placement:
  stage0 (AST) → stage1 (HIR) → stage2 (MIR) → stage3 (pre-analysis) → stage4 (SSA, dominators) → LLVM/obj

This module computes immediate dominators for a MIR function's CFG. It is kept
separate from SSA so that SSA construction can consume a clean, well-tested
dominator table instead of reimplementing graph algorithms inline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set, Optional

from lang2.stage2 import MirFunc, Goto, IfTerminator, MTerminator


@dataclass
class DominatorInfo:
	"""
	Immediate dominator table: idom[block] = immediate dominator block or None for entry.
	"""

	idom: Dict[str, Optional[str]] = field(default_factory=dict)


class DominatorAnalysis:
	"""
	Compute immediate dominators for a MIR CFG.

	Algorithm: classic iterative dataflow:
	  - dom(entry) = {entry}
	  - dom(b) = all blocks initially
	  - dom(b) = {b} ∪ (⋂_{p ∈ preds(b)} dom(p)) until fixed point
	Then idom(b) is chosen as a dominator of b (other than b) that does not
	strictly dominate any other dominator candidate.
	"""

	def compute(self, func: MirFunc) -> DominatorInfo:
		blocks = list(func.blocks.keys())
		entry = func.entry

		# 1. Build predecessor map.
		preds: Dict[str, Set[str]] = {b: set() for b in blocks}
		for bname, block in func.blocks.items():
			term = block.terminator
			if isinstance(term, Goto):
				preds[term.target].add(bname)
			elif isinstance(term, IfTerminator):
				preds[term.then_target].add(bname)
				preds[term.else_target].add(bname)
			# Other terminators (Return, etc.) do not add outgoing edges.

		# 2. Initialize dom sets.
		dom: Dict[str, Set[str]] = {b: set(blocks) for b in blocks}
		dom[entry] = {entry}

		changed = True
		while changed:
			changed = False
			for b in blocks:
				if b == entry:
					continue
				if not preds[b]:
					# Unreachable block: conservatively, only itself.
					new_dom = {b}
				else:
					# Intersection of predecessors' dom sets, union with self.
					p_iter = iter(preds[b])
					inter = dom[next(p_iter)].copy()
					for p in p_iter:
						inter &= dom[p]
					new_dom = inter | {b}
				if new_dom != dom[b]:
					dom[b] = new_dom
					changed = True

		# 3. Compute immediate dominators via the standard definition:
		# idom(b) is the unique dominator of b (other than b) that dominates all other dominators of b.
		idom: Dict[str, Optional[str]] = {entry: None}
		for b in blocks:
			if b == entry:
				continue
			# Candidates are all dominators of b except b itself.
			candidates = dom[b] - {b}
			id_candidate: Optional[str] = None
			for c in candidates:
				# c is the immediate dominator if it dominates b
				# and no other candidate dominates c.
				if all((c == d) or (c not in dom[d]) for d in candidates):
					id_candidate = c
					break
			idom[b] = id_candidate

		return DominatorInfo(idom=idom)
