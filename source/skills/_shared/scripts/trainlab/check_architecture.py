from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

from trainlab.contracts.interfaces import (
    UNCONFIGURED_POLICIES,
    PendingDecision,
    validate_schema_examples,
)
from trainlab.contracts.paths import WEB_STATIC_DIR, validate_static_mount
from trainlab.contracts.schema import BUSINESS_TABLES, SYSTEM_TABLES, table_contracts


def check_path_writes(tree: ast.AST) -> None:
    modules = {"sys"}
    paths: set[str] = set()
    nodes = list(ast.walk(tree))
    for node in nodes:
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "sys")
        if isinstance(node, ast.ImportFrom) and node.module == "sys":
            paths.update(a.asname or a.name for a in node.names if a.name == "path")

    def is_module(node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id in modules

    def is_path(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Name)
            and node.id in paths
            or isinstance(node, ast.Attribute)
            and node.attr == "path"
            and is_module(node.value)
        )

    changed = True
    while changed:
        before = (len(modules), len(paths))
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        if is_path(node.value):
                            paths.add(target.id)
                        if is_module(node.value):
                            modules.add(target.id)
        changed = before != (len(modules), len(paths))
    mutations = {
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "sort",
        "reverse",
        "__setitem__",
        "__delitem__",
        "__iadd__",
        "__imul__",
    }
    for node in nodes:
        forbidden = (
            isinstance(node, ast.Attribute)
            and is_path(node)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            or isinstance(node, ast.Subscript)
            and is_path(node.value)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            or isinstance(node, ast.AugAssign)
            and is_path(node.target)
        )
        if isinstance(node, ast.Call):
            func = node.func
            forbidden |= (
                isinstance(func, ast.Attribute) and is_path(func.value) and func.attr in mutations
            )
            forbidden |= (
                isinstance(func, ast.Name)
                and func.id in {"setattr", "delattr"}
                and len(node.args) >= 2
                and is_module(node.args[0])
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "path"
            )
        if forbidden:
            raise ValueError("runtime sys.path patch forbidden")


def implementation_file(path: Path) -> bool:
    if path.suffix.lower() in {
        ".py",
        ".pyw",
        ".pyc",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".rb",
        ".pl",
        ".ps1",
        ".exe",
        ".so",
        ".dylib",
    }:
        return True
    with path.open("rb") as file:
        return file.read(2) == b"#!" or bool(path.stat().st_mode & 0o111)


def check_layout(source: Path) -> None:
    for name in ("trainlab", "src", "index.py"):
        if (source / name).exists():
            raise ValueError("unapproved implementation root: " + name)
    if not (source / "schemas/contracts.schema.json").is_file():
        raise ValueError("public schema missing")
    generated = {"build", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
    for directory, dirs, files in os.walk(source):
        relative_dir = Path(directory).relative_to(source)
        dirs[:] = [
            d
            for d in dirs
            if not (
                relative_dir == Path(".")
                and (d in generated or d.endswith(".egg-info"))
                or d == "__pycache__"
                and relative_dir.parts
                and relative_dir.parts[0] in {"skills", "tests", "schemas"}
            )
        ]
        if relative_dir in {Path("frontend"), Path("tests"), Path("skills/local-web/web")}:
            dirs[:] = []
            continue
        for filename in files:
            path = Path(directory) / filename
            relative = path.relative_to(source)
            parts = relative.parts
            if parts[0] in {"frontend", "tests"}:
                continue
            if parts[0] == "schemas" and parts[1:] == ("__init__.py",):
                continue
            if not implementation_file(path):
                continue
            if len(parts) < 4 or parts[0] != "skills" or parts[2] != "scripts":
                raise ValueError("runtime implementation outside Skill/scripts: " + str(relative))
            if path.suffix == ".py":
                check_path_writes(ast.parse(path.read_text(encoding="utf-8")))


def main() -> int:
    root = Path.cwd()
    source = root if (root / "pyproject.toml").exists() else root / "source"
    check_layout(source)
    validate_static_mount(WEB_STATIC_DIR)
    tables = table_contracts()
    if (
        tuple(t.name for t in tables if t.business_table) != BUSINESS_TABLES
        or tuple(t.name for t in tables if not t.business_table) != SYSTEM_TABLES
    ):
        raise ValueError("table ownership mismatch")
    if set(UNCONFIGURED_POLICIES) != set(PendingDecision):
        raise ValueError("pending policy mismatch")
    validate_schema_examples()
    print("architecture and public Schema checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
