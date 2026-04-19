"""Internal AST helpers used by the Orchestrator facade."""

from __future__ import annotations

import ast
import copy
from typing import Mapping


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