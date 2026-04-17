"""Tests for QATesterAgent pure static/classmethods."""

import ast

from kycortex_agents.agents.qa_tester import QATesterAgent


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


# ---------------------------------------------------------------------------
# _is_payload_key_set_expression
# ---------------------------------------------------------------------------

class TestIsPayloadKeySetExpression:
    def test_none_returns_false(self):
        assert QATesterAgent._is_payload_key_set_expression(None, set()) is False
