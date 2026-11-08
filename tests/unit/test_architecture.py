"""Enforce layer boundaries by inspecting imports in the source tree."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import tg_sales

PACKAGE_DIR = Path(tg_sales.__file__).resolve().parent

QT = ("PySide6", "pyqtgraph")  # the desktop toolkit is gone and must not come back
WEB = ("fastapi", "starlette", "uvicorn", "tg_sales.api", "tg_sales.launcher")
DATABASE = ("sqlalchemy", "alembic", "sqlite3", "psycopg", "tg_sales.db", "tg_sales.repositories")
NETWORK = ("httpx", "tg_sales.integrations")

FORBIDDEN_IMPORTS: dict[str, tuple[str, ...]] = {
    "domain": (*QT, *WEB, *DATABASE, *NETWORK, "tg_sales.services"),
    "services": (*QT, *WEB),
    "repositories": (*QT, *WEB, *NETWORK, "tg_sales.services"),
    "db": (*QT, *WEB, *NETWORK, "tg_sales.services"),
    "integrations": (*QT, *WEB, *DATABASE, "tg_sales.services"),
    "sync": (*QT, *WEB, *NETWORK),
    "reports": (*QT, *WEB, *NETWORK),
    "legacy": (*QT, *WEB, *NETWORK),
    "api": QT,
    "launcher": QT,
}


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def violations(source: str, layer: str) -> list[str]:
    forbidden = FORBIDDEN_IMPORTS[layer]
    return sorted(
        module
        for module in imported_modules(source)
        if any(module == f or module.startswith(f"{f}.") for f in forbidden)
    )


def test_violation_detection_catches_forbidden_imports() -> None:
    source = "import sqlalchemy.orm\nfrom tg_sales.db.engine import x\nfrom tg_sales.dbx import y\n"
    assert violations(source, "domain") == ["sqlalchemy.orm", "tg_sales.db.engine"]


def test_every_layer_package_exists() -> None:
    for layer in FORBIDDEN_IMPORTS:
        assert (PACKAGE_DIR / layer / "__init__.py").is_file(), layer


@pytest.mark.parametrize("layer", sorted(FORBIDDEN_IMPORTS))
def test_layer_respects_dependency_rules(layer: str) -> None:
    problems = {
        str(path.relative_to(PACKAGE_DIR)): found
        for path in sorted((PACKAGE_DIR / layer).rglob("*.py"))
        if (found := violations(path.read_text(encoding="utf-8"), layer))
    }
    assert problems == {}
