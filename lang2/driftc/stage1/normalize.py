# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Stage1 HIR normalization helpers.

At this stage we normalize HIR into canonical forms expected by stage2:
- materialize borrows of rvalues into temps
- canonicalize lvalue contexts into HPlaceExpr
"""

from __future__ import annotations

from . import hir_nodes as H
from .borrow_materialize import BorrowMaterializeRewriter
from .node_ids import assign_node_ids
from .place_canonicalize import PlaceCanonicalizeRewriter


def normalize_hir(block: H.HBlock) -> H.HBlock:
	"""
	Normalize an HIR block into canonical forms expected by stage2.
	Additional normalization passes can be added here as needed.
	"""
	# Order matters:
	# 1) Materialize shared borrows of rvalues into temps so borrow checking and
	#    MIR lowering can treat borrow operands as places.
	# 2) Canonicalize lvalue contexts so stage2 sees `HPlaceExpr` instead of
	#    re-deriving place-ness from arbitrary expression trees.
	block = BorrowMaterializeRewriter().rewrite_block(block)
	block = PlaceCanonicalizeRewriter().rewrite_block(block)
	# Ensure stable per-function NodeIds for typed side tables.
	assign_node_ids(block, start=1)
	return block
