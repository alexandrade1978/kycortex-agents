"""Deterministic repair-analysis helpers used by the Orchestrator facade."""

from __future__ import annotations

import ast
import re
from typing import Optional

from kycortex_agents.orchestration.artifacts import failed_artifact_content
from kycortex_agents.types import ArtifactType, FailureCategory


def artifact_type_for_failure_category(failure_category: str) -> ArtifactType | None:
	if failure_category == FailureCategory.CODE_VALIDATION.value:
		return ArtifactType.CODE
	if failure_category == FailureCategory.TEST_VALIDATION.value:
		return ArtifactType.TEST
	if failure_category == FailureCategory.DEPENDENCY_VALIDATION.value:
		return ArtifactType.CONFIG
	return None


def failed_artifact_content_for_category(
	output: object,
	output_payload: object,
	failure_category: str,
) -> str:
	artifact_type = artifact_type_for_failure_category(failure_category)
	return failed_artifact_content(output, output_payload, artifact_type)


def first_non_import_line_with_name(content: object, symbol_name: str) -> str:
	if not isinstance(content, str) or not content.strip() or not symbol_name:
		return ""
	symbol_pattern = re.compile(rf"\b{re.escape(symbol_name)}\b")
	for line in content.splitlines():
		stripped = line.strip()
		if not stripped or stripped.startswith("#"):
			continue
		if stripped.startswith("import ") or stripped.startswith("from "):
			continue
		if symbol_pattern.search(stripped):
			return stripped
	return ""


def missing_import_nameerror_details(
	validation_summary: object,
	failed_artifact_content: object = "",
) -> tuple[str, str] | None:
	if not isinstance(validation_summary, str) or not validation_summary.strip():
		return None

	summary_lower = validation_summary.lower()
	if not any(
		marker in summary_lower
		for marker in ("module import failed", "module import: fail", "import summary:")
	):
		return None

	match = re.search(
		r"NameError:\s*name ['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]? is not defined",
		validation_summary,
	)
	if match is None:
		return None

	missing_name = match.group(1)
	if missing_name in {"field", "datetime", "date", "timedelta", "timezone"}:
		return None

	broken_line = first_non_import_line_with_name(failed_artifact_content, missing_name)
	return missing_name, broken_line


def render_name_list(names: list[str]) -> str:
	cleaned = [name for name in names if isinstance(name, str) and name]
	if not cleaned:
		return ""
	if len(cleaned) == 1:
		return cleaned[0]
	if len(cleaned) == 2:
		return f"{cleaned[0]} and {cleaned[1]}"
	return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def missing_required_constructor_details(
	validation_summary: object,
) -> Optional[tuple[str, list[str]]]:
	if not isinstance(validation_summary, str) or not validation_summary.strip():
		return None

	match = re.search(
		r"TypeError:\s+([A-Za-z_][A-Za-z0-9_]*)\.__init__\(\).*?missing\s+\d+\s+required positional arguments?:\s*([^\n;|]+)",
		validation_summary,
		re.IGNORECASE,
	)
	if match is None:
		return None

	missing_fields = list(dict.fromkeys(re.findall(r"'([^']+)'", match.group(2))))
	if not missing_fields:
		return None
	return match.group(1), missing_fields


def required_field_list_from_failed_artifact(
	failed_artifact_content: object,
) -> list[str]:
	if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
		return []

	try:
		tree = ast.parse(failed_artifact_content)
	except SyntaxError:
		return []

	for node in ast.walk(tree):
		target_names: list[str] = []
		value_node: ast.AST | None = None
		if isinstance(node, ast.Assign):
			target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
			value_node = node.value
		elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
			target_names = [node.target.id]
			value_node = node.value
		if not any(name in {"required_fields", "required_keys"} for name in target_names):
			continue
		if value_node is None:
			continue

		items = _string_literal_sequence(value_node)
		if items:
			return items

		try:
			value = ast.literal_eval(value_node)
		except (ValueError, SyntaxError):
			continue
		if isinstance(value, (list, tuple, set)) and all(isinstance(item, str) for item in value):
			return list(value)

	return []


def nested_payload_wrapper_field_validation_details(
	validation_summary: object,
	failed_artifact_content: object,
) -> Optional[tuple[str, list[str], str]]:
	if not isinstance(validation_summary, str) or not validation_summary.strip():
		return None
	if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
		return None

	summary_lower = validation_summary.lower()
	if "valueerror" not in summary_lower or "invalid" not in summary_lower:
		return None
	if not any(token in summary_lower for token in ("test_happy_path", "test_batch", "test_batch_processing")):
		return None

	container_name = next(
		(
			name
			for name in ("details", "data", "metadata", "payload")
			if f"request.{name}" in failed_artifact_content
		),
		"",
	)
	if not container_name:
		return None

	required_fields = required_field_list_from_failed_artifact(failed_artifact_content)
	if not required_fields:
		return None

	wrapper_field_names = {"request_id", "request_type", "details", "data", "metadata", "payload"}
	offending_fields = [
		field for field in required_fields if field in wrapper_field_names or field == container_name
	]
	if not offending_fields:
		return None

	validation_line = ""
	for line in failed_artifact_content.splitlines():
		stripped = line.strip()
		if (
			stripped
			and f"request.{container_name}" in stripped
			and ("issubset" in stripped or " in request." in stripped)
		):
			validation_line = stripped
			break

	return container_name, offending_fields, validation_line


def dataclass_default_order_repair_examples(
	failed_artifact_content: object,
) -> list[str]:
	if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
		return []

	try:
		tree = ast.parse(failed_artifact_content)
	except SyntaxError:
		return []

	lines: list[str] = []
	for node in tree.body:
		if not isinstance(node, ast.ClassDef) or not _has_dataclass_decorator(node):
			continue

		field_entries: list[tuple[str, ast.AST | None]] = []
		for statement in node.body:
			if not isinstance(statement, ast.AnnAssign):
				continue
			if not isinstance(statement.target, ast.Name):
				continue
			field_entries.append((statement.target.id, statement.value))

		if not field_entries:
			continue

		required_fields: list[str] = []
		default_fields: list[tuple[str, ast.AST]] = []
		offending_required_fields: list[str] = []
		seen_default = False
		for field_name, default_value in field_entries:
			if default_value is None:
				required_fields.append(field_name)
				if seen_default:
					offending_required_fields.append(field_name)
				continue
			seen_default = True
			default_fields.append((field_name, default_value))

		if not offending_required_fields or not default_fields:
			continue

		rendered_signature = ", ".join(
			[
				*required_fields,
				*[
					f"{field_name}={ast.unparse(default_value)}"
					for field_name, default_value in default_fields
				],
			],
		)
		offending_fields = ", ".join(offending_required_fields)
		lines.append(
			"The current failed artifact still has this ordering bug in "
			f"{node.name}: move required field(s) {offending_fields} ahead of every defaulted field and implement {node.name}({rendered_signature})."
		)
		if len(lines) >= 2:
			break

	return lines


def internal_constructor_strictness_details(
	validation_summary: object,
	failed_artifact_content: object,
) -> Optional[tuple[str, list[str], list[str]]]:
	constructor_details = missing_required_constructor_details(validation_summary)
	if constructor_details is None:
		return None
	class_name, missing_fields = constructor_details
	required_fields = required_field_list_from_failed_artifact(failed_artifact_content)
	return class_name, missing_fields, required_fields


def plain_class_field_default_factory_details(
	validation_summary: object,
	failed_artifact_content: object,
) -> Optional[tuple[str, str]]:
	summary_lower = validation_summary.lower() if isinstance(validation_summary, str) else ""
	if not any(
		token in summary_lower
		for token in (
			"non-dataclass field(...)",
			"field' object has no attribute",
			"field object has no attribute",
		)
	):
		return None
	if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
		return None

	try:
		tree = ast.parse(failed_artifact_content)
	except SyntaxError:
		return None

	for node in tree.body:
		if not isinstance(node, ast.ClassDef) or _has_dataclass_decorator(node):
			continue
		for statement in node.body:
			field_name = ""
			value: Optional[ast.expr] = None
			if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
				field_name = statement.target.id
				value = statement.value
			elif isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
				field_name = statement.targets[0].id
				value = statement.value
			if not field_name or not isinstance(value, ast.Call):
				continue
			if _call_expression_basename(value.func) != "field":
				continue
			return node.name, field_name

	return None


def invalid_outcome_missing_audit_trail_details(
	validation_summary: object,
	existing_tests: object,
	failed_artifact_content: object,
) -> Optional[tuple[list[str], str, str, bool]]:
	if not isinstance(validation_summary, str) or not validation_summary.strip():
		return None
	if "AssertionError" not in validation_summary and " - assert " not in validation_summary:
		return None
	if not isinstance(existing_tests, str) or not existing_tests.strip():
		return None

	failing_test_names = set(_failing_pytest_test_names(validation_summary))
	if not failing_test_names:
		return None

	try:
		tree = ast.parse(existing_tests)
	except SyntaxError:
		return None

	field_name = "audit_log"
	matching_tests: list[str] = []
	for node in tree.body:
		if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			continue
		if node.name not in failing_test_names:
			continue
		if not _test_function_targets_invalid_path(node):
			continue
		if not _test_requires_non_empty_result_field(node, field_name):
			continue
		matching_tests.append(node.name)

	if not matching_tests:
		return None

	invalid_return_details = _invalid_outcome_audit_return_details(
		failed_artifact_content,
		field_name,
	)
	if invalid_return_details is None:
		return matching_tests, field_name, "", False
	invalid_return_call, omitted_field = invalid_return_details
	return matching_tests, field_name, invalid_return_call, omitted_field


def compare_mentions_invalid_literal(node: ast.Compare) -> bool:
	return _compare_mentions_invalid_literal(node)


def failing_pytest_test_names(validation_summary: object) -> list[str]:
	return _failing_pytest_test_names(validation_summary)


def test_function_targets_invalid_path(
	node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
	return _test_function_targets_invalid_path(node)


setattr(test_function_targets_invalid_path, "__test__", False)


def attribute_is_field_reference(node: ast.AST, field_name: str) -> bool:
	return _attribute_is_field_reference(node, field_name)


def is_len_of_field_reference(node: ast.AST, field_name: str) -> bool:
	return _is_len_of_field_reference(node, field_name)


def test_requires_non_empty_result_field(
	node: ast.FunctionDef | ast.AsyncFunctionDef,
	field_name: str,
) -> bool:
	return _test_requires_non_empty_result_field(node, field_name)


setattr(test_requires_non_empty_result_field, "__test__", False)


def ast_is_empty_literal(node: ast.AST | None) -> bool:
	return _ast_is_empty_literal(node)


def class_field_uses_empty_default(
	failed_artifact_content: object,
	class_name: str,
	field_name: str,
) -> bool:
	return _class_field_uses_empty_default(failed_artifact_content, class_name, field_name)


def invalid_outcome_audit_return_details(
	failed_artifact_content: object,
	field_name: str,
) -> Optional[tuple[str, bool]]:
	return _invalid_outcome_audit_return_details(failed_artifact_content, field_name)


def duplicate_constructor_argument_details(
	validation_summary: object,
) -> Optional[tuple[str, str]]:
	if not isinstance(validation_summary, str) or not validation_summary.strip():
		return None

	match = re.search(
		r"TypeError:\s+([A-Za-z_][A-Za-z0-9_]*)\.__init__\(\).*?got multiple values for argument '([^']+)'",
		validation_summary,
		re.IGNORECASE,
	)
	if match is None:
		return None
	return match.group(1), match.group(2)


def duplicate_constructor_argument_call_details(
	validation_summary: object,
	failed_artifact_content: object,
) -> Optional[tuple[str, str, str, str, str]]:
	duplicate_argument_details = duplicate_constructor_argument_details(validation_summary)
	if duplicate_argument_details is None:
		return None
	if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
		return None

	class_name, field_name = duplicate_argument_details
	try:
		tree = ast.parse(failed_artifact_content)
	except SyntaxError:
		return None

	for node in ast.walk(tree):
		if not isinstance(node, ast.Call):
			continue
		if _callable_name(node) != class_name:
			continue

		mapping_expression = ""
		for keyword in node.keywords:
			if keyword.arg is None:
				mapping_expression = _render_expression(keyword.value).strip()
				break
		if not mapping_expression:
			continue

		field_expression = ""
		for keyword in node.keywords:
			if keyword.arg == field_name:
				field_expression = _render_expression(keyword.value).strip()
				break
		if not field_expression:
			for argument in node.args:
				rendered_argument = _render_expression(argument).strip()
				if rendered_argument == field_name or _expression_root_name(argument) == field_name:
					field_expression = rendered_argument
					break
		if not field_expression:
			continue

		rendered_call = _render_expression(node).strip()
		if rendered_call:
			return class_name, field_name, rendered_call, mapping_expression, field_expression
	return None


def duplicate_constructor_argument_call_hint(
	validation_summary: object,
	failed_artifact_content: object,
) -> Optional[str]:
	call_details = duplicate_constructor_argument_call_details(
		validation_summary,
		failed_artifact_content,
	)
	if call_details is None:
		return None
	return call_details[2]


def duplicate_constructor_explicit_rewrite_hint(
	validation_summary: object,
	failed_artifact_content: object,
) -> Optional[str]:
	call_details = duplicate_constructor_argument_call_details(
		validation_summary,
		failed_artifact_content,
	)
	if call_details is None:
		return None

	class_name, field_name, _, mapping_expression, field_expression = call_details
	class_fields = class_field_names_from_failed_artifact(
		failed_artifact_content,
		class_name,
	)
	if not class_fields:
		return None

	required_fields = set(required_field_list_from_failed_artifact(failed_artifact_content))
	annotation_map = class_field_annotations_from_failed_artifact(
		failed_artifact_content,
		class_name,
	)
	rendered_arguments: list[str] = []
	for class_field in class_fields:
		if class_field == field_name:
			field_value = field_expression
		elif class_field in required_fields:
			field_value = f"{mapping_expression}[{class_field!r}]"
		else:
			default_value = default_value_for_annotation(annotation_map.get(class_field, ""))
			if default_value:
				field_value = f"{mapping_expression}.get({class_field!r}, {default_value})"
			else:
				field_value = f"{mapping_expression}.get({class_field!r})"
		rendered_arguments.append(f"{class_field}={field_value}")

	if not rendered_arguments:
		return None
	return f"{class_name}({', '.join(rendered_arguments)})"


def class_field_annotations_from_failed_artifact(
	failed_artifact_content: object,
	class_name: str,
) -> dict[str, str]:
	if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
		return {}

	try:
		tree = ast.parse(failed_artifact_content)
	except SyntaxError:
		return {}

	for node in tree.body:
		if not isinstance(node, ast.ClassDef) or node.name != class_name:
			continue
		annotations: dict[str, str] = {}
		for statement in node.body:
			if not isinstance(statement, ast.AnnAssign):
				continue
			if isinstance(statement.target, ast.Name):
				annotations[statement.target.id] = ast.unparse(statement.annotation).strip()
		return annotations
	return {}


def default_value_for_annotation(annotation: str) -> str:
	normalized = annotation.strip()
	if not normalized:
		return ""
	if normalized == "bool":
		return "False"
	if normalized == "str":
		return "''"
	if normalized == "int":
		return "0"
	if normalized == "float":
		return "0.0"
	if normalized in {"dict", "Dict"} or normalized.startswith(("dict[", "Dict[")):
		return "{}"
	if normalized in {"list", "List"} or normalized.startswith(("list[", "List[")):
		return "[]"
	if normalized in {"set", "Set"} or normalized.startswith(("set[", "Set[")):
		return "set()"
	return ""


def class_field_names_from_failed_artifact(
	failed_artifact_content: object,
	class_name: str,
) -> list[str]:
	if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
		return []

	try:
		tree = ast.parse(failed_artifact_content)
	except SyntaxError:
		return []

	for node in tree.body:
		if not isinstance(node, ast.ClassDef) or node.name != class_name:
			continue
		fields: list[str] = []
		for statement in node.body:
			if not isinstance(statement, ast.AnnAssign):
				continue
			if isinstance(statement.target, ast.Name):
				fields.append(statement.target.id)
		return fields
	return []


def missing_object_attribute_details(
	validation_summary: object,
	failed_artifact_content: object,
) -> Optional[tuple[str, str, list[str]]]:
	if not isinstance(validation_summary, str) or not validation_summary.strip():
		return None

	match = re.search(
		r"AttributeError:\s+['\"]([A-Za-z_][A-Za-z0-9_]*)['\"] object has no attribute ['\"]([^'\"]+)['\"]",
		validation_summary,
	)
	if match is None:
		return None

	class_name = match.group(1)
	attribute_name = match.group(2).strip()
	if not attribute_name:
		return None
	class_fields = class_field_names_from_failed_artifact(
		failed_artifact_content,
		class_name,
	)
	return class_name, attribute_name, class_fields


def suggest_declared_attribute_replacement(
	attribute_name: str,
	class_fields: list[str],
) -> Optional[str]:
	if not attribute_name or not class_fields:
		return None

	normalized_attribute = attribute_name.lower()
	attribute_tokens = {token for token in normalized_attribute.split("_") if token}
	best_match: Optional[str] = None
	best_score = (-1, -1)

	for field_name in class_fields:
		normalized_field = field_name.lower()
		if normalized_field == normalized_attribute:
			return field_name

		field_tokens = {token for token in normalized_field.split("_") if token}
		overlap = len(field_tokens & attribute_tokens)
		prefix_suffix_bonus = 1 if (
			normalized_attribute.endswith(normalized_field)
			or normalized_field.endswith(normalized_attribute)
		) else 0
		if overlap <= 0 and prefix_suffix_bonus == 0:
			continue

		score = (prefix_suffix_bonus, overlap)
		if score > best_score:
			best_score = score
			best_match = field_name

	return best_match


def _string_literal_sequence(node: ast.AST | None) -> list[str]:
	if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
		return []

	values: list[str] = []
	for element in node.elts:
		if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
			return []
		values.append(element.value)
	return values


def _has_dataclass_decorator(node: ast.ClassDef) -> bool:
	for decorator in node.decorator_list:
		target = decorator.func if isinstance(decorator, ast.Call) else decorator
		if isinstance(target, ast.Name) and target.id == "dataclass":
			return True
		if isinstance(target, ast.Attribute) and target.attr == "dataclass":
			return True
	return False


def _call_expression_basename(node: ast.AST) -> str:
	if isinstance(node, ast.Name):
		return node.id
	if isinstance(node, ast.Attribute):
		return node.attr
	return ""


def _failing_pytest_test_names(validation_summary: object) -> list[str]:
	if not isinstance(validation_summary, str) or not validation_summary.strip():
		return []
	return list(dict.fromkeys(re.findall(r"::([A-Za-z_][A-Za-z0-9_]*)\b", validation_summary)))


def _compare_mentions_invalid_literal(node: ast.Compare) -> bool:
	values = [node.left, *node.comparators]
	return any(
		isinstance(value, ast.Constant)
		and isinstance(value.value, str)
		and value.value.strip().lower() == "invalid"
		for value in values
	)


def _test_function_targets_invalid_path(
	node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
	name_lower = node.name.lower()
	if any(token in name_lower for token in ("invalid", "validation", "reject", "error", "failure")):
		return True
	for child in ast.walk(node):
		if isinstance(child, ast.Compare) and _compare_mentions_invalid_literal(child):
			return True
	return False


def _attribute_is_field_reference(node: ast.AST, field_name: str) -> bool:
	return isinstance(node, ast.Attribute) and node.attr == field_name


def _is_len_of_field_reference(node: ast.AST, field_name: str) -> bool:
	return (
		isinstance(node, ast.Call)
		and isinstance(node.func, ast.Name)
		and node.func.id == "len"
		and len(node.args) == 1
		and _attribute_is_field_reference(node.args[0], field_name)
	)


def _test_requires_non_empty_result_field(
	node: ast.FunctionDef | ast.AsyncFunctionDef,
	field_name: str,
) -> bool:
	for child in ast.walk(node):
		if not isinstance(child, ast.Assert):
			continue
		test_expr = child.test
		if _attribute_is_field_reference(test_expr, field_name):
			return True
		if not isinstance(test_expr, ast.Compare):
			continue
		if _is_len_of_field_reference(test_expr.left, field_name):
			return True
		if any(_is_len_of_field_reference(comparator, field_name) for comparator in test_expr.comparators):
			return True
		if _attribute_is_field_reference(test_expr.left, field_name) or any(
			_attribute_is_field_reference(comparator, field_name)
			for comparator in test_expr.comparators
		):
			return True
	return False


def _ast_is_empty_literal(node: ast.AST | None) -> bool:
	if node is None:
		return False
	if isinstance(node, ast.Constant):
		return node.value in {"", None}
	if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
		return len(node.elts) == 0
	if isinstance(node, ast.Dict):
		return len(node.keys) == 0
	if isinstance(node, ast.Call):
		if node.args or node.keywords:
			return False
		if isinstance(node.func, ast.Name) and node.func.id in {"str", "list", "tuple", "set", "dict"}:
			return True
	return False


def _class_field_uses_empty_default(
	failed_artifact_content: object,
	class_name: str,
	field_name: str,
) -> bool:
	if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
		return False

	try:
		tree = ast.parse(failed_artifact_content)
	except SyntaxError:
		return False

	for node in tree.body:
		if not isinstance(node, ast.ClassDef) or node.name != class_name:
			continue
		for statement in node.body:
			if not isinstance(statement, ast.AnnAssign):
				continue
			if isinstance(statement.target, ast.Name) and statement.target.id == field_name:
				return _ast_is_empty_literal(statement.value)
		return False
	return False


def _invalid_outcome_audit_return_details(
	failed_artifact_content: object,
	field_name: str,
) -> Optional[tuple[str, bool]]:
	if not isinstance(failed_artifact_content, str) or not failed_artifact_content.strip():
		return None

	try:
		tree = ast.parse(failed_artifact_content)
	except SyntaxError:
		return None

	for node in ast.walk(tree):
		if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
			continue
		call = node.value
		outcome_keyword = next((keyword for keyword in call.keywords if keyword.arg == "outcome"), None)
		if outcome_keyword is None:
			continue
		if not (
			isinstance(outcome_keyword.value, ast.Constant)
			and isinstance(outcome_keyword.value.value, str)
			and outcome_keyword.value.value.strip().lower() == "invalid"
		):
			continue

		rendered_call = ast.unparse(call).strip()
		field_keyword = next((keyword for keyword in call.keywords if keyword.arg == field_name), None)
		if field_keyword is not None and _ast_is_empty_literal(field_keyword.value):
			return rendered_call, False

		class_name = _callable_name(call)
		if field_keyword is None and class_name and _class_field_uses_empty_default(
			failed_artifact_content,
			class_name,
			field_name,
		):
			return rendered_call, True
	return None


def _callable_name(node: ast.Call) -> str:
	if isinstance(node.func, ast.Name):
		return node.func.id
	if isinstance(node.func, ast.Attribute):
		return node.func.attr
	return ""


def _expression_root_name(node: ast.AST) -> Optional[str]:
	current = node
	while True:
		if isinstance(current, ast.Name):
			return current.id
		if isinstance(current, ast.Attribute):
			current = current.value
			continue
		if isinstance(current, ast.Subscript):
			current = current.value
			continue
		return None


def _render_expression(node: ast.AST) -> str:
	return ast.unparse(node).strip()