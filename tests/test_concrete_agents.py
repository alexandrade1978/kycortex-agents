import pytest

from kycortex_agents.agents.architect import ArchitectAgent
from kycortex_agents.agents.code_engineer import CodeEngineerAgent
from kycortex_agents.agents.code_reviewer import CodeReviewerAgent
from kycortex_agents.agents.dependency_manager import DependencyManagerAgent
from kycortex_agents.agents.docs_writer import DocsWriterAgent
from kycortex_agents.agents.legal_advisor import LegalAdvisorAgent
from kycortex_agents.agents.qa_tester import QATesterAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.types import AgentInput, AgentOutput, ArtifactRecord, ArtifactType


class ChatCaptureMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_system_prompt: str = ""
        self.last_user_message: str = ""

    def chat(self, system_prompt: str, user_message: str) -> str:
        self.last_system_prompt = system_prompt
        self.last_user_message = user_message
        return "ok"


class CaptureArchitectAgent(ChatCaptureMixin, ArchitectAgent):
    pass


class CaptureCodeEngineerAgent(ChatCaptureMixin, CodeEngineerAgent):
    pass


class CaptureCodeReviewerAgent(ChatCaptureMixin, CodeReviewerAgent):
    pass


class CaptureDependencyManagerAgent(ChatCaptureMixin, DependencyManagerAgent):
    pass


class NoisyDependencyManagerAgent(DependencyManagerAgent):
    def chat(self, system_prompt: str, user_message: str) -> str:
        return (
            "After analyzing the module, the requirements.txt should be:\n\n"
            "```text\n"
            "requests>=2.31.0\n"
            "numpy==2.1.1\n"
            "```\n"
        )


class EmptyDependencyManagerAgent(DependencyManagerAgent):
    def chat(self, system_prompt: str, user_message: str) -> str:
        return "The module only uses the standard library.\n\n# No external runtime dependencies"


class CaptureQATesterAgent(ChatCaptureMixin, QATesterAgent):
    pass


class CaptureDocsWriterAgent(ChatCaptureMixin, DocsWriterAgent):
    pass


class CaptureLegalAdvisorAgent(ChatCaptureMixin, LegalAdvisorAgent):
    pass


def build_config(tmp_path):
    return KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="token")


def test_architect_agent_execute_uses_default_constraints_and_document_artifact(tmp_path):
    agent = CaptureArchitectAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="arch",
        task_title="Architecture",
        task_description="Design the system",
        project_name="Demo",
        project_goal="Build demo",
    )

    result = agent.execute(agent_input)

    assert result.raw_content == "ok"
    assert "Python 3.10+, production-ready dependencies, licensing suitable for open-source or commercial distribution" in agent.last_user_message
    assert "Respect the task scope exactly" in agent.last_user_message
    assert "Prefer one cohesive public service surface plus domain models over separate helper interfaces for scoring, logging, or batch processing." in agent.last_user_message
    assert "Do not introduce standalone RiskScorer, AuditLogger, BatchProcessor, Manager, or Processor collaborators unless the task explicitly requires those public types." in agent.last_user_message
    assert "For compact single-module service tasks, prefer one cohesive public service surface plus domain models" in agent.last_system_prompt
    assert result.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert result.artifacts[0].name == "arch_architecture"


def test_code_engineer_agent_execute_requires_architecture_context(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="code",
        task_title="Implementation",
        task_description="Implement the service",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    with pytest.raises(AgentExecutionError, match="required context key 'architecture'"):
        agent.execute(agent_input)


def test_code_reviewer_agent_execute_adds_review_artifact_and_uses_code_context(tmp_path):
    agent = CaptureCodeReviewerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="review",
        task_title="Review",
        task_description="Review the implementation",
        project_name="Demo",
        project_goal="Build demo",
        context={"code": "print('hello')"},
    )

    result = agent.execute(agent_input)

    assert "print('hello')" in agent.last_user_message
    assert result.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert result.artifacts[0].name == "review_review"


def test_dependency_manager_agent_execute_writes_requirements_artifact(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="deps",
        task_title="Dependencies",
        task_description="Infer runtime dependencies",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "import numpy as np\n\ndef run():\n    return np.array([1])",
            "module_name": "demo_mod",
            "module_filename": "demo_mod.py",
            "code_summary": "import numpy as np",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
        },
    )

    result = agent.execute(agent_input)

    assert "Infer the minimal runtime requirements.txt" in agent.last_user_message
    assert result.artifacts[0].artifact_type == ArtifactType.CONFIG
    assert result.artifacts[0].path == "artifacts/requirements.txt"
    assert result.artifacts[0].name == "deps_requirements"


def test_dependency_manager_agent_normalizes_noisy_requirements_output(tmp_path):
    agent = NoisyDependencyManagerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="deps",
        task_title="Dependencies",
        task_description="Infer runtime dependencies",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "import requests\nimport numpy as np\n",
            "module_name": "demo_mod",
            "module_filename": "demo_mod.py",
        },
    )

    result = agent.execute(agent_input)

    assert result.raw_content == "requests>=2.31.0\nnumpy==2.1.1"
    assert result.artifacts[0].content == "requests>=2.31.0\nnumpy==2.1.1"


def test_dependency_manager_agent_falls_back_to_no_external_dependencies(tmp_path):
    agent = EmptyDependencyManagerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="deps",
        task_title="Dependencies",
        task_description="Infer runtime dependencies",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "import random\nimport logging\n",
            "module_name": "demo_mod",
            "module_filename": "demo_mod.py",
        },
    )

    result = agent.execute(agent_input)

    assert result.raw_content == "# No external runtime dependencies"
    assert result.artifacts[0].content == "# No external runtime dependencies"


def test_dependency_manager_agent_normalizes_blank_requirements_output(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))

    assert agent._normalize_requirements("   \n\t") == "# No external runtime dependencies"


def test_dependency_manager_agent_preserves_explicit_no_dependency_marker(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))

    normalized = agent._normalize_requirements(
        "The module only uses the standard library.\n# No external runtime dependencies"
    )

    assert normalized == "# No external runtime dependencies"


def test_dependency_manager_agent_detects_no_dependency_marker_inside_prose(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))

    normalized = agent._normalize_requirements(
        "Final answer: use the literal marker # No external runtime dependencies in the manifest."
    )

    assert normalized == "# No external runtime dependencies"


def test_dependency_manager_agent_falls_back_when_output_contains_no_requirement_lines(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))

    normalized = agent._normalize_requirements(
        "After analyzing the module, there are no runtime packages to declare."
    )

    assert normalized == "# No external runtime dependencies"


def test_dependency_manager_agent_normalizes_bulleted_requirements_and_deduplicates(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))

    normalized = agent._normalize_requirements(
        "- `requests>=2.31.0`\n* requests>=2.31.0\n* numpy==2.1.1\n"
    )

    assert normalized == "requests>=2.31.0\nnumpy==2.1.1"


def test_dependency_manager_after_execute_leaves_non_requirements_artifacts_unchanged(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="deps",
        task_title="Dependencies",
        task_description="Infer runtime dependencies",
        project_name="Demo",
        project_goal="Build demo",
        context={"code": "import requests"},
    )
    output = AgentOutput(
        summary="summary",
        raw_content="requests>=2.31.0",
        artifacts=[ArtifactRecord(name="notes", artifact_type=ArtifactType.DOCUMENT, path="artifacts/notes.md", content="leave me alone")],
    )

    result = agent.after_execute(agent_input, output)

    assert result.artifacts[0].content == "leave me alone"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("requests>=2.31.0", True),
        ("package[extra]>=1.0", True),
        ("import requests", False),
        ("after analyzing the code", False),
        ("plain prose line", False),
    ],
)
def test_dependency_manager_requirement_detection_filters_non_requirements(tmp_path, line, expected):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))

    assert agent._looks_like_requirement(line) is expected


def test_qa_tester_agent_execute_uses_default_module_name_and_test_artifact(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="tests",
        task_title="Tests",
        task_description="Write tests",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "def add(a, b): return a + b",
            "code_summary": "def add(a, b): return a + b",
            "code_outline": "def add(a, b):",
            "code_public_api": "Functions:\n- add(a, b)\nClasses:\n- none",
        },
    )

    result = agent.execute(agent_input)

    assert "Module name: module" in agent.last_user_message
    assert "Implementation code:" in agent.last_user_message
    assert "Public API outline:" in agent.last_user_message
    assert "Public API contract:" in agent.last_user_message
    assert "Do not duplicate the implementation code in the tests." in agent.last_user_message
    assert "Respect the task's line budget and requested scenario count exactly." in agent.last_user_message
    assert "stay comfortably under that ceiling" in agent.last_user_message
    assert "Leave at least one top-level test of headroom below a stated maximum" in agent.last_user_message
    assert "count top-level tests and total lines explicitly" in agent.last_user_message
    assert "target clear headroom below it instead of landing on the boundary" in agent.last_user_message
    assert "Import every production class you instantiate or reference in a fixture or test body" in agent.last_user_message
    assert "Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols" in agent.last_user_message
    assert "stay on the main service or batch API" in agent.last_user_message
    assert "validator units, scorer units, dataclass serialization, audit logger wrappers" in agent.last_user_message
    assert "merge overlapping checks instead of creating helper-specific extra tests" in agent.last_user_message
    assert "use the direct intake or validation surface for the failure case" in agent.last_user_message
    assert "Keep the batch-processing scenario structurally valid" in agent.last_user_message
    assert "If the public API exposes no dedicated batch helper" in agent.last_user_message
    assert "Never define a custom fixture named `request`" in agent.last_user_message
    assert "If you assert an exact numeric value, use trivially countable inputs" in agent.last_user_message
    assert "Do not infer derived status transitions, escalation flags, or report counters" in agent.last_user_message
    assert "When an API accepts a request, filter, or payload dict with documented required fields" in agent.last_user_message
    assert "When a public service or workflow facade exists, limit imports to that facade and directly exchanged domain models" in agent.last_user_message
    assert "If you use isinstance or another exact type assertion against a returned production class, import that class explicitly" in agent.last_user_message
    assert "When the API contract exposes typed request or result models, instantiate them with the exact field names and full constructor arity" in agent.last_user_message
    assert "do not shorten them to submit(...) or submit_batch(...)" in agent.last_user_message
    assert "Do not assert exact score totals or threshold-triggered boolean flags unless the implementation summary or behavior contract explicitly defines the formula or trigger" in agent.last_user_message
    assert "If an exact numeric assertion depends on top-level dict size or collection size" in agent.last_user_message
    assert "do not pair exact score equality with word-like sample strings such as data, valid_data, or data1" in agent.last_user_message
    assert "risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25" in agent.last_user_message
    assert "risk_factor=\"invalid\" does not raise TypeError" in agent.last_user_message
    assert "use xxxxxxxxxx rather than \"\"" in agent.last_user_message
    assert "request_id=\"\" or another same-type placeholder can still pass" in agent.last_user_message
    assert "empty dict is still a same-type placeholder and may pass when validation only checks dict type" in agent.last_user_message
    assert "do not shorten them to submit(...) or submit_batch(...)" in agent.last_user_message
    assert "ComplianceData(id=\"1\", data={\"key\": \"wrong_value\"}) is still valid input and should be asserted as a non-compliant result" in agent.last_user_message
    assert "Do not write a validation-failure test as `assert not validate_request(...)`" in agent.last_user_message
    assert "choose an input that validate_request rejects before scoring runs" in agent.last_user_message
    assert "a two-item valid batch can emit 5 audit logs, not 3" in agent.last_user_message
    assert "prefer assertions on returned results, terminal batch markers, or monotonic audit growth" in agent.last_user_message
    assert "Unless the current implementation or behavior contract explicitly enumerates every emitted batch log, do not write len(service.audit_logs) == N or a similar exact batch-audit assertion." in agent.last_user_message
    assert "If a previous pytest failure showed a batch audit mismatch such as assert 5 == 3 on len(service.audit_logs), delete that exact count and replace it with stable checks" in agent.last_user_message
    assert "do not create a separate invalid-scoring test that first calls intake_request on an invalid object" in agent.last_user_message
    assert "never use prose sample text for that assertion" in agent.last_user_message
    assert "One invalid batch item can emit two failure-related audit entries" in agent.last_user_message
    assert "Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions" in agent.last_user_message
    assert "Do not replace one guessed helper with another guessed helper during repair" in agent.last_user_message
    assert "Treat the current implementation artifact and API contract as fixed ground truth during repair" in agent.last_user_message
    assert "If a pytest-only runtime failure shows that an earlier assertion overreached the current implementation or contract" in agent.last_user_message
    assert "Import every called production function explicitly" in agent.last_user_message
    assert "Return only raw Python test code." in agent.last_system_prompt
    assert "Do not import `main`, CLI/demo entrypoints" in agent.last_system_prompt
    assert "stay comfortably under that cap" in agent.last_system_prompt
    assert "Leave at least one top-level test of headroom below a stated maximum" in agent.last_system_prompt
    assert "count top-level tests and total lines yourself" in agent.last_system_prompt
    assert "target clear headroom below it instead of landing on the boundary" in agent.last_system_prompt
    assert "Do not hand-count prose strings to justify exact numeric assertions" in agent.last_system_prompt
    assert "Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols" in agent.last_system_prompt
    assert "Do not infer derived status transitions, escalation flags, or report counters" in agent.last_system_prompt
    assert "When an API accepts a request, filter, or payload dict with documented required fields" in agent.last_system_prompt
    assert "When a public service or workflow facade exists, limit imports to that facade and directly exchanged domain models" in agent.last_system_prompt
    assert "If you use isinstance or another exact type assertion against a returned production class, import that class explicitly" in agent.last_system_prompt
    assert "When the API contract exposes typed request or result models, instantiate them with the exact field names and full constructor arity" in agent.last_system_prompt
    assert "do not shorten them to submit(...) or submit_batch(...)" in agent.last_system_prompt
    assert "every constructor call in the suite must pass all five named arguments" in agent.last_system_prompt
    assert "Do not assert exact score totals or threshold-triggered boolean flags unless the implementation summary or behavior contract explicitly defines the formula or trigger" in agent.last_system_prompt
    assert "If an exact numeric assertion depends on top-level dict size or collection size" in agent.last_system_prompt
    assert "do not pair exact score equality with word-like sample strings such as data, valid_data, or data1" in agent.last_system_prompt
    assert "risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25" in agent.last_system_prompt
    assert "risk_factor=\"invalid\" does not raise TypeError" in agent.last_system_prompt
    assert "use xxxxxxxxxx rather than \"\"" in agent.last_system_prompt
    assert "request_id=\"\" or another same-type placeholder can still pass" in agent.last_system_prompt
    assert "empty dict is still a same-type placeholder and may pass when validation only checks dict type" in agent.last_system_prompt
    assert "do not shorten them to submit(...) or submit_batch(...)" in agent.last_system_prompt
    assert "ComplianceData(id=\"1\", data={\"key\": \"wrong_value\"}) is still valid input and should be asserted as a non-compliant result" in agent.last_system_prompt
    assert "Do not write a validation-failure test as `assert not validate_request(...)`" in agent.last_system_prompt
    assert "choose an input that validate_request rejects before scoring runs" in agent.last_system_prompt
    assert "a two-item valid batch can emit 5 audit logs, not 3" in agent.last_system_prompt
    assert "prefer assertions on returned results, terminal batch markers, or monotonic audit growth" in agent.last_system_prompt
    assert "Unless the current implementation or behavior contract explicitly enumerates every emitted batch log, do not write len(service.audit_logs) == N or a similar exact batch-audit assertion." in agent.last_system_prompt
    assert "If a previous pytest failure showed a batch audit mismatch such as assert 5 == 3 on len(service.audit_logs), delete that exact count and replace it with stable checks" in agent.last_system_prompt
    assert "do not create a separate invalid-scoring test that first calls intake_request on an invalid object" in agent.last_system_prompt
    assert "never use natural-language prose samples for that assertion" in agent.last_system_prompt
    assert "One invalid batch item can emit two failure-related audit entries" in agent.last_system_prompt
    assert "If the public API exposes no dedicated batch helper" in agent.last_system_prompt
    assert "Never define a custom fixture named `request`" in agent.last_system_prompt
    assert "If you use the `pytest.` namespace anywhere in the file, add `import pytest` explicitly at the top of the module." in agent.last_system_prompt
    assert "do not add direct unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities" in agent.last_system_prompt
    assert "Do not add caplog assertions or raw logging-text expectations" in agent.last_system_prompt
    assert "Do not use mock-style bookkeeping assertions such as `.call_count` or `.assert_called_once()`" in agent.last_system_prompt
    assert "Do not replace one guessed helper with another guessed helper during repair" in agent.last_system_prompt
    assert "Treat the current implementation artifact and API contract as fixed ground truth during repair" in agent.last_system_prompt
    assert "Task-specific scope, test-count, and size limits override these defaults." in agent.last_system_prompt
    assert result.artifacts[0].artifact_type == ArtifactType.TEST
    assert result.artifacts[0].name == "tests_tests"


def test_code_engineer_agent_prompt_demands_raw_python_output(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="code",
        task_title="Implementation",
        task_description="Implement the service",
        project_name="Demo",
        project_goal="Build demo",
        context={"architecture": "Layered design"},
    )

    agent.execute(agent_input)

    assert "Return only raw Python source code." in agent.last_system_prompt
    assert "Task-specific scope and size limits override generic polish." in agent.last_system_prompt
    assert "stay comfortably under that ceiling so imports, the main guard, and any required repairs still fit" in agent.last_system_prompt
    assert "Treat the architecture as guidance for required behavior" in agent.last_system_prompt
    assert "For compact single-module service tasks, prefer one cohesive public service surface plus domain models over separate helper-only collaborator classes." in agent.last_system_prompt
    assert "Do not split validation, scoring, audit logging, or batch handling into separate Logger, Scorer, Processor, Manager, or interface classes" in agent.last_system_prompt
    assert "Prefer in-memory state and simple standard-library containers unless the task explicitly requires durable persistence" in agent.last_system_prompt
    assert "Do not mix object-style APIs with dict membership tests or subscripting" in agent.last_system_prompt
    assert "If you define dataclasses or typed record models with defaults, keep every required non-default field before every defaulted field so the module imports cleanly" in agent.last_system_prompt
    assert "Example: if AuditLog has required action and details fields plus a defaulted timestamp, declare action and details before timestamp = field(default_factory=...)." in agent.last_system_prompt
    assert "Keep imports consistent with the names you reference. If you call datetime.datetime.now() or datetime.date.today(), import datetime." in agent.last_system_prompt
    assert "Do not include markdown fences" in agent.last_system_prompt
    assert "Target module: code_implementation.py" in agent.last_user_message
    assert "stay comfortably under that ceiling instead of aiming for the exact limit" in agent.last_user_message
    assert "within roughly 10 to 15 lines of the ceiling" in agent.last_user_message
    assert "For compact service tasks, keep validation, scoring, audit logging, and batch behavior on one main service surface or a very small set of top-level functions." in agent.last_user_message
    assert "Do not split those behaviors into separate Logger, Scorer, Processor, Manager, or interface classes unless the task or validated public API explicitly requires those public collaborators." in agent.last_user_message
    assert "Prefer in-memory state and simple standard-library containers unless the task explicitly requires durable persistence" in agent.last_user_message
    assert "you kept service state in memory instead of adding sqlite or filesystem-backed storage" in agent.last_user_message
    assert "you accessed them consistently through attributes instead of mixing in dict membership checks or subscripting" in agent.last_user_message
    assert "If you define dataclasses or typed record models with defaults, keep every required field before any defaulted field so the module imports cleanly and does not fail at import time." in agent.last_user_message
    assert "Example: if AuditLog has required action and details fields plus a defaulted timestamp, declare action and details before timestamp = field(default_factory=...)." in agent.last_user_message
    assert "Keep imports consistent with how you reference names. If you call datetime.datetime.now() or datetime.date.today(), import datetime." in agent.last_user_message


def test_code_reviewer_agent_prompt_includes_tests_and_module_name(tmp_path):
    agent = CaptureCodeReviewerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="review",
        task_title="Review",
        task_description="Review the implementation",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "print('hello')",
            "tests": "def test_it():\n    assert True",
            "module_name": "code_implementation",
            "module_filename": "code_implementation.py",
            "code_public_api": "Functions:\n- none\nClasses:\n- none",
            "test_validation_summary": "Generated test validation:\n- Missing function imports: none",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
        },
    )

    agent.execute(agent_input)

    assert "Module name: code_implementation" in agent.last_user_message
    assert "Module file: code_implementation.py" in agent.last_user_message
    assert "Generated tests:" in agent.last_user_message
    assert "Test validation summary:" in agent.last_user_message
    assert "Dependency validation summary:" in agent.last_user_message


def test_docs_writer_agent_prompt_anchors_to_actual_module(tmp_path):
    agent = CaptureDocsWriterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="docs",
        task_title="Docs",
        task_description="Write docs",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "architecture": "Layered design",
            "code": "def main(): pass",
            "code_summary": "Core API and worker layer",
            "module_name": "code_implementation",
            "module_run_command": "python code_implementation.py",
            "dependency_manifest_path": "artifacts/requirements.txt",
            "dependency_manifest": "requests>=2.0",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
            "code_public_api": "Functions:\n- main()\nClasses:\n- none",
        },
    )

    agent.execute(agent_input)

    assert "Actual module: code_implementation.py" in agent.last_user_message
    assert "Exact run command: python code_implementation.py" in agent.last_user_message
    assert "Dependency manifest: artifacts/requirements.txt" in agent.last_user_message
    assert "Dependency validation summary:" in agent.last_user_message
    assert "Do not invent extra files, package layouts, CLIs, API endpoints, or components" in agent.last_system_prompt


def test_docs_writer_agent_execute_prefers_code_summary_over_code(tmp_path):
    agent = CaptureDocsWriterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="docs",
        task_title="Docs",
        task_description="Write docs",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "architecture": "Layered design",
            "code": "def fallback(): pass",
            "code_summary": "Core API and worker layer",
            "module_run_command": "",
        },
    )

    result = agent.execute(agent_input)

    assert "Code summary: Core API and worker layer" in agent.last_user_message
    assert "Generated code:" in agent.last_user_message
    assert "def fallback(): pass" in agent.last_user_message
    assert "Exact run command: No CLI entrypoint detected" in agent.last_user_message
    assert result.artifacts[0].name == "docs_documentation"


def test_legal_advisor_agent_execute_uses_default_license_and_dependency_placeholder(tmp_path):
    agent = CaptureLegalAdvisorAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="legal",
        task_title="Legal",
        task_description="Review legal posture",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    result = agent.execute(agent_input)

    assert "Project License: Dual-licensed: AGPL-3.0 open-source distribution or separate commercial terms" in agent.last_user_message
    assert "Not specified" in agent.last_user_message
    assert result.artifacts[0].artifact_type == ArtifactType.DOCUMENT
    assert result.artifacts[0].name == "legal_legal_analysis"


def test_legal_advisor_agent_execute_includes_custom_license_and_dependencies(tmp_path):
    agent = CaptureLegalAdvisorAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="legal",
        task_title="Legal",
        task_description="Review dependencies and licensing",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "license": "MIT",
            "dependencies": ["fastapi==0.115.0", "uvicorn==0.30.0"],
        },
    )

    agent.execute(agent_input)

    assert "Project License: MIT" in agent.last_user_message
    assert "- fastapi==0.115.0" in agent.last_user_message
    assert "- uvicorn==0.30.0" in agent.last_user_message
    assert "Goal: Build demo" in agent.last_user_message


def test_legal_advisor_agent_run_uses_custom_license_and_dependency_list(tmp_path):
    agent = CaptureLegalAdvisorAgent(build_config(tmp_path))

    result = agent.run(
        "Assess compliance posture",
        {
            "license": "Apache-2.0",
            "dependencies": ["requests>=2.31.0", "pydantic>=2.0"],
        },
    )

    assert result == "ok"
    assert "Project License: Apache-2.0" in agent.last_user_message
    assert "- requests>=2.31.0" in agent.last_user_message
    assert "- pydantic>=2.0" in agent.last_user_message
    assert "Task: Assess compliance posture" in agent.last_user_message