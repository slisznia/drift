# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Set

from lang2.driftc.core.diagnostics import Diagnostic
from lang2.driftc.core.span import Span
from lang2.driftc.stage1 import closures as C
from lang2.driftc.stage1 import hir_nodes as H


@dataclass
class CaptureDiscoveryResult:
	captures: list[C.HCapture]
	diagnostics: list[Diagnostic]


@dataclass
class _CaptureUsage:
	read: bool = False
	borrow_shared: bool = False
	borrow_mut: bool = False
	move: bool = False
	write: bool = False
	span: Span = Span()


def discover_captures(lambda_expr: H.HLambda) -> CaptureDiscoveryResult:
	"""
	Discover captures for a lambda (v0: locals/params + field projections only).

	- Allowed capture roots: locals/params (BindingId)
	- Allowed projections: field chain (no index/deref)
	- Captures are deduped and sorted deterministically.
	"""
	usage: dict[C.HCaptureKey, _CaptureUsage] = {}
	diags: list[Diagnostic] = []

	lambda_local_ids: Set[H.BindingId] = set()
	for p in lambda_expr.params:
		if p.binding_id is not None:
			lambda_local_ids.add(p.binding_id)

	def _record_local_from_stmt(stmt: H.HStmt) -> None:
		if isinstance(stmt, H.HLet) and stmt.binding_id is not None:
			lambda_local_ids.add(stmt.binding_id)

	def _add_usage(
		root: H.BindingId | None,
		fields: list[str],
		span: Span,
		*,
		read: bool = False,
		borrow_shared: bool = False,
		borrow_mut: bool = False,
		move: bool = False,
		write: bool = False,
	) -> None:
		if root is None or root in lambda_local_ids:
			return
		key = C.HCaptureKey(root_local=root, proj=tuple(C.HCaptureProj(field=f) for f in fields))
		entry = usage.setdefault(key, _CaptureUsage())
		if entry.span == Span():
			entry.span = span
		entry.read = entry.read or read
		entry.borrow_shared = entry.borrow_shared or borrow_shared
		entry.borrow_mut = entry.borrow_mut or borrow_mut
		entry.move = entry.move or move
		entry.write = entry.write or write

	def _flatten_field_chain(expr: H.HExpr) -> tuple[H.BindingId | None, list[str]] | None:
		# HPlaceExpr (canonical place)
		if isinstance(expr, H.HPlaceExpr):
			root = getattr(expr.base, "binding_id", None)
			fields: list[str] = []
			for proj in expr.projections:
				if isinstance(proj, H.HPlaceField):
					fields.append(proj.name)
				else:
					return None
			return (root, fields)
		# HField chain rooted in HVar
		if isinstance(expr, H.HField):
			inner = _flatten_field_chain(expr.subject)
			if inner is None:
				return None
			root, fields = inner
			return (root, fields + [expr.name])
		if isinstance(expr, H.HVar):
			return (expr.binding_id, [])
		return None

	def _walk_place_expr(place: H.HPlaceExpr, *, usage_kind: str) -> None:
		flattened = _flatten_field_chain(place)
		if flattened is None:
			root = getattr(place.base, "binding_id", None)
			if root is not None and root not in lambda_local_ids:
				diags.append(
					Diagnostic(
						message="lambda captures support field projections only in v0",
						severity="error",
						span=getattr(place, "loc", Span()),
					)
				)
			for proj in place.projections:
				if isinstance(proj, H.HPlaceIndex):
					_walk_expr(proj.index)
			return
		if flattened is not None:
			root, fields = flattened
			_add_usage(
				root,
				fields,
				getattr(place, "loc", Span()),
				read=usage_kind == "read",
				borrow_shared=usage_kind == "borrow_shared",
				borrow_mut=usage_kind == "borrow_mut",
				move=usage_kind == "move",
				write=usage_kind == "write",
			)
		for proj in place.projections:
			if isinstance(proj, H.HPlaceIndex):
				_walk_expr(proj.index)

	def _walk_expr(e: H.HExpr) -> None:
		# Skip nested lambdas; captures are per-lambda.
		if isinstance(e, H.HLambda):
			return
		if isinstance(e, H.HMove):
			_walk_place_expr(e.subject, usage_kind="move")
			return
		if isinstance(e, H.HBorrow):
			_walk_place_expr(e.subject, usage_kind="borrow_mut" if e.is_mut else "borrow_shared")
			return
		if isinstance(e, H.HVar):
			_add_usage(e.binding_id, [], getattr(e, "span", Span()), read=True)
			return
		elif isinstance(e, (H.HPlaceExpr, H.HField)):
			flattened = _flatten_field_chain(e)
			if flattened is not None:
				root, fields = flattened
				_add_usage(root, fields, getattr(e, "loc", getattr(e, "span", Span())), read=True)
			elif isinstance(e, H.HPlaceExpr):
				root = getattr(e.base, "binding_id", None)
				if root is not None and root not in lambda_local_ids:
					diags.append(
						Diagnostic(
							message="lambda captures support field projections only in v0",
							severity="error",
							span=getattr(e, "loc", Span()),
						)
					)
			if isinstance(e, H.HPlaceExpr):
				for proj in e.projections:
					if isinstance(proj, H.HPlaceIndex):
						_walk_expr(proj.index)
			return
		# Traverse children
		for child in _iter_expr_children(e):
			_walk_expr(child)

	def _walk_stmt(s: H.HStmt) -> None:
		_record_local_from_stmt(s)
		if isinstance(s, H.HBlock):
			for st in s.statements:
				_walk_stmt(st)
		elif isinstance(s, H.HExprStmt):
			_walk_expr(s.expr)
		elif isinstance(s, H.HLet):
			_walk_expr(s.value)
		elif isinstance(s, H.HAssign):
			if isinstance(s.target, H.HPlaceExpr):
				_walk_place_expr(s.target, usage_kind="write")
			else:
				flattened = _flatten_field_chain(s.target)
				if flattened is not None:
					root, fields = flattened
					_add_usage(root, fields, getattr(s.target, "loc", Span()), write=True)
			_walk_expr(s.value)
		elif isinstance(s, H.HAugAssign):
			if isinstance(s.target, H.HPlaceExpr):
				_walk_place_expr(s.target, usage_kind="write")
			else:
				flattened = _flatten_field_chain(s.target)
				if flattened is not None:
					root, fields = flattened
					_add_usage(root, fields, getattr(s.target, "loc", Span()), write=True)
			_walk_expr(s.value)
		elif isinstance(s, H.HIf):
			_walk_expr(s.cond)
			for st in s.then_block.statements:
				_walk_stmt(st)
			if s.else_block:
				for st in s.else_block.statements:
					_walk_stmt(st)
		elif isinstance(s, H.HReturn):
			if s.value is not None:
				_walk_expr(s.value)
		elif isinstance(s, H.HLoop):
			for st in s.body.statements:
				_walk_stmt(st)
		elif isinstance(s, H.HTry):
			for st in s.body.statements:
				_walk_stmt(st)
			for arm in s.catches:
				for st in arm.block.statements:
					_walk_stmt(st)
		elif isinstance(s, H.HThrow):
			_walk_expr(s.value)
		elif isinstance(s, H.HMatchExpr):
			_walk_expr(s)
		elif isinstance(s, H.HTryExpr):
			_walk_expr(s)

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

	# Seed locals from body statements (params already collected).
	if lambda_expr.body_block is not None:
		for stmt in lambda_expr.body_block.statements:
			_record_local_from_stmt(stmt)
			_walk_stmt(stmt)
	if lambda_expr.body_expr is not None:
		_walk_expr(lambda_expr.body_expr)

	captures: list[C.HCapture] = []
	for key, use in usage.items():
		if use.move and key.proj:
			diags.append(
				Diagnostic(
					message="lambda move captures of projections are not supported yet",
					severity="error",
					span=use.span,
				)
			)
		if use.move and (use.borrow_shared or use.borrow_mut or use.write):
			diags.append(
				Diagnostic(
					message="lambda capture mixes move and borrow/write uses",
					severity="error",
					span=use.span,
				)
			)
		if use.borrow_shared and (use.borrow_mut or use.write):
			diags.append(
				Diagnostic(
					message="lambda capture uses both shared and mutable access",
					severity="error",
					span=use.span,
				)
			)
		if use.move:
			kind = C.HCaptureKind.MOVE
		elif use.borrow_mut or use.write:
			kind = C.HCaptureKind.REF_MUT
		elif use.borrow_shared:
			kind = C.HCaptureKind.REF
		elif use.read:
			kind = C.HCaptureKind.REF
		else:
			continue
		captures.append(C.HCapture(kind=kind, key=key, span=use.span))

	def _overlaps(a: C.HCaptureKey, b: C.HCaptureKey) -> bool:
		if a.root_local != b.root_local:
			return False
		if len(a.proj) <= len(b.proj):
			return a.proj == b.proj[: len(a.proj)]
		return b.proj == a.proj[: len(b.proj)]

	for i, cap_a in enumerate(captures):
		for cap_b in captures[i + 1 :]:
			if not _overlaps(cap_a.key, cap_b.key):
				continue
			if cap_a.kind is C.HCaptureKind.REF and cap_b.kind is C.HCaptureKind.REF:
				continue
			diags.append(
				Diagnostic(
					message="overlapping lambda captures are not supported with mutable or move captures",
					severity="error",
					span=cap_a.span,
				)
			)

	sorted_caps = C.sort_captures(captures)
	lambda_expr.captures = sorted_caps
	return CaptureDiscoveryResult(captures=sorted_caps, diagnostics=diags)
