# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

from lang2.driftc.driftc import compile_stubbed_funcs
from lang2.driftc.module_lowered import flatten_modules
from lang2.driftc.parser import parse_drift_workspace_to_hir, stdlib_root


def _write_file(path: Path, content: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content)


def _compile(tmp_path: Path, content: str):
	mod_root = tmp_path / "mods"
	src = mod_root / "main.drift"
	_write_file(src, content)
	paths = sorted(mod_root.rglob("*.drift"))
	modules, type_table, exc_catalog, module_exports, module_deps, diagnostics = parse_drift_workspace_to_hir(
		paths,
		module_paths=[mod_root],
		stdlib_root=stdlib_root(),
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
	)
	return checked.diagnostics


def test_comparable_requires_equatable(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

import std.core.cmp as cmp;

struct Foo { x: Int }

implement cmp.Comparable for Foo {
	pub fn cmp(self: &Foo, other: &Foo) -> Int { return 0; }
}

fn needs_cmp<T>(x: T) nothrow -> Int require T is cmp.Comparable { return 0; }

fn main() nothrow -> Int {
	val _x = Foo(x = 1);
	val _y = needs_cmp(_x);
	return 0;
}
""",
	)
	assert any(d.code == "E_REQUIREMENT_NOT_SATISFIED" and "cmp.Comparable" in d.message for d in diagnostics)


def test_binary_search_requires_binarysearchable(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

import std.algo as algo;
import std.iter as iter;
import std.core.cmp as cmp;

struct Range { n: Int }
struct Key { x: Int }

implement iter.RandomAccessReadable<Key> for Range {
	pub fn len(self: &Range) -> Int { return self.n; }
	pub fn compare_at(self: &Range, i: Int, j: Int) -> Int { return 0; }
}

fn binary_search<R, T>(r: &R, key: &T) nothrow -> Optional<Int>
	require (R is algo.BinarySearchable<T> and T is cmp.Comparable) {
	return Optional::None();
}

fn main() nothrow -> Int {
	val r = Range(n = 0);
	val k = Key(x = 1);
	val _i = binary_search<type Range, Key>(&r, &k);
	return 0;
}
""",
	)
	assert any(d.code == "E_REQUIREMENT_NOT_SATISFIED" and "BinarySearchable" in d.message for d in diagnostics)


def test_binary_search_requires_comparable(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

import std.iter as iter;
import std.core.cmp as cmp;

struct Range { n: Int }
struct Key { x: Int }

trait BinarySearchable<T> {
	fn compare_key(self: &Self, i: Int, key: &T) -> Int;
}

implement iter.RandomAccessReadable<Key> for Range {
	pub fn len(self: &Range) -> Int { return self.n; }
	pub fn compare_at(self: &Range, i: Int, j: Int) -> Int { return 0; }
}

implement BinarySearchable<Key> for Range {
	pub fn compare_key(self: &Range, i: Int, key: &Key) -> Int { return 0; }
}

fn binary_search<R, T>(r: &R, key: &T) nothrow -> Optional<Int>
	require (R is BinarySearchable<T> and T is cmp.Comparable) {
	return Optional::None();
}

fn main() nothrow -> Int {
	val r = Range(n = 0);
	val k = Key(x = 1);
	val _i = binary_search<type Range, Key>(&r, &k);
	return 0;
}
""",
	)
	assert any(d.code == "E_REQUIREMENT_NOT_SATISFIED" and "Comparable" in d.message for d in diagnostics)


def test_sort_in_place_requires_comparable(tmp_path: Path) -> None:
	diagnostics = _compile(
		tmp_path,
		"""
module m_main

import std.core.cmp as cmp;

struct Range { n: Int }
struct Key { x: Int }

trait Permutable<T> { fn swap(self: &mut Self, i: Int, j: Int) -> Void; }

implement Permutable<Key> for Range {
	pub fn swap(self: &mut Range, i: Int, j: Int) -> Void { return; }
}

fn sort_in_place<R, T>(r: &mut R) nothrow -> Void
	require (R is Permutable<T> and T is cmp.Comparable) {
	return;
}

fn main() nothrow -> Int {
	var r = Range(n = 0);
	val _ = sort_in_place<type Range, Key>(&mut r);
	return 0;
}
""",
	)
	assert any(d.code == "E_REQUIREMENT_NOT_SATISFIED" and "Comparable" in d.message for d in diagnostics)
