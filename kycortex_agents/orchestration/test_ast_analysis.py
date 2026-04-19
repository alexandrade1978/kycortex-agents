"""AST helpers for test-module analysis used by the Orchestrator facade."""

from __future__ import annotations

import ast
import builtins
from typing import Any, Callable, Dict, Iterator, Optional

from kycortex_agents.orchestration.ast_tools import (
    attribute_chain,
    expression_root_name,
    first_call_argument,
    render_expression,
)

MOCK_ASSERTION_ATTRIBUTES = {"call_count"}
MOCK_ASSERTION_METHODS = {
    "assert_any_call",
    "assert_called",
    "assert_called_once",
    "assert_called_once_with",
    "assert_called_with",
    "assert_has_calls",
    "assert_not_called",
}


def function_argument_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = {
        arg.arg
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    }
    if node.args.vararg is not None:
        names.add(node.args.vararg.arg)
    if node.args.kwarg is not None:
        names.add(node.args.kwarg.arg)
    return names


def collect_parametrized_argument_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute) or func.attr != "parametrize":
            continue
        parent = func.value
        if not (
            (isinstance(parent, ast.Attribute) and parent.attr == "mark")
            or (isinstance(parent, ast.Name) and parent.id == "mark")
        ):
            continue
        return extract_parametrize_argument_names(decorator)
    return set()


def extract_parametrize_argument_names(decorator: ast.Call) -> set[str]:
    argnames_node: Optional[ast.AST] = decorator.args[0] if decorator.args else None
    if argnames_node is None:
        for keyword in decorator.keywords:
            if keyword.arg == "argnames":
                argnames_node = keyword.value
                break
    if isinstance(argnames_node, ast.Constant) and isinstance(argnames_node.value, str):
        return {name.strip() for name in argnames_node.value.split(",") if name.strip()}
    if isinstance(argnames_node, (ast.List, ast.Tuple)):
        return {
            element.value.strip()
            for element in argnames_node.elts
            if isinstance(element, ast.Constant)
            and isinstance(element.value, str)
            and element.value.strip()
        }
    return set()


def iter_relevant_test_body_nodes(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield from iter_relevant_test_body_nodes(child)


def bound_target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return bound_target_names(target.value)
    if isinstance(target, (ast.List, ast.Tuple)):
        names: set[str] = set()
        for element in target.elts:
            names.update(bound_target_names(element))
        return names
    return set()


def collect_local_name_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = function_argument_names(node)
    names.update(collect_parametrized_argument_names(node))

    for stmt in node.body:
        for child in iter_relevant_test_body_nodes(stmt):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    names.update(bound_target_names(target))
            elif isinstance(child, ast.AnnAssign):
                names.update(bound_target_names(child.target))
            elif isinstance(child, ast.AugAssign):
                names.update(bound_target_names(child.target))
            elif isinstance(child, (ast.For, ast.AsyncFor)):
                names.update(bound_target_names(child.target))
            elif isinstance(child, (ast.With, ast.AsyncWith)):
                for item in child.items:
                    if item.optional_vars is not None:
                        names.update(bound_target_names(item.optional_vars))
            elif isinstance(child, ast.ExceptHandler) and child.name:
                names.add(child.name)
            elif isinstance(child, ast.NamedExpr):
                names.update(bound_target_names(child.target))
            elif isinstance(child, ast.comprehension):
                names.update(bound_target_names(child.target))
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    if alias.name != "*":
                        names.add(alias.asname or alias.name.split(".")[0])
    return names


def collect_undefined_local_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    module_defined_names: set[str],
) -> list[str]:
    allowed_names = set(dir(builtins))
    allowed_names.update(module_defined_names)
    allowed_names.update(collect_local_name_bindings(node))

    undefined_names: set[str] = set()
    for stmt in node.body:
        for child in iter_relevant_test_body_nodes(stmt):
            if not isinstance(child, ast.Name) or not isinstance(child.ctx, ast.Load):
                continue
            if child.id in allowed_names:
                continue
            undefined_names.add(f"{child.id} (line {child.lineno})")
    return sorted(undefined_names)


def collect_test_local_types(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    class_map: Dict[str, Any],
    function_map: Dict[str, Dict[str, Any]],
    infer_call_result_type: Callable[[Optional[ast.AST], Dict[str, str], Dict[str, Any], Dict[str, Dict[str, Any]]], Optional[str]],
) -> Dict[str, str]:
    local_types: Dict[str, str] = {}
    for stmt in node.body:
        for child in ast.walk(stmt):
            if isinstance(child, ast.Assign):
                inferred_type = infer_call_result_type(child.value, local_types, class_map, function_map)
                if inferred_type is None:
                    continue
                for target in child.targets:
                    for name in bound_target_names(target):
                        local_types[name] = inferred_type
            elif isinstance(child, ast.AnnAssign):
                inferred_type = infer_call_result_type(child.value, local_types, class_map, function_map)
                if inferred_type is None:
                    continue
                for name in bound_target_names(child.target):
                    local_types[name] = inferred_type
    return local_types


def known_type_allows_member(
    node: ast.Attribute,
    local_types: Dict[str, str],
    class_map: Dict[str, Any],
) -> bool:
    if not isinstance(node.value, ast.Name):
        return False
    owner_name = node.value.id
    owner_type = local_types.get(owner_name)
    if owner_type not in class_map and owner_name in class_map:
        owner_type = owner_name
    if owner_type not in class_map:
        return False
    class_info = class_map.get(owner_type, {})
    allowed = set(class_info.get("attributes") or [])
    if not class_info.get("is_enum"):
        allowed.update(class_info.get("fields") or [])
    allowed.update((class_info.get("method_signatures") or {}).keys())
    return node.attr in allowed


def is_mock_factory_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    callable_name = attribute_chain(node.func)
    if not callable_name:
        return False
    return callable_name in {"Mock", "MagicMock", "AsyncMock", "create_autospec"} or any(
        callable_name.endswith(suffix)
        for suffix in (
            ".Mock",
            ".MagicMock",
            ".AsyncMock",
            ".create_autospec",
        )
    )


def is_patch_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    callable_name = attribute_chain(node.func)
    if not callable_name:
        return False
    return (
        callable_name == "patch"
        or callable_name.endswith(".patch")
        or callable_name == "patch.object"
        or callable_name.endswith(".patch.object")
    )


def patched_target_name_from_call(node: ast.Call) -> Optional[str]:
    callable_name = attribute_chain(node.func)
    if not callable_name:
        return None
    if callable_name == "patch.object" or callable_name.endswith(".patch.object"):
        target_node = node.args[0] if len(node.args) >= 1 else None
        attribute_node = node.args[1] if len(node.args) >= 2 else None
        if target_node is None:
            for keyword in node.keywords:
                if keyword.arg == "target":
                    target_node = keyword.value
                elif keyword.arg in {"attribute", "name", "attr"}:
                    attribute_node = keyword.value
        target_name = attribute_chain(target_node) if target_node is not None else ""
        if (
            target_name
            and isinstance(attribute_node, ast.Constant)
            and isinstance(attribute_node.value, str)
        ):
            return f"{target_name}.{attribute_node.value}"
        return None
    target_node = first_call_argument(node)
    if isinstance(target_node, ast.Constant) and isinstance(target_node.value, str):
        return target_node.value
    return None


def collect_mock_support(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[set[str], set[str]]:
    mock_bindings = {
        name
        for name in function_argument_names(node)
        if name == "mocker" or name.startswith("mock")
    }
    patched_targets: set[str] = set()

    for stmt in node.body:
        for child in iter_relevant_test_body_nodes(stmt):
            if isinstance(child, ast.Assign):
                value = child.value
                if is_mock_factory_call(value) or is_patch_call(value):
                    for target in child.targets:
                        mock_bindings.update(bound_target_names(target))
                if isinstance(value, ast.Call) and is_patch_call(value):
                    patched_target = patched_target_name_from_call(value)
                    if patched_target:
                        patched_targets.add(patched_target)
            elif isinstance(child, ast.AnnAssign) and child.value is not None:
                value = child.value
                if is_mock_factory_call(value) or is_patch_call(value):
                    mock_bindings.update(bound_target_names(child.target))
                if isinstance(value, ast.Call) and is_patch_call(value):
                    patched_target = patched_target_name_from_call(value)
                    if patched_target:
                        patched_targets.add(patched_target)
            elif isinstance(child, (ast.With, ast.AsyncWith)):
                for item in child.items:
                    context_expr = item.context_expr
                    if not isinstance(context_expr, ast.Call) or not is_patch_call(context_expr):
                        continue
                    patched_target = patched_target_name_from_call(context_expr)
                    if patched_target:
                        patched_targets.add(patched_target)
                    if item.optional_vars is not None:
                        mock_bindings.update(bound_target_names(item.optional_vars))

    return mock_bindings, patched_targets


def supports_mock_assertion_target(
    node: ast.AST,
    mock_bindings: set[str],
    patched_targets: set[str],
) -> bool:
    target_name = attribute_chain(node)
    root_name = expression_root_name(node)
    if root_name and (root_name in mock_bindings or root_name.startswith("mock")):
        return True
    if target_name and target_name in patched_targets:
        return True
    return False


def find_unsupported_mock_assertions(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    local_types: Dict[str, str],
    class_map: Dict[str, Any],
) -> list[str]:
    mock_bindings, patched_targets = collect_mock_support(node)
    issues: set[str] = set()

    for child in ast.walk(node):
        member_node: Optional[ast.Attribute] = None
        target_node: Optional[ast.AST] = None

        if isinstance(child, ast.Attribute) and child.attr in MOCK_ASSERTION_ATTRIBUTES:
            member_node = child
            target_node = child.value
        elif (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in MOCK_ASSERTION_METHODS
        ):
            member_node = child.func
            target_node = child.func.value

        if member_node is None or target_node is None:
            continue
        if known_type_allows_member(member_node, local_types, class_map):
            continue
        if supports_mock_assertion_target(target_node, mock_bindings, patched_targets):
            continue
        issues.add(f"{render_expression(child)} (line {getattr(child, 'lineno', '?')})")

    return sorted(issues)


__all__ = [
    "MOCK_ASSERTION_ATTRIBUTES",
    "MOCK_ASSERTION_METHODS",
    "bound_target_names",
    "collect_local_name_bindings",
    "collect_mock_support",
    "collect_parametrized_argument_names",
    "collect_test_local_types",
    "collect_undefined_local_names",
    "extract_parametrize_argument_names",
    "find_unsupported_mock_assertions",
    "function_argument_names",
    "is_mock_factory_call",
    "is_patch_call",
    "iter_relevant_test_body_nodes",
    "known_type_allows_member",
    "patched_target_name_from_call",
    "supports_mock_assertion_target",
]
