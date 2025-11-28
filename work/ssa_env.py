"""SSA environment helpers for Drift MIR lowering.

This module is intentionally stand-alone and minimal. Integrate into your compiler
by wiring it into your existing AST/MIR modules.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Iterable


@dataclass
class SSAEnv:
    """Per-function SSA environment.

    - `user_env` maps user-level names (strings from the source) to SSA names.
    - `ssa_types` maps SSA names to type objects (whatever your type system uses).
    - `counter` guarantees uniqueness of SSA names within this function.

    MIR must *only* use SSA names; user names never appear directly in MIR.
    """

    user_env: Dict[str, str] = field(default_factory=dict)
    ssa_types: Dict[str, object] = field(default_factory=dict)
    counter: int = 0

    def fresh_ssa(self, prefix: str, ty: Optional[object] = None) -> str:
        """Return a fresh SSA name like `_x0`, `_t3`, `_phi7`.

        If `ty` is provided, record it in `ssa_types`.
        """
        name = f"_{prefix}{self.counter}"
        self.counter += 1
        if ty is not None:
            self.ssa_types[name] = ty
        return name

    # --- user-vars -----------------------------------------------------

    def bind_user(self, user_name: str, ssa_name: str, ty: Optional[object] = None) -> None:
        """Bind a user variable to an SSA name and record its type (if given)."""
        self.user_env[user_name] = ssa_name
        if ty is not None:
            self.ssa_types[ssa_name] = ty

    def lookup_user(self, user_name: str) -> str:
        """Lookup current SSA name for a user variable.

        Caller should ensure the name is declared; if not, raise a compiler error
        in the caller, not here.
        """
        return self.user_env[user_name]

    # --- block-scoped cloning ------------------------------------------

    def clone_for_block(self, params: Dict[str, str]) -> "SSAEnv":
        """Create a child env for a block from parameter SSA names.

        `params` maps user_name -> param_ssa_name for that block.
        This is the only way to construct a block env for multi-pred blocks.
        """
        child = SSAEnv()
        child.counter = self.counter
        child.ssa_types = dict(self.ssa_types)
        child.user_env = dict(params)
        return child

    def snapshot_live_user_names(self) -> Iterable[str]:
        """Return current live user names (keys of user_env).

        Structured lowering can use this to decide which locals to carry
        through block params.
        """
        return list(self.user_env.keys())
