"""Enforce the dependency rule between the source layers.

domain/ imports only the standard library and other domain modules.
application/ imports domain/ and the standard library.
adapters/ and cli.py may import anything, but `typesafe_sdk` is imported only by
adapters/typesafe_judge.py (and, under tests/, only by the two TypeSafe adapter tests).
Exit status is non-zero when any import breaks a rule.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "harness_drift_detector"
SRC = ROOT / "src" / PACKAGE
TESTS = ROOT / "tests"

LAYER_ALLOWED_INTERNAL: dict[str, set[str]] = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "adapters": {"domain", "adapters"},
    "root": {"domain", "application", "adapters", "root"},
}
LAYERS_WITHOUT_THIRD_PARTY = {"domain", "application"}
TYPESAFE_MODULE = "typesafe_sdk"
TYPESAFE_ALLOWED_SRC = {SRC / "adapters" / "typesafe_judge.py"}
TYPESAFE_ALLOWED_TESTS = {
    TESTS / "adapters" / "test_typesafe_judge.py",
    TESTS / "adapters" / "test_typesafe_live.py",
}
STDLIB = set(sys.stdlib_module_names)


def layer_of(path: Path) -> str:
    relative = path.relative_to(SRC)
    if len(relative.parts) == 1:
        return "root"
    return relative.parts[0]


def internal_layer(module: str) -> str | None:
    """Layer named by an absolute module path inside the package, or None when external."""
    parts = module.split(".")
    if parts[0] != PACKAGE:
        return None
    if len(parts) == 1 or parts[1] in {"cli", "__init__"}:
        return "root"
    return parts[1]


def resolve_relative(path: Path, level: int, module: str | None) -> str:
    package_parts = list(path.relative_to(ROOT / "src").with_suffix("").parts)
    package_parts = package_parts[:-1] if path.name == "__init__.py" else package_parts[:-1]
    base = package_parts[: len(package_parts) - (level - 1)] if level > 1 else package_parts
    return ".".join(base + ([module] if module else []))


def imports_of(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append((node.lineno, resolve_relative(path, node.level, node.module)))
            elif node.module:
                found.append((node.lineno, node.module))
    return found


def check_source() -> list[str]:
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        layer = layer_of(path)
        for lineno, module in imports_of(path):
            top = module.split(".")[0]
            where = f"{path.relative_to(ROOT)}:{lineno}"
            target = internal_layer(module)
            if target is not None:
                if target not in LAYER_ALLOWED_INTERNAL[layer]:
                    violations.append(f"{where}: {layer} imports {module} ({target} layer)")
                continue
            if top == TYPESAFE_MODULE and path not in TYPESAFE_ALLOWED_SRC:
                violations.append(
                    f"{where}: {TYPESAFE_MODULE} is only allowed in adapters/typesafe_judge.py"
                )
                continue
            if layer in LAYERS_WITHOUT_THIRD_PARTY and top not in STDLIB:
                violations.append(f"{where}: {layer} imports third-party module {module}")
    return violations


def check_tests() -> list[str]:
    violations: list[str] = []
    if not TESTS.exists():
        return violations
    for path in sorted(TESTS.rglob("*.py")):
        for lineno, module in imports_of(path):
            if module.split(".")[0] == TYPESAFE_MODULE and path not in TYPESAFE_ALLOWED_TESTS:
                violations.append(
                    f"{path.relative_to(ROOT)}:{lineno}: {TYPESAFE_MODULE} is only allowed "
                    "in the TypeSafe adapter tests"
                )
    return violations


def main() -> int:
    violations = check_source() + check_tests()
    for violation in violations:
        print(violation)
    if violations:
        print(f"verify-layering: {len(violations)} violation(s).")
        return 1
    print("verify-layering: dependency rule holds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
