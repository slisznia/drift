# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

import pytest
from lark import UnexpectedInput

from lang2.driftc.parser import parser as p


def test_parse_export_single_name() -> None:
	prog = p.parse_program(
		"""
module m
export { a }
"""
	)
	assert len(prog.exports) == 1
	assert prog.exports[0].names == ["a"]


def test_parse_export_multiple_names() -> None:
	prog = p.parse_program(
		"""
module m
export { a, b }
"""
	)
	assert len(prog.exports) == 1
	assert prog.exports[0].names == ["a", "b"]


def test_export_trailing_comma_rejected() -> None:
	with pytest.raises(UnexpectedInput):
		p.parse_program(
			"""
module m
export { a, }
"""
		)
