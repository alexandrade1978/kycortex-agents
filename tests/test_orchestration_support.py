import ast
import os
import re
import stat
from types import SimpleNamespace

import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.orchestration.agent_runtime import build_agent_input, execute_agent
from kycortex_agents.orchestration.ast_tools import (
	AstNameReplacer,
	ast_name,
	attribute_chain,
	callable_name,
	expression_root_name,
	first_call_argument,
	is_pytest_fixture,
	render_expression,
)
from kycortex_agents.orchestration.artifacts import ArtifactPersistenceSupport
from kycortex_agents.orchestration.output_helpers import (
	normalize_agent_result,
	semantic_output_key,
	summarize_output,
	unredacted_agent_result,
)
from kycortex_agents.orchestration.private_files import (
	harden_private_directory_permissions,
	harden_private_file_permissions,
)
from kycortex_agents.orchestration.repair_analysis import (
	duplicate_constructor_explicit_rewrite_hint,
	invalid_outcome_missing_audit_trail_details,
	missing_import_nameerror_details,
	missing_object_attribute_details,
	nested_payload_wrapper_field_validation_details,
	plain_class_field_default_factory_details,
	render_name_list,
	required_field_list_from_failed_artifact,
	suggest_declared_attribute_replacement,
)
from kycortex_agents.orchestration.repair_code_validation import (
	build_code_validation_repair_lines,
)
from kycortex_agents.orchestration.repair_focus import (
	build_repair_focus_lines,
)
from kycortex_agents.orchestration.repair_test_validation import (
	build_test_validation_repair_lines,
)
from kycortex_agents.orchestration.repair_signals import (
	content_has_incomplete_required_evidence_payload,
	content_has_matching_datetime_import,
	implementation_prefers_direct_datetime_import,
	implementation_required_evidence_items,
	validation_summary_has_missing_datetime_import_issue,
	validation_summary_has_required_evidence_runtime_issue,
)
from kycortex_agents.orchestration.repair_test_analysis import (
	analyze_test_repair_surface,
	is_helper_alias_like_name,
	module_defined_symbol_names,
	normalized_helper_surface_symbols,
	previous_valid_test_surface,
	validation_summary_helper_alias_names,
)
from kycortex_agents.orchestration.repair_test_runtime import (
	build_runtime_only_test_repair_lines,
)
from kycortex_agents.orchestration.repair_test_structure import (
	build_structural_test_repair_lines,
)
from kycortex_agents.orchestration.repair_instructions import (
	build_code_repair_instruction_from_test_failure,
	build_repair_instruction,
)
from kycortex_agents.orchestration.sandbox_execution import (
	execute_generated_module_import,
	execute_generated_tests,
	sandbox_security_violation,
	write_generated_import_runner,
	write_generated_test_runner,
)
from kycortex_agents.orchestration.sandbox_runtime import (
	build_generated_test_env,
	build_sandbox_preexec_fn,
	looks_like_secret_env_var,
	sanitize_generated_filename,
)
from kycortex_agents.orchestration.sandbox_templates import (
	render_generated_import_runner,
	render_generated_test_runner,
	render_sandbox_sitecustomize,
)
from kycortex_agents.orchestration.test_ast_analysis import (
	collect_local_name_bindings,
	collect_mock_support,
	collect_parametrized_argument_names,
	collect_test_local_types,
	collect_undefined_local_names,
	extract_parametrize_argument_names,
	find_unsupported_mock_assertions,
	function_argument_names,
	is_mock_factory_call,
	is_patch_call,
	patched_target_name_from_call,
)
from kycortex_agents.orchestration.task_constraints import (
	compact_architecture_context,
	should_compact_architecture_context,
	task_exact_top_level_test_count,
	task_fixture_budget,
	task_line_budget,
	task_max_top_level_test_count,
	task_requires_cli_entrypoint,
)
from kycortex_agents.orchestration.validation_reporting import (
	build_code_validation_summary,
	build_dependency_validation_summary,
	build_test_validation_summary,
	completion_diagnostics_from_provider_call,
	completion_diagnostics_summary,
	completion_validation_issue,
	looks_structurally_truncated,
)
from kycortex_agents.orchestration.validation_runtime import (
	provider_call_metadata,
	redact_validation_execution_result,
	sanitize_output_provider_call_metadata,
	summarize_pytest_output,
)
from kycortex_agents.orchestration.validation_analysis import (
	pytest_contract_overreach_signals,
	pytest_failure_details,
	pytest_failure_is_semantic_assertion_mismatch,
	pytest_failure_origin,
	validation_has_blocking_issues,
	validation_has_only_warnings,
	validation_has_static_issues,
)
from kycortex_agents.orchestration.workflow_control import (
	privacy_safe_log_fields,
	task_id_collection_count,
	task_id_count_log_field_name,
	validate_agent_resolution,
)
from kycortex_agents.orchestration.workflow_acceptance import (
	evaluate_workflow_acceptance,
	observed_failure_categories,
	task_acceptance_lists,
)
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import AgentInput, AgentOutput, ArtifactRecord, ArtifactType, ExecutionSandboxPolicy, FailureCategory, TaskStatus


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")
def test_harden_private_file_permissions_sets_mode_600(tmp_path):
	artifact_path = tmp_path / "artifact.txt"
	artifact_path.write_text("secret", encoding="utf-8")
	artifact_path.chmod(0o644)

	harden_private_file_permissions(artifact_path)

	assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")
def test_harden_private_directory_permissions_sets_mode_700(tmp_path):
	directory_path = tmp_path / "artifacts"
	directory_path.mkdir()
	directory_path.chmod(0o755)

	harden_private_directory_permissions(directory_path)

	assert stat.S_IMODE(directory_path.stat().st_mode) == 0o700


def test_artifact_persistence_support_redacts_and_updates_relative_path(tmp_path):
	support = ArtifactPersistenceSupport(output_dir=str(tmp_path / "output"))
	artifacts = [
		ArtifactRecord(
			name="Report Draft",
			artifact_type=ArtifactType.DOCUMENT,
			content="Authorization: Bearer sk-ant-secret-987654",
			path="reports/final draft.md",
		)
	]

	support.persist_artifacts(artifacts)
	persisted_path = tmp_path / "output" / "reports" / "final_draft.md"
	persisted_content = persisted_path.read_text(encoding="utf-8")

	assert artifacts[0].path == "reports/final_draft.md"
	assert artifacts[0].content == persisted_content
	assert persisted_content == "Authorization: Bearer [REDACTED]"


def test_execute_agent_prefers_execute_then_run_with_input_then_run_directly():
	agent_input = AgentInput(
		task_id="task-1",
		task_title="Task",
		task_description="Do work",
		project_name="Demo",
		project_goal="Build demo",
		context={"key": "value"},
	)

	class ExecuteAgent:
		def execute(self, received_input: AgentInput) -> str:
			assert received_input is agent_input
			return "execute"

	class RunWithInputAgent:
		def run_with_input(self, received_input: AgentInput) -> str:
			assert received_input is agent_input
			return "run_with_input"

	class RunAgent:
		def run(self, task_description: str, context: dict[str, object]) -> str:
			assert task_description == "Do work"
			assert context == {"key": "value"}
			return "run"

	assert execute_agent(ExecuteAgent(), agent_input) == "execute"
	assert execute_agent(RunWithInputAgent(), agent_input) == "run_with_input"
	assert execute_agent(RunAgent(), agent_input) == "run"


def test_build_agent_input_uses_repair_defaults_directly():
	project = ProjectState(project_name="Demo", goal="Build demo")
	task = Task(
		id="repair",
		title="Repair architecture",
		description="Repair the architecture",
		assigned_to="architect",
		repair_context={
			"instruction": "",
			"failure_category": "",
			"failure_message": "   ",
			"validation_summary": "   ",
		},
	)

	agent_input = build_agent_input(task, project, {}, repair_focus_lines=[])

	assert "Repair objective:" in agent_input.task_description
	assert "Repair the previous failure." in agent_input.task_description
	assert f"Previous failure category: {FailureCategory.UNKNOWN.value}" in agent_input.task_description
	assert "Previous failure message:" not in agent_input.task_description
	assert "Validation summary:" not in agent_input.task_description


def test_build_agent_input_includes_source_failure_metadata_directly():
	project = ProjectState(project_name="Demo", goal="Build demo")
	task = Task(
		id="code",
		title="Implementation",
		description="Write code",
		assigned_to="code_engineer",
		repair_context={
			"cycle": 1,
			"failure_category": FailureCategory.CODE_VALIDATION.value,
			"source_failure_task_id": "tests",
			"source_failure_category": FailureCategory.TEST_VALIDATION.value,
			"instruction": "Repair the generated Python module.",
			"failure_message": "module import failed",
			"validation_summary": "Generated test validation:\n- Verdict: FAIL",
		},
	)

	agent_input = build_agent_input(
		task,
		project,
		{"budget_decomposition_brief": "Stay within the budget."},
		repair_focus_lines=["Repair the failing import first."],
	)

	assert "Source failure task: tests" in agent_input.task_description
	assert "Source failure category: test_validation" in agent_input.task_description
	assert "Previous failure message: module import failed" in agent_input.task_description
	assert "Budget decomposition brief:" in agent_input.task_description
	assert "Repair priorities:" in agent_input.task_description
	assert "- Repair the failing import first." in agent_input.task_description


def test_artifact_persistence_support_rejects_symlink_escape(tmp_path):
	support = ArtifactPersistenceSupport(output_dir=str(tmp_path / "output"))
	escaped_root = tmp_path / "escaped"
	escaped_root.mkdir()
	(tmp_path / "output").mkdir()
	linked_dir = tmp_path / "output" / "artifacts"
	linked_dir.symlink_to(escaped_root, target_is_directory=True)
	artifacts = [
		ArtifactRecord(
			name="Report Draft",
			artifact_type=ArtifactType.DOCUMENT,
			content="hello",
			path="artifacts/final.md",
		)
	]

	with pytest.raises(AgentExecutionError, match="resolves outside the output directory"):
		support.persist_artifacts(artifacts)

	assert not (escaped_root / "final.md").exists()
	assert artifacts[0].path == "artifacts/final.md"


def test_artifact_persistence_support_rejects_invalid_segment_from_injected_sanitizer(tmp_path):
	def fake_sub(pattern: str, replacement: str, value: str) -> str:
		if value == "unsafe":
			return "."
		return re.sub(pattern, replacement, value)

	support = ArtifactPersistenceSupport(
		output_dir=str(tmp_path / "output"),
		sanitize_sub=fake_sub,
	)

	with pytest.raises(AgentExecutionError, match="artifact path contains an invalid segment"):
		support.sanitize_artifact_relative_path("reports/unsafe/summary.md")


def test_ast_name_replacer_rewrites_names_in_expression():
	expression = ast.parse("foo + bar", mode="eval").body
	rewritten = AstNameReplacer(
		{
			"foo": ast.Constant(value=10),
			"bar": ast.Name(id="baz", ctx=ast.Load()),
		}
	).visit(expression)

	assert ast.unparse(ast.fix_missing_locations(rewritten)) == "10 + baz"


def test_test_ast_analysis_helpers_collect_parametrized_names_and_bindings_directly():
	function_node = ast.parse(
		"@pytest.mark.parametrize('item, expected', [('a', 1)])\n"
		"def test_case(item, other_fixture):\n"
		"    first, *rest = [1, 2, 3]\n"
		"    with helper() as alias:\n"
		"        total = first\n"
		"    import logging as log\n"
		"    return alias, rest, total, log, expected\n"
	).body[0]
	assert isinstance(function_node, ast.FunctionDef)

	assert function_argument_names(function_node) == {"item", "other_fixture"}
	assert collect_parametrized_argument_names(function_node) == {"item", "expected"}
	bindings = collect_local_name_bindings(function_node)
	assert {"item", "other_fixture", "expected", "first", "rest", "alias", "total", "log"}.issubset(bindings)
	keyword_decorator = ast.parse(
		"@pytest.mark.parametrize(argnames='left, right', argvalues=[(1, 2)])\n"
		"def test_keyword(left, right):\n"
		"    return left + right\n"
	).body[0].decorator_list[0]
	assert isinstance(keyword_decorator, ast.Call)
	assert extract_parametrize_argument_names(keyword_decorator) == {"left", "right"}


def test_test_ast_analysis_helpers_detect_undefined_names_patch_targets_and_mocks_directly():
	function_node = ast.parse(
		"def test_case(mocker):\n"
		"    from unittest.mock import MagicMock, patch\n"
		"    mock_logger = MagicMock()\n"
		"    patched = patch('logging.getLogger')\n"
		"    with patch.object(logger, 'info') as patched_info:\n"
		"        assert mock_logger.info.call_count == 0\n"
		"    return missing_name\n"
	).body[0]
	assert isinstance(function_node, ast.FunctionDef)

	undefined_names = collect_undefined_local_names(function_node, set())
	assert undefined_names == ["logger (line 5)", "missing_name (line 7)"]
	mock_bindings, patched_targets = collect_mock_support(function_node)
	assert {"mocker", "mock_logger", "patched", "patched_info"}.issubset(mock_bindings)
	assert patched_targets == {"logger.info", "logging.getLogger"}
	assert is_mock_factory_call(ast.parse("MagicMock()", mode="eval").body) is True
	assert is_patch_call(ast.parse("patch.object(logger, 'info')", mode="eval").body) is True
	patch_call = ast.parse("patch.object(logger, 'info')", mode="eval").body
	assert isinstance(patch_call, ast.Call)
	assert patched_target_name_from_call(patch_call) == "logger.info"


def test_test_ast_analysis_helpers_find_unsupported_mock_assertions_and_local_types_directly():
	function_node = ast.parse(
		"def test_case():\n"
		"    service = Service()\n"
		"    assert logging.getLogger().info.call_count == 1\n"
	).body[0]
	assert isinstance(function_node, ast.FunctionDef)
	local_types = collect_test_local_types(
		function_node,
		{"Service": {"method_signatures": {}, "attributes": [], "fields": [], "is_enum": False}},
		{},
		lambda node, local_types, class_map, function_map: "Service"
		if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Service"
		else None,
	)
	assert local_types == {"service": "Service"}
	assert find_unsupported_mock_assertions(function_node, local_types, {}) == [
		"logging.getLogger().info.call_count (line 3)"
	]


def test_render_sandbox_sitecustomize_returns_dedented_script():
	script = render_sandbox_sitecustomize()

	assert script.startswith("import asyncio\n")
	assert "sandbox policy blocked filesystem write outside sandbox root" in script
	assert script.endswith("\n")


def test_render_generated_test_runner_includes_configured_paths(tmp_path):
	script = render_generated_test_runner(
		sandbox_enabled=True,
		pytest_config_path=str(tmp_path / "pytest.ini"),
		rootdir_path=str(tmp_path),
		pytest_log_path=str(tmp_path / "pytest.log"),
		test_filename="generated_tests.py",
	)

	assert 'sandbox_sitecustomize = TMP_PATH / "sitecustomize.py"' in script
	assert repr(str(tmp_path / "pytest.ini")) in script
	assert repr("generated_tests.py") in script
	assert "pytest.main(pytest_args)" in script


def test_render_generated_import_runner_includes_module_filename():
	script = render_generated_import_runner(
		sandbox_enabled=False,
		module_filename="code_under_test.py",
	)

	assert 'TMP_PATH / "sitecustomize.py"' in script
	assert repr("code_under_test.py") in script
	assert '"code_under_test"' in script


def test_looks_like_secret_env_var_detects_generic_secret_markers():
	assert looks_like_secret_env_var("OPENAI_API_KEY") is True
	assert looks_like_secret_env_var("client_secret") is True
	assert looks_like_secret_env_var("NORMAL_ENV") is False


def test_sanitize_generated_filename_strips_traversal_and_preserves_suffix():
	assert sanitize_generated_filename("../../tests generated", "generated_tests.py") == "tests_generated.py"
	assert sanitize_generated_filename("custom-name", "generated_tests.py") == "custom-name.py"


def test_build_generated_test_env_writes_sandbox_bindings_and_sitecustomize(tmp_path):
	policy = KYCortexConfig(output_dir=str(tmp_path / "output")).execution_sandbox_policy()
	env = build_generated_test_env(tmp_path, policy, host_env={"PATH": "/usr/bin", "PYTHONPATH": "/tmp/injected"})

	assert env["PATH"] == str(tmp_path)
	assert env["HOME"] == str(tmp_path)
	assert env["KYCORTEX_SANDBOX_ROOT"] == str(tmp_path)
	assert env["PYTHONDONTWRITEBYTECODE"] == "1"
	assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
	assert "PYTHONPATH" not in env
	assert (tmp_path / "sitecustomize.py").read_text(encoding="utf-8").startswith("import asyncio\n")


def test_build_generated_test_env_omits_sandbox_files_when_disabled(tmp_path):
	policy = ExecutionSandboxPolicy(enabled=False)
	env = build_generated_test_env(tmp_path, policy, host_env={"PATH": "/usr/bin", "PYTHONPATH": "/tmp/injected"})

	assert env["PATH"] == "/usr/bin"
	assert "KYCORTEX_SANDBOX_ROOT" not in env
	assert "XDG_CONFIG_HOME" not in env
	assert "PYTHONPATH" not in env
	assert not (tmp_path / "sitecustomize.py").exists()


def test_build_sandbox_preexec_fn_applies_limits_with_injected_modules():
	policy = ExecutionSandboxPolicy(enabled=True, max_cpu_seconds=5.2, max_memory_mb=128)
	recorded_calls: list[tuple[object, tuple[int, int]]] = []
	recorded_umasks: list[int] = []
	fake_os = SimpleNamespace(name="posix", umask=lambda value: recorded_umasks.append(value) or 0)
	fake_resource = SimpleNamespace(
		RLIMIT_CPU="cpu",
		RLIMIT_AS="as",
		RLIMIT_CORE="core",
		RLIMIT_FSIZE="fsize",
		setrlimit=lambda limit, values: recorded_calls.append((limit, values)),
	)

	preexec = build_sandbox_preexec_fn(policy, os_module=fake_os, resource_module=fake_resource)

	assert callable(preexec)
	preexec()
	assert recorded_umasks == [0o077]
	assert recorded_calls == [
		("cpu", (5, 5)),
		("as", (134217728, 134217728)),
		("core", (0, 0)),
		("fsize", (1048576, 1048576)),
	]


def test_write_generated_runner_helpers_persist_scripts(tmp_path):
	pytest_runner = write_generated_test_runner(tmp_path, "generated_tests.py", sandbox_enabled=True)
	import_runner = write_generated_import_runner(tmp_path, "generated_module.py", sandbox_enabled=False)

	assert pytest_runner.name == "_kycortex_run_pytest.py"
	assert import_runner.name == "_kycortex_import_module.py"
	assert "generated_tests.py" in pytest_runner.read_text(encoding="utf-8")
	assert "generated_module.py" in import_runner.read_text(encoding="utf-8")


def test_execute_generated_tests_returns_unavailable_when_pytest_missing_directly(tmp_path):
	policy = KYCortexConfig(output_dir=str(tmp_path / "output")).execution_sandbox_policy()

	result = execute_generated_tests(
		"generated_module.py",
		"def ok():\n    return 1\n",
		"generated_tests.py",
		"def test_ok():\n    assert True\n",
		policy,
		pytest_spec_finder=lambda name: None,
	)

	assert result == {
		"available": False,
		"ran": False,
		"returncode": None,
		"summary": "pytest is not installed in the current environment",
	}


def test_execute_generated_module_import_redacts_sensitive_output_directly(tmp_path):
	policy = KYCortexConfig(output_dir=str(tmp_path / "output")).execution_sandbox_policy()

	def fake_run(*args, **kwargs):
		return SimpleNamespace(
			returncode=1,
			stdout="api_key=sk-secret-123456",
			stderr="Authorization: Bearer sk-ant-secret-987654",
		)

	result = execute_generated_module_import(
		"generated_module.py",
		"def ok():\n    return 1\n",
		policy,
		subprocess_run=fake_run,
	)

	assert result["ran"] is True
	assert result["returncode"] == 1
	assert "[REDACTED]" in result["stdout"]
	assert "[REDACTED]" in result["stderr"]
	assert "sk-secret-123456" not in result["summary"]


def test_sandbox_security_violation_detects_blocked_message():
	assert sandbox_security_violation(RuntimeError("sandbox policy blocked filesystem write outside sandbox root")) is True
	assert sandbox_security_violation(RuntimeError("provider temporarily unavailable")) is False


def test_validation_reporting_detects_structural_truncation_and_completion_summary():
	assert looks_structurally_truncated("label:\n", "expected an indented block") is True
	assert looks_structurally_truncated("value = 1\n", "invalid syntax") is False
	assert completion_validation_issue({"hit_token_limit": True}) == "output likely truncated at the completion token limit"
	assert completion_diagnostics_summary({"done_reason": "stop"}) == "provider termination reason recorded"


def test_completion_diagnostics_from_provider_call_marks_length_limited_output_as_truncated():
	diagnostics = completion_diagnostics_from_provider_call(
		{
			"requested_max_tokens": 900,
			"finish_reason": "length",
			"usage": {"output_tokens": 900},
		},
		syntax_ok=False,
	)

	assert diagnostics == {
		"requested_max_tokens": 900,
		"output_tokens": 900,
		"finish_reason": "length",
		"stop_reason": None,
		"done_reason": None,
		"hit_token_limit": True,
		"likely_truncated": True,
	}


def test_build_code_validation_summary_reports_import_and_contract_failures_directly():
	summary = build_code_validation_summary(
		{"syntax_ok": True, "third_party_imports": [], "line_count": 12, "line_budget": 20},
		"failed import",
		completion_diagnostics={"output_tokens": 120},
		import_validation={"ran": True, "returncode": 1, "summary": "TypeError"},
		task_public_contract_preflight={
			"anchor_present": True,
			"passed": False,
			"public_facade": "ComplianceIntakeService",
			"issues": ["missing public facade ComplianceIntakeService"],
		},
	)

	assert "Line count: 12/20" in summary
	assert "Completion diagnostics: token usage recorded" in summary
	assert "Module import: FAIL" in summary
	assert "Task public contract: FAIL" in summary


def test_build_test_validation_summary_reports_warning_override_and_pytest_details_directly():
	summary = build_test_validation_summary(
		{
			"syntax_ok": True,
			"constructor_arity_mismatches": ["MyClass (line 5)"],
		},
		{
			"available": True,
			"ran": True,
			"returncode": 0,
			"summary": "1 passed",
		},
	)

	assert "Constructor arity mismatches (warning): MyClass (line 5)" in summary
	assert "Pytest execution: PASS" in summary
	assert summary.endswith("- Verdict: PASS (warnings overridden by pytest)")


def test_build_dependency_validation_summary_formats_failures_directly():
	summary = build_dependency_validation_summary(
		{
			"required_imports": ["requests"],
			"declared_packages": ["urllib3"],
			"missing_manifest_entries": ["requests"],
			"unused_manifest_entries": ["urllib3"],
			"is_valid": False,
		}
	)

	assert summary == (
		"Dependency manifest validation:\n"
		"- Required third-party imports: requests\n"
		"- Declared packages: urllib3\n"
		"- Missing manifest entries: requests\n"
		"- Unused manifest entries: urllib3\n"
		"- Provenance violations: none\n"
		"- Verdict: FAIL"
	)


def test_output_helpers_summarize_and_classify_titles_directly():
	assert summarize_output("   ") == ""
	assert summarize_output("  first line  \nsecond line") == "first line"
	assert len(summarize_output("x" * 200)) == 120
	assert semantic_output_key("unknown", "Architecture Review") == "architecture"
	assert semantic_output_key("unknown", "Misc Task") is None


def test_output_helpers_normalize_and_restore_unredacted_results_directly():
	normalized = normalize_agent_result("  first line  \nsecond line")
	assert normalized.summary == "first line"
	assert normalized.raw_content == "  first line  \nsecond line"

	structured = AgentOutput(summary="ready", raw_content="RAW")
	assert normalize_agent_result(structured) is structured

	class FakeAgent:
		def _consume_last_unredacted_output(self):
			return AgentOutput(summary="unredacted", raw_content="SECRET")

	assert unredacted_agent_result(FakeAgent(), structured).summary == "unredacted"
	assert unredacted_agent_result(object(), structured) is structured


def test_ast_tools_render_names_and_detect_pytest_fixtures_directly():
	node = ast.Attribute(value=ast.Attribute(value=ast.Name("pkg"), attr="module"), attr="Class")
	assert ast_name(node) == "pkg.module.Class"
	assert ast_name(ast.Constant("x")) == "x"

	fixture_function = ast.parse("@pytest.fixture\ndef sample():\n    return 1\n").body[0]
	assert isinstance(fixture_function, ast.FunctionDef)
	assert is_pytest_fixture(fixture_function) is True

	call_node = ast.Call(func=ast.Attribute(value=ast.Name("service"), attr="validate_request"), args=[ast.Constant("payload")], keywords=[])
	keyword_only_call = ast.Call(func=ast.Name("process_request"), args=[], keywords=[ast.keyword(arg="payload", value=ast.Name("payload"))])
	assert callable_name(call_node) == "validate_request"
	assert attribute_chain(call_node.func) == "service.validate_request"
	assert expression_root_name(call_node.func) == "service"
	assert render_expression(call_node) == "service.validate_request('payload')"
	assert isinstance(first_call_argument(keyword_only_call), ast.Name)
	assert ast_name(ast.Subscript(value=ast.Name("Payload"), slice=ast.Constant(None))) == "Payload"
	assert callable_name(ast.Call(func=ast.Lambda(args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=ast.Constant(None)), args=[], keywords=[])) == ""
	assert attribute_chain(ast.Constant(1)) == ""
	assert expression_root_name(ast.Constant(1)) is None
	assert first_call_argument(ast.Call(func=ast.Name("noop"), args=[], keywords=[])) is None


def test_workflow_acceptance_helpers_build_lists_and_zero_budget_safety_directly():
	project = ProjectState(project_name="Demo", goal="Build demo")
	project.add_task(
		Task(
			id="code",
			title="Implementation",
			description="Implement",
			assigned_to="code_engineer",
			required_for_acceptance=True,
		)
	)
	project.add_task(
		Task(
			id="docs",
			title="Documentation",
			description="Document",
			assigned_to="docs_writer",
		)
	)
	project.tasks[0].status = TaskStatus.DONE.value
	project.tasks[1].status = TaskStatus.FAILED.value
	project.tasks[1].last_error_category = FailureCategory.SANDBOX_SECURITY_VIOLATION.value

	required_lists = task_acceptance_lists(project, "required_tasks")
	assert required_lists["evaluated_task_ids"] == ["code"]
	assert required_lists["completed_task_ids"] == ["code"]

	observed_categories = observed_failure_categories(project)
	assert observed_categories == {FailureCategory.SANDBOX_SECURITY_VIOLATION.value}

	evaluation = evaluate_workflow_acceptance(
		project,
		"required_tasks",
		frozenset({FailureCategory.SANDBOX_SECURITY_VIOLATION.value}),
	)
	assert evaluation["accepted"] is False
	assert evaluation["failed_lane_ids"] == ["real_workflow", "safety"]
	assert evaluation["acceptance_lanes"]["productivity"]["accepted"] is True
	assert evaluation["acceptance_lanes"]["safety"]["zero_budget_failure_categories"] == [
		FailureCategory.SANDBOX_SECURITY_VIOLATION.value
	]


def test_validate_agent_resolution_raises_for_unknown_registry_entry_directly():
	project = ProjectState(project_name="Demo", goal="Build demo")
	project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))

	class EmptyRegistry:
		def has(self, _assigned_to: str) -> bool:
			return False

	with pytest.raises(AgentExecutionError, match="unknown agent 'architect'"):
		validate_agent_resolution(EmptyRegistry(), project)


def test_private_file_hardening_raises_agent_error_on_chmod_failure(tmp_path, monkeypatch):
	artifact_path = tmp_path / "artifact.txt"
	artifact_path.write_text("secret", encoding="utf-8")

	def fail_chmod(_self: object, _mode: int) -> None:
		raise OSError("denied")

	monkeypatch.setattr(type(artifact_path), "chmod", fail_chmod)

	with pytest.raises(AgentExecutionError, match="could not harden file permissions"):
		harden_private_file_permissions(artifact_path)


def test_private_directory_hardening_raises_agent_error_on_chmod_failure(tmp_path, monkeypatch):
	directory_path = tmp_path / "artifacts"
	directory_path.mkdir()

	def fail_chmod(_self: object, _mode: int) -> None:
		raise OSError("denied")

	monkeypatch.setattr(type(directory_path), "chmod", fail_chmod)

	with pytest.raises(AgentExecutionError, match="could not harden directory permissions"):
		harden_private_directory_permissions(directory_path)


def test_private_permission_hardening_skips_non_posix_and_attribute_chain_handles_none(tmp_path, monkeypatch):
	monkeypatch.setattr(os, "name", "nt", raising=False)

	harden_private_file_permissions(tmp_path / "missing.txt")
	harden_private_directory_permissions(tmp_path / "missing-dir")

	assert attribute_chain(None) == ""


def test_build_repair_instruction_specializes_missing_import_directly():
	instruction = build_repair_instruction(
		"code-task",
		"code_validation",
		last_error="NameError: name 'logging' is not defined",
		failed_code="logger = logging.getLogger(__name__)",
		validation={},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: ("logging", "logger = logging.getLogger(__name__)"),
		plain_class_field_default_factory_details=lambda error, code: None,
		test_validation_has_only_warnings=lambda validation: False,
	)

	assert "references logging during module import but never imports it" in instruction
	assert "logger = logging.getLogger(__name__)" in instruction


def test_build_repair_instruction_uses_pytest_warning_focus_directly():
	instruction = build_repair_instruction(
		"tests-task",
		"test_validation",
		last_error="",
		failed_code="",
		validation={
			"test_analysis": {"type_mismatches": ["str vs int at line 10"]},
			"test_execution": {"ran": True, "returncode": 1, "summary": "1 failed"},
		},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: None,
		plain_class_field_default_factory_details=lambda error, code: None,
		test_validation_has_only_warnings=lambda validation: True,
	)

	assert "type mismatches in test arguments" in instruction
	assert "Use the correct argument types" in instruction


def test_build_repair_instruction_covers_missing_import_plain_class_and_warning_only_variants_directly():
	instruction = build_repair_instruction(
		"code-task",
		"code_validation",
		last_error="NameError: name 'logging' is not defined",
		failed_code="logger = build_logger()",
		validation={},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: ("logging", "logger = build_logger()"),
		plain_class_field_default_factory_details=lambda error, code: None,
		test_validation_has_only_warnings=lambda validation: False,
	)

	assert "Do not return that line unchanged" in instruction
	assert "logger = build_logger()" in instruction

	plain_class_instruction = build_repair_instruction(
		"code-task",
		"code_validation",
		last_error="AttributeError: 'Field' object has no attribute 'append'",
		failed_code="class AuditService:\n    audit_history = field(default_factory=list)\n",
		validation={},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: None,
		plain_class_field_default_factory_details=lambda error, code: ("AuditService", "audit_history"),
		test_validation_has_only_warnings=lambda validation: False,
	)

	assert "AuditService.audit_history" in plain_class_instruction
	assert "Initialize self.audit_history inside __init__" in plain_class_instruction

	warning_only_instruction = build_repair_instruction(
		"tests-task",
		"test_validation",
		last_error="",
		failed_code="",
		validation={
			"test_analysis": {"type_mismatches": []},
			"test_execution": {"ran": True, "returncode": 1, "summary": "1 failed"},
		},
		dataclass_default_order_repair_examples=lambda code: [],
		missing_import_nameerror_details=lambda error, code: None,
		plain_class_field_default_factory_details=lambda error, code: None,
		test_validation_has_only_warnings=lambda validation: True,
	)

	assert "Focus on the actual pytest failure details" in warning_only_instruction


def test_build_code_repair_instruction_from_test_failure_handles_duplicate_constructor_binding_directly():
	instruction = build_code_repair_instruction_from_test_failure(
		"summary",
		"failed code",
		duplicate_constructor_argument_details=lambda summary: ("ComplianceRequest", "details"),
		duplicate_constructor_argument_call_hint=lambda summary, code: "ComplianceRequest(request_id, details, **request.details)",
		duplicate_constructor_explicit_rewrite_hint=lambda summary, code: "ComplianceRequest(request_id=request.request_id, details=request.details)",
		plain_class_field_default_factory_details=lambda summary, code: None,
		missing_object_attribute_details=lambda summary, code: None,
		suggest_declared_attribute_replacement=lambda attribute_name, class_fields: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda summary, code: None,
		invalid_outcome_missing_audit_trail_details=lambda summary, tests, code: None,
		internal_constructor_strictness_details=lambda summary, code: None,
	)

	assert "passes details twice to ComplianceRequest(...)" in instruction
	assert "ComplianceRequest(request_id, details, **request.details)" in instruction
	assert "ComplianceRequest(request_id=request.request_id, details=request.details)" in instruction


def test_build_code_repair_instruction_from_test_failure_uses_generic_strictness_fallback_directly():
	instruction = build_code_repair_instruction_from_test_failure(
		"summary",
		"failed code",
		duplicate_constructor_argument_details=lambda summary: None,
		duplicate_constructor_argument_call_hint=lambda summary, code: None,
		duplicate_constructor_explicit_rewrite_hint=lambda summary, code: None,
		plain_class_field_default_factory_details=lambda summary, code: None,
		missing_object_attribute_details=lambda summary, code: None,
		suggest_declared_attribute_replacement=lambda attribute_name, class_fields: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda summary, code: None,
		invalid_outcome_missing_audit_trail_details=lambda summary, tests, code: None,
		internal_constructor_strictness_details=lambda summary, code: ("ComplianceRequest", ["details", "status"], ["request_id"]),
	)

	assert "ComplianceRequest(...) still requires details, status" in instruction
	assert "validator only requires request_id" in instruction


def test_build_code_repair_instruction_from_test_failure_covers_remaining_branch_variants_directly():
	missing_attribute_instruction = build_code_repair_instruction_from_test_failure(
		"summary",
		"failed code",
		duplicate_constructor_argument_details=lambda summary: None,
		duplicate_constructor_argument_call_hint=lambda summary, code: None,
		duplicate_constructor_explicit_rewrite_hint=lambda summary, code: None,
		plain_class_field_default_factory_details=lambda summary, code: None,
		missing_object_attribute_details=lambda summary, code: ("VendorProfile", "audit_log", []),
		suggest_declared_attribute_replacement=lambda attribute_name, class_fields: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda summary, code: None,
		invalid_outcome_missing_audit_trail_details=lambda summary, tests, code: None,
		internal_constructor_strictness_details=lambda summary, code: None,
	)

	assert "that attribute is not defined on the returned object" in missing_attribute_instruction
	assert "VendorProfile must declare audit_log" in missing_attribute_instruction

	invalid_outcome_instruction = build_code_repair_instruction_from_test_failure(
		"summary",
		"failed code",
		duplicate_constructor_argument_details=lambda summary: None,
		duplicate_constructor_argument_call_hint=lambda summary, code: None,
		duplicate_constructor_explicit_rewrite_hint=lambda summary, code: None,
		plain_class_field_default_factory_details=lambda summary, code: None,
		missing_object_attribute_details=lambda summary, code: None,
		suggest_declared_attribute_replacement=lambda attribute_name, class_fields: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda summary, code: None,
		invalid_outcome_missing_audit_trail_details=lambda summary, tests, code: (
			["test_invalid_path"],
			"audit_log",
			"TriageOutcome(outcome='invalid', audit_log='')",
			False,
		),
		internal_constructor_strictness_details=lambda summary, code: None,
	)

	assert "returns TriageOutcome(outcome='invalid', audit_log='') with an empty audit_log" in invalid_outcome_instruction

	strictness_instruction = build_code_repair_instruction_from_test_failure(
		"summary",
		"failed code",
		duplicate_constructor_argument_details=lambda summary: None,
		duplicate_constructor_argument_call_hint=lambda summary, code: None,
		duplicate_constructor_explicit_rewrite_hint=lambda summary, code: None,
		plain_class_field_default_factory_details=lambda summary, code: None,
		missing_object_attribute_details=lambda summary, code: None,
		suggest_declared_attribute_replacement=lambda attribute_name, class_fields: None,
		render_name_list=lambda names: ", ".join(names),
		nested_payload_wrapper_field_validation_details=lambda summary, code: None,
		invalid_outcome_missing_audit_trail_details=lambda summary, tests, code: None,
		internal_constructor_strictness_details=lambda summary, code: ("ComplianceRequest", ["details"], []),
	)

	assert "makes ComplianceRequest(...) require details" in strictness_instruction
	assert "instead of demanding new input fields" in strictness_instruction


def test_missing_import_nameerror_details_extracts_symbol_and_line_directly():
	details = missing_import_nameerror_details(
		"Generated code validation:\n- Module import: FAIL\n- Import summary: NameError: name 'logging' is not defined\n- Verdict: FAIL",
		"from dataclasses import dataclass\nlogger = logging.getLogger(__name__)\n",
	)

	assert details == ("logging", "logger = logging.getLogger(__name__)")


def test_required_field_and_nested_wrapper_detection_work_directly():
	failed_code = (
		"def validate_request(request):\n"
		"    required_fields = {'request_id', 'request_type', 'details'}\n"
		"    return required_fields.issubset(request.details)\n"
	)

	assert required_field_list_from_failed_artifact(failed_code) == ["request_id", "request_type", "details"]
	assert nested_payload_wrapper_field_validation_details(
		"FAILED tests_tests.py::test_happy_path - ValueError: Invalid request\nFAILED tests_tests.py::test_batch_processing - ValueError: Invalid request",
		failed_code,
	) == (
		"details",
		["request_id", "request_type", "details"],
		"return required_fields.issubset(request.details)",
	)


def test_plain_class_field_default_factory_details_detects_runtime_placeholder_directly():
	failed_code = (
		"from dataclasses import field\n\n"
		"class ComplianceIntakeService:\n"
		"    audit_history: list[dict] = field(default_factory=list)\n"
	)

	assert plain_class_field_default_factory_details(
		"AttributeError: 'Field' object has no attribute 'append'",
		failed_code,
	) == ("ComplianceIntakeService", "audit_history")


def test_missing_object_attribute_and_replacement_helpers_work_directly():
	failed_code = (
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class VendorProfile:\n"
		"    certifications: list[str]\n"
		"    incidents: list[str]\n"
	)

	class_name, attribute_name, class_fields = missing_object_attribute_details(
		"AttributeError: 'VendorProfile' object has no attribute 'expired_certifications'",
		failed_code,
	)

	assert (class_name, attribute_name) == ("VendorProfile", "expired_certifications")
	assert class_fields == ["certifications", "incidents"]
	assert suggest_declared_attribute_replacement(attribute_name, class_fields) == "certifications"
	assert render_name_list(class_fields) == "certifications and incidents"


def test_duplicate_constructor_rewrite_hint_and_invalid_audit_detection_work_directly():
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

	assert duplicate_constructor_explicit_rewrite_hint(
		"TypeError: VendorProfile.__init__() got multiple values for argument 'vendor_id'",
		failed_code,
	) == (
		"VendorProfile(vendor_id=vendor_id, service_category=request.details['service_category'], "
		"due_diligence_evidence=request.details['due_diligence_evidence'], "
		"is_sanctioned=request.details.get('is_sanctioned', False))"
	)

	invalid_path_code = (
		"from dataclasses import dataclass\n\n"
		"@dataclass\n"
		"class TriageOutcome:\n"
		"    outcome: str\n"
		"    risk_score: float\n"
		"    audit_log: str = ''\n\n"
		"def handle_request(request):\n"
		"    return TriageOutcome(outcome='invalid', risk_score=0.0)\n"
	)
	tests_code = (
		"def test_validation_failure(service, invalid_request):\n"
		"    result = service.handle_request(invalid_request)\n"
		"    assert result.outcome == 'invalid'\n"
		"    assert len(result.audit_log) > 0\n"
	)

	assert invalid_outcome_missing_audit_trail_details(
		"FAILED tests_tests.py::test_validation_failure - AssertionError: assert 0 > 0",
		tests_code,
		invalid_path_code,
	) == (
		["test_validation_failure"],
		"audit_log",
		"TriageOutcome(outcome='invalid', risk_score=0.0)",
		True,
	)


def test_datetime_repair_signals_detect_missing_imports_directly():
	failed_tests = (
		"from code_implementation import ComplianceRequest\n\n"
		"def test_request():\n"
		"    request = ComplianceRequest(request_id='req-1', timestamp=datetime.now())\n"
	)

	assert content_has_matching_datetime_import("from datetime import datetime\n") is True
	assert validation_summary_has_missing_datetime_import_issue(
		"Generated test validation:\n- Undefined local names: datetime (line 5)\n- Verdict: FAIL",
		failed_tests,
	) is True
	assert implementation_prefers_direct_datetime_import("from datetime import datetime\n\ndef build():\n    return datetime.now()\n") is True


def test_required_evidence_repair_signals_detect_incomplete_payloads_directly():
	implementation_code = (
		"def validate_request(request):\n"
		"    required_evidence = ['ID', 'Address', 'Proof of Income']\n"
		"    return all(item in request.details.get('documents', []) for item in required_evidence)\n"
	)
	failed_tests = (
		"def test_happy_path():\n"
		"    request = {'documents': ['ID']}\n"
		"    assert len(service.risk_scores) == 1\n"
	)

	assert implementation_required_evidence_items(implementation_code) == ["ID", "Address", "Proof of Income"]
	assert content_has_incomplete_required_evidence_payload(failed_tests, implementation_code) is True
	assert validation_summary_has_required_evidence_runtime_issue(
		"Generated test validation:\n- Pytest execution: FAIL\n- Pytest failure details: FAILED tests_tests.py::test_happy_path - AssertionError: assert 0 == 1\n- Verdict: FAIL",
		"risk_scores = []\n" + failed_tests,
		implementation_code,
	) is True


def test_module_defined_symbol_names_and_helper_alias_detection_work_directly():
	implementation_code = (
		"class ComplianceIntakeService:\n"
		"    pass\n\n"
		"def validate_request(request):\n"
		"    return True\n"
	)
	validation_summary = (
		"Generated test validation:\n"
		"- Undefined local names: AuditLogger (line 6), validate_request (line 9)\n"
		"- Verdict: FAIL"
	)

	assert module_defined_symbol_names(implementation_code) == ["ComplianceIntakeService", "validate_request"]
	assert validation_summary_helper_alias_names(validation_summary, implementation_code) == ["AuditLogger"]


def test_repair_test_analysis_helpers_cover_duplicate_blank_and_non_string_inputs_directly():
	assert normalized_helper_surface_symbols([1, "AuditLogger (line 2)", "AuditLogger (line 4)", " "]) == ["AuditLogger"]
	assert module_defined_symbol_names("def validate_request():\n    return True\n\ndef validate_request():\n    return False\n") == ["validate_request"]
	assert is_helper_alias_like_name("   ") is False


def test_previous_valid_test_surface_extracts_member_calls_and_constructor_keywords_directly():
	failed_tests = (
		"from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
		"def test_happy_path():\n"
		"    service = ComplianceIntakeService()\n"
		"    request = ComplianceRequest(request_id='req-1', request_type='screening', details={}, timestamp=1.0)\n"
		"    service.handle_request(request)\n"
	)

	member_calls, constructor_keywords = previous_valid_test_surface(
		failed_tests,
		["ComplianceIntakeService", "ComplianceRequest"],
	)

	assert member_calls == {"ComplianceIntakeService": ["handle_request"]}
	assert constructor_keywords == {
		"ComplianceRequest": ["request_id", "request_type", "details", "timestamp"]
	}


def test_analyze_test_repair_surface_collects_reusable_imports_and_alias_drift_directly():
	implementation_code = (
		"class AuditLogger:\n"
		"    pass\n\n"
		"class ComplianceIntakeService:\n"
		"    def handle_request(self, request):\n"
		"        return None\n"
	)
	validation_summary = (
		"Generated test validation:\n"
		"- Imported module symbols: ComplianceIntakeService\n"
		"- Undefined local names: AuditLogger (line 6), AuditService (line 8), pytest (line 10)\n"
		"- Unknown module symbols: none\n"
		"- Verdict: FAIL"
	)
	failed_tests = (
		"from code_implementation import ComplianceIntakeService\n\n"
		"def test_happy_path():\n"
		"    service = ComplianceIntakeService()\n"
		"    service.handle_request(None)\n"
	)

	analysis = analyze_test_repair_surface(
		validation_summary,
		implementation_code,
		failed_tests,
	)

	assert analysis.imported_module_symbols == ["ComplianceIntakeService"]
	assert analysis.undefined_available_module_symbols == ["AuditLogger"]
	assert analysis.helper_alias_names == ["AuditService"]
	assert analysis.previous_member_calls == {"ComplianceIntakeService": ["handle_request"]}


def test_repair_surface_helpers_cover_invalid_inputs_and_inline_constructor_calls_directly():
	assert validation_summary_helper_alias_names(None, "") == []
	assert previous_valid_test_surface("def broken(:\n", ["ComplianceRequest"]) == ({}, {})

	member_calls, constructor_keywords = previous_valid_test_surface(
		(
			"from code_implementation import ComplianceRequest\n\n"
			"def test_inline_call():\n"
			"    ComplianceRequest(request_id='req-1').validate_request()\n"
		),
		["ComplianceRequest"],
	)

	assert member_calls == {"ComplianceRequest": ["validate_request"]}
	assert constructor_keywords == {"ComplianceRequest": ["request_id"]}
	analysis = analyze_test_repair_surface(None)
	assert analysis.imported_module_symbols == []
	assert analysis.previous_constructor_keywords == {}


def test_build_runtime_only_test_repair_lines_handles_helper_runtime_focus_directly():
	lines = build_runtime_only_test_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- imported module symbols: validate_request, score_request, log_audit\n"
			"- unknown module symbols: none\n"
			"- constructor arity mismatches: none\n"
			"- pytest execution: fail\n"
		),
		failed_content_lower="def test_log_audit():\n    assert len(service.audit_logs) == 3\n",
		imported_module_symbols=["validate_request", "score_request", "log_audit"],
		unknown_module_symbols=[],
		previous_member_calls={},
		previous_constructor_keywords={},
		required_evidence_runtime_issue=False,
		required_evidence_items=[],
	)

	assert any("collapse the suite to exactly three tests" in line for line in lines)
	assert any("Delete standalone score_request, log_audit, and extra invalid-case tests" in line for line in lines)
	assert any("When behavior is uncertain, prefer stable invariants" in line for line in lines)


def test_build_code_validation_repair_lines_handles_constructor_and_attribute_guidance_directly():
	lines = build_code_validation_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- pytest execution: fail\n"
			"- pytest failure details: failed tests_tests.py::test_happy_path - typeerror: vendorprofile.__init__() got multiple values for argument 'vendor_id'\n"
		),
		failed_content_lower="return vendorprofile(vendor_id, **request.details)\nreturn profile.expired_certifications\n",
		dataclass_order_examples=[],
		duplicate_constructor_argument_details=("VendorProfile", "vendor_id"),
		duplicate_constructor_call_hint="VendorProfile(vendor_id, **request.details)",
		duplicate_constructor_explicit_rewrite_hint=(
			"VendorProfile(vendor_id=vendor_id, service_category=request.details['service_category'], "
			"due_diligence_evidence=request.details['due_diligence_evidence'], "
			"is_sanctioned=request.details.get('is_sanctioned', False))"
		),
		missing_attribute_details=("VendorProfile", "expired_certifications", ["certifications", "incidents"]),
		nested_payload_wrapper_details=None,
		constructor_strictness_details=None,
		plain_class_field_details=None,
		missing_import_details=None,
	)

	assert any("got multiple values for argument 'vendor_id'" in line for line in lines)
	assert any("VendorProfile(vendor_id, **request.details)" in line for line in lines)
	assert any("VendorProfile currently defines certifications and incidents" in line for line in lines)
	assert any("Prefer replacing .expired_certifications with .certifications" in line for line in lines)


def test_build_code_validation_repair_lines_handles_dataclass_import_and_line_budget_directly():
	lines = build_code_validation_repair_lines(
		summary_lower=(
			"generated code validation:\n"
			"- module import: fail\n"
			"- import summary: typeerror: non-default argument 'details' follows default argument\n"
			"- import summary: nameerror: name 'logging' is not defined\n"
			"- line count: 312/300\n"
			"- verdict: fail\n"
		),
		failed_content_lower="logger = logging.getlogger(__name__)\n",
		dataclass_order_examples=[
			"The current failed artifact still has this ordering bug in ReviewAction. Rewrite it as ReviewAction(action_id, action_type, details, timestamp=field(default_factory=datetime.now))."
		],
		duplicate_constructor_argument_details=None,
		duplicate_constructor_call_hint="",
		duplicate_constructor_explicit_rewrite_hint="",
		missing_attribute_details=None,
		nested_payload_wrapper_details=None,
		constructor_strictness_details=None,
		plain_class_field_details=None,
		missing_import_details=("logging", "logger = logging.getLogger(__name__)"),
	)

	assert any("reorder the fields so every required non-default field appears before any field with a default" in line for line in lines)
	assert any("ReviewAction(action_id, action_type, details, timestamp=field(default_factory=datetime.now))" in line for line in lines)
	assert any("add `import logging` before first use" in line for line in lines)
	assert any("Rewrite the full module smaller and leave clear headroom below the reported line ceiling" in line for line in lines)


def test_build_code_validation_repair_lines_handles_nested_payload_and_timezone_guidance_directly():
	lines = build_code_validation_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- pytest execution: fail\n"
			"- pytest failure details: failed tests_tests.py::test_batch_processing - valueerror: invalid return case\n"
			"- pytest failure details: failed tests_tests.py::test_risk_scoring_with_certifications - typeerror: can't compare offset-naive and offset-aware datetimes\n"
		),
		failed_content_lower="required_fields = {'request_id', 'request_type', 'details'}\nreturn required_fields.issubset(request.details)\n",
		dataclass_order_examples=[],
		duplicate_constructor_argument_details=None,
		duplicate_constructor_call_hint="",
		duplicate_constructor_explicit_rewrite_hint="",
		missing_attribute_details=None,
		nested_payload_wrapper_details=("details", ["request_id", "request_type", "details"], "return required_fields.issubset(request.details)"),
		constructor_strictness_details=None,
		plain_class_field_details=None,
		missing_import_details=None,
	)

	assert any("treats request_id, request_type, and details as required keys inside request.details" in line for line in lines)
	assert any("Do not return the broken validation line `return required_fields.issubset(request.details)` unchanged" in line for line in lines)
	assert any("Normalize every datetime comparison to one timezone convention before comparing timestamps." in line for line in lines)


def test_build_code_validation_repair_lines_covers_remaining_guidance_variants_directly():
	lines = build_code_validation_repair_lines(
		summary_lower=(
			"generated code validation:\n"
			"- task public contract: fail\n"
			"- pytest failed: assertionerror: assert true is false\n"
			"- import summary: name 'field' is not defined\n"
			"- import summary: likely truncated\n"
			"- pytest failure details: failed tests_tests.py::test_happy_path - valueerror: invalid request\n"
			"- typeerror: request object is not subscriptable\n"
			"- nameerror: datetime is missing\n"
		),
		failed_content_lower="required_fields = {'request_id'}\nreturn required_fields.issubset(request.payload)\nreturn datetime.datetime.now()\n",
		dataclass_order_examples=[],
		duplicate_constructor_argument_details=None,
		duplicate_constructor_call_hint="",
		duplicate_constructor_explicit_rewrite_hint="",
		missing_attribute_details=("AuditResult", "audit_log", []),
		nested_payload_wrapper_details=("payload", ["request_id", "payload"], None),
		constructor_strictness_details=("ComplianceRequest", ["details", "status"], []),
		plain_class_field_details=("AuditService", "history"),
		missing_import_details=("timezone", None),
	)

	assert any("Treat the task public contract anchor as exact" in line for line in lines)
	assert any("If you keep .audit_log in the rewritten module, declare it on AuditResult" in line for line in lines)
	assert any("Do not make ComplianceRequest(...) additionally require details and status" in line for line in lines)
	assert any("import field explicitly from dataclasses" in line for line in lines)
	assert any("because timezone is referenced before it is imported" in line for line in lines)
	assert any("AuditService.history with field(...) on a non-dataclass class" in line for line in lines)
	assert any("rewrite the full module from the top instead of patching a partial tail" in line for line in lines)


def test_build_code_validation_repair_lines_covers_non_module_qualified_missing_import_directly():
	lines = build_code_validation_repair_lines(
		summary_lower="generated code validation:\n- module import: fail\n",
		failed_content_lower="logger = build_logger()\n",
		dataclass_order_examples=[],
		duplicate_constructor_argument_details=None,
		duplicate_constructor_call_hint="",
		duplicate_constructor_explicit_rewrite_hint="",
		missing_attribute_details=None,
		nested_payload_wrapper_details=None,
		constructor_strictness_details=None,
		plain_class_field_details=None,
		missing_import_details=("logging", "logger = build_logger()"),
	)

	assert any("references logging before it is imported" in line for line in lines)
	assert any("logger = build_logger()" in line for line in lines)


def test_build_runtime_only_test_repair_lines_handles_return_shape_and_did_not_raise_directly():
	lines = build_runtime_only_test_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- exact return-shape attribute assumption\n"
			"- pytest execution: fail\n"
			"- pytest failure details: failed tests_tests.py::test_validation_failure - failed: did not raise <class 'valueerror'>\n"
		),
		failed_content_lower="def test_happy_path():\n    assert outcome.request_id == '1'\n",
		imported_module_symbols=[],
		unknown_module_symbols=[],
		previous_member_calls={},
		previous_constructor_keywords={},
		required_evidence_runtime_issue=False,
		required_evidence_items=[],
	)

	assert any("wrapped object return shape" in line for line in lines)
	assert any("rebuild that scenario around an input that actually violates the current validator or contract" in line for line in lines)
	assert any("reserve pytest.raises only for an input that the current validator demonstrably rejects" in line for line in lines)


def test_build_structural_test_repair_lines_handles_budget_and_assertionless_guidance_directly():
	lines = build_structural_test_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- line count: 206/150\n"
			"- top-level test functions: 14/7 max\n"
			"- fixture count: 4/3\n"
			"- tests without assertion-like checks: test_happy_path (line 5), test_batch_processing (line 16)\n"
		),
		failed_content_lower="",
		imported_module_symbols=[],
		undefined_available_module_symbols=[],
		helper_alias_names=[],
		unknown_module_symbols=[],
		helper_surface_symbols=[],
		assertionless_tests=["test_happy_path (line 5)", "test_batch_processing (line 16)"],
		missing_datetime_import_issue=False,
		implementation_prefers_direct_datetime_import=False,
	)

	assert any("Reduce scope aggressively: target 3 to 4 top-level tests" in line for line in lines)
	assert any("The validation summary already flagged these hollow top-level tests" in line for line in lines)
	assert any("discard the current pytest skeleton and rewrite the entire suite from scratch" in line for line in lines)


def test_build_structural_test_repair_lines_handles_alias_drift_and_missing_imports_directly():
	lines = build_structural_test_repair_lines(
		summary_lower="generated test validation:\n- undefined local names: datetime (line 10), auditlogger (line 6)\n- pytest execution: fail\n",
		failed_content_lower="timestamp=request.timestamp",
		imported_module_symbols=["AuditLog", "ComplianceIntakeService", "ComplianceRequest"],
		undefined_available_module_symbols=["AuditLogger"],
		helper_alias_names=["AuditLogger"],
		unknown_module_symbols=[],
		helper_surface_symbols=[],
		assertionless_tests=[],
		missing_datetime_import_issue=True,
		implementation_prefers_direct_datetime_import=True,
	)

	assert any("timestamp=fixed_time instead of timestamp=request.timestamp" in line for line in lines)
	assert any("The previous file referenced real module symbols without importing them: AuditLogger." in line for line in lines)
	assert any("undefined helper or collaborator aliases outside the documented import surface: AuditLogger" in line for line in lines)
	assert any("The current implementation already imports `from datetime import datetime`" in line for line in lines)


def test_build_structural_test_repair_lines_warns_on_helper_alias_near_match_pairs_directly():
	lines = build_structural_test_repair_lines(
		summary_lower="generated test validation:\n- undefined local names: AuditLogger\n",
		failed_content_lower="",
		imported_module_symbols=["AuditLoggerService"],
		undefined_available_module_symbols=[],
		helper_alias_names=["AuditLogger"],
		unknown_module_symbols=[],
		helper_surface_symbols=[],
		assertionless_tests=[],
		missing_datetime_import_issue=False,
		implementation_prefers_direct_datetime_import=False,
	)

	assert any("AuditLogger -> AuditLoggerService" in line for line in lines)


def test_build_structural_test_repair_lines_handles_invalid_member_references_and_exact_alias_match_directly():
	lines = build_structural_test_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- undefined local names: AuditLogger\n"
			"- invalid member references: ComplianceIntakeService.submit, ComplianceIntakeService.submit_batch\n"
		),
		failed_content_lower="",
		imported_module_symbols=["AuditLogger", "ComplianceIntakeService"],
		undefined_available_module_symbols=[],
		helper_alias_names=["AuditLogger"],
		unknown_module_symbols=[],
		helper_surface_symbols=[],
		assertionless_tests=[],
		missing_datetime_import_issue=False,
		implementation_prefers_direct_datetime_import=False,
	)

	assert any("invalid member references are reported" in line for line in lines)
	assert any("invalid-member list is empty" in line for line in lines)


def test_build_structural_test_repair_lines_handles_payload_and_fixture_constraints_directly():
	lines = build_structural_test_repair_lines(
		summary_lower=(
			"generated test validation:\n"
			"- payload contract violations: get_logs payload missing required fields: action, record_id at line 14\n"
			"- non-batch sequence calls: score_request does not accept batch/list inputs at line 46\n"
			"- reserved fixture names: request (line 5)\n"
			"- unsupported mock assertions: mock.assert_called_once() without patch\n"
		),
		failed_content_lower="",
		imported_module_symbols=[],
		undefined_available_module_symbols=[],
		helper_alias_names=[],
		unknown_module_symbols=[],
		helper_surface_symbols=[],
		assertionless_tests=[],
		missing_datetime_import_issue=False,
		implementation_prefers_direct_datetime_import=False,
	)

	assert any("provide every required field or omit that optional payload entirely" in line for line in lines)
	assert any("Keep scalar functions scalar" in line for line in lines)
	assert any("Never define a custom fixture named request." in line for line in lines)
	assert any("Do not use mock-style assertion bookkeeping" in line for line in lines)


def test_build_test_validation_repair_lines_handles_type_mismatch_and_helper_surface_fallback_directly():
	lines = build_test_validation_repair_lines(
		validation_summary=(
			"Generated test validation:\n"
			"- Type mismatches: details expects dict but test uses str at line 8\n"
			"- Imported module symbols: ComplianceIntakeService, ComplianceRequest\n"
			"- Helper surface usages: RiskScoringService (line 33)\n"
			"- Tests without assertion-like checks: test_happy_path (line 5)\n"
			"- Verdict: FAIL"
		),
		failed_artifact_content=(
			"from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
			"def test_happy_path():\n"
			"    service = ComplianceIntakeService()\n"
			"    request = ComplianceRequest(request_id='req-1', request_type='screening', details='details')\n"
			"    service.handle_request(request)\n"
		),
		implementation_code="class RiskScoringService:\n    pass\n",
		helper_surface_symbols=[],
		helper_surface_usages=["RiskScoringService (line 33)"],
		missing_datetime_import_issue=False,
		required_evidence_runtime_issue=False,
		required_evidence_items=[],
		implementation_prefers_direct_datetime_import=False,
	)

	assert any("PRIORITY: Fix type mismatches before other repairs" in line for line in lines)
	assert any("Replace string placeholders like details='details'" in line for line in lines)
	assert any("references these flagged helper surfaces: RiskScoringService" in line for line in lines)
	assert any("The validation summary already flagged these hollow top-level tests: test_happy_path (line 5)." in line for line in lines)


def test_build_test_validation_repair_lines_composes_available_imports_and_runtime_guidance_directly():
	lines = build_test_validation_repair_lines(
		validation_summary=(
			"Generated test validation:\n"
			"- Imported module symbols: AuditLog, ComplianceIntakeService, ComplianceRequest\n"
			"- Undefined local names: datetime (line 18), AuditLogger (line 6)\n"
			"- Pytest execution: FAIL\n"
			"- Constructor arity mismatches: none\n"
			"- Verdict: FAIL"
		),
		failed_artifact_content=(
			"from code_implementation import AuditLog, ComplianceIntakeService, ComplianceRequest\n\n"
			"def test_happy_path():\n"
			"    service = ComplianceIntakeService()\n"
			"    request = ComplianceRequest(request_id='req-1', request_type='screening', details={'source': 'web'}, timestamp=datetime.now())\n"
			"    service.handle_request(request)\n"
		),
		implementation_code=(
			"from datetime import datetime\n\n"
			"class AuditLogger:\n"
			"    pass\n"
		),
		helper_surface_symbols=[],
		helper_surface_usages=[],
		missing_datetime_import_issue=True,
		required_evidence_runtime_issue=False,
		required_evidence_items=[],
		implementation_prefers_direct_datetime_import=True,
	)

	assert any("The previous file referenced real module symbols without importing them: AuditLogger." in line for line in lines)
	assert any("The current implementation already imports `from datetime import datetime`" in line for line in lines)
	assert any("preserve its valid imports, constructor shapes, fixture payload structure, and scenario skeleton" in line for line in lines)


def test_build_repair_focus_lines_dispatches_code_validation_directly():
	lines = build_repair_focus_lines(
		repair_context={
			"failure_category": "code_validation",
			"validation_summary": (
				"Generated code validation:\n"
				"- Module import: FAIL\n"
				"- Import summary: NameError: name 'logging' is not defined\n"
				"- Verdict: FAIL"
			),
			"failed_artifact_content": (
				"from dataclasses import dataclass\n\n"
				"logger = logging.getLogger(__name__)\n"
			),
		},
		context={},
	)

	assert any("logger = logging.getLogger(__name__)" in line for line in lines)
	assert any("import logging" in line for line in lines)


def test_build_repair_focus_lines_dispatches_test_validation_directly():
	lines = build_repair_focus_lines(
		repair_context={
			"failure_category": "test_validation",
			"validation_summary": (
				"Generated test validation:\n"
				"- Type mismatches: details expects dict but test uses str at line 8\n"
				"- Imported module symbols: ComplianceIntakeService, ComplianceRequest\n"
				"- Helper surface usages: RiskScoringService (line 33)\n"
				"- Tests without assertion-like checks: test_happy_path (line 5)\n"
				"- Verdict: FAIL"
			),
			"failed_artifact_content": (
				"from code_implementation import ComplianceIntakeService, ComplianceRequest\n\n"
				"def test_happy_path():\n"
				"    service = ComplianceIntakeService()\n"
				"    request = ComplianceRequest(request_id='req-1', request_type='screening', details='details')\n"
				"    service.handle_request(request)\n"
			),
			"helper_surface_usages": ["RiskScoringService (line 33)"],
		},
		context={"code": "class RiskScoringService:\n    pass\n"},
	)

	assert any("PRIORITY: Fix type mismatches before other repairs" in line for line in lines)
	assert any("references these flagged helper surfaces: RiskScoringService" in line for line in lines)


def test_summarize_pytest_output_handles_empty_and_fallback_cases_directly():
	assert summarize_pytest_output("", "", 5) == "pytest exited with code 5"
	assert summarize_pytest_output("line one", "line two", 1) == "line two"


def test_redact_validation_execution_result_redacts_sensitive_values():
	result = redact_validation_execution_result(
		{
			"stdout": "api_key=sk-secret-123456",
			"stderr": "Authorization: Bearer sk-ant-secret-987654",
		}
	)

	assert "sk-secret-123456" not in str(result)
	assert "sk-ant-secret-987654" not in str(result)
	assert "[REDACTED]" in result["stdout"]
	assert "[REDACTED]" in result["stderr"]


def test_provider_call_metadata_prefers_output_and_redacts_sensitive_fields():
	output = AgentOutput(
		summary="ok",
		raw_content="ok",
		metadata={
			"provider_call": {
				"provider": "anthropic",
				"model": "claude-test",
				"base_url": "https://bob:secret-pass@example.com/messages",
				"error_message": "Authorization: Bearer sk-ant-secret-987654",
			}
		},
	)

	metadata = provider_call_metadata(object(), output)

	assert metadata is not None
	assert metadata["provider"] == "anthropic"
	assert metadata["model"] == "claude-test"
	assert "secret-pass" not in str(metadata)
	assert "sk-ant-secret-987654" not in str(metadata)


def test_sanitize_output_provider_call_metadata_updates_output_copy_in_place():
	output = AgentOutput(
		summary="ok",
		raw_content="ok",
		metadata={
			"provider_call": {
				"provider": "openai",
				"base_url": "https://alice:secret-pass@example.com/v1",
			}
		},
	)

	sanitized = sanitize_output_provider_call_metadata(output)

	assert sanitized is output
	assert "secret-pass" not in str(sanitized.metadata["provider_call"])
	assert "[REDACTED]" in sanitized.metadata["provider_call"]["base_url"]


def test_task_constraint_helpers_parse_limits_and_optional_inputs_directly():
	task = Task(
		id="tests",
		title="Tests",
		description=(
			"Write exactly 2 top-level test functions at most 3 fixtures and under 40 lines. "
			"Include a CLI demo entrypoint."
		),
		assigned_to="qa_tester",
	)

	assert task_line_budget(task) == 40
	assert task_requires_cli_entrypoint(task) is True
	assert task_exact_top_level_test_count(task) == 2
	assert task_max_top_level_test_count(task) is None
	assert task_fixture_budget(task) == 3
	assert task_line_budget(None) is None
	assert task_requires_cli_entrypoint(None) is False


def test_should_compact_architecture_context_uses_budget_and_repair_signals_directly():
	anchor = "- Public facade: ComplianceIntakeService"
	budget_task = Task(
		id="code",
		title="Implementation",
		description="Write one Python module under 300 lines.",
		assigned_to="code_engineer",
	)
	repair_task = Task(
		id="code_repair",
		title="Repair",
		description="Write one Python module.",
		assigned_to="code_engineer",
		repair_context={"cycle": 1},
	)

	assert should_compact_architecture_context(budget_task, anchor, "code_engineer", 900) is True
	assert should_compact_architecture_context(budget_task, anchor, "architect", 900) is False
	assert should_compact_architecture_context(repair_task, anchor, "code_engineer", 3200) is True
	assert should_compact_architecture_context(budget_task, "", "code_engineer", 900) is False


def test_compact_architecture_context_builds_low_budget_and_repair_summaries_directly():
	anchor = (
		"- Public facade: ComplianceIntakeService\n"
		"- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)"
	)
	budget_task = Task(
		id="code",
		title="Implementation",
		description="Write one Python module under 300 lines with a CLI demo entrypoint.",
		assigned_to="code_engineer",
	)
	repair_task = Task(
		id="repair",
		title="Repair",
		description="Write one Python module.",
		assigned_to="code_engineer",
		repair_context={"cycle": 1},
	)

	budget_summary = compact_architecture_context(budget_task, anchor)
	repair_summary = compact_architecture_context(repair_task, anchor)

	assert budget_summary.startswith("Low-budget architecture summary:")
	assert "Stay comfortably under 300 lines" in budget_summary
	assert 'main() plus a literal if __name__ == "__main__": block' in budget_summary
	assert repair_summary.startswith("Repair-focused architecture summary:")
	assert "Do not copy illustrative code blocks over the failing implementation" in repair_summary
	assert "prefer the existing failing module, the validation summary, and the cited pytest details" in repair_summary


def test_workflow_control_log_helpers_minimize_task_ids_directly():
	fields = privacy_safe_log_fields(
		{
			"task_ids": ["arch", "code"],
			"replayed_task_ids": ["arch"],
			"reason": "manual",
		}
	)

	assert fields == {"task_count": 2, "replayed_task_count": 1, "reason": "manual"}
	assert task_id_collection_count(["arch", "code"]) == 2
	assert task_id_collection_count("arch") == 1
	assert task_id_collection_count(None) == 0
	assert task_id_collection_count(3) is None
	assert task_id_count_log_field_name("task_ids") == "task_count"
	assert task_id_count_log_field_name("replayed_task_ids") == "replayed_task_count"
	assert task_id_count_log_field_name("task_id") is None


def test_validation_analysis_helpers_extract_failure_details_and_origin_directly():
	test_execution = {
		"stdout": "FAILED tests_tests.py::test_example - AssertionError: assert 1 == 2\nE   AssertionError: assert 1 == 2\n",
		"stderr": "",
	}

	assert pytest_failure_details(test_execution) == [
		"FAILED tests_tests.py::test_example - AssertionError: assert 1 == 2 | AssertionError: assert 1 == 2"
	]
	assert pytest_failure_origin({"stdout": "tests_tests.py:24: AssertionError\n", "stderr": ""}, "code.py", "tests_tests.py") == "tests"
	assert pytest_failure_is_semantic_assertion_mismatch(test_execution) is True


def test_validation_analysis_helpers_classify_blocking_and_warning_issues_directly():
	blocking_validation = {
		"test_analysis": {
			"syntax_ok": True,
			"undefined_local_names": ["result"],
		}
	}
	warning_validation = {
		"test_analysis": {
			"syntax_ok": True,
			"constructor_arity_mismatches": ["MyClass (line 5)"],
		}
	}

	assert validation_has_static_issues(blocking_validation) is True
	assert validation_has_blocking_issues(blocking_validation) is True
	assert validation_has_blocking_issues(warning_validation) is False
	assert validation_has_only_warnings(warning_validation) is True


def test_validation_analysis_helpers_detect_contract_overreach_directly():
	test_execution = {
		"stdout": "FAILED tests_tests.py::test_example - AssertionError: assert 'approved' == 'rejected'\n",
		"stderr": "",
	}

	signals = pytest_contract_overreach_signals(test_execution)

	assert signals == [
		"exact status/action label mismatch ('approved' vs 'rejected') suggests an unsupported threshold assumption"
	]