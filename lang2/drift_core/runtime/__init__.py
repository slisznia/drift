# Helper to list runtime C sources for linking.
from pathlib import Path
from typing import List

def get_runtime_sources(root: Path) -> List[Path]:
	base = root / "lang2" / "drift_core" / "runtime"
	return [
		base / "array_runtime.c",
		base / "string_runtime.c",
		base / "argv_runtime.c",
		base / "console_runtime.c",
	]

__all__ = ["get_runtime_sources"]
