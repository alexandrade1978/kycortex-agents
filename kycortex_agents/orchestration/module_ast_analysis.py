import ast
from typing import Any, Dict

from kycortex_agents.orchestration.ast_tools import ast_name


def annotation_accepts_sequence_input(annotation: str) -> bool:
    normalized = annotation.replace(" ", "").lower()
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "list[",
            "typing.list",
            "sequence[",
            "typing.sequence",
            "iterable[",
            "typing.iterable",
            "tuple[",
            "set[",
            "collections.abc.sequence",
            "collections.abc.iterable",
        )
    )


def call_signature_details(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    skip_first_param: bool = False,
) -> Dict[str, Any]:
    positional_args = [*node.args.posonlyargs, *node.args.args]
    if skip_first_param and positional_args:
        positional_args = positional_args[1:]
    keyword_only_args = list(node.args.kwonlyargs)
    positional_params = [arg.arg for arg in positional_args]
    keyword_only_params = [arg.arg for arg in keyword_only_args]
    params = [*positional_params, *keyword_only_params]
    param_annotations = [
        ast_name(arg.annotation) if arg.annotation is not None else None
        for arg in [*positional_args, *keyword_only_args]
    ]
    optional_positional = len(node.args.defaults)
    optional_kwonly = sum(default is not None for default in node.args.kw_defaults)
    max_args = len(params)
    min_args = max(0, max_args - optional_positional - optional_kwonly)
    accepts_sequence_input = bool(param_annotations) and annotation_accepts_sequence_input(param_annotations[0] or "")
    return {
        "params": params,
        "param_annotations": param_annotations,
        "min_args": min_args,
        "max_args": max_args,
        "accepts_sequence_input": accepts_sequence_input,
        "return_annotation": ast_name(node.returns) if node.returns is not None else None,
    }


def method_binding_kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        decorator_name = ast_name(target).split(".")[-1]
        if decorator_name == "staticmethod":
            return "static"
        if decorator_name == "classmethod":
            return "class"
    return "instance"


def self_assigned_attributes(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    attributes: list[str] = []
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        if isinstance(child, ast.Assign):
            targets.extend(child.targets)
        elif isinstance(child, ast.AnnAssign):
            targets.append(child.target)
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                attributes.append(target.attr)
    return attributes


def has_dataclass_decorator(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name) and target.id == "dataclass":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "dataclass":
            return True
    return False


def call_expression_basename(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def dataclass_field_has_default(value: ast.expr | None) -> bool:
    if value is None:
        return False
    if not isinstance(value, ast.Call) or call_expression_basename(value.func) != "field":
        return True
    if value.args:
        return True
    return any(keyword.arg in {"default", "default_factory"} for keyword in value.keywords)


def dataclass_field_is_init_enabled(value: ast.expr | None) -> bool:
    if not isinstance(value, ast.Call) or call_expression_basename(value.func) != "field":
        return True
    for keyword in value.keywords:
        if keyword.arg != "init":
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, bool):
            return keyword.value.value
        return True
    return True


__all__ = [
    "annotation_accepts_sequence_input",
    "call_signature_details",
    "call_expression_basename",
    "dataclass_field_has_default",
    "dataclass_field_is_init_enabled",
    "has_dataclass_decorator",
    "method_binding_kind",
    "self_assigned_attributes",
]
