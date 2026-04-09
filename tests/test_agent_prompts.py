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
from kycortex_agents.types import AgentInput, ArtifactType


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


class CaptureQATesterAgent(ChatCaptureMixin, QATesterAgent):
    pass


class CaptureDocsWriterAgent(ChatCaptureMixin, DocsWriterAgent):
    pass


class CaptureLegalAdvisorAgent(ChatCaptureMixin, LegalAdvisorAgent):
    pass


def build_config(tmp_path):
    return KYCortexConfig(output_dir=str(tmp_path / "output"), api_key="token")


def test_architect_agent_uses_typed_input_fields(tmp_path):
    agent = CaptureArchitectAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="arch",
        task_title="Architecture",
        task_description="Design the system",
        project_name="Demo",
        project_goal="Build demo",
        context={"planned_module_filename": "code_implementation.py"},
        constraints=["Python 3.12", "No GPL dependencies"],
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Project Name: Demo" in agent.last_user_message
    assert "Project Goal: Build demo" in agent.last_user_message
    assert "Python 3.12, No GPL dependencies" in agent.last_user_message
    assert "Target module: code_implementation.py" in agent.last_user_message
    assert "Respect the task scope exactly" in agent.last_user_message
    assert "Prefer one cohesive public service surface plus domain models over separate helper interfaces for scoring, logging, or batch processing." in agent.last_user_message
    assert "Do not introduce standalone RiskScorer, AuditLogger, BatchProcessor, Manager, or Processor collaborators unless the task explicitly requires those public types." in agent.last_user_message
    assert "For compact single-module service tasks, prefer one cohesive public service surface plus domain models" in agent.last_system_prompt


def test_architect_agent_run_uses_context_goal_and_target_module(tmp_path):
    agent = CaptureArchitectAgent(build_config(tmp_path))

    result = agent.run(
        "Design a single module",
        {
            "goal": "Build demo",
            "constraints": "Python 3.12",
            "planned_module_filename": "single_module.py",
        },
    )

    assert result == "ok"
    assert "Project Goal: Build demo" in agent.last_user_message
    assert "Constraints: Python 3.12" in agent.last_user_message
    assert "Target module: single_module.py" in agent.last_user_message
    assert "Prefer one cohesive public service surface plus domain models over separate helper interfaces for scoring, logging, or batch processing." in agent.last_user_message
    assert "Do not introduce standalone RiskScorer, AuditLogger, BatchProcessor, Manager, or Processor collaborators unless the task explicitly requires those public types." in agent.last_user_message


def test_architect_agent_includes_task_public_contract_anchor(tmp_path):
    agent = CaptureArchitectAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="arch",
        task_title="Architecture",
        task_description="Design the system",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "planned_module_filename": "code_implementation.py",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)"
            ),
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Task-level public contract anchor:" in agent.last_user_message
    assert "- Public facade: ComplianceIntakeService" in agent.last_user_message
    assert "ComplianceIntakeService.handle_request(request)" in agent.last_user_message
    assert "preserve every listed facade, model, method, and constructor field name exactly" in agent.last_user_message
    assert "do not invent alternate aliases or competing public entrypoints" in agent.last_system_prompt


def test_architect_agent_adds_low_budget_architecture_guidance(tmp_path):
    agent = CaptureArchitectAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="arch",
        task_title="Architecture",
        task_description="Design the system",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "planned_module_filename": "code_implementation.py",
            "provider_max_tokens": 900,
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Provider completion budget: 900 tokens." in agent.last_user_message
    assert "This is a tight completion budget." in agent.last_user_message
    assert "omit optional helper types, response wrappers, validation-result types, internal audit-record types" in agent.last_user_message
    assert "Do not introduce extra named result, scoring, or audit dataclasses unless the public contract explicitly requires them." in agent.last_user_message
    assert "still leaves room for the required CLI entrypoint in the eventual implementation" in agent.last_user_message
    assert "Prefer one facade, one request model" in agent.last_user_message
    assert "Return a compact bullet list only." in agent.last_user_message
    assert "Do not use markdown tables, section headings, or long rationale under this budget." in agent.last_user_message


def test_architect_agent_supports_budget_decomposition_brief_mode(tmp_path):
    agent = CaptureArchitectAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="code__repair_1__budget_plan",
        task_title="Budget plan",
        task_description="Write one Python module under 80 lines.",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "repair_context": {
                "decomposition_mode": "budget_compaction_planner",
            }
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Provide a compact budget decomposition brief for the next repair step." in agent.last_user_message
    assert "Return 4 to 8 short bullets only." in agent.last_user_message
    assert "Do not include file trees, package layouts, headings, markdown tables, or long rationale." in agent.last_user_message
    assert "Provide a detailed architecture document." not in agent.last_user_message


def test_code_engineer_requires_architecture_context(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="code",
        task_title="Code",
        task_description="Implement feature",
        project_name="Demo",
        project_goal="Build demo",
        context={},
    )

    with pytest.raises(AgentExecutionError, match="required context key 'architecture'"):
        agent.execute(agent_input)


def test_code_reviewer_uses_typed_code_context(tmp_path):
    agent = CaptureCodeReviewerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="review",
        task_title="Review",
        task_description="Review implementation",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "print('hello')",
            "tests": "def test_it():\n    assert True",
            "module_name": "demo_mod",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Project: Demo" in agent.last_user_message
    assert "print('hello')" in agent.last_user_message
    assert "Module name: demo_mod" in agent.last_user_message
    assert "Generated tests:" in agent.last_user_message
    assert "Test validation summary:" in agent.last_user_message
    assert "Dependency validation summary:" in agent.last_user_message
    assert "Review constraints:" in agent.last_user_message
    assert "Keep the review under 180 words." in agent.last_user_message
    assert "Report at most 3 distinct issues." in agent.last_user_message
    assert 'No material issues found.' in agent.last_system_prompt


def test_code_engineer_run_uses_context_module_details(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))

    result = agent.run(
        "Implement feature",
        {
            "architecture": "Layered design",
            "existing_code": "def old():\n    return 1",
            "existing_tests": "def test_old():\n    assert old() == 2",
            "repair_validation_summary": "Generated code validation:\n- Syntax OK: no\n- Completion diagnostics: likely truncated at completion limit",
            "module_name": "service_module",
            "module_filename": "service_module.py",
        },
    )

    assert result == "ok"
    assert "Architecture:\nLayered design" in agent.last_user_message
    assert "Target module: service_module.py" in agent.last_user_message
    assert "The file will be saved as `service_module.py` and imported as `service_module`." in agent.last_user_message
    assert "def old():" in agent.last_user_message
    assert "Existing tests context:" in agent.last_user_message
    assert "def test_old():" in agent.last_user_message
    assert "Previous validation summary:" in agent.last_user_message
    assert "Completion diagnostics: likely truncated at completion limit" in agent.last_user_message
    assert "hard blocker" in agent.last_user_message
    assert "Use the existing tests context, when provided" in agent.last_user_message
    assert "Treat that tests context as behavioral evidence only." in agent.last_user_message
    assert "Do not copy pytest test functions, bare assert statements, or test-only scaffolding into this module." in agent.last_user_message
    assert "Respect the task's requested size budget exactly." in agent.last_user_message
    assert "If the task does not specify one, keep the module under 260 lines." in agent.last_user_message
    assert "stay comfortably under that ceiling instead of aiming for the exact limit" in agent.last_user_message
    assert "within roughly 10 to 15 lines of the ceiling" in agent.last_user_message
    assert "For compact service tasks, keep validation, scoring, audit logging, and batch behavior on one main service surface or a very small set of top-level functions." in agent.last_user_message
    assert "Do not split those behaviors into separate Logger, Scorer, Processor, Manager, or interface classes unless the task or validated public API explicitly requires those public collaborators." in agent.last_user_message
    assert "treat each listed failing assertion as an exact behavior contract for this module" in agent.last_user_message
    assert "Do not stop at a nearby constant tweak, renamed helper, or signature change" in agent.last_user_message
    assert "if the task requires a CLI or demo entrypoint" in agent.last_user_message
    assert "if __name__ == \"__main__\":" in agent.last_user_message
    assert "the file stays implementation code rather than turning into a pytest module" in agent.last_user_message
    assert "you stayed comfortably under the ceiling rather than using the full budget" in agent.last_user_message
    assert "you left visible headroom below the ceiling" in agent.last_user_message
    assert "you implemented only the required behavior from the architecture" in agent.last_user_message
    assert "rewrote the full module from the top instead of appending a partial continuation" in agent.last_user_message
    assert "every constructor call matches the constructor you defined" in agent.last_user_message
    assert "every opened string, bracket, parenthesis, and docstring is closed" in agent.last_user_message
    assert "you reduced non-essential docstrings, comments, blank lines, and optional helpers" in agent.last_user_message
    assert "If you are repairing a previously invalid or truncated file" in agent.last_system_prompt
    assert "Treat existing tests and repair summaries as behavioral evidence only." in agent.last_system_prompt
    assert "Do not copy pytest test functions, bare assert statements, or test-only scaffolding into the implementation module." in agent.last_system_prompt
    assert "Do not stop mid-function, mid-string, or mid-docstring." in agent.last_system_prompt
    assert "stay comfortably under that ceiling so imports, the main guard, and any required repairs still fit" in agent.last_system_prompt
    assert "within roughly 10 to 15 lines of the cap" in agent.last_system_prompt
    assert "remove non-essential docstrings, comments, blank lines, and optional helper layers" in agent.last_system_prompt
    assert "Treat the architecture as guidance for required behavior" in agent.last_system_prompt
    assert "For compact single-module service tasks, prefer one cohesive public service surface plus domain models over separate helper-only collaborator classes." in agent.last_system_prompt
    assert "Do not split validation, scoring, audit logging, or batch handling into separate Logger, Scorer, Processor, Manager, or interface classes" in agent.last_system_prompt


def test_code_engineer_prioritizes_repair_directives_over_buggy_baseline(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="code__repair_1",
        task_title="Repair implementation",
        task_description=(
            "Implement the vendor onboarding workflow.\n\n"
            "Repair objective:\n"
            "Repair the generated Python module so valid happy-path and batch requests do not fail on missing internal attributes. "
            "The current failed artifact reads VendorProfile.expired_certifications even though VendorProfile only defines certifications and incidents. "
            "Prefer replacing VendorProfile.expired_certifications with VendorProfile.certifications unless you explicitly add and populate expired_certifications.\n\n"
            "Repair priorities:\n"
            "- Prefer replacing .expired_certifications with .certifications."
        ),
        project_name="Demo",
        project_goal="Build demo",
        context={
            "architecture": "Layered design that still discusses expired certifications.",
            "existing_code": "if vendor_profile.expired_certifications:\n    score += 1.0",
            "existing_tests": "def test_happy_path():\n    assert service.handle_request(request) is not None",
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Pytest failure details: AttributeError: 'VendorProfile' object has no attribute 'expired_certifications'"
            ),
            "repair_context": {
                "cycle": 1,
                "failure_category": "code_validation",
                "repair_owner": "code_engineer",
            },
            "module_name": "service_module",
            "module_filename": "service_module.py",
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Highest-priority repair directives:" in agent.last_user_message
    assert "Literal repair cue: replace VendorProfile.expired_certifications with VendorProfile.certifications" in agent.last_user_message
    assert "Buggy existing code context (edit this broken baseline rather than preserving it unchanged):" in agent.last_user_message
    assert "Secondary architecture guidance:" in agent.last_user_message
    assert agent.last_user_message.index("Highest-priority repair directives:") < agent.last_user_message.index(
        "Buggy existing code context (edit this broken baseline rather than preserving it unchanged):"
    )
    assert agent.last_user_message.index(
        "Buggy existing code context (edit this broken baseline rather than preserving it unchanged):"
    ) < agent.last_user_message.index("Secondary architecture guidance:")
    assert "Treat the existing code context as a buggy baseline to edit, not as a template to preserve unchanged." in agent.last_system_prompt
    assert "ensure the broken reference no longer appears anywhere in the final module" in agent.last_system_prompt


def test_code_engineer_includes_budget_decomposition_brief(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))

    result = agent.run(
        "Implement feature",
        {
            "architecture": "Layered design",
            "budget_decomposition_brief": "- Keep only the public facade.\n- Drop optional helpers and comments.",
            "module_name": "service_module",
            "module_filename": "service_module.py",
        },
    )

    assert result == "ok"
    assert "Budget decomposition brief:" in agent.last_user_message
    assert "Keep only the public facade." in agent.last_user_message
    assert "compact execution plan for this rewrite" in agent.last_user_message
    assert "Task-specific scope and size limits override generic polish" in agent.last_system_prompt
    assert "treat those assertions as exact behavioral requirements for the module" in agent.last_system_prompt
    assert "do not stop at a nearby constant tweak or branch edit" in agent.last_system_prompt
    assert "implement concrete reject conditions for clearly invalid input" in agent.last_system_prompt
    assert "use a transparent deterministic formula and avoid hidden caps" in agent.last_system_prompt
    assert "read the field's actual truth value instead of treating mere key presence as a positive signal" in agent.last_system_prompt
    assert "Prefer in-memory state and simple standard-library containers unless the task explicitly requires durable persistence" in agent.last_system_prompt
    assert "Do not mix object-style APIs with dict membership tests or subscripting" in agent.last_system_prompt
    assert "If the public request model separates wrapper fields from a nested payload container such as details, data, metadata, or payload" in agent.last_system_prompt
    assert "Do not make internal helper dataclasses or typed record models stricter than the documented valid request shape." in agent.last_system_prompt
    assert "If you construct an internal model from **request.details, **request.data, **payload, or another expanded mapping" in agent.last_system_prompt
    assert "Every attribute you read from a dataclass or typed internal model must be declared on that model or derived there consistently." in agent.last_system_prompt
    assert "If repair context cites AttributeError that an object has no attribute X, the rewritten module must either declare and populate X on that object's model or remove every read of .X." in agent.last_system_prompt
    assert "If you define dataclasses or typed record models with defaults, keep every required non-default field before every defaulted field so the module imports cleanly" in agent.last_system_prompt
    assert "Example: if AuditLog has required action and details fields plus a defaulted timestamp, declare action and details before timestamp = field(default_factory=...)." in agent.last_system_prompt
    assert "If import validation reports a 'non-default argument ... follows default argument' error, inspect every dataclass in the module, including audit, review, and result record types" in agent.last_system_prompt
    assert "If you use dataclasses.field(...) or field(default_factory=...) anywhere in the module, import field explicitly from dataclasses" in agent.last_system_prompt
    assert "Keep imports consistent with the names you reference. If you call datetime.datetime.now(), datetime.date.today(), datetime.timedelta(...), or datetime.timezone.utc, import datetime." in agent.last_system_prompt
    assert "If the existing tests or repair summary show a validation-failure sample with a clearly wrong required-field value or type" in agent.last_system_prompt
    assert "If validate_request(...) accepts a happy-path or batch input, derive internal-only fields from existing request data or give them safe defaults" in agent.last_system_prompt
    assert "your validator rejects at least one clearly invalid input shape" in agent.last_user_message
    assert "the formula is transparent and avoids hidden caps, clamps, or arbitrary thresholds" in agent.last_user_message
    assert "you used the field's truth value rather than mere key presence" in agent.last_user_message
    assert "Prefer in-memory state and simple standard-library containers unless the task explicitly requires durable persistence" in agent.last_user_message
    assert "you kept service state in memory instead of adding sqlite or filesystem-backed storage" in agent.last_user_message
    assert "you accessed them consistently through attributes instead of mixing in dict membership checks or subscripting" in agent.last_user_message
    assert "If the request model exposes top-level wrapper fields plus a nested payload container such as details, data, metadata, or payload" in agent.last_user_message
    assert "you validated wrapper fields on the request object and only required true payload keys inside the nested mapping" in agent.last_user_message
    assert "If validate_request(...) accepts the happy-path or batch input shown in the repair context, do not let an internal helper model or dataclass later raise TypeError for extra missing fields." in agent.last_user_message
    assert "if validate_request(...) accepts a happy-path or batch input, no internal helper model or dataclass later raises TypeError for extra missing fields" in agent.last_user_message
    assert "If you construct an internal model from **request.details, **request.data, **payload, or another expanded mapping, do not also pass the same field positionally or as a repeated keyword." in agent.last_user_message
    assert "if you construct an internal model from **request.details, **request.data, **payload, or another expanded mapping, you did not also pass the same field positionally or as a repeated keyword" in agent.last_user_message
    assert "Every attribute you read from a dataclass or typed internal model must be declared on that model or derived there consistently." in agent.last_user_message
    assert "every attribute read from a dataclass or typed internal model is declared on that model or derived there consistently" in agent.last_user_message
    assert "If the repair summary cites AttributeError that an object has no attribute X, either declare and populate X on that object's model or remove every read of .X before you finalize." in agent.last_user_message
    assert "if the repair summary cited AttributeError that an object has no attribute X, you either declared and populated X on that model or removed every read of .X from the rewritten module" in agent.last_user_message
    assert "If you define dataclasses or typed record models with defaults, keep every required field before any defaulted field so the module imports cleanly and does not fail at import time." in agent.last_user_message
    assert "Example: if AuditLog has required action and details fields plus a defaulted timestamp, declare action and details before timestamp = field(default_factory=...)." in agent.last_user_message
    assert "If import validation reports a 'non-default argument ... follows default argument' error, inspect every dataclass in the module, including audit, review, and result record types" in agent.last_user_message
    assert "if you used dataclasses or typed record models with defaults, every required field appears before any field with a default so the module imports cleanly" in agent.last_user_message
    assert "if import validation cited a 'non-default argument ... follows default argument' error, you inspected every dataclass in the module and reordered each offending class" in agent.last_user_message
    assert "If you use dataclasses.field(...) or field(default_factory=...) anywhere in the module, import field explicitly from dataclasses so the module imports cleanly." in agent.last_user_message
    assert "if you used dataclasses.field(...) or field(default_factory=...) anywhere in the module, you imported field explicitly from dataclasses so the module imports cleanly" in agent.last_user_message
    assert "Keep imports consistent with how you reference names. If you call datetime.datetime.now(), datetime.date.today(), datetime.timedelta(...), or datetime.timezone.utc, import datetime." in agent.last_user_message
    assert "If the existing tests or repair summary show a validation-failure sample with a clearly wrong required-field value or type" in agent.last_user_message
    assert "if you reference datetime helpers such as timedelta or timezone, you either imported those exact symbols directly or qualified them through datetime.* consistently" in agent.last_user_message


def test_code_engineer_includes_task_public_contract_anchor(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))

    result = agent.run(
        "Implement feature",
        {
            "architecture": "Layered design",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
        },
    )

    assert result == "ok"
    assert "Task-level public contract anchor:" in agent.last_user_message
    assert "- Public facade: ComplianceIntakeService" in agent.last_user_message
    assert "ComplianceIntakeService.validate_request(request)" in agent.last_user_message
    assert "treat it as higher priority than optional architecture wording" in agent.last_user_message
    assert "Do not replace anchored names with guessed aliases" in agent.last_user_message
    assert "highest-priority public API contract" in agent.last_system_prompt
    assert "every referenced module or symbol is imported consistently; if you call datetime.datetime.now() you imported datetime" in agent.last_user_message


def test_code_engineer_adds_low_budget_code_guidance(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))

    result = agent.run(
        "Implement feature",
        {
            "architecture": "Layered design",
            "provider_max_tokens": 900,
            "module_name": "service_module",
            "module_filename": "service_module.py",
        },
    )

    assert result == "ok"
    assert "Provider completion budget: 900 tokens." in agent.last_user_message
    assert "This is a tight completion budget." in agent.last_user_message
    assert "omit optional response wrappers, validation-result dataclasses, internal audit-record dataclasses" in agent.last_user_message
    assert "Prefer built-in containers for optional return details instead of extra named types" in agent.last_user_message
    assert "Do not introduce any extra dataclass beyond the anchored request model unless the task explicitly requires it." in agent.last_user_message
    assert "keep the required CLI or demo path minimal but mandatory" in agent.last_user_message
    assert 'preserve a working main() plus a literal if __name__ == "__main__": block before spending tokens on optional helper types or richer return models' in agent.last_user_message
    assert "keep the anchored facade, validate_request(...), handle_request(...), and the minimal CLI entrypoint" in agent.last_user_message
    assert "Order the module so acceptance-critical surfaces appear first" in agent.last_user_message
    assert "inline scoring and audit work inside handle_request(...) instead of spending lines on private helper methods" in agent.last_user_message


def test_code_engineer_compacts_long_task_description_when_anchor_present(tmp_path):
    agent = CaptureCodeEngineerAgent(build_config(tmp_path))

    result = agent.run(
        (
            "Write one Python module under 300 lines that implements only the planned compliance intake service. "
            "Use only the standard library. "
            "Include typed models, validation, risk scoring, batch processing, audit logging, and a CLI demo entrypoint. "
            "Prefer the smallest complete design that satisfies those requirements. "
            "Leave at least 15 lines of headroom under the hard cap when the required behavior fits there.\n\n"
            "Public contract anchor:\n"
            "- Public facade: ComplianceIntakeService\n"
            "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
            "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
            "- Supporting validation surface: ComplianceIntakeService.validate_request(request)"
        ),
        {
            "architecture": "Low-budget architecture summary:\n- Keep one main facade.",
            "provider_max_tokens": 900,
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
        },
    )

    assert result == "ok"
    assert "Task constraints summary:" in agent.last_user_message
    assert "- Write one Python module under 300 lines that implements only the planned compliance intake service." in agent.last_user_message
    assert "- Use only the standard library." in agent.last_user_message
    assert "- Include typed models, validation, risk scoring, batch processing, audit logging, and a CLI demo entrypoint." in agent.last_user_message
    assert "- Prefer the smallest complete design that satisfies those requirements." in agent.last_user_message
    assert "- Leave at least 15 lines of headroom under the hard cap when the required behavior fits there." in agent.last_user_message


def test_qa_tester_includes_task_public_contract_anchor(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="tests",
        task_title="Tests",
        task_description="Write tests with a happy path and a batch-processing scenario",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": (
                "class ComplianceRequest:\n"
                "    def __init__(self, request_id, request_type, details, timestamp):\n"
                "        self.request_id = request_id\n"
                "        self.request_type = request_type\n"
                "        self.details = details\n"
                "        self.timestamp = timestamp\n\n"
                "class ComplianceIntakeService:\n"
                "    def handle_request(self, request):\n"
                "        return True\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.validate_request, ComplianceIntakeService.batch_process\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts a ComplianceRequest instance",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Task-level public contract anchor:" in agent.last_user_message
    assert "ComplianceIntakeService.handle_request(request)" in agent.last_user_message
    assert "Because the anchor lists timestamp in ComplianceRequest(request_id, request_type, details, timestamp), every ComplianceRequest(...) call in the suite must pass timestamp explicitly." in agent.last_user_message
    assert "Treat that anchor as exact. For batch coverage, loop over ComplianceIntakeService.handle_request(request) with multiple valid items instead of inventing renamed batch helpers such as process_batch(...), batch_process(...), or batch_intake_requests(...)." in agent.last_user_message
    assert "import pytest" in agent.last_user_message
    assert "from service_module import ComplianceIntakeService, ComplianceRequest" in agent.last_user_message
    assert "def test_happy_path():" in agent.last_user_message
    assert "def test_validation_failure():" in agent.last_user_message
    assert 'request = ComplianceRequest(request_id="request_id-1", request_type="screening", details={"source": "web"}, timestamp=1.0)' in agent.last_user_message
    assert "result = service.handle_request(request)" in agent.last_user_message
    assert "def test_batch_processing():" in agent.last_user_message
    assert "Keep mutable services and request objects local to each test or a local helper. Do not lift them to module scope." in agent.last_user_message
    assert "Task constraints summary:" in agent.last_user_message
    assert "Use the deterministic scaffold above as the exact starting surface." in agent.last_user_message
    assert "Default to exactly 3 top-level tests named `test_happy_path`, `test_validation_failure`, and `test_batch_processing` when those cover the required scope." in agent.last_user_message
    assert "If the task also says to prefer 3 to 5 tests, resolve that softer preference in favor of exactly those 3 tests when they already cover the required scope." in agent.last_user_message
    assert "For hard caps like 150 lines, treat that trio as the effective maximum unless the exact contract or behavior contract explicitly requires more coverage." in agent.last_user_message
    assert "Do not add per-test docstrings in this compact mode." in agent.last_user_message
    assert "If the suite uses `datetime.now()` or any other bare `datetime` reference, you must add a matching datetime import at the top before finalizing." in agent.last_user_message
    assert "Do not add duplicate-detection, risk-tier, audit-only, or helper-only tests unless the exact contract or behavior contract explicitly requires them." in agent.last_user_message
    assert "Avoid guessed exact response.status labels and guessed exact risk-summary bucket totals for batch items" in agent.last_user_message
    assert "Avoid guessed exact outcome or action labels such as blocked, escalated, straight-through, manual investigation, fraud escalation, or time-boxed approval in happy-path or valid batch tests" in agent.last_user_message
    assert "For that batch loop, prefer assertions on response count, request identity, validation shape, or monotonic service state." in agent.last_user_message
    assert "Keep mutable service instances and request objects local to each test or a local helper; do not share a module-level service or request object across tests." in agent.last_user_message
    assert "Concrete class, function, and field names that appear later in generic examples are placeholders only." not in agent.last_user_message
    assert "When a task-level public contract anchor block is provided, treat it as higher priority than generic examples" in agent.last_system_prompt
    assert "Do not copy placeholder example names or invent alternate helpers." in agent.last_system_prompt
    assert "Never use `assert True`, `assert False`, or placeholder comments such as `Assuming ...` to stand in for a real expectation." in agent.last_system_prompt
    assert "default to exactly three top-level tests named test_happy_path, test_validation_failure, and test_batch_processing" in agent.last_system_prompt
    assert "For compact anchored workflow tasks with a hard line cap such as 150 lines, treat that trio as the effective maximum unless the exact contract or behavior contract explicitly requires more coverage." in agent.last_system_prompt
    assert "Do not use per-test docstrings in this compact mode." in agent.last_system_prompt
    assert "If any test keeps datetime.now() or another bare datetime reference, a matching datetime import is mandatory at the top of the file." in agent.last_system_prompt


def test_qa_tester_compacts_long_task_description_when_anchor_present(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="tests",
        task_title="Tests",
        task_description=(
            "Write one compact raw pytest module under 150 lines. "
            "Use at most 3 fixtures and at most 7 top-level test functions. "
            "Include at least one happy path, one validation failure, and one batch-processing scenario. "
            "Prefer 3 to 5 top-level tests when those requested scenarios fit within that budget. "
            "Public contract anchor:\n"
            "- Public facade: ComplianceIntakeService\n"
            "Concrete class, function, and field names used in the generic examples below are placeholders only. "
            "Do not write a validation-failure test as assert not validate_request(...)."
        ),
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": (
                "class ComplianceRequest:\n"
                "    def __init__(self, request_id, request_type, details, timestamp):\n"
                "        self.request_id = request_id\n"
                "        self.request_type = request_type\n"
                "        self.details = details\n"
                "        self.timestamp = timestamp\n\n"
                "class ComplianceIntakeService:\n"
                "    def handle_request(self, request):\n"
                "        return True\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request), ComplianceIntakeService.validate_request(request)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts a ComplianceRequest instance",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Task constraints summary:" in agent.last_user_message
    assert "- Write one compact raw pytest module under 150 lines." in agent.last_user_message
    assert "- Use at most 3 fixtures and at most 7 top-level test functions." in agent.last_user_message
    assert "- Include at least one happy path, one validation failure, and one batch-processing scenario." in agent.last_user_message
    assert "- Prefer 3 to 5 top-level tests when those requested scenarios fit within that budget." in agent.last_user_message
    assert "Concrete class, function, and field names used in the generic examples below are placeholders only." not in agent.last_user_message
    assert "Do not write a validation-failure test as assert not validate_request(...)." not in agent.last_user_message


def test_code_reviewer_run_uses_context_module_validation_fields(tmp_path):
    agent = CaptureCodeReviewerAgent(build_config(tmp_path))

    result = agent.run(
        "Review implementation",
        {
            "code": "def run():\n    return 1",
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
            "tests": "from service_module import run",
            "test_validation_summary": "Generated test validation:\n- Missing function imports: none",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
        },
    )

    assert result == "ok"
    assert "Module name: service_module" in agent.last_user_message
    assert "Module file: service_module.py" in agent.last_user_message
    assert "Functions:\n- run()" in agent.last_user_message
    assert "Generated tests:" in agent.last_user_message
    assert "Do not repeat the same issue or category with different wording." in agent.last_user_message
    assert "For compact generated modules, do not pad the review with repeated PEP8" in agent.last_system_prompt


def test_code_reviewer_compacts_long_generated_tests_context(tmp_path):
    agent = CaptureCodeReviewerAgent(build_config(tmp_path))

    long_tests = "\n".join(
        [
            "import pytest",
            "from service_module import run",
            "",
            "def test_happy_path():",
            "    assert run() == 1",
            "",
            "def test_validation_failure():",
            "    with pytest.raises(ValueError):",
            "        raise ValueError()",
            "",
            "def test_batch_processing():",
            "    values = [1, 2]",
            "    assert len(values) == 2",
            "",
            "def test_extra_case():",
            "    assert True",
            "",
            "def test_more_lines_1():",
            "    assert True",
            "",
            "def test_more_lines_2():",
            "    assert True",
            "",
            "def test_more_lines_3():",
            "    assert True",
        ]
    )

    result = agent.run(
        "Review implementation",
        {
            "code": "def run():\n    return 1",
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
            "tests": long_tests,
            "test_validation_summary": "Generated test validation:\n- Missing function imports: none",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
        },
    )

    assert result == "ok"
    assert "Generated tests:" in agent.last_user_message
    assert "- Total lines: 25" in agent.last_user_message
    assert "- Top-level tests: test_happy_path, test_validation_failure, test_batch_processing, test_extra_case, test_more_lines_1, test_more_lines_2, test_more_lines_3" in agent.last_user_message
    assert "Representative excerpt:" in agent.last_user_message
    assert long_tests not in agent.last_user_message


def test_qa_tester_uses_module_name_when_provided(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="test",
        task_title="Tests",
        task_description="Write tests",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "def add(a, b): return a + b",
            "module_name": "math_utils",
            "module_filename": "math_utils.py",
            "code_summary": "def add(a, b): return a + b",
            "code_outline": "def add(a, b):",
            "code_public_api": "Functions:\n- add(a, b)\nClasses:\n- none",
            "code_exact_test_contract": "Exact test contract:\n- Allowed production imports: add\n- Preferred service or workflow facades: none\n- Exact public callables: add(a, b)\n- Exact public class methods: none\n- Exact constructor fields: none\n- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name.",
            "code_test_targets": "Test targets:\n- Functions to test: add(a, b)\n- Classes to test: none\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- add accepts numeric operands",
            "repair_validation_summary": "Generated test validation:\n- Completion diagnostics: likely truncated at completion limit",
            "repair_helper_surface_usages": ["RiskScoringService (line 33)"],
            "repair_helper_surface_symbols": ["RiskScoringService"],
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Module name: math_utils" in agent.last_user_message
    assert "Public API outline:" in agent.last_user_message
    assert "Public API contract:" in agent.last_user_message
    assert "Exact test contract:" in agent.last_user_message
    assert "Allowed production imports: add" in agent.last_user_message
    assert "Test targets:" in agent.last_user_message
    assert "Functions to test: add(a, b)" in agent.last_user_message
    assert "Behavior contract:" in agent.last_user_message
    assert "Implementation code:" in agent.last_user_message
    assert "def add(a, b): return a + b" in agent.last_user_message
    assert "add accepts numeric operands" in agent.last_user_message
    assert "Previous validation summary:" in agent.last_user_message
    assert "Completion diagnostics: likely truncated at completion limit" in agent.last_user_message
    assert "Flagged helper surfaces to remove during repair:" in agent.last_user_message
    assert "Flagged helper-surface references from validation:" in agent.last_user_message
    assert "Deterministic pytest scaffold anchor:" in agent.last_user_message
    assert "from math_utils import add" in agent.last_user_message
    assert "result = add(1, 2)" in agent.last_user_message
    assert "hard blocker" in agent.last_user_message
    assert "def add(a, b):" in agent.last_user_message
    assert "Import from `math_utils`" in agent.last_user_message
    assert "Import every called production function explicitly" in agent.last_user_message
    assert "Import every production class you instantiate or reference in a fixture or test body" in agent.last_user_message
    assert "Concrete class, function, and field names that appear later in generic examples are placeholders only." in agent.last_user_message
    assert "Do not hand-wire validator, scorer, logger, batch-processor, dataclass, or similar helper objects into a service fixture" in agent.last_user_message
    assert "When a public service or workflow facade exists, limit imports to that facade and directly exchanged domain models" in agent.last_user_message
    assert "If you use isinstance or another exact type assertion against a returned production class, import that class explicitly" in agent.last_user_message
    assert "When the API contract exposes typed request or result models, instantiate them with the exact field names and full constructor arity" in agent.last_user_message
    assert "pass every listed field explicitly in test instantiations, including fields that have defaults" in agent.last_user_message
    assert "Do not rely on Python dataclass defaults just because omission would run" in agent.last_user_message
    assert "<request model>(field_a=\"1\", field_b={\"name\": \"John Doe\", \"amount\": 1000}, field_c=1.0, field_d=\"pending\")" in agent.last_user_message
    assert "If the public API says <request model>(field_a, field_b, field_c, field_d, field_e), every constructor call in the suite must pass all five named arguments" in agent.last_user_message
    assert "Do not assert exact score totals or threshold-triggered boolean flags unless the implementation summary or behavior contract explicitly defines the formula or trigger" in agent.last_user_message
    assert "If an exact numeric assertion depends on top-level dict size or collection size" in agent.last_user_message
    assert "do not invent a guessed exact total such as 6.0 or a derived level such as medium" in agent.last_user_message
    assert "do not pair exact score equality with word-like sample strings such as data, valid_data, or data1" in agent.last_user_message
    assert "Respect the task's line budget and requested scenario count exactly." in agent.last_user_message
    assert "If the task sets a fixture maximum, count fixtures before you finalize" in agent.last_user_message
    assert "Do not assert exact categorical score bands or labels at boundary values" in agent.last_user_message
    assert "stay comfortably under that ceiling" in agent.last_user_message
    assert "Leave at least one top-level test of headroom below a stated maximum" in agent.last_user_message
    assert "count top-level tests and total lines explicitly" in agent.last_user_message
    assert "if the task asks for a fixed number of scenarios or tests" in agent.last_user_message
    assert "merge overlapping checks instead of creating helper-specific extra tests" in agent.last_user_message
    assert "If you assert an exact numeric value, use trivially countable inputs" in agent.last_user_message
    assert "never use prose sample text for that assertion" in agent.last_user_message
    assert "every imported production symbol exists in the API contract" in agent.last_user_message
    assert "every imported production symbol also appears in the listed test targets" in agent.last_user_message
    assert "every class instantiation uses only documented constructor arguments" in agent.last_user_message
    assert "when a public service or workflow facade exists, you limited imports to that facade and directly exchanged domain models" in agent.last_user_message
    assert "if you used isinstance or another exact type assertion against a production class, you explicitly imported that class" in agent.last_user_message
    assert "if the API contract exposed typed request or result models, you instantiated them with the exact field names and full constructor arity" in agent.last_user_message
    assert "every constructor call in the suite includes all listed fields instead of omitting a trailing default such as status" in agent.last_user_message
    assert "you used a self-contained literal or previously defined local rather than reading from the object being constructed" in agent.last_user_message
    assert "if the implementation summary or behavior contract did not explicitly define a formula or trigger, you avoided exact score totals and threshold-triggered boolean flags" in agent.last_user_message
    assert "if the previous validation summary lists constructor arity mismatches" in agent.last_user_message
    assert "every happy-path payload satisfies the listed behavior contract and validation rules" in agent.last_user_message
    assert "you stayed at or under it and inlined one-off setup instead of adding a borderline extra fixture" in agent.last_user_message
    assert "you did not add standalone helper or logging tests" in agent.last_user_message
    assert "every exact numeric assertion is supported by an explicit contract or formula" in agent.last_user_message
    assert "you did not infer derived status transitions, escalation flags, or report counters" in agent.last_user_message
    assert "every request, filter, or payload dict in the suite either supplies all documented required fields" in agent.last_user_message
    assert "you computed it from the actual object passed into the scoring function instead of an assumed inner dict" in agent.last_user_message
    assert "if you asserted derived categorical levels or score bands" in agent.last_user_message
    assert "use 50 for a clear low case, 150 for a clear medium case" in agent.last_user_message
    assert "do not use borderline counts such as 2 to assert an exact low or medium label" in agent.last_user_message
    assert "do not assume that field was normalized to only an inner sub-dict" in agent.last_user_message
    assert "you used repeated-character or similarly obvious inputs rather than prose sample text" in agent.last_user_message
    assert "use the direct intake or validation surface for the failure case" in agent.last_user_message
    assert "omit only the field under test and keep the rest of that payload valid" in agent.last_user_message
    assert "Do not assume empty strings, placeholder IDs, or domain keywords are invalid" in agent.last_user_message
    assert "If the implementation only checks types such as isinstance(id, str) or isinstance(data, dict)" in agent.last_user_message
    assert "<request model>(field_a=\"\", field_b={\"field\": \"value\"}) still passes" in agent.last_user_message
    assert "a same-type identifier placeholder can still pass" in agent.last_user_message
    assert "empty dict is still a same-type placeholder and may pass when validation only checks dict type" in agent.last_user_message
    assert "do not shorten them to submit(...) or <batch workflow alias>(...)" in agent.last_user_message
    assert "<request model>(field_a=\"1\", field_b={\"key\": \"wrong_value\"}) is still valid input and should be asserted as a non-compliant result" in agent.last_user_message
    assert "Do not write a validation-failure test as `assert not <validation function>(...)`" in agent.last_user_message
    assert "choose an input that <validation function> rejects before scoring runs" in agent.last_user_message
    assert "do not assume a wrong nested value type makes the request invalid" in agent.last_user_message
    assert "If a validation-failure path leaves the same caller-owned object in a non-success state such as pending or invalid" in agent.last_user_message
    assert "Keep the batch-processing scenario structurally valid" in agent.last_user_message
    assert "If the provided test targets list batch-capable functions" in agent.last_user_message
    assert "If the public API exposes no dedicated batch helper" in agent.last_user_message
    assert "Example: if the module exposes only <primary workflow>(request) and no <batch workflow>(...)" in agent.last_user_message
    assert "If the module exposes only scalar validation, scoring, or audit helpers" in agent.last_user_message
    assert "If the module exposes only helper-level audit or logging functions" in agent.last_user_message
    assert "Example: if the module exposes <validation function>(request), <scoring function>(request), and <audit function>(request_id, action, result), write exactly three tests" in agent.last_user_message
    assert "If a batch helper returns None or constructs its own domain objects from raw items" in agent.last_user_message
    assert "Prefer the highest-level public service or top-level workflow functions" in agent.last_user_message
    assert "Never redeclare production dataclasses, business functions, CLI parsers, or other implementation code inside the pytest module" in agent.last_user_message
    assert "Do not turn copied implementation into `test_main`, `test_all_tests`, or similar meta-tests" in agent.last_user_message
    assert "Do not add standalone caplog or raw logging-output assertions" in agent.last_user_message
    assert "Do not compare full audit or log file contents by exact string equality" in agent.last_user_message
    assert "Do not assert an exact runtime numeric type such as float unless the contract or current implementation explicitly casts to that type." in agent.last_user_message
    assert "derive it from only the branches exercised by the chosen input rather than summing unrelated branch outcomes" in agent.last_user_message
    assert "a request with document_type=\"income\" should assert 1, not 3" in agent.last_user_message
    assert "assert only actions exercised in that same scenario" in agent.last_user_message
    assert "One invalid batch item can emit two failure-related audit entries" in agent.last_user_message
    assert "prefer assertions on returned results, terminal batch markers, or monotonic audit growth" in agent.last_user_message
    assert "Never define a custom fixture named `request`" in agent.last_user_message
    assert "If you use the `pytest.` namespace anywhere in the file, add `import pytest` explicitly at the top of the module." in agent.last_user_message
    assert "Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions" in agent.last_user_message
    assert "Do not import or instantiate CLI wrapper classes such as names ending in `CLI` or `Cli`" in agent.last_user_message
    assert "Do not replace one guessed helper with another guessed helper during repair" in agent.last_user_message
    assert "If the previous suite already passed static validation and only failed at pytest runtime" in agent.last_user_message
    assert "If a pytest-only runtime failure shows that an earlier assertion overreached the current implementation or contract" in agent.last_user_message
    assert "If the previous validation summary reports undefined local names or undefined fixtures" in agent.last_user_message
    assert "If the previous validation summary reports helper surface usages" in agent.last_user_message
    assert "If flagged helper surfaces are listed below" in agent.last_user_message
    assert "Treat the current implementation artifact and API contract as fixed ground truth during repair" in agent.last_user_message
    assert "ComplianceRequest" not in agent.last_user_message
    assert "ComplianceService" not in agent.last_user_message
    assert "Write complete pytest code only; do not stop mid-test, mid-string, or mid-fixture." in agent.last_system_prompt
    assert "Do not import `main`, CLI/demo entrypoints" in agent.last_system_prompt
    assert "Treat CLI wrapper classes such as names ending in `CLI` or `Cli` as entrypoint surfaces to avoid in tests" in agent.last_system_prompt
    assert "stay comfortably under that cap" in agent.last_system_prompt
    assert "When an Exact test contract block is provided, treat it as the highest-priority import, method, and constructor surface." in agent.last_system_prompt
    assert "Concrete class, function, and field names that appear later in generic examples are placeholders only." in agent.last_system_prompt
    assert "Count fixtures before finalizing" in agent.last_system_prompt
    assert "Do not hand-count prose strings to justify exact numeric assertions" in agent.last_system_prompt
    assert "Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols" in agent.last_system_prompt
    assert "never use natural-language prose samples for that assertion" in agent.last_system_prompt
    assert "If an exact numeric assertion depends on nested payload shape" in agent.last_system_prompt
    assert "do not invent a guessed exact total such as 6.0 or a derived level such as medium" in agent.last_system_prompt
    assert "Do not assert exact categorical score bands or labels at boundary values" in agent.last_system_prompt
    assert "do not use amount=100 to assert an exact label" in agent.last_system_prompt
    assert "do not use borderline counts such as 2 to assert an exact low or medium label" in agent.last_system_prompt
    assert "do not assume that field was normalized to only an inner sub-dict" in agent.last_system_prompt
    assert "Do not infer derived status transitions, escalation flags, or report counters" in agent.last_system_prompt
    assert "When an API accepts a request, filter, or payload dict with documented required fields" in agent.last_system_prompt
    assert "When a public service or workflow facade exists, limit imports to that facade and directly exchanged domain models" in agent.last_system_prompt
    assert "If you use isinstance or another exact type assertion against a returned production class, import that class explicitly" in agent.last_system_prompt
    assert "When the API contract exposes typed request or result models, instantiate them with the exact field names and full constructor arity" in agent.last_system_prompt
    assert "pass every listed field explicitly in test instantiations, including fields that have defaults" in agent.last_system_prompt
    assert "Do not rely on Python dataclass defaults just because omission would run" in agent.last_system_prompt
    assert "<request model>(field_a=\"1\", field_b={\"name\": \"John Doe\", \"amount\": 1000}, field_c=1.0, field_d=\"pending\")" in agent.last_system_prompt
    assert "If the public API says <request model>(field_a, field_b, field_c, field_d, field_e), every constructor call in the suite must pass all five named arguments" in agent.last_system_prompt
    assert "Do not read attributes from the object you are still constructing" in agent.last_system_prompt
    assert "Do not assert exact score totals or threshold-triggered boolean flags unless the implementation summary or behavior contract explicitly defines the formula or trigger" in agent.last_system_prompt
    assert "If an exact numeric assertion depends on top-level dict size or collection size" in agent.last_system_prompt
    assert "do not pair exact score equality with word-like sample strings such as data, valid_data, or data1" in agent.last_system_prompt
    assert "keep the validation-failure coverage on the direct intake or validation surface" in agent.last_system_prompt
    assert "omit only the field under test and keep the rest of that payload valid" in agent.last_system_prompt
    assert "Do not assume empty strings, placeholder IDs, or domain keywords are invalid" in agent.last_system_prompt
    assert "If the implementation only checks types such as isinstance(id, str) or isinstance(data, dict)" in agent.last_system_prompt
    assert "<request model>(field_a=\"\", field_b={\"field\": \"value\"}) still passes" in agent.last_system_prompt
    assert "a same-type identifier placeholder can still pass" in agent.last_system_prompt
    assert "empty dict is still a same-type placeholder and may pass when validation only checks dict type" in agent.last_system_prompt
    assert "do not shorten them to submit(...) or <batch workflow alias>(...)" in agent.last_system_prompt
    assert "<request model>(field_a=\"1\", field_b={\"key\": \"wrong_value\"}) is still valid input and should be asserted as a non-compliant result" in agent.last_system_prompt
    assert "Do not write a validation-failure test as `assert not <validation function>(...)`" in agent.last_system_prompt
    assert "choose an input that <validation function> rejects before scoring runs" in agent.last_system_prompt
    assert "do not assume a wrong nested value type makes the request invalid" in agent.last_system_prompt
    assert "If a validation-failure path leaves the same caller-owned object in a non-success state such as pending or invalid" in agent.last_system_prompt
    assert "Keep batch-processing scenarios structurally valid" in agent.last_system_prompt
    assert "If the provided test targets list batch-capable functions" in agent.last_system_prompt
    assert "Leave at least one top-level test of headroom below a stated maximum" in agent.last_system_prompt
    assert "count top-level tests and total lines yourself" in agent.last_system_prompt
    assert "target clear headroom below it instead of landing on the boundary" in agent.last_system_prompt
    assert "If the public API exposes no dedicated batch helper" in agent.last_system_prompt
    assert "Example: if the module exposes only <primary workflow>(request) and no <batch workflow>(...)" in agent.last_system_prompt
    assert "ComplianceRequest" not in agent.last_system_prompt
    assert "ComplianceService" not in agent.last_system_prompt
    assert "If the module exposes only scalar validation, scoring, or audit helpers" in agent.last_system_prompt
    assert "If the module exposes only helper-level audit or logging functions" in agent.last_system_prompt
    assert "Example: if the module exposes <validation function>(request), <scoring function>(request), and <audit function>(request_id, action, result), write exactly three tests" in agent.last_system_prompt
    assert "If a batch helper returns None or constructs its own domain objects from raw items" in agent.last_system_prompt
    assert "Prefer the highest-level public service or top-level workflow functions" in agent.last_system_prompt
    assert "Never redeclare production dataclasses, business functions, CLI parsers, or other implementation code inside the pytest module" in agent.last_system_prompt
    assert "Do not turn copied implementation into `test_main`, `test_all_tests`, or similar meta-tests" in agent.last_system_prompt
    assert "Do not add caplog assertions or raw logging-text expectations" in agent.last_system_prompt
    assert "Do not compare full audit or log file contents by exact string equality" in agent.last_system_prompt
    assert "Do not assert an exact runtime numeric type such as float unless the contract or current implementation explicitly casts to that type." in agent.last_system_prompt
    assert "derive it from only the branches exercised by the chosen input rather than summing unrelated branch outcomes" in agent.last_system_prompt
    assert "a request with document_type=\"income\" should assert 1, not 3" in agent.last_system_prompt
    assert "assert only the actions exercised in that same scenario" in agent.last_system_prompt
    assert "One invalid batch item can emit two failure-related audit entries" in agent.last_system_prompt
    assert "Never define a custom fixture named `request`" in agent.last_system_prompt
    assert "Do not use mock-style bookkeeping assertions such as `.call_count` or `.assert_called_once()`" in agent.last_system_prompt
    assert "When repairing a previously generated suite that already passed static validation" in agent.last_system_prompt
    assert "If the previous validation summary reports undefined local names or undefined fixtures" in agent.last_system_prompt
    assert "If the previous validation summary reports helper surface usages" in agent.last_system_prompt
    assert "If flagged helper surfaces are provided separately in the repair context" in agent.last_system_prompt
    assert "Do not replace one guessed helper with another guessed helper during repair" in agent.last_system_prompt
    assert "Do not invent replacement response classes, alternate validators, renamed helpers, or new return-wrapper types" in agent.last_system_prompt
    assert "do not add direct unit tests for validators, scorers, enums, loggers, dataclasses, or helper utilities" in agent.last_system_prompt
    assert "every non-built-in fixture used by a test is defined in the same file" in agent.last_user_message
    assert "every test function argument is either a built-in fixture, a locally defined fixture, or a name introduced by the matching parametrization" in agent.last_user_message
    assert "every helper or expected-value name referenced inside a test body is imported, defined in the file, or introduced by the matching parametrization" in agent.last_user_message
    assert "every happy-path batch item satisfies the same required fields as the single-request happy path" in agent.last_user_message
    assert "if the validation-failure scenario omits a required field" in agent.last_user_message
    assert "before you finalized, you counted top-level tests and total lines" in agent.last_user_message
    assert "you did not add caplog or raw logging-text assertions unless the behavior contract explicitly makes emitted log output observable" in agent.last_user_message
    assert "if you asserted audit records, every asserted action is exercised in that same scenario" in agent.last_user_message
    assert "you counted audit records from both the inner failing operation and any outer batch failure handler" in agent.last_user_message
    assert "you did not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions" in agent.last_user_message
    assert "validator units, scorer units, dataclass serialization, audit logger wrappers" in agent.last_user_message
    assert "if the previous suite already passed static validation, you preserved valid imports, constructor signatures, fixture payload shapes, and scenario structure" in agent.last_user_message
    assert "you did not invent replacement API names, response-wrapper classes, alternate validators, or alternate constructor signatures during repair" in agent.last_user_message
    assert "if the validation summary reported helper surface usages, you deleted every import, fixture, helper variable, and top-level test" in agent.last_user_message
    assert "if flagged helper surfaces were listed below, none of those names reappear" in agent.last_user_message
    assert "rewrote the full pytest file from the top instead of appending a partial continuation" in agent.last_user_message
    assert "you reduced non-essential comments, blank lines, optional fixtures, and helper scaffolding" in agent.last_user_message
    assert "stay on the main service or batch API" in agent.last_user_message
    assert "no test imports entrypoints listed under \"Entry points to avoid in tests\"" in agent.last_user_message
    assert "no test imports or instantiates CLI wrapper classes such as names ending in `CLI` or `Cli`" in agent.last_user_message
    assert "no test calls main or CLI/demo entrypoints directly unless argv/input is explicitly controlled in the test" in agent.last_user_message
    assert "Every test function argument must be a built-in pytest fixture" in agent.last_system_prompt
    assert "If you are repairing a previously invalid or truncated test file" in agent.last_system_prompt
    assert "Do not reference pytest fixtures unless you define them in the same file" in agent.last_system_prompt
    assert "If you use the `pytest.` namespace anywhere in the file, add `import pytest` explicitly at the top of the module." in agent.last_system_prompt
    assert "remove non-essential comments, blank lines, extra fixtures, and optional helper scaffolding" in agent.last_system_prompt
    assert "Task-specific scope, test-count, and size limits override these defaults" in agent.last_system_prompt


def test_qa_tester_includes_budget_decomposition_brief(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="tests",
        task_title="Tests",
        task_description="Write one compact pytest module under 80 lines.",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "code": "def add(a, b):\n    return a + b",
            "module_name": "math_utils",
            "module_filename": "math_utils.py",
            "budget_decomposition_brief": (
                "- Keep only happy path, validation failure, and batch loop coverage.\n"
                "- Remove helper-only tests and extra fixtures."
            ),
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Budget decomposition brief:" in agent.last_user_message
    assert "Keep only happy path, validation failure, and batch loop coverage." in agent.last_user_message
    assert "compact rewrite plan for this suite" in agent.last_user_message


def test_docs_writer_falls_back_to_code_for_summary(tmp_path):
    agent = CaptureDocsWriterAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="docs",
        task_title="Docs",
        task_description="Write documentation",
        project_name="Demo",
        project_goal="Build demo",
        context={"architecture": "Layered design", "code": "def main(): pass", "module_name": "demo_mod"},
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Goal: Build demo" in agent.last_user_message
    assert "Code summary: def main(): pass" in agent.last_user_message
    assert "Actual module: demo_mod.py" in agent.last_user_message
    assert "Exact run command: No CLI entrypoint detected" in agent.last_user_message
    assert "Dependency manifest: Not provided" in agent.last_user_message
    assert "Dependency validation summary:" in agent.last_user_message


def test_docs_writer_run_uses_context_for_actual_module_and_run_command(tmp_path):
    agent = CaptureDocsWriterAgent(build_config(tmp_path))

    result = agent.run(
        "Write docs",
        {
            "project_name": "Demo",
            "architecture": "Layered design",
            "code_summary": "Core API",
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "dependency_manifest": "requests>=2.31.0",
            "dependency_manifest_path": "artifacts/requirements.txt",
            "dependency_validation_summary": "Dependency manifest validation:\n- Missing manifest entries: none",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
            "module_run_command": "python service_module.py",
            "test_validation_summary": "Generated test validation:\n- Missing function imports: none",
            "code": "def run():\n    return 1",
        },
    )

    assert result == "ok"
    assert "Actual module: service_module.py" in agent.last_user_message
    assert "Exact run command: python service_module.py" in agent.last_user_message
    assert "Dependency manifest: artifacts/requirements.txt" in agent.last_user_message
    assert "requests>=2.31.0" in agent.last_user_message


def test_dependency_manager_uses_code_context_and_requirements_prompt(tmp_path):
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

    result = agent.run_with_input(agent_input)

    assert result.raw_content == "ok"
    assert "Module: demo_mod.py" in agent.last_user_message
    assert "requirements.txt" in agent.last_user_message
    assert "Do not include development-only tools such as pytest" in agent.last_user_message
    assert "Do not use editable installs, local paths, direct URLs, VCS references, or pip installer directives" in agent.last_user_message


def test_dependency_manager_run_uses_context_module_details(tmp_path):
    agent = CaptureDependencyManagerAgent(build_config(tmp_path))

    result = agent.run(
        "Infer runtime dependencies",
        {
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "import requests",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
            "code": "import requests\n\ndef run():\n    return requests.Session()",
        },
    )

    assert result == "ok"
    assert "Module: service_module.py" in agent.last_user_message
    assert "Code summary: import requests" in agent.last_user_message
    assert "Infer the minimal runtime requirements.txt" in agent.last_user_message
    assert "Do not use editable installs, local paths, direct URLs, VCS references, or pip installer directives" in agent.last_user_message


def test_legal_advisor_formats_dependencies_from_typed_context(tmp_path):
    agent = CaptureLegalAdvisorAgent(build_config(tmp_path))
    agent_input = AgentInput(
        task_id="legal",
        task_title="Legal",
        task_description="Review licensing",
        project_name="Demo",
        project_goal="Build demo",
        context={
            "license": "Dual-licensed: AGPL-3.0 open-source distribution or separate commercial terms",
            "dependencies": ["openai", "anthropic"],
        },
    )

    result = agent.run_with_input(agent_input)

    assert result == "ok"
    assert "Project License: Dual-licensed: AGPL-3.0 open-source distribution or separate commercial terms" in agent.last_user_message
    assert "- openai" in agent.last_user_message
    assert "- anthropic" in agent.last_user_message


def test_qa_tester_run_uses_context_module_contract(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Write tests",
        {
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Core API",
            "code_outline": "def run():",
            "code_public_api": "Functions:\n- run()\nClasses:\n- none",
            "existing_tests": "def test_old():\n    assert True",
            "repair_helper_surface_usages": ["RiskScoringService (line 33)"],
            "repair_helper_surface_symbols": ["RiskScoringService"],
        },
    )

    assert result == "ok"
    assert "Module name: service_module" in agent.last_user_message
    assert "Module file: service_module.py" in agent.last_user_message
    assert "Public API contract:" in agent.last_user_message
    assert "Existing tests context:" in agent.last_user_message
    assert "def test_old():" in agent.last_user_message
    assert "Repair the existing pytest file above when it is provided." in agent.last_user_message
    assert "remove or rewrite those constructor calls instead of preserving guessed helper wiring" in agent.last_user_message
    assert "Flagged helper surfaces to remove during repair:" in agent.last_user_message
    assert "Import from `service_module`" in agent.last_user_message
    assert "If you assert an exact numeric value, use trivially countable inputs" in agent.last_user_message
    assert "do not invent a guessed exact total such as 6.0 or a derived level such as medium" in agent.last_user_message
    assert "never use prose sample text for that assertion" in agent.last_user_message
    assert "Do not hard-code exact response.status labels such as accepted, rejected, pending_review, or flagged" in agent.last_user_message
    assert "Do not hard-code exact outcome or action labels such as blocked, escalated, straight-through, manual investigation, fraud escalation, or time-boxed approval in happy-path or valid batch tests" in agent.last_user_message
    assert "Never define a custom fixture named `request`" in agent.last_user_message
    assert "Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions" in agent.last_user_message
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
    assert "you did not expect a wrong nested field type to raise unless the implementation actually performs arithmetic on that value" in agent.last_user_message
    assert "you recomputed the exact total from every exercised term using the current input values before asserting equality" in agent.last_user_message
    assert "risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25" in agent.last_system_prompt
    assert "do not invent a guessed exact total such as 6.0 or a derived level such as medium" in agent.last_system_prompt
    assert "risk_factor=\"invalid\" does not raise TypeError" in agent.last_system_prompt
    assert "use xxxxxxxxxx rather than \"\"" in agent.last_system_prompt
    assert "every happy-path or valid batch item must include the full required set named by that validator" in agent.last_system_prompt
    assert "copy that full list verbatim into every valid happy-path or valid batch payload instead of shrinking it to a representative subset" in agent.last_system_prompt
    assert "Do not require a strictly positive score, non-empty risk list, or similar nonzero scoring side effect from a generic happy-path input" in agent.last_system_prompt
    assert "When the suite already contains a dedicated validation-failure test, do not reuse that invalid payload inside test_batch_processing" in agent.last_system_prompt
    assert "Do not hard-code exact response.status labels such as accepted, rejected, pending_review, or flagged" in agent.last_system_prompt
    assert "Do not hard-code exact outcome or action labels such as blocked, escalated, straight-through, manual investigation, fraud escalation, or time-boxed approval in happy-path or valid batch tests" in agent.last_system_prompt
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


def test_qa_tester_omits_invalid_prior_suite_when_exact_contract_exists(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "class ComplianceRequest:\n"
                "    def __init__(self, request_id, request_type, details, timestamp=None):\n"
                "        self.request_id = request_id\n"
                "        self.request_type = request_type\n"
                "        self.details = details\n"
                "        self.timestamp = timestamp\n\n"
                "class ComplianceIntakeService:\n"
                "    def intake_request(self, request):\n"
                "        return True\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def intake_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.intake_request\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- intake_request accepts a ComplianceRequest instance",
            "existing_tests": (
                "import pytest\n"
                "from service_module import ComplianceService, ComplianceRequest\n\n"
                "def test_intake():\n"
                "    service = ComplianceService()\n"
                "    request = ComplianceRequest(id=\"1\", details=\"ok\")\n"
                "    assert service.intake_request(request) is True\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Unknown module symbols: ComplianceService\n"
                "- Invalid member references: none\n"
                "- Constructor arity mismatches: ComplianceRequest expects 3-4 args but test uses 2 at line 5\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Existing tests context:" in agent.last_user_message
    assert "Previous invalid pytest file omitted because the validation summary already reported invalid import, member, or constructor surface errors." in agent.last_user_message
    assert "Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation instead." in agent.last_user_message
    assert "from service_module import ComplianceService, ComplianceRequest" not in agent.last_user_message
    assert "service = ComplianceService()" not in agent.last_user_message
    assert "request = ComplianceRequest(id=\"1\", details=\"ok\")" not in agent.last_user_message
    assert "Allowed production imports: ComplianceIntakeService, ComplianceRequest" in agent.last_user_message
    assert "ComplianceIntakeService.intake_request" in agent.last_user_message
    assert "Exact rebuild surface:" in agent.last_user_message
    assert "Deterministic pytest scaffold anchor:" in agent.last_user_message
    assert "import pytest\nfrom service_module import ComplianceIntakeService, ComplianceRequest" in agent.last_user_message
    assert "def test_happy_path():" in agent.last_user_message
    assert "service = ComplianceIntakeService()" in agent.last_user_message
    assert 'request = ComplianceRequest(request_id="request_id-1", request_type="screening", details={"source": "web"}, timestamp=1.0)' in agent.last_user_message
    assert "result = service.intake_request(request)" in agent.last_user_message
    assert "Keep mutable services and request objects local to each test or a local helper. Do not lift them to module scope." in agent.last_user_message
    assert "Allowed imports only: ComplianceIntakeService, ComplianceRequest" in agent.last_user_message
    assert "Center the suite on this documented facade: ComplianceIntakeService" in agent.last_user_message
    assert "Use only these documented callables or methods: ComplianceIntakeService.intake_request" in agent.last_user_message
    assert "Keep documented method names exact. Do not shorten or rename ComplianceIntakeService.intake_request." in agent.last_user_message
    assert "Mirror only these documented constructors: ComplianceRequest(request_id, request_type, details, timestamp)" in agent.last_user_message
    assert "Unknown symbols from the previous validation are forbidden in the rewritten file: ComplianceService" in agent.last_user_message
    assert "No batch helper is documented in the exact contract. For any batch scenario, loop over ComplianceIntakeService.intake_request for multiple valid inputs instead of inventing batch helpers or renamed methods." in agent.last_user_message
    assert "Any import, method, or constructor field not listed in the Exact test contract is forbidden in the rewritten file." in agent.last_user_message


def test_qa_tester_omits_prior_suite_when_validation_flags_bare_datetime_without_import(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass\n"
                "from datetime import datetime\n\n"
                "@dataclass\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: datetime\n\n"
                "class ComplianceIntakeService:\n"
                "    def handle_request(self, request):\n"
                "        return request.request_id\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts a ComplianceRequest instance",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from service_module import ComplianceIntakeService, ComplianceRequest\n\n"
                "def test_happy_path():\n"
                "    service = ComplianceIntakeService()\n"
                "    request = ComplianceRequest(request_id='req-1', request_type='screening', details={'source': 'web'}, timestamp=datetime.now())\n"
                "    assert service.handle_request(request) == 'req-1'\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Undefined local names: datetime (line 5)\n"
                "- Pytest execution: FAIL\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Previous invalid pytest file omitted because the validation summary already reported bare `datetime` references without a matching import." in agent.last_user_message
    assert "timestamp=datetime.now()" not in agent.last_user_message
    assert "from datetime import datetime" in agent.last_user_message
    assert "fixed_time = datetime(2024, 1, 1, 0, 0, 0)" in agent.last_user_message
    assert "timestamp=fixed_time" in agent.last_user_message


def test_qa_tester_omits_prior_suite_when_valid_payload_uses_incomplete_required_evidence(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass\n"
                "from datetime import datetime\n\n"
                "@dataclass\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: datetime\n\n"
                "@dataclass\n"
                "class RiskScore:\n"
                "    request_id: str\n"
                "    score: float\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self):\n"
                "        self.risk_scores = []\n\n"
                "    def handle_request(self, request):\n"
                "        if not self.validate_request(request):\n"
                "            return\n"
                "        self.risk_scores.append(RiskScore(request.request_id, 0.0))\n\n"
                "    def validate_request(self, request):\n"
                "        required_evidence = ['ID', 'Address', 'Proof of Income']\n"
                "        return all(item in request.details.get('documents', []) for item in required_evidence)\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- RiskScore(request_id, score)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest, RiskScore\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request), ComplianceIntakeService.validate_request(request)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp), RiskScore(request_id, score)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request appends to risk_scores only for valid requests",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from datetime import datetime\n"
                "from service_module import ComplianceIntakeService, ComplianceRequest, RiskScore\n\n"
                "def test_happy_path():\n"
                "    service = ComplianceIntakeService()\n"
                "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
                "    request = ComplianceRequest(request_id='req-1', request_type='individual', details={'documents': ['ID']}, timestamp=fixed_time)\n"
                "    service.handle_request(request)\n"
                "    assert len(service.risk_scores) == 1\n\n"
                "def test_validation_failure():\n"
                "    service = ComplianceIntakeService()\n"
                "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
                "    request = ComplianceRequest(request_id='req-2', request_type='individual', details={'documents': []}, timestamp=fixed_time)\n"
                "    service.handle_request(request)\n"
                "    assert len(service.risk_scores) == 0\n\n"
                "def test_batch_processing():\n"
                "    service = ComplianceIntakeService()\n"
                "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
                "    requests = [\n"
                "        ComplianceRequest(request_id='req-3', request_type='individual', details={'documents': ['ID']}, timestamp=fixed_time),\n"
                "        ComplianceRequest(request_id='req-4', request_type='individual', details={'documents': ['ID']}, timestamp=fixed_time),\n"
                "    ]\n"
                "    for request in requests:\n"
                "        service.handle_request(request)\n"
                "    assert len(service.risk_scores) == 2\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Pytest execution: FAIL\n"
                "- Pytest failure details: FAILED tests_tests.py::test_happy_path - AssertionError: assert 0 == 1; FAILED tests_tests.py::test_batch_processing - AssertionError: assert 0 == 2\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Previous invalid pytest file omitted because the current runtime failure shows that supposed happy-path or batch payloads still omit required evidence named by the implementation validator." in agent.last_user_message
    assert "details={'documents': ['ID']}, timestamp=fixed_time" not in agent.last_user_message
    assert "The implementation validator names the full required evidence list as ['ID', 'Address', 'Proof of Income']." in agent.last_user_message
    assert "details={'documents': ['ID', 'Address', 'Proof of Income']}, timestamp=fixed_time" in agent.last_user_message
    assert "Do not reuse reduced or empty document subsets like ['ID'] or [] inside happy-path or batch tests." in agent.last_user_message


def test_qa_tester_omits_prior_suite_when_batch_keeps_invalid_missing_document_item(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass\n"
                "from datetime import datetime\n\n"
                "@dataclass\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: datetime\n\n"
                "@dataclass\n"
                "class RiskScore:\n"
                "    request_id: str\n"
                "    score: float\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self):\n"
                "        self.risk_scores = []\n\n"
                "    def handle_request(self, request):\n"
                "        if not self.validate_request(request):\n"
                "            return\n"
                "        self.risk_scores.append(RiskScore(request.request_id, 0.0))\n\n"
                "    def validate_request(self, request):\n"
                "        required_evidence = ['ID', 'Address', 'Proof of Income']\n"
                "        return all(item in request.details.get('documents', []) for item in required_evidence)\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- RiskScore(request_id, score)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest, RiskScore\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request), ComplianceIntakeService.validate_request(request)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp), RiskScore(request_id, score)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request appends to risk_scores only for valid requests",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from datetime import datetime\n"
                "from service_module import ComplianceIntakeService, ComplianceRequest, RiskScore\n\n"
                "def test_happy_path():\n"
                "    service = ComplianceIntakeService()\n"
                "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
                "    request = ComplianceRequest(request_id='req-1', request_type='individual', details={'documents': ['ID', 'Address', 'Proof of Income']}, timestamp=fixed_time)\n"
                "    service.handle_request(request)\n"
                "    assert len(service.risk_scores) == 1\n\n"
                "def test_validation_failure():\n"
                "    service = ComplianceIntakeService()\n"
                "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
                "    request = ComplianceRequest(request_id='req-2', request_type='individual', details={'documents': ['ID']}, timestamp=fixed_time)\n"
                "    service.handle_request(request)\n"
                "    assert len(service.risk_scores) == 0\n\n"
                "def test_batch_processing():\n"
                "    service = ComplianceIntakeService()\n"
                "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
                "    requests = [\n"
                "        ComplianceRequest(request_id='req-3', request_type='individual', details={'documents': ['ID', 'Address', 'Proof of Income']}, timestamp=fixed_time),\n"
                "        ComplianceRequest(request_id='req-4', request_type='corporate', details={'documents': []}, timestamp=fixed_time),\n"
                "    ]\n"
                "    for request in requests:\n"
                "        service.handle_request(request)\n"
                "    assert len(service.risk_scores) == 2\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Pytest execution: FAIL\n"
                "- Pytest failure details: FAILED tests_tests.py::test_batch_processing - AssertionError: assert 1 == 2\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Previous invalid pytest file omitted because the current runtime failure shows that supposed happy-path or batch payloads still omit required evidence named by the implementation validator." in agent.last_user_message
    assert "details={'documents': []}, timestamp=fixed_time" not in agent.last_user_message
    assert "Do not reuse reduced or empty document subsets like ['ID'] or [] inside happy-path or batch tests." in agent.last_user_message
    assert "details={'documents': ['ID', 'Address', 'Proof of Income']}, timestamp=fixed_time" in agent.last_user_message


def test_qa_tester_omits_prior_suite_when_valid_paths_omit_required_payload_keys(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass, field\n"
                "from datetime import datetime\n"
                "from typing import List\n\n"
                "@dataclass\n"
                "class ClaimRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: datetime = field(default_factory=datetime.now)\n\n"
                "@dataclass\n"
                "class ClaimResult:\n"
                "    request_id: str\n"
                "    status: str\n"
                "    risk_score: float\n"
                "    timestamp: datetime = field(default_factory=datetime.now)\n\n"
                "class ClaimTriageService:\n"
                "    def validate_request(self, request: ClaimRequest) -> bool:\n"
                "        required_fields = {'policy_id', 'claim_type', 'amount', 'timestamp'}\n"
                "        return required_fields.issubset(request.details) and isinstance(request.details.get('amount'), (int, float))\n\n"
                "    def handle_request(self, request: ClaimRequest) -> ClaimResult:\n"
                "        if not self.validate_request(request):\n"
                "            raise ValueError('Invalid claim request')\n"
                "        return ClaimResult(request.request_id, 'straight-through', 0.0, request.timestamp)\n\n"
                "    def batch_handle_requests(self, requests: List[ClaimRequest]) -> List[ClaimResult]:\n"
                "        return [self.handle_request(request) for request in requests]\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Claim triage workflow",
            "code_outline": "class ClaimTriageService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ClaimRequest(request_id, request_type, details, timestamp)\n- ClaimResult(request_id, status, risk_score, timestamp)\n- ClaimTriageService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ClaimRequest, ClaimResult, ClaimTriageService\n"
                "- Preferred service or workflow facades: ClaimTriageService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ClaimTriageService.handle_request(request), ClaimTriageService.validate_request(request), ClaimTriageService.batch_handle_requests(requests)\n"
                "- Exact constructor fields: ClaimRequest(request_id, request_type, details, timestamp), ClaimResult(request_id, status, risk_score, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ClaimTriageService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- validate_request rejects requests when required payload fields are missing\n- handle_request raises ValueError for invalid requests",
            "task_public_contract_anchor": (
                "- Public facade: ClaimTriageService\n"
                "- Primary request model: ClaimRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ClaimTriageService.handle_request(request)\n"
                "- Supporting validation surface: ClaimTriageService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "import pytest\n"
                "from datetime import datetime\n"
                "from service_module import ClaimTriageService, ClaimRequest, ClaimResult\n\n"
                "def test_happy_path():\n"
                "    service = ClaimTriageService()\n"
                "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
                "    request = ClaimRequest(request_id='request_id-1', request_type='car', details={'policy_id': 'policy123', 'amount': 5000, 'timestamp': fixed_time}, timestamp=fixed_time)\n"
                "    result = service.handle_request(request)\n"
                "    assert result.status == 'straight-through'\n\n"
                "def test_validation_failure():\n"
                "    service = ClaimTriageService()\n"
                "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
                "    request = ClaimRequest(request_id='request_id-1', request_type='car', details={'policy_id': 'value', 'claim_type': 'value', 'amount': 'value'}, timestamp=fixed_time)\n"
                "    is_valid = service.validate_request(request)\n"
                "    assert is_valid is False\n"
                "    with pytest.raises(ValueError):\n"
                "        service.handle_request(request)\n\n"
                "def test_batch_processing():\n"
                "    service = ClaimTriageService()\n"
                "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
                "    requests = [\n"
                "        ClaimRequest(request_id='request_id-1', request_type='car', details={'policy_id': 'policy123', 'amount': 5000, 'timestamp': fixed_time}, timestamp=fixed_time),\n"
                "    ]\n"
                "    results = service.batch_handle_requests(requests)\n"
                "    assert len(results) == 1\n"
                "    assert results[0].status == 'straight-through'\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Pytest execution: FAIL\n"
                "- Pytest failure details: FAILED tests_tests.py::test_happy_path - ValueError: Invalid claim request | ValueError: Invalid claim request; FAILED tests_tests.py::test_batch_processing - ValueError: Invalid claim request | ValueError: Invalid claim request\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Previous invalid pytest file omitted because the current runtime failure shows that supposed happy-path or batch payloads still omit required payload fields named by the implementation validator." in agent.last_user_message
    assert "details={'policy_id': 'policy123', 'amount': 5000, 'timestamp': fixed_time}, timestamp=fixed_time" not in agent.last_user_message
    assert "The current validator only checks for the presence of ['policy_id', 'claim_type', 'amount', 'timestamp']." in agent.last_user_message
    assert 'details={"policy_id": "policy123", "claim_type": "collision", "amount": 5000, "timestamp": fixed_time}, timestamp=fixed_time' in agent.last_user_message
    assert "Do not reuse partial payloads that omit required keys inside happy-path or batch tests." in agent.last_user_message


def test_qa_tester_omits_hollow_prior_suite_when_validation_flags_call_only_tests(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "class ComplianceRequest:\n"
                "    def __init__(self, request_id, request_type, details, timestamp=None):\n"
                "        self.request_id = request_id\n"
                "        self.request_type = request_type\n"
                "        self.details = details\n"
                "        self.timestamp = timestamp\n\n"
                "class ComplianceIntakeService:\n"
                "    def handle_request(self, request):\n"
                "        return {'request_id': request.request_id}\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts a ComplianceRequest instance",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from service_module import ComplianceIntakeService, ComplianceRequest\n\n"
                "def test_happy_path():\n"
                "    service = ComplianceIntakeService()\n"
                "    request = ComplianceRequest(request_id=\"1\", request_type=\"screening\", details={\"source\": \"web\"}, timestamp=1.0)\n"
                "    service.handle_request(request)\n\n"
                "def test_batch_processing():\n"
                "    service = ComplianceIntakeService()\n"
                "    for request_id in [\"1\", \"2\"]:\n"
                "        service.handle_request(ComplianceRequest(request_id=request_id, request_type=\"screening\", details={\"source\": \"web\"}, timestamp=1.0))\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Tests without assertion-like checks: test_happy_path (line 3), test_batch_processing (line 8)\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Existing tests context:" in agent.last_user_message
    assert "Previous hollow pytest file omitted because the validation summary already reported top-level tests without assertion-like checks." in agent.last_user_message
    assert "Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch around only the minimum contract-backed scenarios" in agent.last_user_message
    assert 'for request_id in ["1", "2"]:' not in agent.last_user_message
    assert "If repair feedback reports tests without assertion-like checks, discard the prior hollow test bodies and rebuild the minimum contract-backed suite with explicit assertions instead of patching the old file in place." in agent.last_system_prompt


def test_qa_tester_omits_overreaching_prior_suite_when_validation_flags_contract_overreach(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "class ComplianceRequest:\n"
                "    def __init__(self, request_id, request_type, details, timestamp=None):\n"
                "        self.request_id = request_id\n"
                "        self.request_type = request_type\n"
                "        self.details = details\n"
                "        self.timestamp = timestamp\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self):\n"
                "        self.audit_log = []\n\n"
                "    def handle_request(self, request):\n"
                "        self.audit_log.append({'request_id': request.request_id, 'status': 'approved'})\n"
                "        return {'request_id': request.request_id, 'status': 'approved'}\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts a ComplianceRequest instance",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from service_module import ComplianceIntakeService, ComplianceRequest\n\n"
                "def test_batch_processing():\n"
                "    service = ComplianceIntakeService()\n"
                "    requests = [\n"
                "        ComplianceRequest(request_id='1', request_type='screening', details={'source': 'web'}, timestamp=1.0),\n"
                "        ComplianceRequest(request_id='2', request_type='screening', details={'source': 'web'}, timestamp=1.0),\n"
                "    ]\n"
                "    for request in requests:\n"
                "        result = service.handle_request(request)\n"
                "    assert len(service.audit_log) == 3\n"
                "    assert result['status'] == 'blocked'\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Contract overreach signals: exact batch audit length 3 exceeds visible batch size 2 in test_batch_processing (line 10), exact status/action label mismatch ('escalated' vs 'blocked') suggests an unsupported threshold assumption\n"
                "- Pytest execution: FAIL\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Existing tests context:" in agent.last_user_message
    assert "Previous overreaching pytest file omitted because the validation summary already reported contract-overreach assertions." in agent.last_user_message
    assert "Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch around only contract-backed scenarios" in agent.last_user_message
    assert "assert len(service.audit_log) == 3" not in agent.last_user_message
    assert "assert result['status'] == 'blocked'" not in agent.last_user_message
    assert "Exact rebuild surface:" in agent.last_user_message
    assert "Allowed imports only: ComplianceIntakeService, ComplianceRequest" in agent.last_user_message
    assert "Any import, method, or constructor field not listed in the Exact test contract is forbidden in the rewritten file." in agent.last_user_message
    assert "The previous suite overreached by expecting more batch audit entries than the visible number of processed items." in agent.last_user_message
    assert "The previous runtime failure came from a brittle exact status or action label guess." in agent.last_user_message
    assert "In happy-path or valid batch scenarios, do not assert exact outcome strings such as `straight-through` or `manual investigation` unless the contract explicitly defines that input-to-label mapping" in agent.last_user_message
    assert "Apply the same rule to return-review labels such as `auto-approve`, `manual inspection`, and `abuse escalation`" in agent.last_user_message
    assert "If the previous validation summary reports contract overreach signals, that prior suite guessed behavior beyond the documented contract." in agent.last_system_prompt


def test_qa_tester_omits_overreaching_prior_suite_when_validation_flags_return_shape_assumption(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "class AccessReviewRequest:\n"
                "    def __init__(self, request_id, request_type, details, timestamp=None):\n"
                "        self.request_id = request_id\n"
                "        self.request_type = request_type\n"
                "        self.details = details\n"
                "        self.timestamp = timestamp\n\n"
                "class AccessReviewService:\n"
                "    def handle_request(self, request):\n"
                "        return 'approved'\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Access review workflow",
            "code_outline": "class AccessReviewService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- AccessReviewRequest(request_id, request_type, details, timestamp)\n- AccessReviewService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: AccessReviewRequest, AccessReviewService\n"
                "- Preferred service or workflow facades: AccessReviewService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: AccessReviewService.handle_request(request)\n"
                "- Exact constructor fields: AccessReviewRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: AccessReviewService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts an AccessReviewRequest instance",
            "task_public_contract_anchor": (
                "- Public facade: AccessReviewService\n"
                "- Primary request model: AccessReviewRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: AccessReviewService.handle_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from service_module import AccessReviewRequest, AccessReviewService\n\n"
                "def test_happy_path():\n"
                "    service = AccessReviewService()\n"
                "    request = AccessReviewRequest(request_id='1', request_type='review', details={'role': 'admin'}, timestamp=1.0)\n"
                "    outcome = service.handle_request(request)\n"
                "    assert outcome.request_id == '1'\n"
                "    assert outcome.outcome == 'approved'\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Contract overreach signals: exact return-shape attribute assumption ('.request_id' on 'str') suggests an unsupported wrapper expectation\n"
                "- Pytest execution: FAIL\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Previous overreaching pytest file omitted because the validation summary already reported contract-overreach assertions." in agent.last_user_message
    assert "assert outcome.request_id == '1'" not in agent.last_user_message
    assert "assert outcome.outcome == 'approved'" not in agent.last_user_message
    assert "The previous runtime failure came from assuming a wrapped object return shape that the current runtime did not provide." in agent.last_user_message
    assert "Delete every `.request_id`, `.outcome`, or similar attribute read on the workflow return value in happy-path and batch tests." in agent.last_user_message
    assert "assert isinstance(result, str)" in agent.last_user_message
    assert "Exact rebuild surface:" in agent.last_user_message


def test_qa_tester_omits_overreaching_prior_suite_when_validation_flags_action_map_key_assumption(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass, field\n"
                "from datetime import datetime\n\n"
                "@dataclass\n"
                "class VendorSubmission:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: datetime\n\n"
                "@dataclass\n"
                "class ReviewAction:\n"
                "    action_id: str\n"
                "    action_type: str\n"
                "    details: dict\n"
                "    timestamp: datetime = field(default_factory=datetime.now)\n\n"
                "class VendorRiskReviewService:\n"
                "    def __init__(self):\n"
                "        self.review_actions = {}\n\n"
                "    def handle_request(self, request):\n"
                "        action = ReviewAction(action_id='generated-action-id', action_type='approve', details={})\n"
                "        self.review_actions[action.action_id] = action\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Vendor review workflow",
            "code_outline": "class VendorRiskReviewService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- VendorSubmission(request_id, request_type, details, timestamp)\n- ReviewAction(action_id, action_type, details, timestamp)\n- VendorRiskReviewService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ReviewAction, VendorRiskReviewService, VendorSubmission\n"
                "- Preferred service or workflow facades: VendorRiskReviewService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: VendorRiskReviewService.handle_request(request)\n"
                "- Exact constructor fields: VendorSubmission(request_id, request_type, details, timestamp), ReviewAction(action_id, action_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: VendorRiskReviewService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request stores one ReviewAction for a valid request",
            "task_public_contract_anchor": (
                "- Public facade: VendorRiskReviewService\n"
                "- Primary request model: VendorSubmission(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: VendorRiskReviewService.handle_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from service_module import VendorRiskReviewService, VendorSubmission\n\n"
                "def test_happy_path():\n"
                "    service = VendorRiskReviewService()\n"
                "    vendor_submission = VendorSubmission(request_id='request_id-1', request_type='onboarding', details={'service_category': 'IT'}, timestamp=1.0)\n"
                "    service.handle_request(vendor_submission)\n"
                "    assert vendor_submission.request_id in service.review_actions\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Contract overreach signals: exact internal action-map key assumption for 'review_actions' suggests an unsupported storage-key contract\n"
                "- Pytest execution: FAIL\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Previous overreaching pytest file omitted because the validation summary already reported contract-overreach assertions." in agent.last_user_message
    assert "assert vendor_submission.request_id in service.review_actions" not in agent.last_user_message
    assert "The previous runtime failure came from assuming an internal action or review map used request identity as its key." in agent.last_user_message
    assert "Do not assert membership like `request.request_id in service.review_actions` unless the contract explicitly defines that storage key." in agent.last_user_message
    assert "If the implementation stores `ReviewAction(action_id, ...)` or another action record with its own generated identifier" in agent.last_user_message


def test_qa_tester_combines_return_shape_and_did_not_raise_repair_guidance(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "class AccessReviewRequest:\n"
                "    def __init__(self, request_id, request_type, details, timestamp=None):\n"
                "        self.request_id = request_id\n"
                "        self.request_type = request_type\n"
                "        self.details = details\n"
                "        self.timestamp = timestamp\n\n"
                "class AccessReviewService:\n"
                "    def validate_request(self, request):\n"
                "        return request.request_type in {'role assignment', 'system access'} and 'role' in request.details\n\n"
                "    def handle_request(self, request):\n"
                "        if not self.validate_request(request):\n"
                "            raise ValueError('Invalid request')\n"
                "        return 'approved'\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Access review workflow",
            "code_outline": "class AccessReviewService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- AccessReviewRequest(request_id, request_type, details, timestamp)\n- AccessReviewService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: AccessReviewRequest, AccessReviewService\n"
                "- Preferred service or workflow facades: AccessReviewService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: AccessReviewService.handle_request(request), AccessReviewService.validate_request(request)\n"
                "- Exact constructor fields: AccessReviewRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: AccessReviewService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request raises ValueError for invalid requests",
            "task_public_contract_anchor": (
                "- Public facade: AccessReviewService\n"
                "- Primary request model: AccessReviewRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: AccessReviewService.handle_request(request)\n"
                "- Supporting validation surface: AccessReviewService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from service_module import AccessReviewRequest, AccessReviewService\n\n"
                "def test_happy_path():\n"
                "    service = AccessReviewService()\n"
                "    request = AccessReviewRequest(request_id='1', request_type='role assignment', details={'role': 'admin'}, timestamp=1.0)\n"
                "    outcome = service.handle_request(request)\n"
                "    assert outcome.request_id == '1'\n"
                "    assert outcome.outcome == 'approved'\n\n"
                "def test_validation_failure():\n"
                "    service = AccessReviewService()\n"
                "    request = AccessReviewRequest(request_id='2', request_type='role assignment', details={'role': 'user'}, timestamp=1.0)\n"
                "    with pytest.raises(ValueError):\n"
                "        service.handle_request(request)\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Contract overreach signals: exact return-shape attribute assumption ('.request_id' on 'str') suggests an unsupported wrapper expectation\n"
                "- Pytest execution: FAIL\n"
                "- Pytest failure details: FAILED tests_tests.py::test_validation_failure - Failed: DID NOT RAISE <class 'ValueError'>\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "A previous validation-failure test expected an exception that the current input did not trigger." in agent.last_user_message
    assert "The failed suite mixed a guessed return wrapper with a guessed exception path." in agent.last_user_message
    assert "make the validation-failure test use an input that the current validator actually rejects instead of a same-type business variation" in agent.last_user_message
    assert "assert isinstance(result, str)" in agent.last_user_message
    assert "assert is_valid is False" in agent.last_user_message
    assert "with pytest.raises(ValueError):" in agent.last_user_message


def test_qa_tester_omits_overreaching_prior_suite_when_validation_flags_score_state_emptiness_assumption(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass\n\n"
                "@dataclass\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: float\n\n"
                "@dataclass\n"
                "class RiskScore:\n"
                "    request_id: str\n"
                "    score: float\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self):\n"
                "        self._risk_scores = {}\n\n"
                "    def handle_request(self, request):\n"
                "        return 'rejected'\n\n"
                "    def get_risk_scores(self):\n"
                "        return dict(self._risk_scores)\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...\n    def get_risk_scores(self): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- RiskScore(request_id, score)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest, RiskScore\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request), ComplianceIntakeService.get_risk_scores()\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp), RiskScore(request_id, score)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request returns a rejected outcome for invalid requests",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.get_risk_scores()\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from service_module import ComplianceIntakeService, ComplianceRequest\n\n"
                "def test_validation_failure():\n"
                "    service = ComplianceIntakeService()\n"
                "    request = ComplianceRequest(request_id='1', request_type='screening', details={}, timestamp=1.0)\n"
                "    service.handle_request(request)\n"
                "    assert len(service.get_risk_scores()) == 0\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Contract overreach signals: exact validation-failure score-state emptiness assertion on 'service.get_risk_scores()' in test_validation_failure (line 5) assumes rejected input leaves internal score state empty\n"
                "- Pytest execution: FAIL\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Previous overreaching pytest file omitted because the validation summary already reported contract-overreach assertions." in agent.last_user_message
    assert "request = ComplianceRequest(request_id='1', request_type='screening', details={}, timestamp=1.0)" not in agent.last_user_message
    assert "The previous runtime failure came from assuming a rejected or invalid request leaves internal score state empty." in agent.last_user_message
    assert "observable contract-backed effect" in agent.last_user_message
    assert "remove direct reads of `service.get_risk_scores()` or similar internal score state" in agent.last_user_message
    assert "def test_validation_failure():" in agent.last_user_message


def test_qa_tester_replaces_placeholder_boolean_assertions(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "class ComplianceRequest:\n"
                "    def __init__(self, request_id, request_type, details, timestamp=None):\n"
                "        self.request_id = request_id\n"
                "        self.request_type = request_type\n"
                "        self.details = details\n"
                "        self.timestamp = timestamp\n\n"
                "class ComplianceIntakeService:\n"
                "    def validate_request(self, request):\n"
                "        return 'documents' in request.details\n\n"
                "    def handle_request(self, request):\n"
                "        return None\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request), ComplianceIntakeService.validate_request(request)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- validate_request returns False when documents are missing",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)"
            ),
            "existing_tests": (
                "from service_module import ComplianceIntakeService, ComplianceRequest\n\n"
                "def test_validation_failure():\n"
                "    service = ComplianceIntakeService()\n"
                "    request = ComplianceRequest(request_id='1', request_type='individual', details={}, timestamp=1.0)\n"
                "    service.handle_request(request)\n"
                "    assert False  # Assuming handle_request rejects the request\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Pytest execution: FAIL\n"
                "- Pytest failure details: FAILED tests_tests.py::test_validation_failure - assert False | assert False\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Previous hollow pytest file omitted because the validation summary already reported placeholder boolean assertions instead of real expectations." in agent.last_user_message
    assert "Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch around only the minimum contract-backed scenarios" in agent.last_user_message
    assert "assert False  # Assuming handle_request rejects the request" not in agent.last_user_message
    assert "Exact rebuild surface:" in agent.last_user_message
    assert "The previous suite used a placeholder boolean failure such as `assert False` instead of a real contract-backed expectation." in agent.last_user_message
    assert "Delete that placeholder and replace it with an explicit validation result, raised exception, or observable side effect." in agent.last_user_message
    assert "assert is_valid is False" in agent.last_user_message
    assert "service.handle_request(request)(request)" not in agent.last_user_message
    assert "service.validate_request(request)(request)" not in agent.last_user_message
    assert "assert result is None" in agent.last_user_message


def test_qa_tester_omits_validation_side_effect_suite_without_workflow_call(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "class AuditRecord:\n"
                "    def __init__(self, request_id, action, details):\n"
                "        self.request_id = request_id\n"
                "        self.action = action\n"
                "        self.details = details\n\n"
                "class ComplianceRequest:\n"
                "    def __init__(self, request_id, request_type, details, timestamp=None):\n"
                "        self.request_id = request_id\n"
                "        self.request_type = request_type\n"
                "        self.details = details\n"
                "        self.timestamp = timestamp\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self):\n"
                "        self.audit_log = []\n\n"
                "    def validate_request(self, request):\n"
                "        return 'documents' in request.details\n\n"
                "    def handle_request(self, request):\n"
                "        if not self.validate_request(request):\n"
                "            self.audit_log.append(AuditRecord(request.request_id, 'blocked', 'Validation failed'))\n"
                "            return None\n"
                "        self.audit_log.append(AuditRecord(request.request_id, 'approved', 'Accepted'))\n"
                "        return None\n\n"
                "    def get_audit_log(self):\n"
                "        return self.audit_log\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- AuditRecord(request_id, action, details)\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: AuditRecord, ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request), ComplianceIntakeService.validate_request(request), ComplianceIntakeService.get_audit_log()\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request appends a blocked audit record when validation fails",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)"
            ),
            "existing_tests": (
                "from service_module import AuditRecord, ComplianceIntakeService, ComplianceRequest\n\n"
                "def test_validation_failure():\n"
                "    service = ComplianceIntakeService()\n"
                "    request = ComplianceRequest(request_id='1', request_type='individual', details={}, timestamp=1.0)\n"
                "    is_valid = service.validate_request(request)\n"
                "    assert is_valid is False\n"
                "    audit_log = service.get_audit_log()\n"
                "    assert len(audit_log) == 1\n"
                "    assert audit_log[0].action == 'blocked'\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Pytest execution: FAIL\n"
                "- Pytest failure details: FAILED tests_tests.py::test_validation_failure - assert 0 == 1 | assert 0 == 1\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Previous invalid pytest file omitted because the validation-failure test asserted audit or service side effects after calling only `validate_request(...)` without executing the workflow." in agent.last_user_message
    assert "Do not preserve or patch the previous pytest file in place. Rewrite the suite from scratch" in agent.last_user_message
    assert "assert len(audit_log) == 1" not in agent.last_user_message
    assert "result = service.handle_request(request)" in agent.last_user_message
    assert "assert result is None" in agent.last_user_message
    assert "If `test_validation_failure` later asserts audit records, risk-score state, or another workflow side effect, keep the documented workflow call in that test." in agent.last_user_message


def test_qa_tester_omits_presence_only_validation_suite_with_same_shape_placeholder_payload(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass, field\n"
                "from datetime import datetime\n\n"
                "@dataclass\n"
                "class ClaimRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: datetime = field(default_factory=datetime.now)\n\n"
                "@dataclass\n"
                "class ClaimResult:\n"
                "    request_id: str\n"
                "    result: str\n"
                "    risk_score: float\n\n"
                "class ClaimTriageService:\n"
                "    def validate_request(self, request: ClaimRequest) -> bool:\n"
                "        required_fields = {'policy_id', 'claim_type', 'loss_amount'}\n"
                "        if not required_fields.issubset(request.details):\n"
                "            return False\n"
                "        return True\n\n"
                "    def handle_request(self, request: ClaimRequest) -> ClaimResult:\n"
                "        if not self.validate_request(request):\n"
                "            raise ValueError('Invalid claim request')\n"
                "        return ClaimResult(request.request_id, 'straight-through', 0.0)\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Claim triage workflow",
            "code_outline": "class ClaimTriageService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ClaimRequest(request_id, request_type, details, timestamp)\n- ClaimResult(request_id, result, risk_score)\n- ClaimTriageService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ClaimRequest, ClaimResult, ClaimTriageService\n"
                "- Preferred service or workflow facades: ClaimTriageService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ClaimTriageService.handle_request(request), ClaimTriageService.validate_request(request)\n"
                "- Exact constructor fields: ClaimRequest(request_id, request_type, details, timestamp), ClaimResult(request_id, result, risk_score)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ClaimTriageService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- validate_request returns False only when required fields are missing",
            "task_public_contract_anchor": (
                "- Public facade: ClaimTriageService\n"
                "- Primary request model: ClaimRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ClaimTriageService.handle_request(request)\n"
                "- Supporting validation surface: ClaimTriageService.validate_request(request)"
            ),
            "existing_tests": (
                "import pytest\n"
                "from datetime import datetime\n"
                "from service_module import ClaimTriageService, ClaimRequest, ClaimResult\n\n"
                "def test_validation_failure():\n"
                "    service = ClaimTriageService()\n"
                "    fixed_time = datetime(2024, 1, 1, 0, 0, 0)\n"
                "    request = ClaimRequest(request_id=\"request_id-1\", request_type=\"screening\", details={\"policy_id\": \"value\", \"claim_type\": \"value\", \"loss_amount\": \"value\"}, timestamp=fixed_time)\n"
                "    is_valid = service.validate_request(request)\n"
                "    assert is_valid is False\n"
                "    with pytest.raises(ValueError):\n"
                "        service.handle_request(request)\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Pytest execution: FAIL\n"
                "- Pytest failure details: FAILED tests_tests.py::test_validation_failure - assert True is False | assert True is False\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Previous invalid pytest file omitted because the validation-failure payload still keeps every required field that the current validator only checks for presence." in agent.last_user_message
    assert "Do not preserve or patch the previous pytest file in place." in agent.last_user_message
    assert 'details={"policy_id": "value", "claim_type": "value", "loss_amount": "value"}, timestamp=fixed_time' not in agent.last_user_message
    assert 'details={"policy_id": "policy123", "claim_type": "collision"}, timestamp=fixed_time' in agent.last_user_message
    assert "The previous validation-failure test still kept every required payload field that the current validator only checks for presence." in agent.last_user_message
    assert "omit one of those required fields instead of keeping all of them with placeholder values" in agent.last_user_message


def test_qa_tester_omits_prior_suite_when_validation_flags_undefined_helper_alias(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass\n\n"
                "@dataclass\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: float\n\n"
                "@dataclass\n"
                "class AuditLog:\n"
                "    request_id: str\n"
                "    action: str\n"
                "    details: dict\n\n"
                "class ComplianceIntakeService:\n"
                "    def handle_request(self, request):\n"
                "        return AuditLog(request.request_id, 'accepted', request.details)\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- AuditLog(request_id, action, details)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest, AuditLog\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp), AuditLog(request_id, action, details)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts a ComplianceRequest instance and returns an AuditLog record",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)"
            ),
            "existing_tests": (
                "from service_module import AuditLog, ComplianceIntakeService, ComplianceRequest\n\n"
                "def test_happy_path():\n"
                "    service = ComplianceIntakeService(AuditLogger())\n"
                "    request = ComplianceRequest(request_id='1', request_type='screening', details={'source': 'web'}, timestamp=1.0)\n"
                "    result = service.handle_request(request)\n"
                "    assert result.request_id == '1'\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Imported module symbols: AuditLog, ComplianceIntakeService, ComplianceRequest\n"
                "- Undefined local names: AuditLogger (line 4)\n"
                "- Pytest execution: FAIL\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Existing tests context:" in agent.last_user_message
    assert "Previous invalid pytest file omitted because the validation summary reported undefined helper or collaborator aliases outside the Exact test contract: AuditLogger." in agent.last_user_message
    assert "Do not preserve or patch the previous pytest file in place. Rebuild the suite from the Exact test contract and current implementation, and do not replace those guessed helpers with near-match record or dataclass imports." in agent.last_user_message
    assert "service = ComplianceIntakeService(AuditLogger())" not in agent.last_user_message
    assert "The previous file referenced undefined helper or collaborator aliases such as `AuditLogger`." in agent.last_user_message
    assert "Do not repair those names by swapping to a similarly named record or dataclass like `AuditLog()`" in agent.last_user_message
    assert "Record-shaped value models such as AuditLog, RiskScore, ResultRecord, or similar typed data holders are not service collaborators unless the exact contract explicitly says so." in agent.last_system_prompt


def test_qa_tester_keeps_real_module_symbol_suite_and_focuses_missing_imports(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass\n"
                "from datetime import datetime\n\n"
                "@dataclass\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: datetime\n\n"
                "@dataclass\n"
                "class AuditLog:\n"
                "    request_id: str\n"
                "    action: str\n"
                "    details: dict\n"
                "    timestamp: datetime\n\n"
                "@dataclass\n"
                "class RiskScore:\n"
                "    request_id: str\n"
                "    jurisdiction: str\n"
                "    customer_type: str\n"
                "    adverse_indicators: bool\n"
                "    missing_document_severity: str\n"
                "    score: float\n\n"
                "class RiskScorer:\n"
                "    def score_request(self, request: ComplianceRequest) -> RiskScore:\n"
                "        return RiskScore(request.request_id, '', '', False, '', 1.0)\n\n"
                "class AuditLogger:\n"
                "    def log_action(self, audit_log: AuditLog) -> None:\n"
                "        pass\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self, risk_scorer: RiskScorer, audit_logger: AuditLogger):\n"
                "        self.risk_scorer = risk_scorer\n"
                "        self.audit_logger = audit_logger\n\n"
                "    def handle_request(self, request: ComplianceRequest) -> None:\n"
                "        pass\n\n"
                "    def validate_request(self, request: ComplianceRequest) -> bool:\n"
                "        return True\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": (
                "Functions:\n- none\n"
                "Classes:\n"
                "- ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- AuditLog(request_id, action, details, timestamp)\n"
                "- RiskScore(request_id, jurisdiction, customer_type, adverse_indicators, missing_document_severity, score)\n"
                "- RiskScorer()\n"
                "- AuditLogger()\n"
                "- ComplianceIntakeService(risk_scorer, audit_logger)"
            ),
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: AuditLogger, AuditLog, ComplianceIntakeService, ComplianceRequest, RiskScore, RiskScorer\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request), ComplianceIntakeService.validate_request(request)\n"
                "- Exact constructor fields: ComplianceIntakeService(risk_scorer, audit_logger), ComplianceRequest(request_id, request_type, details, timestamp), AuditLog(request_id, action, details, timestamp), RiskScore(request_id, jurisdiction, customer_type, adverse_indicators, missing_document_severity, score)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts a ComplianceRequest instance",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from service_module import AuditLog, ComplianceIntakeService, ComplianceRequest, RiskScore, RiskScorer\n\n"
                "def test_happy_path():\n"
                "    risk_scorer = RiskScorer()\n"
                "    audit_logger = AuditLogger()\n"
                "    service = ComplianceIntakeService(risk_scorer, audit_logger)\n"
                "    request = ComplianceRequest(request_id='1', request_type='screening', details={'source': 'web'}, timestamp=datetime.now())\n"
                "    service.handle_request(request)\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Syntax OK: yes\n"
                "- Imported module symbols: AuditLog, ComplianceIntakeService, ComplianceRequest, RiskScore, RiskScorer\n"
                "- Undefined local names: AuditLogger (line 6), datetime (line 7)\n"
                "- Pytest execution: FAIL\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "audit_logger = AuditLogger()" in agent.last_user_message
    assert "The previous file referenced real production symbols that exist in the module but were never imported, such as `AuditLogger`." in agent.last_user_message
    assert "Add each one to the import list at the top of the file before use instead of deleting, renaming, or leaving it as an undefined local." in agent.last_user_message
    assert "The previous file referenced undefined helper or collaborator aliases such as `AuditLogger`." not in agent.last_user_message
    assert "from datetime import datetime" in agent.last_user_message
    assert "from service_module import ComplianceIntakeService, ComplianceRequest, AuditLogger, AuditLog, RiskScore, RiskScorer" in agent.last_user_message
    assert "Before finalizing, verify that every non-local name used anywhere in the suite is either imported from the target module" in agent.last_system_prompt


def test_qa_tester_contract_first_repair_focuses_pytest_import_and_shared_state(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass, field\n"
                "from datetime import datetime\n\n"
                "@dataclass(frozen=True)\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: float = 1.0\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self):\n"
                "        self.audit_log = []\n\n"
                "    def validate_request(self, request):\n"
                "        return bool(request.request_id) and bool(request.details)\n\n"
                "    def handle_request(self, request):\n"
                "        if not self.validate_request(request):\n"
                "            raise ValueError('Invalid request')\n"
                "        self.audit_log.append({'request_id': request.request_id})\n\n"
                "    def batch_process(self, requests):\n"
                "        for request in requests:\n"
                "            self.handle_request(request)\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request), ComplianceIntakeService.validate_request(request), ComplianceIntakeService.batch_process(requests)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts a ComplianceRequest instance",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "existing_tests": (
                "from service_module import ComplianceIntakeService, ComplianceRequest\n\n"
                "service = ComplianceIntakeService()\n"
                "request = ComplianceRequest(request_id=\"request_id-1\", request_type=\"screening\", details={\"source\": \"web\"}, timestamp=1.0)\n\n"
                "def test_handle_request_valid_request():\n"
                "    service.handle_request(request)\n\n"
                "def test_handle_request_invalid_request():\n"
                "    with pytest.raises(ValueError):\n"
                "        service.handle_request(ComplianceRequest(request_id=\"\", request_type=\"screening\", details={\"source\": \"web\"}, timestamp=1.0))\n\n"
                "def test_batch_process():\n"
                "    service.batch_process([request])\n"
                "    assert len(service.audit_log) == 2\n"
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Undefined local names: pytest (line 8)\n"
                "- Pytest execution: FAIL\n"
                "- Pytest failure details: FAILED tests_tests.py::test_handle_request_invalid_request - NameError: name 'pytest' is not defined; FAILED tests_tests.py::test_batch_process - AssertionError: assert 3 == 2 | len(service.audit_log) mismatch\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Repair focus:" in agent.last_user_message
    assert "The previous file used `pytest.` without importing `pytest`. Add `import pytest` at the top if the rewritten suite keeps any `pytest.` references." in agent.last_user_message
    assert "The previous runtime failure came from a fragile exact audit-length check. Recreate fresh service/request objects inside each test and replace exact batch audit totals with stable delta, monotonic growth, or identity checks unless the contract explicitly enumerates every emitted entry." in agent.last_user_message


def test_qa_tester_contract_first_repair_focuses_datetime_import_and_timeout_minimization(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass, field\n"
                "from datetime import datetime\n"
                "from threading import Lock\n\n"
                "@dataclass(frozen=True)\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: str\n"
                "    timestamp: datetime\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self):\n"
                "        self._lock = Lock()\n"
                "        self._seen = set()\n\n"
                "    def validate_request(self, request):\n"
                "        return isinstance(request.request_id, str) and isinstance(request.details, str)\n\n"
                "    def handle_request(self, request):\n"
                "        with self._lock:\n"
                "            if request.request_id in self._seen:\n"
                "                return 'duplicate'\n"
                "            self._seen.add(request.request_id)\n"
                "        return 'accepted'\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request), ComplianceIntakeService.validate_request(request)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts a ComplianceRequest instance",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Undefined local names: datetime (line 6), datetime (line 12)\n"
                "- Pytest execution: FAIL\n"
                "- Pytest summary: pytest timed out after 60 seconds\n"
                "- Verdict: FAIL"
            ),
        },
    )

    assert result == "ok"
    assert "Repair focus:" in agent.last_user_message
    assert "The previous file referenced `datetime` without importing it. If any rewritten test keeps `datetime.now()` or another bare `datetime` reference, add a matching import such as `from datetime import datetime` or `import datetime` at the top before finalizing." in agent.last_user_message
    assert "Otherwise remove every bare `datetime` reference and switch those timestamp values to a self-contained literal or previously defined local" in agent.last_user_message
    assert "The previous suite hung at runtime. Rewrite to the minimal contract-required trio only: happy path, validation failure, and batch processing. Remove duplicate-detection, risk-tier, audit-only, and other speculative extras unless the exact contract or behavior contract explicitly requires them." in agent.last_user_message
    assert "When the suite already contains a dedicated validation-failure test, do not reuse that invalid payload inside test_batch_processing or any other supposedly valid batch scenario." in agent.last_user_message


def test_qa_tester_contract_first_repair_focuses_line_budget_trimming(tmp_path):
    agent = CaptureQATesterAgent(build_config(tmp_path))

    result = agent.run(
        "Repair tests",
        {
            "code": (
                "from dataclasses import dataclass\n"
                "\n"
                "@dataclass(frozen=True)\n"
                "class ComplianceRequest:\n"
                "    request_id: str\n"
                "    request_type: str\n"
                "    details: dict\n"
                "    timestamp: float\n\n"
                "class ComplianceIntakeService:\n"
                "    def __init__(self):\n"
                "        self.audit_log = []\n\n"
                "    def validate_request(self, request):\n"
                "        return bool(request.request_id) and bool(request.details)\n\n"
                "    def handle_request(self, request):\n"
                "        if not self.validate_request(request):\n"
                "            raise ValueError('Invalid request')\n"
                "        self.audit_log.append({'request_id': request.request_id})\n"
                "        return {'request_id': request.request_id}\n"
            ),
            "module_name": "service_module",
            "module_filename": "service_module.py",
            "code_summary": "Compliance intake workflow",
            "code_outline": "class ComplianceIntakeService:\n    def handle_request(self, request): ...",
            "code_public_api": "Functions:\n- none\nClasses:\n- ComplianceRequest(request_id, request_type, details, timestamp)\n- ComplianceIntakeService()",
            "code_exact_test_contract": (
                "Exact test contract:\n"
                "- Allowed production imports: ComplianceIntakeService, ComplianceRequest\n"
                "- Preferred service or workflow facades: ComplianceIntakeService\n"
                "- Exact public callables: none\n"
                "- Exact public class methods: ComplianceIntakeService.handle_request(request), ComplianceIntakeService.validate_request(request)\n"
                "- Exact constructor fields: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Treat every listed import, method, and constructor field as exact. Do not replace any of them with a guessed alias, shortened variant, or placeholder name."
            ),
            "code_test_targets": "Test targets:\n- Functions to test: none\n- Classes to test: ComplianceIntakeService\n- Entry points to avoid in tests: none",
            "code_behavior_contract": "Behavior contract:\n- handle_request accepts a ComplianceRequest instance",
            "task_public_contract_anchor": (
                "- Public facade: ComplianceIntakeService\n"
                "- Primary request model: ComplianceRequest(request_id, request_type, details, timestamp)\n"
                "- Required request workflow: ComplianceIntakeService.handle_request(request)\n"
                "- Supporting validation surface: ComplianceIntakeService.validate_request(request)\n"
                "- Batch behavior stays on the same facade and should be expressed through repeated handle_request(request) calls rather than renamed public batch aliases."
            ),
            "repair_validation_summary": (
                "Generated test validation:\n"
                "- Line count: 160/150\n"
                "- Top-level test functions: 6/7 max\n"
                "- Fixture count: 0/3\n"
                "- Pytest execution: PASS\n"
                "- Pytest summary: 6 passed in 0.02s\n"
                "- Verdict: FAIL\n"
                "Generated test validation failed: line count 160 exceeds maximum 150"
            ),
        },
    )

    assert result == "ok"
    assert "Repair focus:" in agent.last_user_message
    assert "The previous file failed because it exceeded the hard line budget." in agent.last_user_message
    assert "delete any fourth-or-later top-level test" in agent.last_user_message
    assert "remove per-test docstrings, comments, and extra blank lines" in agent.last_user_message
    assert "drop validator-only, audit-only, risk-tier, or other helper-only coverage" in agent.last_user_message


@pytest.mark.parametrize(
    ("agent_class", "context", "expected_type", "expected_name"),
    [
        (CaptureArchitectAgent, {}, ArtifactType.DOCUMENT, "arch_architecture"),
        (CaptureCodeEngineerAgent, {"architecture": "Layered design"}, ArtifactType.CODE, "code_implementation"),
        (CaptureCodeReviewerAgent, {"code": "print('hello')"}, ArtifactType.DOCUMENT, "review_review"),
        (CaptureDependencyManagerAgent, {"code": "print('hello')"}, ArtifactType.CONFIG, "deps_requirements"),
        (CaptureQATesterAgent, {"code": "def add(a, b): return a + b"}, ArtifactType.TEST, "test_tests"),
        (CaptureDocsWriterAgent, {}, ArtifactType.DOCUMENT, "docs_documentation"),
        (CaptureLegalAdvisorAgent, {}, ArtifactType.DOCUMENT, "legal_legal_analysis"),
    ],
)
def test_execute_adds_role_specific_default_artifact(tmp_path, agent_class, context, expected_type, expected_name):
    agent = agent_class(build_config(tmp_path))
    agent_input = AgentInput(
        task_id=expected_name.split("_", 1)[0],
        task_title="Task",
        task_description="Perform task",
        project_name="Demo",
        project_goal="Build demo",
        context=context,
    )

    result = agent.execute(agent_input)

    assert result.raw_content == "ok"
    assert result.metadata["project_name"] == "Demo"
    assert len(result.artifacts) == 1
    assert result.artifacts[0].artifact_type == expected_type
    assert result.artifacts[0].name == expected_name