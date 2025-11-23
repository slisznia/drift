from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .types import Type


Value = str


@dataclass(frozen=True)
class Param:
    name: str
    type: Type


@dataclass(frozen=True)
class Edge:
    target: str
    args: List[Value] = field(default_factory=list)


class Instruction:
    pass


@dataclass(frozen=True)
class Const(Instruction):
    dest: Value
    type: Type
    value: object


@dataclass(frozen=True)
class Move(Instruction):
    dest: Value
    source: Value


@dataclass(frozen=True)
class Copy(Instruction):
    dest: Value
    source: Value


@dataclass(frozen=True)
class Call(Instruction):
    dest: Value
    callee: str
    args: List[Value]
    normal: Edge
    error: Edge


@dataclass(frozen=True)
class StructInit(Instruction):
    dest: Value
    type: Type
    args: List[Value]


@dataclass(frozen=True)
class FieldGet(Instruction):
    dest: Value
    base: Value
    field: str


@dataclass(frozen=True)
class ArrayInit(Instruction):
    dest: Value
    elements: List[Value]
    element_type: Type


@dataclass(frozen=True)
class ArrayGet(Instruction):
    dest: Value
    base: Value
    index: Value


@dataclass(frozen=True)
class ArraySet(Instruction):
    base: Value
    index: Value
    value: Value


@dataclass(frozen=True)
class Unary(Instruction):
    dest: Value
    op: str
    operand: Value


@dataclass(frozen=True)
class Binary(Instruction):
    dest: Value
    op: str
    left: Value
    right: Value


@dataclass(frozen=True)
class Drop(Instruction):
    value: Value


class Terminator:
    pass


@dataclass(frozen=True)
class Br(Terminator):
    target: Edge


@dataclass(frozen=True)
class CondBr(Terminator):
    cond: Value
    then: Edge
    els: Edge


@dataclass(frozen=True)
class Return(Terminator):
    value: Optional[Value] = None


@dataclass(frozen=True)
class Raise(Terminator):
    error: Value


@dataclass
class BasicBlock:
    name: str
    params: List[Param] = field(default_factory=list)
    instructions: List[Instruction] = field(default_factory=list)
    terminator: Optional[Terminator] = None


@dataclass
class Function:
    name: str
    params: List[Param]
    return_type: Type
    entry: str
    blocks: Dict[str, BasicBlock] = field(default_factory=dict)


@dataclass
class Program:
    functions: Dict[str, Function]
