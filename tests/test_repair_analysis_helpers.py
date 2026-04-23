import ast
from typing import cast

import pytest

import kycortex_agents.orchestration.repair_analysis as repair_analysis_module
from kycortex_agents.orchestration.repair_analysis import (
	_call_expression_basename,
	_callable_name,
	_expression_root_name,
	_has_dataclass_decorator,
	_render_expression,
	_string_literal_sequence,
	attribute_is_field_reference,
	artifact_type_for_failure_category,
	ast_is_empty_literal,
	class_field_uses_empty_default,
	class_field_annotations_from_failed_artifact,
	class_field_names_from_failed_artifact,
	compare_mentions_invalid_literal,
	dataclass_default_order_repair_examples,
	default_value_for_annotation,
	duplicate_constructor_argument_call_details,
	duplicate_constructor_argument_call_hint,
	duplicate_constructor_argument_details,
	duplicate_constructor_explicit_rewrite_hint,
	failed_artifact_content_for_category,
	invalid_outcome_missing_audit_trail_details,
	invalid_outcome_audit_return_details,
	is_len_of_field_reference,
	first_non_import_line_with_name,
	internal_constructor_strictness_details,
	missing_import_nameerror_details,
	missing_object_attribute_details,
	missing_required_constructor_details,
	nested_payload_wrapper_field_validation_details,
	plain_class_field_default_factory_details,
	render_name_list,
	required_field_list_from_failed_artifact,
	suggest_declared_attribute_replacement,
	test_requires_non_empty_result_field,
	test_function_targets_invalid_path,
	failing_pytest_test_names,
)
from kycortex_agents.types import ArtifactType, FailureCategory


def _function_def(source: str) -> ast.FunctionDef:
	return cast(ast.FunctionDef, ast.parse(source).body[0])


def _class_def(source: str) -> ast.ClassDef:
	return cast(ast.ClassDef, ast.parse(source).body[0])


def _call_expr(source: str) -> ast.Call:
	return cast(ast.Call, ast.parse(source, mode="eval").body)


def _compare_expr(source: str) -> ast.Compare:
	return cast(ast.Compare, ast.parse(source, mode="eval").body)


def test_artifact_category_helpers_and_missing_import_details_cover_edges(monkeypatch: pytest.MonkeyPatch):
	assert artifact_type_for_failure_category(FailureCategory.CODE_VALIDATION.value) is ArtifactType.CODE
	assert artifact_type_for_failure_category(FailureCategory.TEST_VALIDATION.value) is ArtifactType.TEST
	assert artifact_type_for_failure_category(FailureCategory.DEPENDENCY_VALIDATION.value) is ArtifactType.CONFIG
	assert artifact_type_for_failure_category("unknown") is None

	monkeypatch.setattr(
		repair_analysis_module,
		"failed_artifact_content",
		lambda output, output_payload, artifact_type: f"artifact:{artifact_type}",
	)
	assert failed_artifact_content_for_category("out", "payload", FailureCategory.CODE_VALIDATION.value) == "artifact:ArtifactType.CODE"
	assert failed_artifact_content_for_category("out", "payload", "unknown") == "artifact:None"

	assert first_non_import_line_with_name("", "helper_factory") == ""
	assert first_non_import_line_with_name(None, "helper_factory") == ""
	content = (
		"# helper_factory should be imported elsewhere\n"
		"import os\n"
		"from helpers import something\n"
		"\n"
		"result = helper_factory(payload)\n"
	)
	assert first_non_import_line_with_name(content, "helper_factory") == "result = helper_factory(payload)"
	assert first_non_import_line_with_name(content, "missing_name") == ""

	assert missing_import_nameerror_details("", content) is None
	assert missing_import_nameerror_details(
		"Generated code validation:\n- Module import failed\n- NameError: name 'datetime' is not defined\n- Verdict: FAIL",
		content,
	) is None
	assert missing_import_nameerror_details(
		"Generated code validation:\n- Module import failed\n- NameError: name 'helper_factory' is not defined\n- Verdict: FAIL",
		content,
	) == ("helper_factory", "result = helper_factory(payload)")


def test_constructor_guidance_helpers_cover_required_fields_and_ordering():
	validation_summary = (
		"TypeError: ComplianceRequest.__init__() missing 2 required positional arguments: "
		"'request_id' and 'details'"
	)
	failed_artifact = (
		"required_fields = ['request_id', 'details']\n"
		"class ComplianceRequest:\n"
		"    request_id: str\n"
		"    details: dict[str, object]\n"
	)

	assert missing_required_constructor_details(validation_summary) == (
		"ComplianceRequest",
		["request_id", "details"],
	)
	assert missing_required_constructor_details("") is None
	assert missing_required_constructor_details("TypeError: broken") is None
	assert missing_required_constructor_details(
		"TypeError: ComplianceRequest.__init__() missing 1 required positional argument: request_id"
	) is None
	assert required_field_list_from_failed_artifact(failed_artifact) == ["request_id", "details"]
	assert required_field_list_from_failed_artifact(
		"required_keys: list[str]\n"
	) == []
	assert required_field_list_from_failed_artifact(
		"required_keys = ('request_id', 'details')\n"
	) == ["request_id", "details"]
	assert required_field_list_from_failed_artifact(
		"required_keys = ['request_id', 1]\n"
	) == []
	assert required_field_list_from_failed_artifact(
		"required_fields = compute_required_fields()\n"
	) == []
	assert internal_constructor_strictness_details(validation_summary, failed_artifact) == (
		"ComplianceRequest",
		["request_id", "details"],
		["request_id", "details"],
	)

	dataclass_code = (
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class ComplianceRequest:\n"
		"    request_type: str = 'screening'\n"
		"    request_id: str\n"
	)
	lines = dataclass_default_order_repair_examples(dataclass_code)
	assert len(lines) == 1
	assert "ComplianceRequest" in lines[0]
	assert "move required field(s) request_id ahead" in lines[0]
	assert dataclass_default_order_repair_examples("") == []
	assert dataclass_default_order_repair_examples("def broken(:\n    pass") == []
	assert dataclass_default_order_repair_examples(
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class EmptyRequest:\n"
		"    def build(self):\n"
		"        return {}\n"
	) == []
	qualified_lines = dataclass_default_order_repair_examples(
		"import dataclasses\n\n"
		"@dataclasses.dataclass\n"
		"class QualifiedRequest:\n"
		"    request_type: str = 'screening'\n"
		"    request_id: str\n"
	)
	assert len(qualified_lines) == 1
	assert "QualifiedRequest" in qualified_lines[0]
	two_line_examples = dataclass_default_order_repair_examples(
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class FirstRequest:\n"
		"    request_type: str = 'screening'\n"
		"    request_id: str\n\n"
		"@dataclass\n"
		"class SecondRequest:\n"
		"    request_type: str = 'screening'\n"
		"    request_id: str\n\n"
		"@dataclass\n"
		"class ThirdRequest:\n"
		"    request_type: str = 'screening'\n"
		"    request_id: str\n"
	)
	assert len(two_line_examples) == 2


def test_nested_payload_and_default_factory_helpers_cover_positive_and_negative_paths():
	assert nested_payload_wrapper_field_validation_details("", "code") is None
	assert nested_payload_wrapper_field_validation_details(
		"FAILED tests_tests.py::test_happy_path - ValueError: Invalid request",
		"",
	) is None
	failed_code = (
		"required_keys = ('request_id', 'request_type', 'details')\n"
		"def validate_request(request):\n"
		"    return set(required_keys).issubset(request.details)\n"
	)
	assert nested_payload_wrapper_field_validation_details(
		"FAILED tests_tests.py::test_happy_path - ValueError: Invalid request",
		failed_code,
	) == (
		"details",
		["request_id", "request_type", "details"],
		"return set(required_keys).issubset(request.details)",
	)
	assert nested_payload_wrapper_field_validation_details(
		"FAILED tests_tests.py::test_happy_path - ValueError: Invalid request",
		"required_fields = ['country']\ndef validate_request(request):\n    return 'country' in request.details\n",
	) is None
	assert nested_payload_wrapper_field_validation_details(
		"FAILED tests_tests.py::test_other_case - ValueError: Invalid request",
		failed_code,
	) is None
	assert nested_payload_wrapper_field_validation_details(
		"FAILED tests_tests.py::test_happy_path - ValueError: Invalid request",
		"def validate_request(request):\n    return request.details\n",
	) is None
	assert nested_payload_wrapper_field_validation_details(
		"FAILED tests_tests.py::test_happy_path - ValueError: Invalid request",
		"required_fields = ['request_id']\ndef validate_request(request):\n    return request.payload['request_id']\n",
	) == ("payload", ["request_id"], "")

	dataclass_code = (
		"from dataclasses import dataclass, field\n\n"
		"@dataclass\n"
		"class ComplianceIntakeService:\n"
		"    audit_history: list[dict[str, object]] = field(default_factory=list)\n"
	)
	assert plain_class_field_default_factory_details(
		"AttributeError: 'Field' object has no attribute 'append'",
		dataclass_code,
	) is None
	assert plain_class_field_default_factory_details(
		"Validation failed",
		"from dataclasses import field\n\nclass ComplianceIntakeService:\n    audit_history = field(default_factory=list)\n",
	) is None
	assert plain_class_field_default_factory_details(
		"AttributeError: 'Field' object has no attribute 'append'",
		"def broken(:\n    pass",
	) is None
	assert plain_class_field_default_factory_details(
		"AttributeError: 'Field' object has no attribute 'append'",
		"class ComplianceIntakeService:\n    audit_history = build_field(default_factory=list)\n",
	) is None
	assert plain_class_field_default_factory_details(
		"Field object has no attribute",
		"class ComplianceIntakeService:\n    audit_history = []\n",
	) is None
	assert plain_class_field_default_factory_details(
		"AttributeError: 'Field' object has no attribute 'append'",
		"from dataclasses import field\n\nclass ComplianceIntakeService:\n    audit_history: list[dict[str, object]] = field(default_factory=list)\n",
	) == ("ComplianceIntakeService", "audit_history")
	assert plain_class_field_default_factory_details(
		"Field object has no attribute",
		"from dataclasses import field\n\nclass ComplianceIntakeService:\n    audit_history = field(default_factory=list)\n",
	) == ("ComplianceIntakeService", "audit_history")


def test_duplicate_constructor_helpers_cover_call_parsing_and_rewrite_paths():
	validation_summary = "TypeError: VendorProfile.__init__() got multiple values for argument 'vendor_id'"
	failed_code = (
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class VendorProfile:\n"
		"    vendor_id: str\n"
		"    service_category: str\n"
		"    due_diligence_evidence: list[str]\n"
		"    is_sanctioned: bool\n\n"
		"def validate_request(request):\n"
		"    required_fields = ['vendor_id', 'service_category', 'due_diligence_evidence']\n"
		"    return all(field in request.details for field in required_fields)\n\n"
		"def build_vendor_profile(request):\n"
		"    vendor_id = request.details['vendor_id']\n"
		"    return VendorProfile(vendor_id, **request.details)\n"
	)

	assert duplicate_constructor_argument_details(validation_summary) == ("VendorProfile", "vendor_id")
	call_details = duplicate_constructor_argument_call_details(validation_summary, failed_code)
	assert call_details is not None
	assert call_details[:2] == ("VendorProfile", "vendor_id")
	assert call_details[2] == "VendorProfile(vendor_id, **request.details)"
	assert call_details[3] == "request.details"
	assert call_details[4] == "vendor_id"
	assert duplicate_constructor_argument_call_hint(validation_summary, failed_code) == "VendorProfile(vendor_id, **request.details)"
	assert duplicate_constructor_explicit_rewrite_hint(validation_summary, failed_code) == (
		"VendorProfile(vendor_id=vendor_id, service_category=request.details['service_category'], "
		"due_diligence_evidence=request.details['due_diligence_evidence'], "
		"is_sanctioned=request.details.get('is_sanctioned', False))"
	)
	assert duplicate_constructor_argument_details("") is None
	assert duplicate_constructor_argument_call_details(validation_summary, "") is None
	assert duplicate_constructor_argument_call_hint(
		validation_summary,
		"def build_vendor_profile(request):\n    return VendorProfile(**request.details)\n",
	) is None
	assert duplicate_constructor_argument_call_details(
		validation_summary,
		"def build_vendor_profile(request):\n    return VendorProfile(vendor_id=request.vendor_id)\n",
	) is None
	keyword_call_code = (
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class VendorProfile:\n"
		"    vendor_id: str\n"
		"    service_category: str\n"
		"    optional_tags: tuple[str, ...]\n\n"
		"def build_vendor_profile(request):\n"
		"    return VendorProfile(vendor_id=request.vendor_id, **request.details)\n"
	)
	keyword_call_details = duplicate_constructor_argument_call_details(validation_summary, keyword_call_code)
	assert keyword_call_details is not None
	assert keyword_call_details[4] == "request.vendor_id"
	assert duplicate_constructor_explicit_rewrite_hint(validation_summary, keyword_call_code) == (
		"VendorProfile(vendor_id=request.vendor_id, service_category=request.details.get('service_category', ''), "
		"optional_tags=request.details.get('optional_tags'))"
	)
	assert duplicate_constructor_argument_call_details(
		validation_summary,
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class VendorProfile:\n"
		"    vendor_id: str\n\n"
		"def build_vendor_profile(request):\n"
		"    return VendorProfile(other_value, **request.details)\n",
	) is None
	assert duplicate_constructor_explicit_rewrite_hint(
		validation_summary,
		"class VendorProfile:\n    pass\n\ndef build_vendor_profile(request):\n    return VendorProfile(vendor_id, **request.details)\n",
	) is None
	assert duplicate_constructor_argument_call_details(validation_summary, "def broken(:\n    pass") is None


def test_attribute_and_annotation_helpers_cover_defaults_and_replacements():
	failed_code = (
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class VendorProfile:\n"
		"    certifications: list[str]\n"
		"    incidents: list[str]\n"
		"    is_active: bool\n"
		"    metadata: dict[str, object]\n"
		"    threshold: float\n"
	)

	assert class_field_annotations_from_failed_artifact(failed_code, "VendorProfile") == {
		"certifications": "list[str]",
		"incidents": "list[str]",
		"is_active": "bool",
		"metadata": "dict[str, object]",
		"threshold": "float",
	}
	assert class_field_names_from_failed_artifact(failed_code, "VendorProfile") == [
		"certifications",
		"incidents",
		"is_active",
		"metadata",
		"threshold",
	]
	assert class_field_names_from_failed_artifact("", "VendorProfile") == []
	assert class_field_names_from_failed_artifact("def broken(:\n    pass", "VendorProfile") == []
	assert class_field_names_from_failed_artifact("class OtherProfile:\n    vendor_id: str\n", "VendorProfile") == []
	assert class_field_annotations_from_failed_artifact("def broken(:\n    pass", "VendorProfile") == {}
	assert class_field_annotations_from_failed_artifact(
		"class VendorProfile:\n    vendor_id = 'raw'\n",
		"VendorProfile",
	) == {}
	assert class_field_annotations_from_failed_artifact("", "VendorProfile") == {}
	assert class_field_annotations_from_failed_artifact(
		"class OtherProfile:\n    vendor_id: str\n",
		"VendorProfile",
	) == {}

	assert default_value_for_annotation("") == ""
	assert default_value_for_annotation("bool") == "False"
	assert default_value_for_annotation("str") == "''"
	assert default_value_for_annotation("int") == "0"
	assert default_value_for_annotation("float") == "0.0"
	assert default_value_for_annotation("Dict[str, object]") == "{}"
	assert default_value_for_annotation("dict[str, object]") == "{}"
	assert default_value_for_annotation("List[str]") == "[]"
	assert default_value_for_annotation("list[str]") == "[]"
	assert default_value_for_annotation("Set[str]") == "set()"
	assert default_value_for_annotation("set[str]") == "set()"
	assert default_value_for_annotation("tuple[str, ...]") == ""

	attribute_details = missing_object_attribute_details(
		"AttributeError: 'VendorProfile' object has no attribute 'vendor_certifications'",
		failed_code,
	)
	assert attribute_details == (
		"VendorProfile",
		"vendor_certifications",
		["certifications", "incidents", "is_active", "metadata", "threshold"],
	)
	assert missing_object_attribute_details("AttributeError: missing", failed_code) is None
	assert suggest_declared_attribute_replacement(
		"vendor_certifications",
		["certifications", "incidents"],
	) == "certifications"
	assert suggest_declared_attribute_replacement("is_active", ["is_active", "incidents"]) == "is_active"
	assert suggest_declared_attribute_replacement("test_data", ["data", "metadata"]) == "data"
	assert suggest_declared_attribute_replacement("unknown", ["certifications", "incidents"]) is None
	assert suggest_declared_attribute_replacement("certification_status", []) is None
	assert suggest_declared_attribute_replacement("", ["certifications"]) is None
	assert render_name_list([]) == ""
	assert render_name_list(cast(list[str], [None, "certifications", ""])) == "certifications"
	assert render_name_list(["certifications"]) == "certifications"
	assert render_name_list(["certifications", "incidents"]) == "certifications and incidents"
	assert render_name_list(["certifications", "incidents", "metadata"]) == "certifications, incidents, and metadata"


def test_invalid_path_and_empty_literal_helpers_cover_case_and_regex_edges():
	assert failing_pytest_test_names("") == []
	assert failing_pytest_test_names(None) == []
	assert failing_pytest_test_names(
		"FAILED tests_tests.py::test_invalid_path\nFAILED tests_tests.py::test_invalid_path\nFAILED tests_tests.py::test_batch_processing"
	) == ["test_invalid_path", "test_batch_processing"]

	assert test_function_targets_invalid_path(
		_function_def("def test_validation_helper():\n    pass\n")
	) is True
	assert test_function_targets_invalid_path(
		_function_def("def test_normal():\n    assert result == 1\n")
	) is False
	assert test_function_targets_invalid_path(
		_function_def("def test_case_insensitive():\n    assert outcome == 'Invalid'\n")
	) is True

	assert ast_is_empty_literal(ast.parse("tuple()", mode="eval").body) is True
	assert ast_is_empty_literal(ast.parse("str()", mode="eval").body) is True
	assert ast_is_empty_literal(ast.parse("str(value)", mode="eval").body) is False
	assert ast_is_empty_literal(ast.parse("custom_func()", mode="eval").body) is False


def test_invalid_outcome_missing_audit_trail_helper_covers_early_returns_and_blank_return_details():
	assert invalid_outcome_missing_audit_trail_details("", "tests", "code") is None
	assert invalid_outcome_missing_audit_trail_details("RuntimeError", "tests", "code") is None
	assert invalid_outcome_missing_audit_trail_details("AssertionError", "", "code") is None
	assert invalid_outcome_missing_audit_trail_details("AssertionError", "def test_ok():\n    pass\n", "code") is None
	assert invalid_outcome_missing_audit_trail_details(
		"FAILED tests_tests.py::test_invalid_path - AssertionError: assert 0 > 0",
		"def broken(:\n    pass",
		"code",
	) is None
	assert invalid_outcome_missing_audit_trail_details(
		"FAILED tests_tests.py::test_invalid_path - AssertionError: assert 0 > 0",
		"def test_other_case():\n    assert result.outcome == 'invalid'\n    assert len(result.audit_log) > 0\n",
		"code",
	) is None
	assert invalid_outcome_missing_audit_trail_details(
		"FAILED tests_tests.py::test_ok - AssertionError: assert 0 > 0",
		"def test_ok():\n    assert result.outcome == 'accepted'\n    assert len(result.audit_log) > 0\n",
		"code",
	) is None
	assert invalid_outcome_missing_audit_trail_details(
		"FAILED tests_tests.py::test_invalid_path - AssertionError: assert 0 > 0",
		"def test_invalid_path():\n    assert result.outcome == 'invalid'\n",
		"code",
	) is None
	assert invalid_outcome_missing_audit_trail_details(
		"FAILED tests_tests.py::test_invalid_path - AssertionError: assert 0 > 0",
		"def test_invalid_path():\n"
		"    assert result.outcome == 'invalid'\n"
		"    assert len(result.audit_log) > 0\n",
		"",
	) == (["test_invalid_path"], "audit_log", "", False)


def test_internal_ast_rendering_helpers_cover_private_branches_directly():
	assert _string_literal_sequence(ast.parse("['vendor_id', 'details']", mode="eval").body) == [
		"vendor_id",
		"details",
	]
	assert _string_literal_sequence(ast.parse("[1, 'details']", mode="eval").body) == []
	assert _string_literal_sequence(ast.parse("{'vendor_id': 'details'}", mode="eval").body) == []

	dataclass_node = _class_def("@dataclass(slots=True)\nclass Demo:\n    pass\n")
	qualified_dataclass_node = _class_def("@dataclasses.dataclass\nclass Demo:\n    pass\n")
	normal_class_node = _class_def("@registry.decorator\nclass Demo:\n    pass\n")
	assert _has_dataclass_decorator(dataclass_node) is True
	assert _has_dataclass_decorator(qualified_dataclass_node) is True
	assert _has_dataclass_decorator(normal_class_node) is False

	name_call = _call_expr("field(default_factory=list)")
	attribute_call = _call_expr("dataclasses.field(default_factory=list)")
	subscript_call = _call_expr("handlers[0]()")
	assert _call_expression_basename(name_call.func) == "field"
	assert _call_expression_basename(attribute_call.func) == "field"
	assert _call_expression_basename(subscript_call.func) == ""
	assert _callable_name(name_call) == "field"
	assert _callable_name(attribute_call) == "field"
	assert _callable_name(subscript_call) == ""

	assert _expression_root_name(ast.parse("request.details['vendor_id']", mode="eval").body) == "request"
	assert _expression_root_name(ast.parse("vendor_id", mode="eval").body) == "vendor_id"
	assert _expression_root_name(ast.parse("build_vendor_profile()", mode="eval").body) is None
	assert _render_expression(ast.parse("request.details['vendor_id']", mode="eval").body) == "request.details['vendor_id']"


def test_invalid_outcome_ast_helpers_cover_private_field_and_return_detection():
	invalid_compare = _compare_expr("result.outcome == 'invalid'")
	valid_compare = _compare_expr("result.outcome == 'accepted'")
	assert compare_mentions_invalid_literal(invalid_compare) is True
	assert compare_mentions_invalid_literal(valid_compare) is False

	audit_field = ast.parse("result.audit_log", mode="eval").body
	other_field = ast.parse("result.metadata", mode="eval").body
	assert attribute_is_field_reference(audit_field, "audit_log") is True
	assert attribute_is_field_reference(other_field, "audit_log") is False
	assert is_len_of_field_reference(ast.parse("len(result.audit_log)", mode="eval").body, "audit_log") is True
	assert is_len_of_field_reference(ast.parse("size(result.audit_log)", mode="eval").body, "audit_log") is False

	assert test_requires_non_empty_result_field(
		_function_def("def test_invalid_path():\n    assert result.audit_log\n"),
		"audit_log",
	) is True
	assert test_requires_non_empty_result_field(
		_function_def("def test_invalid_path():\n    assert 0 < len(result.audit_log)\n"),
		"audit_log",
	) is True
	assert test_requires_non_empty_result_field(
		_function_def("def test_invalid_path():\n    assert result.audit_log != []\n"),
		"audit_log",
	) is True
	assert test_requires_non_empty_result_field(
		_function_def("def test_invalid_path():\n    assert result.metadata == {}\n"),
		"audit_log",
	) is False

	field_defaults_code = (
		"class ReviewOutcome:\n"
		"    audit_log: list[str] = []\n"
		"    metadata: dict[str, object]\n"
	)
	assert class_field_uses_empty_default("", "ReviewOutcome", "audit_log") is False
	assert class_field_uses_empty_default("def broken(:\n    pass", "ReviewOutcome", "audit_log") is False
	assert class_field_uses_empty_default(field_defaults_code, "ReviewOutcome", "audit_log") is True
	assert class_field_uses_empty_default(field_defaults_code, "ReviewOutcome", "metadata") is False
	assert class_field_uses_empty_default(field_defaults_code, "MissingOutcome", "audit_log") is False

	assert invalid_outcome_audit_return_details("", "audit_log") is None
	assert invalid_outcome_audit_return_details("def broken(:\n    pass", "audit_log") is None
	assert invalid_outcome_audit_return_details(
		"def build_response():\n"
		"    return ReviewOutcome(outcome='accepted', audit_log=[])\n",
		"audit_log",
	) is None
	assert invalid_outcome_audit_return_details(
		"def build_response():\n"
		"    return ReviewOutcome(outcome='invalid', audit_log=[])\n",
		"audit_log",
	) == ("ReviewOutcome(outcome='invalid', audit_log=[])", False)
	assert invalid_outcome_audit_return_details(
		"class ReviewOutcome:\n"
		"    audit_log: list[str] = []\n\n"
		"def build_response():\n"
		"    return ReviewOutcome(outcome='invalid')\n",
		"audit_log",
	) == ("ReviewOutcome(outcome='invalid')", True)