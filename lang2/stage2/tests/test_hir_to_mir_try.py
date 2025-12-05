# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Stage 2 test: HIR→MIR lowering for try/catch routing throws intra-function.
"""

from lang2 import stage1 as H
from lang2.stage2 import (
	MirBuilder,
	HIRToMIR,
	ConstString,
	ConstInt,
	ConstructError,
	Goto,
)


def test_try_routes_throw_to_catch_block():
	"""
	Lower:
	  try { throw "x" } catch e { }

	Shape expectations:
	  - entry branches to try_body
	  - try_body constructs the Error, stores into catch binder, then Goto catch
	  - catch falls through to cont
	"""
	builder = MirBuilder(name="try_fn")
	lower = HIRToMIR(builder)

	hir = H.HBlock(
		statements=[
			H.HTry(
				body=H.HBlock(statements=[H.HThrow(value=H.HLiteralString("boom"))]),
				catch_name="e",
				catch_block=H.HBlock(statements=[]),
			)
		]
	)
	lower.lower_block(hir)

	blocks = builder.func.blocks

	# Entry should jump to try_body
	assert blocks["entry"].terminator is not None
	assert isinstance(blocks["entry"].terminator, Goto)
	assert blocks["entry"].terminator.target.startswith("try_body")

	# Try body should build error and jump to catch
	try_body = blocks[blocks["entry"].terminator.target]
	instrs = try_body.instructions
	assert isinstance(instrs[0], ConstString)
	assert isinstance(instrs[1], ConstInt)
	assert isinstance(instrs[2], ConstructError)
	assert isinstance(try_body.terminator, Goto)
	assert try_body.terminator.target.startswith("try_catch")

	# Catch block should end with Goto to cont
	catch_block = blocks[try_body.terminator.target]
	assert isinstance(catch_block.terminator, Goto)
	assert catch_block.terminator.target.startswith("try_cont")
