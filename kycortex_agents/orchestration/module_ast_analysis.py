import ast
import copy
import re
from typing import Any, Dict

from kycortex_agents.orchestration.ast_tools import AstNameReplacer
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


def build_code_outline(raw_content: str) -> str:
    if not raw_content.strip():
        return ""
    pattern = re.compile(r"^(class\s+\w+.*|def\s+\w+.*|async\s+def\s+\w+.*)$")
    outline_lines = [line.strip() for line in raw_content.splitlines() if pattern.match(line.strip())]
    return "\n".join(outline_lines[:40])


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


def example_from_default(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, int):
            return str(max(value, 1)) if value >= 0 else str(value)
        if isinstance(value, float):
            return str(max(value, 1.0)) if value >= 0 else str(value)
        if isinstance(value, str):
            return f"'{value}'" if value else "'sample'"
        if value is None:
            return None
    if isinstance(node, ast.List):
        if not node.elts:
            return "['sample']"
        try:
            return ast.unparse(node)
        except Exception:
            return "['sample']"
    if isinstance(node, ast.Dict):
        if not node.keys:
            return "{'key': 'value'}"
        try:
            return ast.unparse(node)
        except Exception:
            return "{'key': 'value'}"
    if isinstance(node, ast.Set):
        return "{'sample'}"
    if isinstance(node, ast.Tuple):
        return "('sample',)"
    return None


def infer_dict_key_value_examples(tree: ast.AST) -> Dict[str, Dict[str, str]]:
    alias_map: Dict[str, str] = {}
    raw: Dict[str, Dict[str, str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
            if (
                isinstance(target, ast.Name)
                and isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
            ):
                alias_map[target.id] = value.attr

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            var_name = node.func.value.id
            key_name = node.args[0].value
            if len(node.args) >= 2:
                default_node = node.args[1]
                example = example_from_default(default_node)
                if example is not None:
                    raw.setdefault(var_name, {})[key_name] = example

    merged: Dict[str, Dict[str, str]] = {}
    for var_name, key_examples in raw.items():
        real_name = alias_map.get(var_name, var_name)
        if real_name not in merged:
            merged[real_name] = {}
        merged[real_name].update(key_examples)
    return merged


def dict_accessed_keys_from_tree(tree: ast.AST) -> Dict[str, list[str]]:
    keys_by_name: Dict[str, list[str]] = {}
    alias_map: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
            if (
                isinstance(target, ast.Name)
                and isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
            ):
                alias_map[target.id] = value.attr

        var_name = ""
        key_value = ""
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                var_name = node.value.id
                key_value = node.slice.value
        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.In):
            if (
                isinstance(node.left, ast.Constant)
                and isinstance(node.left.value, str)
                and len(node.comparators) == 1
                and isinstance(node.comparators[0], ast.Name)
            ):
                var_name = node.comparators[0].id
                key_value = node.left.value
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get" and isinstance(node.func.value, ast.Name):
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    var_name = node.func.value.id
                    key_value = node.args[0].value
        if var_name and key_value and key_value not in keys_by_name.get(var_name, []):
            keys_by_name.setdefault(var_name, []).append(key_value)

    merged: Dict[str, list[str]] = {}
    for var_name, keys in keys_by_name.items():
        real_name = alias_map.get(var_name, var_name)
        if real_name in merged:
            for key in keys:
                if key not in merged[real_name]:
                    merged[real_name].append(key)
        else:
            merged[real_name] = list(keys)
    return merged


def isinstance_subject_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.attr
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    ):
        return node.slice.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value
    return ""


def isinstance_type_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [ast_name(node)]
    if isinstance(node, ast.Tuple):
        names: list[str] = []
        for element in node.elts:
            if isinstance(element, ast.Name):
                names.append(element.id)
            elif isinstance(element, ast.Attribute):
                names.append(ast_name(element))
        return names
    return []


def collect_isinstance_calls(node: ast.AST, result: list[ast.Call]) -> None:
    if isinstance(node, ast.Call):
        func = node.func
        if (isinstance(func, ast.Name) and func.id == "isinstance") or (
            isinstance(func, ast.Attribute) and func.attr == "isinstance"
        ):
            result.append(node)
            return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        collect_isinstance_calls(node.operand, result)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            collect_isinstance_calls(value, result)


def extract_type_constraints(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, list[str]]:
    constraints: Dict[str, list[str]] = {}
    for child in ast.walk(node):
        if not isinstance(child, (ast.If, ast.Assert)):
            continue
        isinstance_calls: list[ast.Call] = []
        collect_isinstance_calls(child.test, isinstance_calls)
        for call in isinstance_calls:
            if len(call.args) < 2:
                continue
            field_name = isinstance_subject_name(call.args[0])
            if not field_name:
                continue
            type_names = isinstance_type_names(call.args[1])
            if not type_names:
                continue
            existing = constraints.get(field_name) or []
            for type_name in type_names:
                if type_name not in existing:
                    existing.append(type_name)
            constraints[field_name] = existing
    return constraints


def extract_valid_literal_examples(raw_content: str) -> Dict[str, str]:
    examples: Dict[str, str] = {}
    try:
        tree = ast.parse(raw_content)
    except SyntaxError:
        return examples
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        name_lower = target.id.lower()
        if not any(
            keyword in name_lower
            for keyword in ("default", "sample", "example", "valid", "template")
        ):
            continue
        if isinstance(node.value, (ast.Dict, ast.List)):
            try:
                examples[target.id] = ast.unparse(node.value)
            except Exception:
                pass
    return examples


def extract_batch_rule(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    validation_rules: Dict[str, list[str]],
) -> str:
    if "batch" not in node.name:
        return ""
    for child in ast.walk(node):
        if not isinstance(child, ast.For) or not isinstance(child.target, ast.Name):
            continue
        iter_var = child.target.id
        for nested in ast.walk(child):
            if not isinstance(nested, ast.Call):
                continue
            called_name = call_expression_basename(nested.func)
            if called_name != "intake_request":
                continue
            required_fields = validation_rules.get(called_name) or []
            if len(nested.args) < 2:
                continue
            payload_arg = nested.args[1]
            request_id_arg = nested.args[0]
            if isinstance(payload_arg, ast.Name) and payload_arg.id == iter_var:
                batch_fields = list(required_fields)
                if isinstance(request_id_arg, ast.Subscript) and isinstance(request_id_arg.slice, ast.Constant):
                    request_key = request_id_arg.slice.value
                    if isinstance(request_key, str):
                        batch_fields = [request_key, *batch_fields]
                if batch_fields:
                    return (
                        f"{node.name} expects each batch item to include: {', '.join(dict.fromkeys(batch_fields))}"
                    )
            if (
                isinstance(payload_arg, ast.Subscript)
                and isinstance(payload_arg.value, ast.Name)
                and payload_arg.value.id == iter_var
                and isinstance(payload_arg.slice, ast.Constant)
                and isinstance(payload_arg.slice.value, str)
            ):
                wrapper_key = payload_arg.slice.value
                batch_fields = list(required_fields)
                if isinstance(request_id_arg, ast.Subscript) and isinstance(request_id_arg.slice, ast.Constant):
                    request_key = request_id_arg.slice.value
                    if isinstance(request_key, str):
                        return (
                            f"{node.name} expects each batch item to include key `{request_key}` and nested `{wrapper_key}` fields: {', '.join(batch_fields)}"
                        )
                if batch_fields:
                    return (
                        f"{node.name} expects nested `{wrapper_key}` fields: {', '.join(batch_fields)}"
                    )
    return ""


def extract_class_definition_style(node: ast.ClassDef) -> str:
    class_name = node.name
    for decorator in node.decorator_list:
        decorator_name = call_expression_basename(decorator.func) if isinstance(decorator, ast.Call) else call_expression_basename(decorator)
        if decorator_name == "dataclass":
            return f"{class_name} is defined as a @dataclass"
    for base in node.bases:
        base_name = call_expression_basename(base)
        if base_name == "BaseModel":
            return f"{class_name} is defined as a pydantic BaseModel"
        if base_name in {"TypedDict", "NamedTuple"}:
            return f"{class_name} is defined as a {base_name}"
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == "__init__":
            return f"{class_name} uses manual __init__"
    return ""


def extract_return_type_annotation(
    class_name: str | None,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str:
    if node.name.startswith("_") or node.returns is None:
        return ""
    try:
        annotation = ast.unparse(node.returns)
    except Exception:
        return ""
    if not annotation or annotation == "None":
        return ""
    qualified_name = f"{class_name}.{node.name}" if class_name else node.name
    return f"{qualified_name} returns {annotation}"


def extract_constructor_storage_rule(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    first_parameter = first_user_parameter(node)
    if first_parameter is None:
        return ""

    source_name = first_parameter.arg
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        constructor_name = ast_name(child.func)
        if not constructor_name:
            continue
        for keyword in child.keywords:
            if keyword.arg != "data":
                continue
            if isinstance(keyword.value, ast.Name) and keyword.value.id == source_name:
                return f"{node.name} stores full {source_name} in returned {constructor_name}.data"
    return ""


def function_returns_score_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and isinstance(child.value, ast.Name) and child.value.id == "score":
            return True
        if not isinstance(child, ast.Call):
            continue
        if any(
            keyword.arg == "score" and isinstance(keyword.value, ast.Name) and keyword.value.id == "score"
            for keyword in child.keywords
        ):
            return True
        if child.args and isinstance(child.args[0], ast.Name) and child.args[0].id == "score":
            return True
    return False


def expand_local_name_aliases(
    expression: ast.expr,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.expr:
    replacements: dict[str, ast.expr] = {}
    for statement in node.body:
        if isinstance(statement, ast.Return):
            break
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            continue
        expanded_value = AstNameReplacer(replacements).visit(copy.deepcopy(statement.value))
        if isinstance(expanded_value, ast.expr):
            replacements[target.id] = ast.fix_missing_locations(expanded_value)

    if not replacements:
        return expression

    expanded_expression = AstNameReplacer(replacements).visit(copy.deepcopy(expression))
    if isinstance(expanded_expression, ast.expr):
        return ast.fix_missing_locations(expanded_expression)
    return expression


def inline_score_helper_expression(
    expression: ast.expr,
    function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> ast.expr:
    if not isinstance(expression, ast.Call):
        return expression

    helper_name = call_expression_basename(expression.func)
    if not helper_name:
        return expression
    helper_node = function_map.get(helper_name)
    if helper_node is None:
        return expression

    helper_return_expression = direct_return_expression(helper_node)
    if helper_return_expression is None:
        return expression
    helper_return_expression = expand_local_name_aliases(helper_return_expression, helper_node)

    parameter_names = callable_parameter_names(helper_node)
    replacements: dict[str, ast.expr] = {}
    for parameter_name, argument in zip(parameter_names, expression.args):
        replacements[parameter_name] = argument
    for keyword in expression.keywords:
        if keyword.arg is None or keyword.arg not in parameter_names:
            continue
        replacements[keyword.arg] = keyword.value

    if not replacements:
        return expression

    replacer = AstNameReplacer(replacements)
    inlined_expression = replacer.visit(copy.deepcopy(helper_return_expression))
    if isinstance(inlined_expression, ast.expr):
        return ast.fix_missing_locations(inlined_expression)
    return expression


def render_score_expression(
    expression: ast.expr,
    function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> str:
    rendered_expression = inline_score_helper_expression(expression, function_map)
    try:
        return ast.unparse(rendered_expression).strip()
    except Exception:
        return ast_name(rendered_expression)


def extract_score_derivation_rule(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    function_map: Dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> str:
    score_expression_node: ast.expr | None = None

    for child in ast.walk(node):
        if not isinstance(child, ast.Assign) or len(child.targets) != 1:
            continue
        target = child.targets[0]
        if isinstance(target, ast.Name) and target.id == "score":
            score_expression_node = child.value
            break

    if score_expression_node is not None:
        if not function_returns_score_value(node):
            return ""
        score_expression = render_score_expression(
            expand_local_name_aliases(score_expression_node, node),
            function_map,
        )
        if not score_expression:
            return ""
        return f"{node.name} derives score from {score_expression}"

    if "score" not in node.name.lower():
        return ""

    return_expression = direct_return_expression(node)
    if return_expression is None:
        return ""
    score_expression = render_score_expression(
        expand_local_name_aliases(return_expression, node),
        function_map,
    )
    if not score_expression:
        return ""
    return f"{node.name} derives score from {score_expression}"


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
    "build_code_outline",
    "callable_parameter_names",
    "comparison_required_field",
    "call_signature_details",
    "call_expression_basename",
    "dataclass_field_has_default",
    "dataclass_field_is_init_enabled",
    "dict_accessed_keys_from_tree",
    "direct_return_expression",
    "example_from_default",
    "collect_isinstance_calls",
    "extract_class_definition_style",
    "extract_constructor_storage_rule",
    "extract_batch_rule",
    "extract_indirect_required_fields",
    "extract_lookup_field_rules",
    "extract_required_fields",
    "extract_score_derivation_rule",
    "extract_return_type_annotation",
    "extract_sequence_input_rule",
    "extract_type_constraints",
    "extract_valid_literal_examples",
    "expand_local_name_aliases",
    "field_selector_name",
    "first_user_parameter",
    "function_returns_score_value",
    "has_dataclass_decorator",
    "infer_dict_key_value_examples",
    "inline_score_helper_expression",
    "isinstance_subject_name",
    "isinstance_type_names",
    "method_binding_kind",
    "parameter_is_iterated",
    "render_score_expression",
    "self_assigned_attributes",
]
