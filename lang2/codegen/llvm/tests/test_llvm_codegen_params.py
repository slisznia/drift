from lang2.driftc.core.function_id import FunctionId
# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-10
"""
Headers and call lowering for typed parameters (Int, String).
"""

from lang2.driftc.checker import FnInfo, FnSignature
from lang2.driftc.core.types_core import TypeTable
from lang2.driftc.stage2 import BasicBlock, Call, ConstInt, ConstString, MirFunc, Return
from lang2.driftc.stage4.ssa import MirToSSA
from lang2.codegen.llvm import lower_module_to_llvm


def _int_and_string_types():
    table = TypeTable()
    int_ty = table.new_scalar("Int")
    str_ty = table.new_scalar("String")
    table._int_type = int_ty  # type: ignore[attr-defined]
    table._string_type = str_ty  # type: ignore[attr-defined]
    return table, int_ty, str_ty


def _fn_type(table: TypeTable, int_ty: int, *, can_throw: bool) -> int:
    return table.ensure_function("fn", [int_ty], int_ty, can_throw=can_throw)


def test_int_param_header_and_call():
    table, int_ty, _ = _int_and_string_types()

    # add(x: Int, y: Int) returns Int { return x }
    add_block = BasicBlock(name="entry", instructions=[], terminator=Return(value="x"))
    add_id = FunctionId(module="main", name="add", ordinal=0)
    add = MirFunc(fn_id=add_id, name="add", params=["x", "y"], locals=[], blocks={"entry": add_block}, entry="entry")
    add_ssa = MirToSSA().run(add)
    add_sig = FnSignature(name="add", param_type_ids=[int_ty, int_ty], return_type_id=int_ty)
    add_info = FnInfo(fn_id=add_id, name="add", declared_can_throw=False, signature=add_sig, return_type_id=int_ty)

    # main() returns Int { return add(1, 2) }
    main_block = BasicBlock(
        name="entry",
        instructions=[
            ConstInt(dest="t0", value=1),
            ConstInt(dest="t1", value=2),
            Call(dest="t2", fn_id=add_id, args=["t0", "t1"], can_throw=False),
        ],
        terminator=Return(value="t2"),
    )
    main_id = FunctionId(module="main", name="main", ordinal=0)
    main = MirFunc(fn_id=main_id, name="main", params=[], locals=["t0", "t1", "t2"], blocks={"entry": main_block}, entry="entry")
    main_ssa = MirToSSA().run(main)
    main_sig = FnSignature(name="main", param_type_ids=[], return_type_id=int_ty)
    main_info = FnInfo(fn_id=main_id, name="main", declared_can_throw=False, signature=main_sig, return_type_id=int_ty)

    mod = lower_module_to_llvm(
        {add_id: add, main_id: main},
        {add_id: add_ssa, main_id: main_ssa},
        {add_id: add_info, main_id: main_info},
        type_table=table,
    )
    ir = mod.render()

    assert "define i64 @add(i64 %x, i64 %y)" in ir
    assert "define i64 @main()" in ir
    assert "call i64 @add(i64 %t0, i64 %t1)" in ir


def test_mixed_int_string_params_and_return():
    table, int_ty, str_ty = _int_and_string_types()

    # combine(x: Int, s: String) returns String { return s }
    comb_block = BasicBlock(name="entry", instructions=[], terminator=Return(value="s"))
    comb_id = FunctionId(module="main", name="combine", ordinal=0)
    comb = MirFunc(fn_id=comb_id, name="combine", params=["x", "s"], locals=[], blocks={"entry": comb_block}, entry="entry")
    comb_ssa = MirToSSA().run(comb)
    comb_sig = FnSignature(name="combine", param_type_ids=[int_ty, str_ty], return_type_id=str_ty)
    comb_info = FnInfo(fn_id=comb_id, name="combine", declared_can_throw=False, signature=comb_sig, return_type_id=str_ty)

    # main() returns String { return combine(1, "abc") }
    main_block = BasicBlock(
        name="entry",
        instructions=[
            ConstInt(dest="t0", value=1),
            ConstString(dest="t1", value="abc"),
            Call(dest="t2", fn_id=comb_id, args=["t0", "t1"], can_throw=False),
        ],
        terminator=Return(value="t2"),
    )
    main_id = FunctionId(module="main", name="main", ordinal=0)
    main = MirFunc(fn_id=main_id, name="main", params=[], locals=["t0", "t1", "t2"], blocks={"entry": main_block}, entry="entry")
    main_ssa = MirToSSA().run(main)
    main_sig = FnSignature(name="main", param_type_ids=[], return_type_id=str_ty)
    main_info = FnInfo(fn_id=main_id, name="main", declared_can_throw=False, signature=main_sig, return_type_id=str_ty)

    mod = lower_module_to_llvm(
        {comb_id: comb, main_id: main},
        {comb_id: comb_ssa, main_id: main_ssa},
        {comb_id: comb_info, main_id: main_info},
        type_table=table,
    )
    ir = mod.render()

    assert "define %DriftString @combine(i64 %x, %DriftString %s)" in ir
    assert "define %DriftString @main()" in ir
    assert "call %DriftString @combine(i64 %t0, %DriftString %t1)" in ir


def test_fnptr_param_headers():
    table, int_ty, _ = _int_and_string_types()
    fnptr_nothrow = _fn_type(table, int_ty, can_throw=False)
    fnptr_throwing = _fn_type(table, int_ty, can_throw=True)

    # apply(f: fn(Int) nothrow returns Int, x: Int) returns Int { return x }
    apply_block = BasicBlock(name="entry", instructions=[], terminator=Return(value="x"))
    apply_id = FunctionId(module="main", name="apply", ordinal=0)
    apply = MirFunc(fn_id=apply_id, name="apply", params=["f", "x"], locals=[], blocks={"entry": apply_block}, entry="entry")
    apply_ssa = MirToSSA().run(apply)
    apply_sig = FnSignature(name="apply", param_type_ids=[fnptr_nothrow, int_ty], return_type_id=int_ty)
    apply_info = FnInfo(fn_id=apply_id, name="apply", declared_can_throw=False, signature=apply_sig, return_type_id=int_ty)

    # apply_ct(f: fn(Int) returns Int, x: Int) returns Int { return x }
    apply_ct_block = BasicBlock(name="entry", instructions=[], terminator=Return(value="x"))
    apply_ct_id = FunctionId(module="main", name="apply_ct", ordinal=0)
    apply_ct = MirFunc(fn_id=apply_ct_id, name="apply_ct", params=["f", "x"], locals=[], blocks={"entry": apply_ct_block}, entry="entry")
    apply_ct_ssa = MirToSSA().run(apply_ct)
    apply_ct_sig = FnSignature(name="apply_ct", param_type_ids=[fnptr_throwing, int_ty], return_type_id=int_ty)
    apply_ct_info = FnInfo(fn_id=apply_ct_id, name="apply_ct", declared_can_throw=False, signature=apply_ct_sig, return_type_id=int_ty)

    mod = lower_module_to_llvm(
        {apply_id: apply, apply_ct_id: apply_ct},
        {apply_id: apply_ssa, apply_ct_id: apply_ct_ssa},
        {apply_id: apply_info, apply_ct_id: apply_ct_info},
        type_table=table,
    )
    ir = mod.render()

    assert "define i64 @apply(i64 (i64)* %f, i64 %x)" in ir
    assert "define i64 @apply_ct(%FnResult_Int_Error (i64)* %f, i64 %x)" in ir
