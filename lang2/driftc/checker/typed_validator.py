# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from lang2.driftc.stage1 import hir_nodes as H
from lang2.driftc.stage1.call_info import CallInfo
from lang2.driftc.core.types_core import TypeKind


@dataclass
class TypedValidationResult:
	diagnostics: list


def validate_typed_hir(root: H.HNode, *, call_info_by_callsite_id: Mapping[int, CallInfo] | None, expr_types: Mapping[int, int] | None, type_table, tc_diag) -> TypedValidationResult:
	diagnostics: list = []
	allowed_qmem_nodes: set[int] = set()

	def _iter_expr_children(e: H.HExpr) -> list[H.HExpr]:
		children: list[H.HExpr] = []
		for field_name in getattr(e, "__dataclass_fields__", {}) or {}:
			val = getattr(e, field_name, None)
			if isinstance(val, H.HExpr):
				children.append(val)
			elif isinstance(val, list):
				for item in val:
					if isinstance(item, H.HExpr):
						children.append(item)
		return children

	def _scan_calls(node: H.HNode) -> None:
		if isinstance(node, H.HCall):
			if isinstance(node.fn, H.HQualifiedMember):
				if isinstance(call_info_by_callsite_id, Mapping) and isinstance(getattr(node, "callsite_id", None), int) and node.callsite_id in call_info_by_callsite_id:
					allowed_qmem_nodes.add(node.fn.node_id)
		if isinstance(node, H.HTypeApp) and isinstance(getattr(node, "fn", None), H.HQualifiedMember):
			if isinstance(call_info_by_callsite_id, Mapping):
				allowed_qmem_nodes.add(node.fn.node_id)
		if isinstance(node, H.HBlock):
			for stmt in node.statements:
				_scan_calls(stmt)
			return
		for field_name in getattr(node, "__dataclass_fields__", {}) or {}:
			val = getattr(node, field_name, None)
			if isinstance(val, (H.HExpr, H.HBlock)):
				_scan_calls(val)
			elif isinstance(val, list):
				for item in val:
					if isinstance(item, (H.HExpr, H.HBlock)):
						_scan_calls(item)

	def _walk_node(node: H.HNode) -> None:
		if isinstance(node, H.HExpr):
			expr_type_id = None
			if expr_types is not None and isinstance(getattr(node, "node_id", None), int):
				expr_type_id = expr_types.get(node.node_id)
			is_function_expr = False
			if expr_type_id is not None and type_table is not None:
				try:
					is_function_expr = type_table.get(expr_type_id).kind is TypeKind.FUNCTION
				except Exception:
					is_function_expr = False
			if isinstance(node, H.HTypeApp):
				if isinstance(getattr(node, "fn", None), H.HQualifiedMember):
					allowed_qmem_nodes.add(node.fn.node_id)
				if not is_function_expr:
					diagnostics.append(tc_diag(message="internal: HTypeApp survived typed mode (checker bug)", severity="error", span=getattr(node, "loc", None)))
			if isinstance(node, H.HQualifiedMember) and node.node_id not in allowed_qmem_nodes:
				if not is_function_expr:
					diagnostics.append(tc_diag(message="internal: HQualifiedMember survived typed mode (checker bug)", severity="error", span=getattr(node, "loc", None)))
			if getattr(node, "kwargs", None):
				diagnostics.append(tc_diag(message="internal: kwargs survived typed mode (checker bug)", severity="error", span=getattr(node, "loc", None)))
			if isinstance(node, (H.HCall, H.HMethodCall, H.HInvoke)):
				csid = getattr(node, "callsite_id", None)
				if not isinstance(call_info_by_callsite_id, Mapping):
					diagnostics.append(tc_diag(message="internal: missing CallInfo map for typed validation (checker bug)", severity="error", span=getattr(node, "loc", None)))
				elif not isinstance(csid, int) or csid not in call_info_by_callsite_id:
					diagnostics.append(tc_diag(message="internal: missing CallInfo for typed call (checker bug)", severity="error", span=getattr(node, "loc", None)))
			for child in _iter_expr_children(node):
				_walk_node(child)
			return
		if isinstance(node, H.HBlock):
			for stmt in node.statements:
				_walk_node(stmt)
			return
		for field_name in getattr(node, "__dataclass_fields__", {}) or {}:
			val = getattr(node, field_name, None)
			if isinstance(val, (H.HExpr, H.HBlock)):
				_walk_node(val)
			elif isinstance(val, list):
				for item in val:
					if isinstance(item, (H.HExpr, H.HBlock)):
						_walk_node(item)

	_scan_calls(root)
	_walk_node(root)
	return TypedValidationResult(diagnostics=diagnostics)
