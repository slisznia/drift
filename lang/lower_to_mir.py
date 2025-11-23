from __future__ import annotations

from typing import Dict, Tuple

from . import ast, mir
from .checker import CheckedProgram
from .types import BOOL, F64, I64, STR, Type


class LoweringError(Exception):
    pass


def lower_straightline(checked: CheckedProgram) -> mir.Program:
    """
    Minimal lowering for straight-line functions (no control flow) supporting:
    - params
    - literals
    - names
    - binary ops
    - return
    """
    if not checked.program.functions:
        raise LoweringError("no functions to lower")
    fn_def = checked.program.functions[0]
    fn_info = checked.functions[fn_def.name]

    temp_counter = 0

    def fresh() -> str:
        nonlocal temp_counter
        temp_counter += 1
        return f"_t{temp_counter}"

    block_params = [mir.Param(name=p.name, type=fn_info.signature.params[idx]) for idx, p in enumerate(fn_def.params)]
    block = mir.BasicBlock(name="bb0", params=block_params)

    def lower_expr(expr: ast.Expr) -> Tuple[str, Type]:
        if isinstance(expr, ast.Literal):
            dest = fresh()
            lit_val = expr.value
            lit_type = _type_of_literal(lit_val)
            block.instructions.append(mir.Const(dest=dest, type=lit_type, value=lit_val))
            return dest, lit_type
        if isinstance(expr, ast.Name):
            # assume param or previously defined temp
            ty = _lookup_type(expr.ident, block_params, temp_types)
            return expr.ident, ty
        if isinstance(expr, ast.Binary):
            lhs, lhs_ty = lower_expr(expr.left)
            rhs, rhs_ty = lower_expr(expr.right)
            dest = fresh()
            block.instructions.append(mir.Binary(dest=dest, op=expr.op, left=lhs, right=rhs))
            temp_types[dest] = lhs_ty  # naive: assume types match
            return dest, lhs_ty
        raise LoweringError(f"unsupported expression: {expr}")

    temp_types: Dict[str, Type] = {}

    for stmt in fn_def.body.statements:
        if isinstance(stmt, ast.ReturnStmt):
            if stmt.value is None:
                block.terminator = mir.Return()
            else:
                val, _ = lower_expr(stmt.value)
                block.terminator = mir.Return(value=val)
        else:
            raise LoweringError(f"unsupported statement: {stmt}")

    fn = mir.Function(
        name=fn_def.name,
        params=[mir.Param(name=p.name, type=fn_info.signature.params[idx]) for idx, p in enumerate(fn_def.params)],
        return_type=fn_info.signature.return_type,
        entry=block.name,
        blocks={block.name: block},
    )
    return mir.Program(functions={fn.name: fn})


def _lookup_type(name: str, params, temps: Dict[str, Type]) -> Type:
    for p in params:
        if p.name == name:
            return p.type
    if name in temps:
        return temps[name]
    return Type("<unknown>")


def _type_of_literal(value) -> Type:
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, int):
        return I64
    if isinstance(value, float):
        return F64
    if isinstance(value, str):
        return STR
    return Type("<unknown>")
