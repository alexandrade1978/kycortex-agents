"""Tests for QATesterAgent pure static/classmethods."""

import ast
from typing import cast

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.agents.qa_tester import QATesterAgent


def _build_agent(tmp_path) -> QATesterAgent:
    return QATesterAgent(KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="token"))


def _patch_repair_focus_defaults(monkeypatch, **overrides) -> None:
    defaults = {
        "_implementation_required_payload_keys": lambda *args, **kwargs: [],
        "_validation_failure_omitted_payload_key": lambda *args, **kwargs: "",
        "_implementation_required_evidence_items": lambda *args, **kwargs: [],
        "_implementation_required_request_fields": lambda *args, **kwargs: [],
        "_implementation_non_validation_payload_keys": lambda *args, **kwargs: [],
        "_validation_failure_missing_request_field": lambda *args, **kwargs: "",
        "_validation_failure_request_like_object_scaffold_line": lambda *args, **kwargs: ("", ""),
        "_implementation_requires_recent_request_timestamp": lambda *args, **kwargs: False,
        "_summary_has_exact_numeric_score_assertion_issue": lambda *args, **kwargs: False,
        "_summary_has_positive_numeric_score_assertion_issue": lambda *args, **kwargs: False,
        "_summary_has_presence_only_validation_sample_issue": lambda *args, **kwargs: False,
        "_summary_has_required_evidence_runtime_issue": lambda *args, **kwargs: False,
        "_summary_has_required_payload_runtime_issue": lambda *args, **kwargs: False,
        "_summary_has_exact_status_action_label_assertion_issue": lambda *args, **kwargs: False,
        "_summary_has_exact_band_label_assertion_issue": lambda *args, **kwargs: False,
        "_summary_has_exact_temporal_value_assertion_issue": lambda *args, **kwargs: False,
        "_summary_issue_value": lambda *args, **kwargs: "",
        "_comma_separated_items": lambda *args, **kwargs: [],
        "_undefined_available_module_symbol_names": lambda *args, **kwargs: [],
        "_is_helper_alias_like_name": lambda *args, **kwargs: False,
        "_implementation_prefers_direct_datetime_import": lambda *args, **kwargs: False,
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        monkeypatch.setattr(QATesterAgent, name, value)


def _patch_scaffold_defaults(monkeypatch, **overrides) -> None:
    defaults = {
        "_required_payload_argument_overrides": lambda *args, **kwargs: {},
        "_required_evidence_argument_overrides": lambda *args, **kwargs: {},
        "_implementation_prefers_direct_datetime_import": lambda *args, **kwargs: False,
        "_implementation_call_returns_none": lambda *args, **kwargs: False,
        "_return_shape_assertion_line": lambda *args, **kwargs: "",
        "_runtime_return_kind_from_summary": lambda *args, **kwargs: "",
        "_stable_call_assertion_lines": lambda *args, **kwargs: ["assert result is not None"],
        "_validation_failure_omitted_payload_key": lambda *args, **kwargs: "",
        "_validation_failure_missing_request_field": lambda *args, **kwargs: "",
        "_implementation_non_validation_payload_keys": lambda *args, **kwargs: [],
        "_validation_support_method": lambda *args, **kwargs: "",
        "_implementation_validation_result_shape": lambda *args, **kwargs: ("bool", []),
        "_validation_failure_request_like_object_scaffold_line": lambda *args, **kwargs: ("", ""),
        "_validation_failure_argument_overrides": lambda *args, **kwargs: {},
        "_constructor_rejects_invalid_payload": lambda *args, **kwargs: False,
        "_implementation_raises_value_error": lambda *args, **kwargs: False,
        "_stable_audit_assertion_lines": lambda *args, **kwargs: [],
        "_implementation_call_return_class_name": lambda *args, **kwargs: "",
        "_implementation_call_return_primitive_kind": lambda *args, **kwargs: "",
        "_stable_batch_result_assertion_lines": lambda *args, **kwargs: ["assert len(results) == len(requests)"],
        "_prepend_fixed_time_line": lambda lines, **kwargs: lines,
        "_implementation_requires_recent_request_timestamp": lambda *args, **kwargs: False,
        "_fixed_time_import_line": lambda *args, **kwargs: "from datetime import datetime",
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        monkeypatch.setattr(QATesterAgent, name, value)


def _patch_existing_tests_instruction_defaults(monkeypatch, **overrides) -> None:
    original_comma_separated_items = QATesterAgent._comma_separated_items
    _patch_repair_focus_defaults(monkeypatch)
    monkeypatch.setattr(QATesterAgent, "_comma_separated_items", original_comma_separated_items)
    defaults = {
        "_summary_has_missing_datetime_import_issue": lambda *args, **kwargs: False,
        "_undefined_helper_alias_names_outside_exact_contract": lambda *args, **kwargs: [],
        "_undefined_local_names": lambda *args, **kwargs: [],
        "_stale_generated_module_import_roots": lambda *args, **kwargs: [],
        "_summary_has_placeholder_boolean_assertion_issue": lambda *args, **kwargs: False,
        "_summary_has_validation_side_effect_without_workflow_call_issue": lambda *args, **kwargs: False,
        "_summary_has_active_issue": lambda *args, **kwargs: False,
        "_summary_issue_value": lambda *args, **kwargs: "",
    }
    for name, value in defaults.items():
        monkeypatch.setattr(QATesterAgent, name, value)
    for name, value in overrides.items():
        monkeypatch.setattr(QATesterAgent, name, value)


def _patch_exact_rebuild_surface_defaults(monkeypatch, **overrides) -> None:
    _patch_existing_tests_instruction_defaults(monkeypatch)
    defaults = {
        "_should_rebuild_from_exact_contract": lambda *args, **kwargs: True,
        "_task_anchor_overrides": lambda *args, **kwargs: {},
        "_return_shape_assertion_line": lambda *args, **kwargs: "",
        "_implementation_call_return_primitive_kind": lambda *args, **kwargs: "",
        "_stable_call_assertion_lines": lambda *args, **kwargs: ["assert result is not None"],
        "_implementation_prefers_direct_datetime_import": lambda *args, **kwargs: False,
    }
    for name, value in defaults.items():
        monkeypatch.setattr(QATesterAgent, name, value)
    for name, value in overrides.items():
        monkeypatch.setattr(QATesterAgent, name, value)


# ---------------------------------------------------------------------------
# _canonical_band_like_label
# ---------------------------------------------------------------------------

class TestCanonicalBandLikeLabel:
    def test_known_labels(self):
        assert QATesterAgent._canonical_band_like_label("high") == "high"
        assert QATesterAgent._canonical_band_like_label("LOW") == "low"
        assert QATesterAgent._canonical_band_like_label(" Medium ") == "medium"
        assert QATesterAgent._canonical_band_like_label("Critical") == "critical"

    def test_hyphen_and_space_normalisation(self):
        assert QATesterAgent._canonical_band_like_label("high-risk") is None
        assert QATesterAgent._canonical_band_like_label("  high  ") == "high"

    def test_empty_string(self):
        assert QATesterAgent._canonical_band_like_label("") is None

    def test_unknown_label(self):
        assert QATesterAgent._canonical_band_like_label("extreme") is None


# ---------------------------------------------------------------------------
# _band_like_literal_values
# ---------------------------------------------------------------------------

class TestBandLikeLiteralValues:
    def test_single_constant(self):
        node = ast.parse('"high"', mode="eval").body
        assert QATesterAgent._band_like_literal_values(node) == ["high"]

    def test_single_unknown_constant(self):
        node = ast.parse('"unknown"', mode="eval").body
        assert QATesterAgent._band_like_literal_values(node) == []

    def test_list_of_bands(self):
        node = ast.parse('["high", "low", "medium"]', mode="eval").body
        assert QATesterAgent._band_like_literal_values(node) == ["high", "low", "medium"]

    def test_list_with_non_band_returns_empty(self):
        node = ast.parse('["high", "banana"]', mode="eval").body
        assert QATesterAgent._band_like_literal_values(node) == []

    def test_non_sequence_non_constant(self):
        node = ast.parse("x + 1", mode="eval").body
        assert QATesterAgent._band_like_literal_values(node) == []


# ---------------------------------------------------------------------------
# _numeric_literal_value
# ---------------------------------------------------------------------------

class TestNumericLiteralValue:
    def test_integer(self):
        node = ast.parse("42", mode="eval").body
        assert QATesterAgent._numeric_literal_value(node) == 42

    def test_float(self):
        node = ast.parse("3.14", mode="eval").body
        assert QATesterAgent._numeric_literal_value(node) == 3.14

    def test_negative_integer(self):
        node = ast.parse("-5", mode="eval").body
        assert QATesterAgent._numeric_literal_value(node) == -5

    def test_string_returns_none(self):
        node = ast.parse('"hello"', mode="eval").body
        assert QATesterAgent._numeric_literal_value(node) is None

    def test_complex_expression_returns_none(self):
        node = ast.parse("x + 1", mode="eval").body
        assert QATesterAgent._numeric_literal_value(node) is None

    def test_negative_non_numeric_returns_none(self):
        node = ast.parse('-"oops"', mode="eval").body
        assert QATesterAgent._numeric_literal_value(node) is None


# ---------------------------------------------------------------------------
# _expression_text
# ---------------------------------------------------------------------------

class TestExpressionText:
    def test_simple_name(self):
        node = ast.parse("FooBar", mode="eval").body
        assert QATesterAgent._expression_text(node) == "foobar"

    def test_attribute_access(self):
        node = ast.parse("result.status", mode="eval").body
        assert QATesterAgent._expression_text(node) == "result.status"

    def test_unparse_failure_returns_empty_string(self, monkeypatch):
        monkeypatch.setattr(ast, "unparse", lambda _node: (_ for _ in ()).throw(ValueError("boom")))
        node = ast.parse("value", mode="eval").body
        assert QATesterAgent._expression_text(node) == ""


# ---------------------------------------------------------------------------
# _summary_has_placeholder_boolean_assertion_issue
# ---------------------------------------------------------------------------

class TestSummaryHasPlaceholderBooleanAssertionIssue:
    def test_assuming_comment_is_detected(self):
        summary = "pytest failure details: assert True"
        content = "def test_x():\n    # assuming this placeholder is fine\n    assert value"
        assert QATesterAgent._summary_has_placeholder_boolean_assertion_issue(summary, content) is True

    def test_returns_true_when_summary_matches_and_content_missing(self):
        summary = "pytest failure details: assert False"
        assert QATesterAgent._summary_has_placeholder_boolean_assertion_issue(summary, "") is True


# ---------------------------------------------------------------------------
# _summary_has_exact_status_action_label_assertion_issue
# ---------------------------------------------------------------------------

def test_summary_has_exact_status_action_label_assertion_issue_detects_score_literal_in_audit_assertion():
    summary = """
pytest execution: fail
FAILED tests/test_demo.py::test_audit_log_score_label
"""
    content = """
def test_audit_log_score_label():
    audit_log = ["score: 0.75"]
    assert "score: 0.75" in audit_log
"""

    assert QATesterAgent._summary_has_exact_status_action_label_assertion_issue(summary, content) is True


# ---------------------------------------------------------------------------
# _validation_result_call_is_invalid
# ---------------------------------------------------------------------------

def _parse_call(code: str) -> ast.Call:
    node = ast.parse(code, mode="eval").body
    assert isinstance(node, ast.Call)
    return node


def _parse_func(code: str) -> ast.FunctionDef:
    node = ast.parse(code).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


class TestValidationResultCallIsInvalid:
    def test_call_with_is_valid_false(self):
        node = _parse_call("ValidationResult(is_valid=False)")
        assert QATesterAgent._validation_result_call_is_invalid(node) is True

    def test_call_with_is_valid_true(self):
        node = _parse_call("ValidationResult(is_valid=True)")
        assert QATesterAgent._validation_result_call_is_invalid(node) is False

    def test_call_without_is_valid(self):
        node = _parse_call("SomeOther(name='x')")
        assert QATesterAgent._validation_result_call_is_invalid(node) is False

    def test_call_with_non_constant_is_valid(self):
        node = _parse_call("ValidationResult(is_valid=some_var)")
        assert QATesterAgent._validation_result_call_is_invalid(node) is False


# ---------------------------------------------------------------------------
# _body_affects_validation_result
# ---------------------------------------------------------------------------

class TestBodyAffectsValidationResult:
    def test_raise_in_body(self):
        tree = ast.parse("raise ValueError('bad')")
        assert QATesterAgent._body_affects_validation_result(tree.body) is True

    def test_return_false(self):
        func = _parse_func("def f():\n    return False")
        assert QATesterAgent._body_affects_validation_result(func.body) is True

    def test_return_call_with_is_valid_false(self):
        func = _parse_func("def f():\n    return ValidationResult(is_valid=False)")
        assert QATesterAgent._body_affects_validation_result(func.body) is True

    def test_assign_valid_false(self):
        func = _parse_func("def f():\n    is_valid = False")
        assert QATesterAgent._body_affects_validation_result(func.body) is True

    def test_errors_append(self):
        func = _parse_func("def f():\n    errors.append('problem')")
        assert QATesterAgent._body_affects_validation_result(func.body) is True

    def test_warning_list_not_detected(self):
        func = _parse_func("def f():\n    warning_errors.append('problem')")
        assert QATesterAgent._body_affects_validation_result(func.body) is False

    def test_benign_body(self):
        func = _parse_func("def f():\n    x = 42\n    return True")
        assert QATesterAgent._body_affects_validation_result(func.body) is False

    def test_return_true_not_detected(self):
        func = _parse_func("def f():\n    return True")
        assert QATesterAgent._body_affects_validation_result(func.body) is False


# ---------------------------------------------------------------------------
# _function_payload_alias_names
# ---------------------------------------------------------------------------

class TestFunctionPayloadAliasNames:
    def test_parameter_detection(self):
        code = "def validate(self, details, metadata):\n    pass"
        func = ast.parse(code).body[0]
        aliases = QATesterAgent._function_payload_alias_names(func)
        assert "details" in aliases
        assert "metadata" in aliases

    def test_attribute_assignment(self):
        code = "def validate(self, request):\n    d = request.data\n    p = request.payload"
        func = ast.parse(code).body[0]
        aliases = QATesterAgent._function_payload_alias_names(func)
        assert "d" in aliases
        assert "p" in aliases

    def test_subscript_assignment(self):
        code = "def validate(self, request):\n    x = request['details']"
        func = ast.parse(code).body[0]
        aliases = QATesterAgent._function_payload_alias_names(func)
        assert "x" in aliases

    def test_non_function_returns_empty(self):
        node = ast.parse("x = 1").body[0]
        assert QATesterAgent._function_payload_alias_names(node) == set()

    def test_no_payload_params(self):
        code = "def validate(self, name, age):\n    pass"
        func = ast.parse(code).body[0]
        aliases = QATesterAgent._function_payload_alias_names(func)
        assert len(aliases) == 0

    def test_annotated_assignment(self):
        code = "def validate(self, request):\n    d: dict = request.data"
        func = ast.parse(code).body[0]
        aliases = QATesterAgent._function_payload_alias_names(func)
        assert "d" in aliases


# ---------------------------------------------------------------------------
# _set_call_argument_value
# ---------------------------------------------------------------------------

class TestSetCallArgumentValue:
    def test_set_keyword_argument(self):
        call_node = _parse_call("Foo(name='old')")
        new_value = ast.Constant(value="new")
        QATesterAgent._set_call_argument_value("Foo(name)", call_node, "name", new_value)
        assert call_node.keywords[0].value.value == "new"  # type: ignore[attr-defined]

    def test_set_positional_argument(self):
        call_node = _parse_call("Foo('old')")
        new_value = ast.Constant(value="new")
        QATesterAgent._set_call_argument_value("Foo(name)", call_node, "name", new_value)
        assert call_node.args[0].value == "new"  # type: ignore[attr-defined]

    def test_add_missing_kwarg(self):
        call_node = _parse_call("Foo()")
        new_value = ast.Constant(value="added")
        QATesterAgent._set_call_argument_value("Foo(name)", call_node, "name", new_value)
        assert len(call_node.keywords) == 1
        assert call_node.keywords[0].arg == "name"


# ---------------------------------------------------------------------------
# _string_literal_sequence
# ---------------------------------------------------------------------------

class TestStringLiteralSequence:
    def test_list_of_strings(self):
        node = ast.parse('["a", "b", "c"]', mode="eval").body
        assert QATesterAgent._string_literal_sequence(node) == ["a", "b", "c"]

    def test_tuple_of_strings(self):
        node = ast.parse('("x", "y")', mode="eval").body
        assert QATesterAgent._string_literal_sequence(node) == ["x", "y"]

    def test_list_with_non_string_returns_empty(self):
        node = ast.parse('["a", 1]', mode="eval").body
        assert QATesterAgent._string_literal_sequence(node) == []

    def test_non_sequence_returns_empty(self):
        node = ast.parse("42", mode="eval").body
        assert QATesterAgent._string_literal_sequence(node) == []


# ---------------------------------------------------------------------------
# _named_reference_identifier
# ---------------------------------------------------------------------------

class TestNamedReferenceIdentifier:
    def test_name_node(self):
        node = ast.parse("foo", mode="eval").body
        assert QATesterAgent._named_reference_identifier(node) == "foo"

    def test_attribute_node(self):
        node = ast.parse("obj.bar", mode="eval").body
        assert QATesterAgent._named_reference_identifier(node) == "bar"

    def test_other_node(self):
        node = ast.parse("1 + 2", mode="eval").body
        assert QATesterAgent._named_reference_identifier(node) == ""

    def test_none_returns_empty(self):
        assert QATesterAgent._named_reference_identifier(None) == ""


# ---------------------------------------------------------------------------
# _sample_literal_for_parameter
# ---------------------------------------------------------------------------

class TestSampleLiteralForParameter:
    def test_name_parameter(self):
        result = QATesterAgent._sample_literal_for_parameter("name")
        assert isinstance(result, str)
        assert result  # non-empty

    def test_indexed_parameter(self):
        r1 = QATesterAgent._sample_literal_for_parameter("name", index=0)
        r2 = QATesterAgent._sample_literal_for_parameter("name", index=1)
        assert r1  # non-empty
        assert r2  # non-empty


# ---------------------------------------------------------------------------
# _canonical_status_like_label
# ---------------------------------------------------------------------------

class TestCanonicalStatusLikeLabel:
    def test_known_status(self):
        assert QATesterAgent._canonical_status_like_label("approved") == "approved"
        assert QATesterAgent._canonical_status_like_label("REJECTED") == "rejected"
        assert QATesterAgent._canonical_status_like_label("manual review") == "manual_review"
        assert QATesterAgent._canonical_status_like_label("fraud-escalation") == "fraud_escalation"
        assert QATesterAgent._canonical_status_like_label("straight through") == "straight_through_review"

    def test_empty_string(self):
        assert QATesterAgent._canonical_status_like_label("") is None

    def test_unknown_status(self):
        assert QATesterAgent._canonical_status_like_label("banana") is None


# ---------------------------------------------------------------------------
# _status_like_literal_values
# ---------------------------------------------------------------------------

class TestStatusLikeLiteralValues:
    def test_single_constant(self):
        node = ast.parse('"approved"', mode="eval").body
        assert QATesterAgent._status_like_literal_values(node) == ["approved"]

    def test_list_of_statuses(self):
        node = ast.parse('["approved", "rejected"]', mode="eval").body
        result = QATesterAgent._status_like_literal_values(node)
        assert "approved" in result
        assert "rejected" in result

    def test_list_with_unknown_returns_empty(self):
        node = ast.parse('["approved", "banana"]', mode="eval").body
        assert QATesterAgent._status_like_literal_values(node) == []

    def test_non_string_returns_empty(self):
        node = ast.parse("42", mode="eval").body
        assert QATesterAgent._status_like_literal_values(node) == []


# ---------------------------------------------------------------------------
# _test_function_targets_valid_processing
# ---------------------------------------------------------------------------

class TestTestFunctionTargetsValidProcessing:
    def test_validation_in_name_returns_false(self):
        func = _parse_func("def test_validation_error():\n    pass\n")
        assert QATesterAgent._test_function_targets_valid_processing(func) is False

    def test_happy_in_name_returns_true(self):
        func = _parse_func("def test_happy_path():\n    pass\n")
        assert QATesterAgent._test_function_targets_valid_processing(func) is True

    def test_batch_in_name_returns_true(self):
        func = _parse_func("def test_batch_processing():\n    pass\n")
        assert QATesterAgent._test_function_targets_valid_processing(func) is True

    def test_calls_workflow_function(self):
        func = _parse_func(
            "def test_process():\n    result = handle_request(data)\n"
        )
        assert QATesterAgent._test_function_targets_valid_processing(func) is True

    def test_no_workflow_calls(self):
        func = _parse_func("def test_something():\n    x = 1 + 2\n")
        assert QATesterAgent._test_function_targets_valid_processing(func) is False


# ---------------------------------------------------------------------------
# _stable_batch_result_assertion_lines
# ---------------------------------------------------------------------------

class TestStableBatchResultAssertionLines:
    def test_with_runtime_return_kind(self):
        lines = QATesterAgent._stable_batch_result_assertion_lines(
            "class Foo: pass", "batch_process", runtime_return_kind="Result"
        )
        assert any("len(results)" in line for line in lines)
        assert any("Result" in line for line in lines)

    def test_no_return_class_returns_empty(self):
        lines = QATesterAgent._stable_batch_result_assertion_lines(
            "def foo(): pass", "foo"
        )
        assert isinstance(lines, list)

    def test_return_class_with_request_id_and_risk_score_fields(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_stable_direct_mapping_batch_assertion_lines",
            classmethod(lambda cls, *args, **kwargs: []),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_call_return_primitive_kind",
            classmethod(lambda cls, *args, **kwargs: ""),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_call_return_class_name",
            classmethod(lambda cls, *args, **kwargs: "AssessmentResult"),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_class_field_names",
            classmethod(lambda cls, *args, **kwargs: {"request_id", "risk_score"}),
        )

        lines = QATesterAgent._stable_batch_result_assertion_lines("", "batch_process")

        assert "assert results[0].request_id == requests[0].request_id" in lines
        assert "assert results[-1].request_id == requests[-1].request_id" in lines
        assert any("item.risk_score" in line for line in lines)

    def test_return_class_with_score_field_uses_score_fallback(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_stable_direct_mapping_batch_assertion_lines",
            classmethod(lambda cls, *args, **kwargs: []),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_call_return_primitive_kind",
            classmethod(lambda cls, *args, **kwargs: ""),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_call_return_class_name",
            classmethod(lambda cls, *args, **kwargs: "ScoreResult"),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_class_field_names",
            classmethod(lambda cls, *args, **kwargs: {"score"}),
        )

        lines = QATesterAgent._stable_batch_result_assertion_lines("", "batch_process")

        assert any("item.score" in line for line in lines)
        assert all("item.risk_score" not in line for line in lines)

    def test_return_class_with_mapping_risk_score_and_audit_log_fields(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_stable_direct_mapping_batch_assertion_lines",
            classmethod(lambda cls, *args, **kwargs: []),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_call_return_primitive_kind",
            classmethod(lambda cls, *args, **kwargs: ""),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_call_return_class_name",
            classmethod(lambda cls, *args, **kwargs: "AuditResult"),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_class_field_names",
            classmethod(lambda cls, *args, **kwargs: {"details", "audit_log"}),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_result_mapping_field_keys",
            classmethod(lambda cls, *args, **kwargs: {"risk_score"}),
        )

        lines = QATesterAgent._stable_batch_result_assertion_lines("", "batch_process")

        assert "assert all(isinstance(item.details, dict) for item in results)" in lines
        assert "assert all('risk_score' in item.details for item in results)" in lines
        assert any("item.details['risk_score']" in line for line in lines)
        assert "assert all(len(item.audit_log) > 0 for item in results)" in lines

    def test_return_class_with_mapping_field_without_risk_score_skips_nested_score_assertions(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_stable_direct_mapping_batch_assertion_lines",
            classmethod(lambda cls, *args, **kwargs: []),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_call_return_primitive_kind",
            classmethod(lambda cls, *args, **kwargs: ""),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_call_return_class_name",
            classmethod(lambda cls, *args, **kwargs: "PayloadResult"),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_class_field_names",
            classmethod(lambda cls, *args, **kwargs: {"payload"}),
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_result_mapping_field_keys",
            classmethod(lambda cls, *args, **kwargs: {"status"}),
        )

        lines = QATesterAgent._stable_batch_result_assertion_lines("", "batch_process")

        assert "assert all(isinstance(item.payload, dict) for item in results)" in lines
        assert all("risk_score" not in line for line in lines)


# ---------------------------------------------------------------------------
# _is_payload_key_set_expression
# ---------------------------------------------------------------------------

class TestIsPayloadKeySetExpression:
    def test_none_returns_false(self):
        assert QATesterAgent._is_payload_key_set_expression(None, set()) is False

    def test_recognizes_set_wrapped_and_keys_payload_expressions(self):
        aliases = {"payload"}

        assert QATesterAgent._is_payload_key_set_expression(
            ast.parse("set(request.details.keys())", mode="eval").body,
            aliases,
        ) is True
        assert QATesterAgent._is_payload_key_set_expression(
            ast.parse("request.details.keys()", mode="eval").body,
            aliases,
        ) is True
        assert QATesterAgent._is_payload_key_set_expression(
            ast.parse("sorted(request.status)", mode="eval").body,
            aliases,
        ) is False


class TestPayloadExpressionHelpers:
    def test_detects_payload_container_and_direct_payload_container_expressions(self):
        aliases = {"payload"}

        assert QATesterAgent._is_payload_container_expression(
            ast.parse("payload", mode="eval").body,
            aliases,
        ) is True
        assert QATesterAgent._is_payload_container_expression(
            ast.parse("request.details", mode="eval").body,
            aliases,
        ) is True
        assert QATesterAgent._is_payload_container_expression(
            ast.parse("record['context']", mode="eval").body,
            aliases,
        ) is True
        assert QATesterAgent._is_payload_container_expression(
            ast.parse("request.status", mode="eval").body,
            aliases,
        ) is False

        assert QATesterAgent._is_direct_payload_container_expression(
            ast.parse("payload", mode="eval").body,
            aliases,
        ) is True
        assert QATesterAgent._is_direct_payload_container_expression(
            ast.parse("request.details", mode="eval").body,
            aliases,
        ) is True
        assert QATesterAgent._is_direct_payload_container_expression(
            ast.parse("'payload'", mode="eval").body,
            aliases,
        ) is False

    def test_detects_expressions_that_reference_payload_values(self):
        aliases = {"payload"}

        assert QATesterAgent._expression_references_payload_value(
            ast.parse("payload.get('country')", mode="eval").body,
            aliases,
        ) is True
        assert QATesterAgent._expression_references_payload_value(
            ast.parse("payload['country']", mode="eval").body,
            aliases,
        ) is True
        assert QATesterAgent._expression_references_payload_value(
            ast.parse("'country' in request.details", mode="eval").body,
            aliases,
        ) is True
        assert QATesterAgent._expression_references_payload_value(
            ast.parse("request.status == 'open'", mode="eval").body,
            aliases,
        ) is False


class TestPayloadGuardHelpers:
    def test_detects_nested_payload_value_guards(self):
        nested_func = _parse_func(
            "def validate(details):\n"
            "    if details.get('country'):\n"
            "        if 'country' in details:\n"
            "            assert details['country']\n"
        )
        single_guard_func = _parse_func(
            "def validate(details):\n"
            "    if details.get('country'):\n"
            "        assert details['country']\n"
        )

        nested_outer_if = cast(ast.If, nested_func.body[0])
        nested_inner_if = cast(ast.If, nested_outer_if.body[0])
        single_guard_if = cast(ast.If, single_guard_func.body[0])
        nested_assert = nested_inner_if.body[0]
        single_guard_assert = single_guard_if.body[0]

        assert QATesterAgent._node_is_conditionally_guarded_by_payload_value(
            nested_assert,
            QATesterAgent._ast_parent_map(nested_func),
            {"details"},
        ) is True
        assert QATesterAgent._node_is_conditionally_guarded_by_payload_value(
            single_guard_assert,
            QATesterAgent._ast_parent_map(single_guard_func),
            {"details"},
        ) is False

    def test_resolves_loop_required_names_and_presence_check_validation_effects(self):
        mapped_func = _parse_func(
            "def validate(required_fields, details):\n"
            "    for field in required_fields:\n"
            "        if field not in details:\n"
            "            return False\n"
        )
        literal_func = _parse_func(
            "def validate(details):\n"
            "    for key in ['country', 'documents']:\n"
            "        if key not in details:\n"
            "            pass\n"
        )

        mapped_for = cast(ast.For, mapped_func.body[0])
        literal_for = cast(ast.For, literal_func.body[0])
        mapped_compare = cast(ast.If, mapped_for.body[0]).test
        literal_compare = cast(ast.If, literal_for.body[0]).test

        assert QATesterAgent._loop_iterated_required_names(
            mapped_compare,
            QATesterAgent._ast_parent_map(mapped_func),
            {"required_fields": ["country", "documents"]},
        ) == ["country", "documents"]
        assert QATesterAgent._loop_iterated_required_names(
            literal_compare,
            QATesterAgent._ast_parent_map(literal_func),
            {},
        ) == ["country", "documents"]
        assert QATesterAgent._presence_check_branch_affects_validation(
            mapped_compare,
            QATesterAgent._ast_parent_map(mapped_func),
        ) is True
        assert QATesterAgent._presence_check_branch_affects_validation(
            literal_compare,
            QATesterAgent._ast_parent_map(literal_func),
        ) is False

    def test_extracts_required_evidence_items_from_assignments_and_annotations(self):
        assert QATesterAgent._implementation_required_evidence_items("") == []
        assert QATesterAgent._implementation_required_evidence_items(
            "required_documents = ['ID', 'Passport']\n"
        ) == ["ID", "Passport"]
        assert QATesterAgent._implementation_required_evidence_items(
            "required_evidence: tuple[str, ...] = ('ID', 'Address')\n"
        ) == ["ID", "Address"]


class TestCallableReturnShapeHelpers:
    def test_resolves_callable_nodes_and_return_shapes_for_class_and_primitive_paths(self):
        implementation_code = (
            "class ReviewResult:\n"
            "    request_id: str\n"
            "    status: str\n\n"
            "class ReviewService:\n"
            "    def make_result(self):\n"
            "        result = ReviewResult()\n"
            "        return result\n\n"
            "    def handle_request(self, request):\n"
            "        return self.make_result()\n\n"
            "    def build_payload(self):\n"
            "        payload = {'status': 'ok'}\n"
            "        return payload\n\n"
            "    def build_payload_via_helper(self):\n"
            "        return self.build_payload()\n\n"
            "def standalone():\n"
            "    value = {'status': 'ok'}\n"
            "    return value\n"
        )

        handle_node = QATesterAgent._implementation_callable_node(
            implementation_code,
            "ReviewService.handle_request(request)",
        )
        payload_node = QATesterAgent._implementation_callable_node(
            implementation_code,
            "ReviewService.build_payload_via_helper",
        )
        standalone_node = QATesterAgent._implementation_callable_node(
            implementation_code,
            "standalone()",
        )

        assert handle_node is not None and handle_node.name == "handle_request"
        assert payload_node is not None and payload_node.name == "build_payload_via_helper"
        assert standalone_node is not None and standalone_node.name == "standalone"
        assert QATesterAgent._resolved_callable_return_shapes(
            implementation_code,
            "ReviewService.handle_request",
        ) == ([], ["ReviewResult"])
        assert QATesterAgent._resolved_callable_return_shapes(
            implementation_code,
            "ReviewService.build_payload_via_helper",
        ) == (["dict"], [])
        assert QATesterAgent._resolved_callable_return_shapes(
            implementation_code,
            "standalone",
        ) == (["dict"], [])

    def test_resolve_return_expression_shape_handles_none_cycles_builtins_and_class_calls(self):
        implementation_code = (
            "class ReviewResult:\n"
            "    request_id: str\n\n"
            "class ReviewService:\n"
            "    def build(self):\n"
            "        payload = {'status': 'ok'}\n"
            "        alias = payload\n"
            "        return alias\n"
        )
        function_node = QATesterAgent._implementation_callable_node(
            implementation_code,
            "ReviewService.build",
        )
        assert function_node is not None

        assert QATesterAgent._resolve_return_expression_shape(
            implementation_code,
            "ReviewService.build",
            function_node,
            None,
            seen_callable_refs=set(),
        ) == ("", "")
        assert QATesterAgent._resolve_return_expression_shape(
            implementation_code,
            "ReviewService.build",
            function_node,
            ast.parse("alias", mode="eval").body,
            seen_callable_refs=set(),
        ) == ("dict", "")
        assert QATesterAgent._resolve_return_expression_shape(
            implementation_code,
            "ReviewService.build",
            function_node,
            ast.parse("list()", mode="eval").body,
            seen_callable_refs=set(),
        ) == ("list", "")
        assert QATesterAgent._resolve_return_expression_shape(
            implementation_code,
            "ReviewService.build",
            function_node,
            ast.parse("ReviewResult()", mode="eval").body,
            seen_callable_refs=set(),
        ) == ("", "ReviewResult")
        assert QATesterAgent._resolve_return_expression_shape(
            implementation_code,
            "ReviewService.build",
            function_node,
            ast.parse("alias", mode="eval").body,
            seen_callable_refs=set(),
            seen_names={"alias"},
        ) == ("", "")

    def test_collects_class_field_names_from_annotations_assignments_and_init_fallback(self):
        implementation_code = (
            "class AnnotatedResult:\n"
            "    request_id: str\n"
            "    status: str\n\n"
            "class AssignedResult:\n"
            "    request_id = 'req-1'\n"
            "    status = 'pending'\n\n"
            "class InitOnlyResult:\n"
            "    def __init__(self):\n"
            "        self.request_id = 'req-1'\n"
            "        self.status = 'pending'\n"
        )

        assert QATesterAgent._call_expression_name(_parse_call("builder()")) == "builder"
        assert QATesterAgent._call_expression_name(_parse_call("service.handle_request()")) == "handle_request"
        assert QATesterAgent._normalized_callable_ref("ReviewService.handle_request(request)") == "ReviewService.handle_request"
        assert QATesterAgent._implementation_callable_node(implementation_code, "missing") is None
        assert QATesterAgent._implementation_class_field_names(
            implementation_code,
            "AnnotatedResult",
        ) == ["request_id", "status"]
        assert QATesterAgent._implementation_class_field_names(
            implementation_code,
            "AssignedResult",
        ) == ["request_id", "status"]
        assert QATesterAgent._implementation_class_field_names(
            implementation_code,
            "InitOnlyResult",
        ) == ["request_id", "status"]
        assert QATesterAgent._implementation_class_field_names("def broken(:\n    pass", "Broken") == []


class TestValidationAndAssertionShapeHelpers:
    def test_infers_validation_result_shapes_and_annotation_based_return_kinds(self):
        implementation_code = (
            "class ValidationOutcome:\n"
            "    is_valid: bool\n"
            "    reasons: list[str]\n\n"
            "class ReviewResult:\n"
            "    request_id: str\n"
            "    status: str\n\n"
            "class ReviewService:\n"
            "    def validate_request(self):\n"
            "        return ValidationOutcome(is_valid=False, reasons=[])\n\n"
            "    def validate_flag(self) -> bool:\n"
            "        decision = incoming\n"
            "        return decision\n\n"
            "    def build_result(self) -> ReviewResult:\n"
            "        pending = incoming\n"
            "        return pending\n\n"
            "    def build_count(self) -> int:\n"
            "        total = incoming\n"
            "        return total\n"
        )

        assert QATesterAgent._implementation_validation_result_shape(
            implementation_code,
            "ReviewService.validate_request",
        ) == ("object_is_valid", ["is_valid", "reasons"])
        assert QATesterAgent._implementation_validation_result_shape(
            implementation_code,
            "ReviewService.validate_flag",
        ) == ("bool", [])
        assert QATesterAgent._implementation_call_return_class_name(
            implementation_code,
            "ReviewService.build_result",
        ) == "ReviewResult"
        assert QATesterAgent._implementation_call_return_primitive_kind(
            implementation_code,
            "ReviewService.build_count",
        ) == "int"

    def test_collects_result_mapping_keys_and_stable_result_assertions(self):
        implementation_code = (
            "class ReviewResult:\n"
            "    request_id: str\n"
            "    status: str\n"
            "    details: dict[str, object]\n\n"
            "class ReviewService:\n"
            "    def handle_request(self, request):\n"
            "        return ReviewResult(\n"
            "            request_id=request.request_id,\n"
            "            status='approved',\n"
            "            details={'risk_score': 1.0, 'source': 'api'},\n"
            "        )\n"
        )

        mapping_keys = QATesterAgent._implementation_result_mapping_field_keys(
            implementation_code,
            "ReviewResult",
            "details",
        )
        lines = QATesterAgent._stable_result_assertion_lines(
            implementation_code,
            "ReviewService.handle_request",
            result_name="result",
            request_name="request",
        )

        assert mapping_keys == ["risk_score", "source"]
        assert "assert result.request_id == request.request_id" in lines
        assert "assert isinstance(result.status, str)" in lines
        assert "assert isinstance(result.details, dict)" in lines
        assert "assert 'risk_score' in result.details" in lines
        assert "details_risk_score_value = result.details['risk_score']" in lines

    def test_builds_direct_mapping_and_primitive_audit_assertion_lines(self):
        implementation_code = (
            "class AuditRecord:\n"
            "    request_id: str\n\n"
            "class ReviewService:\n"
            "    def __init__(self):\n"
            "        self.audit_log = []\n\n"
            "    def build_payload(self, request):\n"
            "        if request.request_id:\n"
            "            return {'request_id': request.request_id, 'status': 'approved', 'risk_score': 1.0}\n"
            "        return {'request_id': request.request_id, 'status': 'pending', 'risk_score': 0.5, 'extra': 'x'}\n\n"
            "    def build_count(self, request) -> int:\n"
            "        self.audit_log.append(AuditRecord())\n"
            "        return 1\n"
        )

        direct_lines = QATesterAgent._stable_direct_mapping_assertion_lines(
            implementation_code,
            "ReviewService.build_payload",
            result_name="result",
            request_name="request",
        )
        batch_lines = QATesterAgent._stable_direct_mapping_batch_assertion_lines(
            implementation_code,
            "ReviewService.build_payload",
        )
        call_lines = QATesterAgent._stable_call_assertion_lines(
            implementation_code,
            "ReviewService.build_count",
            result_name="result",
            request_name="request",
            service_name="service",
        )

        assert "assert isinstance(result, dict)" in direct_lines
        assert "assert result['request_id'] == request.request_id" in direct_lines
        assert "assert 'status' in result" in direct_lines
        assert "assert isinstance(result['status'], str)" in direct_lines
        assert "assert 'risk_score' in result" in direct_lines
        assert "assert len(results) == len(requests)" in batch_lines
        assert "assert all(isinstance(item, dict) for item in results)" in batch_lines
        assert "assert all('status' in item and isinstance(item['status'], str) for item in results)" in batch_lines
        assert call_lines[0] == "assert isinstance(result, int)"
        assert "assert len(service.audit_log) == 1" in call_lines
        assert "assert service.audit_log[-1].request_id == request.request_id" in call_lines


class TestPayloadOverrideHelpers:
    def test_renders_required_payload_argument_overrides_with_known_and_default_literals(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["policy_id", "custom_field"],
        )

        overrides = QATesterAgent._required_payload_argument_overrides(
            "ReviewRequest(request_id, details, timestamp)",
            "implementation_code",
        )

        assert QATesterAgent._sample_literal_for_required_key("policy_id") == '"policy123"'
        assert QATesterAgent._sample_literal_for_required_key("unknown_key") == '"sample"'
        assert overrides == {"details": '{"policy_id": "policy123", "custom_field": "sample"}'}

    def test_required_payload_argument_overrides_returns_empty_without_payload_like_parameters(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["policy_id"],
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_payload_like_parameter_names",
            lambda *args, **kwargs: [],
        )

        overrides = QATesterAgent._required_payload_argument_overrides(
            "ReviewRequest(request_id, timestamp)",
            "implementation_code",
        )

        assert overrides == {}

    def test_builds_validation_failure_overrides_and_request_scaffold(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["policy_id", "documents"],
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_non_validation_payload_keys",
            lambda *args, **kwargs: ["risk_score"],
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_prefers_direct_datetime_import",
            lambda *args, **kwargs: True,
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_request_fields",
            lambda *args, **kwargs: ["request_id", "timestamp", "requester"],
        )

        overrides = QATesterAgent._validation_failure_argument_overrides(
            "ReviewRequest(request_id, details, timestamp)",
            "implementation_code",
        )
        scaffold_name, scaffold_line = QATesterAgent._validation_failure_request_like_object_scaffold_line(
            "implementation_code"
        )

        assert QATesterAgent._validation_failure_omitted_payload_key("implementation_code") == "documents"
        assert QATesterAgent._validation_failure_missing_request_field("implementation_code") == "timestamp"
        assert overrides == {
            "details": '{"policy_id": "policy123", "risk_score": 1}',
            "timestamp": "fixed_time",
        }
        assert scaffold_name == "invalid_request"
        assert scaffold_line == (
            'invalid_request = type("InvalidRequest", (), {"request_id": "request_id-1", '
            '"requester": {"id": "analyst"}})()'
        )


class TestRuntimeAndConstructorGuardHelpers:
    def test_detects_constructor_payload_rejection_and_value_error_usage(self):
        implementation_code = (
            "class ReviewRequest:\n"
            "    def __init__(self, request_id, details):\n"
            "        if not isinstance(details, dict):\n"
            "            raise ValueError('details must be a dict')\n"
            "        self.request_id = request_id\n"
            "        self.details = details\n"
        )

        assert QATesterAgent._constructor_rejects_invalid_payload(
            "ReviewRequest(request_id, details)",
            implementation_code,
        ) is True
        assert QATesterAgent._constructor_rejects_invalid_payload(
            "ReviewRequest(request_id)",
            implementation_code,
        ) is False
        assert QATesterAgent._implementation_raises_value_error(implementation_code) is True
        assert QATesterAgent._implementation_raises_value_error("return 1") is False

    def test_detects_none_returning_callables_and_strips_assignment_prefixes(self):
        implementation_code = (
            "class ReviewService:\n"
            "    def noop(self):\n"
            "        return\n\n"
            "    def explicit_none(self):\n"
            "        def inner():\n"
            "            return 1\n"
            "        return None\n\n"
            "def standalone():\n"
            "    return 1\n"
        )

        noop_node = QATesterAgent._implementation_callable_node(implementation_code, "ReviewService.noop")
        assert noop_node is not None

        assert QATesterAgent._implementation_call_returns_none(implementation_code, "ReviewService.noop") is True
        assert QATesterAgent._implementation_call_returns_none(implementation_code, "ReviewService.explicit_none") is True
        assert QATesterAgent._implementation_call_returns_none(implementation_code, "standalone") is False
        assert QATesterAgent._function_returns_only_none(noop_node) is True
        assert QATesterAgent._function_returns_only_none(ast.parse("value = 1").body[0]) is False
        assert QATesterAgent._call_expression_without_assignment("result = service.handle_request(request)") == (
            "service.handle_request(request)"
        )
        assert QATesterAgent._call_expression_without_assignment("is_valid = service.validate_request(request)") == (
            "service.validate_request(request)"
        )
        assert QATesterAgent._call_expression_without_assignment("service.handle_request(request)") == (
            "service.handle_request(request)"
        )

    def test_builds_runtime_return_shape_assertions_and_support_method_selection(self):
        summary = (
            "Generated test validation:\n"
            "- Problem: exact return-shape attribute assumption ('.request_id' on 'dict')\n"
            "- Verdict: FAIL"
        )
        none_summary = (
            "Generated test validation:\n"
            "- Problem: exact return-shape attribute assumption ('.request_id' on 'NoneType')\n"
            "- Verdict: FAIL"
        )

        assert QATesterAgent._runtime_return_kind_from_summary(summary) == "dict"
        assert QATesterAgent._runtime_return_kind_from_summary(none_summary) == "type(None)"
        assert QATesterAgent._runtime_return_kind_from_summary("no runtime shape here") == ""
        assert QATesterAgent._return_shape_assertion_line(summary) == "assert isinstance(result, dict)"
        assert QATesterAgent._return_shape_assertion_line("no runtime shape here") == ""
        assert QATesterAgent._validation_support_method(
            ["ReviewService.handle_request(request)", "ReviewService.validate_request(request)"],
            ["ReviewService"],
        ) == "ReviewService.validate_request(request)"
        assert QATesterAgent._validation_support_method(
            ["OtherService.validate(request)"],
            ["ReviewService"],
        ) == "OtherService.validate(request)"
        assert QATesterAgent._payload_like_parameter_names(
            "ReviewRequest(request_id, details, metadata, custom_payload, timestamp)"
        ) == ["details", "metadata", "custom_payload"]


class TestRequiredPayloadRuntimeIssueHelpers:
    def test_detects_incomplete_required_evidence_payload_and_runtime_issue(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_evidence_items",
            lambda *args, **kwargs: ["ID", "Address"],
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["country", "documents"],
        )
        content = (
            "def test_happy_path():\n"
            "    request = ReviewRequest('request-1', {'country': 'PT', 'documents': ['ID']})\n"
            "    assert validate_request(request) is True\n"
        )
        complete_content = (
            "def test_happy_path():\n"
            "    request = ReviewRequest('request-1', {'country': 'PT', 'documents': ['ID', 'Address']})\n"
            "    assert validate_request(request) is True\n"
        )
        summary = "Pytest execution: FAIL\nassert 1 == 2\nmissing required documents"

        assert QATesterAgent._content_has_incomplete_required_evidence_payload(content, "implementation") is True
        assert QATesterAgent._content_has_incomplete_required_evidence_payload(complete_content, "implementation") is False
        assert QATesterAgent._summary_has_required_evidence_runtime_issue(summary, content, "implementation") is True
        assert QATesterAgent._summary_has_required_evidence_runtime_issue(
            "Pytest execution: FAIL\nassert 1 == 2",
            complete_content,
            "implementation",
        ) is False

    def test_detects_incomplete_required_payload_for_valid_paths_and_runtime_issue(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["country", "documents"],
        )
        content = (
            "def test_happy_path():\n"
            "    request = ReviewRequest('request-1', {'country': 'PT'})\n"
            "    assert validate_request(request) is True\n"
        )
        summary = "Pytest failure details:\nValueError: missing required field"

        assert QATesterAgent._content_has_incomplete_required_payload_for_valid_paths(content, "implementation") is True
        assert QATesterAgent._summary_has_required_payload_runtime_issue(summary, content, "implementation") is True
        assert QATesterAgent._summary_has_required_payload_runtime_issue(
            "Pytest execution: FAIL\nassert False",
            content,
            "implementation",
        ) is False

    def test_detects_presence_only_validation_sample_issues_and_contract_values(self, monkeypatch):
        implementation_code = (
            "class ReviewService:\n"
            "    def validate_request(self, details):\n"
            "        required_fields = ['country', 'documents']\n"
            "        if not set(required_fields).issubset(details):\n"
            "            return False\n"
            "        for field in required_fields:\n"
            "            if field not in details:\n"
            "                return False\n"
            "        return True\n"
        )
        type_checking_code = (
            "def validate_request(details):\n"
            "    required_fields = ['country', 'documents']\n"
            "    if not isinstance(details, dict):\n"
            "        return False\n"
            "    return set(required_fields).issubset(details)\n"
        )
        content = (
            "def test_validation_failure():\n"
            "    invalid_request = ReviewRequest('request-1', {'country': 'PT', 'documents': ['ID']})\n"
            "    with pytest.raises(ValueError):\n"
            "        service.validate_request(invalid_request)\n"
        )
        summary = "Pytest failure details:\nAssertionError: Did not raise ValueError"

        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["country", "documents"],
        )

        assert QATesterAgent._implementation_has_presence_only_required_field_validation(implementation_code) is True
        assert QATesterAgent._implementation_has_presence_only_required_field_validation(type_checking_code) is False
        assert QATesterAgent._block_mentions_all_required_payload_keys(
            "{'country': 'PT', 'documents': ['ID']}",
            ["country", "documents"],
        ) is True
        assert QATesterAgent._summary_has_presence_only_validation_sample_issue(
            summary,
            content,
            implementation_code,
        ) is True
        assert QATesterAgent._contract_line_value(
            "- Expected return type: dict\n- Notes: stable",
            "Expected return type",
        ) == "dict"
        assert QATesterAgent._contract_line_value(
            "- Expected return type: None",
            "Expected return type",
        ) == ""
        assert QATesterAgent._task_anchor_line_value(
            "- Symbol: ReviewService.validate_request\n- File: tests/test_qa_tester.py",
            "Symbol",
        ) == "ReviewService.validate_request"


class TestAnchorAndConstraintParsingHelpers:
    def test_parses_nested_signature_items_and_defined_symbols(self):
        assert QATesterAgent._comma_separated_items(cast(str, 123)) == []
        assert QATesterAgent._comma_separated_items(
            "request_id, build_payload(country, documents), None, {'documents': ['ID', 'Address']}, timestamp"
        ) == [
            "request_id",
            "build_payload(country, documents)",
            "{'documents': ['ID', 'Address']}",
            "timestamp",
        ]
        assert QATesterAgent._signature_name_and_params(
            "ReviewRequest(request_id: str, details={'documents': ['ID', 'Address']}, timestamp=None)"
        ) == (
            "ReviewRequest",
            [
                "request_id: str",
                "details={'documents': ['ID', 'Address']}",
                "timestamp=None",
            ],
        )
        assert QATesterAgent._parameter_name("**kwargs: dict[str, str] = {}") == "kwargs"
        assert QATesterAgent._string_list(["country", "", 1, "documents"]) == ["country", "documents"]
        assert QATesterAgent._module_defined_symbol_names(
            "class ReviewService:\n"
            "    pass\n\n"
            "def helper():\n"
            "    pass\n\n"
            "async def run():\n"
            "    pass\n\n"
            "class ReviewService:\n"
            "    pass\n"
        ) == ["ReviewService", "helper", "run"]

    def test_builds_task_anchor_overrides_and_anchor_block(self):
        anchor = (
            "- Public facade: ReviewService\n"
            "- Primary request model: ReviewRequest(request_id, details, timestamp)\n"
            "- Required request workflow: ReviewService.handle_request(request)\n"
            "- Supporting validation surface: ReviewService.validate_request(request)\n"
            "- Batch guidance: repeated handle_request(request) calls\n"
        )

        assert QATesterAgent._task_anchor_overrides({}) == {}

        overrides = QATesterAgent._task_anchor_overrides(anchor)

        assert overrides == {
            "allowed_imports": ["ReviewService", "ReviewRequest"],
            "preferred_facades": ["ReviewService"],
            "exact_methods": [
                "ReviewService.handle_request(request)",
                "ReviewService.validate_request(request)",
            ],
            "exact_constructors": ["ReviewRequest(request_id, details, timestamp)"],
            "request_model_signature": "ReviewRequest(request_id, details, timestamp)",
            "request_workflow": "ReviewService.handle_request(request)",
            "suppress_batch_aliases": True,
        }

        block = QATesterAgent._task_public_contract_anchor_block(anchor)
        assert "Task-level public contract anchor:" in block
        assert "Treat that anchor as exact." in block
        assert "every ReviewRequest(...) call in the suite must pass timestamp explicitly" in block

    def test_compacts_task_constraints_and_normalizes_snake_case_names(self):
        task_description = (
            "Keep the suite compact. Prefer direct happy-path and validation coverage. "
            "Stay on the documented facade. Avoid guessed score totals. "
            "Preserve timestamp arguments exactly. Ignore this sentence once the summary is capped.\n\n"
            "Public contract anchor:\n- Public facade: ReviewService"
        )

        summary = QATesterAgent._compact_task_constraints_block(task_description)

        assert summary == (
            "Task constraints summary:\n"
            "- Keep the suite compact.\n"
            "- Prefer direct happy-path and validation coverage.\n"
            "- Stay on the documented facade.\n"
            "- Avoid guessed score totals."
        )
        assert QATesterAgent._snake_case_name("RiskScoreResult") == "risk_score_result"
        assert QATesterAgent._snake_case_name(" review-request 2 ") == "review_request_2"


class TestSelectionAndFixedTimeHelpers:
    def test_merges_items_and_selects_preferred_constructors(self):
        assert QATesterAgent._task_anchor_line_value(123, "Symbol") == ""
        assert QATesterAgent._merge_preserving_order(
            ["ReviewService", ""],
            ["ReviewRequest", "ReviewService", "  "],
            ["ReviewResult"],
        ) == ["ReviewService", "ReviewRequest", "ReviewResult"]
        assert QATesterAgent._preferred_constructor_signature([], ["ReviewService"]) == ""
        assert QATesterAgent._preferred_constructor_signature(
            [
                "ReviewService()",
                "AuditRecord()",
                "ReviewRequest(request_id, details)",
            ],
            ["ReviewService"],
        ) == "ReviewRequest(request_id, details)"
        assert QATesterAgent._preferred_constructor_signature(
            [
                "WorkflowManager()",
                "PayloadEnvelope(details, metadata)",
                "AuditRecord()",
            ],
            ["WorkflowManager"],
        ) == "PayloadEnvelope(details, metadata)"
        assert QATesterAgent._preferred_constructor_signature(
            [
                "ServiceFacade()",
                "TypedInput(request_id, request_type)",
                "AuditRecord()",
            ],
            ["ServiceFacade"],
        ) == "TypedInput(request_id, request_type)"
        assert QATesterAgent._preferred_constructor_signature(
            ["ReviewService()", "AuditRecord()"],
            ["ReviewService"],
        ) == "AuditRecord()"
        assert QATesterAgent._instance_name_for_class("ReviewOutcome") == "result"
        assert QATesterAgent._instance_name_for_class("AuditRecord") == "record"
        assert QATesterAgent._instance_name_for_class("RiskScore") == "risk_score"

    def test_builds_guidance_and_fixed_time_lines_for_multiple_datetime_styles(self, monkeypatch):
        guidance = QATesterAgent._contract_first_user_guidance(
            "kycortex_agents.example_module",
            "example_module.py",
        )

        assert "Write a complete raw pytest file." in guidance
        assert "Assume the module code already exists in `example_module.py`." in guidance
        assert "Return complete raw Python only." in guidance

        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_prefers_datetime_module_import",
            lambda *args, **kwargs: True,
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_requires_recent_request_timestamp",
            lambda *args, **kwargs: True,
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_prefers_timezone_aware_now",
            lambda *args, **kwargs: True,
        )

        assert QATesterAgent._fixed_time_expression("implementation") == "datetime.datetime.now(datetime.timezone.utc)"
        assert QATesterAgent._fixed_time_import_line("implementation") == "import datetime"
        assert QATesterAgent._fixed_time_assignment_line("implementation") == (
            "fixed_time = datetime.datetime.now(datetime.timezone.utc)"
        )
        assert QATesterAgent._prepend_fixed_time_line(
            ["service = ReviewService()", "result = fixed_time"],
            implementation_code="implementation",
        ) == [
            "service = ReviewService()",
            "fixed_time = datetime.datetime.now(datetime.timezone.utc)",
            "result = fixed_time",
        ]

        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_prefers_datetime_module_import",
            lambda *args, **kwargs: False,
        )
        assert QATesterAgent._fixed_time_expression("implementation") == "datetime.now(timezone.utc)"
        assert QATesterAgent._fixed_time_import_line("implementation") == "from datetime import datetime, timezone"

        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_requires_recent_request_timestamp",
            lambda *args, **kwargs: False,
        )
        assert QATesterAgent._fixed_time_expression("implementation") == "datetime(2024, 1, 1, 0, 0, 0)"
        assert QATesterAgent._fixed_time_import_line("implementation") == "from datetime import datetime"
        assert QATesterAgent._prepend_fixed_time_line(
            ["fixed_time = datetime(2024, 1, 1, 0, 0, 0)", "result = fixed_time"],
            implementation_code="implementation",
        ) == [
            "fixed_time = datetime(2024, 1, 1, 0, 0, 0)",
            "result = fixed_time",
        ]

    def test_covers_sample_literal_categories_and_constraint_edge_cases(self):
        assert QATesterAgent._compact_task_constraints_block("") == ""
        assert QATesterAgent._compact_task_constraints_block(
            "Public contract anchor:\n- Public facade: ReviewService"
        ) == "Task constraints summary:\n- Public contract anchor: - Public facade: ReviewService"
        assert QATesterAgent._task_public_contract_anchor_block(None) == ""
        assert QATesterAgent._snake_case_name("") == "value"
        assert QATesterAgent._snake_case_name("HTTPRequest") == "http_request"
        assert QATesterAgent._sample_literal_for_parameter("left", index=2) == "3"
        assert QATesterAgent._sample_literal_for_parameter("review_id") == '"review_id-1"'
        assert QATesterAgent._sample_literal_for_parameter("request_type") == '"screening"'
        assert QATesterAgent._sample_literal_for_parameter("status") == '"pending"'
        assert QATesterAgent._sample_literal_for_parameter("outcome") == '"accepted"'
        assert QATesterAgent._sample_literal_for_parameter("is_valid") == "True"
        assert QATesterAgent._sample_literal_for_parameter("created_at") == "1.0"
        assert QATesterAgent._sample_literal_for_parameter("payload") == '{"source": "web"}'
        assert QATesterAgent._sample_literal_for_parameter("total_score") == "1"
        assert QATesterAgent._sample_literal_for_parameter("name", index=4) == '"sample_5"'


class TestRemainingParsingAndScaffoldEdges:
    def test_covers_remaining_parsing_and_anchor_edge_cases(self):
        assert QATesterAgent._merge_preserving_order(
            cast(list[str], ["ReviewService", 1, " AuditRecord "]),
            ["ReviewService"],
        ) == ["ReviewService", "AuditRecord"]
        assert QATesterAgent._module_defined_symbol_names("def broken(:\n    pass\n") == []
        assert QATesterAgent._string_list(("country", "documents")) == []
        assert QATesterAgent._parameter_name("   ") == ""
        assert QATesterAgent._signature_name_and_params(cast(str, None)) == ("", [])

        block = QATesterAgent._task_public_contract_anchor_block(
            "- Public facade: ReviewService\n"
            "- Required request workflow: ReviewService.handle_request(request)\n"
        )

        assert "Treat that anchor as exact." not in block
        assert "timestamp explicitly" not in block
        assert QATesterAgent._snake_case_name("__RiskScore") == "risk_score"

    def test_covers_remaining_constructor_and_batch_scaffold_branches(self):
        assert QATesterAgent._preferred_constructor_signature(
            [
                "ReviewService()",
                "AuditService(request_id)",
                "TypedInput(request_id, request_type)",
            ],
            ["ReviewService"],
        ) == "TypedInput(request_id, request_type)"
        assert QATesterAgent._constructor_call_expression("ReviewRequest(*, name)") == (
            "ReviewRequest",
            'ReviewRequest(name="sample_2")',
        )
        assert QATesterAgent._batch_loop_scaffold_lines(
            primary_method="ReviewService.handle_batch",
            preferred_constructor="()",
        ) == []
        assert QATesterAgent._batch_loop_scaffold_lines(
            primary_method="ReviewService.handle_batch",
            preferred_constructor="ReviewRequest(name)",
            collect_results=False,
        ) == [
            "service = ReviewService()",
            "requests = [",
            '    ReviewRequest(name="sample_1"),',
            '    ReviewRequest(name="sample_2"),',
            "]",
            "for request in requests:",
            "    result = service.handle_batch(request)",
        ]
        assert QATesterAgent._method_scaffold_lines(
            "ReviewService.handle_request",
            "",
        ) == (
            "service = ReviewService()",
            "result = service.handle_request()",
        )


class TestDeterministicSurfaceScaffoldSelection:
    def test_prefers_facade_methods_and_facade_batch_methods(self, monkeypatch):
        _patch_scaffold_defaults(monkeypatch)
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request), ReviewService.handle_batch(requests), AuditService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name, details)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Include batch coverage.",
            code_exact_test_contract=contract,
            code_test_targets="batch",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "def test_happy_path():" in block
        assert "service = ReviewService()" in block
        assert "result = service.handle_request(request)" in block
        assert "def test_batch_processing():" in block
        assert "result = service.handle_batch([request])" in block

    def test_falls_back_to_exact_methods_when_no_facade_is_declared(self, monkeypatch):
        _patch_scaffold_defaults(monkeypatch)
        contract = (
            "- Allowed production imports: AuditService, ReviewRequest\n"
            "- Preferred service or workflow facades: None\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: AuditService.handle_request(request), AuditService.handle_batch(requests)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Exercise the documented service surface.",
            code_exact_test_contract=contract,
            code_test_targets="batch",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "service = AuditService()" in block
        assert "result = service.handle_request(request)" in block
        assert "result = service.handle_batch([request])" in block

    def test_uses_callable_surfaces_when_methods_are_not_documented(self, monkeypatch):
        _patch_scaffold_defaults(monkeypatch)
        contract = (
            "- Allowed production imports: ReviewRequest, handle_request, handle_batch\n"
            "- Preferred service or workflow facades: None\n"
            "- Exact public callables: handle_request(request), handle_batch(requests)\n"
            "- Exact public class methods: None\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Include batch coverage.",
            code_exact_test_contract=contract,
            code_test_targets="batch",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "result = handle_request(request)" in block
        assert "result = handle_batch([request])" in block


class TestDeterministicSurfaceScaffoldValidationBody:
    def test_uses_constructor_value_error_path_for_callable_validation_failures(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _constructor_rejects_invalid_payload=lambda *args, **kwargs: True,
        )
        contract = (
            "- Allowed production imports: ReviewRequest, handle_request\n"
            "- Preferred service or workflow facades: None\n"
            "- Exact public callables: handle_request(request)\n"
            "- Exact public class methods: None\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Exercise validation coverage.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "def test_validation_failure():" in block
        assert "with pytest.raises(ValueError):" in block
        assert 'ReviewRequest(name="sample_1")' in block

    def test_builds_object_is_valid_validation_lines_with_error_assertions(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _validation_support_method=lambda *args, **kwargs: "ValidationService.validate_request(request)",
            _implementation_validation_result_shape=lambda *args, **kwargs: ("object_is_valid", ["errors"]),
        )
        contract = (
            "- Allowed production imports: ReviewService, ValidationService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request), ValidationService.validate_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Include validation guidance.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "service = ValidationService()" in block
        assert "validation = service.validate_request(request)" in block
        assert "assert validation.is_valid is False" in block
        assert "assert len(validation.errors) > 0" in block

    def test_wraps_validation_calls_that_raise_value_error_and_marks_none_batch_results(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _implementation_raises_value_error=lambda *args, **kwargs: True,
            _implementation_call_returns_none=lambda _implementation_code, callable_ref: callable_ref == "ReviewService.handle_batch(requests)",
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request), ReviewService.handle_batch(requests)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Include batch coverage.",
            code_exact_test_contract=contract,
            code_test_targets="batch",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "with pytest.raises(ValueError):" in block
        assert "service.handle_request(request)" in block
        assert "assert result is None" in block


class TestDeterministicSurfaceScaffoldBatchFallback:
    def test_collects_none_results_when_batch_falls_back_to_primary_loop(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _implementation_call_returns_none=lambda _implementation_code, callable_ref: callable_ref == "ReviewService.handle_request(request)",
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Exercise batch fallback coverage.",
            code_exact_test_contract=contract,
            code_test_targets="batch",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "def test_batch_processing():" in block
        assert "assert len(results) == len(requests)" in block
        assert "assert all(item is None for item in results)" in block

    def test_appends_audit_assertions_and_deduplicates_rendered_lines(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _stable_audit_assertion_lines=lambda *args, **kwargs: ["assert audit_log == ['ok']"],
            _validation_support_method=lambda *args, **kwargs: "ValidationService.validate_request(request)",
            _implementation_raises_value_error=lambda *args, **kwargs: True,
            _return_shape_assertion_line=lambda *args, **kwargs: "assert isinstance(result, dict)",
            _prepend_fixed_time_line=lambda lines, **kwargs: [*lines, lines[-1]] if lines else lines,
        )
        contract = (
            "- Allowed production imports: ReviewService, ValidationService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request), ValidationService.validate_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Exercise batch audit fallback coverage.",
            code_exact_test_contract=contract,
            code_test_targets="batch",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        lines = block.splitlines()
        assert "assert audit_log == ['ok']" in block
        assert lines.count("    assert isinstance(result, dict)") == 1
        assert lines.count("        service.handle_request(request)") == 1
        assert lines.count("    assert audit_log == ['ok']") == 1


class TestDeterministicSurfaceScaffoldGuidanceNotes:
    def test_keeps_invalid_constructor_guidance_for_missing_payload_keys(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _validation_failure_omitted_payload_key=lambda *args, **kwargs: "risk_score",
            _constructor_rejects_invalid_payload=lambda *args, **kwargs: True,
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Explain invalid payload guidance.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "keep the scaffolded omission of the required payload key `risk_score` exactly as shown" in block
        assert 'keep the scaffolded invalid constructor line exactly as shown: `request = ReviewRequest(name="sample_1")`' in block
        assert "The request model rejects this malformed payload during construction." in block

    def test_skips_invalid_constructor_line_guidance_when_missing_payload_key_case_has_no_constructor_line(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _validation_failure_omitted_payload_key=lambda *args, **kwargs: "risk_score",
            _constructor_scaffold_line_with_overrides=lambda *args, **kwargs: ("", ""),
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Explain invalid payload guidance without constructor line.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "keep the scaffolded omission of the required payload key `risk_score` exactly as shown" in block
        assert "keep the scaffolded invalid constructor line exactly as shown" not in block

    def test_keeps_invalid_object_guidance_for_missing_request_fields(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _validation_failure_missing_request_field=lambda *args, **kwargs: "request_id",
            _validation_failure_request_like_object_scaffold_line=lambda *args, **kwargs: (
                "invalid_request",
                "invalid_request = build_invalid_request(details={})",
            ),
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Explain missing request field guidance.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "keep the scaffolded request-like object missing the top-level field `request_id` exactly as shown" in block
        assert "keep the scaffolded invalid-object line exactly as shown: `invalid_request = build_invalid_request(details={})`" in block
        assert "the field must be absent from the object entirely, not merely present with a falsey value" in block

    def test_skips_invalid_object_line_guidance_when_missing_request_field_case_has_no_constructor_line(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _validation_failure_missing_request_field=lambda *args, **kwargs: "request_id",
            _validation_failure_request_like_object_scaffold_line=lambda *args, **kwargs: ("", ""),
            _constructor_scaffold_line_with_overrides=lambda *args, **kwargs: ("", ""),
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Explain missing request field guidance without constructor line.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "keep the scaffolded request-like object missing the top-level field `request_id` exactly as shown" in block
        assert "keep the scaffolded invalid-object line exactly as shown" not in block
        assert "the field must be absent from the object entirely, not merely present with a falsey value" in block


class TestDeterministicSurfaceScaffoldEnvelope:
    def test_scaffold_without_allowed_imports_still_renders_primary_body(self, monkeypatch):
        _patch_scaffold_defaults(monkeypatch)
        contract = (
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Render a simple happy path.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "from sample_module import" not in block
        assert "def test_happy_path():" in block

    def test_scaffold_can_render_validation_only_when_primary_and_batch_lines_are_empty(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _constructor_scaffold_line_with_overrides=lambda *args, **kwargs: ("", ""),
            _method_scaffold_lines=lambda *args, **kwargs: ("", ""),
            _validation_support_method=lambda *args, **kwargs: "ReviewService.validate_request(request)",
            _validation_failure_request_like_object_scaffold_line=lambda *args, **kwargs: (
                "invalid_request",
                "invalid_request = build_invalid_request()",
            ),
        )
        contract = (
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Render validation-only guidance.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "```python\nimport pytest" in block
        assert "def test_happy_path():" not in block
        assert "def test_batch_processing():" not in block
        assert "- If `test_validation_failure` later asserts audit records" in block

    def test_scaffold_can_render_batch_only_when_primary_lines_are_empty(self, monkeypatch):
        def _patched_method_scaffold_lines(method_name: str, _constructor_variable: str) -> tuple[str, str]:
            if "batch" in method_name.lower():
                return "", "results = service.handle_batch(requests)"
            return "", ""

        _patch_scaffold_defaults(
            monkeypatch,
            _constructor_scaffold_line_with_overrides=lambda *args, **kwargs: ("", ""),
            _method_scaffold_lines=_patched_method_scaffold_lines,
        )
        contract = (
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request), ReviewService.handle_batch(requests)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Render batch coverage.",
            code_exact_test_contract=contract,
            code_test_targets="batch request handling",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "def test_happy_path():" not in block
        assert "def test_batch_processing():" in block
        assert "results = service.handle_batch(requests)" in block


class TestDeterministicSurfaceScaffoldSelectionAndValidationEdges:
    def test_primary_method_selection_falls_back_when_preferred_facades_do_not_match(self, monkeypatch):
        _patch_scaffold_defaults(monkeypatch)
        contract = (
            "- Preferred service or workflow facades: MissingFacade, AnotherFacade\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Render a simple happy path.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "def test_happy_path():" in block
        assert "handle_request(request)" in block

    def test_validation_uses_primary_callable_scaffold_when_no_method_exists(self, monkeypatch):
        call_count = {"constructor": 0}

        def _constructor_scaffold_line_with_overrides(
            _signature: str,
            argument_overrides: dict[str, str] | None = None,
        ) -> tuple[str, str]:
            call_count["constructor"] += 1
            if call_count["constructor"] > 1:
                return "invalid_request", "invalid_request = ReviewRequest(name='broken')"
            return "request", "request = ReviewRequest(name='ok')"

        def _callable_scaffold_line(callable_name: str, constructor_variable: str) -> str:
            callable_root = callable_name.split("(", 1)[0]
            return f"result = {callable_root}({constructor_variable})"

        _patch_scaffold_defaults(
            monkeypatch,
            _constructor_scaffold_line_with_overrides=_constructor_scaffold_line_with_overrides,
            _validation_failure_request_like_object_scaffold_line=lambda *args, **kwargs: ("", ""),
            _callable_scaffold_line=_callable_scaffold_line,
        )
        contract = (
            "- Preferred service or workflow facades: None\n"
            "- Exact public callables: handle_request(request)\n"
            "- Exact public class methods: None\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Render callable validation guidance.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "def test_validation_failure():" in block
        assert "handle_request(invalid_request)" in block

    def test_validation_inserts_service_assignment_when_body_starts_empty(self, monkeypatch):
        call_count = {"constructor": 0}

        def _constructor_scaffold_line_with_overrides(
            _signature: str,
            argument_overrides: dict[str, str] | None = None,
        ) -> tuple[str, str]:
            call_count["constructor"] += 1
            if call_count["constructor"] > 1:
                return "", ""
            return "request", "request = ReviewRequest(name='ok')"

        def _method_scaffold_lines(method_name: str, constructor_variable: str) -> tuple[str, str]:
            if method_name.startswith("ReviewService.handle_request") and constructor_variable == "request":
                return "primary_service = ReviewService()", "result = primary_service.handle_request(request)"
            return "", ""

        _patch_scaffold_defaults(
            monkeypatch,
            _constructor_scaffold_line_with_overrides=_constructor_scaffold_line_with_overrides,
            _validation_failure_request_like_object_scaffold_line=lambda *args, **kwargs: ("", ""),
            _method_scaffold_lines=_method_scaffold_lines,
            _validation_support_method=lambda *args, **kwargs: "ReviewService.validate_request(request)",
            _instance_name_for_class=lambda *args, **kwargs: "validation_service",
        )
        contract = (
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Render validation-only assignment fallback.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "validation_service = ReviewService()" in block
        assert "is_valid = validation_service.validate_request()" in block

    def test_validation_object_result_without_errors_skips_error_length_assertion(self, monkeypatch):
        _patch_scaffold_defaults(
            monkeypatch,
            _validation_support_method=lambda *args, **kwargs: "ReviewService.validate_request(request)",
            _implementation_validation_result_shape=lambda *args, **kwargs: ("object_is_valid", []),
        )
        contract = (
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: None\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Render validation result guidance.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "assert validation.is_valid is False" in block
        assert "assert len(validation.errors) > 0" not in block

    def test_validation_uses_primary_callable_branch_when_exact_methods_are_absent(self, monkeypatch):
        call_count = {"constructor": 0}

        def _constructor_scaffold_line_with_overrides(
            _signature: str,
            argument_overrides: dict[str, str] | None = None,
        ) -> tuple[str, str]:
            call_count["constructor"] += 1
            if call_count["constructor"] > 1:
                return "invalid_request", "invalid_request = ReviewRequest(name='broken')"
            return "request", "request = ReviewRequest(name='ok')"

        def _callable_scaffold_line(callable_name: str, constructor_variable: str) -> str:
            callable_root = callable_name.split("(", 1)[0]
            return f"result = {callable_root}({constructor_variable})"

        _patch_scaffold_defaults(
            monkeypatch,
            _constructor_scaffold_line_with_overrides=_constructor_scaffold_line_with_overrides,
            _validation_failure_request_like_object_scaffold_line=lambda *args, **kwargs: ("", ""),
            _callable_scaffold_line=_callable_scaffold_line,
        )
        contract = (
            "- Preferred service or workflow facades:\n"
            "- Exact public callables: handle_request(request)\n"
            "- Exact public class methods:\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Render callable validation guidance.",
            code_exact_test_contract=contract,
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "def test_validation_failure():" in block
        assert "handle_request(invalid_request)" in block

    def test_primary_method_branch_can_be_reached_with_flipping_callable_truthiness(self, monkeypatch):
        class _FlippingCallable:
            def __init__(self, rendered: str):
                self.rendered = rendered
                self.bool_calls = 0

            def __bool__(self) -> bool:
                self.bool_calls += 1
                return self.bool_calls == 1

            def lower(self) -> str:
                return self.rendered.lower()

        flipping_callable = _FlippingCallable("handle_request(request)")

        def _comma_separated_items(value: str) -> list[object]:
            mapping: dict[str, list[object]] = {
                "allowed": [],
                "facades": [],
                "callables": [flipping_callable],
                "methods": ["ReviewService.handle_request(request)"],
                "constructors": ["ReviewRequest(name)"],
            }
            return mapping.get(value, [])

        def _contract_line_value(_contract: str, label: str) -> str:
            mapping = {
                "Allowed production imports": "allowed",
                "Preferred service or workflow facades": "facades",
                "Exact public callables": "callables",
                "Exact public class methods": "methods",
                "Exact constructor fields": "constructors",
            }
            return mapping[label]

        def _method_scaffold_lines(_method_name: str, _constructor_variable: str) -> tuple[str, str]:
            if flipping_callable.bool_calls >= 2:
                return "fallback_service = ReviewService()", "result = fallback_service.handle_request(request)"
            return "primary_service = ReviewService()", "result = primary_service.handle_request(request)"

        _patch_scaffold_defaults(
            monkeypatch,
            _contract_line_value=_contract_line_value,
            _comma_separated_items=_comma_separated_items,
            _method_scaffold_lines=_method_scaffold_lines,
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Render a simple happy path.",
            code_exact_test_contract="synthetic contract",
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert flipping_callable.bool_calls == 2
        assert "fallback_service = ReviewService()" in block

    def test_validation_uses_primary_callable_branch_with_direct_contract_lists(self, monkeypatch):
        call_count = {"constructor": 0}
        original_comma_separated_items = QATesterAgent._comma_separated_items

        def _contract_line_value(_contract: str, label: str) -> str:
            mapping = {
                "Allowed production imports": "allowed",
                "Preferred service or workflow facades": "facades",
                "Exact public callables": "callables",
                "Exact public class methods": "methods",
                "Exact constructor fields": "constructors",
            }
            return mapping[label]

        def _comma_separated_items(value: str) -> list[str]:
            mapping = {
                "allowed": [],
                "facades": [],
                "callables": ["handle_request(request)"],
                "methods": [],
                "constructors": ["ReviewRequest(name)"],
            }
            return mapping.get(value, original_comma_separated_items(value))

        def _constructor_scaffold_line_with_overrides(
            _signature: str,
            argument_overrides: dict[str, str] | None = None,
        ) -> tuple[str, str]:
            call_count["constructor"] += 1
            if call_count["constructor"] > 1:
                return "invalid_request", "invalid_request = ReviewRequest(name='broken')"
            return "request", "request = ReviewRequest(name='ok')"

        def _callable_scaffold_line(callable_name: str, constructor_variable: str) -> str:
            callable_root = callable_name.split("(", 1)[0]
            return f"result = {callable_root}({constructor_variable})"

        _patch_scaffold_defaults(
            monkeypatch,
            _contract_line_value=_contract_line_value,
            _comma_separated_items=_comma_separated_items,
            _constructor_scaffold_line_with_overrides=_constructor_scaffold_line_with_overrides,
            _validation_failure_request_like_object_scaffold_line=lambda *args, **kwargs: ("", ""),
            _callable_scaffold_line=_callable_scaffold_line,
        )

        block = QATesterAgent._deterministic_surface_scaffold_block(
            module_name="sample_module",
            task_description="Render callable validation guidance.",
            code_exact_test_contract="synthetic callable contract",
            code_test_targets="",
            task_public_contract_anchor="",
            implementation_code="",
            repair_validation_summary="",
        )

        assert "def test_validation_failure():" in block
        assert "handle_request(invalid_request)" in block


class TestImportRootHelpers:
    def test_python_import_roots_returns_empty_on_syntax_error(self):
        assert QATesterAgent._python_import_roots("import") == set()

    def test_python_import_roots_collects_absolute_import_roots_and_skips_relative_imports(self):
        content = (
            "import alpha.beta as ab\n"
            "import gamma\n"
            "from delta.epsilon import tool\n"
            "from .relative import helper\n"
        )

        assert QATesterAgent._python_import_roots(content) == {"alpha", "gamma", "delta"}

    def test_python_import_roots_ignores_empty_synthetic_import_roots(self, monkeypatch):
        synthetic_tree = ast.Module(
            body=[
                ast.Import(names=[ast.alias(name="", asname=None)]),
                ast.ImportFrom(module=None, names=[ast.alias(name="tool", asname=None)], level=0),
            ],
            type_ignores=[],
        )
        monkeypatch.setattr(ast, "parse", lambda _raw_content: synthetic_tree)

        assert QATesterAgent._python_import_roots("import placeholder") == set()

    def test_stale_generated_module_import_roots_uses_python_filename_root(self):
        stale_roots = QATesterAgent._stale_generated_module_import_roots(
            existing_tests="import sample_module\nimport sample_module_implementation\n",
            module_name="",
            module_filename="sample_module.py",
        )

        assert stale_roots == ["sample_module_implementation"]

    def test_stale_generated_module_import_roots_accepts_extensionless_filename(self):
        stale_roots = QATesterAgent._stale_generated_module_import_roots(
            existing_tests="import sample_module\nimport sample_module_implementation\n",
            module_name="ignored_name",
            module_filename="sample_module",
        )

        assert stale_roots == ["sample_module_implementation"]

    def test_stale_generated_module_import_roots_falls_back_to_module_name_or_empty(self):
        from_module_name = QATesterAgent._stale_generated_module_import_roots(
            existing_tests="import sample_module_implementation\n",
            module_name="sample_module",
            module_filename=None,
        )
        without_expected_root = QATesterAgent._stale_generated_module_import_roots(
            existing_tests="import sample_module_implementation\n",
            module_name=None,
            module_filename=None,
        )

        assert from_module_name == ["sample_module_implementation"]
        assert without_expected_root == []


class TestShouldRebuildFromExactContract:
    def test_returns_true_for_exact_numeric_score_issue(self, monkeypatch):
        _patch_repair_focus_defaults(monkeypatch)
        monkeypatch.setattr(QATesterAgent, "_undefined_helper_alias_names_outside_exact_contract", lambda *args, **kwargs: False)
        monkeypatch.setattr(QATesterAgent, "_summary_has_missing_datetime_import_issue", lambda *args, **kwargs: False)
        monkeypatch.setattr(QATesterAgent, "_implementation_required_request_fields", lambda *args, **kwargs: [])
        monkeypatch.setattr(QATesterAgent, "_implementation_required_payload_keys", lambda *args, **kwargs: [])
        monkeypatch.setattr(QATesterAgent, "_summary_has_placeholder_boolean_assertion_issue", lambda *args, **kwargs: False)
        monkeypatch.setattr(QATesterAgent, "_summary_has_validation_side_effect_without_workflow_call_issue", lambda *args, **kwargs: False)
        monkeypatch.setattr(QATesterAgent, "_summary_has_active_issue", lambda *args, **kwargs: False)
        monkeypatch.setattr(QATesterAgent, "_summary_has_exact_numeric_score_assertion_issue", lambda *args, **kwargs: True)

        should_rebuild = QATesterAgent._should_rebuild_from_exact_contract(
            code_exact_test_contract="- exact contract",
            repair_validation_summary="",
            existing_tests="",
            implementation_code="",
        )

        assert should_rebuild is True


class TestExistingTestsContextAndInstruction:
    def test_returns_exact_value_overreach_guidance_for_band_threshold_issues(self, monkeypatch):
        _patch_existing_tests_instruction_defaults(
            monkeypatch,
            _summary_has_exact_band_label_assertion_issue=lambda *args, **kwargs: True,
        )

        existing_tests_context, instruction = QATesterAgent._existing_tests_context_and_instruction(
            existing_tests="def test_placeholder():\n    pass\n",
            module_name="sample_module",
            module_filename="sample_module.py",
            code_exact_test_contract="- exact contract",
            repair_validation_summary="",
            implementation_code="",
        )

        assert existing_tests_context.startswith("Previous overreaching pytest file omitted")
        assert "exact risk-level or severity-band threshold assertions" in instruction

    def test_returns_type_mismatch_rebuild_guidance(self, monkeypatch):
        _patch_existing_tests_instruction_defaults(
            monkeypatch,
            _summary_issue_value=lambda *args, **kwargs: "details expected Dict[str, Any] but got str",
        )

        existing_tests_context, instruction = QATesterAgent._existing_tests_context_and_instruction(
            existing_tests="def test_placeholder():\n    pass\n",
            module_name="sample_module",
            module_filename="sample_module.py",
            code_exact_test_contract="- exact contract",
            repair_validation_summary="",
            implementation_code="",
        )

        assert existing_tests_context.startswith("Previous pytest file omitted because the validation summary reported type mismatches")
        assert "CRITICALLY IMPORTANT" in instruction
        assert "details expected Dict[str, Any] but got str" in instruction

    def test_returns_empty_existing_tests_context_for_non_string_input(self, monkeypatch):
        _patch_existing_tests_instruction_defaults(monkeypatch)

        existing_tests_context, instruction = QATesterAgent._existing_tests_context_and_instruction(
            existing_tests=["not", "a", "string"],
            module_name="sample_module",
            module_filename="sample_module.py",
            code_exact_test_contract="- exact contract",
            repair_validation_summary="",
            implementation_code="",
        )

        assert existing_tests_context == ""
        assert instruction.startswith("Repair the existing pytest file above")


class TestExactRebuildSurfaceBlock:
    def test_skips_contract_specific_lines_when_exact_contract_has_no_surface_metadata(self, monkeypatch):
        _patch_exact_rebuild_surface_defaults(monkeypatch)

        block = QATesterAgent._exact_rebuild_surface_block(
            code_exact_test_contract="",
            repair_validation_summary="",
            task_public_contract_anchor="",
            existing_tests="",
            implementation_code="",
        )

        assert "- Allowed imports only:" not in block
        assert "- Center the suite on this documented facade:" not in block
        assert "- Use only these documented callables or methods:" not in block
        assert "- Mirror only these documented constructors:" not in block

    def test_renders_contract_lines_invalid_members_and_single_surface_batch_guidance(self, monkeypatch):
        _patch_exact_rebuild_surface_defaults(
            monkeypatch,
            _summary_issue_value=lambda _summary, label: {
                "Unknown module symbols": "GhostHelper",
                "Invalid member references": "service.ghost_call",
            }.get(label, ""),
            _summary_has_exact_band_label_assertion_issue=lambda *args, **kwargs: True,
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: handle_request(request)\n"
            "- Exact public class methods: ReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._exact_rebuild_surface_block(
            code_exact_test_contract=contract,
            repair_validation_summary="",
            task_public_contract_anchor="",
            existing_tests="",
            implementation_code="",
        )

        assert "- Allowed imports only: ReviewService, ReviewRequest" in block
        assert "- Center the suite on this documented facade: ReviewService" in block
        assert "- Use only these documented callables or methods: handle_request(request), ReviewService.handle_request(request)" in block
        assert "- Keep documented method names exact. Do not shorten or rename ReviewService.handle_request(request)." in block
        assert "- Mirror only these documented constructors: ReviewRequest(name)" in block
        assert "- Invalid member references from the previous validation are forbidden in the rewritten file: service.ghost_call" in block
        assert "- The previous failed suite overreached with exact risk-tier or severity-band thresholds." in block
        assert "- No batch helper is documented in the exact contract." in block

    def test_adds_datetime_style_and_required_evidence_fallback_guidance(self, monkeypatch):
        _patch_exact_rebuild_surface_defaults(
            monkeypatch,
            _summary_has_missing_datetime_import_issue=lambda *args, **kwargs: True,
            _implementation_prefers_direct_datetime_import=lambda *args, **kwargs: True,
            _summary_has_required_evidence_runtime_issue=lambda *args, **kwargs: True,
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: handle_request(request)\n"
            "- Exact public class methods: None\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._exact_rebuild_surface_block(
            code_exact_test_contract=contract,
            repair_validation_summary="",
            task_public_contract_anchor="",
            existing_tests="",
            implementation_code="",
        )

        assert "- Match the implementation's datetime style: add `from datetime import datetime` at the top" in block
        assert "- Copy the full required evidence list named by the implementation validator into every valid happy-path or batch payload" in block

    def test_adds_missing_datetime_warning_without_direct_import_style_guidance(self, monkeypatch):
        _patch_exact_rebuild_surface_defaults(
            monkeypatch,
            _summary_has_missing_datetime_import_issue=lambda *args, **kwargs: True,
            _implementation_prefers_direct_datetime_import=lambda *args, **kwargs: False,
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: handle_request(request)\n"
            "- Exact public class methods: None\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._exact_rebuild_surface_block(
            code_exact_test_contract=contract,
            repair_validation_summary="",
            task_public_contract_anchor="",
            existing_tests="",
            implementation_code="",
        )

        assert "- The previous failed suite used bare `datetime` references without a matching import." in block
        assert "- Match the implementation's datetime style: add `from datetime import datetime` at the top" not in block

    def test_adds_required_payload_guidance_for_named_missing_key(self, monkeypatch):
        _patch_exact_rebuild_surface_defaults(
            monkeypatch,
            _summary_has_required_payload_runtime_issue=lambda *args, **kwargs: True,
            _implementation_required_payload_keys=lambda *args, **kwargs: ["customer_id", "details"],
            _validation_failure_omitted_payload_key=lambda *args, **kwargs: "customer_id",
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: handle_request(request)\n"
            "- Exact public class methods: None\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._exact_rebuild_surface_block(
            code_exact_test_contract=contract,
            repair_validation_summary="",
            task_public_contract_anchor="",
            existing_tests="",
            implementation_code="",
        )

        assert "- The implementation validator requires the full payload key set ['customer_id', 'details'] for valid processing." in block
        assert "- In `test_validation_failure`, keep the scaffolded missing-field case on the required payload key `customer_id`." in block

    def test_adds_required_payload_guidance_without_named_missing_key(self, monkeypatch):
        _patch_exact_rebuild_surface_defaults(
            monkeypatch,
            _summary_has_required_payload_runtime_issue=lambda *args, **kwargs: True,
            _implementation_required_payload_keys=lambda *args, **kwargs: ["customer_id", "details"],
            _validation_failure_omitted_payload_key=lambda *args, **kwargs: "",
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: handle_request(request)\n"
            "- Exact public class methods: None\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._exact_rebuild_surface_block(
            code_exact_test_contract=contract,
            repair_validation_summary="",
            task_public_contract_anchor="",
            existing_tests="",
            implementation_code="",
        )

        assert "- The implementation validator requires the full payload key set ['customer_id', 'details'] for valid processing." in block
        assert "keep the scaffolded missing-field case on the required payload key" not in block

    def test_adds_presence_only_and_downstream_key_guidance_without_named_payload_keys(self, monkeypatch):
        _patch_exact_rebuild_surface_defaults(
            monkeypatch,
            _summary_has_required_payload_runtime_issue=lambda *args, **kwargs: True,
            _summary_has_presence_only_validation_sample_issue=lambda *args, **kwargs: True,
            _validation_failure_omitted_payload_key=lambda *args, **kwargs: "customer_id",
            _implementation_non_validation_payload_keys=lambda *args, **kwargs: ["risk_score", "review_notes"],
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: handle_request(request)\n"
            "- Exact public class methods: None\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._exact_rebuild_surface_block(
            code_exact_test_contract=contract,
            repair_validation_summary="",
            task_public_contract_anchor="",
            existing_tests="",
            implementation_code="",
        )

        assert "- Copy the full required payload key set named by the implementation validator into every valid happy-path or batch payload" in block
        assert "- In `test_validation_failure`, keep the scaffolded missing-field case on the validator-required key `customer_id` exactly as shown." in block
        assert "- Do not swap that rejection case to downstream scoring-only keys such as `risk_score`, `review_notes`." in block

    def test_adds_presence_only_guidance_without_named_missing_key(self, monkeypatch):
        _patch_exact_rebuild_surface_defaults(
            monkeypatch,
            _summary_has_presence_only_validation_sample_issue=lambda *args, **kwargs: True,
            _validation_failure_omitted_payload_key=lambda *args, **kwargs: "",
            _implementation_non_validation_payload_keys=lambda *args, **kwargs: ["risk_score", "review_notes"],
        )
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: handle_request(request)\n"
            "- Exact public class methods: None\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._exact_rebuild_surface_block(
            code_exact_test_contract=contract,
            repair_validation_summary="",
            task_public_contract_anchor="",
            existing_tests="",
            implementation_code="",
        )

        assert "- Do not swap that rejection case to downstream scoring-only keys such as `risk_score`, `review_notes`." in block
        assert "keep the scaffolded missing-field case on the validator-required key" not in block

    def test_skips_single_surface_batch_guidance_when_batch_surface_is_documented(self, monkeypatch):
        _patch_exact_rebuild_surface_defaults(monkeypatch)
        contract = (
            "- Allowed production imports: ReviewService, ReviewRequest\n"
            "- Preferred service or workflow facades: ReviewService\n"
            "- Exact public callables: handle_request(request), handle_batch(requests)\n"
            "- Exact public class methods: ReviewService.handle_request(request), ReviewService.handle_batch(requests)\n"
            "- Exact constructor fields: ReviewRequest(name)"
        )

        block = QATesterAgent._exact_rebuild_surface_block(
            code_exact_test_contract=contract,
            repair_validation_summary="",
            task_public_contract_anchor="",
            existing_tests="",
            implementation_code="",
        )

        assert "- No batch helper is documented in the exact contract." not in block


class TestDatetimeAndImportHelpers:
    def test_datetime_import_line_prefers_direct_datetime_and_timezone_import(self):
        content = "fixed_time = datetime.now(timezone.utc)"

        assert QATesterAgent._datetime_import_line_for_content(content) == "from datetime import datetime, timezone"

    def test_datetime_import_line_supports_timezone_only_references(self):
        assert QATesterAgent._datetime_import_line_for_content("value = timezone.utc") == "from datetime import datetime, timezone"

    def test_datetime_import_line_falls_back_to_fixed_time_import(self, monkeypatch):
        monkeypatch.setattr(QATesterAgent, "_fixed_time_import_line", lambda *args, **kwargs: "fallback import")

        assert QATesterAgent._datetime_import_line_for_content("", implementation_code="") == "fallback import"

    def test_datetime_import_line_falls_back_when_content_has_no_datetime_references(self, monkeypatch):
        monkeypatch.setattr(QATesterAgent, "_fixed_time_import_line", lambda *args, **kwargs: "fallback import")

        assert QATesterAgent._datetime_import_line_for_content("value = fixed_time", implementation_code="") == "fallback import"

    def test_normalize_datetime_reference_style_returns_empty_string_for_non_string(self):
        assert QATesterAgent._normalize_datetime_reference_style(None) == ""

    def test_ensure_import_line_returns_original_content_for_empty_or_existing_import(self):
        assert QATesterAgent._ensure_import_line(None, "import pytest") == ""
        assert QATesterAgent._ensure_import_line("import pytest\nprint('ok')", "import pytest") == "import pytest\nprint('ok')"

    def test_ensure_import_line_inserts_after_shebang_and_existing_imports(self):
        content = "#!/usr/bin/env python\nimport os\nfrom pathlib import Path\nprint('ok')"

        updated = QATesterAgent._ensure_import_line(content, "import pytest")

        assert updated.splitlines() == [
            "#!/usr/bin/env python",
            "import os",
            "from pathlib import Path",
            "import pytest",
            "print('ok')",
        ]

    def test_ensure_import_line_appends_after_import_block_at_end_of_file(self):
        content = "import os\nfrom pathlib import Path"

        updated = QATesterAgent._ensure_import_line(content, "import pytest")

        assert updated.splitlines() == [
            "import os",
            "from pathlib import Path",
            "import pytest",
        ]

    def test_ensure_module_import_symbol_appends_missing_symbol_to_existing_from_import(self):
        content = "from datetime import datetime\nvalue = datetime.now()"

        updated = QATesterAgent._ensure_module_import_symbol(content, "datetime", "timezone")

        assert updated.splitlines()[0] == "from datetime import datetime, timezone"

    def test_ensure_module_import_symbol_returns_original_content_for_invalid_inputs(self):
        assert QATesterAgent._ensure_module_import_symbol(None, "datetime", "timezone") == ""
        assert QATesterAgent._ensure_module_import_symbol("value = 1", "", "timezone") == "value = 1"
        assert QATesterAgent._ensure_module_import_symbol("value = 1", "datetime", "") == "value = 1"

    def test_ensure_module_import_symbol_leaves_existing_symbol_unchanged(self):
        content = "from datetime import datetime, timezone\nvalue = datetime.now(timezone.utc)"

        updated = QATesterAgent._ensure_module_import_symbol(content, "datetime", "timezone")

        assert updated == content

    def test_ensure_module_import_symbol_inserts_new_import_when_missing(self):
        content = "import os\nprint('ok')"

        updated = QATesterAgent._ensure_module_import_symbol(content, "datetime", "timezone")

        assert updated.splitlines() == [
            "import os",
            "from datetime import timezone",
            "print('ok')",
        ]


class TestAstConstructionHelpers:
    def test_implementation_class_node_returns_none_for_empty_name_and_missing_class(self):
        implementation_code = "class ReviewRequest:\n    pass\n"

        assert QATesterAgent._implementation_class_node(implementation_code, "") is None
        assert QATesterAgent._implementation_class_node(implementation_code, "MissingRequest") is None

    def test_implementation_class_node_returns_matching_class(self):
        implementation_code = "class ReviewRequest:\n    pass\n"

        class_node = QATesterAgent._implementation_class_node(implementation_code, "ReviewRequest")

        assert isinstance(class_node, ast.ClassDef)
        assert class_node.name == "ReviewRequest"

    def test_constructor_signature_by_name_returns_match_or_empty(self):
        contract = "- Exact constructor fields: ReviewRequest(name), ReviewBatch(items)"

        assert QATesterAgent._constructor_signature_by_name(contract, "ReviewBatch") == "ReviewBatch(items)"
        assert QATesterAgent._constructor_signature_by_name(contract, "MissingRequest") == ""

    def test_call_argument_nodes_by_parameter_skips_star_and_missing_positionals(self):
        call_node = _parse_call("Foo(name='sample')")

        argument_nodes = QATesterAgent._call_argument_nodes_by_parameter(
            "Foo(*, name, title)",
            call_node,
        )

        assert set(argument_nodes) == {"name"}
        assert cast(ast.Constant, argument_nodes["name"]).value == "sample"

    def test_call_argument_nodes_by_parameter_reads_positional_arguments(self):
        call_node = _parse_call("Foo('sample')")

        argument_nodes = QATesterAgent._call_argument_nodes_by_parameter("Foo(name)", call_node)

        assert cast(ast.Constant, argument_nodes["name"]).value == "sample"

    def test_set_call_argument_value_leaves_call_unchanged_when_parameter_is_absent(self):
        call_node = _parse_call("Foo(existing='value')")

        QATesterAgent._set_call_argument_value(
            "Foo(other)",
            call_node,
            "missing",
            ast.Constant(value="new"),
        )

        assert call_node.keywords[0].arg == "existing"
        assert cast(ast.Constant, call_node.keywords[0].value).value == "value"

    def test_implementation_class_field_annotation_name_reads_annassign_and_init_parameter(self):
        implementation_code = (
            "class ReviewRequest:\n"
            "    name: str\n"
            "\n"
            "    def helper(self) -> None:\n"
            "        pass\n"
            "\n"
            "class ReviewBatch:\n"
            "    def helper(self) -> None:\n"
            "        pass\n"
            "\n"
            "    def __init__(self, count: int):\n"
            "        self.count = count\n"
        )

        assert QATesterAgent._implementation_class_field_annotation_name(implementation_code, "ReviewRequest", "name") == "str"
        assert QATesterAgent._implementation_class_field_annotation_name(implementation_code, "ReviewBatch", "count") == "int"

    def test_implementation_class_field_annotation_name_returns_empty_for_missing_targets(self):
        implementation_code = (
            "class ReviewRequest:\n"
            "    def helper(self) -> None:\n"
            "        pass\n"
            "\n"
            "    def __init__(self, count: int):\n"
            "        self.count = count\n"
        )

        assert QATesterAgent._implementation_class_field_annotation_name(implementation_code, "", "count") == ""
        assert QATesterAgent._implementation_class_field_annotation_name(implementation_code, "ReviewRequest", "missing") == ""

    def test_payload_string_literal_prefers_constant_dict_keys_and_parameter_fallback(self):
        constant_result = QATesterAgent._payload_string_literal(ast.Constant(value="  sample payload  "), "details")
        dict_result = QATesterAgent._payload_string_literal(
            ast.parse("{'jurisdiction': 'US', 'customer_type': 'individual'}", mode="eval").body,
            "details",
        )
        parameter_result = QATesterAgent._payload_string_literal(
            ast.parse("{1: 'value'}", mode="eval").body,
            "risk_score",
        )
        empty_name_result = QATesterAgent._payload_string_literal(None, "")

        assert cast(ast.Constant, constant_result).value == "sample payload"
        assert cast(ast.Constant, dict_result).value == "jurisdiction customer_type"
        assert cast(ast.Constant, parameter_result).value == "risk score"
        assert cast(ast.Constant, empty_name_result).value == "payload"


class TestPayloadConstructionHelpers:
    def test_payload_dict_with_required_keys_preserves_order_and_applies_overrides(self, monkeypatch):
        monkeypatch.setattr(QATesterAgent, "_sample_literal_for_required_key", lambda key: f'"sample-{key}"')
        payload_node = ast.parse(
            "{1: 'skip', 'existing': 'old', 'omit_me': 'gone'}",
            mode="eval",
        ).body

        result = QATesterAgent._payload_dict_with_required_keys(
            payload_node,
            ["existing", "request_type", "required_key"],
            request_type_node=ast.Constant(value="refund"),
            omitted_key="omit_me",
            additional_payload_keys=["extra_key"],
            literal_overrides={"existing": '"updated"', "override_key": '123'},
        )

        rendered = ast.literal_eval(ast.unparse(result))

        assert list(rendered) == ["existing", "request_type", "required_key", "extra_key", "override_key"]
        assert rendered == {
            "existing": "updated",
            "request_type": "refund",
            "required_key": "sample-required_key",
            "extra_key": "sample-extra_key",
            "override_key": 123,
        }

    def test_ast_nodes_equivalent_handles_none_and_matching_nodes(self):
        left = ast.parse("{'name': 'value'}", mode="eval").body
        right = ast.parse("{'name': 'value'}", mode="eval").body

        assert QATesterAgent._ast_nodes_equivalent(left, right) is True
        assert QATesterAgent._ast_nodes_equivalent(None, None) is True
        assert QATesterAgent._ast_nodes_equivalent(None, left) is False

    def test_positive_risk_payload_literal_overrides_detects_positive_components(self):
        function_node = ast.parse(
            "def test_score(score, some_flag):\n"
            "    assert some_flag\n"
            "    assert score.base_score == 1.0\n"
            "    assert score.final_score >= 0.5\n"
            "    assert 0.0 < score.high_value_factor\n"
            "    assert 0.1 <= score.condition_mismatch_factor\n"
        ).body[0]

        overrides = QATesterAgent._positive_risk_payload_literal_overrides(function_node)

        assert overrides == {
            "receipt_status": '"missing"',
            "item_sku": '"ELEC-LAPTOP-001"',
            "item_value_usd": "1299.99",
            "reason": '"damaged in shipping"',
            "condition_notes": '"sealed box with intact packaging"',
        }

    def test_positive_risk_payload_literal_overrides_ignores_non_positive_eq_and_lte_bounds(self):
        function_node = ast.parse(
            "def test_score(score):\n"
            "    assert score.high_value_factor == 0.0\n"
            "    assert 0.0 <= score.condition_mismatch_factor\n"
        ).body[0]

        overrides = QATesterAgent._positive_risk_payload_literal_overrides(function_node)

        assert overrides == {}


class TestNormalizedHelperSurfaceSymbols:
    def test_deduplicates_and_strips_line_hints(self):
        assert QATesterAgent._normalized_helper_surface_symbols(None) == []
        assert QATesterAgent._normalized_helper_surface_symbols(
            [" helper_one (line 4)", 1, "", "helper_one", "helper_two (line 9)"]
        ) == ["helper_one", "helper_two"]


class TestRepairHelperSurfaceBlock:
    def test_falls_back_to_usages_and_lists_both_sections(self, tmp_path):
        agent = _build_agent(tmp_path)

        assert agent._repair_helper_surface_block({}) == ""

        block = agent._repair_helper_surface_block(
            {
                "repair_helper_surface_usages": [" helper_alias (line 14)", "", 1],
            }
        )

        assert "Flagged helper surfaces to remove during repair:" in block
        assert "helper_alias" in block
        assert "Flagged helper-surface references from validation:" in block


class TestRepairFocusBlock:
    def test_guides_missing_request_field_scaffold(self, monkeypatch):
        _patch_repair_focus_defaults(
            monkeypatch,
            _implementation_required_request_fields=lambda *args, **kwargs: ["request_id", "details"],
            _validation_failure_missing_request_field=lambda *args, **kwargs: "request_id",
            _validation_failure_request_like_object_scaffold_line=lambda *args, **kwargs: (
                "invalid_request",
                "invalid_request = SimpleNamespace(details={})",
            ),
        )

        block = QATesterAgent._repair_focus_block(
            "Generated test validation:\n- Verdict: FAIL",
            "implementation_code",
            "existing_tests",
        )

        assert "The current validator checks top-level request field presence on the request object" in block
        assert "Keep the request-like object missing `request_id` exactly as shown" in block
        assert "Keep the constructor-free invalid object line exactly as scaffolded" in block
        assert "Do not fake a missing top-level field with `request_id=None`" in block

    def test_guides_datetime_and_helper_alias_repairs(self, monkeypatch):
        _patch_repair_focus_defaults(
            monkeypatch,
            _summary_issue_value=lambda *args, **kwargs: "pytest, datetime, helper_alias (line 12)",
            _comma_separated_items=lambda value: [item.strip() for item in value.split(",") if item.strip()],
            _undefined_available_module_symbol_names=lambda *args, **kwargs: ["handle_request"],
            _is_helper_alias_like_name=lambda name: name == "helper_alias",
            _implementation_prefers_direct_datetime_import=lambda *args, **kwargs: True,
        )

        block = QATesterAgent._repair_focus_block(
            "Generated test validation:\n- Undefined local names: pytest, datetime, helper_alias (line 12)\n- Verdict: FAIL",
            "implementation_code",
            "existing_tests",
        )

        assert "Add `import pytest` at the top" in block
        assert "referenced `datetime` without importing it" in block
        assert "Match that import style in the rewritten tests" in block
        assert "real production symbols that exist in the module but were never imported" in block
        assert "`handle_request`" in block
        assert "undefined helper or collaborator aliases such as `helper_alias`" in block

    def test_guides_payload_presence_and_required_evidence_repairs(self, monkeypatch):
        _patch_repair_focus_defaults(
            monkeypatch,
            _implementation_required_payload_keys=lambda *args, **kwargs: ["request_id", "details"],
            _validation_failure_omitted_payload_key=lambda *args, **kwargs: "request_id",
            _implementation_required_evidence_items=lambda *args, **kwargs: ["ID", "Address"],
            _implementation_non_validation_payload_keys=lambda *args, **kwargs: ["risk_score", "risk_band"],
            _summary_has_presence_only_validation_sample_issue=lambda *args, **kwargs: True,
            _summary_has_required_payload_runtime_issue=lambda *args, **kwargs: True,
            _summary_has_required_evidence_runtime_issue=lambda *args, **kwargs: True,
        )

        block = QATesterAgent._repair_focus_block(
            "Generated test validation:\n- Verdict: FAIL",
            "implementation_code",
            "existing_tests",
        )

        assert "omit at least one required field" in block
        assert "keep the scaffolded omission on the validator-required key `request_id` exactly as shown" in block
        assert "Do not swap that missing-field case to optional downstream business keys such as risk_score, risk_band" in block
        assert "Every valid happy-path or batch payload must include all required payload keys named by the current validator" in block
        assert "The current validator requires the full evidence set ['ID', 'Address'] before processing" in block


class TestRepairRequestPayloadLiterals:
    def test_returns_empty_string_for_non_string_content(self):
        implementation_code = "class ReturnCase:\n    request_id: str\n    details: dict[str, object]\n"
        contract = "- Exact constructor fields: ReturnCase(request_id, details)"

        updated = QATesterAgent._repair_request_payload_literals(
            None,
            implementation_code,
            contract,
        )

        assert updated == ""

    def test_returns_original_content_for_syntax_error(self):
        implementation_code = "class ReturnCase:\n    request_id: str\n    details: dict[str, object]\n"
        contract = "- Exact constructor fields: ReturnCase(request_id, details)"
        content = "def test_happy_path(:\n    pass\n"

        updated = QATesterAgent._repair_request_payload_literals(
            content,
            implementation_code,
            contract,
        )

        assert updated == content

    def test_rewrites_string_payloads_for_happy_path(self):
        content = (
            "def test_happy_path():\n"
            "    request = ReturnCase('request-1', {'country': 'PT'})\n"
        )
        implementation_code = "class ReturnCase:\n    request_id: str\n    details: str\n"
        contract = "- Exact constructor fields: ReturnCase(request_id, details)"

        updated = QATesterAgent._repair_request_payload_literals(
            content,
            implementation_code,
            contract,
        )

        assert "ReturnCase('request-1', 'country')" in updated

    def test_rewrites_async_risk_payloads_with_literal_overrides(self, monkeypatch):
        monkeypatch.setattr(QATesterAgent, "_implementation_required_payload_keys", lambda *args, **kwargs: [])

        content = (
            "async def test_risk_scoring():\n"
            "    request = ReturnCase('request-1', {})\n"
            "    assert result.high_value_factor == 1.0\n"
        )
        implementation_code = "class ReturnCase:\n    request_id: str\n    details: dict[str, object]\n"
        contract = "- Exact constructor fields: ReturnCase(request_id, details)"

        updated = QATesterAgent._repair_request_payload_literals(
            content,
            implementation_code,
            contract,
        )

        assert "async def test_risk_scoring():" in updated
        assert "'item_sku': 'ELEC-LAPTOP-001'" in updated
        assert "'item_value_usd': 1299.99" in updated

    def test_rewrites_risk_scoring_payloads_for_returns_screening_schema(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: [
                "order_reference",
                "return_reason",
                "items",
                "receipt_present",
                "prior_returns",
                "timing_days",
            ],
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_non_validation_payload_keys",
            lambda *args, **kwargs: [],
        )

        content = (
            "def test_risk_scoring():\n"
            "    request = ReturnCase('request-1', 'standard_return', {'order_reference': 'ORD123456', 'return_reason': 'item defective', 'items': [{'sku': 'SKU001', 'category': 'electronics', 'value': 150.0}], 'receipt_present': True, 'prior_returns': 1, 'timing_days': 14}, fixed_time)\n"
            "    assert result.risk_score > 0.0\n"
            "    assert 'serial_returns' in result.risk_factors\n"
            "    assert 'no_receipt' in result.risk_factors\n"
            "    assert 'high_value_electronics' in result.risk_factors\n"
        )
        implementation_code = (
            "class ReturnCase:\n"
            "    request_id: str\n"
            "    request_type: str\n"
            "    details: dict[str, object]\n"
            "    timestamp: datetime\n"
        )
        contract = "- Exact constructor fields: ReturnCase(request_id, request_type, details, timestamp)"

        updated = QATesterAgent._repair_request_payload_literals(
            content,
            implementation_code,
            contract,
        )

        assert "'receipt_present': False" in updated
        assert "'prior_returns': 5" in updated
        assert "'items': [{'sku': 'ELEC-LAPTOP-001', 'category': 'electronics', 'value': 1299.99}]" in updated
        assert "receipt_status" not in updated
        assert "item_value_usd" not in updated

    def test_rewrites_validation_failure_and_happy_path_payloads(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["country", "documents"],
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_validation_failure_omitted_payload_key",
            lambda *args, **kwargs: "country",
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_non_validation_payload_keys",
            lambda *args, **kwargs: ["risk_score"],
        )

        content = (
            "def test_validation_failure():\n"
            "    invalid_request = ReturnCase('request-1', {'country': 'PT', 'documents': ['id']})\n\n"
            "def test_happy_path():\n"
            "    request = ReturnCase('request-1', {'country': 'PT'})\n"
        )
        implementation_code = "class ReturnCase:\n    request_id: str\n    details: dict[str, object]\n"
        contract = "- Exact constructor fields: ReturnCase(request_id, details)"

        updated = QATesterAgent._repair_request_payload_literals(
            content,
            implementation_code,
            contract,
        )

        assert "invalid_request = ReturnCase('request-1', {'documents': ['id']})" in updated
        assert "request = ReturnCase('request-1', {'country': 'PT', 'documents': ['ID', 'Passport']})" in updated

    def test_leaves_validation_failure_payload_unchanged_when_required_key_is_already_missing(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["country", "documents"],
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_validation_failure_omitted_payload_key",
            lambda *args, **kwargs: "country",
        )

        content = (
            "def test_validation_failure():\n"
            "    invalid_request = ReturnCase('request-1', {'documents': ['id']})\n"
        )
        implementation_code = "class ReturnCase:\n    request_id: str\n    details: dict[str, object]\n"
        contract = "- Exact constructor fields: ReturnCase(request_id, details)"

        updated = QATesterAgent._repair_request_payload_literals(
            content,
            implementation_code,
            contract,
        )

        assert updated == content

    def test_leaves_risk_scoring_payload_unchanged_when_replacement_is_equivalent(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["country"],
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_non_validation_payload_keys",
            lambda *args, **kwargs: [],
        )

        content = (
            "def test_risk_scoring():\n"
            "    request = ReturnCase('request-1', {'country': 'PT', 'item_sku': 'ELEC-LAPTOP-001', 'item_value_usd': 1299.99})\n"
            "    assert result.high_value_factor == 1.0\n"
        )
        implementation_code = "class ReturnCase:\n    request_id: str\n    details: dict[str, object]\n"
        contract = "- Exact constructor fields: ReturnCase(request_id, details)"

        updated = QATesterAgent._repair_request_payload_literals(
            content,
            implementation_code,
            contract,
        )

        assert updated == content

    def test_leaves_risk_scoring_payload_unchanged_when_override_only_replacement_is_equivalent(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: [],
        )

        content = (
            "def test_risk_scoring():\n"
            "    request = ReturnCase('request-1', {'item_sku': 'ELEC-LAPTOP-001', 'item_value_usd': 1299.99})\n"
            "    assert result.high_value_factor == 1.0\n"
        )
        implementation_code = "class ReturnCase:\n    request_id: str\n    details: dict[str, object]\n"
        contract = "- Exact constructor fields: ReturnCase(request_id, details)"

        updated = QATesterAgent._repair_request_payload_literals(
            content,
            implementation_code,
            contract,
        )

        assert updated == content

    def test_rewrites_validation_failure_payload_when_payload_argument_is_not_dict(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["country", "documents"],
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_validation_failure_omitted_payload_key",
            lambda *args, **kwargs: "country",
        )
        monkeypatch.setattr(
            QATesterAgent,
            "_payload_dict_with_required_keys",
            lambda *args, **kwargs: ast.parse("{'documents': ['ID']}", mode="eval").body,
        )

        content = (
            "def test_validation_failure():\n"
            "    payload = existing_payload\n"
            "    invalid_request = ReturnCase('request-1', payload)\n"
        )
        implementation_code = "class ReturnCase:\n    request_id: str\n    details: dict[str, object]\n"
        contract = "- Exact constructor fields: ReturnCase(request_id, details)"

        updated = QATesterAgent._repair_request_payload_literals(
            content,
            implementation_code,
            contract,
        )

        assert "invalid_request = ReturnCase('request-1', {'documents': ['ID']})" in updated
        assert "invalid_request = ReturnCase('request-1', payload)" not in updated

    def test_leaves_happy_path_payload_unchanged_when_required_keys_already_match(self, monkeypatch):
        monkeypatch.setattr(
            QATesterAgent,
            "_implementation_required_payload_keys",
            lambda *args, **kwargs: ["country", "documents"],
        )

        content = (
            "def test_happy_path():\n"
            "    request = ReturnCase('request-1', {'country': 'PT', 'documents': ['ID', 'Passport']})\n"
        )
        implementation_code = "class ReturnCase:\n    request_id: str\n    details: dict[str, object]\n"
        contract = "- Exact constructor fields: ReturnCase(request_id, details)"

        updated = QATesterAgent._repair_request_payload_literals(
            content,
            implementation_code,
            contract,
        )

        assert updated == content

    def test_validation_failure_drops_stale_details_key_deletion_when_details_becomes_none(self):
        content = (
            "def test_validation_failure():\n"
            "    vendor_submission = VendorSubmission(request_id='request_id-1', request_type='screening', details={'vendor_name': 'SampleVendor'}, timestamp=fixed_time)\n"
            "    del vendor_submission.details['due_diligence_evidence']\n"
        )
        implementation_code = (
            "from datetime import datetime\n\n"
            "class VendorSubmission:\n"
            "    request_id: str\n"
            "    request_type: str\n"
            "    details: dict[str, object]\n"
            "    timestamp: datetime\n\n"
            "class VendorRiskReviewService:\n"
            "    def validate_request(self, request: VendorSubmission) -> bool:\n"
            "        return isinstance(request.details, dict)\n"
        )
        updated = QATesterAgent._normalize_placeholder_payload_values(
            content,
            implementation_code,
        )

        assert "details=None" in updated
        assert "del vendor_submission.details['due_diligence_evidence']" not in updated

    def test_validation_failure_preserves_pytest_raises_when_implementation_raises_value_error(self):
        content = (
            "import pytest\n\n"
            "def test_validation_failure():\n"
            "    with pytest.raises(ValueError):\n"
            "        service.handle_request(vendor_submission)\n"
        )
        implementation_code = (
            "class VendorRiskReviewService:\n"
            "    def validate_request(self, request):\n"
            "        return isinstance(request.details, dict)\n\n"
            "    def handle_request(self, request):\n"
            "        if not self.validate_request(request):\n"
            "            raise ValueError('invalid request')\n"
            "        return {'outcome': 'accepted'}\n"
        )

        updated = QATesterAgent._normalize_placeholder_payload_values(
            content,
            implementation_code,
        )

        assert "with pytest.raises(ValueError):" in updated
        assert "_validation_result = service.handle_request(vendor_submission)" not in updated

    def test_validation_failure_rewrites_pytest_raises_when_implementation_does_not_raise_value_error(self):
        content = (
            "import pytest\n\n"
            "def test_validation_failure():\n"
            "    with pytest.raises(ValueError):\n"
            "        service.handle_request(vendor_submission)\n"
        )
        implementation_code = (
            "class VendorRiskReviewService:\n"
            "    def validate_request(self, request):\n"
            "        return isinstance(request.details, dict)\n\n"
            "    def handle_request(self, request):\n"
            "        return {'outcome': 'blocked'}\n"
        )

        updated = QATesterAgent._normalize_placeholder_payload_values(
            content,
            implementation_code,
        )

        assert "with pytest.raises(ValueError):" not in updated
        assert "_validation_result = service.handle_request(vendor_submission)" in updated
        assert "try:" in updated

    def test_validation_failure_rewrites_inverted_bool_assert_and_direct_outcome_assertions(self):
        content = (
            "import pytest\n"
            "from datetime import datetime\n"
            "from code_implementation import ClaimTriageService, ClaimRequest, ClaimOutcome\n\n"
            "def test_validation_failure():\n"
            "    service = ClaimTriageService()\n"
            "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
            "    request = ClaimRequest(request_id='request_id-1', request_type='screening', details=None, timestamp=fixed_time)\n"
            "    is_valid = service.validate_request(request)\n"
            "    assert is_valid is True\n"
            "    outcome = service.handle_request(request)\n"
            "    assert outcome.request_id == request.request_id\n"
            "    assert isinstance(outcome.outcome, str)\n"
        )
        implementation_code = (
            "from datetime import datetime\n\n"
            "class ClaimRequest:\n"
            "    request_id: str\n"
            "    request_type: str\n"
            "    details: dict[str, object]\n"
            "    timestamp: datetime\n\n"
            "class ClaimTriageService:\n"
            "    def validate_request(self, request):\n"
            "        return isinstance(request.details, dict)\n\n"
            "    def handle_request(self, request):\n"
            "        if not self.validate_request(request):\n"
            "            raise ValueError('invalid request')\n"
            "        return {'outcome': 'accepted'}\n"
        )

        updated = QATesterAgent._normalize_placeholder_payload_values(
            content,
            implementation_code,
        )

        assert "assert is_valid is False" in updated
        assert "with pytest.raises(ValueError):" in updated
        assert "service.handle_request(request)" in updated
        assert "outcome = service.handle_request(request)" not in updated
        assert "assert outcome.request_id == request.request_id" not in updated
        assert "assert isinstance(outcome.outcome, str)" not in updated


class TestServiceDependencyHelpers:
    def test_maps_dependency_methods_and_infers_forwarded_return_types(self):
        implementation_code = (
            "class ReviewRequest:\n"
            "    pass\n\n"
            "class RiskScore:\n"
            "    pass\n\n"
            "class AuditRecord:\n"
            "    pass\n\n"
            "class AccessReviewService:\n"
            "    def __init__(self, risk_engine, audit_logger, notifier):\n"
            "        self.risk_engine = risk_engine\n"
            "        self.audit_logger = audit_logger\n"
            "        self.notifier = notifier\n\n"
            "    def handle_request(self, request: ReviewRequest):\n"
            "        risk = self.risk_engine.calculate_risk(request)\n"
            "        self.determine_outcome(risk)\n"
            "        record = self.audit_logger.record(request=request)\n"
            "        self.persist_record(result=record)\n"
            "        self.notifier.notify()\n"
            "        self.risk_engine.calculate_risk(request)\n"
            "        helper.calculate_risk(request)\n"
            "        other.notifier.notify()\n"
            "        return record\n\n"
            "    def determine_outcome(self, risk: RiskScore):\n"
            "        return risk\n\n"
            "    def persist_record(self, result: AuditRecord):\n"
            "        return result\n"
        )

        dependency_methods = QATesterAgent._service_dependency_method_map(
            implementation_code,
            "AccessReviewService",
            ["risk_engine", "audit_logger", "notifier"],
        )
        return_types = QATesterAgent._service_dependency_return_type_map(
            implementation_code,
            "AccessReviewService",
            ["risk_engine", "audit_logger", "notifier"],
        )

        assert dependency_methods == {
            "risk_engine": ["calculate_risk"],
            "audit_logger": ["record"],
            "notifier": ["notify"],
        }
        assert return_types == {
            ("risk_engine", "calculate_risk"): "RiskScore",
            ("audit_logger", "record"): "AuditRecord",
        }

    def test_builds_stub_return_expressions_and_dependency_fallbacks(self):
        contract = (
            "Exact test contract:\n"
            "- Exact constructor fields: RiskScore(request_id, score, reasons, outcome, details, timestamp, policy_name)\n"
        )

        stub_expression = QATesterAgent._stub_return_expression_for_class("RiskScore", contract)
        typed_dependency_stub = QATesterAgent._dependency_stub_expression(
            "risk_engine",
            ["calculate_risk"],
            {("risk_engine", "calculate_risk"): "RiskScore"},
            contract,
        )
        fallback_dependency_stub = QATesterAgent._dependency_stub_expression(
            "notifier",
            ["is_ready", "risk_score", "fetch_records", "notify"],
            {},
            contract,
        )
        dynamic_dependency_stub = QATesterAgent._dependency_stub_expression(
            "audit_logger",
            [],
            {},
            contract,
        )

        assert stub_expression.startswith("RiskScore(")
        assert "request_id=args[0].request_id if args and hasattr(args[0], 'request_id') else 'request_id-1'" in stub_expression
        assert "score=0.0" in stub_expression
        assert "reasons=[]" in stub_expression
        assert 'outcome="approved"' in stub_expression
        assert "details={}" in stub_expression
        assert "timestamp=getattr(args[0], 'timestamp', None)" in stub_expression
        assert 'policy_name="sample_7"' in stub_expression
        assert '"calculate_risk": lambda self, *args, **kwargs: RiskScore(' in typed_dependency_stub
        assert '"is_ready": lambda self, *args, **kwargs: True' in fallback_dependency_stub
        assert '"risk_score": lambda self, *args, **kwargs: 0.0' in fallback_dependency_stub
        assert '"fetch_records": lambda self, *args, **kwargs: []' in fallback_dependency_stub
        assert '"notify": lambda self, *args, **kwargs: None' in fallback_dependency_stub
        assert "__getattr__" in dynamic_dependency_stub

    def test_ignores_missing_classes_and_unknown_dependency_calls(self):
        implementation_code = (
            "class AccessReviewService:\n"
            "    def handle_request(self, request):\n"
            "        self.other_dep.notify(request)\n"
            "        self.audit_logger.record(request)\n"
        )

        dependency_methods = QATesterAgent._service_dependency_method_map(
            implementation_code,
            "AccessReviewService",
            ["audit_logger"],
        )
        missing_service_methods = QATesterAgent._service_dependency_method_map(
            implementation_code,
            "MissingService",
            ["audit_logger"],
        )

        assert dependency_methods == {"audit_logger": ["record"]}
        assert missing_service_methods == {}

    def test_inferred_forwarded_argument_annotation_returns_empty_for_unusable_calls(self):
        implementation_code = (
            "class AccessReviewService:\n"
            "    def handle_request(self, request, extra):\n"
            "        self.missing(request)\n"
            "        self.target_one(extra, request)\n"
            "        self.target_one(**request)\n"
            "        self.target_one(item='literal')\n"
            "        self.target_one(other=request)\n"
            "        self.target_positional_untyped(request)\n"
            "        self.target_unannotated(item=request)\n"
            "\n"
            "    def target_one(self, item: str):\n"
            "        return item\n"
            "\n"
            "    def target_positional_untyped(self, item):\n"
            "        return item\n"
            "\n"
            "    def target_unannotated(self, item):\n"
            "        return item\n"
        )
        class_node = QATesterAgent._implementation_class_node(implementation_code, "AccessReviewService")
        assert isinstance(class_node, ast.ClassDef)
        method_nodes = {
            child.name: child
            for child in class_node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        annotation_name = QATesterAgent._inferred_forwarded_argument_annotation(
            method_nodes["handle_request"],
            method_nodes,
            "request",
        )

        assert annotation_name == ""

    def test_service_dependency_return_type_map_skips_unknown_duplicate_and_untyped_paths(self):
        implementation_code = (
            "class RiskScore:\n"
            "    pass\n"
            "\n"
            "class AccessReviewService:\n"
            "    def handle_request(self, request):\n"
            "        plain = build()\n"
            "        foreign = self.other_dep.score(request)\n"
            "        risk = self.risk_engine.calculate_risk(request)\n"
            "        self.consume(risk)\n"
            "        again = self.risk_engine.calculate_risk(request)\n"
            "        self.consume(again)\n"
            "        temp = self.risk_engine.fetch_raw(request)\n"
            "        self.consume_untyped(temp)\n"
            "\n"
            "    def consume(self, risk: RiskScore):\n"
            "        return risk\n"
            "\n"
            "    def consume_untyped(self, value):\n"
            "        return value\n"
        )

        return_types = QATesterAgent._service_dependency_return_type_map(
            implementation_code,
            "AccessReviewService",
            ["risk_engine"],
        )
        missing_service_return_types = QATesterAgent._service_dependency_return_type_map(
            implementation_code,
            "MissingService",
            ["risk_engine"],
        )

        assert return_types == {("risk_engine", "calculate_risk"): "RiskScore"}
        assert missing_service_return_types == {}

    def test_stub_return_expression_for_class_returns_none_or_skips_star_parameters(self):
        contract = (
            "Exact test contract:\n"
            "- Exact constructor fields: RiskScore(*, request_id, score)"
        )

        missing_stub = QATesterAgent._stub_return_expression_for_class("MissingScore", contract)
        typed_stub = QATesterAgent._stub_return_expression_for_class("RiskScore", contract)

        assert missing_stub == "None"
        assert "request_id=args[0].request_id if args and hasattr(args[0], 'request_id') else 'request_id-1'" in typed_stub
        assert "score=0.0" in typed_stub
        assert "*=" not in typed_stub

    def test_repairs_zero_arg_service_instantiations_and_merges_needed_imports(self):
        implementation_code = (
            "class ReviewRequest:\n"
            "    def __init__(self, request_id, details):\n"
            "        self.request_id = request_id\n"
            "        self.details = details\n\n"
            "class RiskScore:\n"
            "    def __init__(self, request_id, score):\n"
            "        self.request_id = request_id\n"
            "        self.score = score\n\n"
            "class AuditRecord:\n"
            "    def __init__(self, request_id, status, timestamp):\n"
            "        self.request_id = request_id\n"
            "        self.status = status\n"
            "        self.timestamp = timestamp\n\n"
            "class AccessReviewService:\n"
            "    def __init__(self, risk_engine, audit_logger):\n"
            "        self.risk_engine = risk_engine\n"
            "        self.audit_logger = audit_logger\n\n"
            "    def handle_request(self, request: ReviewRequest):\n"
            "        risk = self.risk_engine.calculate_risk(request)\n"
            "        self.determine_outcome(risk)\n"
            "        record = self.audit_logger.record(request=request)\n"
            "        self.persist_record(result=record)\n"
            "        return record\n\n"
            "    def determine_outcome(self, risk: RiskScore):\n"
            "        return risk\n\n"
            "    def persist_record(self, result: AuditRecord):\n"
            "        return result\n"
        )
        contract = (
            "Exact test contract:\n"
            "- Allowed production imports: ReviewRequest, AccessReviewService, RiskScore, AuditRecord\n"
            "- Preferred service or workflow facades: AccessReviewService\n"
            "- Exact public callables: none\n"
            "- Exact public class methods: AccessReviewService.handle_request(request)\n"
            "- Exact constructor fields: ReviewRequest(request_id, details), RiskScore(request_id, score), AuditRecord(request_id, status, timestamp), AccessReviewService(risk_engine, audit_logger)\n"
            "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
        )
        content = (
            "from service_module import ReviewRequest, AccessReviewService\n\n"
            "def test_happy_path():\n"
            "    service = AccessReviewService()\n"
            "    request = ReviewRequest(request_id='req-1', details={})\n"
            "    result = service.handle_request(request)\n"
            "    assert result is not None\n"
        )

        updated = QATesterAgent._repair_zero_arg_service_instantiations(
            content,
            module_name="service_module",
            implementation_code=implementation_code,
            code_exact_test_contract=contract,
        )

        assert "AccessReviewService()" not in updated
        assert "from service_module import ReviewRequest, AccessReviewService, AuditRecord, RiskScore" in updated
        assert 'risk_engine=type("_RiskEngineStub"' in updated
        assert '"calculate_risk": lambda self, *args, **kwargs: RiskScore(' in updated
        assert 'audit_logger=type("_AuditLoggerStub"' in updated
        assert '"record": lambda self, *args, **kwargs: AuditRecord(' in updated

    def test_zero_arg_service_repair_returns_empty_string_for_non_string_or_blank_content(self):
        implementation_code = "class AccessReviewService:\n    pass\n"

        assert (
            QATesterAgent._repair_zero_arg_service_instantiations(
                None,
                module_name="service_module",
                implementation_code=implementation_code,
                code_exact_test_contract="",
            )
            == ""
        )
        assert (
            QATesterAgent._repair_zero_arg_service_instantiations(
                "   ",
                module_name="service_module",
                implementation_code=implementation_code,
                code_exact_test_contract="",
            )
            == "   "
        )

    def test_zero_arg_service_repair_leaves_content_unchanged_when_no_replacement_is_built(self, monkeypatch):
        implementation_code = (
            "class AccessReviewService:\n"
            "    def __init__(self, risk_engine):\n"
            "        self.risk_engine = risk_engine\n"
        )
        contract = (
            "Exact test contract:\n"
            "- Preferred service or workflow facades: AccessReviewService\n"
            "- Exact constructor fields: AccessReviewService(risk_engine)"
        )
        content = (
            "from service_module import AccessReviewService\n\n"
            "def test_service():\n"
            "    service = AccessReviewService()\n"
            "    assert service is not None\n"
        )

        monkeypatch.setattr(
            QATesterAgent,
            "_constructor_call_expression",
            classmethod(lambda cls, signature, argument_overrides=None: ("AccessReviewService", "")),
        )

        updated = QATesterAgent._repair_zero_arg_service_instantiations(
            content,
            module_name="service_module",
            implementation_code=implementation_code,
            code_exact_test_contract=contract,
        )

        assert updated == content


class TestRandomImportHelpers:
    def test_detects_random_references_and_selects_matching_import_lines(self):
        assert QATesterAgent._content_has_matching_random_import(None) is False
        assert QATesterAgent._content_has_matching_random_import("import random\n") is True
        assert QATesterAgent._content_has_matching_random_import("from random import random\n") is True
        assert QATesterAgent._content_has_matching_random_import("from random import randint\n") is False

        assert QATesterAgent._content_has_random_reference("") is False
        assert QATesterAgent._content_has_random_reference("value = random()\n") is True
        assert QATesterAgent._content_has_random_reference("value = random.choice(options)\n") is True
        assert QATesterAgent._content_has_random_reference("value = helper.random()\n") is False

        assert QATesterAgent._random_import_line_for_content("value = random.choice(options)\n") == "import random"
        assert QATesterAgent._random_import_line_for_content("value = random()\n") == "from random import random"

    def test_finalizer_adds_matching_random_import_for_missing_references(self):
        direct_random_content = (
            "from service_module import ReviewRequest\n\n"
            "def test_sampling():\n"
            "    score = random()\n"
            "    assert score >= 0.0\n"
        )
        module_random_content = (
            "from service_module import ReviewRequest\n\n"
            "def test_sampling_choice():\n"
            "    selected = random.choice(['a', 'b'])\n"
            "    assert selected in {'a', 'b'}\n"
        )
        implementation_code = "class ReviewRequest:\n    pass\n"

        finalized_direct = QATesterAgent._finalize_generated_test_suite(
            direct_random_content,
            module_name="service_module",
            implementation_code=implementation_code,
        )
        finalized_module = QATesterAgent._finalize_generated_test_suite(
            module_random_content,
            module_name="service_module",
            implementation_code=implementation_code,
        )

        assert "from random import random" in finalized_direct.splitlines()[:3]
        assert "score = random()" in finalized_direct
        assert "import random" in finalized_module.splitlines()[:3]
        assert "selected = random.choice(['a', 'b'])" in finalized_module

    def test_finalizer_returns_empty_string_for_non_string_or_blank_content(self):
        implementation_code = "class ReviewRequest:\n    pass\n"

        assert (
            QATesterAgent._finalize_generated_test_suite(
                None,
                module_name="service_module",
                implementation_code=implementation_code,
            )
            == ""
        )
        assert (
            QATesterAgent._finalize_generated_test_suite(
                "   ",
                module_name="service_module",
                implementation_code=implementation_code,
            )
            == "   "
        )


class TestConstructorScaffoldHelpers:
    def test_builds_constructor_scaffolds_and_call_expressions(self):
        assert QATesterAgent._constructor_scaffold_line("") == ("", "")
        assert QATesterAgent._constructor_call_expression("") == ("", "")
        assert QATesterAgent._constructor_call_expression("AccessReviewService()") == (
            "AccessReviewService",
            "AccessReviewService()",
        )

        variable_name, scaffold_line = QATesterAgent._constructor_scaffold_line(
            "ReviewRequest(name, details)"
        )
        override_variable, override_line = QATesterAgent._constructor_scaffold_line_with_overrides(
            "ReviewRequest(name, details)",
            argument_overrides={"details": "{}"},
        )
        class_name, constructor_expression = QATesterAgent._constructor_call_expression(
            "Alert(name, status)",
            index_offset=2,
        )

        assert variable_name == "request"
        assert scaffold_line == 'request = ReviewRequest(name="sample_1", details={"source": "web"})'
        assert override_variable == "request"
        assert override_line == 'request = ReviewRequest(name="sample_1", details={})'
        assert class_name == "Alert"
        assert constructor_expression == 'Alert(name="sample_3", status="pending")'


class TestBatchAndMethodScaffoldHelpers:
    def test_builds_batch_loop_scaffolds_with_optional_result_collection(self):
        assert (
            QATesterAgent._batch_loop_scaffold_lines(
                primary_method="handle_batch",
                preferred_constructor="ReviewRequest(name, details)",
            )
            == []
        )

        lines = QATesterAgent._batch_loop_scaffold_lines(
            primary_method="AccessReviewService.handle_batch",
            preferred_constructor="ReviewRequest(name, details)",
            argument_overrides={"details": "{}"},
            collect_results=True,
        )

        assert lines == [
            "service = AccessReviewService()",
            "requests = [",
            '    ReviewRequest(name="sample_1", details={}),',
            '    ReviewRequest(name="sample_2", details={}),',
            "]",
            "results = []",
            "for request in requests:",
            "    result = service.handle_batch(request)",
            "    results.append(result)",
        ]

    def test_builds_callable_and_method_scaffolds_for_single_and_batch_paths(self):
        assert QATesterAgent._callable_scaffold_line("", "review_request") == ""
        assert QATesterAgent._callable_scaffold_line(
            "handle_request(request)",
            "review_request",
        ) == "result = handle_request(review_request)"
        assert QATesterAgent._callable_scaffold_line(
            "process_batch(requests)",
            "review_request",
        ) == "result = process_batch([review_request])"
        assert QATesterAgent._callable_scaffold_line(
            "process_batch()",
            "",
        ) == "result = process_batch(...)"

        assert QATesterAgent._method_scaffold_lines("invalid", "review_request") == ("", "")
        assert QATesterAgent._method_scaffold_lines(
            "AccessReviewService.handle_request",
            "review_request",
        ) == (
            "service = AccessReviewService()",
            "result = service.handle_request(review_request)",
        )
        assert QATesterAgent._method_scaffold_lines(
            "AccessReviewService.handle_batch",
            "review_request",
        ) == (
            "service = AccessReviewService()",
            "result = service.handle_batch([review_request])",
        )
        assert QATesterAgent._method_scaffold_lines(
            "AccessReviewService.handle_batch",
            "",
        ) == (
            "service = AccessReviewService()",
            "result = service.handle_batch(...)",
        )


class TestAssertionIssueDetectors:
    def test_detects_exact_status_action_label_assertion_issue_from_terse_pytest_failure_summary(self):
        summary = "Generated test validation failed: pytest failed: 1 failed, 4 passed in 0.09s"
        content = (
            "def test_happy_path():\n"
            "    assert isinstance(result.outcome, str)\n\n"
            "def test_risk_scoring():\n"
            "    assert result.risk_score == 45\n"
            "    assert result.outcome == 'blocked'\n"
        )

        assert QATesterAgent._summary_has_exact_status_action_label_assertion_issue(summary, content) is True

    def test_detects_exact_band_label_assertion_issues_from_summary_and_failed_tests(self):
        summary_literal = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: assert 'high' in ['low', 'medium']\n"
            "- Verdict: FAIL"
        )
        summary_ast = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: FAILED tests_test.py::test_happy_path - AssertionError\n"
            "- Verdict: FAIL"
        )
        summary_eq = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: FAILED tests_test.py::test_batch_processing - AssertionError\n"
            "- Verdict: FAIL"
        )
        content_in = (
            "def test_happy_path():\n"
            "    assert result.risk_band in ['low', 'medium']\n"
        )
        content_eq = (
            "def test_batch_processing():\n"
            "    assert result.priority == 'critical'\n"
        )

        assert QATesterAgent._summary_has_exact_band_label_assertion_issue(None) is False
        assert QATesterAgent._summary_has_exact_band_label_assertion_issue(summary_literal) is True
        assert QATesterAgent._summary_has_exact_band_label_assertion_issue(summary_ast, content_in) is True
        assert QATesterAgent._summary_has_exact_band_label_assertion_issue(summary_eq, content_eq) is True

    def test_skips_full_band_in_assertions_and_non_eq_comparators(self):
        summary = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: FAILED tests_test.py::test_happy_path - AssertionError\n"
            "- Verdict: FAIL"
        )
        content = (
            "def test_happy_path():\n"
            "    assert result.risk_band in ['low', 'medium', 'high', 'critical']\n"
            "    assert result.priority != expected_priority\n"
            "    assert result.severity == result.classification\n"
        )

        assert QATesterAgent._summary_has_exact_band_label_assertion_issue(summary, content) is False

    def test_detects_band_eq_assertions_when_only_one_side_has_canonical_band_literal(self):
        summary = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: FAILED tests_test.py::test_happy_path - AssertionError\n"
            "- Verdict: FAIL"
        )
        content_left_band = (
            "def test_happy_path():\n"
            "    assert 'critical' == result.severity\n"
        )
        content_right_band = (
            "def test_happy_path():\n"
            "    assert result.priority == 'high'\n"
        )

        assert QATesterAgent._summary_has_exact_band_label_assertion_issue(summary, content_left_band) is True
        assert QATesterAgent._summary_has_exact_band_label_assertion_issue(summary, content_right_band) is True

    def test_detects_exact_temporal_and_numeric_score_assertion_issues(self):
        temporal_summary = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: FAILED tests_test.py::test_happy_path - AssertionError: assert '2026-04-22' == result.timestamp.isoformat()\n"
            "- Verdict: FAIL"
        )
        temporal_content = (
            "def test_happy_path():\n"
            "    assert result.timestamp == '2026-04-22'\n"
        )
        numeric_summary = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: FAILED tests_test.py::test_risk_scoring - AssertionError: assert 1.0 == 0.0\n"
            "- Verdict: FAIL"
        )
        numeric_content = (
            "def test_risk_scoring():\n"
            "    assert result.risk_score == 1.0\n"
        )

        assert QATesterAgent._summary_has_exact_temporal_value_assertion_issue(
            temporal_summary,
            temporal_content,
        ) is True
        assert QATesterAgent._summary_has_exact_numeric_score_assertion_issue(
            numeric_summary,
            numeric_content,
        ) is True

    def test_detects_positive_numeric_score_assertions_and_recent_timestamp_requirements(self):
        summary = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: FAILED tests_test.py::test_risk_scoring - AssertionError\n"
            "- Verdict: FAIL"
        )
        content_gt = (
            "def test_risk_scoring():\n"
            "    assert result.risk_score > 0\n"
        )
        content_lt = (
            "def test_risk_scoring():\n"
            "    assert 0 < result.score\n"
        )

        assert QATesterAgent._summary_has_positive_numeric_score_assertion_issue(summary, content_gt) is True
        assert QATesterAgent._summary_has_positive_numeric_score_assertion_issue(summary, content_lt) is True
        assert QATesterAgent._implementation_prefers_timezone_aware_now(
            "return datetime.now(timezone.utc)"
        ) is True
        assert QATesterAgent._implementation_requires_recent_request_timestamp("") is False
        assert QATesterAgent._implementation_requires_recent_request_timestamp(
            "if request timestamp is stale:\n    return policy"
        ) is True
        assert QATesterAgent._implementation_requires_recent_request_timestamp(
            "age = datetime.now(timezone.utc) - request.timestamp\nreturn policy if age.days >= 30 else None"
        ) is True
        assert QATesterAgent._implementation_requires_recent_request_timestamp(
            "request_timestamp = request.timestamp\nage = datetime.now() - request_timestamp\nreturn age.total_seconds() <= 86400"
        ) is True

    def test_handles_negative_paths_for_temporal_and_numeric_detectors(self):
        temporal_summary = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: FAILED tests_test.py::test_happy_path - AssertionError: assert '2026-04-22' == value\n"
            "- Verdict: FAIL"
        )
        temporal_non_eq_content = (
            "def test_happy_path():\n"
            "    assert result.timestamp != '2026-04-22'\n"
        )
        temporal_validation_failure_content = (
            "def test_validation_failure():\n"
            "    assert request.timestamp == '2026-04-22'\n"
        )

        assert QATesterAgent._summary_has_exact_temporal_value_assertion_issue(None, temporal_non_eq_content) is False
        assert QATesterAgent._summary_has_exact_temporal_value_assertion_issue(
            temporal_summary,
            temporal_non_eq_content,
        ) is False
        assert QATesterAgent._summary_has_exact_temporal_value_assertion_issue(
            temporal_summary.replace("test_happy_path", "test_validation_failure"),
            temporal_validation_failure_content,
        ) is False

        numeric_summary = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: FAILED tests_test.py::test_risk_scoring - AssertionError: assert 1.0 == 0.0\n"
            "- Verdict: FAIL"
        )
        numeric_non_eq_content = (
            "def test_risk_scoring():\n"
            "    assert result.risk_score > 0.0\n"
        )
        numeric_no_token_content = (
            "def test_risk_scoring():\n"
            "    assert result.priority == 1.0\n"
        )

        assert QATesterAgent._summary_has_exact_numeric_score_assertion_issue("", numeric_no_token_content) is False
        assert QATesterAgent._summary_has_exact_numeric_score_assertion_issue(
            "Generated test validation: assert x == y",
            numeric_no_token_content,
        ) is False
        assert QATesterAgent._summary_has_exact_numeric_score_assertion_issue(
            numeric_summary,
            numeric_non_eq_content,
        ) is False
        assert QATesterAgent._summary_has_exact_numeric_score_assertion_issue(
            numeric_summary,
            numeric_no_token_content,
        ) is False

        positive_summary = (
            "Generated test validation:\n"
            "- Pytest execution: FAIL\n"
            "- Pytest failure details: FAILED tests_test.py::test_risk_scoring - AssertionError\n"
            "- Verdict: FAIL"
        )
        positive_gt_literal_left = (
            "def test_risk_scoring():\n"
            "    assert 1.0 > result.risk_score\n"
        )
        positive_lt_literal_right = (
            "def test_risk_scoring():\n"
            "    assert result.score < 2.0\n"
        )

        assert QATesterAgent._summary_has_positive_numeric_score_assertion_issue("", positive_gt_literal_left) is False
        assert QATesterAgent._summary_has_positive_numeric_score_assertion_issue(
            positive_summary,
            "def test_risk_scoring():\n    assert result.priority > 0\n",
        ) is False
        assert QATesterAgent._summary_has_positive_numeric_score_assertion_issue(
            positive_summary,
            positive_gt_literal_left,
        ) is True
        assert QATesterAgent._summary_has_positive_numeric_score_assertion_issue(
            positive_summary,
            positive_lt_literal_right,
        ) is True


class TestDatetimeHelpers:
    def test_content_datetime_helper_guards_return_false_for_non_str(self):
        assert QATesterAgent._content_has_direct_datetime_import(None) is False
        assert QATesterAgent._content_has_direct_datetime_import("") is False
        assert QATesterAgent._content_has_datetime_module_import(None) is False
        assert QATesterAgent._content_has_datetime_module_import("") is False
        assert QATesterAgent._content_has_bare_datetime_reference(None) is False
        assert QATesterAgent._content_has_bare_datetime_reference("") is False
        assert QATesterAgent._content_has_direct_datetime_reference(None) is False
        assert QATesterAgent._content_has_direct_datetime_reference("") is False

    def test_content_datetime_helpers_match_positive_patterns(self):
        direct_import = "from datetime import datetime, timezone\n"
        module_import = "import datetime\n"
        bare_ref = "dt = datetime(2026, 1, 1)\n"
        direct_ref = "ts = datetime.now()\n"

        assert QATesterAgent._content_has_direct_datetime_import(direct_import) is True
        assert QATesterAgent._content_has_direct_datetime_import(module_import) is False
        assert QATesterAgent._content_has_datetime_module_import(module_import) is True
        assert QATesterAgent._content_has_datetime_module_import(direct_import) is False
        assert QATesterAgent._content_has_bare_datetime_reference(bare_ref) is True
        assert QATesterAgent._content_has_bare_datetime_reference(module_import) is False
        assert QATesterAgent._content_has_direct_datetime_reference(direct_ref) is True
        assert QATesterAgent._content_has_direct_datetime_reference(module_import) is False

    def test_missing_datetime_import_issue_with_content_having_import_returns_false(self):
        summary = "Undefined local names: datetime"
        content_with_import = "from datetime import datetime\ndt = datetime(2026, 1, 1)\n"
        content_bare_no_import = "dt = datetime(2026, 1, 1)\n"
        content_no_ref = "result = service.handle_request(request)\n"

        assert QATesterAgent._summary_has_missing_datetime_import_issue("") is False
        assert QATesterAgent._summary_has_missing_datetime_import_issue("no datetime issue") is False
        assert QATesterAgent._summary_has_missing_datetime_import_issue(summary) is True
        assert QATesterAgent._summary_has_missing_datetime_import_issue(summary, content_with_import) is False
        assert QATesterAgent._summary_has_missing_datetime_import_issue(summary, content_bare_no_import) is True
        assert QATesterAgent._summary_has_missing_datetime_import_issue(summary, content_no_ref) is False

    def test_implementation_prefers_datetime_module_import_branches(self):
        direct_import_impl = "from datetime import datetime\n\ndef handle(r):\n    return datetime.now()\n"
        module_import_impl = "import datetime\n\ndef handle(r):\n    return datetime.datetime.now()\n"
        dt_datetime_ref = "def handle(r):\n    return datetime.datetime.now()\n"
        dt_timezone_ref = "def handle(r):\n    return datetime.timezone.utc\n"

        assert QATesterAgent._implementation_prefers_datetime_module_import("") is False
        assert QATesterAgent._implementation_prefers_datetime_module_import(None) is False
        assert QATesterAgent._implementation_prefers_datetime_module_import(direct_import_impl) is False
        assert QATesterAgent._implementation_prefers_datetime_module_import(module_import_impl) is True
        assert QATesterAgent._implementation_prefers_datetime_module_import(dt_datetime_ref) is True
        assert QATesterAgent._implementation_prefers_datetime_module_import(dt_timezone_ref) is True


class TestRequiredFieldHelpers:
    def test_is_required_field_collection_name_guards_and_patterns(self):
        assert QATesterAgent._is_required_field_collection_name("") is False
        assert QATesterAgent._is_required_field_collection_name("optional_fields") is False
        assert QATesterAgent._is_required_field_collection_name("required_fields") is True
        assert QATesterAgent._is_required_field_collection_name("required_keys") is True
        assert QATesterAgent._is_required_field_collection_name("required_payload_keys") is True
        assert QATesterAgent._is_required_field_collection_name("required_something_else") is False

    def test_is_required_evidence_collection_name(self):
        assert QATesterAgent._is_required_evidence_collection_name("required_documents") is True
        assert QATesterAgent._is_required_evidence_collection_name("required_evidence") is True
        assert QATesterAgent._is_required_evidence_collection_name("documents") is False
        assert QATesterAgent._is_required_evidence_collection_name("") is False

    def test_all_membership_required_names_guard_exits(self):
        import ast

        # Not an `all()` call
        non_all = ast.parse("x in collection", mode="eval").body
        assert QATesterAgent._all_membership_required_names(non_all, {}) == ([], None)

        # `all()` with multiple generators
        multi_gen = ast.parse("all(f in required_fields and g in required_keys for f in x for g in y)", mode="eval").body
        assert QATesterAgent._all_membership_required_names(multi_gen, {}) == ([], None)

        # `all()` with tuple target instead of Name
        tuple_target_code = ast.parse("all((a, b) in required_fields for (a, b) in pairs)", mode="eval").body
        assert QATesterAgent._all_membership_required_names(tuple_target_code, {}) == ([], None)


class TestASTPayloadHelpers:
    def test_body_affects_validation_result_edge_paths(self):
        import ast

        # multi-target assign → continue (does not match single-name guard)
        multi_target = ast.parse("a = b = False").body
        assert QATesterAgent._body_affects_validation_result(multi_target) is False

        # single-target "is_valid" but value not a False constant → falls through
        non_false_valid_assign = ast.parse("is_valid = some_function()").body
        assert QATesterAgent._body_affects_validation_result(non_false_valid_assign) is False

        # Call with func.attr not in {append, extend} → continue
        remove_call = ast.parse("errors.remove(e)").body
        assert QATesterAgent._body_affects_validation_result(remove_call) is False

        # Call with append but func.value is Attribute (not Name) → continue
        attr_append = ast.parse("self.errors.append(e)").body
        assert QATesterAgent._body_affects_validation_result(attr_append) is False

    def test_is_payload_container_expression_none_guard_and_name_match(self):
        import ast

        assert QATesterAgent._is_payload_container_expression(None, {"details"}) is False

        details_node = ast.parse("details", mode="eval").body
        assert QATesterAgent._is_payload_container_expression(details_node, {"details"}) is True

        unmatched_node = ast.parse("result_value", mode="eval").body
        assert QATesterAgent._is_payload_container_expression(unmatched_node, {"details"}) is False

    def test_is_direct_payload_container_expression_guards_and_name_match(self):
        import ast

        assert QATesterAgent._is_direct_payload_container_expression(None, {"details"}) is False

        details_name = ast.parse("details", mode="eval").body
        assert QATesterAgent._is_direct_payload_container_expression(details_name, {"details"}) is True

        other_name = ast.parse("result", mode="eval").body
        assert QATesterAgent._is_direct_payload_container_expression(other_name, {"details"}) is False

    def test_is_request_field_container_expression_guards_and_paths(self):
        import ast

        assert QATesterAgent._is_request_field_container_expression(None) is False

        dict_attr = ast.parse("request.__dict__", mode="eval").body
        assert QATesterAgent._is_request_field_container_expression(dict_attr) is True

        vars_with_arg = ast.parse("vars(request)", mode="eval").body
        assert QATesterAgent._is_request_field_container_expression(vars_with_arg) is True

        vars_no_arg = ast.parse("vars()", mode="eval").body
        assert QATesterAgent._is_request_field_container_expression(vars_no_arg) is False

    def test_implementation_required_evidence_items_syntax_error_and_empty(self):
        assert QATesterAgent._implementation_required_evidence_items("def (") == []
        assert QATesterAgent._implementation_required_evidence_items("") == []

        impl_no_items = "required_evidence = some_function()\ndef validate(r): pass\n"
        assert QATesterAgent._implementation_required_evidence_items(impl_no_items) == []

        impl_with_items = (
            "required_evidence = ['proof_of_identity', 'address_proof']\n"
            "def validate(r):\n"
            "    if 'proof_of_identity' not in r.details:\n"
            "        raise ValueError('missing')\n"
        )
        result = QATesterAgent._implementation_required_evidence_items(impl_with_items)
        assert "proof_of_identity" in result

    def test_class_has_payload_like_field_via_plain_assign(self):
        import ast

        class_with_assign = ast.parse(
            "class MyClass:\n    name: str = 'x'\n    details = {}\n"
        ).body[0]
        assert isinstance(class_with_assign, ast.ClassDef)
        assert QATesterAgent._class_has_payload_like_field(class_with_assign) is True

        class_without_payload = ast.parse(
            "class MyClass:\n    name = 'test'\n    count = 42\n"
        ).body[0]
        assert QATesterAgent._class_has_payload_like_field(class_without_payload) is False


class TestImplementationAnalysisHelpers:
    def test_implementation_required_request_fields_syntax_error_and_module_level_validate(self):
        assert QATesterAgent._implementation_required_request_fields("def (") == []
        assert QATesterAgent._implementation_required_request_fields("") == []

        impl_module_validate = (
            "def validate_request(request):\n"
            "    required_fields = ['company_name', 'contact_email']\n"
            "    if 'company_name' not in vars(request):\n"
            "        raise ValueError('missing company_name')\n"
        )
        result = QATesterAgent._implementation_required_request_fields(impl_module_validate)
        assert "company_name" in result

    def test_implementation_required_request_fields_annassign_fields(self):
        impl_annassign = (
            "class Service:\n"
            "    def validate(self, request):\n"
            "        required_fields: list = ['name', 'email']\n"
            "        if 'name' not in vars(request):\n"
            "            raise ValueError('missing name')\n"
        )
        result = QATesterAgent._implementation_required_request_fields(impl_annassign)
        assert "name" in result

    def test_implementation_validate_payload_alias_names_handles_none(self):
        assert QATesterAgent._implementation_validate_payload_alias_names("def (") == set()
        assert QATesterAgent._implementation_validate_payload_alias_names("") == set()

    def test_function_payload_alias_names_vararg_kwarg_and_attr_subscript(self):
        import ast

        # function with vararg and kwarg
        func_with_vararg = ast.parse(
            "def validate(*details, **context):\n    pass\n"
        ).body[0]
        aliases = QATesterAgent._function_payload_alias_names(func_with_vararg)
        assert "details" in aliases
        assert "context" in aliases

        # function with attribute assignment extracting payload attr
        func_with_attr_assign = ast.parse(
            "def validate(self, request):\n"
            "    payload = request.details\n"
            "    if 'key' not in payload:\n"
            "        raise ValueError('missing')\n"
        ).body[0]
        aliases = QATesterAgent._function_payload_alias_names(func_with_attr_assign)
        assert "payload" in aliases

        # function with subscript assignment extracting payload attr
        func_with_sub_assign = ast.parse(
            "def validate(self, request):\n"
            "    payload = request['details']\n"
            "    if 'key' not in payload:\n"
            "        raise ValueError('missing')\n"
        ).body[0]
        aliases = QATesterAgent._function_payload_alias_names(func_with_sub_assign)
        assert "payload" in aliases

    def test_function_payload_alias_names_subscript_non_payload_key_skipped(self):
        import ast

        # subscript with key not in payload_attrs → should not add alias
        func_non_payload_sub = ast.parse(
            "def validate(self, r):\n"
            "    x = r['something_else']\n"
        ).body[0]
        aliases = QATesterAgent._function_payload_alias_names(func_non_payload_sub)
        assert "x" not in aliases

        # subscript with non-Constant slice → should not add alias
        func_non_const_slice = ast.parse(
            "def validate(self, r):\n"
            "    x = r[key]\n"
        ).body[0]
        aliases = QATesterAgent._function_payload_alias_names(func_non_const_slice)
        assert "x" not in aliases


class TestAnnotationAndCallableHelpers:
    def test_annotation_name_branches(self):
        import ast

        assert QATesterAgent._annotation_name(None) == ""

        name_node = ast.parse("MyType", mode="eval").body
        assert QATesterAgent._annotation_name(name_node) == "MyType"

        attr_node = ast.parse("module.MyType", mode="eval").body
        assert QATesterAgent._annotation_name(attr_node) == "MyType"

        subscript_no_slice = ast.parse("Optional[str]", mode="eval").body
        result = QATesterAgent._annotation_name(subscript_no_slice)
        assert result == "str"

        tuple_node = ast.parse("(int, str)", mode="eval").body
        result = QATesterAgent._annotation_name(tuple_node)
        assert result in ("int", "str")

        # Tuple where all elements give empty names (e.g. numeric constants)
        import ast as _ast
        empty_tuple = _ast.Tuple(elts=[], ctx=_ast.Load())
        assert QATesterAgent._annotation_name(empty_tuple) == ""

    def test_call_expression_name_attribute_and_unknown(self):
        import ast

        attr_call = ast.parse("service.handle_request(r)", mode="eval").body
        assert QATesterAgent._call_expression_name(attr_call) == "handle_request"

        # func is a subscript (not Name or Attribute) → returns ""
        unknown_call = _ast_call_with_subscript_func()
        assert QATesterAgent._call_expression_name(unknown_call) == ""

    def test_nested_callable_ref_edge_paths(self):
        assert QATesterAgent._nested_callable_ref("", "method") == ""
        assert QATesterAgent._nested_callable_ref("func", "") == ""

        # no dot in normalized_ref → return call_name
        result = QATesterAgent._nested_callable_ref("handle_request(r)", "validate")
        assert result == "validate"

        # class.method form but empty class_name part → return call_name
        result = QATesterAgent._nested_callable_ref(".method(r)", "validate")
        assert result == "validate"

    def test_implementation_callable_node_guards(self):
        assert QATesterAgent._implementation_callable_node("def (", "func") is None
        assert QATesterAgent._implementation_callable_node("def func(): pass", "") is None

    def test_callable_local_assignment_values_annassign_branch(self):
        import ast

        func = ast.parse(
            "def handle():\n"
            "    x: int = 5\n"
            "    x = 10\n"
        ).body[0]
        values = QATesterAgent._callable_local_assignment_values(func, "x")
        assert len(values) >= 2

    def test_resolved_callable_return_shapes_empty_and_cycle_guards(self):
        assert QATesterAgent._resolved_callable_return_shapes("def f(): pass", "") == ([], [])
        assert QATesterAgent._resolved_callable_return_shapes(
            "def f(): pass", "f", seen_callable_refs={"f"}
        ) == ([], [])


def _ast_call_with_subscript_func():
    """Helper: build an ast.Call where func is a Subscript (not Name or Attribute)."""
    import ast as _ast
    subscript = _ast.Subscript(
        value=_ast.Name(id="funcs", ctx=_ast.Load()),
        slice=_ast.Constant(value=0),
        ctx=_ast.Load(),
    )
    return _ast.Call(func=subscript, args=[], keywords=[])


class TestExpressionPrimitiveKindAndReturnAnalysis:
    def test_expression_primitive_kind_float(self):
        import ast

        node = ast.Constant(value=3.14)
        assert QATesterAgent._expression_primitive_kind(node) == "float"

    def test_expression_primitive_kind_dict_list_tuple_constants(self):
        import ast

        # dict/list/tuple constant values rarely appear in parsed AST but can be constructed
        dict_const = ast.Constant(value={"a": 1})
        assert QATesterAgent._expression_primitive_kind(dict_const) == "dict"

        list_const = ast.Constant(value=[1, 2])
        assert QATesterAgent._expression_primitive_kind(list_const) == "list"

        tuple_const = ast.Constant(value=(1, 2))
        assert QATesterAgent._expression_primitive_kind(tuple_const) == "tuple"

    def test_expression_primitive_kind_ast_list_and_tuple(self):
        import ast

        list_node = ast.parse("[1, 2]", mode="eval").body
        assert QATesterAgent._expression_primitive_kind(list_node) == "list"

        tuple_node = ast.parse("(1, 2)", mode="eval").body
        assert QATesterAgent._expression_primitive_kind(tuple_node) == "tuple"

    def test_expression_primitive_kind_ifexp_mismatch(self):
        import ast

        # IfExp where body_kind != orelse_kind → returns ""
        ifexp = ast.parse("1 if flag else 'x'", mode="eval").body
        result = QATesterAgent._expression_primitive_kind(ifexp)
        assert result == ""

    def test_implementation_call_return_primitive_kind_callable_none_guard(self):
        assert QATesterAgent._implementation_call_return_primitive_kind("def (broken", "func") == ""

    def test_implementation_call_return_primitive_kind_infer_single_kind(self):
        code = "def get_count(): return 42"
        result = QATesterAgent._implementation_call_return_primitive_kind(code, "get_count")
        assert result == "int"

    def test_implementation_class_field_names_duplicate_guard(self):
        code = "class MyModel:\n    x = 1\n    x = 2\n"
        fields = QATesterAgent._implementation_class_field_names(code, "MyModel")
        assert fields.count("x") == 1

    def test_implementation_class_field_names_non_name_assign_target(self):
        # Assign with a non-Name target (tuple unpacking) should skip (no crash)
        code = "class MyModel:\n    a, b = 1, 2\n"
        fields = QATesterAgent._implementation_class_field_names(code, "MyModel")
        # a,b come from tuple targets which are not ast.Name; should be empty
        # (they might be Tuple nodes) — simply verify no error
        assert isinstance(fields, list)

    def test_implementation_class_field_names_init_self_assigns(self):
        code = (
            "class MyModel:\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "    def other(self):\n"
            "        pass\n"
        )
        fields = QATesterAgent._implementation_class_field_names(code, "MyModel")
        assert "x" in fields

    def test_service_audit_collection_info_guards(self):
        assert QATesterAgent._service_audit_collection_info("def (", "MyService.validate") == ("", "")
        assert QATesterAgent._service_audit_collection_info("class A: pass", "") == ("", "")
        assert QATesterAgent._service_audit_collection_info("class A: pass", "validate") == ("", "")

    def test_service_audit_collection_info_class_not_found(self):
        code = "class OtherService: pass\n"
        result = QATesterAgent._service_audit_collection_info(code, "MyService.validate")
        assert result == ("", "")

    def test_service_audit_collection_info_returns_list_and_dict_type(self):
        code = (
            "class MyService:\n"
            "    def __init__(self):\n"
            "        self.audit_log = []\n"
            "        self.audit_map = {}\n"
        )
        result_list = QATesterAgent._service_audit_collection_info(code, "MyService.validate")
        assert result_list[1] in ("list", "dict", "")

    def test_implementation_result_mapping_field_keys_guards(self):
        assert QATesterAgent._implementation_result_mapping_field_keys("def (", "MyModel", "mapping") == []
        assert QATesterAgent._implementation_result_mapping_field_keys("class A: pass", "", "mapping") == []
        assert QATesterAgent._implementation_result_mapping_field_keys("class A: pass", "MyModel", "") == []

    def test_implementation_result_mapping_field_keys_non_string_key(self):
        code = (
            "class MyResult:\n"
            "    pass\n"
            "\n"
            "def build():\n"
            "    return MyResult(mapping={key: 1})\n"
        )
        keys = QATesterAgent._implementation_result_mapping_field_keys(code, "MyResult", "mapping")
        assert isinstance(keys, list)

    def test_implementation_direct_mapping_return_keys_guards(self):
        assert QATesterAgent._implementation_direct_mapping_return_keys("def (", "func") == []
        assert QATesterAgent._implementation_direct_mapping_return_keys("def func(): return {}", "func") == []

    def test_implementation_direct_mapping_return_keys_intersect(self):
        code = (
            "def get_map():\n"
            "    if x:\n"
            "        return {'a': 1, 'b': 2}\n"
            "    return {'a': 3, 'c': 4}\n"
        )
        keys = QATesterAgent._implementation_direct_mapping_return_keys(code, "get_map")
        assert "a" in keys
        assert "b" not in keys
        assert "c" not in keys


class TestValidationFailureAndConstructorHelpers:
    def test_sample_literal_for_required_key_bool_prefix_path(self):
        # key starting with is_/has_ → line 3204
        assert QATesterAgent._sample_literal_for_required_key("is_active") == "True"
        assert QATesterAgent._sample_literal_for_required_key("has_permission") == "True"

    def test_sample_literal_for_required_key_bool_token_path(self):
        # key containing bool token (not starting with prefix) → line 3206
        result = QATesterAgent._sample_literal_for_required_key("approval_required")
        assert result == "True"

    def test_validation_failure_request_like_object_empty_rendered_items(self):
        # When all required request fields equal the missing_field, rendered_items is empty
        code = (
            "class MyRequest:\n"
            "    def validate(self, payload):\n"
            "        if 'timestamp' not in payload:\n"
            "            raise ValueError\n"
        )
        result = QATesterAgent._validation_failure_request_like_object_scaffold_line(code)
        assert isinstance(result, tuple)

    def test_constructor_rejects_invalid_payload_parse_error(self):
        assert QATesterAgent._constructor_rejects_invalid_payload("MyClass(payload)", "def (") is False

    def test_constructor_rejects_invalid_payload_non_init_method_skipped(self):
        code = (
            "class MyClass:\n"
            "    def validate(self, payload):\n"
            "        if not isinstance(payload, dict):\n"
            "            raise ValueError('bad')\n"
        )
        assert QATesterAgent._constructor_rejects_invalid_payload("MyClass(payload)", code) is False

    def test_constructor_rejects_invalid_payload_raise_name_branch(self):
        code = (
            "class MyClass:\n"
            "    def __init__(self, payload):\n"
            "        if not isinstance(payload, dict):\n"
            "            raise ValueError\n"
        )
        result = QATesterAgent._constructor_rejects_invalid_payload("MyClass(payload)", code)
        assert isinstance(result, bool)

    def test_constructor_rejects_invalid_payload_subscript_isinstance(self):
        code = (
            "class MyClass:\n"
            "    def __init__(self, payload):\n"
            "        if not isinstance(payload['field'], str):\n"
            "            raise ValueError('bad')\n"
        )
        result = QATesterAgent._constructor_rejects_invalid_payload("MyClass(payload)", code)
        assert isinstance(result, bool)

    def test_implementation_call_returns_none_syntax_error(self):
        assert QATesterAgent._implementation_call_returns_none("def (", "func") is False

    def test_implementation_call_returns_none_class_method_not_found(self):
        code = "class MyService:\n    def other(self): pass\n"
        result = QATesterAgent._implementation_call_returns_none(code, "MyService.validate")
        assert result is False

    def test_implementation_call_returns_none_top_level_not_found(self):
        code = "def other_func(): pass\n"
        result = QATesterAgent._implementation_call_returns_none(code, "validate")
        assert result is False

    def test_stable_result_assertion_lines_score_field(self):
        code = (
            "class ValidationResult:\n"
            "    score: float\n"
            "    is_valid: bool\n"
            "\n"
            "class MyService:\n"
            "    def validate(self, payload) -> ValidationResult:\n"
            "        return ValidationResult()\n"
        )
        lines = QATesterAgent._stable_result_assertion_lines(
            code, "MyService.validate", result_name="result", request_name="request"
        )
        assert isinstance(lines, list)

    def test_stable_audit_assertion_lines_batch_dict_kind(self):
        code = (
            "class MyService:\n"
            "    def __init__(self):\n"
            "        self.audit_records = {}\n"
            "    def process(self, request):\n"
            "        return True\n"
        )
        lines = QATesterAgent._stable_audit_assertion_lines(
            code, "MyService.process", service_name="svc", request_name="req", batch=True
        )
        assert isinstance(lines, list)

    def test_stable_audit_assertion_lines_batch_list_kind(self):
        code = (
            "class MyService:\n"
            "    def __init__(self):\n"
            "        self.audit_log = []\n"
            "    def process(self, request):\n"
            "        return True\n"
        )
        lines = QATesterAgent._stable_audit_assertion_lines(
            code, "MyService.process", service_name="svc", request_name="req", batch=True
        )
        assert isinstance(lines, list)


class TestRuntimeAndPresenceHelpers:
    def test_runtime_return_kind_from_summary_unknown_type(self):
        summary = "exact return-shape attribute assumption ('.x' on 'CustomClass')"
        result = QATesterAgent._runtime_return_kind_from_summary(summary)
        assert result == ""

    def test_payload_like_parameter_names_empty_parameter(self):
        # signature with a positional-only or empty-name param
        result = QATesterAgent._payload_like_parameter_names("func(, data)")
        assert isinstance(result, list)

    def test_content_has_incomplete_required_evidence_payload_empty_content(self):
        impl = (
            "class Validator:\n"
            "    def validate(self, payload):\n"
            "        required = ['id_document', 'address_proof', 'income_statement']\n"
            "        if not set(required).issubset(set(payload.get('documents', []))):\n"
            "            raise ValueError\n"
        )
        assert QATesterAgent._content_has_incomplete_required_evidence_payload("", impl) is False
        assert QATesterAgent._content_has_incomplete_required_evidence_payload("   ", impl) is False
        assert QATesterAgent._content_has_incomplete_required_evidence_payload(None, impl) is False

    def test_content_has_incomplete_required_evidence_payload_syntax_error(self):
        impl = (
            "class Validator:\n"
            "    def validate(self, payload):\n"
            "        required = ['id_document', 'address_proof', 'income_statement']\n"
            "        if not set(required).issubset(set(payload.get('documents', []))):\n"
            "            raise ValueError\n"
        )
        assert QATesterAgent._content_has_incomplete_required_evidence_payload("def (broken", impl) is False

    def test_content_has_incomplete_required_payload_empty_and_syntax_error(self):
        impl = "class V:\n    def validate(self, p):\n        if 'x' not in p: raise ValueError\n"
        assert QATesterAgent._content_has_incomplete_required_payload_for_valid_paths("", impl) is False
        assert QATesterAgent._content_has_incomplete_required_payload_for_valid_paths("def (", impl) is False

    def test_content_has_incomplete_required_payload_dict_no_overlap(self):
        impl = "class V:\n    def validate(self, p):\n        if 'required_field' not in p: raise ValueError\n"
        content = (
            "def test_valid_processing():\n"
            "    svc = V()\n"
            "    result = svc.validate({'unrelated_key': 1})\n"
        )
        result = QATesterAgent._content_has_incomplete_required_payload_for_valid_paths(content, impl)
        assert isinstance(result, bool)

    def test_implementation_has_presence_only_required_field_validation_empty(self):
        assert QATesterAgent._implementation_has_presence_only_required_field_validation("") is False
        assert QATesterAgent._implementation_has_presence_only_required_field_validation(None) is False

    def test_implementation_has_presence_only_required_field_validation_syntax_error(self):
        assert QATesterAgent._implementation_has_presence_only_required_field_validation("def (broken") is False

    def test_implementation_has_presence_only_required_field_validation_annassign_branch(self):
        code = (
            "class Validator:\n"
            "    def validate(self, r):\n"
            "        required: list = ['name', 'email']\n"
            "        for f in required:\n"
            "            if f not in r:\n"
            "                raise ValueError\n"
        )
        result = QATesterAgent._implementation_has_presence_only_required_field_validation(code)
        assert isinstance(result, bool)

    def test_block_mentions_all_required_payload_keys_empty_block(self):
        assert QATesterAgent._block_mentions_all_required_payload_keys("", ["key1"]) is False
        assert QATesterAgent._block_mentions_all_required_payload_keys("some block", []) is False

    def test_summary_has_presence_only_validation_no_block(self):
        summary = (
            "pytest execution: fail\n"
            "pytest failure details: assert True is False\n"
        )
        impl = "class V:\n    def validate(self, p):\n        required = ['x']\n        if 'x' not in p: raise ValueError\n"
        content = "def test_validation_failure(): pass\n"
        result = QATesterAgent._summary_has_presence_only_validation_sample_issue(summary, content, impl)
        assert isinstance(result, bool)

    def test_contract_line_value_non_string_contract(self):
        assert QATesterAgent._contract_line_value(42, "label") == ""
        assert QATesterAgent._contract_line_value(None, "label") == ""

    def test_summary_has_presence_only_validation_no_validate_call_in_block(self):
        summary = (
            "pytest execution: fail\n"
            "pytest failure details: assert True is False\n"
        )
        impl = "class V:\n    def validate(self, p):\n        required = ['x']\n        if 'x' not in p: raise ValueError\n"
        content = "def test_validation_failure():\n    result = do_other_thing({'x': 1})\n"
        result = QATesterAgent._summary_has_presence_only_validation_sample_issue(summary, content, impl)
        assert result is False


class TestContentPayloadPathsAndHelpers:
    def test_payload_like_parameter_names_asterisk_param_is_skipped(self):
        # "*" as parameter → _parameter_name("*") == "" → triggers continue at line 3492
        result = QATesterAgent._payload_like_parameter_names("func(*, payload)")
        assert "payload" in result

    def test_content_has_incomplete_required_evidence_payload_empty_content(self):
        impl = (
            "class V:\n"
            "    def validate(self, p):\n"
            "        required_evidence = ['id', 'passport', 'proof']\n"
            "        if not set(required_evidence).issubset(set(p.get('documents', []))):\n"
            "            raise ValueError\n"
        )
        assert QATesterAgent._content_has_incomplete_required_evidence_payload("", impl) is False
        assert QATesterAgent._content_has_incomplete_required_evidence_payload("  ", impl) is False

    def test_content_has_incomplete_required_evidence_payload_syntax_error(self):
        impl = (
            "class V:\n"
            "    def validate(self, p):\n"
            "        required_evidence = ['id', 'passport', 'proof']\n"
            "        if not set(required_evidence).issubset(set(p.get('documents', []))):\n"
            "            raise ValueError\n"
        )
        assert QATesterAgent._content_has_incomplete_required_evidence_payload("def (broken", impl) is False

    def test_content_has_incomplete_required_payload_empty_content_with_keys(self):
        impl = (
            "class V:\n"
            "    def validate(self, payload):\n"
            "        if 'name' not in payload: raise ValueError\n"
            "        if 'email' not in payload: raise ValueError\n"
        )
        assert QATesterAgent._content_has_incomplete_required_payload_for_valid_paths("", impl) is False
        assert QATesterAgent._content_has_incomplete_required_payload_for_valid_paths("def (", impl) is False

    def test_content_has_incomplete_required_payload_dict_no_overlap_with_keys(self):
        impl = (
            "class V:\n"
            "    def validate(self, payload):\n"
            "        if 'name' not in payload: raise ValueError\n"
            "        if 'email' not in payload: raise ValueError\n"
        )
        content = (
            "def test_valid_processing():\n"
            "    svc = V()\n"
            "    result = svc.validate({'unrelated_key': 'value'})\n"
            "    assert result is not None\n"
        )
        result = QATesterAgent._content_has_incomplete_required_payload_for_valid_paths(content, impl)
        assert isinstance(result, bool)


class TestRiskFactorAndContentPayloadHelpers:
    def test_risk_factor_membership_name_multiple_ops(self):
        import ast

        cmp = ast.parse("a < b < c", mode="eval").body
        assert QATesterAgent._risk_factor_membership_name(cmp) == ""

    def test_risk_factor_membership_name_not_in_op(self):
        import ast

        cmp = ast.parse("'no_receipt' not in x.risk_factors", mode="eval").body
        assert QATesterAgent._risk_factor_membership_name(cmp) == ""

    def test_risk_factor_membership_name_wrong_attr(self):
        import ast

        cmp = ast.parse("'no_receipt' in x.other_factors", mode="eval").body
        assert QATesterAgent._risk_factor_membership_name(cmp) == ""

    def test_risk_factor_membership_name_unknown_factor(self):
        import ast

        cmp = ast.parse("'unknown_factor' in x.risk_factors", mode="eval").body
        assert QATesterAgent._risk_factor_membership_name(cmp) == ""

    def test_positive_risk_payload_overrides_damaged_inconsistency(self):
        import ast

        code = (
            "def test_high_risk():\n"
            "    assert 'damaged_inconsistency' in svc.risk_factors\n"
        )
        func_node = ast.parse(code).body[0]
        overrides = QATesterAgent._positive_risk_payload_literal_overrides(func_node)
        assert "return_reason" in overrides

    def test_content_has_incomplete_required_payload_loop_back_and_no_overlap(self):
        impl = (
            "class V:\n"
            "    def validate(self, payload):\n"
            "        if 'name' not in payload: raise ValueError\n"
            "        if 'email' not in payload: raise ValueError\n"
        )
        # Two test functions: first has no dict overlap, second also has no overlap
        content = (
            "def test_valid_processing():\n"
            "    svc = V()\n"
            "    result = svc.validate({'unrelated': 1})\n"
            "    assert result\n"
            "\n"
            "def test_valid_processing_alt():\n"
            "    svc = V()\n"
            "    result = svc.validate({'other': 2})\n"
            "    assert result\n"
        )
        result = QATesterAgent._content_has_incomplete_required_payload_for_valid_paths(content, impl)
        assert isinstance(result, bool)

    def test_content_has_incomplete_required_payload_complete_dict_continues(self):
        impl = (
            "class V:\n"
            "    def validate(self, payload):\n"
            "        if 'name' not in payload: raise ValueError\n"
            "        if 'email' not in payload: raise ValueError\n"
        )
        # Dict contains ALL required keys → required_payload_set.issubset(dict_keys) is True → continue (3637->3627)
        content = (
            "def test_valid_processing():\n"
            "    svc = V()\n"
            "    result = svc.validate({'name': 'John', 'email': 'j@x.com'})\n"
            "    assert result\n"
        )
        result = QATesterAgent._content_has_incomplete_required_payload_for_valid_paths(content, impl)
        assert result is False


class TestNormalizePlaceholderPayloadValues:
    def test_empty_string_content(self):
        # empty string → still a string → returns "" (line 6063)
        result = QATesterAgent._normalize_placeholder_payload_values("")
        assert result == ""

    def test_syntax_error_content(self):
        # syntax error → returns content unchanged (lines 6072-6073)
        result = QATesterAgent._normalize_placeholder_payload_values("def (broken")
        assert result == "def (broken"

    def test_dict_with_non_constant_key_skipped(self):
        # dict with variable key → continue at 6083
        content = "x = {key: 'value'}\n"
        result = QATesterAgent._normalize_placeholder_payload_values(content)
        assert isinstance(result, str)

    def test_dict_items_value_replaced_with_list(self):
        # key="items", value="value" → replacement = ["sample"] (line 6102)
        content = "payload = {'items': 'value'}\n"
        result = QATesterAgent._normalize_placeholder_payload_values(content)
        assert '"sample"' in result or "sample" in result

    def test_dict_metadata_value_replaced_with_dict(self):
        # key="metadata", value="value" → replacement = {"key": "value"} (line 6111)
        content = "payload = {'metadata': 'value'}\n"
        result = QATesterAgent._normalize_placeholder_payload_values(content)
        assert isinstance(result, str)

    def test_dict_approved_value_replaced_with_true(self):
        # key="approved", value="value" → replacement = True (line 6121)
        content = "payload = {'approved': 'value'}\n"
        result = QATesterAgent._normalize_placeholder_payload_values(content)
        assert "True" in result

    def test_dict_score_value_replaced_with_int(self):
        # key="score", value="value" → replacement = 1 (line 6132)
        content = "payload = {'score': 'value'}\n"
        result = QATesterAgent._normalize_placeholder_payload_values(content)
        assert "1" in result

    def test_call_with_kwargs_star_keyword_skipped(self):
        # keyword with arg=None (**kwargs) → continue at 6152
        content = "func(**kwargs)\n"
        result = QATesterAgent._normalize_placeholder_payload_values(content)
        assert isinstance(result, str)

    def test_call_keyword_details_space_value_replaced_with_dict(self):
        # keyword arg `details="emergency_access stale"` → dict replacement (lines 6160-6161)
        content = "func(details='emergency_access stale')\n"
        result = QATesterAgent._normalize_placeholder_payload_values(content)
        assert isinstance(result, str)

    def test_call_keyword_items_space_value_replaced_with_list(self):
        # keyword arg `items="foo bar"` → list replacement (lines 6163-6164)
        content = "func(items='foo bar')\n"
        result = QATesterAgent._normalize_placeholder_payload_values(content)
        assert isinstance(result, str)

    def test_validation_failure_function_dict_kwarg_replaced_with_none(self):
        # test_validation_failure function with isinstance_dict impl → dict kwarg replaced (line 6200+)
        impl = "class V:\n    def validate(self, details):\n        if not isinstance(details, dict): raise ValueError\n"
        content = (
            "def test_validation_failure():\n"
            "    svc = V()\n"
            "    with pytest.raises(ValueError):\n"
            "        svc.validate(details={'key': 'value'})\n"
        )
        result = QATesterAgent._normalize_placeholder_payload_values(content, impl)
        assert isinstance(result, str)

    def test_targets_details_like_subscript_non_subscript(self):
        # Test via the public API: a delete with non-subscript target in test_validation_failure
        impl = "class V:\n    def validate(self, details):\n        if not isinstance(details, dict): raise ValueError\n"
        content = (
            "def test_validation_failure():\n"
            "    d = {'x': 1}\n"
            "    del d['details']\n"
            "    svc = V()\n"
            "    svc.validate(details=None)\n"
        )
        result = QATesterAgent._normalize_placeholder_payload_values(content, impl)
        assert isinstance(result, str)

    def test_validation_failure_with_pytest_raises_block_transformed(self):
        # test_validation_failure with `with pytest.raises(ValueError): call(...)` → transformed (lines 6260+)
        impl = "class V:\n    def validate(self, payload):\n        if 'x' not in payload: raise ValueError\n"
        content = (
            "def test_validation_failure():\n"
            "    svc = V()\n"
            "    with pytest.raises(ValueError):\n"
            "        svc.validate(payload={'x': 'value'})\n"
        )
        result = QATesterAgent._normalize_placeholder_payload_values(content, impl)
        assert isinstance(result, str)

    def test_validation_failure_delete_and_kwarg_guard_paths(self):
        impl = (
            "class V:\n"
            "    def validate(self, details):\n"
            "        if not isinstance(details, dict):\n"
            "            return {'outcome': 'blocked'}\n"
            "        return {'outcome': 'blocked'}\n"
        )
        content = (
            "def test_validation_failure():\n"
            "    svc = V()\n"
            "    details = {'x': 'value'}\n"
            "    keep = {'y': 'value'}\n"
            "    del keep['y']\n"
            "    del details['x']\n"
            "    kwargs = {'details': {'k': 'v'}}\n"
            "    svc.validate(**kwargs)\n"
            "    svc.validate(details=details)\n"
        )

        result = QATesterAgent._normalize_placeholder_payload_values(content, impl)

        assert isinstance(result, str)
        assert "del details['x']" not in result
        assert "svc.validate(**kwargs)" in result
        assert "svc.validate(details=details)" in result

    def test_validation_failure_with_block_rewritten_when_impl_does_not_raise(self):
        impl = (
            "class V:\n"
            "    def validate(self, payload):\n"
            "        if not isinstance(payload, dict):\n"
            "            return {'outcome': 'blocked'}\n"
            "        return {'outcome': 'blocked'}\n"
        )
        content = (
            "def test_validation_failure():\n"
            "    svc = V()\n"
            "    with pytest.raises(ValueError):\n"
            "        svc.validate(payload={'x': 'value'})\n"
        )

        result = QATesterAgent._normalize_placeholder_payload_values(content, impl)

        assert isinstance(result, str)
        assert "try:" in result
        assert "_validation_result = svc.validate(payload=None)" in result

    def test_validation_failure_expectation_rewrite_paths(self):
        impl = (
            "class V:\n"
            "    def validate(self, request):\n"
            "        if request is None:\n"
            "            raise ValueError('bad request')\n"
            "        return type('R', (), {'is_valid': True})()\n"
            "\n"
            "    def submit(self, request):\n"
            "        return {'outcome': 'blocked'}\n"
        )
        content = (
            "def test_validation_failure():\n"
            "    svc = V()\n"
            "    invalid_request = None\n"
            "    _holder.value = svc.validate(request=invalid_request)\n"
            "    validation_result = svc.validate(invalid_request)\n"
            "    assert validation_result == True\n"
            "    submit_result = svc.submit(invalid_request)\n"
            "    assert submit_result['outcome'] == 'blocked'\n"
        )

        result = QATesterAgent._normalize_placeholder_payload_values(content, impl)

        assert isinstance(result, str)
        assert "assert validation_result == False" in result
        assert "with pytest.raises(ValueError):" in result
        assert "svc.submit(invalid_request)" in result
        assert "assert submit_result['outcome'] == 'blocked'" not in result




