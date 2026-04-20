import ast
import copy
import re
import sys
from typing import Any, Dict

from kycortex_agents.orchestration.ast_tools import AstNameReplacer
from kycortex_agents.orchestration.ast_tools import ast_name
from kycortex_agents.orchestration.test_ast_analysis import bound_target_names


_STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", set()))


def is_probable_third_party_import(module_name: str) -> bool:
    normalized_name = module_name.strip()
    if not normalized_name:
        return False
    if normalized_name == "__future__":
        return False
    if normalized_name in _STDLIB_MODULES:
        return False
    return True


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


def analyze_python_module(raw_content: str) -> Dict[str, Any]:
    analysis: Dict[str, Any] = {
        "syntax_ok": True,
        "syntax_error": None,
        "functions": [],
        "classes": {},
        "imports": [],
        "third_party_imports": [],
        "invalid_dataclass_field_usages": [],
        "module_variables": [],
        "symbols": [],
        "has_main_guard": '__name__ == "__main__"' in raw_content or "__name__ == '__main__'" in raw_content,
    }
    if not raw_content.strip():
        return analysis
    try:
        tree = ast.parse(raw_content)
    except SyntaxError as exc:
        analysis["syntax_ok"] = False
        analysis["syntax_error"] = f"{exc.msg} at line {exc.lineno}"
        return analysis

    functions: list[Dict[str, Any]] = []
    classes: Dict[str, Dict[str, Any]] = {}
    import_roots: set[str] = set()
    invalid_dataclass_field_usages: list[str] = []
    module_variables: set[str] = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            signature = call_signature_details(node)
            functions.append({
                "name": node.name,
                "params": signature["params"],
                "param_annotations": signature["param_annotations"],
                "min_args": signature["min_args"],
                "max_args": signature["max_args"],
                "return_annotation": signature["return_annotation"],
                "signature": f"{node.name}({', '.join(signature['params'])})",
                "accepts_sequence_input": signature["accepts_sequence_input"],
                "async": isinstance(node, ast.AsyncFunctionDef),
            })
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in bound_target_names(target):
                    if not name.startswith("_"):
                        module_variables.add(name)
            continue
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                for name in bound_target_names(node.target):
                    if not name.startswith("_"):
                        module_variables.add(name)
            continue
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
            continue
        if not isinstance(node, ast.ClassDef):
            continue

        field_names: list[str] = []
        dataclass_init_params: list[str] = []
        dataclass_required_params: list[str] = []
        class_attributes: list[str] = []
        init_params: list[str] = []
        constructor_min_args: int | None = None
        constructor_max_args: int | None = None
        methods: list[str] = []
        method_signatures: Dict[str, Dict[str, Any]] = {}
        bases = [ast_name(base) for base in node.bases]
        is_enum = any(base.endswith("Enum") for base in bases)
        is_dataclass = has_dataclass_decorator(node)

        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                field_name = stmt.target.id
                field_names.append(field_name)
                if (
                    not is_dataclass
                    and isinstance(stmt.value, ast.Call)
                    and call_expression_basename(stmt.value.func) == "field"
                ):
                    invalid_dataclass_field_usages.append(
                        f"{node.name}.{field_name} uses field(...) on a non-dataclass class"
                    )
                if is_dataclass:
                    has_default = dataclass_field_has_default(stmt.value)
                    if dataclass_field_is_init_enabled(stmt.value):
                        dataclass_init_params.append(field_name)
                        if not has_default:
                            dataclass_required_params.append(field_name)
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        class_attributes.append(target.id)
                        if (
                            not is_dataclass
                            and isinstance(stmt.value, ast.Call)
                            and call_expression_basename(stmt.value.func) == "field"
                        ):
                            invalid_dataclass_field_usages.append(
                                f"{node.name}.{target.id} uses field(...) on a non-dataclass class"
                            )
            elif isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
                signature = call_signature_details(stmt, skip_first_param=True)
                init_params = signature["params"]
                constructor_min_args = signature["min_args"]
                constructor_max_args = signature["max_args"]
                class_attributes.extend(self_assigned_attributes(stmt))
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and not stmt.name.startswith("_"):
                binding_kind = method_binding_kind(stmt)
                signature = call_signature_details(
                    stmt,
                    skip_first_param=binding_kind != "static",
                )
                if binding_kind == "static":
                    params = list(signature["params"])
                elif binding_kind == "class":
                    params = ["cls", *signature["params"]]
                else:
                    params = ["self", *signature["params"]]
                methods.append(f"{stmt.name}({', '.join(params)})")
                method_signatures[stmt.name] = signature

        if init_params:
            constructor_params = init_params
        elif is_dataclass:
            constructor_params = dataclass_init_params
        else:
            constructor_params = []
        if constructor_min_args is None and constructor_max_args is None:
            if is_dataclass:
                constructor_min_args = len(dataclass_required_params)
                constructor_max_args = len(dataclass_init_params)
            else:
                constructor_min_args = 0
                constructor_max_args = 0
        classes[node.name] = {
            "name": node.name,
            "bases": bases,
            "is_enum": is_enum,
            "fields": field_names,
            "attributes": sorted(set(class_attributes)),
            "constructor_params": constructor_params,
            "constructor_min_args": constructor_min_args if constructor_min_args is not None else len(constructor_params),
            "constructor_max_args": constructor_max_args if constructor_max_args is not None else len(constructor_params),
            "methods": methods,
            "method_signatures": method_signatures,
        }

    analysis["functions"] = functions
    analysis["classes"] = classes
    analysis["imports"] = sorted(import_roots)
    analysis["third_party_imports"] = [
        module_name for module_name in sorted(import_roots) if is_probable_third_party_import(module_name)
    ]
    analysis["invalid_dataclass_field_usages"] = sorted(dict.fromkeys(invalid_dataclass_field_usages))
    analysis["module_variables"] = sorted(module_variables)
    analysis["symbols"] = sorted([item["name"] for item in functions] + list(classes.keys()))
    return analysis


def entrypoint_function_names(code_analysis: Dict[str, Any]) -> set[str]:
    function_names = {item["name"] for item in code_analysis.get("functions") or []}
    return {
        name
        for name in function_names
        if name == "main" or name.startswith("cli_") or name.endswith("_cli") or name.endswith("_demo")
    }


def entrypoint_class_names(code_analysis: Dict[str, Any]) -> set[str]:
    class_names = set((code_analysis.get("classes") or {}).keys())
    return {
        name
        for name in class_names
        if name.lower().endswith("cli") or name.lower().endswith("_cli") or name.lower().endswith("demo")
    }


def entrypoint_symbol_names(code_analysis: Dict[str, Any]) -> set[str]:
    return entrypoint_function_names(code_analysis) | entrypoint_class_names(code_analysis)


def preferred_test_class_names(code_analysis: Dict[str, Any]) -> list[str]:
    entrypoints = entrypoint_symbol_names(code_analysis)
    workflow_method_prefixes = (
        "process_",
        "validate_",
        "intake_",
        "handle_",
        "submit_",
        "batch_",
        "export_",
    )
    preferred: list[str] = []
    for class_name, class_info in sorted((code_analysis.get("classes") or {}).items()):
        if class_name in entrypoints:
            continue
        method_names = list((class_info.get("method_signatures") or {}).keys())
        if any(method_name.startswith(workflow_method_prefixes) for method_name in method_names):
            preferred.append(class_name)
    return preferred


def constructor_param_matches_class(param_name: str, class_name: str) -> bool:
    normalized_param = param_name.strip().lower()
    if not normalized_param:
        return False

    snake_name = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
    candidate_names = {snake_name}
    parts = snake_name.split("_")
    if len(parts) > 2:
        for start in range(1, len(parts) - 1):
            candidate_names.add("_".join(parts[start:]))

    if normalized_param in candidate_names:
        return True

    suffix = snake_name.split("_")[-1]
    return suffix in {"logger", "repository", "service"} and normalized_param == suffix


def helper_classes_to_avoid(
    code_analysis: Dict[str, Any],
    preferred_classes: list[str] | None = None,
) -> list[str]:
    preferred = set(preferred_classes or preferred_test_class_names(code_analysis))
    if not preferred:
        return []
    class_map = code_analysis.get("classes") or {}
    entrypoints = entrypoint_symbol_names(code_analysis)
    helper_suffixes = ("service", "repository", "logger")
    required_constructor_helpers: set[str] = set()
    for preferred_name in preferred:
        class_info = class_map.get(preferred_name) or {}
        constructor_params = [
            param_name
            for param_name in (class_info.get("constructor_params") or [])
            if isinstance(param_name, str)
        ]
        for helper_name in class_map.keys():
            if helper_name in preferred or helper_name in entrypoints:
                continue
            if not helper_name.lower().endswith(helper_suffixes):
                continue
            if any(
                constructor_param_matches_class(param_name, helper_name)
                for param_name in constructor_params
            ):
                required_constructor_helpers.add(helper_name)
    helper_names: list[str] = []
    for class_name in sorted(class_map.keys()):
        if class_name in entrypoints or class_name in preferred or class_name in required_constructor_helpers:
            continue
        if class_name.lower().endswith(helper_suffixes):
            helper_names.append(class_name)
    return helper_names


def exposed_test_class_names(
    code_analysis: Dict[str, Any],
    preferred_classes: list[str] | None = None,
) -> list[str]:
    class_map = code_analysis.get("classes") or {}
    entrypoints = entrypoint_symbol_names(code_analysis)
    preferred = preferred_classes or preferred_test_class_names(code_analysis)
    helpers_to_avoid = set(helper_classes_to_avoid(code_analysis, preferred))
    return sorted(
        class_name
        for class_name in class_map.keys()
        if class_name not in entrypoints and class_name not in helpers_to_avoid
    )


def build_code_exact_test_contract(code_analysis: Dict[str, Any]) -> str:
    if not code_analysis.get("syntax_ok", True):
        return "Exact test contract unavailable because module syntax is invalid."

    entrypoints = entrypoint_symbol_names(code_analysis)
    functions = code_analysis.get("functions") or []
    classes = code_analysis.get("classes") or {}
    preferred_classes = preferred_test_class_names(code_analysis)
    exposed_class_names = exposed_test_class_names(code_analysis, preferred_classes)
    allowed_imports = sorted(
        [item["name"] for item in functions if item["name"] not in entrypoints]
        + exposed_class_names
    )
    exact_method_refs: list[str] = []
    constructor_refs: list[str] = []

    for class_name in exposed_class_names:
        class_info = classes[class_name]
        constructor_params = class_info.get("constructor_params") or []
        if constructor_params:
            constructor_refs.append(f"{class_name}({', '.join(constructor_params)})")
        for method_name in class_info.get("methods") or []:
            if method_name.startswith("_"):
                continue
            exact_method_refs.append(f"{class_name}.{method_name}")

    callable_refs = [
        item["signature"]
        for item in functions
        if item["name"] not in entrypoints
    ]

    lines = ["Exact test contract:"]
    lines.append(f"- Allowed production imports: {', '.join(allowed_imports or ['none'])}")
    lines.append(f"- Preferred service or workflow facades: {', '.join(preferred_classes or ['none'])}")
    lines.append(f"- Exact public callables: {', '.join(callable_refs or ['none'])}")
    lines.append(f"- Exact public class methods: {', '.join(exact_method_refs or ['none'])}")
    lines.append(f"- Exact constructor fields: {', '.join(constructor_refs or ['none'])}")
    lines.append(
        "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
    )
    return "\n".join(lines)


def build_code_test_targets(code_analysis: Dict[str, Any]) -> str:
    if not code_analysis.get("syntax_ok", True):
        return "Test targets unavailable because module syntax is invalid."

    entrypoints = entrypoint_symbol_names(code_analysis)
    preferred_classes = preferred_test_class_names(code_analysis)
    helpers_to_avoid = helper_classes_to_avoid(code_analysis, preferred_classes)
    batch_capable_functions = [
        item["signature"]
        for item in code_analysis.get("functions") or []
        if item["name"] not in entrypoints and item.get("accepts_sequence_input")
    ]
    scalar_functions = [
        item["signature"]
        for item in code_analysis.get("functions") or []
        if item["name"] not in entrypoints and not item.get("accepts_sequence_input")
    ]
    testable_functions = [
        item["signature"]
        for item in code_analysis.get("functions") or []
        if item["name"] not in entrypoints
    ]
    classes = exposed_test_class_names(code_analysis, preferred_classes)
    lines = ["Test targets:"]
    lines.append(f"- Functions to test: {', '.join(testable_functions or ['none'])}")
    lines.append(f"- Batch-capable functions: {', '.join(batch_capable_functions or ['none'])}")
    lines.append(f"- Scalar-only functions: {', '.join(scalar_functions or ['none'])}")
    lines.append(f"- Classes to test: {', '.join(classes or ['none'])}")
    lines.append(f"- Preferred workflow classes: {', '.join(preferred_classes or ['none'])}")
    lines.append(
        f"- Helper classes to avoid in compact workflow tests: {', '.join(helpers_to_avoid or ['none'])}"
    )
    lines.append(f"- Entry points to avoid in tests: {', '.join(sorted(entrypoints) or ['none'])}")
    return "\n".join(lines)


def build_module_run_command(module_filename: str, code_analysis: Dict[str, Any]) -> str:
    if code_analysis.get("has_main_guard"):
        return f"python {module_filename}"
    return ""


def parse_behavior_contract(
    contract: str,
) -> tuple[Dict[str, list[str]], Dict[str, Dict[str, list[str]]], Dict[str, Dict[str, Any]], set[str], Dict[str, Dict[str, list[str]]]]:
    validation_rules: Dict[str, list[str]] = {}
    field_value_rules: Dict[str, Dict[str, list[str]]] = {}
    type_constraint_rules: Dict[str, Dict[str, list[str]]] = {}
    batch_rules: Dict[str, Dict[str, Any]] = {}
    sequence_input_functions: set[str] = set()
    if not contract.strip():
        return validation_rules, field_value_rules, batch_rules, sequence_input_functions, type_constraint_rules

    for raw_line in contract.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        validation_match = re.match(r"-\s+(\w+) requires fields: (.+)$", line)
        if validation_match:
            function_name = validation_match.group(1)
            fields = [field.strip() for field in validation_match.group(2).split(",") if field.strip()]
            if fields:
                validation_rules[function_name] = fields
            continue

        type_constraint_match = re.match(r"-\s+(\w+) requires parameter `([^`]+)` to be of type: (.+)$", line)
        if type_constraint_match:
            function_name = type_constraint_match.group(1)
            field_name = type_constraint_match.group(2)
            raw_types = re.sub(r"\s*\(keys used:[^)]*\)", "", type_constraint_match.group(3))
            types = [t.strip() for t in raw_types.split(",") if t.strip()]
            if types:
                type_constraint_rules.setdefault(function_name, {})[field_name] = types
            continue

        field_value_match = re.match(r"-\s+(\w+) expects field `([^`]+)` to be one of: (.+)$", line)
        if field_value_match:
            function_name = field_value_match.group(1)
            field_name = field_value_match.group(2)
            values = [value.strip() for value in field_value_match.group(3).split(",") if value.strip()]
            if values:
                field_value_rules.setdefault(function_name, {})[field_name] = values
            continue

        sequence_input_match = re.match(r"-\s+(\w+) accepts sequence inputs via parameter `([^`]+)`$", line)
        if sequence_input_match:
            sequence_input_functions.add(sequence_input_match.group(1))
            continue

        nested_match = re.match(
            r"-\s+(\w+) expects each batch item to include key `([^`]+)` and nested `([^`]+)` fields: (.+)$",
            line,
        )
        if nested_match:
            batch_rules[nested_match.group(1)] = {
                "request_key": nested_match.group(2),
                "wrapper_key": nested_match.group(3),
                "fields": [field.strip() for field in nested_match.group(4).split(",") if field.strip()],
            }
            continue

        direct_match = re.match(r"-\s+(\w+) expects each batch item to include: (.+)$", line)
        if direct_match:
            batch_rules[direct_match.group(1)] = {
                "request_key": None,
                "wrapper_key": None,
                "fields": [field.strip() for field in direct_match.group(2).split(",") if field.strip()],
            }
            continue

        wrapper_match = re.match(r"-\s+(\w+) expects nested `([^`]+)` fields: (.+)$", line)
        if wrapper_match:  # pragma: no branch
            batch_rules[wrapper_match.group(1)] = {
                "request_key": None,
                "wrapper_key": wrapper_match.group(2),
                "fields": [field.strip() for field in wrapper_match.group(3).split(",") if field.strip()],
            }

    return validation_rules, field_value_rules, batch_rules, sequence_input_functions, type_constraint_rules


def build_code_public_api(code_analysis: Dict[str, Any]) -> str:
    if not code_analysis.get("syntax_ok", True):
        return f"Module syntax error: {code_analysis.get('syntax_error') or 'unknown syntax error'}"

    lines: list[str] = []
    functions = code_analysis.get("functions") or []
    classes = code_analysis.get("classes") or {}

    if functions:
        lines.append("Functions:")
        for function in functions:
            lines.append(f"- {function['signature']}")
    else:
        lines.append("Functions:\n- none")

    if classes:
        lines.append("Classes:")
        for class_name in sorted(classes):
            class_info = classes[class_name]
            if class_info.get("is_enum"):
                members = ", ".join(class_info.get("attributes") or []) or "none"
                lines.append(f"- {class_name} enum members: {members}")
                continue
            constructor = ", ".join(class_info.get("constructor_params") or [])
            class_attrs = ", ".join(class_info.get("attributes") or class_info.get("fields") or [])
            methods = ", ".join(class_info.get("methods") or [])
            suffix = f"({constructor})" if constructor else "()"
            if class_attrs:
                lines.append(f"- {class_name}{suffix}; class attributes/fields: {class_attrs}")
            else:
                lines.append(f"- {class_name}{suffix}")
            if constructor:
                lines.append(
                    f"  tests must instantiate with all listed constructor fields explicitly: {constructor}"
                )
            if methods:
                lines.append(f"  methods: {methods}")
    else:
        lines.append("Classes:\n- none")

    lines.append(
        f"Entrypoint: {'python ' + 'MODULE_FILE' if code_analysis.get('has_main_guard') else 'no __main__ entrypoint detected'}"
    )
    return "\n".join(lines)


def build_code_behavior_contract(raw_content: str) -> str:
    if not raw_content.strip():
        return ""
    try:
        tree = ast.parse(raw_content)
    except SyntaxError:
        return ""

    validation_rules: dict[str, list[str]] = {}
    field_value_rules: dict[str, Dict[str, list[str]]] = {}
    type_constraints: dict[str, Dict[str, list[str]]] = {}
    batch_rules: list[str] = []
    constructor_storage_rules: list[str] = []
    score_derivation_rules: list[str] = []
    sequence_input_rules: list[str] = []
    function_map: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            function_nodes = [stmt for stmt in node.body if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_nodes = [node]
        else:
            continue

        for function_node in function_nodes:
            function_map[function_node.name] = function_node
            required_fields = extract_required_fields(function_node)
            if required_fields:
                validation_rules[function_node.name] = required_fields

    for function_name, function_node in function_map.items():
        if function_name in validation_rules:
            continue
        propagated_fields = extract_indirect_required_fields(function_node, validation_rules)
        if propagated_fields:
            validation_rules[function_name] = propagated_fields

    for function_name, function_node in function_map.items():
        lookup_rules = extract_lookup_field_rules(function_node)
        if lookup_rules:
            field_value_rules[function_name] = lookup_rules

    for function_name, function_node in function_map.items():
        constraints = extract_type_constraints(function_node)
        if constraints:
            type_constraints[function_name] = constraints

    for function_node in function_map.values():
        batch_rule = extract_batch_rule(function_node, validation_rules)
        if batch_rule:
            batch_rules.append(batch_rule)

    for function_node in function_map.values():
        constructor_storage_rule = extract_constructor_storage_rule(function_node)
        if constructor_storage_rule:
            constructor_storage_rules.append(constructor_storage_rule)

    for function_node in function_map.values():
        score_derivation_rule = extract_score_derivation_rule(function_node, function_map)
        if score_derivation_rule:
            score_derivation_rules.append(score_derivation_rule)

    for function_node in function_map.values():
        sequence_rule = extract_sequence_input_rule(function_node)
        if sequence_rule:
            sequence_input_rules.append(sequence_rule)

    literal_examples = extract_valid_literal_examples(raw_content)

    class_definition_styles: list[str] = []
    return_type_annotations: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            style = extract_class_definition_style(node)
            if style:
                class_definition_styles.append(style)
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    annotation = extract_return_type_annotation(node.name, stmt)
                    if annotation:
                        return_type_annotations.append(annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotation = extract_return_type_annotation(None, node)
            if annotation:
                return_type_annotations.append(annotation)

    if not (
        validation_rules
        or field_value_rules
        or type_constraints
        or batch_rules
        or constructor_storage_rules
        or score_derivation_rules
        or sequence_input_rules
        or literal_examples
        or class_definition_styles
        or return_type_annotations
    ):
        return ""

    lines = ["Behavior contract:"]
    for function_name in sorted(validation_rules):
        lines.append(
            f"- {function_name} requires fields: {', '.join(validation_rules[function_name])}"
        )
    dict_accessed_keys = dict_accessed_keys_from_tree(tree) if type_constraints else {}
    dict_key_examples = infer_dict_key_value_examples(tree) if type_constraints else {}
    for function_name in sorted(type_constraints):
        for field_name in sorted(type_constraints[function_name]):
            type_list = ", ".join(type_constraints[function_name][field_name])
            keys_hint = ""
            dict_example = ""
            if "dict" in type_constraints[function_name][field_name]:
                keys = dict_accessed_keys.get(field_name)
                if keys:
                    sorted_keys = sorted(keys)
                    keys_hint = f" (keys used: {', '.join(sorted_keys)})"
                    inferred = dict_key_examples.get(field_name, {})
                    example_pairs = ", ".join(
                        f"'{k}': {inferred.get(k, repr('value'))}"
                        for k in sorted_keys
                    )
                    if example_pairs:
                        dict_example = (
                            f"- EXAMPLE: {field_name}={{{example_pairs}}} "
                            f"— NEVER pass a plain string for `{field_name}`"
                        )
            lines.append(
                f"- {function_name} requires parameter `{field_name}` to be of type: {type_list}{keys_hint}"
            )
            if dict_example:
                lines.append(dict_example)
    for function_name in sorted(field_value_rules):
        for field_name in sorted(field_value_rules[function_name]):
            lines.append(
                f"- {function_name} expects field `{field_name}` to be one of: {', '.join(field_value_rules[function_name][field_name])}"
            )
    for rule in sorted(dict.fromkeys(constructor_storage_rules)):
        lines.append(f"- {rule}")
    for rule in sorted(dict.fromkeys(score_derivation_rules)):
        lines.append(f"- {rule}")
    for rule in sorted(sequence_input_rules):
        lines.append(f"- {rule}")
    for rule in batch_rules:
        lines.append(f"- {rule}")
    for style in class_definition_styles:
        lines.append(f"- {style}")
    for annotation in return_type_annotations:
        lines.append(f"- {annotation}")
    if literal_examples:
        lines.append("")
        lines.append("Fixture example patterns:")
        for var_name, example_literal in sorted(literal_examples.items()):
            lines.append(f"- {var_name} = {example_literal}")
    return "\n".join(lines)


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
