set shell := ["bash", "-lc"]
set quiet
CLANG_BIN := "clang-15"

# Default task: run the staged lang2 compiler tests.
default: lang2-test

test: test-ssa test-e2e
	@echo "test-ssa test-e2e: Success."

test-e2e:
	rm -rf build/tests/e2e
	./.venv/bin/python3 tests/e2e_runner.py

test-ssa:
	PYTHONPATH=. ./.venv/bin/python3 -m lang.mir_ssa_tests
	./.venv/bin/python3 tests/ssa_check_smoke.py
	./.venv/bin/python3 tests/ssa_programs_test.py
	if ! command -v {{CLANG_BIN}} >/dev/null 2>&1; then \
	  echo "{{CLANG_BIN}} is missing"; \
	  exit 1; \
	fi
	{{CLANG_BIN}} -Ilang -Ilang/runtime -o /tmp/runtime_error_dummy_raw tests/runtime_error_dummy_raw.c lang/runtime/error_dummy.c lang/runtime/string_runtime.c lang/runtime/diagnostic_runtime.c && /tmp/runtime_error_dummy_raw
	# legacy args test removed
	{{CLANG_BIN}} -Ilang -Ilang/runtime -o /tmp/runtime_diagnostic_value tests/runtime_diagnostic_value.c lang/runtime/diagnostic_runtime.c lang/runtime/string_runtime.c && /tmp/runtime_diagnostic_value

test-runtime-c:
	#!/usr/bin/env bash
	if ! command -v {{CLANG_BIN}} >/dev/null 2>&1; then
	  echo "{{CLANG_BIN}} is missing"
	  exit 1
	fi
	{{CLANG_BIN}} -Ilang -Ilang/runtime -o /tmp/runtime_error_dummy_raw tests/runtime_error_dummy_raw.c lang/runtime/error_dummy.c lang/runtime/string_runtime.c && /tmp/runtime_error_dummy_raw
	# legacy args test removed
	echo "test-runtime-c OK"

test-e2e-ssa-subset:
	rm -rf build/tests/e2e
	PYTHONPATH=. ./.venv/bin/python3 tests/e2e_runner.py hello throw_try try_catch try_call_error try_event_catch_stmt try_event_catch_expr try_event_catch_no_fallback array_string for_array console_hello ref_struct_mutation

# Loop a built e2e binary repeatedly to catch flakiness.
run-e2e-loop CASE="exception_args_dot" RUNS="1000":
	exe="build/tests/e2e/{{CASE}}/a.out"; \
	if [ ! -x "$exe" ]; then \
	  echo "missing $exe; build the case first (e.g., just test-e2e {{CASE}})" >&2; \
	  exit 1; \
	fi; \
	expect="tests/e2e/{{CASE}}/expected.json"; \
	./.venv/bin/python3 tools/run_loop.py --exe "$exe" --runs {{RUNS}} --expect-file "$expect"

parse-all: parse-examples
	@echo "parse-examples: Success."

# Parse every Drift example under examples/
parse-examples:
	./.venv/bin/python3 tools/draft_linter.py examples

# Lang2 staged compiler tests
lang2-test: lang2-stage1-test lang2-stage2-test lang2-stage3-test lang2-stage4-test lang2-parser-test lang2-core-test lang2-llvm-test lang2-borrow-test lang2-type-checker-test lang2-method-registry-test lang2-driver-suite lang2-codegen-test
	@echo "lang2 tests: Success."

lang2-stage1-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/stage1

lang2-stage2-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/stage2

lang2-stage3-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/stage3

lang2-stage4-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/stage4

# Parser tests (lang2 parser copy + adapter).
lang2-parser-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/parser

# Core TypeEnv/TypeTable tests.
lang2-core-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/core

# Type checker tests (typed HIR + resolution).
lang2-type-checker-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/type_checker

# Method registry/resolver tests.
lang2-method-registry-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/method_registry

# Driver/integration tests (driftc pipeline, try sugar, declared events).
lang2-driver-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/driver

lang2-driver-suite:
	# Full driver suite (lang2/tests/driver).
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/driver

# Basic LLVM codegen smoke test (llvmlite), kept separate from pytest collection.
lang2-llvm-test:
	./.venv/bin/python3 tools/test-llvm/test_codegen.py /tmp/lang2_test_codegen.o

# LLVM textual codegen tests (SSA→LLVM IR).
lang2-codegen-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	# Clean codegen artifacts to keep cases isolated between runs.
	rm -rf build/tests/lang2
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/codegen/llvm/tests
	# Run clang-based IR cases (per-case dirs under lang2/codegen/ir_cases).
	PYTHONPATH=. ./.venv/bin/python3 lang2/codegen/ir_cases/e2e_runner.py
	# Run Drift-source e2e cases (per-case dirs under lang2/codegen/tests/e2e).
	PYTHONPATH=. ./.venv/bin/python3 lang2/codegen/tests/e2e/runner.py --summarize

# Lang2 e2e runner (lang2.driftc: json + run modes against tests/e2e)
lang2-e2e CASES="":
	PYTHONPATH=. ./.venv/bin/python3 lang2/codegen/codegen_runner.py {{CASES}}

# Borrow checker scaffolding tests.
lang2-borrow-test:
	# Ensure pytest is available in the venv
	if ! ./.venv/bin/python3 -m pytest --version >/dev/null 2>&1; then \
	  echo "pytest is missing in .venv; please install it (e.g., .venv/bin/python3 -m pip install pytest)"; \
	  exit 1; \
	fi
	PYTHONPATH=. ./.venv/bin/python3 -m pytest -v lang2/tests/borrow_checker

stage-for-review:
	#!/usr/bin/env bash
	staged_dir=staged
	TODAY=$(date +'%Y-%m-%dT%H-%M-%S%Z')
	COMBINED_NAME="combined_${TODAY}.txt"
	rm -rf "$staged_dir"
	mkdir -p "$staged_dir"
	rm -f combined_*
	git ls-files -m -o --exclude-standard | while IFS= read -r f; do
		[ -f "$f" ] || continue
		mkdir -p "$staged_dir/$(dirname "$f")"
		cp -- "$f" "$staged_dir/$f"
	done
	mapfile -d '' files < <(find "$staged_dir/" -type f -print0 | sort -z)
	{
		echo "[==== AGENT INSTRUCTIONS ====]"
		echo "Role: Act as a production-compiler reviewer for Drift."
		echo "Primary constraints (in order): (1) semantic correctness + soundness, (2) adherence to and inspiration from: the Drift language spec (if you don't have it ask for it), modern languages like Rust, Java's Project Loom and POSIX C whenever our lang-spec is undrespecified, (3) determinism + reproducibility, (4) diagnostics quality/stability, (5) maintainability/extensibility, (6) performance (no hidden big-O or allocation cliffs)."
		echo "Review requirements: For each change/claim, verify against invariants, spec rules, and edge cases; when unsure (missing spec context), say exactly what can’t be verified and what assumption you’re making."
		echo "Output: Report only issues, risks, or better long-term alternatives. You can include Drift code snippets or pseudo code to illustrate solutions. If no issues, output “Reviewed and found no material issues to resolve.” and (optionally) a one-line checklist of what you verified. "
		echo "Decision rule: If multiple solutions exist, recommend the cleanest long-term design even if it’s more work; avoid speculative refactors unless requested. Don't say: If you want a “clean long-term alternative” - we positively want only "clean long-term", provide the plan for executing it. "
		echo "Style: concise, technical, no fluff."
		echo "Date: ${TODAY}"
		echo "[==== FILE LIST ====]"
		printf '%s\n' "${files[@]}"
		echo

		# feed awk a NUL-separated list so xargs -0 is happy
		printf '%s\0' "${files[@]}" |
			xargs -0 awk '
				FNR==1 { print "\n[==== File: " FILENAME " =====]" }
				{ print }
			'
	} > $COMBINED_NAME

	# rm -f staged.zip && zip -r staged.zip "$staged_dir"
