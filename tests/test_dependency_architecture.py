import ast
import importlib.metadata as metadata
from pathlib import Path
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]


def production_requirements():
    return [
        Requirement(line)
        for raw in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    ]


def external_imports():
    modules = set()
    paths = [*(ROOT / "app").rglob("*.py"), *(ROOT / "alembic").rglob("*.py"), ROOT / "main.py"]
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Import):
                modules.update(item.name.split(".")[0] for item in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return modules - set(sys.stdlib_module_names) - {"app"}


def dependency_closure():
    mapping = metadata.packages_distributions()
    roots = {canonicalize_name(name) for module in external_imports() for name in mapping.get(module, [])}
    # These backends are selected by configuration rather than direct imports.
    pending = list(roots | {"bcrypt", "psycopg2-binary"})
    required = set()
    while pending:
        name = pending.pop()
        if name in required:
            continue
        required.add(name)
        for raw in metadata.requires(name) or []:
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(canonicalize_name(requirement.name))
    return required


def test_production_requirements_are_unique_exact_pins_matching_environment():
    names = [canonicalize_name(item.name) for item in production_requirements()]
    assert len(names) == len(set(names))
    for item in production_requirements():
        assert len(item.specifier) == 1
        assert next(iter(item.specifier)).operator == "=="
        if item.marker is None or item.marker.evaluate():
            assert metadata.version(item.name) in item.specifier, item.name


def test_runtime_imports_are_declared_in_production_requirements():
    declared = {canonicalize_name(item.name) for item in production_requirements()}
    mapping = metadata.packages_distributions()
    for module in external_imports():
        distributions = {canonicalize_name(name) for name in mapping.get(module, [])}
        assert distributions & declared, module


def test_runtime_dependency_tree_is_fully_pinned():
    declared = {canonicalize_name(item.name) for item in production_requirements()}
    assert not dependency_closure() - declared


def test_production_pins_have_no_unused_dependencies():
    active = {canonicalize_name(item.name) for item in production_requirements() if item.marker is None or item.marker.evaluate()}
    assert not active - dependency_closure()


def test_production_excludes_legacy_sqlite_drivers_and_development_tools():
    declared = {canonicalize_name(item.name) for item in production_requirements()}
    assert not declared & {"aiosqlite", "pysqlite3", "pysqlite3-binary", "python-jose", "ecdsa", "cryptography", "pytest", "pip-audit", "bandit", "httpx2"}
    assert "sqlite3" in sys.stdlib_module_names
    assert {"redis", "psycopg2-binary"} <= declared
