# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from lang2.driftc.parser import parser as p
from lang2.driftc.parser.ast import IfStmt, TraitDef, TraitIs, TraitNot, TraitOr


def test_parse_trait_def_with_require_and_method() -> None:
	prog = p.parse_program(
		"""
trait Debuggable require Self is Printable {
	fn fmt(self: Int) returns String
}
"""
	)
	assert len(prog.traits) == 1
	tr = prog.traits[0]
	assert isinstance(tr, TraitDef)
	assert tr.name == "Debuggable"
	assert tr.require is not None
	assert tr.methods and tr.methods[0].name == "fmt"


def test_parse_struct_and_function_require_clauses() -> None:
	prog = p.parse_program(
		"""
struct File require Self is Destructible { }

fn use_file() returns Int require T is Debuggable {
	return 0;
}
"""
	)
	assert len(prog.structs) == 1
	assert prog.structs[0].require is not None
	assert len(prog.functions) == 1
	assert prog.functions[0].require is not None


def test_parse_trait_guard_in_if_stmt() -> None:
	prog = p.parse_program(
		"""
fn main() returns Int {
	if T is Debuggable or not T is Printable { return 1; } else { return 2; }
}
"""
	)
	stmt = prog.functions[0].body.statements[0]
	assert isinstance(stmt, IfStmt)
	assert isinstance(stmt.condition, TraitOr)
	assert isinstance(stmt.condition.left, TraitIs)
	assert isinstance(stmt.condition.right, TraitNot)
