"""SSA environment helpers for Drift MIR lowering.

This module is intentionally minimal. It is intended to be used by a future
strict-SSA lowering path; current lowering still uses the older mutable-locals
style.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

from .types import Type


@dataclass
class SSAContext:
    """Function-global SSA state (shared across block envs)."""

    counter: int = 0
    ssa_types: Dict[str, Type] = field(default_factory=dict)


@dataclass
class SSAEnv:
    """Per-block SSA environment, sharing a function-global context.

    - `ctx` holds the global SSA counter and type table for the function.
    - `user_env` maps user-level names (strings from the source) to SSA names.

    MIR must *only* use SSA names; user names never appear directly in MIR.
    """

    ctx: SSAContext
    user_env: Dict[str, str] = field(default_factory=dict)

    def fresh_ssa(self, prefix: str, ty: Optional[Type] = None) -> str:
        """Return a fresh SSA name like `_x0`, `_t3`, `_phi7`.

        If `ty` is provided, record it in the shared `ssa_types`.
        """
        name = f"_{prefix}{self.ctx.counter}"
        self.ctx.counter += 1
        if ty is not None:
            self.ctx.ssa_types[name] = ty
        return name

    # --- user-vars -----------------------------------------------------

    def bind_user(self, user_name: str, ssa_name: str, ty: Optional[Type] = None) -> None:
        """Bind a user variable to an SSA name and record its type (if given)."""
        self.user_env[user_name] = ssa_name
        if ty is not None:
            self.ctx.ssa_types[ssa_name] = ty

    def lookup_user(self, user_name: str) -> str:
        """Lookup current SSA name for a user variable.

        Caller should ensure the name is declared; if not, raise a compiler error
        in the caller, not here.
        """
        return self.user_env[user_name]

    def has_user(self, user_name: str) -> bool:
        return user_name in self.user_env

    # --- block-scoped cloning ------------------------------------------

    def clone_for_block(self, params: Dict[str, str]) -> "SSAEnv":
        """Create a child env for a block from parameter SSA names.

        `params` maps user_name -> param_ssa_name for that block.
        The child shares the function-global counter/type table via ctx.
        """
        return SSAEnv(ctx=self.ctx, user_env=dict(params))

    def snapshot_live_user_names(self) -> Iterable[str]:
        """Return current live user names (keys of user_env).

        Structured lowering can use this to decide which locals to carry
        through block params.
        """
        return list(self.user_env.keys())
