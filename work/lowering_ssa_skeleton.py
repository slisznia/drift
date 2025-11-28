"""Skeleton for SSA-based MIR lowering.

This is not a drop-in replacement; it's a scaffold showing how to use SSAEnv
and block params/edges to produce strict SSA.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple

from ssa_env import SSAEnv

# These are placeholders for your real MIR classes.
# Replace with imports from your existing MIR module.

@dataclass
class Param:
    name: str
    type: object

@dataclass
class Edge:
    target: str
    args: List[str]

@dataclass
class BasicBlock:
    name: str
    params: List[Param] = field(default_factory=list)
    instructions: List[object] = field(default_factory=list)
    terminator: object = None

@dataclass
class Move:
    dest: str
    source: str


def lower_function(fn_ast, type_ctx) -> Tuple[List[BasicBlock], SSAEnv]:
    """Lower a function AST to SSA MIR.

    - Creates an initial SSAEnv and binds function params to SSA names.
    - Creates an entry block with param SSA names.
    - Delegates body lowering to `lower_block_in_env`.
    """
    env = SSAEnv()
    blocks: Dict[str, BasicBlock] = {}

    # 1) Create entry block and param SSA names
    entry_name = f"{fn_ast.name}_entry"
    entry_block = BasicBlock(name=entry_name)

    for param in fn_ast.params:
        ty = type_ctx.lookup_param_type(fn_ast, param.name)
        ssa_name = env.fresh_ssa(param.name, ty)
        entry_block.params.append(Param(name=ssa_name, type=ty))
        env.bind_user(param.name, ssa_name, ty)

    blocks[entry_name] = entry_block

    # 2) Lower body in this env
    current_block = entry_block
    current_block = lower_block_in_env(fn_ast.body, env, blocks, current_block, type_ctx)

    # Expect current_block to end with a return terminator in a real compiler.
    return list(blocks.values()), env


def lower_block_in_env(stmts, env: SSAEnv, blocks: Dict[str, BasicBlock],
                       current: BasicBlock, type_ctx) -> BasicBlock:
    """Lower a sequence of statements under a given SSA env.

    This function shows how to handle let/assign and structured control flow
    while preserving SSA.
    """
    for stmt in stmts:
        kind = stmt.kind
        if kind == "let":
            current = lower_let(stmt, env, current, type_ctx)
        elif kind == "assign":
            current = lower_assign(stmt, env, current, type_ctx)
        elif kind == "if":
            current = lower_if(stmt, env, blocks, current, type_ctx)
        elif kind == "while":
            current = lower_while(stmt, env, blocks, current, type_ctx)
        else:
            # other statements omitted
            pass

    return current


def lower_let(stmt, env: SSAEnv, current: BasicBlock, type_ctx) -> BasicBlock:
    ty = type_ctx.infer_expr_type(stmt.value)
    val_ssa = lower_expr_to_ssa(stmt.value, env, current, type_ctx)
    dest_ssa = env.fresh_ssa(stmt.name, ty)
    current.instructions.append(Move(dest=dest_ssa, source=val_ssa))
    env.bind_user(stmt.name, dest_ssa, ty)
    return current


def lower_assign(stmt, env: SSAEnv, current: BasicBlock, type_ctx) -> BasicBlock:
    # Source-level: x = expr;
    # SSA: x_old = env[x]; expr uses env; x_new = expr; env[x] = x_new.
    if stmt.name not in env.user_env:
        raise RuntimeError(f"assignment to undeclared variable {stmt.name}")

    ty = type_ctx.infer_expr_type(stmt.value)
    val_ssa = lower_expr_to_ssa(stmt.value, env, current, type_ctx)
    dest_ssa = env.fresh_ssa(stmt.name, ty)
    current.instructions.append(Move(dest=dest_ssa, source=val_ssa))
    env.bind_user(stmt.name, dest_ssa, ty)
    return current


def lower_if(stmt, env: SSAEnv, blocks: Dict[str, BasicBlock],
             current: BasicBlock, type_ctx) -> BasicBlock:
    """Skeleton if/else lowering with φ via block params.

    This assumes a high-level AST with:
      - stmt.cond
      - stmt.then_body (list of stmts)
      - stmt.else_body (list of stmts or None)
    """
    # Evaluate condition to an SSA name (left as placeholder)
    cond_ssa = lower_expr_to_ssa(stmt.cond, env, current, type_ctx)

    then_name = f"{current.name}_then"
    else_name = f"{current.name}_else"
    join_name = f"{current.name}_join"

    then_block = BasicBlock(name=then_name)
    else_block = BasicBlock(name=else_name)
    join_block = BasicBlock(name=join_name)

    blocks[then_name] = then_block
    blocks[else_name] = else_block
    blocks[join_name] = join_block

    # Current block branches to then/else; arguments are current SSA versions.
    live_users = list(env.snapshot_live_user_names())
    then_args = [env.lookup_user(u) for u in live_users]
    else_args = [env.lookup_user(u) for u in live_users]

    current.terminator = ("CondBr", {
        "cond": cond_ssa,
        "then": Edge(target=then_name, args=then_args),
        "else": Edge(target=else_name, args=else_args),
    })

    # Build block params for join and envs for then/else/join
    join_params = []
    for u in live_users:
        # One φ param per live user
        phi_ssa = env.fresh_ssa(f"{u}_phi", ty=env.ssa_types[env.lookup_user(u)])
        join_params.append(Param(name=phi_ssa, type=env.ssa_types[env.lookup_user(u)]))

    join_block.params = join_params

    # Env for then and else start from current env (same mapping)
    then_env = env.clone_for_block({u: env.lookup_user(u) for u in live_users})
    else_env = env.clone_for_block({u: env.lookup_user(u) for u in live_users})

    # Lower then body
    lower_block_in_env(stmt.then_body, then_env, blocks, then_block, type_ctx)
    if then_block.terminator is None:
        # Fall through to join, passing then_env versions
        then_block.terminator = ("Br", Edge(
            target=join_name,
            args=[then_env.lookup_user(u) for u in live_users],
        ))

    # Lower else body
    if stmt.else_body is not None:
        lower_block_in_env(stmt.else_body, else_env, blocks, else_block, type_ctx)
    # else: else_env remains same as entry
    if else_block.terminator is None:
        else_block.terminator = ("Br", Edge(
            target=join_name,
            args=[else_env.lookup_user(u) for u in live_users],
        ))

    # Join env: map each user to the join param SSA name.
    join_env_map = {
        u: join_params[i].name
        for i, u in enumerate(live_users)
    }
    join_env = env.clone_for_block(join_env_map)

    # Continue lowering after the if using join_env in join_block
    return join_block  # caller must continue with join_env


def lower_while(stmt, env: SSAEnv, blocks: Dict[str, BasicBlock],
                current: BasicBlock, type_ctx) -> BasicBlock:
    """Skeleton while lowering with φ-style block params.

    while cond { body }
    """
    header_name = f"{current.name}_while_header"
    body_name = f"{current.name}_while_body"
    after_name = f"{current.name}_while_after"

    header_block = BasicBlock(name=header_name)
    body_block = BasicBlock(name=body_name)
    after_block = BasicBlock(name=after_name)

    blocks[header_name] = header_block
    blocks[body_name] = body_block
    blocks[after_name] = after_block

    # Initial jump from current -> header, passing current SSA versions
    live_users = list(env.snapshot_live_user_names())
    init_args = [env.lookup_user(u) for u in live_users]
    current.terminator = ("Br", Edge(target=header_name, args=init_args))

    # Header params (φ-like)
    header_params = []
    for u in live_users:
        phi_ssa = env.fresh_ssa(f"{u}_phi", ty=env.ssa_types[env.lookup_user(u)])
        header_params.append(Param(name=phi_ssa, type=env.ssa_types[env.lookup_user(u)]))
    header_block.params = header_params

    # Env in header
    header_env_map = {
        u: header_params[i].name
        for i, u in enumerate(live_users)
    }
    header_env = env.clone_for_block(header_env_map)

    # Lower condition in header
    cond_ssa = lower_expr_to_ssa(stmt.cond, header_env, header_block, type_ctx)

    # Build env for body starting from header_env
    body_env = header_env.clone_for_block({
        u: header_env.lookup_user(u) for u in live_users
    })

    # CondBr in header
    header_block.terminator = ("CondBr", {
        "cond": cond_ssa,
        "then": Edge(target=body_name, args=[body_env.lookup_user(u) for u in live_users]),
        "else": Edge(target=after_name, args=[header_env.lookup_user(u) for u in live_users]),
    })

    # Lower body
    lower_block_in_env(stmt.body, body_env, blocks, body_block, type_ctx)
    if body_block.terminator is None:
        # Backedge to header with updated SSA names
        body_block.terminator = ("Br", Edge(
            target=header_name,
            args=[body_env.lookup_user(u) for u in live_users],
        ))

    # After env uses header_env mapping; join semantics for after
    after_params = []
    for u in live_users:
        out_ssa = env.fresh_ssa(f"{u}_out", ty=env.ssa_types[env.lookup_user(u)])
        after_params.append(Param(name=out_ssa, type=env.ssa_types[env.lookup_user(u)]))
    after_block.params = after_params

    # Note: wiring the exact args into after from header's else edge and
    # any `break` targets would be needed in a full implementation.

    return after_block


def lower_expr_to_ssa(expr, env: SSAEnv, current: BasicBlock, type_ctx) -> str:
    """Placeholder: convert an expression to SSA, optionally emitting instructions.

    For now, pretend expressions are just existing user variables.
    """
    if expr.kind == "name":
        return env.lookup_user(expr.name)
    # For real expressions, you would allocate temps via env.fresh_ssa("t", ty)
    # and emit Moves/ops into `current.instructions`.
    raise NotImplementedError("lower_expr_to_ssa: only names handled in skeleton")
