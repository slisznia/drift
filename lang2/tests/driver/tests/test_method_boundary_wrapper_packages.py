# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

from lang2.driftc import stage1 as H
from lang2.driftc.core.function_id import FunctionId, function_symbol, method_wrapper_id
from lang2.driftc.driftc import _collect_external_trait_and_impl_metadata, _parse_function_symbol, main as driftc_main
from lang2.driftc.impl_index import GlobalImplIndex, find_impl_method_conflicts
from lang2.driftc.method_registry import CallableRegistry, CallableSignature, SelfMode, Visibility
from lang2.driftc.packages.provider_v0 import collect_external_exports, load_package_v0
from lang2.driftc.packages.type_table_link_v0 import import_type_tables_and_build_typeid_maps
from lang2.driftc.parser import parse_drift_workspace_to_hir
from lang2.driftc.stage1.call_info import CallTargetKind
from lang2.driftc.type_checker import TypeChecker
from lang2.driftc.checker import FnSignature, TypeParam
from lang2.driftc.core.types_core import TypeParamId


def _write_file(path: Path, content: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content)


def _emit_pkg_args(package_id: str) -> list[str]:
	return ["--package-id", package_id, "--package-version", "0.0.0", "--package-target", "test"]


def _emit_method_pkg(tmp_path: Path, *, module_id: str, package_id: str) -> Path:
	module_dir = tmp_path.joinpath(*module_id.split("."))
	_write_file(
		module_dir / "lib.drift",
		f"""
module {module_id}

export {{ S, make }}

pub struct S {{ x: Int }}

implement S {{
\tpub fn bump(self: S) returns Int nothrow {{
\t\treturn self.x + 1;
\t}}
}}

pub fn make() returns S nothrow {{
\treturn S(x = 1);
}}
""".lstrip(),
	)
	pkg_path = tmp_path / f"{module_id.replace('.', '_')}.dmp"
	assert (
		driftc_main(
			[
				"-M",
				str(tmp_path),
				str(module_dir / "lib.drift"),
				*_emit_pkg_args(package_id),
				"--emit-package",
				str(pkg_path),
			]
		)
		== 0
	)
	return pkg_path


def _build_registry(signatures: dict[FunctionId, FnSignature]) -> tuple[CallableRegistry, dict[object, int]]:
	registry = CallableRegistry()
	module_ids: dict[object, int] = {None: 0}
	next_id = 1
	for fn_id, sig in signatures.items():
		if getattr(sig, "is_wrapper", False):
			continue
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
				name=fn_id.name if fn_id.module == "main" else f"{fn_id.module}::{fn_id.name}",
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


def _decode_package_signatures(
	pkg_path: Path,
	*,
	type_table,
) -> dict[FunctionId, FnSignature]:
	pkg = load_package_v0(pkg_path)
	payload_tts: list[object] = []
	for mod in pkg.modules_by_id.values():
		payload = mod.payload
		if isinstance(payload, dict):
			tt = payload.get("type_table")
			if isinstance(tt, dict):
				payload_tts.append(tt)
				break
	if not payload_tts:
		raise AssertionError("missing type_table in package payload")
	tid_maps = import_type_tables_and_build_typeid_maps(payload_tts, type_table)
	tid_map = tid_maps[0]
	out: dict[FunctionId, FnSignature] = {}
	for mid, mod in pkg.modules_by_id.items():
		payload = mod.payload
		if not isinstance(payload, dict):
			continue
		sigs_obj = payload.get("signatures")
		if not isinstance(sigs_obj, dict):
			continue
		for sym, sd in sigs_obj.items():
			if not isinstance(sd, dict):
				continue
			name = str(sd.get("name") or sym)
			module_name = sd.get("module")
			if module_name is not None and "::" not in name:
				name = f"{module_name}::{name}"
			param_type_ids = sd.get("param_type_ids")
			if isinstance(param_type_ids, list):
				param_type_ids = [tid_map.get(int(x), int(x)) for x in param_type_ids]
			ret_tid = sd.get("return_type_id")
			if isinstance(ret_tid, int):
				ret_tid = tid_map.get(ret_tid, ret_tid)
			impl_tid = sd.get("impl_target_type_id")
			if isinstance(impl_tid, int):
				impl_tid = tid_map.get(impl_tid, impl_tid)
			wraps_symbol = sd.get("wraps_target_symbol")
			wraps_fn_id = None
			if isinstance(wraps_symbol, str) and wraps_symbol:
				wraps_fn_id = _parse_function_symbol(wraps_symbol)
			fn_id = _parse_function_symbol(str(sym))
			type_param_names = sd.get("type_params")
			if not isinstance(type_param_names, list):
				type_param_names = []
			impl_type_param_names = sd.get("impl_type_params")
			if not isinstance(impl_type_param_names, list):
				impl_type_param_names = []
			type_params = [
				TypeParam(id=TypeParamId(fn_id, idx), name=tp)
				for idx, tp in enumerate(type_param_names)
				if isinstance(tp, str)
			]
			impl_owner = FunctionId(module="lang.__external", name=f"__impl_{sym}", ordinal=0)
			impl_type_params = [
				TypeParam(id=TypeParamId(impl_owner, idx), name=tp)
				for idx, tp in enumerate(impl_type_param_names)
				if isinstance(tp, str)
			]
			sig = FnSignature(
				name=name,
				module=module_name,
				method_name=sd.get("method_name"),
				param_names=sd.get("param_names"),
				param_type_ids=param_type_ids,
				return_type_id=ret_tid,
				is_method=bool(sd.get("is_method", False)),
				self_mode=sd.get("self_mode"),
				impl_target_type_id=impl_tid,
				is_pub=bool(sd.get("is_pub", False)),
				is_wrapper=bool(sd.get("is_wrapper", False)),
				wraps_target_fn_id=wraps_fn_id,
				is_exported_entrypoint=bool(sd.get("is_exported_entrypoint", False)),
				type_params=type_params,
				impl_type_params=impl_type_params,
			)
			out[fn_id] = sig
	return out


def test_cross_package_method_call_uses_wrapper_fn_id(tmp_path: Path) -> None:
	pkgs_root = tmp_path / "pkgs"
	pkgs_root.mkdir(parents=True, exist_ok=True)
	pkg_path = _emit_method_pkg(
		pkgs_root,
		module_id="acme.pointm",
		package_id="acme.pointm",
	)
	pkg = load_package_v0(pkg_path)
	external_exports = collect_external_exports([pkg])

	src_root = tmp_path / "src"
	_write_file(
		src_root / "main.drift",
		"""
module main

import acme.pointm as P

fn main() returns Int  nothrow{
\tval p = P.make()
\treturn try p.bump() catch { 0 }
}
""".lstrip(),
	)
	paths = sorted(src_root.rglob("*.drift"))
	func_hirs, signatures, fn_ids_by_name, type_table, _exc_catalog, module_exports, module_deps, diagnostics = (
		parse_drift_workspace_to_hir(
			paths,
			module_paths=[src_root],
			external_module_exports=external_exports,
		)
	)
	assert diagnostics == []

	external_sigs_by_id = _decode_package_signatures(pkg_path, type_table=type_table)
	signatures.update(external_sigs_by_id)

	external_sigs_by_symbol = {function_symbol(fn_id): sig for fn_id, sig in external_sigs_by_id.items()}
	_external_trait_defs, external_impl_metas, _missing_traits, _missing_impl_modules = _collect_external_trait_and_impl_metadata(
		loaded_pkgs=[pkg],
		type_table=type_table,
		external_signatures_by_symbol=external_sigs_by_symbol,
	)
	registry, module_ids = _build_registry(signatures)
	impl_index = GlobalImplIndex.from_module_exports(
		module_exports=module_exports,
		type_table=type_table,
		module_ids=module_ids,
	)
	for impl in external_impl_metas:
		if getattr(impl, "trait_key", None) is None:
			impl_index.add_impl(impl=impl, type_table=type_table, module_ids=module_ids)
	conflicts = find_impl_method_conflicts(
		module_exports=module_exports,
		signatures_by_id=signatures,
		type_table=type_table,
		visible_modules_by_name={mod: set(deps) | {mod} for mod, deps in module_deps.items()},
	)
	assert conflicts == []

	main_ids = fn_ids_by_name.get("main") or []
	assert len(main_ids) == 1
	main_id = main_ids[0]
	main_block = func_hirs[main_id]
	main_sig = signatures[main_id]
	param_types = {}
	if main_sig.param_names and main_sig.param_type_ids:
		param_types = {pname: pty for pname, pty in zip(main_sig.param_names, main_sig.param_type_ids)}
	current_mod = module_ids.setdefault(main_sig.module, len(module_ids))
	visible_mods = _visible_modules_for("main", module_deps, module_ids)
	tc = TypeChecker(type_table=type_table)
	result = tc.check_function(
		main_id,
		main_block,
		param_types=param_types,
		return_type=main_sig.return_type_id,
		signatures_by_id=signatures,
		callable_registry=registry,
		impl_index=impl_index,
		visible_modules=visible_mods,
		current_module=current_mod,
	)
	assert not result.diagnostics

	calls = _collect_method_calls(result.typed_fn.body)
	assert len(calls) == 1
	call = calls[0]
	info = result.typed_fn.call_info_by_node_id.get(call.node_id)
	assert info is not None
	assert info.target.kind is CallTargetKind.DIRECT

	impl_id = next(
		fn_id
		for fn_id, sig in external_sigs_by_id.items()
		if sig.is_method and sig.method_name == "bump" and not getattr(sig, "is_wrapper", False)
	)
	assert info.target.symbol == method_wrapper_id(impl_id)
	assert info.sig.can_throw is True
