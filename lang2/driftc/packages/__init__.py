# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
"""
Package tooling (Milestone 4).

This package implements the **unsigned package artifact** format used by `driftc`
to bundle one or more modules for local consumption and later signing by `drift`.

Pinned model (from `docs/design/drift-tooling-and-packages.md`):
- `driftc` is offline and never performs network I/O.
- `drift` signs artifacts for distribution.
- `driftc` is still the gatekeeper at use time and must verify trust/policy
  before consuming any package contents.

Milestone 4 starts with an intentionally **unstable v0 payload**:
- payload_kind = "provisional-dmir"
- payload_version = 0

The container+manifest are designed to stay stable so later we can swap the
payload kind to real DMIR without rewriting the ecosystem.
"""

from __future__ import annotations

__all__ = [
	"package_v0",
]

