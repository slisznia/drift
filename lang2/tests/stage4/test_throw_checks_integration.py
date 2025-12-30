# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Integration: stage2 → stage3 → stage4 throw checks.
Ensures the throw summary plus checker-inferred declared_can_throw map drive the invariants.
"""

from __future__ import annotations

import pytest

from lang2.driftc import stage1 as H
from lang2.driftc.stage1 import normalize_hir
from lang2.driftc.stage2 import HIRToMIR, MirBuilder, mir_nodes as M
from lang2.driftc.stage3.throw_summary import ThrowSummaryBuilder
from lang2.driftc.stage4 import run_throw_checks
from lang2.driftc.core.types_core import TypeTable


def _lower_fn(name: str, hir_block: H.HBlock, *, can_throw: bool) -> tuple[str, object]:
	builder = MirBuilder(name=name)
	can_throw_map = {name: True} if can_throw else {}
	# Stage2 lowering for exception constructors requires schemas; these tests
	# use only zero-field events, so we seed minimal entries here.
	type_table = TypeTable()
	type_table.exception_schemas = {
		"m:EvtX": ("m:EvtX", []),
		"m:Evt": ("m:Evt", []),
	}
	HIRToMIR(builder, type_table=type_table, can_throw_by_name=can_throw_map).lower_block(normalize_hir(hir_block))
	return name, builder.func


def test_can_throw_function_passes_checks():
	"""A declared can-throw function that throws should pass all invariants."""
	fn_name, mir_fn = _lower_fn(
		"f_can",
		H.HBlock(
			statements=[
				H.HThrow(
					value=H.HExceptionInit(event_fqn="m:EvtX", pos_args=[], kw_args=[]),
				)
			]
		),
		can_throw=True,
	)
	mir_funcs = {fn_name: mir_fn}
	summaries = ThrowSummaryBuilder().build(mir_funcs, code_to_exc={})
	infos = run_throw_checks(mir_funcs, summaries, declared_can_throw={fn_name: True})
	assert fn_name in infos
	assert infos[fn_name].declared_can_throw is True


def test_can_throw_try_catch_and_return_ok_shape():
	"""
	Can-throw function with try/catch and an explicit FnResult.Ok return passes all invariants.
	The try/catch itself does not terminate the function; we append a ConstructResultOk + Return.
	"""
	fn_name, mir_fn = _lower_fn(
		"f_ok",
		H.HBlock(
			statements=[
				H.HTry(
					body=H.HBlock(
						statements=[
							H.HThrow(
								value=H.HExceptionInit(event_fqn="m:Evt", pos_args=[], kw_args=[]),
							)
						]
					),
					catches=[H.HCatchArm(event_fqn="m:Evt", binder="e", block=H.HBlock(statements=[]))],
				)
			]
		),
		can_throw=True,
	)

	# Manually append an Ok return in the try_cont block so return-shape checks pass.
	try_cont_blocks = [name for name in mir_fn.blocks if name.startswith("try_cont")]
	assert try_cont_blocks, "expected a try_cont block to append return"
	cont = mir_fn.blocks[try_cont_blocks[0]]
	ok_val = "ok_val"
	ok_res = "ok_res"
	cont.instructions.extend(
		[
			M.ConstInt(dest=ok_val, value=1),
			M.ConstructResultOk(dest=ok_res, value=ok_val),
		]
	)
	cont.terminator = M.Return(value=ok_res)

	mir_funcs = {fn_name: mir_fn}
	summaries = ThrowSummaryBuilder().build(mir_funcs, code_to_exc={"m:Evt": 1})
	infos = run_throw_checks(mir_funcs, summaries, declared_can_throw={fn_name: True})
	assert fn_name in infos
	assert infos[fn_name].declared_can_throw is True


def test_can_throw_fnresult_forwarding_currently_rejected():
	"""
	Structural FnResult check still rejects forwarding/aliasing:
	a can-throw function that returns a value not produced by ConstructResultOk/Err
	should fail for now (type-aware checks will relax this later).
	"""
	# MIR: entry -> return param "p" (no ConstructResultOk/Err defines it).
	entry = M.BasicBlock(name="entry", instructions=[], terminator=M.Return(value="p"))
	mir_fn = M.MirFunc(
		name="f_forward",
		params=[],
		locals=["p"],
		blocks={"entry": entry},
		entry="entry",
	)
	mir_funcs = {"f_forward": mir_fn}
	summaries = ThrowSummaryBuilder().build(mir_funcs, code_to_exc={})
	declared_can_throw = {"f_forward": True}

	with pytest.raises(RuntimeError):
		run_throw_checks(mir_funcs, summaries, declared_can_throw)


def test_can_throw_without_throw_and_ok_return_passes():
	"""
	A can-throw function that never throws but returns a ConstructResultOk value
	should clear all invariants.
	"""
	entry = M.BasicBlock(
		name="entry",
		instructions=[
			M.ConstInt(dest="v_ok", value=42),
			M.ConstructResultOk(dest="r_ok", value="v_ok"),
		],
		terminator=M.Return(value="r_ok"),
	)
	mir_fn = M.MirFunc(
		name="f_ok_only",
		params=[],
		locals=[],
		blocks={"entry": entry},
		entry="entry",
	)
	mir_funcs = {"f_ok_only": mir_fn}
	summaries = ThrowSummaryBuilder().build(mir_funcs, code_to_exc={})
	declared_can_throw = {"f_ok_only": True}

	infos = run_throw_checks(mir_funcs, summaries, declared_can_throw)
	assert "f_ok_only" in infos
	assert infos["f_ok_only"].declared_can_throw is True


def test_fnresult_forwarding_aliasing_expected_fail():
	"""
	Structural FnResult check still fails for forwarding/aliasing.
	This documents the limitation; it should be relaxed once the type-aware check is available.
	"""
	# MIR: ConstructResultOk -> StoreLocal alias -> Return alias
	entry = M.BasicBlock(
		name="entry",
		instructions=[
			M.ConstInt(dest="v_ok", value=7),
			M.ConstructResultOk(dest="r0", value="v_ok"),
			M.StoreLocal(local="alias", value="r0"),
		],
		terminator=M.Return(value="alias"),
	)
	mir_fn = M.MirFunc(
		name="f_alias",
		params=[],
		locals=["alias"],
		blocks={"entry": entry},
		entry="entry",
	)
	mir_funcs = {"f_alias": mir_fn}
	summaries = ThrowSummaryBuilder().build(mir_funcs, code_to_exc={})
	declared_can_throw = {"f_alias": True}

	with pytest.raises(RuntimeError):
		run_throw_checks(mir_funcs, summaries, declared_can_throw)

