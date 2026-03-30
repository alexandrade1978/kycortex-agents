"""Internal helpers for empirical provider validation and workflow summaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task
from kycortex_agents.config import DEFAULT_PROVIDER_BASE_URLS

DEFAULT_PROVIDER_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "ollama": "qwen2.5-coder:7b",
}

PROVIDER_CREDENTIAL_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _provider_budget_summary(provider_call: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(provider_call, Mapping):
        return None
    return {
        "total_calls": provider_call.get("provider_call_count"),
        "calls_by_provider": dict(provider_call.get("provider_call_counts_by_provider") or {}),
        "max_calls_per_agent": provider_call.get("provider_max_calls_per_agent"),
        "max_calls_by_provider": dict(provider_call.get("provider_max_calls_per_provider") or {}),
        "remaining_calls": provider_call.get("provider_remaining_calls"),
        "remaining_calls_by_provider": dict(provider_call.get("provider_remaining_calls_by_provider") or {}),
    }


def _ollama_base_url(base_url_override: str | None) -> str:
    base_url = base_url_override or DEFAULT_PROVIDER_BASE_URLS["ollama"]
    return base_url.rstrip("/")


def resolve_model(
    provider: str,
    model_override: str | None,
    *,
    ollama_base_url: str | None = None,
    urlopen_fn: Callable[..., Any] | None = None,
) -> str:
    """Resolve the concrete model to use for a provider validation run."""

    provider = provider.strip().lower()
    if model_override is not None or provider != "ollama":
        return model_override or DEFAULT_PROVIDER_MODELS[provider]

    default_model = DEFAULT_PROVIDER_MODELS[provider]
    urlopen_impl = urlopen if urlopen_fn is None else urlopen_fn
    request = Request(f"{_ollama_base_url(ollama_base_url)}/api/tags", method="GET")
    try:
        with urlopen_impl(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return default_model

    installed_models = [item.get("name", "") for item in payload.get("models", []) if item.get("name")]
    if default_model in installed_models:
        return default_model
    if installed_models:
        return installed_models[0]
    return default_model


def get_provider_availability(
    provider: str,
    *,
    environ: Mapping[str, str] | None = None,
    urlopen_fn: Callable[..., Any] | None = None,
    ollama_base_url: str | None = None,
) -> dict[str, Any]:
    """Return whether the provider is runnable in the current environment."""

    provider = provider.strip().lower()
    if provider not in DEFAULT_PROVIDER_MODELS:
        raise ValueError(f"Unsupported provider: {provider}")

    resolved_environ = environ if environ is not None else os.environ
    if provider in PROVIDER_CREDENTIAL_ENV_VARS:
        env_var = PROVIDER_CREDENTIAL_ENV_VARS[provider]
        available = bool(resolved_environ.get(env_var))
        return {
            "provider": provider,
            "available": available,
            "reason": None if available else f"missing {env_var}",
        }

    urlopen_impl = urlopen if urlopen_fn is None else urlopen_fn
    request = Request(f"{_ollama_base_url(ollama_base_url)}/api/tags", method="GET")
    try:
        with urlopen_impl(request, timeout=5) as response:
            available = getattr(response, "status", 200) == 200
    except (HTTPError, URLError, TimeoutError, OSError):
        available = False

    return {
        "provider": provider,
        "available": available,
        "reason": None if available else "ollama tags endpoint unreachable",
    }


def build_full_workflow_config(
    provider: str,
    model: str,
    output_dir: str,
    *,
    ollama_base_url: str | None = None,
    ollama_num_ctx: int | None = 16384,
    workflow_failure_policy: str = "continue",
    workflow_resume_policy: str = "resume_failed",
    workflow_max_repair_cycles: int = 1,
) -> KYCortexConfig:
    """Build the empirical full-workflow config used by provider-validation examples."""

    config = KYCortexConfig(
        llm_provider=provider,
        llm_model=model,
        base_url=_ollama_base_url(ollama_base_url) if provider == "ollama" else None,
        ollama_num_ctx=ollama_num_ctx if provider == "ollama" else None,
        temperature=0.0,
        max_tokens=3200,
        timeout_seconds=180.0,
        workflow_failure_policy=workflow_failure_policy,
        workflow_resume_policy=workflow_resume_policy,
        workflow_max_repair_cycles=workflow_max_repair_cycles,
        project_name=f"full-provider-workflow-{provider}",
        output_dir=output_dir,
    )
    config.validate_runtime()
    return config


def build_full_workflow_project(output_dir: str, provider: str) -> ProjectState:
    """Build the canonical empirical full workflow used for provider comparison."""

    project = ProjectState(
        project_name=f"ComplianceIntake{provider.title()}",
        goal=(
            "Build a substantial single-module Python service for a compliance intake team. "
            "The module must use only the standard library and implement typed domain models, "
            "request validation, risk scoring, audit logging, batch processing, and a small CLI demo."
        ),
        state_file=str(Path(output_dir) / "project_state.json"),
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description=(
                "Design a concrete single-module architecture for a compliance intake service. "
                "Keep the design under 350 words and identify entities, workflows, audit boundaries, "
                "and operational risks."
            ),
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description=(
                "Write one Python module under 300 lines that implements only the planned compliance intake service. "
                "Use only the standard library. Include typed models, validation, risk scoring, batch processing, "
                "audit logging, and a CLI demo entrypoint. Prefer the smallest complete design that satisfies those requirements. "
                "Target roughly 240 to 280 lines when the requested behavior fits there so the hard 300-line cap keeps repair headroom. "
                "Implement only the minimal core flow rather than mirroring every optional architecture layer or future extension point. "
                "Avoid extra helper layers, exhaustive docstrings, and optional abstractions. Return raw Python only."
            ),
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )
    project.add_task(
        Task(
            id="deps",
            title="Dependencies",
            description=(
                "Infer the minimal runtime requirements.txt for the generated module. "
                "List only third-party runtime packages that are actually required."
            ),
            assigned_to="dependency_manager",
            dependencies=["code"],
        )
    )
    project.add_task(
        Task(
            id="tests",
            title="Tests",
            description=(
                "Write one compact raw pytest module under 150 lines for the generated compliance intake service. "
                "Use at most 3 fixtures and at most 7 top-level test functions. Include at least one happy path, one validation failure, and one batch-processing scenario. "
                "Prefer 3 to 5 top-level tests when those requested scenarios fit within that budget, and merge overlapping checks instead of adding helper-specific extras. "
                "Use the direct intake or validation surface for the validation-failure scenario and keep the batch-processing scenario fully valid unless the implementation contract explicitly requires partially invalid batch items. "
                "If the implementation exposes no dedicated batch helper, express the batch scenario as a short list of individually valid items processed one by one instead of passing a list into scalar-only validators or scorers. "
                "Do not import or test `main`, CLI/demo entrypoints, or other symbols explicitly listed as entry points to avoid in tests. "
                "Do not spend standalone tests on simple logging or audit helpers unless the public contract makes them independently observable. "
                "Do not add standalone caplog or raw logging-output assertions unless externally observable logging behavior is explicitly required. "
                "Never define a custom fixture named `request`; pytest reserves that name. Use inline setup or a specific fixture name instead. "
                "Do not use `.call_count`, `.assert_called_once()`, or similar mock-style assertions on logging objects or production callables unless the same test installs the exact mock or patch target first. "
                "If you need an exact numeric assertion, use trivially countable inputs rather than prose strings; otherwise prefer stable non-exact assertions. "
                "If an exact numeric assertion depends on string length, modulo, or counts, use repeated-character or similarly obvious inputs rather than natural-language sample text. "
                "Prefer direct assertions over exhaustive permutations or class-based test suites. Return raw Python only."
            ),
            assigned_to="qa_tester",
            dependencies=["code", "deps"],
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description=(
                "Review the generated implementation, dependency manifest, and tests for correctness, maintainability, "
                "and operational realism. Keep it actionable and concise."
            ),
            assigned_to="code_reviewer",
            dependencies=["tests"],
        )
    )
    project.add_task(
        Task(
            id="docs",
            title="Documentation",
            description=(
                "Write an engineer-facing README for the generated module, including setup, usage, dependency notes, "
                "design assumptions, and extension points."
            ),
            assigned_to="docs_writer",
            dependencies=["review"],
        )
    )
    project.add_task(
        Task(
            id="legal",
            title="Legal",
            description=(
                "Provide a concise legal and compliance note covering audit-data handling, privacy concerns, "
                "licensing assumptions, and distribution considerations for the generated compliance intake module."
            ),
            assigned_to="legal_advisor",
            dependencies=["docs"],
        )
    )
    return project


def summarize_workflow_run(
    project: ProjectState,
    *,
    provider: str,
    model: str,
    output_dir: str,
) -> dict[str, Any]:
    """Build a compact structured summary for a provider workflow run."""

    snapshot = project.snapshot()
    task_status_counts: dict[str, int] = {}
    task_summaries = []
    repair_task_ids = []
    failed_task_ids = []

    for task in project.tasks:
        task_status_counts[task.status] = task_status_counts.get(task.status, 0) + 1
        if task.repair_origin_task_id:
            repair_task_ids.append(task.id)
        if task.status == "failed" and not task.repair_origin_task_id:
            failed_task_ids.append(task.id)
        task_summaries.append(
            {
                "id": task.id,
                "status": task.status,
                "assigned_to": task.assigned_to,
                "attempts": task.attempts,
                "last_error": task.last_error,
                "last_error_type": task.last_error_type,
                "last_error_category": task.last_error_category,
                "provider_budget": _provider_budget_summary(task.last_provider_call),
                "repair_origin_task_id": task.repair_origin_task_id,
                "repair_attempt": task.repair_attempt,
            }
        )

    return {
        "provider": provider,
        "model": model,
        "project_name": project.project_name,
        "phase": project.phase,
        "terminal_outcome": project.terminal_outcome,
        "failure_category": project.failure_category,
        "acceptance_criteria_met": project.acceptance_criteria_met,
        "acceptance_policy": project.acceptance_policy,
        "repair_cycle_count": project.repair_cycle_count,
        "repair_max_cycles": project.repair_max_cycles,
        "repair_budget_remaining": max(project.repair_max_cycles - project.repair_cycle_count, 0),
        "repair_history": list(project.repair_history),
        "workflow_last_resumed_at": project.workflow_last_resumed_at,
        "workflow_finished_at": project.workflow_finished_at,
        "workflow_telemetry": snapshot.workflow_telemetry,
        "state_file": project.state_file,
        "output_dir": output_dir,
        "task_status_counts": task_status_counts,
        "failed_task_ids": sorted(failed_task_ids),
        "repair_task_ids": sorted(repair_task_ids),
        "task_summaries": task_summaries,
    }


def execute_empirical_validation_workflow(config: KYCortexConfig, project: ProjectState) -> None:
    """Execute a full workflow and consume any configured bounded repair cycles."""

    orchestrator = Orchestrator(config)
    last_error: Exception | None = None

    while True:
        try:
            orchestrator.execute_workflow(project)
        except Exception as exc:  # pragma: no cover - exercised via monkeypatched test doubles
            last_error = exc
        else:
            last_error = None

        should_resume = (
            config.workflow_resume_policy == "resume_failed"
            and project.can_start_repair_cycle()
            and any(task.status in {"failed", "skipped"} for task in project.tasks)
        )
        if not should_resume:
            break

    if last_error is not None:
        raise last_error


def write_summary_json(summary: dict[str, Any], path: str) -> None:
    """Persist a provider-validation summary as formatted JSON."""

    summary_path = Path(path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")