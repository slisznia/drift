set shell := ["bash", "-lc"]

parse-all: parse-playground parse-examples
	@echo "Done."

# Parse every Drift snippet under playground/ to ensure the grammar accepts them.
parse-playground:
	just lint-tabs
	python3 tools/parse_playground.py

# Parse every Drift example under examples/
parse-examples:
	just lint-tabs
	python3 tools/parse_playground.py examples

# Ensure .drift files use tabs for indentation
lint-tabs:
	@git grep -nE '^[ ]{2,}' -- '*.drift' && { echo 'Found space-indented lines in .drift files'; exit 1; } || true
