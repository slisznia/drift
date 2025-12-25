# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

from lang2.driftc.core.function_id import FunctionId, function_symbol
from lang2.driftc.method_registry import CallableRegistry, CallableSignature, Visibility
from lang2.driftc.parser import parse_drift_to_hir
from lang2.driftc.traits.enforce import enforce_fn_requires
from lang2.driftc.type_checker import TypeChecker


def _build_registry(signatures: dict[FunctionId, object]) -> tuple[CallableRegistry, dict[object, int]]:
	registry = CallableRegistry()
	module_ids: dict[object, int] = {None: 0}
	next_id = 1
	for fn_id, sig in signatures.items():
		if getattr(sig, "is_method", False):
			continue
		if sig.param_type_ids is None or sig.return_type_id is None:
			continue
		module_id = module_ids.setdefault(sig.module, len(module_ids))
		registry.register_free_function(
			callable_id=next_id,
			name=function_symbol(fn_id),
			module_id=module_id,
			visibility=Visibility.public(),
			signature=CallableSignature(param_types=tuple(sig.param_type_ids), result_type=sig.return_type_id),
			fn_id=fn_id,
			is_generic=bool(getattr(sig, "type_params", None)),
		)
		next_id += 1
	return registry, module_ids


def _typecheck_fn(src: str, tmp_path: Path, fn_name: str) -> tuple[TypeChecker, object, dict[FunctionId, object], FunctionId]:
	path = tmp_path / "bounds.drift"
	path.write_text(src)
	func_hirs, sigs, fn_ids_by_name, type_table, _exc_catalog, diagnostics = parse_drift_to_hir(path)
	assert diagnostics == []
	fn_ids = fn_ids_by_name.get(fn_name) or []
	if not fn_ids:
		qualified = [name for name in fn_ids_by_name.keys() if name.endswith(f"::{fn_name}")]
		if len(qualified) == 1:
			fn_ids = fn_ids_by_name.get(qualified[0]) or []
	assert len(fn_ids) == 1
	fn_id = fn_ids[0]
	registry, module_ids = _build_registry(sigs)
	current_mod = module_ids.setdefault(fn_id.module, len(module_ids))
	tc = TypeChecker(type_table=type_table)
	res = tc.check_function(
		fn_id,
		func_hirs[fn_id],
		return_type=sigs[fn_id].return_type_id if fn_id in sigs else None,
		signatures_by_id=sigs,
		callable_registry=registry,
		visible_modules=(current_mod,),
		current_module=current_mod,
	)
	return tc, res, sigs, fn_id


def _enforce_fn_requires(tc: TypeChecker, typed_fn: object, sigs: dict[FunctionId, object], fn_id: FunctionId) -> list[object]:
	worlds = getattr(tc.type_table, "trait_worlds", {}) or {}
	world = worlds.get(fn_id.module or "main")
	assert world is not None
	res = enforce_fn_requires(world, typed_fn, tc.type_table, module_name=fn_id.module or "main", signatures=sigs)
	return res.diagnostics


def test_type_param_bound_satisfied(tmp_path: Path) -> None:
	tc, res, sigs, fn_id = _typecheck_fn(
		"""
trait Show { fn show(self: Int) returns Int }

implement Show for Int {
	pub fn show(self: Int) returns Int { return self; }
}

fn f<T>(x: T) returns Int require T is Show { return 0; }

fn main() returns Int { return f<type Int>(1); }
""",
		tmp_path,
		"main",
	)
	assert res.diagnostics == []
	diags = _enforce_fn_requires(tc, res.typed_fn, sigs, fn_id)
	assert diags == []


def test_type_param_bound_unsatisfied(tmp_path: Path) -> None:
	tc, res, sigs, fn_id = _typecheck_fn(
		"""
trait Show { fn show(self: Int) returns Int }

fn f<T>(x: T) returns Int require T is Show { return 0; }

fn main() returns Int { return f<type String>("s"); }
""",
		tmp_path,
		"main",
	)
	assert any("trait requirements not met" in d.message for d in res.diagnostics)


def test_type_param_bounds_with_guard_is_decidable(tmp_path: Path) -> None:
	tc, res, sigs, fn_id = _typecheck_fn(
		"""
trait Show { fn show(self: Int) returns Int }

implement Show for Int {
	pub fn show(self: Int) returns Int { return self; }
}

fn f<T>(x: T) returns Int require T is Show {
	if T is Show { return 1; } else { return 2; }
}

fn main() returns Int { return f<type Int>(1); }
""",
		tmp_path,
		"f",
	)
	assert res.diagnostics == []
