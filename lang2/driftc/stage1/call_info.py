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
	INTRINSIC = auto()


class IntrinsicKind(Enum):
	"""Intrinsic operations emitted by the type checker."""
	SWAP = "swap"
	REPLACE = "replace"
	BYTE_LENGTH = "byte_length"
	STRING_EQ = "string_eq"
	STRING_CONCAT = "string_concat"



@dataclass(frozen=True)
class CallTarget:
	kind: CallTargetKind
	symbol: SymbolId | None = None
	callee_node_id: int | None = None
	intrinsic: IntrinsicKind | None = None

	@staticmethod
	def direct(symbol: SymbolId) -> "CallTarget":
		return CallTarget(kind=CallTargetKind.DIRECT, symbol=symbol)

	@staticmethod
	def indirect(callee_node_id: int) -> "CallTarget":
		return CallTarget(kind=CallTargetKind.INDIRECT, callee_node_id=callee_node_id)

	@staticmethod
	def intrinsic(kind: IntrinsicKind) -> "CallTarget":
		return CallTarget(kind=CallTargetKind.INTRINSIC, intrinsic=kind)


@dataclass(frozen=True)
class CallSig:
	param_types: Tuple[TypeId, ...]
	user_ret_type: TypeId
	can_throw: bool
	includes_callee: bool = False


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
	"IntrinsicKind",
	"SymbolId",
	"call_abi_ret_type",
]
