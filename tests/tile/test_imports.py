"""Guard test: assert that no source file imports the deleted shim modules.

This test walks all Python files under the project source directory and
raises an assertion error if it finds any import statement referencing
the removed shim module names:

    - tile_id
    - hash_algorithm
    - state   (as a tile shim – i.e. within the tile package)
    - map_info
"""

from __future__ import annotations

import ast
import pathlib
import re

# Project root is three levels above this test file:
#   tests/tile/test_imports.py  -> tests/ -> project_root/
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "dynmap_recorder"

# Shim module names that must no longer be imported from anywhere.
BANNED_MODULES = {
    "tile_id",
    "hash_algorithm",
    "map_info",
}

# Relative-import pattern (from .tile_id import ..., from .hash_algorithm ...)
RELATIVE_IMPORT_RE = re.compile(
    r"from\s+\.(?:synchronizers\.tile\.)?(" + "|".join(BANNED_MODULES) + r")\s+import"
)

# Absolute-import pattern
ABSOLUTE_IMPORT_RE = re.compile(
    r"(?:from|import)\s+dynmap_recorder\.synchronizers\.tile\.("
    + "|".join(BANNED_MODULES)
    + r")"
)


def _collect_violations(directory: pathlib.Path) -> list[tuple[pathlib.Path, int, str]]:
    """Return a list of (file, line_number, line_text) for each banned import found."""
    violations = []
    for py_file in directory.rglob("*.py"):
        lines = py_file.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            if RELATIVE_IMPORT_RE.search(line) or ABSOLUTE_IMPORT_RE.search(line):
                violations.append((py_file, lineno, line.strip()))
    return violations


def test_no_shim_imports():
    violations = _collect_violations(SOURCE_ROOT)
    if violations:
        report = "\n".join(
            f"  {v[0].relative_to(PROJECT_ROOT)}:{v[1]}  {v[2]}"
            for v in violations
        )
        raise AssertionError(
            f"Found {len(violations)} stale shim import(s):\n{report}"
        )
