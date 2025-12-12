from __future__ import annotations

from lang2.driftc.core.types_core import TypeTable, TypeKind


def test_type_table_registers_basic_kinds():
	table = TypeTable()
	int_ty = table.new_scalar("Int")
	bool_ty = table.new_scalar("Bool")
	err_ty = table.new_error("Error")
	fnres_ty = table.new_fnresult(int_ty, err_ty)
	fn_ty = table.new_function("foo", [int_ty], bool_ty)
	unknown_ty = table.new_unknown()

	assert table.get(int_ty).kind is TypeKind.SCALAR
	assert table.get(int_ty).name == "Int"

	assert table.get(err_ty).kind is TypeKind.ERROR

	fnres_def = table.get(fnres_ty)
	assert fnres_def.kind is TypeKind.FNRESULT
	assert fnres_def.param_types == [int_ty, err_ty]

	fn_def = table.get(fn_ty)
	assert fn_def.kind is TypeKind.FUNCTION
	assert fn_def.param_types == [int_ty, bool_ty]

	assert table.get(unknown_ty).kind is TypeKind.UNKNOWN


def test_type_table_seeds_void():
	table = TypeTable()

	void_ty = table.ensure_void()

	# Canonical Void is a dedicated kind and id should be stable.
	assert table.get(void_ty).kind is TypeKind.VOID
	assert void_ty == table.ensure_void()


def test_type_table_seeds_error_canonically():
	table = TypeTable()

	err_ty = table.ensure_error()

	assert table.get(err_ty).kind is TypeKind.ERROR
	assert table.get(err_ty).name == "Error"
	assert err_ty == table.ensure_error()


def test_type_table_seeds_diagnostic_value_and_optional():
	table = TypeTable()
	dv_ty = table.ensure_diagnostic_value()
	opt_int = table.new_optional(table.ensure_int())
	opt_int_again = table.new_optional(table.ensure_int())

	assert table.get(dv_ty).kind is TypeKind.DIAGNOSTICVALUE
	assert dv_ty == table.ensure_diagnostic_value()
	assert table.get(opt_int).kind is TypeKind.OPTIONAL
	assert table.get(opt_int).param_types == [table.ensure_int()]
	# Optional cache should reuse the same id for the same inner.
	assert opt_int == opt_int_again
