# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

from lang2.driftc.parser import parse_drift_to_hir


def test_stage1_function_def_nothrow_sets_declared_can_throw(tmp_path: Path) -> None:
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn add1(x: Int) nothrow returns Int { return x + 1; }
"""
	)
	func_hirs, sigs, fn_ids_by_name, _table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics == []
	fn_ids = fn_ids_by_name.get("main::add1") or fn_ids_by_name.get("add1") or []
	assert len(fn_ids) == 1
	sig = sigs[fn_ids[0]]
	assert sig.declared_can_throw is False
	assert {fid.name for fid in func_hirs} == {"add1"}
