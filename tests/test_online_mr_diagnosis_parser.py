from __future__ import annotations

import ast
from pathlib import Path


PARSER_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "netconsole"
    / "services"
    / "rail_transit"
    / "online_mr_diagnosis_parser.py"
)


def test_online_mr_diagnosis_parser_has_no_sqlite_boundary_calls() -> None:
    source = PARSER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_names = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "sqlite3" not in imported_modules
    assert "sqlite3" not in imported_names
    assert not {"connect", "execute", "executemany", "executescript", "commit"}.intersection(
        called_attributes
    )
    assert not any(
        statement in source.upper()
        for statement in (
            "CREATE TABLE",
            "CREATE INDEX",
            "INSERT INTO",
            "DELETE FROM",
            "DROP TABLE",
            "SELECT COUNT",
        )
    )
