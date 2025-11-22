set shell := ["bash", "-lc"]

test: parse-all
	python3 tools/draft_linter.py tests/programs
	python3 tests/run_tests.py

parse-all: parse-playground parse-examples
	@echo "Parsing successful."

# Parse every Drift snippet under playground/ to ensure the grammar accepts them.
parse-playground:
	python3 tools/draft_linter.py playground
	python3 tools/parse_playground.py

# Parse every Drift example under examples/
parse-examples:
	python3 tools/draft_linter.py examples
	python3 tools/parse_playground.py examples
