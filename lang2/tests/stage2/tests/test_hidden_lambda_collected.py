# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

import lang2.driftc.stage2.mir_nodes as M
from lang2.driftc.driftc import compile_stubbed_funcs
from lang2.driftc.parser import parse_drift_to_hir


def test_hidden_lambda_is_collected_into_mir_funcs(tmp_path: Path) -> None:
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn main() returns Int {
    val a: Int = 10;
    val r: Int = (|x| => { return a + x; })(2);
    return r;
}
"""
	)
	func_hirs, sigs, _fn_ids_by_name, type_table, exc_env, diagnostics = parse_drift_to_hir(src)
	assert diagnostics == []

	mir_funcs = compile_stubbed_funcs(
		func_hirs,
		signatures=sigs,
		type_table=type_table,
		exc_env=exc_env,
	)
	hidden = [name for name in mir_funcs.keys() if name.startswith("__lambda_")]
	assert len(hidden) == 1
	hidden_name = hidden[0]

	hidden_func = mir_funcs[hidden_name]
	hidden_instrs = [i for b in hidden_func.blocks.values() for i in b.instructions]
	assert any(isinstance(i, M.StructGetField) for i in hidden_instrs)

	main_instrs = [i for b in mir_funcs["main"].blocks.values() for i in b.instructions]
	assert any(isinstance(i, M.Call) and i.fn == hidden_name for i in main_instrs)
