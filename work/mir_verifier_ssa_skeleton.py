"""Skeleton of a strict-SSA MIR verifier.

This assumes:
  - Every SSA name is defined exactly once:
      * function params
      * block params
      * defining instructions (e.g. Move, Alloc)
  - No special cases for `_t*` or any other prefix.
"""

from dataclasses import dataclass, field
from typing import Dict, Set, List


@dataclass
class BlockInfo:
    defined: Set[str] = field(default_factory=set)
    used: Set[str] = field(default_factory=set)


class SSAVerifier:
    def __init__(self, func):
        self.func = func  # func.blocks: List[BasicBlock]
        self.global_defs: Dict[str, str] = {}

    def verify(self) -> None:
        # First pass: register all block params and function params as definitions.
        for block in self.func.blocks:
            self._register_block_params(block)

        # Second pass: visit instructions and terminators.
        for block in self.func.blocks:
            self._visit_block(block)

    # --- helpers -------------------------------------------------------

    def _define(self, ssa_name: str, where: str) -> None:
        if ssa_name in self.global_defs:
            prev = self.global_defs[ssa_name]
            raise RuntimeError(
                f"SSA name {ssa_name!r} defined twice: {prev} and {where}"
            )
        self.global_defs[ssa_name] = where

    def _use(self, ssa_name: str, where: str) -> None:
        if ssa_name not in self.global_defs:
            raise RuntimeError(
                f"SSA name {ssa_name!r} used before definition at {where}"
            )

    def _register_block_params(self, block) -> None:
        for p in block.params:
            self._define(p.name, where=f"block_param {block.name}")

    def _visit_block(self, block) -> None:
        # Instructions
        for instr in block.instructions:
            self._visit_instr(block, instr)

        # Terminator
        if block.terminator is not None:
            self._visit_terminator(block, block.terminator)

    def _visit_instr(self, block, instr) -> None:
        where = f"block {block.name}, instr {instr!r}"

        # This is a placeholder; adapt to your real MIR instruction set.
        from lowering_ssa_skeleton import Move  # or your real Move

        if isinstance(instr, Move):
            # dest is a def, source is a use
            self._define(instr.dest, where)
            self._use(instr.source, where)
        else:
            # handle other instruction kinds (binary ops, calls, etc.)
            pass

    def _visit_terminator(self, block, term) -> None:
        where = f"block {block.name}, terminator {term!r}"

        # Placeholder: assuming terminator is a tuple of (kind, payload)
        kind, payload = term
        if kind == "Br":
            edge = payload
            for arg in edge.args:
                self._use(arg, where)
        elif kind == "CondBr":
            cond = payload["cond"]
            self._use(cond, where)
            for edge in (payload["then"], payload["else"]):
                for arg in edge.args:
                    self._use(arg, where)
        else:
            # returns, etc.
            pass
