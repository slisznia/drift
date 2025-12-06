# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-08
"""
Shared helpers for tests that need checker inputs.

These helpers avoid re-spelling FnSignature construction, declared_can_throw
derivation via the checker stub, and exception catalog setup.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Sequence

from lang2.checker import Checker, FnSignature


def make_signatures(
	return_types: Mapping[str, Any],
	throws_events: Mapping[str, Sequence[str]] | None = None,
) -> Dict[str, FnSignature]:
	"""
	Build a name -> FnSignature map from simple return-type/throws inputs.

	Args:
	  return_types: mapping of function name -> return type (string/tuple placeholder).
	  throws_events: optional mapping of function name -> iterable of event names.
	"""
	signatures: Dict[str, FnSignature] = {}
	for name, ret_ty in return_types.items():
		events = tuple(throws_events[name]) if throws_events and name in throws_events else ()
		signatures[name] = FnSignature(name=name, return_type=ret_ty, throws_events=events)
	return signatures


def declared_from_signatures(signatures: Mapping[str, FnSignature]) -> Dict[str, bool]:
	"""
	Derive declared_can_throw via the checker stub given FnSignature inputs.
	"""
	checked = Checker(signatures=signatures).check(signatures.keys())
	return {name: info.declared_can_throw for name, info in checked.fn_infos.items()}


def build_exception_catalog(events: Iterable[str] | Mapping[str, int]) -> Dict[str, int]:
	"""
	Construct a simple exception catalog (event name -> code) for tests.

	Accepts either an explicit mapping or an iterable of names (assigned 1..N).
	"""
	if isinstance(events, Mapping):
		return dict(events)
	return {name: idx for idx, name in enumerate(events, start=1)}


__all__ = ["make_signatures", "declared_from_signatures", "build_exception_catalog"]
