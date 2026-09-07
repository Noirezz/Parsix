"""Architecture audit: verifies domain, application, and modules have zero FastAPI/API dependencies."""

from __future__ import annotations

import ast
import os
from pathlib import Path


def test_core_layers_have_no_api_imports():
    root_dir = Path("services/made-core/src/made_core")
    isolated_dirs = ["domain", "application", "modules"]

    forbidden_modules = {"fastapi", "starlette", "made_api", "uvicorn"}

    violations: list[str] = []

    for sub in isolated_dirs:
        sub_path = root_dir / sub
        assert sub_path.exists(), f"Directory {sub_path} must exist"

        for py_file in sub_path.rglob("*.py"):
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_pkg = alias.name.split(".")[0]
                        if top_pkg in forbidden_modules:
                            violations.append(f"{py_file}:{node.lineno} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top_pkg = node.module.split(".")[0]
                        if top_pkg in forbidden_modules:
                            violations.append(f"{py_file}:{node.lineno} imports from {node.module}")

    assert not violations, f"Architectural violations found: {violations}"
