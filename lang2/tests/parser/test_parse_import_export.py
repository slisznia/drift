from __future__ import annotations

from lang2.driftc.parser.parser import parse_program


def test_parse_program_collects_imports_exports_and_functions():
	source = """
module a.b
export { foo, Bar }
from c.d import thing as t
import c.d as cd

fn foo() returns Int { return 1; }
"""
	prog = parse_program(source)

	assert prog.module == "a.b"

	assert [e.names for e in prog.exports] == [["foo", "Bar"]]

	assert len(prog.from_imports) == 1
	from_imp = prog.from_imports[0]
	assert from_imp.module_path == ["c", "d"]
	assert from_imp.symbol == "thing"
	assert from_imp.alias == "t"

	assert len(prog.imports) == 1
	imp = prog.imports[0]
	assert imp.path == ["c", "d"]
	assert imp.alias == "cd"

	assert [fn.name for fn in prog.functions] == ["foo"]
