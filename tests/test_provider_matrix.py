import importlib.util
import json
import sys
from pathlib import Path
from urllib.error import URLError

from kycortex_agents.memory.project_state import ProjectState, Task


def _load_example_module(module_name: str, relative_path: str):
    project_root = Path(__file__).resolve().parents[1]
    examples_dir = project_root / "examples"
    module_path = project_root / relative_path
    sys.path.insert(0, str(examples_dir))
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_full_provider_workflow_build_config_accepts_resume_controls(tmp_path):
    module = _load_example_module(
        "example_full_provider_workflow_test",
        "examples/example_full_provider_workflow.py",
    )

    config = module.build_config(
        "ollama",
        "llama3",
        str(tmp_path / "output"),
        workflow_failure_policy="continue",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=2,
    )

    assert config.workflow_failure_policy == "continue"
    assert config.workflow_resume_policy == "resume_failed"
    assert config.workflow_max_repair_cycles == 2


def test_provider_matrix_summary_reports_repair_lineage(tmp_path):
    from kycortex_agents.provider_matrix import summarize_workflow_run

    project = ProjectState(
        project_name="Demo",
        goal="Validate provider summary output",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.phase = "completed"
    project.terminal_outcome = "completed"
    project.acceptance_criteria_met = True
    project.repair_cycle_count = 1
    project.repair_max_cycles = 1
    project.repair_history = [{"cycle": 1, "failed_task_ids": ["tests"]}]
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Run tests",
            assigned_to="qa_tester",
            status="done",
            attempts=2,
        )
    )
    project.add_task(
        Task(
            id="tests__repair_1",
            title="Tests Repair",
            description="Repair tests",
            assigned_to="qa_tester",
            status="done",
            attempts=1,
            repair_origin_task_id="tests",
            repair_attempt=1,
        )
    )

    summary = summarize_workflow_run(
        project,
        provider="ollama",
        model="llama3",
        output_dir=str(tmp_path / "output"),
    )

    assert summary["terminal_outcome"] == "completed"
    assert summary["repair_cycle_count"] == 1
    assert summary["repair_task_ids"] == ["tests__repair_1"]
    assert summary["task_status_counts"] == {"done": 2}


def test_provider_matrix_summary_reports_failed_non_repair_tasks(tmp_path):
    from kycortex_agents.provider_matrix import summarize_workflow_run

    project = ProjectState(
        project_name="Demo",
        goal="Validate provider summary output",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.phase = "failed"
    project.terminal_outcome = "failed"
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description="Run tests",
            assigned_to="qa_tester",
            status="failed",
        )
    )
    project.add_task(
        Task(
            id="tests__repair_1",
            title="Tests Repair",
            description="Repair tests",
            assigned_to="qa_tester",
            status="failed",
            repair_origin_task_id="tests",
            repair_attempt=1,
        )
    )

    summary = summarize_workflow_run(
        project,
        provider="openai",
        model="gpt-4o-mini",
        output_dir=str(tmp_path / "output"),
    )

    assert summary["failed_task_ids"] == ["tests"]


def test_provider_matrix_resolve_model_handles_override_and_ollama_probe(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    assert resolve_model("openai", None) == "gpt-4o-mini"
    assert resolve_model("ollama", "custom-model") == "custom-model"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "llama3.2:latest"}]}).encode("utf-8")

    monkeypatch.setattr("kycortex_agents.provider_matrix.urlopen", lambda *args, **kwargs: Response())

    assert resolve_model("ollama", None) == "llama3.2:latest"


def test_provider_matrix_resolve_model_prefers_default_when_installed(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "llama3"}, {"name": "llama3.2:latest"}]}).encode("utf-8")

    monkeypatch.setattr("kycortex_agents.provider_matrix.urlopen", lambda *args, **kwargs: Response())

    assert resolve_model("ollama", None) == "llama3"


def test_provider_matrix_resolve_model_falls_back_when_probe_returns_no_models(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"models": []}).encode("utf-8")

    monkeypatch.setattr("kycortex_agents.provider_matrix.urlopen", lambda *args, **kwargs: Response())

    assert resolve_model("ollama", None) == "llama3"


def test_provider_matrix_resolve_model_falls_back_to_default_when_ollama_probe_fails(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    monkeypatch.setattr(
        "kycortex_agents.provider_matrix.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
    )

    assert resolve_model("ollama", None) == "llama3"


def test_provider_matrix_resolve_model_falls_back_to_default_when_ollama_probe_raises_oserror(monkeypatch):
    from kycortex_agents.provider_matrix import resolve_model

    monkeypatch.setattr(
        "kycortex_agents.provider_matrix.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionRefusedError("offline")),
    )

    assert resolve_model("ollama", None) == "llama3"


def test_provider_matrix_availability_uses_env_vars_and_ollama_probe(monkeypatch):
    from kycortex_agents.provider_matrix import get_provider_availability

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    assert get_provider_availability("openai")["available"] is False
    assert get_provider_availability("anthropic")["available"] is False
    assert get_provider_availability("ollama", urlopen_fn=lambda *args, **kwargs: Response())["available"] is True


def test_provider_matrix_availability_respects_explicit_empty_environ():
    from kycortex_agents.provider_matrix import get_provider_availability

    availability = get_provider_availability("openai", environ={})

    assert availability == {
        "provider": "openai",
        "available": False,
        "reason": "missing OPENAI_API_KEY",
    }


def test_provider_matrix_availability_reports_unknown_provider_and_ollama_failure():
    from kycortex_agents.provider_matrix import get_provider_availability

    try:
        get_provider_availability("custom")
    except ValueError as exc:
        assert "Unsupported provider: custom" in str(exc)
    else:  # pragma: no cover - safety assertion
        raise AssertionError("Expected unsupported provider to raise ValueError")

    availability = get_provider_availability(
        "ollama",
        urlopen_fn=lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    assert availability == {
        "provider": "ollama",
        "available": False,
        "reason": "ollama tags endpoint unreachable",
    }


def test_build_full_workflow_project_contains_expected_dependency_graph(tmp_path):
    from kycortex_agents.provider_matrix import build_full_workflow_project

    project = build_full_workflow_project(str(tmp_path / "output"), "ollama")

    assert [task.id for task in project.tasks] == ["arch", "code", "deps", "tests", "review", "docs", "legal"]
    assert project.get_task("code").dependencies == ["arch"]
    assert project.get_task("tests").dependencies == ["code", "deps"]
    assert project.get_task("legal").dependencies == ["docs"]


def test_write_summary_json_persists_sorted_payload(tmp_path):
    from kycortex_agents.provider_matrix import write_summary_json

    path = tmp_path / "summary" / "provider_summary.json"
    write_summary_json({"b": 2, "a": 1}, str(path))

    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "b": 2}


def test_provider_matrix_example_skips_unavailable_provider(tmp_path, monkeypatch):
    module = _load_example_module(
        "example_provider_matrix_validation_test",
        "examples/example_provider_matrix_validation.py",
    )

    monkeypatch.setattr(
        module,
        "get_provider_availability",
        lambda provider: {"provider": provider, "available": False, "reason": "missing credentials"},
    )

    result = module.run_provider(
        "openai",
        output_root=str(tmp_path / "matrix"),
        failure_policy="continue",
        resume_policy="resume_failed",
        max_repair_cycles=1,
    )

    assert result == {
        "provider": "openai",
        "available": False,
        "availability_reason": "missing credentials",
        "status": "skipped",
    }


def test_provider_matrix_parser_defaults_to_all_supported_providers():
    module = _load_example_module(
        "example_provider_matrix_validation_parser_test",
        "examples/example_provider_matrix_validation.py",
    )

    args = module.build_parser().parse_args([])

    assert args.providers == []
    assert module.resolve_requested_providers(args.providers) == ["anthropic", "ollama", "openai"]


def test_provider_matrix_parser_rejects_unsupported_provider():
    module = _load_example_module(
        "example_provider_matrix_validation_parser_invalid_provider_test",
        "examples/example_provider_matrix_validation.py",
    )

    try:
        module.resolve_requested_providers(["invalid-provider"])
    except SystemExit as exc:
        assert str(exc) == (
            "Unsupported providers: invalid-provider. Supported providers: anthropic, ollama, openai."
        )
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected unsupported provider to raise SystemExit")


def test_execute_empirical_validation_workflow_consumes_bounded_repair_cycle(monkeypatch, tmp_path):
    import kycortex_agents.provider_matrix as provider_matrix

    config = provider_matrix.build_full_workflow_config(
        "ollama",
        "llama3",
        str(tmp_path / "output"),
        workflow_failure_policy="continue",
        workflow_resume_policy="resume_failed",
        workflow_max_repair_cycles=1,
    )
    project = ProjectState(
        project_name="Demo",
        goal="Exercise empirical repair loop",
        state_file=str(tmp_path / "project_state.json"),
    )
    project.repair_max_cycles = 1
    project.add_task(Task(id="arch", title="Architecture", description="Design", assigned_to="architect"))

    class FakeOrchestrator:
        def __init__(self, _config):
            self.config = _config

        def execute_workflow(self, state):
            arch = state.get_task("arch")
            if state.repair_cycle_count == 0:
                arch.status = "failed"
                state.phase = "failed"
                return
            arch.status = "done"
            state.phase = "completed"

    original_can_start_repair_cycle = project.can_start_repair_cycle

    def fake_can_start_repair_cycle():
        if project.repair_cycle_count == 0 and project.get_task("arch").status == "failed":
            return True
        return original_can_start_repair_cycle()

    monkeypatch.setattr(project, "can_start_repair_cycle", fake_can_start_repair_cycle)

    original_execute_workflow = FakeOrchestrator.execute_workflow

    def wrapped_execute_workflow(self, state):
        if state.repair_cycle_count == 0 and state.get_task("arch").status == "failed":
            state.start_repair_cycle(reason="retry failed arch", failed_task_ids=["arch"])
        original_execute_workflow(self, state)
        if state.repair_cycle_count == 1 and state.get_task("arch").status == "done":
            repair_task = state.get_task("arch__repair_1")
            if repair_task is None:
                state.add_task(
                    Task(
                        id="arch__repair_1",
                        title="Architecture Repair",
                        description="Repair architecture",
                        assigned_to="architect",
                        repair_origin_task_id="arch",
                        repair_attempt=1,
                        status="done",
                    )
                )

    FakeOrchestrator.execute_workflow = wrapped_execute_workflow

    monkeypatch.setattr(provider_matrix, "Orchestrator", FakeOrchestrator)

    provider_matrix.execute_empirical_validation_workflow(config, project)

    assert project.get_task("arch").status == "done"
    assert project.repair_cycle_count == 1
    assert project.get_task("arch__repair_1").repair_origin_task_id == "arch"


def test_execute_empirical_validation_workflow_raises_last_error_when_resume_is_disabled(monkeypatch, tmp_path):
    import kycortex_agents.provider_matrix as provider_matrix

    config = provider_matrix.build_full_workflow_config(
        "ollama",
        "llama3",
        str(tmp_path / "output"),
        workflow_failure_policy="fail_fast",
        workflow_resume_policy="interrupted_only",
        workflow_max_repair_cycles=0,
    )
    project = ProjectState(
        project_name="Demo",
        goal="Exercise non-resumable failure path",
        state_file=str(tmp_path / "project_state.json"),
    )

    class AlwaysFailingOrchestrator:
        def __init__(self, _config):
            self.config = _config

        def execute_workflow(self, state):
            state.phase = "failed"
            raise RuntimeError("provider boom")

    monkeypatch.setattr(provider_matrix, "Orchestrator", AlwaysFailingOrchestrator)

    try:
        provider_matrix.execute_empirical_validation_workflow(config, project)
    except RuntimeError as exc:
        assert str(exc) == "provider boom"
    else:  # pragma: no cover - safety assertion
        raise AssertionError("Expected runtime error to propagate when resume is disabled")