import ast
import os
import re
import stat
from types import SimpleNamespace

import pytest

from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.orchestration.ast_tools import AstNameReplacer
from kycortex_agents.orchestration.artifacts import ArtifactPersistenceSupport
from kycortex_agents.orchestration.private_files import (
	harden_private_directory_permissions,
	harden_private_file_permissions,
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
from kycortex_agents.types import ArtifactRecord, ArtifactType, ExecutionSandboxPolicy


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