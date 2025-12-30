#!/usr/bin/env python3
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-09
"""End-to-end check: method resolution failure produces diagnostics and nonzero exit."""

from pathlib import Path

from lang2.driftc import driftc


def _write_file(path: Path, content: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content)


def test_method_resolution_failure_reports_diagnostic(tmp_path):
	src = tmp_path / "bad_method.drift"
	src.write_text(
		"""
implement Point {
    fn m(self: &Point) returns Int { return 1; }
}

fn main() returns Int  nothrow{
    val x = 1;
    return x.m(); // no such method on Int;
}
"""
	)
	exit_code = driftc.main([str(src)])
	assert exit_code == 1


def test_cross_module_trait_dot_call_e2e(tmp_path: Path) -> None:
	mod_root = tmp_path / "mods"
	_write_file(
		mod_root / "m_box" / "lib.drift",
		"""
module m_box

export { Box }

pub struct Box { value: Int }
""",
	)
	_write_file(
		mod_root / "m_trait" / "lib.drift",
		"""
module m_trait

import m_box

export { Show }

pub trait Show { fn show(self: m_box.Box) returns Int }

implement Show for m_box.Box {
	pub fn show(self: m_box.Box) returns Int { return self.value; }
}
""",
	)
	_write_file(
		mod_root / "m_main" / "main.drift",
		"""
module m_main

import m_box
import m_trait as t

use trait t.Show

fn main() returns Int  nothrow{
	val b: m_box.Box = m_box.Box(value = 1);
	try {
		return b.show();
	} catch {
		return 0;
	}
}
""",
	)
	paths = sorted(mod_root.rglob("*.drift"))
	exit_code = driftc.main(["-M", str(mod_root), *[str(p) for p in paths]])
	assert exit_code == 0


def test_cross_module_trait_ufcs_e2e(tmp_path: Path) -> None:
	mod_root = tmp_path / "mods"
	_write_file(
		mod_root / "m_box" / "lib.drift",
		"""
module m_box

export { Box }

pub struct Box { value: Int }
""",
	)
	_write_file(
		mod_root / "m_trait" / "lib.drift",
		"""
module m_trait

import m_box

export { Show }

pub trait Show { fn show(self: m_box.Box) returns Int }

implement Show for m_box.Box {
	pub fn show(self: m_box.Box) returns Int { return self.value + 1; }
}
""",
	)
	_write_file(
		mod_root / "m_main" / "main.drift",
		"""
module m_main

import m_box
import m_trait

fn main() returns Int  nothrow{
	val b: m_box.Box = m_box.Box(value = 1);
	return m_trait.Show::show(b);
}
""",
	)
	paths = sorted(mod_root.rglob("*.drift"))
	exit_code = driftc.main(["-M", str(mod_root), *[str(p) for p in paths]])
	assert exit_code == 0
