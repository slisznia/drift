# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from lang2.driftc.parser import parser as p
from lang2.driftc.traits.world import build_trait_world


def test_trait_world_collects_traits_and_impls_with_qualified_heads() -> None:
	prog = p.parse_program(
		"""
trait Debuggable { fn fmt(self: Int) returns String }

implement Debuggable for a.Point { fn fmt(self: a.Point) returns String { return ""; } }
implement Debuggable for b.Point { fn fmt(self: b.Point) returns String { return ""; } }
"""
	)
	world = build_trait_world(prog)
	assert world.diagnostics == []
	assert len(world.traits) == 1
	assert len(world.impls) == 2
	assert len(world.impls_by_trait_target) == 2


def test_trait_world_reports_unknown_trait_in_require() -> None:
	prog = p.parse_program(
		"""
struct File require Self is Missing { }
"""
	)
	world = build_trait_world(prog)
	assert any("unknown trait" in d.message for d in world.diagnostics)


def test_trait_world_allows_unqualified_trait_in_struct_require() -> None:
	prog = p.parse_program(
		"""
trait Debuggable { fn fmt(self: Int) returns String }
struct File require Self is Debuggable { }
"""
	)
	world = build_trait_world(prog)
	assert world.diagnostics == []


def test_trait_world_rejects_overlapping_impls_for_same_head() -> None:
	prog = p.parse_program(
		"""
trait Debuggable { fn fmt(self: Int) returns String }

implement Debuggable for Box<T> { fn fmt(self: Box<T>) returns String { return ""; } }
implement Debuggable for Box<U> { fn fmt(self: Box<U>) returns String { return ""; } }
"""
	)
	world = build_trait_world(prog)
	assert any("overlapping impls" in d.message for d in world.diagnostics)


def test_trait_world_rejects_self_in_function_require() -> None:
	prog = p.parse_program(
		"""
trait Debuggable { fn fmt(self: Int) returns String }

fn use_file() returns Int require Self is Debuggable { return 0; }
"""
	)
	world = build_trait_world(prog)
	assert any("function require clause cannot use 'Self'" in d.message for d in world.diagnostics)
