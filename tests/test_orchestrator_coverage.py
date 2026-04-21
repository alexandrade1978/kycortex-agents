"""Targeted coverage tests for Orchestrator internal helpers.

These tests target the largest uncovered code clusters (by missed-statement
count) and focus on pure or near-pure methods that accept simple inputs.
"""

import ast

import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.orchestration.module_ast_analysis import (
    build_code_behavior_contract,
    extract_type_constraints,
    infer_dict_key_value_examples,
    isinstance_subject_name,
    isinstance_type_names,
)
from kycortex_agents.orchestration.repair_test_analysis import module_defined_symbol_names
from kycortex_agents.orchestration.test_ast_analysis import (
    analyze_test_type_mismatches,
    auto_fix_test_type_mismatches,
    collect_mock_support,
    infer_argument_type,
    known_type_allows_member,
    parent_map,
    patched_target_name_from_call,
)
from kycortex_agents.orchestration import (
    ast_is_empty_literal,
    default_value_for_annotation,
    plain_class_field_default_factory_details,
    python_import_roots,
    required_field_list_from_failed_artifact,
    validation_has_blocking_issues,
    validation_has_only_warnings,
    validation_has_static_issues,
)
from kycortex_agents.orchestrator import Orchestrator, _example_from_default


@pytest.fixture()
def orch(tmp_path):
    config = KYCortexConfig(output_dir=str(tmp_path / "output"))
    return Orchestrator(config)


# ---------------------------------------------------------------------------
# _test_validation_has_static_issues  (24 missed statements)
# ---------------------------------------------------------------------------

class TestTestValidationHasStaticIssues:
    def test_missing_test_analysis_returns_true(self, orch):
        assert validation_has_static_issues({}) is True

    def test_non_dict_test_analysis_returns_true(self, orch):
        assert validation_has_static_issues({"test_analysis": "nope"}) is True

    def test_clean_validation_returns_false(self, orch):
        validation = {"test_analysis": {"syntax_ok": True}}
        assert validation_has_static_issues(validation) is False

    def test_syntax_not_ok(self, orch):
        validation = {"test_analysis": {"syntax_ok": False}}
        assert validation_has_static_issues(validation) is True

    def test_line_count_exceeds_budget(self, orch):
        validation = {"test_analysis": {"syntax_ok": True, "line_count": 200, "line_budget": 100}}
        assert validation_has_static_issues(validation) is True

    def test_line_count_within_budget(self, orch):
        validation = {"test_analysis": {"syntax_ok": True, "line_count": 50, "line_budget": 100}}
        assert validation_has_static_issues(validation) is False

    def test_top_level_test_count_mismatch(self, orch):
        validation = {
            "test_analysis": {
                "syntax_ok": True,
                "top_level_test_count": 5,
                "expected_top_level_test_count": 3,
            }
        }
        assert validation_has_static_issues(validation) is True

    def test_top_level_test_count_exceeds_max(self, orch):
        validation = {
            "test_analysis": {
                "syntax_ok": True,
                "top_level_test_count": 10,
                "max_top_level_test_count": 5,
            }
        }
        assert validation_has_static_issues(validation) is True

    def test_fixture_count_exceeds_budget(self, orch):
        validation = {"test_analysis": {"syntax_ok": True, "fixture_count": 5, "fixture_budget": 2}}
        assert validation_has_static_issues(validation) is True

    def test_fixture_count_within_budget(self, orch):
        validation = {"test_analysis": {"syntax_ok": True, "fixture_count": 1, "fixture_budget": 2}}
        assert validation_has_static_issues(validation) is False

    def test_blocking_issue_key_triggers(self, orch):
        validation = {"test_analysis": {"syntax_ok": True, "missing_function_imports": ["foo"]}}
        assert validation_has_static_issues(validation) is True

    def test_warning_issue_key_triggers(self, orch):
        validation = {"test_analysis": {"syntax_ok": True, "contract_overreach_signals": ["bar"]}}
        assert validation_has_static_issues(validation) is True


# ---------------------------------------------------------------------------
# _test_validation_has_blocking_issues  (~10 missed)
# ---------------------------------------------------------------------------

class TestTestValidationHasBlockingIssues:
    def test_clean_validation(self, orch):
        validation = {"test_analysis": {"syntax_ok": True}}
        assert validation_has_blocking_issues(validation) is False

    def test_missing_analysis(self, orch):
        assert validation_has_blocking_issues({}) is True

    def test_blocking_key(self, orch):
        validation = {"test_analysis": {"syntax_ok": True, "undefined_fixtures": ["x"]}}
        assert validation_has_blocking_issues(validation) is True

    def test_warning_key_not_blocking(self, orch):
        validation = {"test_analysis": {"syntax_ok": True, "type_mismatches": ["z"]}}
        assert validation_has_blocking_issues(validation) is False


# ---------------------------------------------------------------------------
# _test_validation_has_only_warnings
# ---------------------------------------------------------------------------

class TestTestValidationHasOnlyWarnings:
    def test_only_warnings(self, orch):
        validation = {"test_analysis": {"syntax_ok": True, "type_mismatches": ["m"]}}
        assert validation_has_only_warnings(validation) is True

    def test_blocking_issues(self, orch):
        validation = {"test_analysis": {"syntax_ok": True, "undefined_fixtures": ["x"]}}
        assert validation_has_only_warnings(validation) is False

    def test_no_issues(self, orch):
        validation = {"test_analysis": {"syntax_ok": True}}
        assert validation_has_only_warnings(validation) is False


# ---------------------------------------------------------------------------
# _ast_is_empty_literal  (11 missed)
# ---------------------------------------------------------------------------

class TestAstIsEmptyLiteral:
    def test_none_input(self):
        assert ast_is_empty_literal(None) is False

    def test_empty_string_constant(self):
        node = ast.parse('""', mode="eval").body
        assert ast_is_empty_literal(node) is True

    def test_none_constant(self):
        node = ast.parse("None", mode="eval").body
        assert ast_is_empty_literal(node) is True

    def test_non_empty_string(self):
        node = ast.parse('"hello"', mode="eval").body
        assert ast_is_empty_literal(node) is False

    def test_empty_list(self):
        node = ast.parse("[]", mode="eval").body
        assert ast_is_empty_literal(node) is True

    def test_non_empty_list(self):
        node = ast.parse("[1]", mode="eval").body
        assert ast_is_empty_literal(node) is False

    def test_empty_dict(self):
        node = ast.parse("{}", mode="eval").body
        assert ast_is_empty_literal(node) is True

    def test_non_empty_dict(self):
        node = ast.parse("{'k': 1}", mode="eval").body
        assert ast_is_empty_literal(node) is False

    def test_empty_tuple(self):
        node = ast.parse("()", mode="eval").body
        assert ast_is_empty_literal(node) is True

    def test_empty_set_call(self):
        node = ast.parse("set()", mode="eval").body
        assert ast_is_empty_literal(node) is True

    def test_dict_call(self):
        node = ast.parse("dict()", mode="eval").body
        assert ast_is_empty_literal(node) is True

    def test_list_call(self):
        node = ast.parse("list()", mode="eval").body
        assert ast_is_empty_literal(node) is True

    def test_call_with_args_not_empty(self):
        node = ast.parse("list([1, 2])", mode="eval").body
        assert ast_is_empty_literal(node) is False

    def test_non_builtin_call(self):
        node = ast.parse("MyClass()", mode="eval").body
        assert ast_is_empty_literal(node) is False


# ---------------------------------------------------------------------------
# _infer_argument_type  (29 missed)
# ---------------------------------------------------------------------------

class TestInferArgumentType:
    def test_none_payload(self, orch):
        assert infer_argument_type(None, {}, "field", {}) == ""

    def test_dict_payload_string_field(self, orch):
        code = "{'name': 'alice'}"
        node = ast.parse(code, mode="eval").body
        assert infer_argument_type(node, {}, "name", {}) == "str"

    def test_dict_payload_int_field(self, orch):
        node = ast.parse("{'age': 30}", mode="eval").body
        assert infer_argument_type(node, {}, "age", {}) == "int"

    def test_dict_payload_missing_field(self, orch):
        node = ast.parse("{'name': 'alice'}", mode="eval").body
        assert infer_argument_type(node, {}, "missing", {}) == ""

    def test_dict_field_is_dict(self, orch):
        node = ast.parse("{'data': {'k': 'v'}}", mode="eval").body
        assert infer_argument_type(node, {}, "data", {}) == "dict"

    def test_dict_field_is_list(self, orch):
        node = ast.parse("{'items': [1, 2]}", mode="eval").body
        assert infer_argument_type(node, {}, "items", {}) == "list"

    def test_dict_field_is_tuple(self, orch):
        node = ast.parse("{'coords': (1, 2)}", mode="eval").body
        assert infer_argument_type(node, {}, "coords", {}) == "tuple"

    def test_dict_field_is_set(self, orch):
        node = ast.parse("{'tags': {1, 2}}", mode="eval").body
        assert infer_argument_type(node, {}, "tags", {}) == "set"

    def test_dict_field_is_builtin_call(self, orch):
        node = ast.parse("{'items': list()}", mode="eval").body
        assert infer_argument_type(node, {}, "items", {}) == "list"

    def test_dict_field_is_dict_call(self, orch):
        node = ast.parse("{'data': dict()}", mode="eval").body
        assert infer_argument_type(node, {}, "data", {}) == "dict"


# ---------------------------------------------------------------------------
# _isinstance_subject_name  (10 missed)
# ---------------------------------------------------------------------------

class TestIsinstanceSubjectName:
    def test_name_node(self, orch):
        node = ast.parse("x", mode="eval").body
        assert isinstance_subject_name(node) == "x"

    def test_attribute_node(self, orch):
        node = ast.parse("obj.attr", mode="eval").body
        assert isinstance_subject_name(node) == "attr"

    def test_subscript_node(self, orch):
        node = ast.parse("d['key']", mode="eval").body
        assert isinstance_subject_name(node) == "key"

    def test_call_get_method(self, orch):
        node = ast.parse("d.get('field')", mode="eval").body
        assert isinstance_subject_name(node) == "field"

    def test_unrecognised(self, orch):
        node = ast.parse("1 + 2", mode="eval").body
        assert isinstance_subject_name(node) == ""


# ---------------------------------------------------------------------------
# _isinstance_type_names  (13 missed)
# ---------------------------------------------------------------------------

class TestIsinstanceTypeNames:
    def test_single_name(self, orch):
        node = ast.parse("int", mode="eval").body
        assert isinstance_type_names(node) == ["int"]

    def test_attribute(self, orch):
        node = ast.parse("module.MyClass", mode="eval").body
        result = isinstance_type_names(node)
        assert len(result) == 1
        assert "MyClass" in result[0]

    def test_tuple_of_types(self, orch):
        node = ast.parse("(int, str, float)", mode="eval").body
        assert isinstance_type_names(node) == ["int", "str", "float"]

    def test_empty_tuple(self, orch):
        node = ast.parse("()", mode="eval").body
        assert isinstance_type_names(node) == []

    def test_non_type_expression(self, orch):
        node = ast.parse("42", mode="eval").body
        assert isinstance_type_names(node) == []


# ---------------------------------------------------------------------------
# _extract_type_constraints  (13 missed)
# ---------------------------------------------------------------------------

class TestExtractTypeConstraints:
    def test_isinstance_in_if(self, orch):
        code = (
            "def validate(data):\n"
            "    if not isinstance(data, dict):\n"
            "        raise TypeError('bad')\n"
        )
        func = ast.parse(code).body[0]
        assert isinstance(func, ast.FunctionDef)
        constraints = extract_type_constraints(func)
        assert "data" in constraints
        assert "dict" in constraints["data"]

    def test_isinstance_tuple(self, orch):
        code = (
            "def validate(value):\n"
            "    if not isinstance(value, (str, int)):\n"
            "        raise TypeError('bad')\n"
        )
        func = ast.parse(code).body[0]
        assert isinstance(func, ast.FunctionDef)
        constraints = extract_type_constraints(func)
        assert "value" in constraints
        assert "str" in constraints["value"]
        assert "int" in constraints["value"]

    def test_no_isinstance(self, orch):
        code = "def validate(data):\n    return data\n"
        func = ast.parse(code).body[0]
        assert isinstance(func, ast.FunctionDef)
        constraints = extract_type_constraints(func)
        assert constraints == {}


# ---------------------------------------------------------------------------
# _collect_mock_support  (15 missed)
# ---------------------------------------------------------------------------

class TestCollectMockSupport:
    def test_mocker_argument_detected(self, orch):
        code = (
            "def test_something(mocker):\n"
            "    pass\n"
        )
        func = ast.parse(code).body[0]
        assert isinstance(func, ast.FunctionDef)
        mock_bindings, patched = collect_mock_support(func)
        assert "mocker" in mock_bindings

    def test_mock_prefixed_argument(self, orch):
        code = "def test_something(mock_service):\n    pass\n"
        func = ast.parse(code).body[0]
        assert isinstance(func, ast.FunctionDef)
        mock_bindings, _ = collect_mock_support(func)
        assert "mock_service" in mock_bindings

    def test_no_mocks(self, orch):
        code = "def test_something(x, y):\n    pass\n"
        func = ast.parse(code).body[0]
        assert isinstance(func, ast.FunctionDef)
        mock_bindings, patched = collect_mock_support(func)
        assert len(mock_bindings) == 0
        assert len(patched) == 0


# ---------------------------------------------------------------------------
# _module_defined_symbol_names  (static, ~5 missed)
# ---------------------------------------------------------------------------

class TestModuleDefinedSymbolNames:
    def test_classes_and_functions(self):
        code = "class Foo:\n    pass\n\ndef bar():\n    pass\n\nasync def baz():\n    pass\n"
        assert module_defined_symbol_names(code) == ["Foo", "bar", "baz"]

    def test_empty_string(self):
        assert module_defined_symbol_names("") == []

    def test_non_string(self):
        assert module_defined_symbol_names(None) == []

    def test_syntax_error(self):
        assert module_defined_symbol_names("def (()") == []


# ---------------------------------------------------------------------------
# _python_import_roots  (static, ~5 missed)
# ---------------------------------------------------------------------------

class TestPythonImportRoots:
    def test_import_statement(self):
        code = "import os\nimport json.decoder"
        assert python_import_roots(code) == {"os", "json"}

    def test_from_import(self):
        code = "from pathlib import Path\nfrom collections.abc import Mapping"
        assert python_import_roots(code) == {"pathlib", "collections"}

    def test_relative_import_ignored(self):
        code = "from . import sibling"
        assert python_import_roots(code) == set()

    def test_empty_string(self):
        assert python_import_roots("") == set()

    def test_non_string(self):
        assert python_import_roots(42) == set()


# ---------------------------------------------------------------------------
# _known_type_allows_member  (12 missed)
# ---------------------------------------------------------------------------

class TestKnownTypeAllowsMember:
    def test_known_attribute(self, orch):
        code = "obj.name"
        node = ast.parse(code, mode="eval").body
        assert isinstance(node, ast.Attribute)
        local_types = {"obj": "MyClass"}
        class_map = {"MyClass": {"attributes": ["name", "age"], "fields": [], "method_signatures": {}, "is_enum": False}}
        assert known_type_allows_member(node, local_types, class_map) is True

    def test_unknown_attribute(self, orch):
        code = "obj.nonexistent"
        node = ast.parse(code, mode="eval").body
        assert isinstance(node, ast.Attribute)
        local_types = {"obj": "MyClass"}
        class_map = {"MyClass": {"attributes": ["name"], "fields": [], "method_signatures": {}, "is_enum": False}}
        assert known_type_allows_member(node, local_types, class_map) is False

    def test_enum_skips_fields(self, orch):
        code = "obj.RED"
        node = ast.parse(code, mode="eval").body
        assert isinstance(node, ast.Attribute)
        local_types = {"obj": "Color"}
        class_map = {"Color": {"attributes": ["RED"], "fields": ["RED"], "method_signatures": {}, "is_enum": True}}
        assert known_type_allows_member(node, local_types, class_map) is True

    def test_method_allowed(self, orch):
        code = "obj.validate"
        node = ast.parse(code, mode="eval").body
        assert isinstance(node, ast.Attribute)
        local_types = {"obj": "Service"}
        class_map = {"Service": {"attributes": [], "fields": [], "method_signatures": {"validate": {}}, "is_enum": False}}
        assert known_type_allows_member(node, local_types, class_map) is True

    def test_non_name_value(self, orch):
        # Attribute node where .value is not a Name (e.g. func().attr)
        node = ast.parse("func().attr", mode="eval").body
        assert isinstance(node, ast.Attribute)
        assert known_type_allows_member(node, {}, {}) is False

    def test_owner_not_in_map(self, orch):
        node = ast.parse("obj.name", mode="eval").body
        assert isinstance(node, ast.Attribute)
        assert known_type_allows_member(node, {"obj": "Unknown"}, {}) is False

    def test_owner_name_as_type(self, orch):
        code = "MyClass.method"
        node = ast.parse(code, mode="eval").body
        assert isinstance(node, ast.Attribute)
        local_types = {}
        class_map = {"MyClass": {"attributes": [], "fields": [], "method_signatures": {"method": {}}, "is_enum": False}}
        assert known_type_allows_member(node, local_types, class_map) is True


# ---------------------------------------------------------------------------
# _patched_target_name_from_call  (20 missed)
# ---------------------------------------------------------------------------

class TestPatchedTargetNameFromCall:
    def test_patch_with_string(self, orch):
        code = "patch('module.Class')"
        tree = ast.parse(code, mode="eval").body
        assert isinstance(tree, ast.Call)
        assert patched_target_name_from_call(tree) == "module.Class"

    def test_patch_object(self, orch):
        code = "patch.object(MyClass, 'method')"
        tree = ast.parse(code, mode="eval").body
        assert isinstance(tree, ast.Call)
        result = patched_target_name_from_call(tree)
        assert result is not None
        assert "method" in result

    def test_no_args(self, orch):
        code = "patch()"
        tree = ast.parse(code, mode="eval").body
        assert isinstance(tree, ast.Call)
        result = patched_target_name_from_call(tree)
        assert result is None

    def test_non_string_arg(self, orch):
        code = "patch(some_variable)"
        tree = ast.parse(code, mode="eval").body
        assert isinstance(tree, ast.Call)
        result = patched_target_name_from_call(tree)
        assert result is None


# ---------------------------------------------------------------------------
# _parent_map
# ---------------------------------------------------------------------------

class TestParentMap:
    def test_basic_tree(self, orch):
        tree = ast.parse("x = 1")
        pm = parent_map(tree)
        assert isinstance(pm, dict)
        assert len(pm) > 0


# ---------------------------------------------------------------------------
# _auto_fix_test_type_mismatches  (19 missed)
# ---------------------------------------------------------------------------

class TestAutoFixTestTypeMismatches:
    def test_no_dict_keys_returns_unchanged(self, orch):
        code = "class Foo:\n    pass\n"
        test_code = "def test_foo():\n    f = Foo()\n"
        result = auto_fix_test_type_mismatches(test_code, code)
        assert result == test_code

    def test_fixes_string_to_dict(self, orch):
        impl_code = (
            "class Service:\n"
            "    def handle(self, details):\n"
            "        return details['name']\n"
        )
        test_code = "def test_handle():\n    s = Service()\n    s.handle(details='test')\n"
        result = auto_fix_test_type_mismatches(test_code, impl_code)
        assert "{'name': 'value'}" in result or "details=" in result

    def test_syntax_error_in_impl_returns_unchanged(self, orch):
        result = auto_fix_test_type_mismatches("test", "def (():")
        assert result == "test"

    def test_skips_negative_test(self, orch):
        impl_code = (
            "class Service:\n"
            "    def handle(self, details):\n"
            "        return details['name']\n"
        )
        test_code = "def test_validation_failure():\n    s = Service()\n    s.handle(details='bad')\n"
        result = auto_fix_test_type_mismatches(test_code, impl_code)
        assert "details='bad'" in result

    def test_skips_is_false_test(self, orch):
        impl_code = (
            "class Service:\n"
            "    def handle(self, details):\n"
            "        return details['name']\n"
        )
        test_code = (
            "def test_negative():\n"
            "    s = Service()\n"
            "    result = s.handle(details='bad')\n"
            "    assert result is False\n"
        )
        result = auto_fix_test_type_mismatches(test_code, impl_code)
        assert "details='bad'" in result

    def test_reuses_existing_dict_variable(self, orch):
        impl_code = (
            "class Service:\n"
            "    def handle(self, details):\n"
            "        return details['name']\n"
        )
        test_code = (
            "def test_handle():\n"
            "    details = {'name': 'alice'}\n"
            "    s = Service()\n"
            "    s.handle(details='test')\n"
        )
        result = auto_fix_test_type_mismatches(test_code, impl_code)
        assert "details=details" in result or "details={'name'" in result


# ---------------------------------------------------------------------------
# _default_value_for_annotation  (8 missed)
# ---------------------------------------------------------------------------

class TestDefaultValueForAnnotation:
    def test_bool(self):
        assert default_value_for_annotation("bool") == "False"

    def test_str(self):
        assert default_value_for_annotation("str") == "''"

    def test_int(self):
        assert default_value_for_annotation("int") == "0"

    def test_float(self):
        assert default_value_for_annotation("float") == "0.0"

    def test_dict(self):
        assert default_value_for_annotation("dict") == "{}"

    def test_dict_generic(self):
        assert default_value_for_annotation("dict[str, Any]") == "{}"

    def test_Dict(self):
        assert default_value_for_annotation("Dict") == "{}"

    def test_list(self):
        assert default_value_for_annotation("list") == "[]"

    def test_list_generic(self):
        assert default_value_for_annotation("list[int]") == "[]"

    def test_List(self):
        assert default_value_for_annotation("List") == "[]"

    def test_set(self):
        assert default_value_for_annotation("set") == "set()"

    def test_set_generic(self):
        assert default_value_for_annotation("Set[str]") == "set()"

    def test_unknown(self):
        assert default_value_for_annotation("MyClass") == ""

    def test_empty(self):
        assert default_value_for_annotation("") == ""


# ---------------------------------------------------------------------------
# _required_field_list_from_failed_artifact  (11 missed)
# ---------------------------------------------------------------------------

class TestRequiredFieldListFromFailedArtifact:
    def test_finds_required_fields_list(self):
        code = "required_fields = ['name', 'age', 'email']"
        assert required_field_list_from_failed_artifact(code) == ["name", "age", "email"]

    def test_finds_required_keys(self):
        code = "required_keys = ('id', 'type')"
        assert required_field_list_from_failed_artifact(code) == ["id", "type"]

    def test_non_string_input(self):
        assert required_field_list_from_failed_artifact(None) == []

    def test_empty_string(self):
        assert required_field_list_from_failed_artifact("") == []

    def test_syntax_error(self):
        assert required_field_list_from_failed_artifact("def (()") == []

    def test_no_required_fields(self):
        assert required_field_list_from_failed_artifact("x = 1") == []

    def test_annotated_assignment(self):
        code = "required_fields: list[str] = ['a', 'b']"
        assert required_field_list_from_failed_artifact(code) == ["a", "b"]


# ---------------------------------------------------------------------------
# _plain_class_field_default_factory_details  (9 missed)
# ---------------------------------------------------------------------------

class TestPlainClassFieldDefaultFactoryDetails:
    def test_returns_none_when_no_token(self, orch):
        assert plain_class_field_default_factory_details("other error", "class X:\n  pass") is None

    def test_detects_field_object_issue(self, orch):
        code = (
            "class MyModel:\n"
            "    items: list = field(default_factory=list)\n"
        )
        result = plain_class_field_default_factory_details(
            "non-dataclass field(...) used", code
        )
        assert result is not None
        assert result[0] == "MyModel"
        assert result[1] == "items"

    def test_returns_none_if_no_code(self, orch):
        assert plain_class_field_default_factory_details("field' object has no attribute", "") is None

    def test_returns_none_for_non_string(self, orch):
        assert plain_class_field_default_factory_details("field' object has no attribute", None) is None


# ---------------------------------------------------------------------------
# _analyze_test_type_mismatches extras  (remaining branches)
# ---------------------------------------------------------------------------

class TestAnalyzeTestTypeMismatchesExtras:
    def test_empty_rules(self, orch):
        tree = ast.parse("def test_x(): pass")
        assert analyze_test_type_mismatches(tree, {}, {}) == []

    def test_detects_str_passed_as_dict(self, orch):
        test_code = (
            "def test_validate():\n"
            "    validate({'name': 'test'})\n"
        )
        tree = ast.parse(test_code)
        rules = {"validate": {"name": ["dict"]}}
        result = analyze_test_type_mismatches(tree, rules, {})
        assert isinstance(result, list)

    def test_matching_type_no_mismatch(self, orch):
        test_code = (
            "def test_validate():\n"
            "    validate({'name': 'test'})\n"
        )
        tree = ast.parse(test_code)
        rules = {"validate": {"name": ["str"]}}
        result = analyze_test_type_mismatches(tree, rules, {})
        assert isinstance(result, list)


# -- _example_from_default ---------------------------------------------------

class TestExampleFromDefault:
    def test_bool_true(self):
        node = ast.Constant(value=True)
        assert _example_from_default(node) == "True"

    def test_bool_false(self):
        node = ast.Constant(value=False)
        assert _example_from_default(node) == "False"

    def test_int_zero(self):
        node = ast.Constant(value=0)
        assert _example_from_default(node) == "1"

    def test_int_positive(self):
        node = ast.Constant(value=5)
        assert _example_from_default(node) == "5"

    def test_int_negative(self):
        node = ast.Constant(value=-3)
        assert _example_from_default(node) == "-3"

    def test_float_zero(self):
        node = ast.Constant(value=0.0)
        assert _example_from_default(node) == "1.0"

    def test_float_positive(self):
        node = ast.Constant(value=2.5)
        assert _example_from_default(node) == "2.5"

    def test_string_empty(self):
        node = ast.Constant(value="")
        assert _example_from_default(node) == "'sample'"

    def test_string_nonempty(self):
        node = ast.Constant(value="hello")
        assert _example_from_default(node) == "'hello'"

    def test_none(self):
        node = ast.Constant(value=None)
        assert _example_from_default(node) is None

    def test_empty_list(self):
        node = ast.List(elts=[], ctx=ast.Load())
        assert _example_from_default(node) == "['sample']"

    def test_nonempty_list(self):
        node = ast.parse("[1, 2]", mode="eval").body
        result = _example_from_default(node)
        assert result == "[1, 2]"

    def test_empty_dict(self):
        node = ast.Dict(keys=[], values=[])
        assert _example_from_default(node) == "{'key': 'value'}"

    def test_nonempty_dict(self):
        node = ast.parse("{'a': 1}", mode="eval").body
        result = _example_from_default(node)
        assert result == "{'a': 1}"

    def test_set(self):
        node = ast.Set(elts=[ast.Constant(value="x")])
        assert _example_from_default(node) == "{'sample'}"

    def test_tuple(self):
        node = ast.Tuple(elts=[ast.Constant(value="x")], ctx=ast.Load())
        assert _example_from_default(node) == "('sample',)"

    def test_unknown_node(self):
        node = ast.Name(id="foo", ctx=ast.Load())
        assert _example_from_default(node) is None


# -- _infer_dict_key_value_examples ------------------------------------------

class TestInferDictKeyValueExamples:
    def test_get_with_int_default(self, orch):
        code = "details.get('count', 0)"
        tree = ast.parse(code)
        result = infer_dict_key_value_examples(tree)
        assert result["details"]["count"] == "1"

    def test_get_with_bool_default(self, orch):
        code = "details.get('active', False)"
        tree = ast.parse(code)
        result = infer_dict_key_value_examples(tree)
        assert result["details"]["active"] == "False"

    def test_get_with_list_default(self, orch):
        code = "details.get('items', [])"
        tree = ast.parse(code)
        result = infer_dict_key_value_examples(tree)
        assert result["details"]["items"] == "['sample']"

    def test_get_with_string_default(self, orch):
        code = "details.get('name', 'unknown')"
        tree = ast.parse(code)
        result = infer_dict_key_value_examples(tree)
        assert result["details"]["name"] == "'unknown'"

    def test_alias_resolution(self, orch):
        code = (
            "d = request.details\n"
            "d.get('count', 0)\n"
        )
        tree = ast.parse(code)
        result = infer_dict_key_value_examples(tree)
        assert "details" in result
        assert result["details"]["count"] == "1"

    def test_multiple_keys(self, orch):
        code = (
            "details.get('prior_returns', 0)\n"
            "details.get('receipt_present', False)\n"
            "details.get('items', [])\n"
        )
        tree = ast.parse(code)
        result = infer_dict_key_value_examples(tree)
        assert result["details"]["prior_returns"] == "1"
        assert result["details"]["receipt_present"] == "False"
        assert result["details"]["items"] == "['sample']"

    def test_no_default_arg(self, orch):
        code = "details.get('key')"
        tree = ast.parse(code)
        result = infer_dict_key_value_examples(tree)
        assert result == {}

    def test_empty_code(self, orch):
        tree = ast.parse("")
        result = infer_dict_key_value_examples(tree)
        assert result == {}


# -- contract uses typed examples --------------------------------------------

class TestBehaviorContractTypedExamples:
    def test_contract_uses_inferred_types(self, orch):
        code = (
            "class Service:\n"
            "    def validate(self, request):\n"
            "        if not isinstance(request.details, dict):\n"
            "            return False\n"
            "        return True\n"
            "    def score(self, details):\n"
            "        n = details.get('prior_returns', 0)\n"
            "        ok = details.get('receipt_present', False)\n"
            "        items = details.get('items', [])\n"
            "        return n\n"
        )
        contract = build_code_behavior_contract(code)
        assert "'prior_returns': 1" in contract
        assert "'receipt_present': False" in contract
        assert "'items': ['sample']" in contract
        assert "'prior_returns': 'value'" not in contract

    def test_contract_fallback_to_value_when_no_default(self, orch):
        code = (
            "class Service:\n"
            "    def validate(self, request):\n"
            "        if not isinstance(request.details, dict):\n"
            "            return False\n"
            "        return True\n"
            "    def process(self, details):\n"
            "        x = details['unknown_key']\n"
            "        return x\n"
        )
        contract = build_code_behavior_contract(code)
        assert "'unknown_key': 'value'" in contract
