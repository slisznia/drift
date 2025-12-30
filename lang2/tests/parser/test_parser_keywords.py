import pytest
from lark.exceptions import UnexpectedInput

from lang2.driftc.parser import parser as p


def test_type_keyword_is_reserved() -> None:
	with pytest.raises(UnexpectedInput):
		p.parse_program(
			"""
fn main() returns Int {
	val type: Int = 1;
	return type;
}
"""
		)
