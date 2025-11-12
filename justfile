set shell := ["bash", "-lc"]

# Parse every Drift snippet under playground/ to ensure the grammar accepts them.
parse-playground:
	python3 tools/parse_playground.py
