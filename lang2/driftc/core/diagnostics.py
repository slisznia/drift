"""
Common diagnostic structure for checker/driver passes.

This is deliberately minimal for now: a message plus optional span/metadata.
The real compiler can extend this with richer location/types as needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .span import Span


@dataclass
class Diagnostic:
	"""Represents a compiler diagnostic (error/warning/etc.)."""

	message: str
	code: str | None = None
	# Optional diagnostic phase label.
	#
	# Most compiler code paths emit diagnostics into a phase-specific sink (parser,
	# typecheck, borrowcheck, codegen). Some early semantic validations happen
	# while still building HIR; in those cases, attaching an explicit phase makes
	# JSON output and test expectations unambiguous.
	phase: str | None = None
	severity: str = "error"
	span: Span = field(default_factory=Span)  # Source location (Span() denotes unknown).
	notes: list[str] = field(default_factory=list)

	def __post_init__(self) -> None:
		# Normalize missing spans to the sentinel Span() so downstream tooling
		# can rely on a structured object instead of None.
		if self.span is None:  # type: ignore[unreachable]
			self.span = Span()
