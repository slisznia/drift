# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lang2.driftc.driftc import main as driftc_main


def _write_file(path: Path, content: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content)


def _run_driftc_json(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
	rc = driftc_main(argv + ["--json"])
	out = capsys.readouterr().out
	payload = json.loads(out) if out.strip() else {}
	return rc, payload


def test_prelude_default_enables_println(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
	source = """
module m_main

fn main() nothrow -> Int{
	println("ok");
	return 0;
}
"""
	root = tmp_path / "mods"
	main_path = root / "m_main" / "main.drift"
	_write_file(main_path, source)
	rc, payload = _run_driftc_json(["-M", str(root), str(main_path)], capsys)
	assert rc == 0, payload


def test_no_prelude_rejects_unqualified_println(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
	source = """
module m_main

fn main() nothrow -> Int{
	println("ok");
	return 0;
}
"""
	root = tmp_path / "mods"
	main_path = root / "m_main" / "main.drift"
	_write_file(main_path, source)
	rc, payload = _run_driftc_json(["--no-prelude", "-M", str(root), str(main_path)], capsys)
	assert rc != 0
	msgs = [d.get("message", "") for d in payload.get("diagnostics", [])]
	assert any("println" in m for m in msgs)


def test_no_prelude_explicit_import_allows_println(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
	main_src = """
module m_main

import lang.core as core

fn main() nothrow -> Int{
	core.println("ok");
	return 0;
}
	"""
	root = tmp_path / "mods"
	main_path = root / "m_main" / "main.drift"
	_write_file(main_path, main_src)
	rc, payload = _run_driftc_json(["--no-prelude", "-M", str(root), str(main_path)], capsys)
	assert rc == 0, payload
