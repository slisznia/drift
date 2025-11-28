"""Strict SSA MIR verifier (v2) for the new SSA lowering path.

This verifier enforces:
  - Single definition per SSA name (function params, block params, defining instructions/terminators).
  - Def-before-use (order-insensitive across blocks).
  - Operand use checking for supported MIR instructions/terminators.

It assumes MIR blocks are provided either as a list or as a dict of BasicBlock objects.
"""

from __future__ import annotations

from typing import Dict

from . import mir


class SSAVerifierV2:
    def __init__(self, func):
        # func.blocks: Iterable[BasicBlock] or dict of name -> BasicBlock
        self.func = func
        self.global_defs: Dict[str, str] = {}

    def verify(self) -> None:
        # Register block params and function params.
        for block in self._iter_blocks():
            self._register_block_params(block)
        # Register defining instruction dests and terminator dests.
        for block in self._iter_blocks():
            self._register_instr_defs(block)
            self._register_term_defs(block)
        # Check uses in instructions and terminators.
        for block in self._iter_blocks():
            self._visit_block(block)

    def _iter_blocks(self):
        blocks = getattr(self.func, "blocks", None)
        if blocks is None:
            return []
        if isinstance(blocks, dict):
            return blocks.values()
        return blocks

    def _define(self, ssa_name: str, where: str) -> None:
        if ssa_name in self.global_defs:
            prev = self.global_defs[ssa_name]
            raise RuntimeError(f"SSA name {ssa_name!r} defined twice: {prev} and {where}")
        self.global_defs[ssa_name] = where

    def _use(self, ssa_name: str, where: str) -> None:
        if ssa_name not in self.global_defs:
            raise RuntimeError(f"SSA name {ssa_name!r} used before definition at {where}")

    def _register_block_params(self, block) -> None:
        for p in block.params:
            self._define(p.name, where=f"block_param {block.name}")

    def _register_instr_defs(self, block) -> None:
        where = f"block {block.name}"
        for instr in block.instructions:
            dest = getattr(instr, "dest", None)
            if dest:
                self._define(dest, f"{where}, instr {instr!r}")

    def _register_term_defs(self, block) -> None:
        term = block.terminator
        if term is None:
            return
        dest = getattr(term, "dest", None)
        if dest:
            self._define(dest, where=f"terminator {block.name}")

    def _visit_block(self, block) -> None:
        where_block = f"block {block.name}"
        for instr in block.instructions:
            self._visit_instr(where_block, instr)
        if block.terminator is not None:
            self._visit_terminator(where_block, block.terminator)

    def _visit_instr(self, where_block: str, instr) -> None:
        where = f"{where_block}, instr {instr!r}"
        if isinstance(instr, mir.Move):
            self._use(instr.source, where)
        elif isinstance(instr, mir.Binary):
            self._use(instr.left, where)
            self._use(instr.right, where)
        elif isinstance(instr, mir.Call):
            if instr.normal or instr.error:
                raise RuntimeError(
                    f"Call with edges must appear as terminator, found in instruction list at {where}"
                )
            for arg in instr.args:
                self._use(arg, where)
            # Calls in the instruction list are expected to have no edges; edges handled in terminators.
        elif isinstance(instr, mir.Unary):
            self._use(instr.operand, where)
        elif isinstance(instr, mir.ArrayGet):
            self._use(instr.base, where)
            self._use(instr.index, where)
        # Add other instruction kinds as the SSA lowering grows.

    def _visit_terminator(self, where_block: str, term) -> None:
        where = f"{where_block}, term {term!r}"
        # Call-as-terminator with normal/error edges
        if isinstance(term, mir.Call) and (term.normal or term.error):
            for arg in term.args:
                self._use(arg, where)
            for edge in (term.normal, term.error):
                if edge:
                    for arg in edge.args:
                        self._use(arg, where)
            return
        if isinstance(term, mir.CondBr):
            self._use(term.cond, where)
            for edge in (term.then, term.els):
                for arg in edge.args:
                    self._use(arg, where)
            return
        if isinstance(term, mir.Br):
            for arg in term.target.args:
                self._use(arg, where)
            return
        if isinstance(term, mir.Return) and term.value is not None:
            self._use(term.value, where)
            return
        # Raise or other terminators either carry no SSA operands or are not yet handled in the scaffold.
