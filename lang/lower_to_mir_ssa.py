"""Skeleton strict-SSA lowering for Drift MIR.

This is a scaffold to guide the eventual rewrite of lower_to_mir into a strict
SSA form. It is not wired into the compiler yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from . import ast, mir
from .checker import CheckedProgram
from .ssa_env import SSAEnv, SSAContext
from .types import Type, BOOL, I64, F64, STR, array_element_type


@dataclass
class LoweredFunction:
    blocks: Dict[str, mir.BasicBlock]
    env: SSAEnv


def lower_function_ssa(fn_def: ast.FunctionDef, checked: CheckedProgram) -> LoweredFunction:
    """Lower a single function into SSA MIR blocks (scaffold only)."""
    fn_info = checked.functions[fn_def.name]
    ctx = SSAContext()
    env = SSAEnv(ctx=ctx)
    blocks: Dict[str, mir.BasicBlock] = {}
    block_counter = 0

    def fresh_block(prefix: str) -> str:
        nonlocal block_counter
        block_counter += 1
        return f"{prefix}{block_counter}"

    entry_name = "bb0"
    entry_block = mir.BasicBlock(name=entry_name, params=[])
    blocks[entry_name] = entry_block

    # Bind params to fresh SSA names
    for idx, p in enumerate(fn_def.params):
        ty = fn_info.signature.params[idx]
        ssa_name = env.fresh_ssa(p.name, ty)
        entry_block.params.append(mir.Param(name=ssa_name, type=ty))
        env.bind_user(p.name, ssa_name, ty)

    # Lower body (placeholder)
    current, env = lower_block_in_env(fn_def.body.statements, env, blocks, entry_block, checked, fresh_block)

    return LoweredFunction(blocks=blocks, env=env)


def lower_block_in_env(
    stmts: List[ast.Stmt],
    env: SSAEnv,
    blocks: Dict[str, mir.BasicBlock],
    current: mir.BasicBlock,
    checked: CheckedProgram,
    fresh_block: callable,
) -> Tuple[mir.BasicBlock, SSAEnv]:
    """Lower a sequence of statements under a given SSA env (scaffold)."""
    for stmt in stmts:
        if isinstance(stmt, ast.LetStmt):
            current, env = lower_let(stmt, env, current, checked)
        elif isinstance(stmt, ast.AssignStmt):
            current, env = lower_assign(stmt, env, current, checked)
        elif isinstance(stmt, ast.IfStmt):
            current, env = lower_if(stmt, env, blocks, current, checked, fresh_block)
        elif isinstance(stmt, ast.ReturnStmt):
            # Scaffold: return without building pair ABI; assumes expression lowered elsewhere.
            if stmt.value is None:
                current.terminator = mir.Return()
            else:
                val_ssa, _ = lower_expr_to_ssa(stmt.value, env, current, checked)
                current.terminator = mir.Return(value=val_ssa)
            return current, env
        elif isinstance(stmt, ast.WhileStmt):
            current, env = lower_while(stmt, env, blocks, current, checked, fresh_block)
        else:
            # Other statements (if/while/try) to be filled in later.
            pass
    return current, env


def lower_let(
    stmt: ast.LetStmt, env: SSAEnv, current: mir.BasicBlock, checked: CheckedProgram
) -> Tuple[mir.BasicBlock, SSAEnv]:
    val_ssa, val_ty = lower_expr_to_ssa(stmt.value, env, current, checked)
    dest_ssa = env.fresh_ssa(stmt.name, val_ty)
    current.instructions.append(mir.Move(dest=dest_ssa, source=val_ssa))
    env.bind_user(stmt.name, dest_ssa, val_ty)
    return current, env


def lower_assign(
    stmt: ast.AssignStmt, env: SSAEnv, current: mir.BasicBlock, checked: CheckedProgram
) -> Tuple[mir.BasicBlock, SSAEnv]:
    if not env.has_user(stmt.target.ident):
        raise LoweringError(f"assignment to undeclared variable {stmt.target.ident}")
    val_ssa, val_ty = lower_expr_to_ssa(stmt.value, env, current, checked)
    dest_ssa = env.fresh_ssa(stmt.target.ident, val_ty)
    current.instructions.append(mir.Move(dest=dest_ssa, source=val_ssa))
    env.bind_user(stmt.target.ident, dest_ssa, val_ty)
    return current, env


def lower_if(
    stmt: ast.IfStmt,
    env: SSAEnv,
    blocks: Dict[str, mir.BasicBlock],
    current: mir.BasicBlock,
    checked: CheckedProgram,
    fresh_block: callable,
) -> Tuple[mir.BasicBlock, SSAEnv]:
    """SSA if/else lowering with block params as φ (scaffold)."""
    cond_ssa, _ = lower_expr_to_ssa(stmt.condition, env, current, checked)

    then_name = fresh_block("bb_then")
    else_name = fresh_block("bb_else")
    join_name = fresh_block("bb_join")

    then_block = mir.BasicBlock(name=then_name)
    else_block = mir.BasicBlock(name=else_name)
    join_block = mir.BasicBlock(name=join_name)

    blocks[then_name] = then_block
    blocks[else_name] = else_block
    blocks[join_name] = join_block

    live_users = list(env.snapshot_live_user_names())
    then_args = [env.lookup_user(u) for u in live_users]
    else_args = [env.lookup_user(u) for u in live_users]

    current.terminator = mir.CondBr(
        cond=cond_ssa,
        then=mir.Edge(target=then_name, args=then_args),
        els=mir.Edge(target=else_name, args=else_args),
    )

    # Join params (fresh SSA) and branch envs.
    join_params: list[mir.Param] = []
    for u in live_users:
        ty = env.ctx.ssa_types[env.lookup_user(u)]
        phi_ssa = env.fresh_ssa(f"{u}_phi", ty=ty)
        join_params.append(mir.Param(name=phi_ssa, type=ty))
    join_block.params = join_params

    then_env = env.clone_for_block({u: env.lookup_user(u) for u in live_users})
    else_env = env.clone_for_block({u: env.lookup_user(u) for u in live_users})

    then_block, then_env = lower_block_in_env(stmt.then_block.statements, then_env, blocks, then_block, checked, fresh_block)
    if then_block.terminator is None:
        then_block.terminator = mir.Br(
            target=mir.Edge(target=join_name, args=[then_env.lookup_user(u) for u in live_users])
        )

    if stmt.else_block:
        else_block, else_env = lower_block_in_env(stmt.else_block.statements, else_env, blocks, else_block, checked, fresh_block)
    if else_block.terminator is None:
        else_block.terminator = mir.Br(
            target=mir.Edge(target=join_name, args=[else_env.lookup_user(u) for u in live_users])
        )

    join_env_map = {u: join_params[i].name for i, u in enumerate(live_users)}
    join_env = env.clone_for_block(join_env_map)

    return join_block, join_env


def lower_while(
    stmt: ast.WhileStmt,
    env: SSAEnv,
    blocks: Dict[str, mir.BasicBlock],
    current: mir.BasicBlock,
    checked: CheckedProgram,
    fresh_block: callable,
) -> Tuple[mir.BasicBlock, SSAEnv]:
    """SSA while lowering with block params as φ (scaffold)."""
    header_name = fresh_block("bb_while_header")
    body_name = fresh_block("bb_while_body")
    after_name = fresh_block("bb_while_after")

    header_block = mir.BasicBlock(name=header_name)
    body_block = mir.BasicBlock(name=body_name)
    after_block = mir.BasicBlock(name=after_name)

    blocks[header_name] = header_block
    blocks[body_name] = body_block
    blocks[after_name] = after_block

    live_users = list(env.snapshot_live_user_names())
    init_args = [env.lookup_user(u) for u in live_users]
    current.terminator = mir.Br(target=mir.Edge(target=header_name, args=init_args))

    # Header params (phi-like)
    header_params: list[mir.Param] = []
    for u in live_users:
        ty = env.ctx.ssa_types[env.lookup_user(u)]
        phi_ssa = env.fresh_ssa(f"{u}_phi", ty=ty)
        header_params.append(mir.Param(name=phi_ssa, type=ty))
    header_block.params = header_params

    header_env = env.clone_for_block({u: header_params[i].name for i, u in enumerate(live_users)})

    # Lower condition
    cond_ssa, _ = lower_expr_to_ssa(stmt.condition, header_env, header_block, checked)

    # Prepare body env starting from header env
    body_env = header_env.clone_for_block({u: header_env.lookup_user(u) for u in live_users})

    header_block.terminator = mir.CondBr(
        cond=cond_ssa,
        then=mir.Edge(target=body_name, args=[body_env.lookup_user(u) for u in live_users]),
        els=mir.Edge(target=after_name, args=[header_env.lookup_user(u) for u in live_users]),
    )

    # Lower body
    body_block, body_env = lower_block_in_env(stmt.body.statements, body_env, blocks, body_block, checked, fresh_block)
    if body_block.terminator is None:
        body_block.terminator = mir.Br(
            target=mir.Edge(target=header_name, args=[body_env.lookup_user(u) for u in live_users])
        )

    # After env maps live users to header params (loop exit).
    after_params: list[mir.Param] = []
    for u in live_users:
        ty = env.ctx.ssa_types[env.lookup_user(u)]
        out_ssa = env.fresh_ssa(f"{u}_out", ty=ty)
        after_params.append(mir.Param(name=out_ssa, type=ty))
    after_block.params = after_params

    after_env = env.clone_for_block({u: after_params[i].name for i, u in enumerate(live_users)})
    return after_block, after_env


def lower_expr_to_ssa(expr: ast.Expr, env: SSAEnv, current: mir.BasicBlock, checked: CheckedProgram) -> Tuple[str, Type]:
    """Lower an expression to SSA, emitting instructions into the current block."""
    # Names
    if isinstance(expr, ast.Name):
        ssa = env.lookup_user(expr.ident)
        ty = env.ctx.ssa_types.get(ssa)
        if ty is None:
            raise LoweringError(f"unknown type for SSA name '{ssa}'")
        return ssa, ty
    # Literals
    if isinstance(expr, ast.Literal):
        lit_val = expr.value
        lit_ty = _type_of_literal(lit_val)
        dest = env.fresh_ssa("lit", lit_ty)
        current.instructions.append(mir.Const(dest=dest, type=lit_ty, value=lit_val, loc=getattr(expr, "loc", None)))
        env.ctx.ssa_types[dest] = lit_ty
        return dest, lit_ty
    # Binary ops
    if isinstance(expr, ast.Binary):
        lhs, lhs_ty = lower_expr_to_ssa(expr.left, env, current, checked)
        rhs, rhs_ty = lower_expr_to_ssa(expr.right, env, current, checked)
        loc = getattr(expr, "loc", None)
        # String equality/inequality routed via runtime helper.
        if lhs_ty == STR and rhs_ty == STR and expr.op in {"==", "!="}:
            dest = env.fresh_ssa("strcmp", BOOL)
            current.instructions.append(
                mir.Call(
                    dest=dest,
                    callee="drift_string_eq",
                    args=[lhs, rhs],
                    ret_type=BOOL,
                    err_dest=None,
                    normal=None,
                    error=None,
                    loc=loc,
                )
            )
            env.ctx.ssa_types[dest] = BOOL
            # If op is !=, add a not.
            if expr.op == "!=":
                inv_dest = env.fresh_ssa("not", BOOL)
                current.instructions.append(
                    mir.Unary(dest=inv_dest, op="not", operand=dest, loc=loc)
                )
                env.ctx.ssa_types[inv_dest] = BOOL
                return inv_dest, BOOL
            return dest, BOOL
        dest = env.fresh_ssa("bin")
        current.instructions.append(mir.Binary(dest=dest, op=expr.op, left=lhs, right=rhs, loc=loc))
        if expr.op in {"==", "!=", "<", "<=", ">", ">="}:
            res_ty = BOOL
        else:
            res_ty = lhs_ty
        env.ctx.ssa_types[dest] = res_ty
        return dest, res_ty
    # Calls (simple name callee, no error edges in scaffold)
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
        callee = expr.func.ident
        if callee not in checked.functions:
            raise LoweringError(f"unknown function '{callee}' in SSA lowering")
        arg_ssa: List[str] = []
        for a in expr.args:
            v, _ = lower_expr_to_ssa(a, env, current, checked)
            arg_ssa.append(v)
        ret_ty = checked.functions[callee].signature.return_type
        dest = env.fresh_ssa(callee, ret_ty)
        current.instructions.append(
            mir.Call(dest=dest, callee=callee, args=arg_ssa, ret_type=ret_ty, err_dest=None, normal=None, error=None, loc=getattr(expr, "loc", None))
        )
        env.ctx.ssa_types[dest] = ret_ty
        return dest, ret_ty
    # Array indexing
    if isinstance(expr, ast.Index):
        base_ssa, base_ty = lower_expr_to_ssa(expr.value, env, current, checked)
        idx_ssa, idx_ty = lower_expr_to_ssa(expr.index, env, current, checked)
        elem_ty = array_element_type(base_ty)
        if elem_ty is None:
            raise LoweringError(f"type {base_ty} is not indexable")
        dest = env.fresh_ssa("idx", elem_ty)
        current.instructions.append(
            mir.ArrayGet(dest=dest, base=base_ssa, index=idx_ssa, loc=getattr(expr, "loc", None))
        )
        env.ctx.ssa_types[dest] = elem_ty
        return dest, elem_ty
    if isinstance(expr, ast.Attr):
        # Field access requires real field type info; not supported in the scaffold yet.
        raise LoweringError("field access not yet supported in SSA lowering (needs real field type lookup)")
    raise LoweringError(f"lower_expr_to_ssa scaffold does not handle {expr}")


def _infer_expr_type(expr: ast.Expr, checked: CheckedProgram) -> Type:
    # Placeholder: not used by SSA lowering paths; kept for compatibility.
    raise LoweringError("type inference scaffold incomplete")


def _type_of_literal(value: object) -> Type:
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, int):
        return I64
    if isinstance(value, float):
        return F64
    if isinstance(value, str):
        return STR
    raise LoweringError(f"unsupported literal {value!r}")


class LoweringError(Exception):
    pass
