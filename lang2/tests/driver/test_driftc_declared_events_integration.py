"""
Integration: declared events must cover thrown events.
"""

from __future__ import annotations

from lang2.driftc import stage1 as H
from lang2.driftc.driftc import compile_stubbed_funcs
from lang2.driftc.core.types_core import TypeTable
from lang2.test_support import make_signatures, build_exception_catalog


def test_declared_events_subset_enforced_by_driver():
	"""
	Function declares throws(EvtA) but throws EvtB -> expect a diagnostic.
	"""
	fn_name = "f_decl"
	hir = H.HBlock(
		statements=[
			H.HThrow(
				value=H.HExceptionInit(event_fqn="m:EvtB", pos_args=[], kw_args=[]),
			),
		]
	)

	signatures = make_signatures(
		{fn_name: "Int"},
		throws_events={"f_decl": ("m:EvtA",)},
		declared_can_throw={"f_decl": True},
	)
	exc_env = build_exception_catalog({"m:EvtA": 1, "m:EvtB": 2})
	type_table = TypeTable()
	type_table.exception_schemas = {
		"m:EvtA": ("m:EvtA", []),
		"m:EvtB": ("m:EvtB", []),
	}

	_, checked = compile_stubbed_funcs(
		func_hirs={fn_name: hir},
		signatures=signatures,
		exc_env=exc_env,
		type_table=type_table,
		build_ssa=True,
		return_checked=True,
	)

	assert checked.fn_infos[fn_name].declared_events == frozenset({"m:EvtA"})
	msgs = [d.message for d in checked.diagnostics]
	assert any("throws ['m:EvtA'] but throws additional events ['m:EvtB']" in m for m in msgs)
