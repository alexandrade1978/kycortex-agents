"""AST helpers for test-module analysis used by the Orchestrator facade."""

from __future__ import annotations

import ast
import builtins
import re
from typing import Any, Callable, Dict, Iterator, Optional, cast

from kycortex_agents.orchestration.ast_tools import (
    ast_name,
    attribute_chain,
    callable_name,
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


def ast_contains_node(root: ast.AST, target: ast.AST) -> bool:
    return any(candidate is target for candidate in ast.walk(root))


def parent_map(root: ast.AST) -> Dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(root)
        for child in ast.iter_child_nodes(parent)
    }


def collect_local_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, ast.AST]:
    bindings: Dict[str, ast.AST] = {}
    for stmt in node.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            bindings[stmt.targets[0].id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            bindings[stmt.target.id] = stmt.value
    return bindings


def resolve_bound_value(
    node: Optional[ast.AST],
    bindings: Dict[str, ast.AST],
    *,
    max_depth: int = 3,
) -> Optional[ast.AST]:
    current = node
    depth = 0
    while isinstance(current, ast.Name) and depth < max_depth:
        current = bindings.get(current.id, current)
        depth += 1
    return current


def call_argument_value(
    node: ast.Call,
    argument_name: str,
    class_map: Dict[str, Any],
) -> Optional[ast.AST]:
    for keyword in node.keywords:
        if keyword.arg == argument_name:
            return keyword.value
    if not isinstance(node.func, ast.Name):
        return None
    constructor_params = class_map.get(node.func.id, {}).get("constructor_params") or []
    if argument_name not in constructor_params:
        return None
    argument_index = constructor_params.index(argument_name)
    if argument_index < len(node.args):
        return node.args[argument_index]
    return None


def extract_literal_dict_keys(
    node: Optional[ast.AST],
    bindings: Dict[str, ast.AST],
    class_map: Optional[Dict[str, Any]] = None,
) -> Optional[set[str]]:
    resolved = resolve_bound_value(node, bindings)
    if isinstance(resolved, ast.Dict):
        return {
            key.value
            for key in resolved.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    if (
        isinstance(resolved, ast.Subscript)
        and isinstance(resolved.slice, ast.Constant)
        and isinstance(resolved.slice.value, str)
    ):
        source = resolve_bound_value(resolved.value, bindings)
        if isinstance(source, ast.Dict):
            for key_node, value_node in zip(source.keys, source.values):
                if isinstance(key_node, ast.Constant) and key_node.value == resolved.slice.value:
                    return extract_literal_dict_keys(value_node, bindings, class_map)
    if isinstance(resolved, ast.Call):
        for candidate_name in ("data", "payload", "request", "item"):
            candidate_value = call_argument_value(resolved, candidate_name, class_map or {})
            nested_keys = extract_literal_dict_keys(candidate_value, bindings, class_map)
            if nested_keys is not None:
                return nested_keys
    return None


def extract_literal_field_values(
    node: Optional[ast.AST],
    bindings: Dict[str, ast.AST],
    field_name: str,
    class_map: Dict[str, Any],
) -> list[str]:
    resolved = resolve_bound_value(node, bindings)
    if isinstance(resolved, ast.Dict):
        for key_node, value_node in zip(resolved.keys, resolved.values):
            if isinstance(key_node, ast.Constant) and key_node.value == field_name:
                return extract_string_literals(value_node, bindings)
        return []
    if isinstance(resolved, ast.Call):
        direct_value = call_argument_value(resolved, field_name, class_map)
        if direct_value is not None:
            return extract_string_literals(direct_value, bindings)
        nested_payload = call_argument_value(resolved, "data", class_map)
        if nested_payload is not None:
            return extract_literal_field_values(nested_payload, bindings, field_name, class_map)
    return []


def extract_string_literals(node: Optional[ast.AST], bindings: Dict[str, ast.AST]) -> list[str]:
    resolved = resolve_bound_value(node, bindings)
    if isinstance(resolved, ast.Constant) and isinstance(resolved.value, str):
        return [resolved.value]
    return []


def extract_literal_list_items(
    node: Optional[ast.AST],
    bindings: Dict[str, ast.AST],
) -> Optional[list[ast.AST]]:
    resolved = resolve_bound_value(node, bindings)
    if isinstance(resolved, ast.List):
        return list(resolved.elts)
    return None


def infer_argument_type(
    payload_node: Optional[ast.AST],
    bindings: Dict[str, ast.AST],
    field_name: str,
    class_map: Dict[str, Any],
) -> str:
    if payload_node is None:
        return ""
    resolved = resolve_bound_value(payload_node, bindings)
    field_value: Optional[ast.AST] = None
    if isinstance(resolved, ast.Dict):
        for key_node, value_node in zip(resolved.keys, resolved.values):
            if isinstance(key_node, ast.Constant) and key_node.value == field_name:
                field_value = value_node
                break
    elif isinstance(resolved, ast.Call):
        field_value = call_argument_value(resolved, field_name, class_map)
    if field_value is None:
        return ""
    field_value = resolve_bound_value(field_value, bindings)
    if isinstance(field_value, ast.Constant):
        return type(field_value.value).__name__
    if isinstance(field_value, ast.Dict):
        return "dict"
    if isinstance(field_value, ast.List):
        return "list"
    if isinstance(field_value, ast.Tuple):
        return "tuple"
    if isinstance(field_value, ast.Set):
        return "set"
    if isinstance(field_value, ast.Call):
        func_name = ast_name(field_value.func)
        if func_name in {"dict", "list", "set", "tuple", "str", "int", "float", "bool"}:
            return func_name
    return ""


def call_argument_count(node: ast.Call) -> int:
    return len(node.args) + sum(1 for keyword in node.keywords if keyword.arg is not None)


def infer_expression_type(
    node: Optional[ast.AST],
    local_types: Dict[str, str],
    class_map: Dict[str, Any],
    function_map: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    if isinstance(node, ast.Name):
        owner_type = local_types.get(node.id)
        return owner_type if owner_type in class_map else None
    if isinstance(node, ast.Call):
        return infer_call_result_type(node, local_types, class_map, function_map)
    return None


def infer_call_result_type(
    node: Optional[ast.AST],
    local_types: Dict[str, str],
    class_map: Dict[str, Any],
    function_map: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        if node.func.id in class_map:
            return node.func.id
        function_info = function_map.get(node.func.id)
        if not isinstance(function_info, dict):
            return None
        return_annotation = function_info.get("return_annotation")
        return return_annotation if isinstance(return_annotation, str) and return_annotation in class_map else None
    if not isinstance(node.func, ast.Attribute):
        return None
    owner_type = infer_expression_type(node.func.value, local_types, class_map, function_map)
    if owner_type not in class_map:
        return None
    method_info = (class_map.get(owner_type, {}).get("method_signatures") or {}).get(node.func.attr)
    if not isinstance(method_info, dict):
        return None
    return_annotation = method_info.get("return_annotation")
    return return_annotation if isinstance(return_annotation, str) and return_annotation in class_map else None


def analyze_typed_test_member_usage(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    local_types: Dict[str, str],
    class_map: Dict[str, Any],
    function_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> tuple[list[str], list[str]]:
    invalid_member_refs: set[str] = set()
    call_arity_mismatches: set[str] = set()
    resolved_function_map = function_map or {}
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            owner_type = infer_expression_type(
                child.func.value,
                local_types,
                class_map,
                resolved_function_map,
            )
            if owner_type not in class_map:
                continue
            method_info = (class_map.get(owner_type, {}).get("method_signatures") or {}).get(child.func.attr)
            if not isinstance(method_info, dict):
                invalid_member_refs.add(f"{owner_type}.{child.func.attr} (line {child.lineno})")
                continue
            actual_count = call_argument_count(child)
            min_expected = method_info.get("min_args")
            max_expected = method_info.get("max_args")
            if not isinstance(min_expected, int) or not isinstance(max_expected, int):
                continue
            if min_expected <= actual_count <= max_expected:
                continue
            if min_expected == max_expected:
                call_arity_mismatches.add(
                    f"{owner_type}.{child.func.attr} expects {max_expected} args but test uses {actual_count} at line {child.lineno}"
                )
            else:
                call_arity_mismatches.add(
                    f"{owner_type}.{child.func.attr} expects {min_expected}-{max_expected} args but test uses {actual_count} at line {child.lineno}"
                )
        elif isinstance(child, ast.Attribute):
            owner_type = infer_expression_type(
                child.value,
                local_types,
                class_map,
                resolved_function_map,
            )
            if owner_type not in class_map:
                continue
            class_info = class_map.get(owner_type, {})
            allowed = set(class_info.get("attributes") or [])
            if not class_info.get("is_enum"):
                allowed.update(class_info.get("fields") or [])
            allowed.update((class_info.get("method_signatures") or {}).keys())
            if child.attr not in allowed:
                invalid_member_refs.add(f"{owner_type}.{child.attr} (line {child.lineno})")
    return sorted(invalid_member_refs), sorted(call_arity_mismatches)


def payload_argument_for_validation(node: ast.Call, callable_name: str) -> Optional[ast.expr]:
    if callable_name == "validate_request":
        return first_call_argument(node)
    if len(node.args) >= 2:
        return node.args[1]
    if node.keywords:
        for keyword in node.keywords:
            if keyword.arg in {"data", "payload", "request", "item"}:
                return keyword.value
    return first_call_argument(node)


def validate_batch_call(
    node: ast.Call,
    bindings: Dict[str, ast.AST],
    callable_name: str,
    batch_rule: Dict[str, Any],
) -> list[str]:
    violations: list[str] = []
    batch_arg = first_call_argument(node)
    batch_items = extract_literal_list_items(batch_arg, bindings)
    if batch_items is None:
        return violations

    required_fields = batch_rule.get("fields") or []
    request_key = batch_rule.get("request_key")
    wrapper_key = batch_rule.get("wrapper_key")
    for item in batch_items:
        resolved_item = resolve_bound_value(item, bindings)
        if not isinstance(resolved_item, ast.Dict):
            violations.append(
                f"{callable_name} expects dict-like batch items, but test uses {type(resolved_item).__name__} at line {getattr(item, 'lineno', node.lineno)}"
            )
            continue

        item_keys = extract_literal_dict_keys(resolved_item, bindings) or set()
        if request_key and request_key not in item_keys:
            violations.append(
                f"{callable_name} batch item missing required key: {request_key} at line {getattr(item, 'lineno', node.lineno)}"
            )
        if wrapper_key:
            nested_keys = extract_literal_dict_keys(
                ast.Subscript(value=resolved_item, slice=ast.Constant(value=wrapper_key)),
                bindings,
            )
            if nested_keys is None:
                violations.append(
                    f"{callable_name} batch item missing nested payload `{wrapper_key}` at line {getattr(item, 'lineno', node.lineno)}"
                )
                continue
            missing_nested_fields = [field for field in required_fields if field not in nested_keys]
            if missing_nested_fields:
                violations.append(
                    f"{callable_name} batch item nested `{wrapper_key}` missing required fields: {', '.join(missing_nested_fields)} at line {getattr(item, 'lineno', node.lineno)}"
                )
            continue

        missing_fields = [field for field in required_fields if field not in item_keys]
        if missing_fields:
            violations.append(
                f"{callable_name} batch item missing required fields: {', '.join(missing_fields)} at line {getattr(item, 'lineno', node.lineno)}"
            )

    return violations


def assert_expects_false(node: ast.Assert, call_node: ast.Call) -> bool:
    test = node.test
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return ast_contains_node(test.operand, call_node)
    if not isinstance(test, ast.Compare):
        return False

    def false_constant(item: ast.AST) -> bool:
        return isinstance(item, ast.Constant) and item.value is False

    if ast_contains_node(test.left, call_node):
        return any(false_constant(comparator) for comparator in test.comparators) and any(
            isinstance(op, (ast.Is, ast.Eq)) for op in test.ops
        )
    if any(ast_contains_node(comparator, call_node) for comparator in test.comparators):
        return false_constant(test.left) and any(isinstance(op, (ast.Is, ast.Eq)) for op in test.ops)
    return False


def call_has_negative_expectation(node: ast.Call, parent_map: Dict[ast.AST, ast.AST]) -> bool:
    current: Optional[ast.AST] = node
    while current is not None:
        parent = parent_map.get(current)
        if parent is None:
            return False
        if isinstance(parent, ast.Assert) and assert_expects_false(parent, node):
            return True
        if isinstance(parent, (ast.With, ast.AsyncWith)) and with_uses_pytest_raises(parent):
            return True
        current = parent
    return False


def invalid_outcome_subject_matches(
    node: ast.AST,
    result_name: Optional[str],
    payload_name: Optional[str],
) -> bool:
    if result_name and isinstance(node, ast.Name) and node.id == result_name:
        return True
    if (
        result_name is not None
        and isinstance(node, ast.Attribute)
        and node.attr in {"status", "state", "outcome", "result", "valid", "is_valid", "success", "accepted"}
        and isinstance(node.value, ast.Name)
        and node.value.id == result_name
    ):
        return True
    return (
        payload_name is not None
        and isinstance(node, ast.Attribute)
        and node.attr in {"status", "state", "outcome", "result", "valid", "is_valid", "success", "accepted"}
        and isinstance(node.value, ast.Name)
        and node.value.id == payload_name
    )


def invalid_outcome_marker_matches(node: ast.AST) -> bool:
    if not isinstance(node, ast.Constant):
        return False
    if node.value is False or node.value is None:
        return True
    return isinstance(node.value, str) and node.value.strip().lower() in {
        "invalid",
        "failed",
        "error",
        "pending",
        "rejected",
        "reject",
    }


def assert_expects_invalid_outcome(
    node: ast.AST,
    result_name: Optional[str],
    payload_name: Optional[str],
) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return invalid_outcome_subject_matches(node.operand, result_name, payload_name)

    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    if not isinstance(node.ops[0], (ast.Eq, ast.Is)):
        return False

    left = node.left
    right = node.comparators[0]
    return (
        invalid_outcome_subject_matches(left, result_name, payload_name)
        and invalid_outcome_marker_matches(right)
    ) or (
        invalid_outcome_subject_matches(right, result_name, payload_name)
        and invalid_outcome_marker_matches(left)
    )


def assigned_name_for_call(
    call_node: ast.Call,
    parent_map: Dict[ast.AST, ast.AST],
) -> Optional[str]:
    parent = parent_map.get(call_node)
    if isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
        return parent.targets[0].id
    if isinstance(parent, ast.AnnAssign) and isinstance(parent.target, ast.Name):
        return parent.target.id
    return None


def call_expects_invalid_outcome(
    test_node: ast.FunctionDef | ast.AsyncFunctionDef,
    call_node: ast.Call,
    parent_map: Dict[ast.AST, ast.AST],
) -> bool:
    result_name = assigned_name_for_call(call_node, parent_map)
    payload_arg = first_call_argument(call_node)
    payload_name = payload_arg.id if isinstance(payload_arg, ast.Name) else None

    for child in ast.walk(test_node):
        if not isinstance(child, ast.Assert) or getattr(child, "lineno", 0) <= getattr(call_node, "lineno", 0):
            continue
        if assert_expects_invalid_outcome(child.test, result_name, payload_name):
            return True
    return False


def batch_call_allows_partial_invalid_items(
    test_node: ast.FunctionDef | ast.AsyncFunctionDef,
    call_node: ast.Call,
    bindings: Dict[str, ast.AST],
    parent_map: Dict[ast.AST, ast.AST],
) -> bool:
    batch_items = extract_literal_list_items(first_call_argument(call_node), bindings)
    if batch_items is None or len(batch_items) <= 1:
        return False

    result_name = assigned_name_for_call(call_node, parent_map)
    batch_size = len(batch_items)
    for child in ast.walk(test_node):
        if not isinstance(child, ast.Assert):
            continue
        if assert_limits_batch_result(child.test, result_name, call_node, batch_size):
            return True
    return False


def analyze_test_behavior_contracts(
    tree: ast.AST,
    validation_rules: Dict[str, list[str]],
    field_value_rules: Dict[str, Dict[str, list[str]]],
    batch_rules: Dict[str, Dict[str, Any]],
    sequence_input_functions: set[str],
    function_names: set[str],
    class_map: Dict[str, Any],
) -> tuple[list[str], list[str]]:
    payload_violations: set[str] = set()
    non_batch_calls: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
            continue

        bindings = collect_local_bindings(node)
        node_parent_map = parent_map(node)
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            called_name = callable_name(child)
            if not called_name:
                continue
            negative_expectation = call_has_negative_expectation(child, node_parent_map)
            invalid_outcome_expectation = negative_expectation or call_expects_invalid_outcome(
                node,
                child,
                node_parent_map,
            )

            if called_name in validation_rules:
                payload_arg = payload_argument_for_validation(child, called_name)
                payload_node = resolve_bound_value(payload_arg, bindings)
                payload_keys = extract_literal_dict_keys(payload_node, bindings, class_map)
                if payload_keys is not None:
                    missing_fields = [field for field in validation_rules[called_name] if field not in payload_keys]
                    if missing_fields and not invalid_outcome_expectation:  # pragma: no branch
                        payload_violations.add(
                            f"{called_name} payload missing required fields: {', '.join(missing_fields)} at line {child.lineno}"
                        )

            if called_name in field_value_rules:
                payload_arg = payload_argument_for_validation(child, called_name)
                payload_node = resolve_bound_value(payload_arg, bindings)
                for field_name, allowed_values in field_value_rules[called_name].items():
                    observed_values = extract_literal_field_values(payload_node, bindings, field_name, class_map)
                    invalid_values = [value for value in observed_values if value not in allowed_values]
                    if invalid_values and not invalid_outcome_expectation:
                        payload_violations.add(
                            f"{called_name} field `{field_name}` uses unsupported values: {', '.join(invalid_values)} at line {child.lineno}"
                        )

            if called_name in batch_rules:
                batch_allows_partial_invalid = batch_call_allows_partial_invalid_items(
                    node,
                    child,
                    bindings,
                    node_parent_map,
                )
                batch_violations = [] if negative_expectation or batch_allows_partial_invalid else validate_batch_call(
                    child,
                    bindings,
                    called_name,
                    batch_rules[called_name],
                )
                payload_violations.update(batch_violations)
                continue

            if called_name in sequence_input_functions:
                continue

            if called_name in function_names and "batch" not in called_name:
                sequence_arg = first_call_argument(child)
                sequence_node = resolve_bound_value(sequence_arg, bindings)
                if isinstance(sequence_node, ast.List):
                    non_batch_calls.add(
                        f"{called_name} does not accept batch/list inputs at line {child.lineno}"
                    )

    return sorted(payload_violations), sorted(non_batch_calls)


def analyze_test_type_mismatches(
    tree: ast.AST,
    type_constraint_rules: Dict[str, Dict[str, list[str]]],
    class_map: Dict[str, Any],
) -> list[str]:
    if not type_constraint_rules:
        return []
    mismatches: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
            continue
        bindings = collect_local_bindings(node)
        node_parent_map = parent_map(node)
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            called_name = callable_name(child)
            if not called_name or called_name not in type_constraint_rules:
                continue
            if call_has_negative_expectation(child, node_parent_map):
                continue
            constraints = type_constraint_rules[called_name]
            payload_arg = payload_argument_for_validation(child, called_name)
            payload_node = resolve_bound_value(payload_arg, bindings)
            for field_name, allowed_types in constraints.items():
                observed_type = infer_argument_type(
                    payload_node, bindings, field_name, class_map,
                )
                if not observed_type:
                    continue
                allowed_lower = {t.lower() for t in allowed_types}
                if observed_type.lower() not in allowed_lower:
                    mismatches.add(
                        f"{called_name} passes {observed_type} for `{field_name}` (expected {', '.join(allowed_types)}) at line {child.lineno}"
                    )
    return sorted(mismatches)


def auto_fix_test_type_mismatches(
    test_content: str,
    code_content: str,
    dict_accessed_keys_from_tree: Callable[[ast.AST], Dict[str, list[str]]],
) -> str:
    """Auto-fix str->dict type mismatches in generated test code."""
    try:
        impl_tree = ast.parse(code_content)
    except SyntaxError:
        return test_content
    dict_keys = dict_accessed_keys_from_tree(impl_tree)
    if not dict_keys:
        return test_content

    skip_lines: set[int] = set()
    try:
        test_tree = ast.parse(test_content)
        for node in ast.walk(test_tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            name_lower = node.name.lower()
            is_negative = "validation_failure" in name_lower or "invalid" in name_lower
            if not is_negative:
                func_src = ast.get_source_segment(test_content, node) or ""
                if "is False" in func_src or "is_valid is False" in func_src:
                    is_negative = True
            if is_negative:
                start = node.lineno - 1
                end = node.end_lineno or node.lineno
                for line_number in range(start, end):
                    skip_lines.add(line_number)
    except SyntaxError:
        pass

    func_var_dict_ranges: list[tuple[int, int, set[str]]] = []
    try:
        test_tree = ast.parse(test_content)
        for node in ast.walk(test_tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            dict_assigned_vars: set[str] = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Assign) and len(child.targets) == 1:
                    target = child.targets[0]
                    if isinstance(target, ast.Name) and isinstance(child.value, ast.Dict):
                        dict_assigned_vars.add(target.id)
            start = node.lineno - 1
            end = node.end_lineno or node.lineno
            func_var_dict_ranges.append((start, end, dict_assigned_vars))
    except SyntaxError:
        pass

    lines = test_content.split("\n")
    for param_name, keys in dict_keys.items():
        if not keys:
            continue
        dict_literal = "{" + ", ".join(f"'{key}': 'value'" for key in sorted(keys)) + "}"
        str_pattern = re.compile(
            rf"\b({re.escape(param_name)})\s*=\s*(?:'[^']*'|\"[^\"]*\")"
        )
        for line_index, line in enumerate(lines):
            if line_index in skip_lines:
                continue
            if not str_pattern.search(line):
                continue
            replacement = dict_literal
            for start, end, dict_assigned_vars in func_var_dict_ranges:
                if start <= line_index < end and param_name in dict_assigned_vars:
                    replacement = param_name
                    break
            lines[line_index] = str_pattern.sub(rf"\1={replacement}", line)
    return "\n".join(lines)


def assert_limits_batch_result(
    test: ast.AST,
    result_name: Optional[str],
    call_node: ast.Call,
    batch_size: int,
) -> bool:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    op = test.ops[0]

    if len_call_matches_batch_result(test.left, result_name, call_node):
        compared_value = int_constant_value(test.comparators[0])
        return comparison_implies_partial_batch_result(op, compared_value, batch_size)

    if len_call_matches_batch_result(test.comparators[0], result_name, call_node):
        compared_value = int_constant_value(test.left)
        reversed_op = {
            ast.Lt: ast.Gt,
            ast.LtE: ast.GtE,
            ast.Gt: ast.Lt,
            ast.GtE: ast.LtE,
        }.get(type(op), type(op))
        return comparison_implies_partial_batch_result(reversed_op(), compared_value, batch_size)

    return False


def len_call_matches_batch_result(
    node: ast.AST,
    result_name: Optional[str],
    call_node: ast.Call,
) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Name) or node.func.id != "len" or len(node.args) != 1:
        return False
    candidate = node.args[0]
    if result_name is not None and isinstance(candidate, ast.Name) and candidate.id == result_name:
        return True
    return candidate is call_node


def int_constant_value(node: ast.AST) -> Optional[int]:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def comparison_implies_partial_batch_result(
    op: ast.cmpop,
    compared_value: Optional[int],
    batch_size: int,
) -> bool:
    if compared_value is None:
        return False
    if isinstance(op, ast.Eq):
        return compared_value < batch_size
    if isinstance(op, ast.Lt):
        return compared_value <= batch_size
    if isinstance(op, ast.LtE):
        return compared_value < batch_size
    return False


def name_suggests_validation_failure(test_name: str) -> bool:
    normalized_test_name = test_name.lower()
    return any(
        token in normalized_test_name
        for token in ("validation", "invalid", "reject", "failure", "error")
    )


def is_internal_score_state_target(rendered_target: str) -> bool:
    normalized_target = rendered_target.replace(" ", "").lower()
    if "score" not in normalized_target:
        return False
    if not ("." in normalized_target or "get_" in normalized_target):
        return False
    return bool(
        re.search(r"\.(?:get_)?(?:risk_)?scores?\b", normalized_target)
        or any(
            token in normalized_target
            for token in (
                "score_record",
                "score_records",
                "score_cache",
                "score_map",
            )
        )
    )


def behavior_contract_explicitly_limits_score_state_to_valid_requests(
    code_behavior_contract: str,
    rendered_target: str,
) -> bool:
    normalized_target = rendered_target.replace(" ", "").lower()
    if "risk_score" not in normalized_target:
        return False

    normalized_contract = code_behavior_contract.lower()
    if not re.search(r"risk[_ ]scores?", normalized_contract):
        return False

    return bool(
        re.search(r"risk[_ ]scores?.*\bonly\b.*\bvalid\b", normalized_contract)
        or re.search(r"appends?.*risk[_ ]scores?.*\bonly\b.*\bvalid\b", normalized_contract)
        or re.search(r"only\s+valid\s+requests?.*risk[_ ]scores?", normalized_contract)
        or re.search(r"valid\s+requests?.*append.*risk[_ ]scores?", normalized_contract)
    )


def is_len_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and len(node.args) == 1
        and not node.keywords
    )


def exact_len_assertion(node: ast.AST) -> Optional[tuple[str, int]]:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    if not isinstance(node.ops[0], ast.Eq):
        return None

    left = node.left
    right = node.comparators[0]
    if is_len_call(left):
        compared_value = int_constant_value(right)
        if compared_value is None:
            return None
        left_call = cast(ast.Call, left)
        return render_expression(left_call.args[0]), compared_value
    if is_len_call(right):
        compared_value = int_constant_value(left)
        if compared_value is None:
            return None
        right_call = cast(ast.Call, right)
        return render_expression(right_call.args[0]), compared_value
    return None


def loop_contains_non_batch_call(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        called_name = callable_name(child)
        if not called_name or called_name == "len":
            continue
        if "batch" in called_name.lower():
            continue
        return True
    return False


def visible_repeated_single_call_batch_sizes(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    bindings: Dict[str, ast.AST],
) -> list[int]:
    batch_sizes: list[int] = []
    for child in ast.walk(node):
        if not isinstance(child, (ast.For, ast.AsyncFor)):
            continue
        batch_items = extract_literal_list_items(child.iter, bindings)
        if batch_items is None or len(batch_items) <= 1:
            continue
        if not loop_contains_non_batch_call(child):
            continue
        batch_sizes.append(len(batch_items))
    return batch_sizes


def find_contract_overreach_signals(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    bindings: Dict[str, ast.AST],
    code_behavior_contract: str = "",
) -> list[str]:
    visible_batch_sizes = visible_repeated_single_call_batch_sizes(node, bindings)
    signals: set[str] = set()
    largest_batch_size = max(visible_batch_sizes) if visible_batch_sizes else None
    for child in ast.walk(node):
        if not isinstance(child, ast.Assert):
            continue
        assertion = exact_len_assertion(child.test)
        if assertion is None:
            continue
        asserted_target, compared_value = assertion
        normalized_target = asserted_target.replace(" ", "").lower()
        if largest_batch_size is not None and (
            "audit_log" in normalized_target or "audit_logs" in normalized_target
        ):
            if compared_value > largest_batch_size:
                signals.add(
                    f"exact batch audit length {compared_value} exceeds visible batch size {largest_batch_size} in {node.name} (line {child.lineno})"
                )

        if not name_suggests_validation_failure(node.name):
            continue
        if compared_value != 0:
            continue
        if not is_internal_score_state_target(asserted_target):
            continue
        if behavior_contract_explicitly_limits_score_state_to_valid_requests(
            code_behavior_contract,
            asserted_target,
        ):
            continue
        signals.add(
            "exact validation-failure score-state emptiness assertion on "
            f"'{asserted_target}' in {node.name} (line {child.lineno}) assumes rejected input leaves internal score state empty"
        )
    return sorted(signals)


def collect_module_defined_names(tree: ast.AST) -> set[str]:
    if not isinstance(tree, ast.Module):
        return set()

    names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                names.update(bound_target_names(target))
        elif isinstance(stmt, ast.AnnAssign):
            names.update(bound_target_names(stmt.target))
    return names


def with_uses_pytest_raises(node: ast.With | ast.AsyncWith) -> bool:
    for item in node.items:
        context_expr = item.context_expr
        if not isinstance(context_expr, ast.Call):
            continue
        called_name = context_expr.func.id if isinstance(context_expr.func, ast.Name) else None
        if called_name is None:
            from kycortex_agents.orchestration.ast_tools import callable_name

            called_name = callable_name(context_expr)
        if called_name == "raises":
            return True
    return False


def with_uses_pytest_assertion_context(node: ast.With | ast.AsyncWith) -> bool:
    for item in node.items:
        context_expr = item.context_expr
        if not isinstance(context_expr, ast.Call):
            continue
        called_name = context_expr.func.id if isinstance(context_expr.func, ast.Name) else None
        if called_name is None:
            from kycortex_agents.orchestration.ast_tools import callable_name

            called_name = callable_name(context_expr)
        if called_name in {"raises", "warns", "deprecated_call"}:
            return True
    return False


def count_test_assertion_like_checks(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    assertion_like_count = 0
    mock_bindings, patched_targets = collect_mock_support(node)

    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            assertion_like_count += 1
            continue
        if isinstance(child, (ast.With, ast.AsyncWith)) and with_uses_pytest_assertion_context(child):
            assertion_like_count += 1
            continue

        target_node: Optional[ast.AST] = None
        if isinstance(child, ast.Attribute) and child.attr in MOCK_ASSERTION_ATTRIBUTES:
            target_node = child.value
        elif (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in MOCK_ASSERTION_METHODS
        ):
            target_node = child.func.value

        if target_node is None:
            continue
        if supports_mock_assertion_target(target_node, mock_bindings, patched_targets):
            assertion_like_count += 1

    return assertion_like_count


__all__ = [
    "MOCK_ASSERTION_ATTRIBUTES",
    "MOCK_ASSERTION_METHODS",
    "assert_expects_false",
    "assert_expects_invalid_outcome",
    "assert_limits_batch_result",
    "assigned_name_for_call",
    "auto_fix_test_type_mismatches",
    "call_expects_invalid_outcome",
    "call_has_negative_expectation",
    "ast_contains_node",
    "behavior_contract_explicitly_limits_score_state_to_valid_requests",
    "parent_map",
    "batch_call_allows_partial_invalid_items",
    "bound_target_names",
    "call_argument_count",
    "call_argument_value",
    "analyze_typed_test_member_usage",
    "collect_local_bindings",
    "collect_local_name_bindings",
    "collect_module_defined_names",
    "collect_mock_support",
    "collect_parametrized_argument_names",
    "collect_test_local_types",
    "collect_undefined_local_names",
    "comparison_implies_partial_batch_result",
    "count_test_assertion_like_checks",
    "exact_len_assertion",
    "extract_literal_dict_keys",
    "extract_literal_field_values",
    "extract_literal_list_items",
    "extract_parametrize_argument_names",
    "extract_string_literals",
    "find_contract_overreach_signals",
    "find_unsupported_mock_assertions",
    "function_argument_names",
    "infer_argument_type",
    "infer_call_result_type",
    "infer_expression_type",
    "int_constant_value",
    "invalid_outcome_marker_matches",
    "invalid_outcome_subject_matches",
    "is_internal_score_state_target",
    "is_len_call",
    "is_mock_factory_call",
    "is_patch_call",
    "iter_relevant_test_body_nodes",
    "known_type_allows_member",
    "len_call_matches_batch_result",
    "loop_contains_non_batch_call",
    "payload_argument_for_validation",
    "patched_target_name_from_call",
    "resolve_bound_value",
    "name_suggests_validation_failure",
    "validate_batch_call",
    "visible_repeated_single_call_batch_sizes",
    "with_uses_pytest_assertion_context",
    "with_uses_pytest_raises",
    "supports_mock_assertion_target",
]
