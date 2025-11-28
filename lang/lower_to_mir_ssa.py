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
from .types import Type


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


def lower_expr_to_ssa(expr: ast.Expr, env: SSAEnv, current: mir.BasicBlock, checked: CheckedProgram) -> Tuple[str, Type]:
    """Placeholder expression lowering: handles names only."""
    if isinstance(expr, ast.Name):
        ssa = env.lookup_user(expr.ident)
        ty = env.ctx.ssa_types[ssa]
        return ssa, ty
    raise LoweringError("lower_expr_to_ssa scaffold handles names only")


def _infer_expr_type(expr: ast.Expr, checked: CheckedProgram) -> Type:
    # Placeholder: in real lowering, use the checker/type info.
    from .types import I64, STR, BOOL, F64
    if isinstance(expr, ast.Literal):
        if isinstance(expr.value, bool):
            return BOOL
        if isinstance(expr.value, int):
            return I64
        if isinstance(expr.value, float):
            return F64
        if isinstance(expr.value, str):
            return STR
    raise LoweringError("type inference scaffold incomplete")


class LoweringError(Exception):
    pass
