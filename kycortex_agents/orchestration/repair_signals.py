"""Deterministic repair-signal helpers used by the Orchestrator facade."""

from __future__ import annotations

import ast
import re


def content_has_matching_datetime_import(content: object) -> bool:
	if not isinstance(content, str) or not content.strip():
		return False
	return bool(
		re.search(
			r"^\s*(?:from\s+datetime\s+import\s+[^\n]*\bdatetime\b|import\s+datetime\b)",
			content,
			flags=re.MULTILINE,
		)
	)


def content_has_bare_datetime_reference(content: object) -> bool:
	if not isinstance(content, str) or not content.strip():
		return False
	return bool(
		re.search(
			r"(?<![A-Za-z0-9_\.])datetime(?:\.[A-Za-z_][A-Za-z0-9_]*)?\s*\(",
			content,
		)
	)


def validation_summary_has_missing_datetime_import_issue(
	validation_summary: object,
	failed_artifact_content: object = "",
) -> bool:
	if not isinstance(validation_summary, str) or not validation_summary.strip():
		return False
	summary_lower = validation_summary.lower()
	if (
		"undefined local names: datetime" not in summary_lower
		and "name 'datetime' is not defined" not in summary_lower
	):
		return False
	if isinstance(failed_artifact_content, str) and failed_artifact_content.strip():
		return (
			content_has_bare_datetime_reference(failed_artifact_content)
			and not content_has_matching_datetime_import(failed_artifact_content)
		)
	return True


def implementation_prefers_direct_datetime_import(implementation_code: object) -> bool:
	if not isinstance(implementation_code, str) or not implementation_code.strip():
		return False
	return bool(
		re.search(
			r"^\s*from\s+datetime\s+import\s+[^\n]*\bdatetime\b",
			implementation_code,
			flags=re.MULTILINE,
		)
	)


def implementation_required_evidence_items(implementation_code: object) -> list[str]:
	if not isinstance(implementation_code, str) or not implementation_code.strip():
		return []

	try:
		tree = ast.parse(implementation_code)
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
		if not any(name in {"required_evidence", "required_documents"} for name in target_names):
			continue
		items = _string_literal_sequence(value_node)
		if items:
			unique_items: list[str] = []
			seen: set[str] = set()
			for item in items:
				if item in seen:
					continue
				seen.add(item)
				unique_items.append(item)
			return unique_items
	return []


def content_has_incomplete_required_evidence_payload(
	content: object,
	implementation_code: object,
) -> bool:
	required_evidence_items = implementation_required_evidence_items(implementation_code)
	if len(required_evidence_items) <= 1:
		return False
	if not isinstance(content, str) or not content.strip():
		return False

	try:
		tree = ast.parse(content)
	except SyntaxError:
		return False

	required_evidence_set = set(required_evidence_items)
	for node in tree.body:
		if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			continue
		function_name = node.name.lower()
		if any(token in function_name for token in ("validation", "invalid", "reject", "error", "failure")):
			continue
		if not (
			any(token in function_name for token in ("happy", "batch"))
			or any(
				(isinstance(child, ast.Attribute) and child.attr == "risk_scores")
				or (isinstance(child, ast.Name) and child.id == "risk_scores")
				for child in ast.walk(node)
			)
		):
			continue
		for child in ast.walk(node):
			if not isinstance(child, ast.Dict):
				continue
			document_items: list[str] | None = None
			for key, value in zip(child.keys, child.values):
				if isinstance(key, ast.Constant) and key.value == "documents":
					document_items = _string_literal_sequence(value)
					break
			if document_items is None:
				continue
			if not required_evidence_set.issubset(set(document_items)):
				return True
	return False


def validation_summary_has_required_evidence_runtime_issue(
	validation_summary: object,
	failed_artifact_content: object = "",
	implementation_code: object = "",
) -> bool:
	if not isinstance(validation_summary, str) or not validation_summary.strip():
		return False

	summary_lower = validation_summary.lower()
	if "pytest execution: fail" not in summary_lower and "pytest failure details:" not in summary_lower:
		return False
	if not any(
		int(actual_count) < int(expected_count)
		for actual_count, expected_count in re.findall(r"assert\s+(\d+)\s*==\s*(\d+)", summary_lower)
	):
		return False
	if (
		isinstance(failed_artifact_content, str)
		and failed_artifact_content.strip()
		and "risk_scores" not in failed_artifact_content.lower()
	):
		return False
	return content_has_incomplete_required_evidence_payload(
		failed_artifact_content,
		implementation_code,
	)


def _string_literal_sequence(node: ast.AST | None) -> list[str]:
	if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
		return []

	values: list[str] = []
	for element in node.elts:
		if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
			return []
		values.append(element.value)
	return values