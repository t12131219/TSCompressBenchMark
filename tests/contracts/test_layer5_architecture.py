import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_statistics_and_reporting_keep_the_layer_dependency_boundary() -> None:
    forbidden = {
        "tscompbench.adapters",
        "tscompbench.codecs",
        "tscompbench.execution",
        "tscompbench.validation",
        "tscompbench.runner",
    }
    statistics_imports: set[str] = set()
    for path in (PROJECT_ROOT / "src" / "tscompbench" / "statistics").glob("*.py"):
        statistics_imports.update(_imports(path))
    reporting_imports: set[str] = set()
    for path in (PROJECT_ROOT / "src" / "tscompbench" / "reporting").glob("*.py"):
        reporting_imports.update(_imports(path))

    assert not {
        imported
        for imported in statistics_imports
        if any(imported == name or imported.startswith(name + ".") for name in forbidden)
    }
    assert not {
        imported
        for imported in reporting_imports
        if any(imported == name or imported.startswith(name + ".") for name in forbidden)
    }
    assert "tscompbench.statistics" in reporting_imports
