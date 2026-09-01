import importlib.util
import sys
import threading
from pathlib import Path
from urllib import request


def _load_script_module(module_name: str, relative_path: str):
    project_root = Path(__file__).resolve().parents[1]
    module_path = project_root / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(project_root))
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _fake_view() -> dict[str, object]:
    return {
        "source": {
            "state_file": "/srv/customer-secret-root/internal-observability/project_state.sqlite",
            "state_store_kind": "sqlite",
            "schema_version": 3,
        },
        "workflow_overview": {
            "project_name": "InternalObservabilityDemo",
            "goal": "Demonstrate a static HTML internal observability report.",
            "workflow_status": "failed",
            "phase": "review",
            "acceptance_policy": "strict",
            "terminal_outcome": "failed",
            "failure_category": "test_validation",
            "acceptance_criteria_met": False,
            "acceptance_evaluation": {},
            "updated_at": "2026-05-19T14:00:00+00:00",
            "task_count": 2,
            "task_status_counts": {"done": 1, "failed": 1},
            "tasks_with_provider_calls": 2,
            "tasks_without_provider_calls": 0,
            "final_providers": ["anthropic", "openai"],
            "observed_providers": ["anthropic", "openai"],
            "attempt_count": 2,
            "retry_attempt_count": 1,
            "duration_ms": {"count": 2, "total": 52.5, "min": 12.5, "max": 40, "avg": 26.25},
            "usage": {"completion_tokens": 2, "prompt_tokens": 8},
        },
        "task_timeline": [
            {
                "task_id": "code",
                "title": "Implementation",
                "description": "Implement the application",
                "dependencies": [],
                "repair_origin_task_id": None,
                "assigned_to": "code_engineer",
                "status": "done",
                "has_output": True,
                "has_failure": False,
                "started_at": "2026-03-22T10:00:00+00:00",
                "last_attempt_started_at": "2026-03-22T10:01:00+00:00",
                "completed_at": "2026-03-22T10:03:00+00:00",
                "provider": "openai",
                "model": "gpt-4.1",
                "success": True,
                "attempts_used": 2,
                "retry_attempt_count": 1,
                "task_duration_ms": 180000,
                "last_attempt_duration_ms": 120000,
                "provider_duration_ms": 12.5,
                "provider_latency_ms": 9.5,
                "usage": {"completion_tokens": 2, "prompt_tokens": 5},
                "provider_health": {},
            },
            {
                "task_id": "review",
                "title": "Review",
                "description": "Review the changes",
                "dependencies": ["code"],
                "repair_origin_task_id": None,
                "assigned_to": "code_reviewer",
                "status": "failed",
                "has_output": False,
                "has_failure": True,
                "started_at": "2026-03-22T10:04:00+00:00",
                "last_attempt_started_at": "2026-03-22T10:05:00+00:00",
                "completed_at": "2026-03-22T10:07:00+00:00",
                "provider": "anthropic",
                "model": "claude-sonnet-4",
                "success": False,
                "attempts_used": 0,
                "retry_attempt_count": 0,
                "task_duration_ms": 180000,
                "last_attempt_duration_ms": 120000,
                "provider_duration_ms": 40,
                "provider_latency_ms": 30,
                "usage": {"prompt_tokens": 3},
                "provider_health": {},
            },
        ],
        "provider_panels": [
            {
                "provider": "anthropic",
                "task_count": 1,
                "success_count": 0,
                "failure_count": 1,
                "attempt_count": 0,
                "retry_attempt_count": 0,
                "models": ["claude-sonnet-4"],
                "duration_ms": {"count": 1, "total": 40, "min": 40, "max": 40, "avg": 40},
                "usage": {"prompt_tokens": 3},
                "status_counts": {},
                "last_outcome_counts": {},
                "retryable_failure_count": 0,
                "active_health_check_count": 0,
            },
            {
                "provider": "openai",
                "task_count": 1,
                "success_count": 1,
                "failure_count": 0,
                "attempt_count": 2,
                "retry_attempt_count": 1,
                "models": ["gpt-4.1"],
                "duration_ms": {"count": 1, "total": 12.5, "min": 12.5, "max": 12.5, "avg": 12.5},
                "usage": {"completion_tokens": 2, "prompt_tokens": 5},
                "status_counts": {"open_circuit": 1},
                "last_outcome_counts": {"failure": 1},
                "retryable_failure_count": 1,
                "active_health_check_count": 1,
            },
        ],
        "execution_panel": {
            "resume_summary": {
                "resume_event_count": 1,
                "reason_counts": {"manual resume": 1},
                "resumed_task_count": 2,
                "unique_task_count": 2,
                "last_resumed_at": "2026-03-22T10:08:00+00:00",
            },
            "repair_summary": {
                "cycle_count": 2,
                "max_cycles": 5,
                "budget_remaining": 3,
                "history_count": 2,
                "reason_counts": {"fix failing tests": 2},
                "failure_category_counts": {"test_validation": 2},
                "failed_task_count": 1,
            },
            "fallback_summary": {
                "task_count": 1,
                "entry_count": 1,
                "providers": ["anthropic"],
                "statuses": ["failed_health_check"],
            },
            "error_summary": {
                "final_error_count": 1,
                "fallback_error_count": 1,
            },
        },
        "evidence_panel": {
            "state_sha256": "a" * 64,
            "event_chain_head": "b" * 64,
            "event_count": 5,
            "verification_checks": {
                "state_digest": "passed",
                "event_chain": "passed",
                "integrity_sidecar": "skipped",
                "artifact_manifest": "skipped",
            },
            "verification_passed": True,
            "legal_hold": True,
            "snapshot_history_limit": 8,
            "run_identity": {
                "run_id": "run-123",
                "hostname": "control-plane-01",
                "os_user": "ops-user"
            },
        },
    }


def test_build_html_report_renders_adapter_backed_sections_without_private_paths():
    module = _load_script_module(
        "render_internal_observability_html_test",
        "scripts/render_internal_observability_html.py",
    )

    html_report = module.build_html_report(_fake_view())

    assert "Internal Observability Report" in html_report
    assert "InternalObservabilityDemo" in html_report
    assert "Workflow Overview" in html_report
    assert "Task Timeline" in html_report
    assert "Provider Panels" in html_report
    assert "Execution Diagnostics" in html_report
    assert "project_state.sqlite" in html_report
    assert "gpt-4.1" in html_report
    assert "claude-sonnet-4" in html_report
    assert "open_circuit" in html_report
    assert "report-search" in html_report
    assert "task-status-filter" in html_report
    assert "provider-filter" in html_report
    assert "task-sort" in html_report
    assert "provider-sort" in html_report
    assert "Evidence &amp; Integrity" in html_report
    assert 'id="evidence"' in html_report
    assert "state sha256" in html_report
    assert "event chain head" in html_report
    assert "legal hold" in html_report
    assert "verification passed" in html_report
    assert 'data-task-status="done"' in html_report
    assert 'data-provider="openai"' in html_report
    assert 'data-provider-name="openai"' in html_report
    assert 'data-task-duration-ms="' in html_report
    assert 'data-failure-count="' in html_report
    assert 'id="task-code"' in html_report
    assert 'href="#task-code"' in html_report
    assert 'id="provider-openai"' in html_report
    assert 'href="#provider-openai"' in html_report
    assert 'id="diagnostic-resume-events"' in html_report
    assert 'href="#diagnostic-resume-events"' in html_report
    assert 'data-search-text="' in html_report
    assert 'href="#tasks"' in html_report
    assert "applyFilters" in html_report
    assert "URLSearchParams" in html_report
    assert "history.replaceState" in html_report
    assert "kycortex-internal-observability-report-filters" in html_report
    assert "task_sort" in html_report
    assert "provider_sort" in html_report
    assert "reset-filters" in html_report
    assert "copy-filter-link" in html_report
    assert "print-report" in html_report
    assert "expand-visible-details" in html_report
    assert "collapse-visible-details" in html_report
    assert "share-link-feedback" in html_report
    assert "filter-summary" in html_report
    assert "tasks-visible-count" in html_report
    assert "providers-visible-count" in html_report
    assert "diagnostics-visible-count" in html_report
    assert "tasks-empty-state" in html_report
    assert "providers-empty-state" in html_report
    assert "diagnostics-empty-state" in html_report
    assert "match-highlight" in html_report
    assert "search-highlight-target" in html_report
    assert "applyHighlights" in html_report
    assert "updateFilterSummary" in html_report
    assert "resetFilters" in html_report
    assert "copyFilterLink" in html_report
    assert "setVisibleDrilldownsExpanded" in html_report
    assert "printCurrentReport" in html_report
    assert "sortTaskCards" in html_report
    assert "sortProviderCards" in html_report
    assert "card-link" in html_report
    assert "window.print" in html_report
    assert "drilldown.open = isExpanded" in html_report
    assert "navigator.clipboard" in html_report
    assert "@media print" in html_report
    assert ".task-card:target" in html_report
    assert "data-highlight-source=" in html_report
    assert "Task Drill-down" in html_report
    assert "Provider Drill-down" in html_report
    assert "Resume Detail" in html_report
    assert "Fallback Detail" in html_report
    assert "code_engineer" in html_report
    assert "Retryable Failures" in html_report
    assert "failed_health_check" in html_report
    assert "manual resume" in html_report
    assert "customer-secret-root" not in html_report


def test_main_writes_html_report_without_leaking_private_paths(tmp_path, capsys, monkeypatch):
    module = _load_script_module(
        "render_internal_observability_html_main_test",
        "scripts/render_internal_observability_html.py",
    )
    output_html = tmp_path / "customer-secret-root" / "reports" / "internal_observability_report.html"

    monkeypatch.setattr(module, "load_internal_observability_view", lambda state_file: _fake_view())

    exit_code = module.main(
        [
            "/srv/customer-secret-root/internal-observability/project_state.sqlite",
            "--output-html",
            str(output_html),
        ]
    )

    captured = capsys.readouterr().out.splitlines()
    rendered = output_html.read_text(encoding="utf-8")

    assert exit_code == 0
    assert output_html.is_file()
    assert "Wrote internal_observability_report.html from project_state.sqlite" in captured
    assert all("customer-secret-root" not in line for line in captured)
    assert "InternalObservabilityDemo" in rendered
    assert "report-search" in rendered
    assert "open_circuit" in rendered
    assert "manual resume" in rendered


def test_build_http_server_serves_adapter_backed_report_and_healthz(monkeypatch):
    module = _load_script_module(
        "render_internal_observability_html_server_test",
        "scripts/render_internal_observability_html.py",
    )

    monkeypatch.setattr(module, "load_internal_observability_view", lambda state_file: _fake_view())
    server = module.build_observability_http_server(
        "/srv/customer-secret-root/internal-observability/project_state.sqlite",
        host="127.0.0.1",
        port=0,
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    try:
        base_url = f"http://127.0.0.1:{server.server_port}"

        with request.urlopen(f"{base_url}/?status=failed&provider=anthropic") as response:
            html_report = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
            assert response.headers["Cache-Control"] == "no-store"
            assert "InternalObservabilityDemo" in html_report
            assert "task-sort" in html_report
            assert "customer-secret-root" not in html_report

        with request.urlopen(f"{base_url}/healthz") as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/plain")
            assert body == "ok\n"
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()


def test_build_html_report_embeds_provenance_footer():
    module = _load_script_module(
        "render_internal_observability_html_provenance_test",
        "scripts/render_internal_observability_html.py",
    )

    html_report = module.build_html_report(
        _fake_view(),
        provenance={
            "generated_at": "2026-08-01T12:00:00+00:00",
            "tool_version": "1.0.13b2",
            "state_sha256": "a" * 64,
        },
    )

    assert 'id="provenance"' in html_report
    assert "generated at (UTC): 2026-08-01T12:00:00+00:00" in html_report
    assert "tool: kycortex-agents 1.0.13b2" in html_report
    assert f"source state sha256: {'a' * 64}" in html_report
    assert "schema version: 3" in html_report
    assert "Sensitivity: INTERNAL" in html_report
    assert "redacted at recording time" in html_report
    assert "not, by itself, a certified compliance or audit record" in html_report
    assert "shareable via URL" not in html_report
    assert "Treat this report as internal data." in html_report
    assert "customer-secret-root" not in html_report


def test_build_report_provenance_hashes_persisted_state(tmp_path):
    module = _load_script_module(
        "render_internal_observability_html_provenance_hash_test",
        "scripts/render_internal_observability_html.py",
    )
    from kycortex_agents.memory.project_state import ProjectState, compute_state_digest
    from kycortex_agents.memory.state_store import resolve_state_store

    state_path = tmp_path / "project_state.json"
    ProjectState(project_name="Demo", goal="Provenance", state_file=str(state_path)).save()

    provenance = module.build_report_provenance(str(state_path))

    payload = resolve_state_store(str(state_path)).load(str(state_path))
    assert provenance["state_sha256"] == compute_state_digest(payload)
    assert provenance["tool_version"]
    assert provenance["generated_at"].endswith("+00:00")


def test_build_report_provenance_degrades_when_state_missing(tmp_path):
    module = _load_script_module(
        "render_internal_observability_html_provenance_missing_test",
        "scripts/render_internal_observability_html.py",
    )

    provenance = module.build_report_provenance(str(tmp_path / "missing.json"))

    assert provenance["state_sha256"] == "unavailable"