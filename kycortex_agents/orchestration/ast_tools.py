"""Internal AST helpers used by the Orchestrator facade."""

from __future__ import annotations

import ast
import copy
from typing import Mapping, Optional


class AstNameReplacer(ast.NodeTransformer):
    """Replace selected name nodes with AST expressions."""

    def __init__(self, replacements: Mapping[str, ast.expr]):
        self._replacements = dict(replacements)

    def visit_Name(self, node: ast.Name) -> ast.AST:
        replacement = self._replacements.get(node.id)
        if replacement is None:
            return node
        return ast.copy_location(copy.deepcopy(replacement), node)


def ast_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{ast_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        value_name = ast_name(node.value)
        slice_name = ast_name(node.slice)
        if value_name and slice_name:
            return f"{value_name}[{slice_name}]"
        return value_name
    if isinstance(node, ast.Tuple):
        return ", ".join(filter(None, (ast_name(element) for element in node.elts)))
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool)):
        return str(node.value)
    return ""


def is_pytest_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "fixture":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "fixture":
            return True
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Name) and func.id == "fixture":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "fixture":  # pragma: no branch
                return True
    return False


def callable_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def attribute_chain(node: Optional[ast.AST]) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = attribute_chain(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        base = attribute_chain(node.func)
        return f"{base}()" if base else ""
    return ""


def expression_root_name(node: ast.AST) -> Optional[str]:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Call):
        current = current.func
        while isinstance(current, ast.Attribute):
            current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None


def render_expression(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse is available on supported versions
        return attribute_chain(node) or node.__class__.__name__


def first_call_argument(node: ast.Call) -> Optional[ast.expr]:
    if node.args:
        return node.args[0]
    if node.keywords:
        return node.keywords[0].value
    return None


def python_import_roots(raw_content: object) -> set[str]:
    if not isinstance(raw_content, str) or not raw_content.strip():
        return set()

    try:
        tree = ast.parse(raw_content)
    except SyntaxError:
        return set()

    import_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                if root_name:
                    import_roots.add(root_name)
            continue
        if isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            module_name = (node.module or "").split(".", 1)[0]
            if module_name:
                import_roots.add(module_name)
    return import_roots