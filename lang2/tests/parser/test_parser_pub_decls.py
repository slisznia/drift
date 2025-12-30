# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from lang2.driftc.parser import parser as p


def test_parse_pub_top_level_decls() -> None:
	prog = p.parse_program(
		"""
module m

pub fn f() returns Int { return 0; }
fn g() returns Int { return 1; }

pub const ANSWER: Int = 1;

pub struct S { }
pub exception Boom()
pub variant Opt<T> { Some(value: T), None }
pub trait Debuggable { fn fmt(self: Int) returns Int }

pub implement S {
	pub fn tag(self: S) returns Int { return 0; }
}
"""
	)
	assert len(prog.functions) == 2
	assert prog.functions[0].is_pub is True
	assert prog.functions[1].is_pub is False
	assert len(prog.consts) == 1
	assert prog.consts[0].is_pub is True
	assert len(prog.structs) == 1
	assert prog.structs[0].is_pub is True
	assert len(prog.exceptions) == 1
	assert prog.exceptions[0].is_pub is True
	assert len(prog.variants) == 1
	assert prog.variants[0].is_pub is True
	assert len(prog.traits) == 1
	assert prog.traits[0].is_pub is True
	assert len(prog.implements) == 1
	assert prog.implements[0].is_pub is True
