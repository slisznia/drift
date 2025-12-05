# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Stage 2 tests: HIR→MIR lowering for throw/try (throw only for now).
"""

from lang2 import stage1 as H
from lang2.stage2 import (
	MirBuilder,
	HIRToMIR,
	ConstInt,
	ConstString,
	ConstructError,
	ConstructResultErr,
	Return,
)


def test_throw_lowers_to_error_and_result_err_return():
	"""
	`throw payload` should:
	  - emit a ConstInt for the event code placeholder,
	  - ConstructError(code, payload),
	  - ConstructResultErr(error),
	  - Return that result.
	"""
	builder = MirBuilder(name="throw_fn")
	lower = HIRToMIR(builder)

	hir_block = H.HBlock(statements=[H.HThrow(value=H.HLiteralString("boom"))])
	lower.lower_block(hir_block)

	entry = builder.func.blocks["entry"]
	instrs = entry.instructions

	# Expect: payload literal, event-code const, ConstructError, ConstructResultErr
	assert len(instrs) == 4
	assert isinstance(instrs[0], ConstString)
	assert isinstance(instrs[1], ConstInt)
	assert isinstance(instrs[2], ConstructError)
	assert isinstance(instrs[3], ConstructResultErr)

	term = entry.terminator
	assert isinstance(term, Return)
	assert term.value == instrs[3].dest
