# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-27
"""
Typed call metadata shared between stage1 and stage2.

Stage2 must not re-resolve call targets or throw-ness; it consumes this data
verbatim from the type checker.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Tuple

from lang2.driftc.core.function_id import FunctionId
from lang2.driftc.core.types_core import TypeId, TypeTable


SymbolId = FunctionId


class CallTargetKind(Enum):
	"""Call target classification for typed HIR."""
	DIRECT = auto()
	INDIRECT = auto()


@dataclass(frozen=True)
class CallTarget:
	kind: CallTargetKind
	symbol: SymbolId | None = None
	callee_node_id: int | None = None

	@staticmethod
	def direct(symbol: SymbolId) -> "CallTarget":
		return CallTarget(kind=CallTargetKind.DIRECT, symbol=symbol)

	@staticmethod
	def indirect(callee_node_id: int) -> "CallTarget":
		return CallTarget(kind=CallTargetKind.INDIRECT, callee_node_id=callee_node_id)


@dataclass(frozen=True)
class CallSig:
	param_types: Tuple[TypeId, ...]
	user_ret_type: TypeId
	can_throw: bool


@dataclass(frozen=True)
class CallInfo:
	target: CallTarget
	sig: CallSig


def call_abi_ret_type(sig: CallSig, type_table: TypeTable) -> TypeId:
	"""
	Return the ABI return type for a call signature.

	Can-throw calls return FnResult<ok, Error>; nothrow calls return the user
	return type directly.
	"""
	if sig.can_throw:
		err = type_table.ensure_error()
		return type_table.ensure_fnresult(sig.user_ret_type, err)
	return sig.user_ret_type


__all__ = [
	"CallInfo",
	"CallSig",
	"CallTarget",
	"CallTargetKind",
	"SymbolId",
	"call_abi_ret_type",
]
