from pathlib import Path
import pytest

from lang2.driftc import stage1 as H
from lang2.driftc.core.function_id import FunctionId
from lang2.driftc.parser import parse_drift_to_hir


def _main_fn_id(fn_ids_by_name: dict[str, list[FunctionId]]) -> FunctionId:
	ids = fn_ids_by_name.get("main") or []
	if len(ids) == 1:
		return ids[0]
	qualified = [name for name in fn_ids_by_name.keys() if name.endswith("::main")]
	assert len(qualified) == 1
	ids = fn_ids_by_name.get(qualified[0]) or []
	assert len(ids) == 1
	return ids[0]


def test_parse_simple_return(tmp_path: Path):
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn main() returns Int {
    return 42;
}
"""
	)
	func_hirs, sigs, fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics == []
	assert {fid.name for fid in func_hirs} == {"main"}
	fn_id = _main_fn_id(fn_ids_by_name)
	assert sigs[fn_id].return_type.name == "Int"
	block = func_hirs[fn_id]
	assert len(block.statements) == 1
	assert isinstance(block.statements[0], H.HReturn)
	assert isinstance(block.statements[0].value, H.HLiteralInt)


def test_parse_float_literal(tmp_path: Path):
	src = tmp_path / "main.drift"
	src.write_text(
		"""
	fn main() returns Float {
	    return 1.25;
	}
	"""
	)
	func_hirs, sigs, fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics == []
	assert {fid.name for fid in func_hirs} == {"main"}
	fn_id = _main_fn_id(fn_ids_by_name)
	assert sigs[fn_id].return_type.name == "Float"
	block = func_hirs[fn_id]
	assert isinstance(block.statements[0], H.HReturn)
	assert isinstance(block.statements[0].value, H.HLiteralFloat)


@pytest.mark.parametrize(
	"lit",
	[
		"1.",
		".5",
		"1e-3",
		"1.0e",
		"1.0e+",
		"1_0.0",
	],
)
def test_invalid_float_literals_produce_diagnostics(tmp_path: Path, lit: str):
	"""
	Float literal MVP rules (see work/float-type/work-progress.md):
	- dot required with digits on both sides
	- exponent requires dot form
	- no underscores

	These should be rejected as normal parser diagnostics (not hard crashes).
	"""
	src = tmp_path / "main.drift"
	src.write_text(f"fn main() returns Float {{ return {lit}; }}\n")
	_func_hirs, _sigs, _fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics, f"expected diagnostics for invalid float literal {lit!r}"
	assert any(d.severity == "error" for d in diagnostics)


def test_parse_fnresult_ok(tmp_path: Path):
	"""
	FnResult is an internal ABI carrier in lang2, not a surface type.

	The parser should accept the syntax (so we can diagnose it with spans), but
	should emit an error diagnostic instructing users to write `returns T`.
	"""
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn callee() returns FnResult<Int, Error> {
    return 1;
}
"""
	)
	_func_hirs, _sigs, _fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics
	assert any("internal-only type 'FnResult'" in d.message for d in diagnostics)


def test_parse_ok_as_attr_stays_call(tmp_path: Path):
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn main() returns Int {
    return ns.Ok(1);
}
"""
	)
	func_hirs, sigs, fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics == []
	assert {fid.name for fid in func_hirs} == {"main"}
	fn_id = _main_fn_id(fn_ids_by_name)
	assert sigs[fn_id].return_type.name == "Int"
	main = func_hirs[fn_id]
	assert isinstance(main.statements[0], H.HReturn)
	# ns.Ok should not be rewritten to HResultOk (attr call stays a normal call)
	assert isinstance(main.statements[0].value, (H.HCall, H.HMethodCall))


def test_parse_throw_stmt(tmp_path: Path):
	src = tmp_path / "main.drift"
	src.write_text(
		"""
module m

exception Boom()

fn main() returns Int {
    throw Boom();
}
"""
	)
	func_hirs, sigs, fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics == []
	fn_id = _main_fn_id(fn_ids_by_name)
	assert sigs[fn_id].return_type.name == "Int"
	main = func_hirs[fn_id]
	assert isinstance(main.statements[0], H.HThrow)


def test_parse_raise_expr_maps_to_throw(tmp_path: Path):
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn main() returns Int {
    raise err_val;
}
"""
	)
	func_hirs, sigs, fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics == []
	fn_id = _main_fn_id(fn_ids_by_name)
	assert sigs[fn_id].return_type.name == "Int"
	main = func_hirs[fn_id]
	assert len(main.statements) == 1
	assert isinstance(main.statements[0], H.HThrow)


def test_implement_header_rejects_reference_target(tmp_path: Path):
	src = tmp_path / "impl_ref.drift"
	src.write_text(
		"""
implement &Point {
    fn move(self: &Point) returns Void { return; }
}
"""
	)
	_, _sigs, _fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics, "expected diagnostic for reference-qualified implement header"
	assert "nominal type" in diagnostics[0].message


def test_parse_while_stmt_lowering(tmp_path: Path):
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn main() returns Int {
    while true {
        return 1;
    }
}
"""
	)
	func_hirs, _sigs, fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics == []
	block = func_hirs[_main_fn_id(fn_ids_by_name)]
	assert isinstance(block.statements[0], H.HLoop)


def test_fnresult_typeids_are_resolved(tmp_path: Path):
	"""
	Ensure the resolver produces real TypeIds for a normal return type.

	FnResult is internal-only, but the type resolver still must produce real
	TypeIds (no fallback string/tuple resolution) for surface types.
	"""
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn drift_main() returns Int {
    return 1;
}
"""
	)
	_, sigs, fn_ids_by_name, type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics == []
	drift_ids = fn_ids_by_name.get("main::drift_main") or fn_ids_by_name.get("drift_main") or []
	assert len(drift_ids) == 1
	sig = sigs[drift_ids[0]]
	assert sig.return_type_id is not None
	assert type_table.get(sig.return_type_id).name == "Int"


def test_nonescaping_param_annotation_rejects_non_callable_param(tmp_path: Path):
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn apply(nonescaping f: Int, x: Int) returns Int {
    return x;
}
"""
	)
	_func_hirs, sigs, fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert any("nonescaping parameter" in d.message for d in diagnostics)
	apply_ids = fn_ids_by_name.get("main::apply") or fn_ids_by_name.get("apply") or []
	assert len(apply_ids) == 1
	sig = sigs[apply_ids[0]]
	assert sig.param_nonescaping == [True, False]


def test_nonescaping_param_annotation_accepts_callable_param(tmp_path: Path):
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn apply(nonescaping f: Fn, x: Int) returns Int {
    return x;
}
"""
	)
	_func_hirs, sigs, fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert diagnostics == []
	apply_ids = fn_ids_by_name.get("main::apply") or fn_ids_by_name.get("apply") or []
	assert len(apply_ids) == 1
	sig = sigs[apply_ids[0]]
	assert sig.param_nonescaping == [True, False]


def test_duplicate_function_definition_reports_diagnostic(tmp_path: Path) -> None:
	src = tmp_path / "main.drift"
	src.write_text(
		"""
fn main() returns Int { return 0; }
fn main() returns Int { return 1; }
"""
	)
	_, sigs, _fn_ids_by_name, _type_table, _exc_catalog, diagnostics = parse_drift_to_hir(src)
	assert any("duplicate function signature" in d.message for d in diagnostics)
	assert any(fid.name == "main" for fid in sigs)
