# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
"""
Package reader/provider (v0).

This module reads unsigned package artifacts produced by `driftc` for Milestone 4.

It is intentionally narrow:
- verifies internal blob hashes from the manifest,
- exposes per-module interface and payload JSON objects.

Signature verification is a separate concern:
- Distributed packages are expected to be signed by `drift`.
- `driftc` is the final gatekeeper at use time.
- Milestone 4 allows unsigned packages only for local workspace outputs
  (e.g. `build/drift/localpkgs/`).
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from lang2.driftc.packages.package_v0 import sha256_hex


@dataclass(frozen=True)
class LoadedModuleV0:
	"""A single module loaded from a package artifact."""

	module_id: str
	interface: dict[str, Any]
	payload: dict[str, Any]


@dataclass(frozen=True)
class LoadedPackageV0:
	"""A loaded package artifact (unsigned container, v0 payload)."""

	path: Path
	manifest: dict[str, Any]
	modules_by_id: dict[str, LoadedModuleV0]


def _read_json_bytes(zf: zipfile.ZipFile, name: str) -> bytes:
	try:
		return zf.read(name)
	except KeyError as exc:
		raise ValueError(f"package is missing required entry '{name}'") from exc


def load_package_v0(path: Path) -> LoadedPackageV0:
	"""
	Load an unsigned package artifact and verify internal hashes.
	"""
	with zipfile.ZipFile(path) as zf:
		manifest_bytes = _read_json_bytes(zf, "manifest.json")
		manifest = json.loads(manifest_bytes.decode("utf-8"))

		if manifest.get("kind") != "drift-package":
			raise ValueError("not a drift-package artifact")
		if manifest.get("format") != 0:
			raise ValueError("unsupported package format version")

		blob_meta = manifest.get("blobs") or []
		blobs: dict[str, dict[str, Any]] = {b["sha256"]: b for b in blob_meta if isinstance(b, dict) and "sha256" in b}

		def _load_blob(sha: str) -> bytes:
			meta = blobs.get(sha)
			if meta is None:
				raise ValueError(f"manifest references unknown blob sha256 {sha}")
			ext = "json" if meta.get("kind") == "json" else "bin"
			data = _read_json_bytes(zf, f"blobs/{sha}.{ext}")
			if sha256_hex(data) != sha:
				raise ValueError(f"blob sha256 mismatch for {sha}")
			return data

		modules_by_id: dict[str, LoadedModuleV0] = {}
		for m in manifest.get("modules") or []:
			if not isinstance(m, dict):
				continue
			module_id = m.get("module_id")
			if not isinstance(module_id, str) or not module_id:
				raise ValueError("module entry missing module_id")
			if module_id in modules_by_id:
				raise ValueError(f"duplicate module_id '{module_id}' in package")
			iface_sha = m.get("interface_sha256")
			payload_sha = m.get("payload_sha256")
			if not isinstance(iface_sha, str) or not isinstance(payload_sha, str):
				raise ValueError(f"module '{module_id}' missing interface/payload hashes")

			iface_obj = json.loads(_load_blob(iface_sha).decode("utf-8"))
			payload_obj = json.loads(_load_blob(payload_sha).decode("utf-8"))
			modules_by_id[module_id] = LoadedModuleV0(module_id=module_id, interface=iface_obj, payload=payload_obj)

	return LoadedPackageV0(path=path, manifest=manifest, modules_by_id=modules_by_id)


def collect_external_exports(packages: Iterable[LoadedPackageV0]) -> dict[str, dict[str, set[str]]]:
	"""
	Collect export sets (values/types) from loaded packages.

This is used by the workspace loader to accept imports satisfied by packages.
	"""
	out: dict[str, dict[str, set[str]]] = {}
	for pkg in packages:
		for mid, mod in pkg.modules_by_id.items():
			exp = mod.interface.get("exports") if isinstance(mod.interface, dict) else None
			values_raw = []
			types_raw = []
			if isinstance(exp, dict):
				values_raw = exp.get("values") or []
				types_raw = exp.get("types") or []
			values = {str(v) for v in values_raw if isinstance(v, (str, int))}
			types = {str(t) for t in types_raw if isinstance(t, (str, int))}
			prev = out.get(mid)
			if prev is None:
				out[mid] = {"values": values, "types": types}
			else:
				prev["values"].update(values)
				prev["types"].update(types)
	return out


def discover_package_files(roots: Iterable[Path]) -> list[Path]:
	"""
	Discover package artifact files under the given roots.

MVP convention: any `*.dmp` file is a package artifact.
	"""
	out: list[Path] = []
	for root in roots:
		if root.is_file() and root.suffix == ".dmp":
			out.append(root)
			continue
		if not root.exists():
			continue
		for p in sorted(root.rglob("*.dmp")):
			if p.is_file():
				out.append(p)
	return out
