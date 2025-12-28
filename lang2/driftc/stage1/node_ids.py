# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-27
"""
NodeId assignment for HIR nodes.

This pass assigns stable, per-function NodeIds so typed side tables can key
off HIR nodes without relying on Python object identity.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Iterable

from lang2.driftc.stage1 import hir_nodes as H

_HIR_MODULES = {H.__name__, "lang2.driftc.stage1.closures"}


def assign_node_ids(root: H.HNode, *, start: int = 1) -> int:
	"""
	Assign NodeIds to all HIR nodes reachable from `root`.

	Returns the next available NodeId after traversal.
	"""
	next_id = start
	seen: set[int] = set()

	def walk(obj: object) -> None:
		nonlocal next_id
		obj_id = id(obj)
		if obj_id in seen:
			return
		seen.add(obj_id)

		if isinstance(obj, H.HNode):
			if is_dataclass(obj) and getattr(obj, "__dataclass_params__", None) and obj.__dataclass_params__.frozen:
				object.__setattr__(obj, "node_id", next_id)
			else:
				obj.node_id = next_id
			next_id += 1

		if not _should_descend(obj):
			return
		if is_dataclass(obj):
			for f in fields(obj):
				walk_value(getattr(obj, f.name))
		else:
			for val in vars(obj).values():
				walk_value(val)

	def walk_value(val: object) -> None:
		if val is None:
			return
		if isinstance(val, (list, tuple)):
			for item in val:
				walk_value(item)
			return
		if isinstance(val, dict):
			for item in val.values():
				walk_value(item)
			return
		walk(val)

	def _should_descend(obj: object) -> bool:
		if isinstance(obj, H.HNode):
			return True
		if is_dataclass(obj) and obj.__class__.__module__ in _HIR_MODULES:
			return True
		return False

	walk(root)
	return next_id


__all__ = ["assign_node_ids"]
