"""Simple SSA MIR simplification: fold constant scalars and drop dead pure defs.

Limited scope:
- Constant folding for integer/scalar Binary ops when both operands are Consts.
- Remove unused Const/Copy/Binary/Unary instructions.
- Do not reorder or cross side-effecting instructions; stores/calls/etc. are barriers and untouched.
"""

from __future__ import annotations

from typing import Dict, Set

from . import mir
from .types import BOOL


_INT_BIN_OPS = {"+", "-", "*", "/", "==", "!=", "<", "<=", ">", ">="}


def _fold_binary(op: str, lhs_val, rhs_val):
    if not isinstance(lhs_val, (int, bool)) or not isinstance(rhs_val, (int, bool)):
        return None
    if op == "+":
        return lhs_val + rhs_val
    if op == "-":
        return lhs_val - rhs_val
    if op == "*":
        return lhs_val * rhs_val
    if op == "/":
        return lhs_val // rhs_val if rhs_val != 0 else None
    if op == "==":
        return lhs_val == rhs_val
    if op == "!=":
        return lhs_val != rhs_val
    if op == "<":
        return lhs_val < rhs_val
    if op == "<=":
        return lhs_val <= rhs_val
    if op == ">":
        return lhs_val > rhs_val
    if op == ">=":
        return lhs_val >= rhs_val
    return None


def simplify_function(fn: mir.Function) -> mir.Function:
    """Return a simplified copy of the MIR function."""
    blocks: Dict[str, mir.BasicBlock] = {}
    for name, block in fn.blocks.items():
        const_values: Dict[str, object] = {}
        uses: Dict[str, int] = {}

        def note_use(val: str) -> None:
            uses[val] = uses.get(val, 0) + 1

        # First pass: collect const values and uses.
        for instr in block.instructions:
            if isinstance(instr, mir.Const):
                const_values[instr.dest] = instr.value
            # track uses for pure defs; side-effecting ops are barriers, but still record operand uses.
            if isinstance(instr, mir.Move):
                note_use(instr.source)
            elif isinstance(instr, mir.Binary):
                note_use(instr.left)
                note_use(instr.right)
            elif isinstance(instr, mir.Unary):
                note_use(instr.operand)
            elif isinstance(instr, mir.Copy):
                note_use(instr.source)
            elif isinstance(instr, mir.FieldGet):
                note_use(instr.base)
            elif isinstance(instr, mir.FieldSet):
                note_use(instr.base)
                note_use(instr.value)
            elif isinstance(instr, mir.ArrayGet):
                note_use(instr.base)
                note_use(instr.index)
            elif isinstance(instr, mir.ArraySet):
                note_use(instr.base)
                note_use(instr.index)
                note_use(instr.value)
            elif isinstance(instr, mir.StructInit):
                for a in instr.args:
                    note_use(a)
            elif isinstance(instr, mir.ArrayInit):
                for a in instr.elements:
                    note_use(a)
            elif isinstance(instr, mir.ArrayLiteral):
                for a in instr.elements:
                    note_use(a)
            elif isinstance(instr, mir.ArrayLen):
                note_use(instr.base)
            elif isinstance(instr, mir.Call):
                for a in instr.args:
                    note_use(a)
            elif isinstance(instr, mir.CallWithCtx):
                note_use(instr.ctx_dest)
                if instr.ctx_arg:
                    note_use(instr.ctx_arg)
                for a in instr.args:
                    note_use(a)
            elif isinstance(instr, mir.ConsoleWrite):
                note_use(instr.value)
            elif isinstance(instr, mir.ConsoleWriteln):
                note_use(instr.value)
            elif isinstance(instr, mir.Drop):
                note_use(instr.value)

        if block.terminator:
            term = block.terminator
            if isinstance(term, mir.CondBr):
                note_use(term.cond)
                for edge in (term.then, term.els):
                    for a in edge.args:
                        note_use(a)
            elif isinstance(term, mir.Br):
                for a in term.target.args:
                    note_use(a)
            elif isinstance(term, mir.Return) and term.value is not None:
                note_use(term.value)
            elif isinstance(term, mir.Call) and (term.normal or term.error):
                for a in term.args:
                    note_use(a)
                for edge in (term.normal, term.error):
                    if edge:
                        for a in edge.args:
                            note_use(a)
            elif isinstance(term, mir.Throw):
                note_use(term.error)

        new_instrs: list[mir.Instruction] = []
        for instr in block.instructions:
            # Fold pure binary ops with const operands.
            if isinstance(instr, mir.Binary) and instr.op in _INT_BIN_OPS:
                lhs_val = const_values.get(instr.left)
                rhs_val = const_values.get(instr.right)
                folded = _fold_binary(instr.op, lhs_val, rhs_val)
                if folded is not None:
                    new_instrs.append(
                        mir.Const(dest=instr.dest, type=BOOL if isinstance(folded, bool) else instr.type, value=folded)
                    )
                    const_values[instr.dest] = folded
                    continue
            # Dead pure defs: drop if never used.
            if isinstance(instr, (mir.Const, mir.Copy, mir.Binary, mir.Unary, mir.Move, mir.ArrayLen)):
                dest = getattr(instr, "dest", None)
                if dest and uses.get(dest, 0) == 0:
                    continue
            new_instrs.append(instr)
        new_block = mir.BasicBlock(name=block.name, params=list(block.params), instructions=new_instrs, terminator=block.terminator)
        blocks[name] = new_block
    return mir.Function(
        name=fn.name,
        params=fn.params,
        return_type=fn.return_type,
        entry=fn.entry,
        module=fn.module,
        source=fn.source,
        blocks=blocks,
    )
