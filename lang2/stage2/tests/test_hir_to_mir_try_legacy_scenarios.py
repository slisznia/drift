# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Ported exception scenarios to pin legacy semantics:

* Throw event B, inner try catches event A, outer catches event B -> outer catch is taken.
* Multi-arm try: event-specific arms followed by catch-all; thrown event matches the correct arm.
"""

from __future__ import annotations

from lang2.stage2 import HIRToMIR, MirBuilder, mir_nodes as M
from lang2 import stage1 as H


def _walk_else(func: M.MirFunc, block: M.BasicBlock) -> M.BasicBlock:
	"""Follow the else-targets of IfTerminator until a non-If terminator."""
	while isinstance(block.terminator, M.IfTerminator):
		block = func.blocks[block.terminator.else_target]
	return block


def test_throw_b_skips_inner_catch_a_hits_outer_catch_b():
	"""
	Inner try catches EvtA, outer catches EvtB.
	Throw EvtB in inner body should skip inner catch and land in outer catch.
	"""
	exc_env = {"EvtA": 1, "EvtB": 2}
	builder = MirBuilder(name="legacy_inner_outer_events")
	lower = HIRToMIR(builder, exc_env=exc_env)

	inner_try = H.HTry(
		body=H.HBlock(statements=[H.HThrow(value=H.HDVInit(dv_type_name="EvtB", args=[]))]),
		catches=[H.HCatchArm(event_name="EvtA", binder=None, block=H.HBlock(statements=[]))],
	)
	outer_try = H.HTry(
		body=H.HBlock(statements=[inner_try]),
		catches=[H.HCatchArm(event_name="EvtB", binder="b", block=H.HBlock(statements=[]))],
	)
	lower.lower_block(H.HBlock(statements=[outer_try]))
	func = builder.func

	# Identify the two main dispatch blocks (not the chained "next" blocks).
	dispatch_blocks = {
		name: blk for name, blk in func.blocks.items()
		if name.startswith("try_dispatch") and "next" not in name
	}
	assert len(dispatch_blocks) >= 2
	sorted_dispatch = sorted(dispatch_blocks.items(), key=lambda item: item[0])
	outer_dispatch_name, outer_dispatch = sorted_dispatch[0]
	inner_dispatch_name, inner_dispatch = sorted_dispatch[1]

	# Inner unmatched path should goto outer dispatch.
	inner_final = _walk_else(func, inner_dispatch)
	assert isinstance(inner_final.terminator, M.Goto)
	assert inner_final.terminator.target == outer_dispatch_name

	# Outer dispatch should take the then-branch to the EvtB catch (the one that binds "b").
	assert isinstance(outer_dispatch.terminator, M.IfTerminator)
	then_target = outer_dispatch.terminator.then_target
	# Identify the outer catch block by looking for the binder store.
	catch_blocks = {name: blk for name, blk in func.blocks.items() if name.startswith("try_catch")}
	target_block = catch_blocks[then_target]
	assert any(isinstance(instr, M.StoreLocal) and instr.local == "b" for instr in target_block.instructions)


def test_multi_event_with_catch_all_matches_specific_arm():
	"""
	Multi-arm try with two events followed by catch-all; thrown event matches
	the correct event-specific arm, not the catch-all.
	"""
	exc_env = {"EvtA": 1, "EvtB": 2}
	builder = MirBuilder(name="legacy_multi_event")
	lower = HIRToMIR(builder, exc_env=exc_env)

	hir = H.HBlock(
		statements=[
			H.HTry(
				body=H.HBlock(statements=[H.HThrow(value=H.HDVInit(dv_type_name="EvtB", args=[]))]),
				catches=[
					H.HCatchArm(event_name="EvtA", binder=None, block=H.HBlock(statements=[])),
					H.HCatchArm(event_name="EvtB", binder="b", block=H.HBlock(statements=[])),
					H.HCatchArm(event_name=None, binder=None, block=H.HBlock(statements=[])),
				],
			)
		]
	)
	lower.lower_block(hir)
	func = builder.func

	dispatch = func.blocks["try_dispatch"]
	# First IfTerminator should compare against EvtA code; else branch continues chain.
	assert isinstance(dispatch.terminator, M.IfTerminator)
	first_then = dispatch.terminator.then_target
	first_else = dispatch.terminator.else_target
	assert first_then == "try_catch_0"

	# Second IfTerminator (in else branch) should jump to EvtB catch, not catch-all.
	second_dispatch = func.blocks[first_else]
	assert isinstance(second_dispatch.terminator, M.IfTerminator)
	assert second_dispatch.terminator.then_target == "try_catch_1"

	# Catch-all is only in the final else of the second dispatch.
	final_else = func.blocks[second_dispatch.terminator.else_target]
	final_term = _walk_else(func, final_else)
	assert isinstance(final_term.terminator, M.Goto)
	assert final_term.terminator.target == "try_catch_2"
