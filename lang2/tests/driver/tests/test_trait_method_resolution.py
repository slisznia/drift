# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

from lang2.driftc import stage1 as H
from lang2.driftc.core.function_id import FunctionId
from lang2.driftc.impl_index import GlobalImplIndex, ImplMeta
from lang2.driftc.method_registry import CallableRegistry, CallableSignature, SelfMode, Visibility
from lang2.driftc.parser import parse_drift_workspace_to_hir
from lang2.driftc.trait_index import GlobalTraitImplIndex, GlobalTraitIndex
from lang2.driftc.type_checker import TypeChecker
from lang2.driftc.traits.world import TraitKey


def _write_file(path: Path, content: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content)


def _callable_name(fn_id: FunctionId) -> str:
	return fn_id.name if fn_id.module == "main" else f"{fn_id.module}::{fn_id.name}"


def _build_registry(signatures: dict[FunctionId, object]) -> tuple[CallableRegistry, dict[object, int]]:
	registry = CallableRegistry()
	module_ids: dict[object, int] = {None: 0}
	next_id = 1
	for fn_id, sig in signatures.items():
		if sig.param_type_ids is None or sig.return_type_id is None:
			continue
		module_id = module_ids.setdefault(sig.module, len(module_ids))
		if sig.is_method:
			if sig.impl_target_type_id is None or sig.self_mode is None:
				continue
			self_mode = {
				"value": SelfMode.SELF_BY_VALUE,
				"ref": SelfMode.SELF_BY_REF,
				"ref_mut": SelfMode.SELF_BY_REF_MUT,
			}.get(sig.self_mode)
			if self_mode is None:
				continue
			registry.register_inherent_method(
				callable_id=next_id,
				name=sig.method_name or sig.name,
				module_id=module_id,
				visibility=Visibility.public() if sig.is_pub else Visibility.private(),
				signature=CallableSignature(param_types=tuple(sig.param_type_ids), result_type=sig.return_type_id),
				fn_id=fn_id,
				impl_id=next_id,
				impl_target_type_id=sig.impl_target_type_id,
				self_mode=self_mode,
				is_generic=bool(sig.type_params or getattr(sig, "impl_type_params", [])),
			)
		else:
			registry.register_free_function(
				callable_id=next_id,
				name=_callable_name(fn_id),
				module_id=module_id,
				visibility=Visibility.public(),
				signature=CallableSignature(param_types=tuple(sig.param_type_ids), result_type=sig.return_type_id),
				fn_id=fn_id,
				is_generic=bool(sig.type_params),
			)
		next_id += 1
	return registry, module_ids


def _visible_modules_for(
	module_name: str, module_deps: dict[str, set[str]], module_ids: dict[object, int]
) -> tuple[int, ...]:
	visible = set(module_deps.get(module_name, set()))
	visible.add(module_name)
	return tuple(sorted(module_ids.setdefault(mod, len(module_ids)) for mod in visible))


def _collect_method_calls(block: H.HBlock) -> list[H.HMethodCall]:
	calls: list[H.HMethodCall] = []

	def walk_expr(expr: H.HExpr) -> None:
		if isinstance(expr, H.HMethodCall):
			calls.append(expr)
			walk_expr(expr.receiver)
			for a in expr.args:
				walk_expr(a)
			for kw in getattr(expr, "kwargs", []) or []:
				if getattr(kw, "value", None) is not None:
					walk_expr(kw.value)
			return
		for child in getattr(expr, "__dict__", {}).values():
			if isinstance(child, H.HExpr):
				walk_expr(child)
			elif isinstance(child, H.HBlock):
				walk_block(child)
			elif isinstance(child, list):
				for it in child:
					if isinstance(it, H.HExpr):
						walk_expr(it)
					elif isinstance(it, H.HBlock):
						walk_block(it)

	def walk_block(b: H.HBlock) -> None:
		for st in b.statements:
			if isinstance(st, H.HExprStmt):
				walk_expr(st.expr)
			elif isinstance(st, H.HReturn) and st.value is not None:
				walk_expr(st.value)
			else:
				for child in getattr(st, "__dict__", {}).values():
					if isinstance(child, H.HExpr):
						walk_expr(child)
					elif isinstance(child, H.HBlock):
						walk_block(child)
					elif isinstance(child, list):
						for it in child:
							if isinstance(it, H.HExpr):
								walk_expr(it)
							elif isinstance(it, H.HBlock):
								walk_block(it)

	walk_block(block)
	return calls


def _resolve_main_block(
	tmp_path: Path, files: dict[Path, str], *, main_module: str
) -> tuple[H.HBlock, object, dict[FunctionId, object], dict[str, set[str]], dict[object, int], object, dict[str, list[object]]]:
	mod_root = tmp_path / "mods"
	for rel, content in files.items():
		_write_file(mod_root / rel, content)
	paths = sorted(mod_root.rglob("*.drift"))
	func_hirs, signatures, fn_ids_by_name, type_table, _exc_catalog, module_exports, module_deps, diagnostics = parse_drift_workspace_to_hir(
		paths,
	)
	assert diagnostics == []
	registry, module_ids = _build_registry(signatures)
	impl_index = GlobalImplIndex.from_module_exports(
		module_exports=module_exports,
		type_table=type_table,
		module_ids=module_ids,
	)
	trait_index = GlobalTraitIndex.from_trait_worlds(getattr(type_table, "trait_worlds", None))
	trait_impl_index = GlobalTraitImplIndex.from_module_exports(
		module_exports=module_exports,
		type_table=type_table,
		module_ids=module_ids,
	)
	trait_scope_by_module: dict[str, list[object]] = {}
	for mod, exp in module_exports.items():
		if isinstance(exp, dict):
			scope = exp.get("trait_scope", [])
			trait_scope_by_module[mod] = list(scope) if isinstance(scope, list) else []
	main_key = f"{main_module}::main"
	main_ids = fn_ids_by_name.get(main_key) or []
	assert len(main_ids) == 1
	main_id = main_ids[0]
	main_block = func_hirs[main_id]
	visible_modules = _visible_modules_for(main_module, module_deps, module_ids)
	type_checker = TypeChecker(type_table=type_table)
	result = type_checker.check_function(
		main_id,
		main_block,
		callable_registry=registry,
		signatures_by_id=signatures,
		impl_index=impl_index,
		trait_index=trait_index,
		trait_impl_index=trait_impl_index,
		trait_scope_by_module=trait_scope_by_module,
		visible_modules=visible_modules,
		current_module=module_ids.setdefault(main_module, len(module_ids)),
	)
	return (
		main_block,
		result,
		signatures,
		module_deps,
		module_ids,
		type_table,
		trait_scope_by_module,
	)


def _typecheck_named_fn(
	tmp_path: Path,
	files: dict[Path, str],
	*,
	module_name: str,
	fn_name: str,
) -> object:
	mod_root = tmp_path / "mods"
	for rel, content in files.items():
		_write_file(mod_root / rel, content)
	paths = sorted(mod_root.rglob("*.drift"))
	func_hirs, signatures, fn_ids_by_name, type_table, _exc_catalog, module_exports, module_deps, diagnostics = parse_drift_workspace_to_hir(
		paths,
	)
	assert diagnostics == []
	registry, module_ids = _build_registry(signatures)
	impl_index = GlobalImplIndex.from_module_exports(
		module_exports=module_exports,
		type_table=type_table,
		module_ids=module_ids,
	)
	trait_index = GlobalTraitIndex.from_trait_worlds(getattr(type_table, "trait_worlds", None))
	trait_impl_index = GlobalTraitImplIndex.from_module_exports(
		module_exports=module_exports,
		type_table=type_table,
		module_ids=module_ids,
	)
	trait_scope_by_module: dict[str, list[object]] = {}
	for mod, exp in module_exports.items():
		if isinstance(exp, dict):
			scope = exp.get("trait_scope", [])
			trait_scope_by_module[mod] = list(scope) if isinstance(scope, list) else []
	key = f"{module_name}::{fn_name}"
	fn_ids = fn_ids_by_name.get(key) or []
	assert len(fn_ids) == 1
	fn_id = fn_ids[0]
	block = func_hirs[fn_id]
	sig = signatures.get(fn_id)
	param_types = {}
	if sig and sig.param_names and sig.param_type_ids:
		param_types = {pname: pty for pname, pty in zip(sig.param_names, sig.param_type_ids)}
	current_mod = module_ids.setdefault(module_name, len(module_ids))
	visible_modules = _visible_modules_for(module_name, module_deps, module_ids)
	type_checker = TypeChecker(type_table=type_table)
	return type_checker.check_function(
		fn_id,
		block,
		param_types=param_types,
		return_type=sig.return_type_id if sig is not None else None,
		signatures_by_id=signatures,
		callable_registry=registry,
		impl_index=impl_index,
		trait_index=trait_index,
		trait_impl_index=trait_impl_index,
		trait_scope_by_module=trait_scope_by_module,
		visible_modules=visible_modules,
		current_module=current_mod,
	)


def test_trait_dot_call_succeeds_with_use_trait(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

pub trait Show {
	fn show(self: Self) returns Int
}

export { Box, Show }

implement Show for Box<Int> {
	pub fn show(self: Box<Int>) returns Int { return self.value; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box as box
use trait box.Show

fn main() returns Int {
	val b: box.Box<Int> = box.Box<type Int>(1);
	return b.show();
}
""",
	}
	main_block, result, sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics == []
	calls = _collect_method_calls(main_block)
	assert calls
	res = result.typed_fn.call_resolutions[id(calls[0])]
	assert res.decl.fn_id in sigs
	assert res.decl.fn_id.module == "m_box"


def test_trait_not_in_scope_is_not_found(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

pub trait Show {
	fn show(self: Box<Int>) returns Int
}

export { Box, Show }

implement Show for Box<Int> {
	pub fn show(self: Box<Int>) returns Int { return self.value; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box as box

	fn main() returns Int {
		val b: box.Box<Int> = box.Box<type Int>(1);
		return b.show();
	}
	""",
	}
	_, result, _sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics
	msgs = [d.message for d in result.diagnostics]
	assert any("no matching method 'show'" in m for m in msgs)


def test_inherent_beats_trait_method(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

export { Box }

implement Box<Int> {
	pub fn tag(self: Box<Int>) returns Int { return 1; }
}
""",
		Path("m_trait.drift"): """
module m_trait

import m_box

pub trait Tag {
	fn tag(self: m_box.Box<Int>) returns Int
}

export { Tag }

implement Tag for m_box.Box<Int> {
	pub fn tag(self: m_box.Box<Int>) returns Int { return 2; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box
import m_trait
use trait m_trait.Tag

fn main() returns Int {
	val b: m_box.Box<Int> = m_box.Box<type Int>(1);
	return b.tag();
}
""",
	}
	main_block, result, sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics == []
	calls = _collect_method_calls(main_block)
	res = result.typed_fn.call_resolutions[id(calls[0])]
	assert res.decl.fn_id in sigs
	assert res.decl.fn_id.module == "m_box"


def test_trait_ambiguity_reports_modules(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

export { Box }
""",
		Path("m_a.drift"): """
module m_a

import m_box

pub trait Show {
	fn show(self: m_box.Box<Int>) returns Int
}

export { Show }

implement Show for m_box.Box<Int> {
	pub fn show(self: m_box.Box<Int>) returns Int { return 1; }
}
""",
		Path("m_b.drift"): """
module m_b

import m_box

pub trait Show {
	fn show(self: m_box.Box<Int>) returns Int
}

export { Show }

implement Show for m_box.Box<Int> {
	pub fn show(self: m_box.Box<Int>) returns Int { return 2; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box
import m_a
import m_b
use trait m_a.Show
use trait m_b.Show

fn main() returns Int {
	val b: m_box.Box<Int> = m_box.Box<type Int>(1);
	return b.show();
}
""",
	}
	_, result, _sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics
	msgs = [d.message for d in result.diagnostics]
	assert any("ambiguous method 'show'" in m for m in msgs)


def test_trait_require_blocks_candidate(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

export { Box }
""",
		Path("m_trait.drift"): """
module m_trait

import m_box

pub trait Hashable {
	fn hash(self: Int) returns Int
}

export { Hashable, Show }

implement Hashable for Int {
	pub fn hash(self: Int) returns Int { return self; }
}

pub trait Show {
	fn show(self: m_box.Box<String>) returns Int
}

implement Show for m_box.Box<String> require String is Hashable {
	pub fn show(self: m_box.Box<String>) returns Int { return 0; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box
import m_trait
use trait m_trait.Show

fn main() returns Int {
	val b: m_box.Box<String> = m_box.Box<type String>("s");
	return b.show();
}
""",
	}
	_, result, _sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics
	msgs = [d.message for d in result.diagnostics]
	assert any("requirement not satisfied" in m for m in msgs)
	assert any("Hashable" in m for m in msgs)


def test_trait_private_impl_not_visible_across_modules(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

export { Box }
""",
		Path("m_trait.drift"): """
module m_trait

import m_box

pub trait Show {
	fn show(self: m_box.Box<Int>) returns Int
}

export { Show }
""",
		Path("m_impl.drift"): """
module m_impl

import m_box
import m_trait

implement m_trait.Show for m_box.Box<Int> {
	fn show(self: m_box.Box<Int>) returns Int { return 1; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box
import m_trait
import m_impl
use trait m_trait.Show

fn main() returns Int {
	val b: m_box.Box<Int> = m_box.Box<type Int>(1);
	return b.show();
}
""",
	}
	_, result, _sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics
	msgs = [d.message for d in result.diagnostics]
	assert any("exists but is not visible" in m for m in msgs)
	assert any("m_trait.Show@m_impl" in m for m in msgs)


def test_trait_same_trait_multiple_impls_ambiguous(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

export { Box }
""",
		Path("m_trait.drift"): """
module m_trait

import m_box

pub trait Show {
	fn show(self: m_box.Box<Int>) returns Int
}

export { Show }
""",
		Path("m_a.drift"): """
module m_a

import m_box
import m_trait

implement m_trait.Show for m_box.Box<Int> {
	pub fn show(self: m_box.Box<Int>) returns Int { return 1; }
}
""",
		Path("m_b.drift"): """
module m_b

import m_box
import m_trait

implement m_trait.Show for m_box.Box<Int> {
	pub fn show(self: m_box.Box<Int>) returns Int { return 2; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box
import m_trait
import m_a
import m_b
use trait m_trait.Show

fn main() returns Int {
	val b: m_box.Box<Int> = m_box.Box<type Int>(1);
	return b.show();
}
""",
	}
	_, result, _sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics
	msgs = [d.message for d in result.diagnostics]
	assert any("ambiguous method 'show'" in m for m in msgs)


def test_trait_bound_does_not_expand_scope(tmp_path: Path) -> None:
	files = {
		Path("m_trait.drift"): """
module m_trait

export { Show }

pub trait Show {
	fn show(self: Self) returns Int
}

implement Show for Int {
	pub fn show(self: Int) returns Int { return self; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_trait

fn f<T>(x: T) returns Int require T is m_trait.Show { return x.show(); }

fn main() returns Int { return f<type Int>(1); }
""",
	}
	result = _typecheck_named_fn(
		tmp_path, files, module_name="m_main", fn_name="f"
	)
	assert result.diagnostics
	msgs = [d.message for d in result.diagnostics]
	assert any("no matching method 'show'" in m for m in msgs)


def test_trait_bound_with_use_trait_succeeds(tmp_path: Path) -> None:
	files = {
		Path("m_trait.drift"): """
module m_trait

export { Show }

pub trait Show {
	fn show(self: Self) returns Int
}

implement Show for Int {
	pub fn show(self: Int) returns Int { return self; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_trait
use trait m_trait.Show

fn f<T>(x: T) returns Int require T is m_trait.Show { return x.show(); }

fn main() returns Int { return f<type Int>(1); }
""",
	}
	result = _typecheck_named_fn(
		tmp_path, files, module_name="m_main", fn_name="f"
	)
	assert result.diagnostics == []


def test_trait_bound_enforced_at_call_site(tmp_path: Path) -> None:
	files = {
		Path("m_trait.drift"): """
module m_trait

export { Show }

pub trait Show {
	fn show(self: Self) returns Int
}

implement Show for Int {
	pub fn show(self: Int) returns Int { return self; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_trait
use trait m_trait.Show

fn f<T>(x: T) returns Int require T is m_trait.Show { return x.show(); }

fn main() returns Int { return f<type String>("s"); }
""",
	}
	_, result, _sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics
	msgs = [d.message for d in result.diagnostics]
	assert any("requirement not satisfied" in m for m in msgs)
	assert any("m_trait.Show" in m for m in msgs)


def test_ufcs_call_without_use_trait(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

export { Box }
""",
		Path("m_trait.drift"): """
module m_trait

import m_box

pub trait Show {
	fn show(self: m_box.Box<Int>) returns Int
}

export { Show }

implement Show for m_box.Box<Int> {
	pub fn show(self: m_box.Box<Int>) returns Int { return self.value; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box
import m_trait

fn main() returns Int {
	val b: m_box.Box<Int> = m_box.Box<type Int>(1);
	return m_trait.Show::show(b);
}
""",
	}
	_, result, _sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics == []


def test_ufcs_disambiguates_traits(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

export { Box }
""",
		Path("m_a.drift"): """
module m_a

import m_box

pub trait Show {
	fn show(self: m_box.Box<Int>) returns Int
}

export { Show }

implement Show for m_box.Box<Int> {
	pub fn show(self: m_box.Box<Int>) returns Int { return 1; }
}
""",
		Path("m_b.drift"): """
module m_b

import m_box

pub trait Show {
	fn show(self: m_box.Box<Int>) returns Int
}

export { Show }

implement Show for m_box.Box<Int> {
	pub fn show(self: m_box.Box<Int>) returns Int { return 2; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box
import m_a
import m_b

fn main() returns Int {
	val b: m_box.Box<Int> = m_box.Box<type Int>(1);
	return m_a.Show::show(b);
}
""",
	}
	_, result, _sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics == []


def test_ufcs_respects_method_visibility(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

export { Box }
""",
		Path("m_trait.drift"): """
module m_trait

import m_box

pub trait Show {
	fn show(self: m_box.Box<Int>) returns Int
}

export { Show }
""",
		Path("m_impl.drift"): """
module m_impl

import m_box
import m_trait

implement m_trait.Show for m_box.Box<Int> {
	fn show(self: m_box.Box<Int>) returns Int { return 1; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box
import m_trait
import m_impl

fn main() returns Int {
	val b: m_box.Box<Int> = m_box.Box<type Int>(1);
	return m_trait.Show::show(b);
}
""",
	}
	_, result, _sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics
	msgs = [d.message for d in result.diagnostics]
	assert any("exists but is not visible" in m for m in msgs)


def test_ufcs_respects_requirements(tmp_path: Path) -> None:
	files = {
		Path("m_box.drift"): """
module m_box

pub struct Box<T> { value: T }

export { Box }
""",
		Path("m_trait.drift"): """
module m_trait

import m_box

pub trait Hashable {
	fn hash(self: Int) returns Int
}

export { Hashable, Show }

implement Hashable for Int {
	pub fn hash(self: Int) returns Int { return self; }
}

pub trait Show {
	fn show(self: m_box.Box<String>) returns Int
}

implement Show for m_box.Box<String> require String is Hashable {
	pub fn show(self: m_box.Box<String>) returns Int { return 0; }
}
""",
		Path("m_main.drift"): """
module m_main

import m_box
import m_trait

fn main() returns Int {
	val b: m_box.Box<String> = m_box.Box<type String>("s");
	return m_trait.Show::show(b);
}
""",
	}
	_, result, _sigs, _deps, _ids, _types, _trait_scope = _resolve_main_block(
		tmp_path, files, main_module="m_main"
	)
	assert result.diagnostics
	msgs = [d.message for d in result.diagnostics]
	assert any("requirement not satisfied" in m for m in msgs)
	assert any("Hashable" in m for m in msgs)


def test_ufcs_requires_exported_trait(tmp_path: Path) -> None:
	files = {
		Path("m_trait.drift"): """
module m_trait

pub trait Show {
	fn show(self: Self) returns Int
}
""",
		Path("m_main.drift"): """
module m_main

import m_trait

fn main() returns Int {
	return m_trait.Show::show(1);
}
""",
	}
	mod_root = tmp_path / "mods"
	for rel, content in files.items():
		_write_file(mod_root / rel, content)
	paths = sorted(mod_root.rglob("*.drift"))
	_func_hirs, _sigs, _ids, _types, _exc, _exports, _deps, diagnostics = parse_drift_workspace_to_hir(paths)
	assert diagnostics
	msgs = [d.message for d in diagnostics]
	assert any("does not export trait 'Show'" in m for m in msgs)


def test_trait_impl_index_dedupes_duplicate_impls(tmp_path: Path) -> None:
	files = {
		Path("m_box/lib.drift"): """
module m_box

export { Box }

pub struct Box<T> { value: T }
""",
		Path("m_trait/lib.drift"): """
module m_trait

import m_box

export { Show }

pub trait Show { fn show(self: m_box.Box<Int>) returns Int }
""",
		Path("m_impl/lib.drift"): """
module m_impl

import m_box
import m_trait as t

implement t.Show for m_box.Box<Int> {
	pub fn show(self: m_box.Box<Int>) returns Int { return 1; }
}
""",
	}
	mod_root = tmp_path / "mods"
	for rel, content in files.items():
		_write_file(mod_root / rel, content)
	paths = sorted(mod_root.rglob("*.drift"))
	_func_hirs, _sigs, _fn_ids_by_name, type_table, _exc_catalog, module_exports, _deps, diagnostics = (
		parse_drift_workspace_to_hir(paths)
	)
	assert diagnostics == []
	module_ids: dict[object, int] = {None: 0}
	trait_impl_index = GlobalTraitImplIndex.from_module_exports(
		module_exports=module_exports,
		type_table=type_table,
		module_ids=module_ids,
	)
	impls = module_exports.get("m_impl", {}).get("impls", [])
	assert impls
	impl = impls[0]
	assert isinstance(impl, ImplMeta)
	trait_impl_index.add_impl(impl=impl, type_table=type_table, module_ids=module_ids)
	base_id = type_table.get_struct_base(module_id="m_box", name="Box")
	assert base_id is not None
	assert impl.trait_key is not None
	cands = trait_impl_index.get_candidates(impl.trait_key, base_id, "show")
	assert len(cands) == 1
	assert len({cand.fn_id for cand in cands}) == 1


def test_missing_trait_metadata_is_hard_error(tmp_path: Path) -> None:
	files = {
		Path("m_box/lib.drift"): """
module m_box

export { Box }

pub struct Box<T> { value: T }
""",
		Path("m_traits/lib.drift"): """
module m_traits

import m_box

export { Show }

pub trait Show { fn show(self: m_box.Box<Int>) returns Int }
""",
		Path("m_main/main.drift"): """
module m_main

import m_box
import m_traits as t

use trait t.Show

fn main() returns Int {
	val b: m_box.Box<Int> = m_box.Box<type Int>(1);
	return b.show();
}
""",
	}
	mod_root = tmp_path / "mods"
	for rel, content in files.items():
		_write_file(mod_root / rel, content)
	paths = sorted(mod_root.rglob("*.drift"))
	func_hirs, signatures, fn_ids_by_name, type_table, _exc_catalog, module_exports, module_deps, diagnostics = (
		parse_drift_workspace_to_hir(paths)
	)
	assert diagnostics == []
	registry, module_ids = _build_registry(signatures)
	impl_index = GlobalImplIndex.from_module_exports(
		module_exports=module_exports,
		type_table=type_table,
		module_ids=module_ids,
	)
	trait_scope_by_module: dict[str, list[object]] = {}
	for mod, exp in module_exports.items():
		if isinstance(exp, dict):
			scope = exp.get("trait_scope", [])
			trait_scope_by_module[mod] = list(scope) if isinstance(scope, list) else []
	main_ids = fn_ids_by_name.get("m_main::main") or []
	assert len(main_ids) == 1
	main_id = main_ids[0]
	main_block = func_hirs[main_id]
	visible_modules = _visible_modules_for("m_main", module_deps, module_ids)
	trait_index = GlobalTraitIndex()
	trait_index.mark_missing(TraitKey(module="m_traits", name="Show"))
	trait_impl_index = GlobalTraitImplIndex()
	type_checker = TypeChecker(type_table=type_table)
	result = type_checker.check_function(
		main_id,
		main_block,
		callable_registry=registry,
		signatures_by_id=signatures,
		impl_index=impl_index,
		trait_index=trait_index,
		trait_impl_index=trait_impl_index,
		trait_scope_by_module=trait_scope_by_module,
		visible_modules=visible_modules,
		current_module=module_ids.setdefault("m_main", len(module_ids)),
	)
	assert any("missing trait metadata" in d.message for d in result.diagnostics)
