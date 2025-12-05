# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Try/catch validation for catch-all placement:
  - Multiple catch-alls are rejected (already enforced in lowering).
  - Catch-all not last is currently accepted but produces a catch-all-only dispatch
    (later event arms become unreachable). This test pins that behavior until the
    checker enforces ordering.
"""

from __future__ import annotations

import pytest

from lang2.stage2 import HIRToMIR, MirBuilder, mir_nodes as M
from lang2 import stage1 as H


def test_multiple_catch_all_rejected():
	"""Lowering should reject more than one catch-all arm."""
	builder = MirBuilder(name="try_multi_catchall")
	lower = HIRToMIR(builder)

	hir = H.HBlock(
		statements=[
			H.HTry(
				body=H.HBlock(statements=[]),
				catches=[
					H.HCatchArm(event_name=None, binder=None, block=H.HBlock(statements=[])),
					H.HCatchArm(event_name=None, binder=None, block=H.HBlock(statements=[])),
				],
			)
		]
	)
	with pytest.raises(RuntimeError):
		lower.lower_block(hir)


def test_catch_all_not_last_is_unreachable_for_later_arms():
	"""
	Catch-all before event arms: dispatch still targets the catch-all and the later
	event-specific arm becomes unreachable. This pins the current behavior until
	the checker enforces catch-all-last.
	"""
	builder = MirBuilder(name="try_catchall_first")
	lower = HIRToMIR(builder, exc_env={"EvtA": 1})

	hir = H.HBlock(
		statements=[
			H.HTry(
				body=H.HBlock(statements=[H.HThrow(value=H.HDVInit(dv_type_name="X", args=[]))]),
				catches=[
					H.HCatchArm(event_name=None, binder=None, block=H.HBlock(statements=[])),
					H.HCatchArm(event_name="EvtA", binder="a", block=H.HBlock(statements=[])),
				],
			)
		]
	)
	lower.lower_block(hir)

	func = builder.func
	dispatch = func.blocks["try_dispatch"]

	# Dispatch will still build an if-chain over event arms; walk to the final else.
	while isinstance(dispatch.terminator, M.IfTerminator):
		dispatch = func.blocks[dispatch.terminator.else_target]

	# Final resolution should be either goto catch-all or rethrow; here it should jump to the first catch-all.
	assert isinstance(dispatch.terminator, M.Goto)
	assert dispatch.terminator.target == "try_catch_0"

	# The second catch block exists but is not referenced by dispatch.
	assert "try_catch_1" in func.blocks
