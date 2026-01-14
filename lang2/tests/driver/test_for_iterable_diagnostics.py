# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

from lang2.driftc.driftc import compile_stubbed_funcs
from lang2.driftc.module_lowered import flatten_modules
from lang2.driftc.parser import parse_drift_workspace_to_hir, stdlib_root


def _write_file(path: Path, content: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content)


def _compile(tmp_path: Path, content: str, *, use_stdlib: bool = True, run_borrow_check: bool = False):
	mod_root = tmp_path / "mods"
	src = mod_root / "main.drift"
	_write_file(src, content)
	paths = sorted(mod_root.rglob("*.drift"))
	modules, type_table, exc_catalog, module_exports, module_deps, diagnostics = parse_drift_workspace_to_hir(
		paths,
		module_paths=[mod_root],
		stdlib_root=stdlib_root() if use_stdlib else None,
	)
	assert diagnostics == []
	func_hirs, sigs, _fn_ids = flatten_modules(modules)
	_, checked = compile_stubbed_funcs(
		func_hirs=func_hirs,
		signatures=sigs,
		exc_env=exc_catalog,
		type_table=type_table,
		module_exports=module_exports,
		module_deps=module_deps,
		return_checked=True,
		run_borrow_check=run_borrow_check,
	)
	return checked.diagnostics


def test_for_on_non_iterable_reports_error(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

fn main() nothrow -> Int {
	for x in 1 { x; }
	return 0;
}
""",
	)
	assert any("type is not iterable" in d.message for d in diagnostics)


def test_next_on_non_iterator_reports_error(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

import std.iter as iter;

fn main() nothrow -> Int {
	var x = 1;
	iter.SinglePassIterator::next(&mut x);
	return 0;
}
""",
	)
	assert any("no matching method 'next'" in d.message for d in diagnostics)


def test_iterable_ufcs_reports_generic_error(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

import std.iter as iter;

fn main() nothrow -> Int {
	iter.Iterable::iter(1);
	return 0;
}
""",
	)
	assert any("no matching method 'iter'" in d.message for d in diagnostics)
	assert not any("type is not iterable" in d.message for d in diagnostics)


def test_for_without_stdlib_root_is_not_iterable(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

fn main() nothrow -> Int {
	val xs = [1, 2, 3];
	for x in move xs { x; }
	return 0;
}
""",
		use_stdlib=False,
	)
	assert any(d.code == "E-NOT-ITERABLE" for d in diagnostics)


def test_for_iter_result_without_iterator_impl_reports_error(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

import std.iter as iter;

struct Dummy(x: Int);
struct NotIter(x: Int);

implement iter.Iterable<Dummy, Int, NotIter> for Dummy {
	pub fn iter(self: Dummy) -> NotIter { return NotIter(x = 0); }
}

fn main() nothrow -> Int {
	val d = Dummy(x = 1);
	for x in d { x; }
	return 0;
}
""",
	)
	assert any(d.code == "E-ITER-RESULT-NOT-ITERATOR" for d in diagnostics)


def test_for_ignores_local_iterable_names(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

trait Iterable<T> { fn iter(self: &Self) -> Int; }
trait SinglePassIterator<T> { fn next(self: &mut Self) -> Int; }

fn main() nothrow -> Int {
	val xs = [1, 2, 3];
	for x in xs { x; }
	return 0;
}
""",
	)
	assert diagnostics == []


def test_for_over_function_returned_array_compiles(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

fn make() nothrow -> Array<Int> { return [1, 2, 3]; }

fn main() nothrow -> Int {
	for x in make() { x; }
	return 0;
}
""",
	)
	assert diagnostics == []


def test_for_over_owned_array_compiles(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

fn main() nothrow -> Int {
	val xs = [1, 2, 3];
	for x in xs { x; }
	return 0;
}
""",
	)
	assert diagnostics == []


def test_for_over_borrowed_array_compiles(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

fn main() nothrow -> Int {
	val xs = [1, 2, 3];
	for x in &xs { x; }
	return 0;
}
""",
	)
	assert diagnostics == []


def test_for_over_owned_array_consumes_non_copy(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

fn main() nothrow -> Int {
	var a = [1, 2, 3];
	for x in a { x; }
	a.push(4);
	return 0;
}
""",
		run_borrow_check=True,
	)
	assert any(d.code == "E_USE_AFTER_MOVE" for d in diagnostics)


def test_for_owned_array_requires_copy_element(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

fn consume(xs: Array<Array<Int>>) nothrow -> Int {
	for x in xs { x; }
	return 0;
}

fn main() nothrow -> Int {
	return 0;
}
""",
	)
	assert any("requirement not satisfied" in d.message and "Copy" in d.message for d in diagnostics)


def test_for_mut_array_is_not_iterable(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

fn main() nothrow -> Int {
	var xs = [1, 2, 3];
	for x in &mut xs { x; }
	return 0;
}
""",
	)
	assert any(d.code == "E-NOT-ITERABLE" for d in diagnostics)
