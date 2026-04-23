"""Direct coverage tests for QATesterAgent static methods."""

from kycortex_agents.agents.qa_tester import QATesterAgent


class TestQATesterStaticMethods:
    """Test QATesterAgent static utility methods."""

    def test_summary_has_active_issue_with_valid_summary(self):
        """Test detecting active issues in summary strings."""
        # Test with active issue marker - search is case-insensitive
        summary = "details: some error message"
        result = QATesterAgent._summary_has_active_issue(summary, "Details")
        assert result is True

    def test_summary_has_active_issue_with_none_value(self):
        """Test that 'none' values are treated as no active issue."""
        summary = "Details: none"
        result = QATesterAgent._summary_has_active_issue(summary, "Details")
        assert result is False

    def test_summary_has_active_issue_case_insensitive(self):
        """Test case-insensitive label matching."""
        summary = "details: error message"
        result = QATesterAgent._summary_has_active_issue(summary, "Details")
        assert result is True

    def test_summary_has_active_issue_no_marker(self):
        """Test when label is not in summary."""
        summary = "Some text without the marker"
        result = QATesterAgent._summary_has_active_issue(summary, "Details")
        assert result is False

    def test_summary_has_active_issue_non_string_input(self):
        """Test non-string input returns False."""
        result = QATesterAgent._summary_has_active_issue(123, "Details")
        assert result is False

    def test_summary_issue_value_extracts_value(self):
        """Test extracting issue value from summary."""
        summary = "- Details: error message text"
        result = QATesterAgent._summary_issue_value(summary, "Details")
        assert result == "error message text"

    def test_summary_issue_value_multiline(self):
        """Test extracting from multiline summary."""
        summary = "Some header\n- Constraint: maximum 100 tokens\nOther info"
        result = QATesterAgent._summary_issue_value(summary, "Constraint")
        assert result == "maximum 100 tokens"

    def test_summary_issue_value_none_value(self):
        """Test that 'none' is converted to empty string."""
        summary = "- Details: none"
        result = QATesterAgent._summary_issue_value(summary, "Details")
        assert result == ""

    def test_summary_issue_value_case_insensitive(self):
        """Test case-insensitive prefix matching."""
        summary = "- CONSTRAINT: some value"
        result = QATesterAgent._summary_issue_value(summary, "constraint")
        assert result == "some value"

    def test_summary_issue_value_no_match(self):
        """Test when label not found returns empty string."""
        summary = "- Other: value"
        result = QATesterAgent._summary_issue_value(summary, "Details")
        assert result == ""

    def test_summary_issue_value_non_string_input(self):
        """Test non-string input returns empty string."""
        result = QATesterAgent._summary_issue_value(None, "Details")
        assert result == ""

    def test_extract_failed_test_names_valid_summary(self):
        """Test extracting failed test names from validation summary."""
        summary = "FAILED test_module::test_function1\nFAILED test_module::test_function2"
        result = QATesterAgent._pytest_failed_test_names(summary)
        assert result == ["test_function1", "test_function2"]

    def test_extract_failed_test_names_deduplicates(self):
        """Test that duplicate test names are deduplicated."""
        summary = "FAILED test_module::test_func\nFAILED other::test_func"
        result = QATesterAgent._pytest_failed_test_names(summary)
        assert result == ["test_func"]

    def test_extract_failed_test_names_empty_summary(self):
        """Test empty or whitespace-only summary returns empty list."""
        assert QATesterAgent._pytest_failed_test_names("") == []
        assert QATesterAgent._pytest_failed_test_names("   ") == []

    def test_extract_failed_test_names_no_failures(self):
        """Test summary without failures returns empty list."""
        summary = "All tests passed"
        result = QATesterAgent._pytest_failed_test_names(summary)
        assert result == []

    def test_extract_failed_test_names_non_string_input(self):
        """Test non-string input returns empty list."""
        result = QATesterAgent._pytest_failed_test_names(123)
        assert result == []

    def test_is_validation_failure_test_name_valid_names(self):
        """Test detection of validation failure test names."""
        assert QATesterAgent._is_validation_failure_test_name("test_validation") is True
        assert QATesterAgent._is_validation_failure_test_name("test_invalid") is True
        assert QATesterAgent._is_validation_failure_test_name("test_reject") is True
        assert QATesterAgent._is_validation_failure_test_name("test_error") is True
        assert QATesterAgent._is_validation_failure_test_name("test_failure") is True

    def test_is_validation_failure_test_name_case_insensitive(self):
        """Test case-insensitive matching."""
        assert QATesterAgent._is_validation_failure_test_name("TEST_VALIDATION") is True
        assert QATesterAgent._is_validation_failure_test_name("Test_Invalid") is True

    def test_is_validation_failure_test_name_non_matching(self):
        """Test names that don't match validation failure patterns."""
        assert QATesterAgent._is_validation_failure_test_name("test_success") is False
        assert QATesterAgent._is_validation_failure_test_name("test_basic") is False

    def test_is_validation_failure_test_name_empty_input(self):
        """Test empty string returns False."""
        assert QATesterAgent._is_validation_failure_test_name("") is False
        assert QATesterAgent._is_validation_failure_test_name("   ") is False

    def test_test_function_block_extracts_function(self):
        """Test extracting a test function block from content."""
        content = '''def test_example():
    """Test docstring."""
    assert True

def test_other():
    assert False
'''
        result = QATesterAgent._test_function_block(content, "test_example")
        assert "def test_example():" in result
        assert 'assert True' in result
        # Should not include the next function
        assert "test_other" not in result

    def test_test_function_block_with_arguments(self):
        """Test extracting function with arguments."""
        content = '''def test_with_args(param1, param2):
    """Test with parameters."""
    return param1 + param2
'''
        result = QATesterAgent._test_function_block(content, "test_with_args")
        assert "def test_with_args(param1, param2):" in result
        assert "return param1 + param2" in result

    def test_test_function_block_function_not_found(self):
        """Test when function is not found returns empty string."""
        content = "def test_other():\n    pass"
        result = QATesterAgent._test_function_block(content, "test_missing")
        assert result == ""

    def test_test_function_block_empty_content(self):
        """Test empty content returns empty string."""
        result = QATesterAgent._test_function_block("", "test_func")
        assert result == ""

    def test_test_function_block_empty_test_name(self):
        """Test empty test name returns empty string."""
        content = "def test_example():\n    pass"
        result = QATesterAgent._test_function_block(content, "")
        assert result == ""

    def test_test_function_block_non_string_content(self):
        """Test non-string content returns empty string."""
        result = QATesterAgent._test_function_block(123, "test_func")
        assert result == ""
