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


def first_user_parameter(node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.arg | None:
    positional = [*node.args.posonlyargs, *node.args.args]
    if positional and positional[0].arg in {"self", "cls"}:
        positional = positional[1:]
    return positional[0] if positional else None


def parameter_is_iterated(node: ast.FunctionDef | ast.AsyncFunctionDef, parameter_name: str) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.For):
            continue
        iterator = child.iter
        if isinstance(iterator, ast.Name) and iterator.id == parameter_name:
            return True
    return False


def direct_return_expression(node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    for statement in node.body:
        if isinstance(statement, ast.Return) and statement.value is not None:
            return statement.value
    return None


def callable_parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    positional = [*node.args.posonlyargs, *node.args.args]
    if positional and positional[0].arg in {"self", "cls"}:
        positional = positional[1:]
    return [argument.arg for argument in positional]


def extract_sequence_input_rule(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    parameter = first_user_parameter(node)
    if parameter is None:
        return ""
    annotation = ast_name(parameter.annotation) if parameter.annotation is not None else ""
    if annotation_accepts_sequence_input(annotation):
        return f"{node.name} accepts sequence inputs via parameter `{parameter.arg}`"
    if parameter_is_iterated(node, parameter.arg):
        return f"{node.name} accepts sequence inputs via parameter `{parameter.arg}`"
    return ""


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


def comparison_required_field(node: ast.Compare) -> str:
    if not node.ops or not isinstance(node.left, ast.Constant) or not isinstance(node.left.value, str):
        return ""
    comparator = node.comparators[0] if node.comparators else None
    if not isinstance(comparator, (ast.Name, ast.Attribute, ast.Subscript)):
        return ""
    if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
        return ""
    return node.left.value


def extract_required_fields(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    literal_fields: list[str] = []
    for stmt in ast.walk(node):
        if not isinstance(stmt, ast.Assign):
            if not isinstance(stmt, ast.Compare):
                continue
            field_name = comparison_required_field(stmt)
            if field_name and field_name not in literal_fields:
                literal_fields.append(field_name)
            continue
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            continue
        if stmt.targets[0].id != "required_fields" or not isinstance(stmt.value, (ast.List, ast.Set, ast.Tuple)):
            continue
        fields: list[str] = []
        for element in stmt.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                fields.append(element.value)
        if fields:
            return fields
    return literal_fields


def extract_indirect_required_fields(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    validation_rules: Dict[str, list[str]],
) -> list[str]:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        called_name = call_expression_basename(child.func)
        if called_name in validation_rules:
            return list(validation_rules[called_name])
    return []


def field_selector_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def extract_lookup_field_rules(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, list[str]]:
    dict_key_sets: Dict[str, list[str]] = {}
    lookup_rules: Dict[str, list[str]] = {}

    for child in ast.walk(node):
        if isinstance(child, ast.Assign) and len(child.targets) == 1 and isinstance(child.targets[0], ast.Name):
            if not isinstance(child.value, ast.Dict):
                continue
            literal_keys = [
                key.value
                for key in child.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
            if literal_keys:
                dict_key_sets[child.targets[0].id] = literal_keys

    for child in ast.walk(node):
        if not isinstance(child, ast.Subscript) or not isinstance(child.value, ast.Name):
            continue
        allowed_values = dict_key_sets.get(child.value.id)
        if not allowed_values:
            continue
        selected_field_name = field_selector_name(child.slice)
        if not selected_field_name:
            continue
        lookup_rules[selected_field_name] = list(dict.fromkeys(allowed_values))

    return lookup_rules


__all__ = [
    "annotation_accepts_sequence_input",
    "callable_parameter_names",
    "comparison_required_field",
    "call_signature_details",
    "call_expression_basename",
    "dataclass_field_has_default",
    "dataclass_field_is_init_enabled",
    "direct_return_expression",
    "extract_indirect_required_fields",
    "extract_lookup_field_rules",
    "extract_required_fields",
    "extract_sequence_input_rule",
    "field_selector_name",
    "first_user_parameter",
    "has_dataclass_decorator",
    "method_binding_kind",
    "parameter_is_iterated",
    "self_assigned_attributes",
]
