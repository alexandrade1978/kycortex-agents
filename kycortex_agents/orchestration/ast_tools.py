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