from __future__ import annotations

from lang2.driftc.core.type_resolve_common import resolve_opaque_type
from lang2.driftc.core.types_core import TypeKind, TypeTable
from lang2.driftc.parser.ast import TypeExpr


def test_resolve_builtin_void_and_error_are_canonical():
	table = TypeTable()

	void_ty = resolve_opaque_type("Void", table)
	err_ty = resolve_opaque_type("Error", table)

	assert table.get(void_ty).kind is TypeKind.VOID
	assert void_ty == table.ensure_void()

	assert table.get(err_ty).kind is TypeKind.ERROR
	assert err_ty == table.ensure_error()


def test_resolve_fnresult_and_array_typeexpr():
	table = TypeTable()
	int_ty = table.ensure_int()
	err_ty = table.ensure_error()

	fnres_expr = TypeExpr(name="FnResult", args=[TypeExpr(name="Int"), TypeExpr(name="Error")])
	fnres_ty = resolve_opaque_type(fnres_expr, table)
	fnres_def = table.get(fnres_ty)

	assert fnres_def.kind is TypeKind.FNRESULT
	assert fnres_def.param_types == [int_ty, err_ty]

	arr_ty = resolve_opaque_type("Array<Int>", table)
	arr_def = table.get(arr_ty)

	assert arr_def.kind is TypeKind.ARRAY
	assert arr_def.param_types == [int_ty]


def test_resolve_tuple_fnresult():
	table = TypeTable()
	int_ty = table.ensure_int()
	err_ty = table.ensure_error()

	fnres_ty = resolve_opaque_type((int_ty, err_ty), table)

	fnres_def = table.get(fnres_ty)
	assert fnres_def.kind is TypeKind.FNRESULT
	assert fnres_def.param_types == [int_ty, err_ty]
