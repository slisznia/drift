# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
# author: Sławomir Liszniański; created: 2025-12-04
"""
Tests for stage4 throw_checks helpers.

We deliberately keep these tests tiny: they prove that stage4 can consume
stage3 ThrowSummary data, combine it with a `declared_can_throw` view, and
enforce basic invariants (no ConstructError in non-can-throw functions).
"""

from lang2.stage3 import ThrowSummary
from lang2.stage4 import (
	FuncThrowInfo,
	build_func_throw_info,
	enforce_can_throw_invariants,
)


def test_build_func_throw_info_combines_summary_and_decl():
	summaries = {
		"f": ThrowSummary(
			constructs_error=True,
			exception_types={"MyExc"},
			may_fail_sites={("entry", 0)},
		)
	}
	func_infos = build_func_throw_info(summaries, declared_can_throw={"f": True})
	assert "f" in func_infos
	info = func_infos["f"]
	assert isinstance(info, FuncThrowInfo)
	assert info.constructs_error is True
	assert info.exception_types == {"MyExc"}
	assert ("entry", 0) in info.may_fail_sites
	assert info.declared_can_throw is True


def test_enforce_can_throw_invariants_raises_for_non_declared_thrower():
	summaries = {
		"g": ThrowSummary(
			constructs_error=True,
			exception_types=set(),
			may_fail_sites=set(),
		)
	}
	func_infos = build_func_throw_info(summaries, declared_can_throw={"g": False})
	try:
		enforce_can_throw_invariants(func_infos)
		raised = False
	except RuntimeError:
		raised = True
	assert raised, "expected invariant violation for non-can-throw function"


def test_enforce_can_throw_invariants_allows_declared_thrower():
	summaries = {
		"h": ThrowSummary(
			constructs_error=True,
			exception_types=set(),
			may_fail_sites=set(),
		)
	}
	func_infos = build_func_throw_info(summaries, declared_can_throw={"h": True})
	# Should not raise
	enforce_can_throw_invariants(func_infos)
