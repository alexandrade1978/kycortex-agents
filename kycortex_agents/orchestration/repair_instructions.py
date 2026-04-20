"""Repair instruction helpers used by the Orchestrator facade."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence

from kycortex_agents.types import FailureCategory


def repair_owner_for_category(task_assigned_to: str, failure_category: str) -> str:
	owner_by_category = {
		FailureCategory.CODE_VALIDATION.value: "code_engineer",
		FailureCategory.TEST_VALIDATION.value: "qa_tester",
		FailureCategory.DEPENDENCY_VALIDATION.value: "dependency_manager",
	}
	return owner_by_category.get(failure_category, task_assigned_to)


def build_repair_instruction(
	task_id: str,
	failure_category: str,
	*,
	last_error: str,
	failed_code: str,
	validation: Dict[str, Any],
	dataclass_default_order_repair_examples: Callable[[str], Sequence[str]],
	missing_import_nameerror_details: Callable[[str, str], Optional[tuple[str, str]]],
	plain_class_field_default_factory_details: Callable[[str, str], Optional[tuple[str, str]]],
	test_validation_has_only_warnings: Callable[[Dict[str, Any]], bool],
) -> str:
	if failure_category == FailureCategory.CODE_VALIDATION.value:
		if "follows default argument" in last_error.lower():
			instruction = (
				"Repair the generated Python module by reordering any dataclass fields that currently place a defaulted field before a required field. "
				"Inspect every dataclass in the module, preserve the documented public names, and avoid unrelated behavior changes."
			)
			dataclass_examples = dataclass_default_order_repair_examples(failed_code)
			if dataclass_examples:
				instruction = f"{instruction} {dataclass_examples[0]}"
			return instruction
		missing_import_details = missing_import_nameerror_details(last_error, failed_code)
		if missing_import_details is not None:
			missing_name, broken_line = missing_import_details
			instruction = (
				"Repair the generated Python module so every referenced symbol is imported before first use and the module imports cleanly. "
				f"The current failed artifact references {missing_name} during module import but never imports it. "
				"Add the missing import or rewrite every use of that name to match an actually imported symbol while preserving the documented public contract."
			)
			if broken_line:
				if f"{missing_name}." in broken_line:
					instruction = (
						f"{instruction} The exact broken line `{broken_line}` still appears in the failed artifact. "
						f"If you keep that module-qualified reference, add `import {missing_name}` before first use instead of returning the same missing-import line unchanged."
					)
				else:
					instruction = (
						f"{instruction} The exact broken line `{broken_line}` still appears in the failed artifact. "
						f"Do not return that line unchanged; import the name that defines {missing_name} or rewrite the line to use an already imported symbol."
					)
			return instruction
		plain_class_field_details = plain_class_field_default_factory_details(last_error, failed_code)
		if plain_class_field_details is not None:
			class_name, field_name = plain_class_field_details
			return (
				"Repair the generated Python module so mutable service state is initialized on real instances instead of being left as a dataclasses.Field placeholder. "
				"Preserve the documented public facade, constructor contract, and workflow methods. "
				f"The current failed artifact defines {class_name}.{field_name} with field(...) on a non-dataclass class, which leaves {field_name} unusable at runtime. "
				f"Initialize self.{field_name} inside __init__ and keep zero-argument construction compatible with the documented facade. Only convert {class_name} to @dataclass if the same public methods and constructor behavior remain valid."
			)

	if failure_category == FailureCategory.TEST_VALIDATION.value:
		test_execution = validation.get("test_execution") if validation else None
		pytest_failed = (
			isinstance(test_execution, dict)
			and test_execution.get("ran")
			and test_execution.get("returncode") not in (None, 0)
		)
		if pytest_failed and validation and test_validation_has_only_warnings(validation):
			test_analysis = validation.get("test_analysis") or {}
			type_mismatches = test_analysis.get("type_mismatches") or []
			if type_mismatches:
				return (
					"Repair the generated pytest suite so it passes when executed. "
					"The following type mismatches in test arguments are causing the pytest failures and MUST be fixed: "
					+ "; ".join(type_mismatches)
					+ ". Use the correct argument types as documented in the module contract."
				)
			return (
				"Repair the generated pytest suite so it passes when executed. "
				"Focus on the actual pytest failure details (tracebacks, assertion errors) rather than static analysis warnings. "
				"The static warnings may be false positives caused by structurally different but valid code patterns."
			)

	instructions = {
		FailureCategory.CODE_VALIDATION.value: "Repair the generated Python module so it becomes syntactically valid and internally consistent.",
		FailureCategory.TEST_VALIDATION.value: "Repair the generated pytest suite so it matches the generated module contract and passes validation.",
		FailureCategory.DEPENDENCY_VALIDATION.value: "Repair the requirements manifest so every required third-party import is declared minimally and correctly.",
		FailureCategory.TASK_EXECUTION.value: "Retry the task using the previous runtime failure details and correct the specific execution issue.",
		FailureCategory.UNKNOWN.value: "Retry the task using the previous failure details and produce a corrected result.",
	}
	return instructions.get(failure_category, f"Repair the previous failure for task '{task_id}' using the preserved evidence.")


def build_repair_instruction_runtime(
	task: Any,
	failure_category: str,
	*,
	failed_artifact_content: Callable[[Any, Any], str],
	artifact_type: Any,
	validation_payload: Callable[[Any], Dict[str, Any]],
	dataclass_default_order_repair_examples: Callable[[str], Sequence[str]],
	missing_import_nameerror_details: Callable[[str, str], Optional[tuple[str, str]]],
	plain_class_field_default_factory_details: Callable[[str, str], Optional[tuple[str, str]]],
	test_validation_has_only_warnings: Callable[[Dict[str, Any]], bool],
) -> str:
	return build_repair_instruction(
		task.id,
		failure_category,
		last_error=task.last_error if isinstance(task.last_error, str) else "",
		failed_code=failed_artifact_content(task, artifact_type),
		validation=validation_payload(task),
		dataclass_default_order_repair_examples=dataclass_default_order_repair_examples,
		missing_import_nameerror_details=missing_import_nameerror_details,
		plain_class_field_default_factory_details=plain_class_field_default_factory_details,
		test_validation_has_only_warnings=test_validation_has_only_warnings,
	)


def build_code_repair_instruction_from_test_failure(
	validation_summary: str,
	failed_artifact_content: str,
	*,
	duplicate_constructor_argument_details: Callable[[str], Optional[tuple[str, str]]],
	duplicate_constructor_argument_call_hint: Callable[[str, str], Optional[str]],
	duplicate_constructor_explicit_rewrite_hint: Callable[[str, str], Optional[str]],
	plain_class_field_default_factory_details: Callable[[str, str], Optional[tuple[str, str]]],
	missing_object_attribute_details: Callable[[str, str], Optional[tuple[str, str, list[str]]]],
	suggest_declared_attribute_replacement: Callable[[str, list[str]], Optional[str]],
	render_name_list: Callable[[list[str]], str],
	nested_payload_wrapper_field_validation_details: Callable[[str, str], Optional[tuple[str, list[str], str]]],
	invalid_outcome_missing_audit_trail_details: Callable[[str, object, str], Optional[tuple[list[str], str, str, bool]]],
	internal_constructor_strictness_details: Callable[[str, str], Optional[tuple[str, list[str], list[str]]]],
	existing_tests: object = "",
) -> str:
	duplicate_argument_details = duplicate_constructor_argument_details(validation_summary)
	if duplicate_argument_details is not None:
		class_name, field_name = duplicate_argument_details
		instruction = (
			"Repair the generated Python module so valid happy-path and batch requests do not fail because the same constructor field is bound twice. "
			"Keep internal constructor calls unambiguous and preserve the documented contract. "
			f"The current failed artifact still passes {field_name} twice to {class_name}(...). "
			f"Do not pass {field_name} both positionally and through **request.details or another expanded mapping. "
			"Remove the duplicate from the expanded payload or switch to explicit keyword construction so each constructor field is bound exactly once."
		)
		duplicate_call_hint = duplicate_constructor_argument_call_hint(validation_summary, failed_artifact_content)
		if duplicate_call_hint:
			instruction = (
				f"{instruction} The exact broken call {duplicate_call_hint} still appears in the failed artifact. "
				f"Do not return that call unchanged; rewrite that construction so {field_name} is bound exactly once and that exact call no longer appears anywhere in the module."
			)
		explicit_rewrite_hint = duplicate_constructor_explicit_rewrite_hint(validation_summary, failed_artifact_content)
		if duplicate_call_hint and explicit_rewrite_hint:
			instruction = (
				f"{instruction} For this failed artifact, rewrite {duplicate_call_hint} to {explicit_rewrite_hint} "
				"or an equivalent explicit constructor call that binds each field once and supplies safe defaults for fields omitted by valid inputs."
			)
		return instruction

	plain_class_field_details = plain_class_field_default_factory_details(validation_summary, failed_artifact_content)
	if plain_class_field_details is not None:
		class_name, field_name = plain_class_field_details
		return (
			"Repair the generated Python module so mutable service state is initialized on real instances instead of being left as a dataclasses.Field placeholder. "
			"Preserve the documented public facade, constructor contract, and workflow methods. "
			f"The current failed artifact defines {class_name}.{field_name} with field(...) on a plain class, so {field_name} remains a Field object and runtime calls such as append() fail. "
			f"Do not leave {field_name} = field(...) on a non-dataclass class. Initialize self.{field_name} inside __init__ with the same zero-argument construction expected by the tests, or convert the whole class to @dataclass only if that still preserves the same public methods and constructor behavior."
		)

	missing_attribute_details = missing_object_attribute_details(validation_summary, failed_artifact_content)
	if missing_attribute_details is not None:
		class_name, attribute_name, class_fields = missing_attribute_details
		replacement_field = suggest_declared_attribute_replacement(attribute_name, class_fields)
		instruction = (
			"Repair the generated Python module so valid happy-path and batch requests do not fail on missing internal attributes. "
			"Keep dataclass fields, helper-return objects, and member accesses internally consistent."
		)
		if class_fields:
			instruction = (
				f"{instruction} The current failed artifact reads {class_name}.{attribute_name} even though "
				f"{class_name} only defines {render_name_list(class_fields)}."
			)
		else:
			instruction = (
				f"{instruction} The current failed artifact reads {class_name}.{attribute_name} even though "
				"that attribute is not defined on the returned object."
			)
		return (
			f"{instruction} Rename the access to an existing field or define and derive that attribute consistently "
			f"on the model. If the rewritten module keeps .{attribute_name} anywhere, {class_name} must declare "
			f"{attribute_name} and populate or derive it where {class_name} instances are built. Otherwise replace "
			f"that access with one of the existing fields and remove every undeclared read of .{attribute_name}; "
			+ (
				f"the closest declared field here is {replacement_field}, so prefer replacing {class_name}.{attribute_name} with {class_name}.{replacement_field} unless the task explicitly requires a separate {attribute_name} field. "
				if replacement_field
				else ""
			)
			+ "do not leave near-match field names split across construction and scoring paths."
		)

	nested_payload_wrapper_details = nested_payload_wrapper_field_validation_details(validation_summary, failed_artifact_content)
	if nested_payload_wrapper_details is not None:
		container_name, offending_fields, validation_line = nested_payload_wrapper_details
		rendered_fields = render_name_list(offending_fields)
		instruction = (
			"Repair the generated Python module so valid happy-path and batch requests do not fail because the validator is checking request-wrapper fields inside the nested payload container. "
			"Preserve the documented split between top-level request fields and nested payload data. "
			f"The current failed artifact still treats {rendered_fields} as required keys inside request.{container_name}. "
			f"Keep wrapper fields such as {rendered_fields} on the request object, and reserve request.{container_name} checks for actual payload keys only. "
			f"Do not require {rendered_fields} as keys inside request.{container_name}; validate them directly on the request object or drop that nested wrapper-field requirement entirely."
		)
		if validation_line:
			instruction = (
				f"{instruction} The exact broken validation line `{validation_line}` still appears in the failed artifact. "
				"Do not return that line unchanged; replace it with wrapper-field checks on the request object plus only true payload-key validation inside the nested container."
			)
		return instruction

	invalid_outcome_audit_details = invalid_outcome_missing_audit_trail_details(
		validation_summary,
		existing_tests,
		failed_artifact_content,
	)
	if invalid_outcome_audit_details is not None:
		failing_tests, audit_field, invalid_return_call, omitted_field = invalid_outcome_audit_details
		rendered_tests = render_name_list(failing_tests)
		instruction = (
			"Repair the generated Python module so rejected or validation-failure paths still emit non-empty audit evidence instead of returning a blank placeholder. "
			"Preserve the documented invalid outcome contract and repair the implementation rather than weakening the tests. "
			f"The failing pytest case {rendered_tests} requires invalid requests to keep their rejected result while populating {audit_field} with a concrete reason, trace, or rejection explanation. "
			f"Do not leave {audit_field} empty on invalid paths, do not omit it just to fall back to an empty default, and do not return blank placeholders for rejected outcomes."
		)
		if invalid_return_call:
			if omitted_field:
				instruction = (
					f"{instruction} The current failed artifact still returns {invalid_return_call} on an invalid path and omits {audit_field}, which falls back to a blank default. "
					f"Do not return that call unchanged; populate {audit_field} with a non-empty rejection explanation."
				)
			else:
				instruction = (
					f"{instruction} The current failed artifact still returns {invalid_return_call} with an empty {audit_field}. "
					f"Do not return that call unchanged; populate {audit_field} with a non-empty rejection explanation."
				)
		return instruction

	strictness_details = internal_constructor_strictness_details(validation_summary, failed_artifact_content)
	if strictness_details is None:
		return (
			"Repair the generated Python module so it satisfies the existing valid pytest suite "
			"and the documented contract without shifting the failure onto the tests."
		)

	class_name, missing_fields, required_fields = strictness_details
	instruction = (
		"Repair the generated Python module so valid happy-path and batch requests do not fail "
		"while constructing internal models. Align internal constructor requirements with the "
		"documented contract, validate_request(...), and the existing valid pytest inputs. "
		"Do not shift new required payload fields onto the tests."
	)
	rendered_missing_fields = render_name_list(missing_fields)
	if required_fields:
		instruction = (
			f"{instruction} The current validator only requires "
			f"{render_name_list(required_fields)}, but {class_name}(...) still requires "
			f"{rendered_missing_fields}."
		)
	else:
		instruction = (
			f"{instruction} The current failed artifact still makes {class_name}(...) require "
			f"{rendered_missing_fields} during the cited valid pytest cases."
		)
	return f"{instruction} Derive those internal values or give them safe defaults instead of demanding new input fields."


def build_code_repair_instruction_from_test_failure_runtime(
	code_task: Any,
	validation_summary: str,
	*,
	failed_artifact_content: Callable[[Any, Any], str],
	artifact_type: Any,
	duplicate_constructor_argument_details: Callable[[str], Optional[tuple[str, str]]],
	duplicate_constructor_argument_call_hint: Callable[[str, str], Optional[str]],
	duplicate_constructor_explicit_rewrite_hint: Callable[[str, str], Optional[str]],
	plain_class_field_default_factory_details: Callable[[str, str], Optional[tuple[str, str]]],
	missing_object_attribute_details: Callable[[str, str], Optional[tuple[str, str, list[str]]]],
	suggest_declared_attribute_replacement: Callable[[str, list[str]], Optional[str]],
	render_name_list: Callable[[list[str]], str],
	nested_payload_wrapper_field_validation_details: Callable[[str, str], Optional[tuple[str, list[str], str]]],
	invalid_outcome_missing_audit_trail_details: Callable[[str, object, str], Optional[tuple[list[str], str, str, bool]]],
	internal_constructor_strictness_details: Callable[[str, str], Optional[tuple[str, list[str], list[str]]]],
	existing_tests: object = "",
) -> str:
	return build_code_repair_instruction_from_test_failure(
		validation_summary,
		failed_artifact_content(code_task, artifact_type),
		duplicate_constructor_argument_details=duplicate_constructor_argument_details,
		duplicate_constructor_argument_call_hint=duplicate_constructor_argument_call_hint,
		duplicate_constructor_explicit_rewrite_hint=duplicate_constructor_explicit_rewrite_hint,
		plain_class_field_default_factory_details=plain_class_field_default_factory_details,
		missing_object_attribute_details=missing_object_attribute_details,
		suggest_declared_attribute_replacement=suggest_declared_attribute_replacement,
		render_name_list=render_name_list,
		nested_payload_wrapper_field_validation_details=nested_payload_wrapper_field_validation_details,
		invalid_outcome_missing_audit_trail_details=invalid_outcome_missing_audit_trail_details,
		internal_constructor_strictness_details=internal_constructor_strictness_details,
		existing_tests=existing_tests,
	)