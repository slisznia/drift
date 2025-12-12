# vim: set noexpandtab: -*- indent-tabs-mode: t -*-
"""
Guard the shape of MIR call instructions so we don't accidentally reintroduce
error-edge fields. Calls are plain instructions in the value-based error model.
"""

from lang2.driftc.stage2 import Call, MethodCall


def test_call_has_only_dest_fn_args():
	"""Call should remain a simple instruction with dest/fn/args only."""
	field_names = set(Call.__dataclass_fields__.keys())
	assert field_names == {"dest", "fn", "args"}


def test_method_call_has_only_dest_receiver_method_args():
	"""MethodCall should remain a simple instruction with dest/receiver/method_name/args only."""
	field_names = set(MethodCall.__dataclass_fields__.keys())
	assert field_names == {"dest", "receiver", "method_name", "args"}
