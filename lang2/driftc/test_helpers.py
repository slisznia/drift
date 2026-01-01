# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
from __future__ import annotations

from lang2.driftc.core.types_core import TypeTable
from lang2.driftc.traits.linked_world import LinkedWorld, RequireEnv, build_require_env, link_trait_worlds


def build_linked_world(type_table: TypeTable | None) -> tuple[LinkedWorld, RequireEnv]:
	"""
	Shared helper for tests: build LinkedWorld + RequireEnv from a TypeTable.

	This centralizes the linking logic so test harnesses don't drift from the
	compiler pipeline.
	"""
	trait_worlds = getattr(type_table, "trait_worlds", {}) if type_table is not None else {}
	if not isinstance(trait_worlds, dict):
		trait_worlds = {}
	linked_world = link_trait_worlds(trait_worlds)
	default_package = getattr(type_table, "package_id", None)
	module_packages = getattr(type_table, "module_packages", None)
	return linked_world, build_require_env(
		linked_world,
		default_package=default_package,
		module_packages=module_packages,
	)
