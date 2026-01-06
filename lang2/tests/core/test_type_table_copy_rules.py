# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from lang2.driftc.core.types_core import TypeTable


def test_fnresult_is_not_copy() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	err_ty = table.ensure_error()
	fnres = table.ensure_fnresult(int_ty, err_ty)
	assert table.is_copy(fnres) is False


def test_optional_copy_matches_inner() -> None:
	table = TypeTable()
	int_ty = table.ensure_int()
	opt_int = table.new_optional(int_ty)
	assert table.is_copy(opt_int) is True

	arr_ty = table.new_array(int_ty)
	opt_arr = table.new_optional(arr_ty)
	assert table.is_copy(opt_arr) is False
