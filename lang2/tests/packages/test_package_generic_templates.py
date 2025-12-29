# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from pathlib import Path

from lang2.driftc.driftc import main as driftc_main
from lang2.driftc.packages.provider_v0 import load_package_v0


def _write_file(path: Path, text: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(text, encoding="utf-8")


def test_package_includes_generic_templates(tmp_path: Path) -> None:
	_write_file(
		tmp_path / "main.drift",
		"""
module main

import lib

fn main() returns Int nothrow {
	return 0
}
""".lstrip(),
	)
	_write_file(
		tmp_path / "lib" / "lib.drift",
		"""
module lib

export { id }

pub fn id<T>(x: T) returns T nothrow {
	return x
}
""".lstrip(),
	)
	_write_file(
		tmp_path / "lib" / "req.drift",
		"""
module lib

export { need }

pub fn need<T>(x: T) returns Int nothrow require T is Copy {
	return 1
}
""".lstrip(),
	)

	out = tmp_path / "p.dmp"
	argv = [
		"-M",
		str(tmp_path),
		str(tmp_path / "main.drift"),
		str(tmp_path / "lib" / "lib.drift"),
		str(tmp_path / "lib" / "req.drift"),
		"--package-id",
		"test.pkg",
		"--package-version",
		"0.0.0",
		"--package-target",
		"test",
		"--emit-package",
		str(out),
	]
	assert driftc_main(argv) == 0

	pkg = load_package_v0(out)
	lib_payload = pkg.modules_by_id["lib"].payload
	templates = lib_payload.get("generic_templates")
	assert isinstance(templates, list)
	entry = next(e for e in templates if isinstance(e, dict) and e.get("fn_symbol") == "lib::id")
	assert entry.get("ir_kind") == "TemplateHIR-v0"
	template_id = entry.get("template_id")
	assert isinstance(template_id, dict)
	assert template_id.get("module") == "lib"
	assert template_id.get("name") == "id"
	assert template_id.get("ordinal") == 0
	assert "require" in entry
	ir = entry.get("ir")
	assert isinstance(ir, dict)
	assert ir.get("_type") == "HBlock"
	sig = entry.get("signature")
	assert isinstance(sig, dict)
	assert sig.get("type_params") == ["T"]
	param_types = sig.get("param_types")
	assert isinstance(param_types, list)
	assert param_types[0].get("param") == "T"
	ret = sig.get("return_type")
	assert isinstance(ret, dict)
	assert ret.get("param") == "T"
	need = next(e for e in templates if isinstance(e, dict) and e.get("fn_symbol") == "lib::need")
	assert isinstance(need.get("require"), dict)
