"""Practical import guard, not a hostile-code sandbox."""

import ast
import sys
from importlib.util import resolve_name
from pathlib import Path


def import_violations(source: str, module: str, *, layer: str, is_package: bool = False):
    parent = module if is_package else module.rpartition(".")[0]
    errors = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            name = (
                resolve_name("." * node.level + (node.module or ""), parent)
                if node.level
                else node.module
            )
            names = [name]
            if node.module is None:
                names = [f"{name}.{alias.name}" for alias in node.names]
        else:
            continue
        for name in names:
            if name.startswith("visto."):
                target_layer = name.split(".")[1]
                if target_layer not in (
                    {"domain"} if layer == "domain" else {"domain", "application"}
                ):
                    errors.append(name)
            elif name.split(".")[0] not in sys.stdlib_module_names:
                errors.append(name)
    return errors


def test_guard_rejects_relative_outward_imports_in_modules_and_initializers():
    assert import_violations(
        "from ..adapters import api", "visto.domain", layer="domain", is_package=True
    ) == ["visto.adapters"]
    assert import_violations(
        "from ..adapters import api", "visto.domain.models", layer="domain"
    ) == ["visto.adapters"]
    assert import_violations(
        "from .. import adapters",
        "visto.application",
        layer="application",
        is_package=True,
    ) == ["visto.adapters"]
    assert (
        import_violations(
            "from .models import Goal", "visto.domain", layer="domain", is_package=True
        )
        == []
    )
    assert import_violations("import fastapi", "visto.application.ports", layer="application") == [
        "fastapi"
    ]


def test_inner_layers_import_only_stdlib_and_inward_packages():
    package = Path(__file__).resolve().parents[1] / "src/visto"
    checked = []
    for layer in ("domain", "application"):
        for source in (package / layer).rglob("*.py"):
            parts = source.relative_to(package).with_suffix("").parts
            is_package = source.name == "__init__.py"
            module = "visto." + ".".join(parts[:-1] if is_package else parts)
            assert (
                import_violations(
                    source.read_text(encoding="utf-8"), module, layer=layer, is_package=is_package
                )
                == []
            ), source
            checked.append(source)
    assert any("domain" in source.parts for source in checked)
    assert any("application" in source.parts for source in checked)
