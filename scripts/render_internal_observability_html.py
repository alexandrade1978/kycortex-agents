from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from kycortex_agents.memory.internal_observability import InternalObservabilityView, load_internal_observability_view
from kycortex_agents.memory.project_state import compute_state_digest
from kycortex_agents.memory.state_store import resolve_state_store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a static internal observability HTML report from a persisted project state file.",
    )
    parser.add_argument("state_file", help="Path to the persisted project state file (.json/.sqlite/.db).")
    parser.add_argument(
        "--output-html",
        help="Optional output HTML path. Defaults to internal_observability_report.html next to the state file.",
    )
    parser.add_argument(
      "--serve",
      action="store_true",
      help="Serve the internal observability report over a local HTTP server instead of writing an HTML file.",
    )
    parser.add_argument(
      "--host",
      default="127.0.0.1",
      help="Host interface for --serve mode. Defaults to 127.0.0.1.",
    )
    parser.add_argument(
      "--port",
      type=int,
      default=8765,
      help="Port for --serve mode. Defaults to 8765. Use 0 to request an ephemeral port.",
    )
    return parser


def resolve_output_html_path(state_file: str, output_html: str | None) -> Path:
    if isinstance(output_html, str) and output_html.strip():
        return Path(output_html)
    return Path(state_file).resolve().with_name("internal_observability_report.html")


def _tool_version() -> str:
    try:
        return importlib_metadata.version("kycortex-agents")
    except importlib_metadata.PackageNotFoundError:
        return "unknown"


def build_report_provenance(state_file: str) -> dict[str, str]:
    """Return generation provenance for the report: timestamp, tool version, and source digest."""

    try:
        payload = resolve_state_store(state_file).load(state_file)
        state_sha256 = compute_state_digest(payload)
    except Exception:
        state_sha256 = "unavailable"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": _tool_version(),
        "state_sha256": state_sha256,
    }


def build_html_report(view: InternalObservabilityView, provenance: Mapping[str, str] | None = None) -> str:
    overview = view["workflow_overview"]
    if provenance is None:
        provenance = build_report_provenance(view["source"]["state_file"])
    workflow_status = _status_value(overview["workflow_status"])
    source_name = Path(view["source"]["state_file"]).name if view["source"]["state_file"] else "none"
    final_providers = _format_csv(overview["final_providers"])
    observed_providers = _format_csv(overview["observed_providers"])
    status_counts = _render_kv_chips(overview["task_status_counts"])
    jump_links = _render_jump_links(
        [
            ("overview", "Overview"),
            ("tasks", "Tasks"),
            ("providers", "Providers"),
            ("diagnostics", "Diagnostics"),
            ("provenance", "Provenance"),
        ]
    )
    task_status_filter_options = _render_select_options(sorted(overview["task_status_counts"]), "All statuses")
    provider_filter_options = _render_select_options(overview["observed_providers"], "All providers")
    task_sort_options = _render_named_select_options(
      [
        ("default", "Workflow order"),
        ("slowest-task", "Slowest task"),
        ("slowest-provider", "Slowest provider"),
        ("title", "Title A-Z"),
      ]
    )
    provider_sort_options = _render_named_select_options(
      [
        ("default", "Report order"),
        ("most-failures", "Most failures"),
        ("slowest-avg", "Slowest avg duration"),
        ("name", "Provider A-Z"),
      ]
    )
    provider_cards = "".join(_render_provider_panel(panel) for panel in view["provider_panels"])
    task_cards = "".join(_render_task_card(task) for task in view["task_timeline"])
    execution_panel = view["execution_panel"]
    diagnostic_cards = "".join(
      [
        _render_diagnostic_card(
          "Resume Events",
          execution_panel["resume_summary"]["resume_event_count"],
          "Resume Detail",
          [
            ("Reasons", _format_count_map(execution_panel["resume_summary"].get("reason_counts", {}))),
            ("Resumed Tasks", str(execution_panel["resume_summary"].get("resumed_task_count", 0))),
            ("Unique Tasks", str(execution_panel["resume_summary"].get("unique_task_count", 0))),
            ("Last Resumed", _none_label(execution_panel["resume_summary"].get("last_resumed_at"))),
          ],
        ),
        _render_diagnostic_card(
          "Repair Cycles",
          execution_panel["repair_summary"]["cycle_count"],
          "Repair Detail",
          [
            ("Max Cycles", str(execution_panel["repair_summary"].get("max_cycles", 0))),
            ("Budget Remaining", str(execution_panel["repair_summary"].get("budget_remaining", 0))),
            ("History Count", str(execution_panel["repair_summary"].get("history_count", 0))),
            (
              "Failure Categories",
              _format_count_map(execution_panel["repair_summary"].get("failure_category_counts", {})),
            ),
            ("Reasons", _format_count_map(execution_panel["repair_summary"].get("reason_counts", {}))),
          ],
        ),
        _render_diagnostic_card(
          "Fallback Entries",
          execution_panel["fallback_summary"]["entry_count"],
          "Fallback Detail",
          [
            ("Tasks", str(execution_panel["fallback_summary"].get("task_count", 0))),
            ("Providers", _format_csv(execution_panel["fallback_summary"].get("providers", []))),
            ("Statuses", _format_csv(execution_panel["fallback_summary"].get("statuses", []))),
          ],
        ),
        _render_diagnostic_card(
          "Final Errors",
          execution_panel["error_summary"]["final_error_count"],
          "Error Detail",
          [
            ("Final Errors", str(execution_panel["error_summary"].get("final_error_count", 0))),
            ("Fallback Errors", str(execution_panel["error_summary"].get("fallback_error_count", 0))),
          ],
        ),
      ]
    )

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Internal Observability Report</title>
  <style>
    :root {{
      --bg: #f2ede3;
      --bg-strong: #e0d3bf;
      --ink: #17313b;
      --muted: #5d6d72;
      --card: rgba(255, 252, 247, 0.88);
      --card-strong: #fffaf2;
      --line: rgba(23, 49, 59, 0.14);
      --accent: #b55d3d;
      --accent-soft: rgba(181, 93, 61, 0.12);
      --ok: #2f6f5f;
      --warn: #9a6a15;
      --fail: #9f3d2b;
      --shadow: 0 20px 45px rgba(34, 35, 30, 0.12);
      --radius: 22px;
      --radius-sm: 14px;
      --title-font: \"Avenir Next Condensed\", \"Gill Sans Nova\", \"Trebuchet MS\", sans-serif;
      --body-font: \"Iowan Old Style\", \"Palatino Linotype\", \"Book Antiqua\", Palatino, serif;
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      font-family: var(--body-font);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(181, 93, 61, 0.18), transparent 34%),
        radial-gradient(circle at top right, rgba(47, 111, 95, 0.14), transparent 28%),
        linear-gradient(180deg, #fbf7f0 0%, var(--bg) 48%, #ece4d7 100%);
    }}

    .page {{
      width: min(1180px, calc(100vw - 32px));
      margin: 24px auto 48px;
      display: grid;
      gap: 20px;
    }}

    .hero {{
      border-radius: calc(var(--radius) + 8px);
      padding: 28px;
      background:
        linear-gradient(135deg, rgba(255, 250, 242, 0.96), rgba(235, 222, 201, 0.9)),
        var(--card-strong);
      box-shadow: var(--shadow);
      border: 1px solid rgba(23, 49, 59, 0.08);
    }}

    .eyebrow {{
      font-family: var(--title-font);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.78rem;
      color: var(--accent);
      margin-bottom: 12px;
    }}

    h1, h2, h3 {{
      margin: 0;
      font-family: var(--title-font);
      letter-spacing: 0.01em;
    }}

    h1 {{
      font-size: clamp(2.1rem, 4vw, 3.8rem);
      line-height: 0.95;
      max-width: 11ch;
    }}

    .hero-grid {{
      display: grid;
      grid-template-columns: 1.6fr 1fr;
      gap: 24px;
      align-items: end;
      margin-top: 18px;
    }}

    .hero-meta {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}

    .meta-card, .panel, .metric-card, .task-card, .provider-card {{
      border-radius: var(--radius);
      background: var(--card);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }}

    .meta-card {{
      padding: 14px 16px;
    }}

    .meta-label {{
      display: block;
      font-family: var(--title-font);
      text-transform: uppercase;
      letter-spacing: 0.11em;
      font-size: 0.72rem;
      color: var(--muted);
      margin-bottom: 8px;
    }}

    .meta-value {{
      font-size: 1.08rem;
      word-break: break-word;
    }}

    .section-grid {{
      display: grid;
      gap: 20px;
    }}

    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
    }}

    .metric-card {{
      padding: 16px 18px 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.84), rgba(255,248,240,0.94));
    }}

    .metric-value {{
      font-family: var(--title-font);
      font-size: 2rem;
      line-height: 1;
      margin-top: 10px;
    }}

    .panel {{
      padding: 20px;
    }}

    .panel-header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      margin-bottom: 14px;
    }}

    .panel-subtitle {{
      color: var(--muted);
      font-size: 0.95rem;
    }}

    .section-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 14px;
      justify-content: end;
      align-items: baseline;
    }}

    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .filter-summary {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 16px;
    }}

    .jump-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }}

    .jump-link {{
      text-decoration: none;
      color: var(--ink);
      background: rgba(255, 252, 247, 0.8);
      border: 1px solid rgba(23, 49, 59, 0.1);
      border-radius: 999px;
      padding: 8px 14px;
      font-family: var(--title-font);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.74rem;
    }}

    .chip {{
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--ink);
      font-family: var(--title-font);
      font-size: 0.78rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}

    .task-grid, .provider-grid, .execution-grid {{
      display: grid;
      gap: 16px;
    }}

    .filter-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 16px;
      padding: 14px;
      border-radius: var(--radius-sm);
      background: rgba(255, 250, 242, 0.78);
      border: 1px solid rgba(23, 49, 59, 0.08);
    }}

    .filter-control {{
      display: grid;
      gap: 6px;
      min-width: min(220px, 100%);
    }}

    .filter-control label {{
      font-family: var(--title-font);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.74rem;
      color: var(--muted);
    }}

    .filter-control select {{
      appearance: none;
      border-radius: 12px;
      border: 1px solid rgba(23, 49, 59, 0.14);
      background: #fffdf8;
      padding: 10px 12px;
      font: inherit;
      color: var(--ink);
    }}

    .filter-control input {{
      border-radius: 12px;
      border: 1px solid rgba(23, 49, 59, 0.14);
      background: #fffdf8;
      padding: 10px 12px;
      font: inherit;
      color: var(--ink);
    }}

    .filter-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: end;
    }}

    .secondary-button {{
      border-radius: 12px;
      border: 1px solid rgba(23, 49, 59, 0.14);
      background: rgba(255, 252, 247, 0.9);
      color: var(--ink);
      padding: 10px 14px;
      font-family: var(--title-font);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.74rem;
      cursor: pointer;
    }}

    .filter-feedback {{
      color: var(--muted);
      font-size: 0.92rem;
      align-self: center;
    }}

    .is-hidden {{
      display: none !important;
    }}

    .task-grid {{ grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }}
    .provider-grid {{ grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
    .execution-grid {{ grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}

    .task-card, .provider-card, .diagnostic-card {{
      padding: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.82), rgba(250,243,232,0.95));
    }}

    .card-top {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      margin-bottom: 10px;
    }}

    .card-actions {{
      display: flex;
      flex-direction: column;
      align-items: end;
      gap: 8px;
    }}

    .card-link {{
      text-decoration: none;
      color: var(--accent);
      font-family: var(--title-font);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.72rem;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 6px 10px;
      font-family: var(--title-font);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.72rem;
      background: rgba(23, 49, 59, 0.08);
      color: var(--ink);
    }}

    .badge.ok {{ background: rgba(47, 111, 95, 0.14); color: var(--ok); }}
    .badge.fail {{ background: rgba(159, 61, 43, 0.14); color: var(--fail); }}
    .badge.warn {{ background: rgba(154, 106, 21, 0.16); color: var(--warn); }}

    dl {{
      margin: 0;
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: 8px 12px;
      font-size: 0.98rem;
    }}

    dt {{ color: var(--muted); }}
    dd {{ margin: 0; }}

    .drilldown {{
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid rgba(23, 49, 59, 0.1);
    }}

    .drilldown summary {{
      cursor: pointer;
      font-family: var(--title-font);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.76rem;
      color: var(--accent);
      list-style: none;
    }}

    .drilldown summary::-webkit-details-marker {{
      display: none;
    }}

    .drilldown summary::after {{
      content: "+";
      display: inline-block;
      margin-left: 8px;
      color: var(--muted);
    }}

    .drilldown[open] summary::after {{
      content: "-";
    }}

    .drilldown dl {{
      margin-top: 12px;
    }}

    .match-highlight {{
      background: rgba(181, 93, 61, 0.22);
      color: inherit;
      padding: 0 2px;
      border-radius: 4px;
    }}

    .empty-state {{
      margin: 16px 0 0;
      padding: 14px 16px;
      border-radius: var(--radius-sm);
      border: 1px dashed rgba(23, 49, 59, 0.16);
      background: rgba(255, 252, 247, 0.78);
      color: var(--muted);
    }}

    .task-card:target,
    .provider-card:target,
    .diagnostic-card:target {{
      scroll-margin-top: 24px;
      outline: 3px solid rgba(181, 93, 61, 0.28);
      outline-offset: 2px;
    }}

    .footer-note {{
      color: var(--muted);
      font-size: 0.92rem;
      padding: 4px 2px 0;
    }}

    @media print {{
      body {{
        background: #ffffff;
      }}

      .page {{
        width: 100%;
        margin: 0;
      }}

      .hero,
      .panel,
      .meta-card,
      .metric-card,
      .task-card,
      .provider-card,
      .diagnostic-card {{
        box-shadow: none;
        background: #ffffff;
        border-color: rgba(23, 49, 59, 0.18);
      }}

      .jump-links,
      .filter-bar {{
        display: none !important;
      }}
    }}

    @media (max-width: 900px) {{
      .hero-grid {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}

    @media (max-width: 640px) {{
      .page {{ width: min(100vw - 20px, 1180px); margin: 10px auto 28px; }}
      .hero {{ padding: 22px; }}
      .metrics {{ grid-template-columns: 1fr; }}
      .hero-meta {{ grid-template-columns: 1fr; }}
      dl {{ grid-template-columns: 1fr; gap: 4px; }}
    }}
  </style>
</head>
<body>
  <main class=\"page\">
    <section class=\"hero\" id=\"overview\">
      <div class=\"eyebrow\">Internal Observability Report</div>
      <h1>{_escape(overview['project_name'])}</h1>
      <div class=\"hero-grid\">
        <div>
          <p>{_escape(overview['goal'])}</p>
          <div class=\"chips\">
            <span class=\"badge {_status_badge_class(workflow_status)}\">{_escape(workflow_status)}</span>
            <span class=\"chip\">phase: {_escape(overview['phase'])}</span>
            <span class=\"chip\">state file: {_escape(source_name)}</span>
            <span class=\"chip\">store: {_escape(view['source']['state_store_kind'])}</span>
          </div>
        </div>
        <div class=\"hero-meta\">
          <div class=\"meta-card\">
            <span class=\"meta-label\">Final Providers</span>
            <div class=\"meta-value\">{_escape(final_providers)}</div>
          </div>
          <div class=\"meta-card\">
            <span class=\"meta-label\">Observed Providers</span>
            <div class=\"meta-value\">{_escape(observed_providers)}</div>
          </div>
          <div class=\"meta-card\">
            <span class=\"meta-label\">Outcome</span>
            <div class=\"meta-value\">{_escape(_none_label(overview['terminal_outcome']))}</div>
          </div>
          <div class=\"meta-card\">
            <span class=\"meta-label\">Updated</span>
            <div class=\"meta-value\">{_escape(_none_label(overview['updated_at']))}</div>
          </div>
        </div>
      </div>
      <nav class=\"jump-links\" aria-label=\"Report sections\">{jump_links}</nav>
    </section>

    <section class=\"metrics\">
      <article class=\"metric-card\">
        <span class=\"meta-label\">Tasks</span>
        <div class=\"metric-value\">{overview['task_count']}</div>
      </article>
      <article class=\"metric-card\">
        <span class=\"meta-label\">Attempts</span>
        <div class=\"metric-value\">{overview['attempt_count']}</div>
      </article>
      <article class=\"metric-card\">
        <span class=\"meta-label\">Retry Attempts</span>
        <div class=\"metric-value\">{overview['retry_attempt_count']}</div>
      </article>
      <article class=\"metric-card\">
        <span class=\"meta-label\">Acceptance</span>
        <div class=\"metric-value\">{str(overview['acceptance_criteria_met']).lower()}</div>
      </article>
    </section>

    <section class=\"panel\">
      <div class=\"panel-header\">
        <h2>Workflow Overview</h2>
        <span class=\"panel-subtitle\">Adapter-backed internal telemetry, not snapshot mirroring</span>
      </div>
      <div class=\"chips\">{status_counts}</div>
      <p class=\"footer-note\">Duration summary: count={overview['duration_ms']['count']}, total={_escape(_none_label(overview['duration_ms']['total']))}, avg={_escape(_none_label(overview['duration_ms']['avg']))}. Usage: {_escape(_format_metric_map(overview['usage']))}</p>
    </section>

    <section class=\"panel\" id=\"tasks\">
      <div class=\"panel-header\">
        <h2>Task Timeline</h2>
        <div class=\"section-meta\">
          <span class=\"panel-subtitle\">Exact provider/model, durations, retries, and failure presence</span>
          <span class=\"panel-subtitle\" id=\"tasks-visible-count\">Showing {len(view['task_timeline'])} of {len(view['task_timeline'])} tasks</span>
        </div>
      </div>
      <div class=\"filter-bar\">
        <div class=\"filter-control\">
          <label for=\"report-search\">Search</label>
          <input id=\"report-search\" type=\"search\" placeholder=\"Search tasks, providers, diagnostics\" />
        </div>
        <div class=\"filter-control\">
          <label for=\"task-status-filter\">Task status</label>
          <select id=\"task-status-filter\">
            {task_status_filter_options}
          </select>
        </div>
        <div class=\"filter-control\">
          <label for=\"provider-filter\">Provider</label>
          <select id=\"provider-filter\">
            {provider_filter_options}
          </select>
        </div>
        <div class="filter-control">
          <label for="task-sort">Task order</label>
          <select id="task-sort">
            {task_sort_options}
          </select>
        </div>
        <div class="filter-control">
          <label for="provider-sort">Provider order</label>
          <select id="provider-sort">
            {provider_sort_options}
          </select>
        </div>
        <div class=\"filter-actions\">
          <button class="secondary-button" id="reset-filters" type="button">Reset View</button>
          <button class=\"secondary-button\" id=\"copy-filter-link\" type=\"button\">Copy Filter Link</button>
          <button class="secondary-button" id="print-report" type="button">Print / Save PDF</button>
          <button class="secondary-button" id="expand-visible-details" type="button">Expand Visible Details</button>
          <button class="secondary-button" id="collapse-visible-details" type="button">Collapse Visible Details</button>
          <span class="filter-feedback" id="share-link-feedback">Filter state is encoded in the URL. Treat this report as internal data.</span>
        </div>
      </div>
      <div class=\"filter-summary\" id=\"filter-summary\">
        <span class=\"chip\">filters: all</span>
        <span class=\"chip\">tasks: {len(view['task_timeline'])}/{len(view['task_timeline'])}</span>
        <span class=\"chip\">providers: {len(view['provider_panels'])}/{len(view['provider_panels'])}</span>
        <span class=\"chip\">diagnostics: 4/4</span>
      </div>
      <div class=\"task-grid\">{task_cards}</div>
      <p class=\"empty-state is-hidden\" id=\"tasks-empty-state\">No task cards match the current filters.</p>
    </section>

    <section class=\"panel\" id=\"providers\">
      <div class=\"panel-header\">
        <h2>Provider Panels</h2>
        <div class=\"section-meta\">
          <span class=\"panel-subtitle\">Rollups built from provider summary and provider health summary</span>
          <span class=\"panel-subtitle\" id=\"providers-visible-count\">Showing {len(view['provider_panels'])} of {len(view['provider_panels'])} providers</span>
        </div>
      </div>
      <div class=\"provider-grid\">{provider_cards}</div>
      <p class=\"empty-state is-hidden\" id=\"providers-empty-state\">No provider cards match the current filters.</p>
    </section>

    <section class=\"panel\" id=\"diagnostics\">
      <div class=\"panel-header\">
        <h2>Execution Diagnostics</h2>
        <div class=\"section-meta\">
          <span class=\"panel-subtitle\">Resume, repair, fallback, and final error counters</span>
          <span class=\"panel-subtitle\" id=\"diagnostics-visible-count\">Showing 4 of 4 diagnostics</span>
        </div>
      </div>
      <div class=\"execution-grid\">{diagnostic_cards}</div>
      <p class=\"empty-state is-hidden\" id=\"diagnostics-empty-state\">No diagnostic cards match the current filters.</p>
    </section>

    <section class=\"panel\" id=\"provenance\">
      <div class=\"panel-header\">
        <h2>Report Provenance</h2>
        <span class=\"panel-subtitle\">Generation metadata for evidence handling</span>
      </div>
      <div class=\"chips\">
        <span class=\"chip\">generated at (UTC): {_escape(provenance['generated_at'])}</span>
        <span class=\"chip\">tool: kycortex-agents {_escape(provenance['tool_version'])}</span>
        <span class=\"chip\">source state file: {_escape(source_name)}</span>
        <span class=\"chip\">store: {_escape(view['source']['state_store_kind'])}</span>
        <span class=\"chip\">schema version: {view['source']['schema_version']}</span>
        <span class=\"chip\">source state sha256: {_escape(provenance['state_sha256'])}</span>
      </div>
      <p class=\"footer-note\">Sensitivity: INTERNAL. This report contains operational workflow data; share only with authorized recipients under your data-handling policy.</p>
      <p class=\"footer-note\">Sensitive values (credentials, secrets) were redacted at recording time before persistence; redaction is irreversible.</p>
      <p class=\"footer-note\">Disclaimer: this is an operational telemetry report rendered from persisted workflow state. It is not, by itself, a certified compliance or audit record, and the source state digest above does not attest tamper-evidence of the recording process.</p>
    </section>
  </main>
  <script>
    const reportSearch = document.getElementById("report-search");
    const taskStatusFilter = document.getElementById("task-status-filter");
    const providerFilter = document.getElementById("provider-filter");
    const taskSortControl = document.getElementById("task-sort");
    const providerSortControl = document.getElementById("provider-sort");
    const resetFiltersButton = document.getElementById("reset-filters");
    const copyFilterLinkButton = document.getElementById("copy-filter-link");
    const printReportButton = document.getElementById("print-report");
    const expandVisibleDetailsButton = document.getElementById("expand-visible-details");
    const collapseVisibleDetailsButton = document.getElementById("collapse-visible-details");
    const shareLinkFeedback = document.getElementById("share-link-feedback");
    const filterSummary = document.getElementById("filter-summary");
    const tasksVisibleCount = document.getElementById("tasks-visible-count");
    const providersVisibleCount = document.getElementById("providers-visible-count");
    const diagnosticsVisibleCount = document.getElementById("diagnostics-visible-count");
    const tasksEmptyState = document.getElementById("tasks-empty-state");
    const providersEmptyState = document.getElementById("providers-empty-state");
    const diagnosticsEmptyState = document.getElementById("diagnostics-empty-state");
    const taskGrid = document.querySelector(".task-grid");
    const providerGrid = document.querySelector(".provider-grid");
    const taskCards = Array.from(document.querySelectorAll(".task-card[data-task-status]"));
    const providerCards = Array.from(document.querySelectorAll(".provider-card[data-provider-name]"));
    const diagnosticCards = Array.from(document.querySelectorAll(".diagnostic-card[data-search-text]"));
    const drilldownBlocks = Array.from(document.querySelectorAll(".drilldown"));
    const highlightTargets = Array.from(document.querySelectorAll(".search-highlight-target[data-highlight-source]"));
    const taskCardOrder = new Map(taskCards.map((card, index) => [card, index]));
    const providerCardOrder = new Map(providerCards.map((card, index) => [card, index]));
    const FILTER_STORAGE_KEY = "kycortex-internal-observability-report-filters";
    const TASK_SORT_LABELS = {{
      "slowest-task": "slowest task",
      "slowest-provider": "slowest provider",
      title: "title A-Z",
    }};
    const PROVIDER_SORT_LABELS = {{
      "most-failures": "most failures",
      "slowest-avg": "slowest avg duration",
      name: "provider A-Z",
    }};

    function normalizeFilterState(state = {{}}) {{
      return {{
        search: typeof state.search === "string" ? state.search.trim() : "",
        status: typeof state.status === "string" && state.status ? state.status : "all",
        provider: typeof state.provider === "string" && state.provider ? state.provider : "all",
        taskSort: typeof state.taskSort === "string" && state.taskSort ? state.taskSort : "default",
        providerSort: typeof state.providerSort === "string" && state.providerSort ? state.providerSort : "default",
      }};
    }}

    function readFilterStateFromUrl() {{
      const params = new URLSearchParams(window.location.search);
      return normalizeFilterState({{
        search: params.get("q") || "",
        status: params.get("status") || "all",
        provider: params.get("provider") || "all",
        taskSort: params.get("task_sort") || "default",
        providerSort: params.get("provider_sort") || "default",
      }});
    }}

    function loadFilterStateFromStorage() {{
      try {{
        const rawState = window.localStorage.getItem(FILTER_STORAGE_KEY);
        if (!rawState) {{
          return normalizeFilterState();
        }}
        return normalizeFilterState(JSON.parse(rawState));
      }} catch {{
        return normalizeFilterState();
      }}
    }}

    function persistFilterState(state) {{
      const normalizedState = normalizeFilterState(state);
      const url = new URL(window.location.href);

      if (normalizedState.search) {{
        url.searchParams.set("q", normalizedState.search);
      }} else {{
        url.searchParams.delete("q");
      }}
      if (normalizedState.status !== "all") {{
        url.searchParams.set("status", normalizedState.status);
      }} else {{
        url.searchParams.delete("status");
      }}
      if (normalizedState.provider !== "all") {{
        url.searchParams.set("provider", normalizedState.provider);
      }} else {{
        url.searchParams.delete("provider");
      }}
      if (normalizedState.taskSort !== "default") {{
        url.searchParams.set("task_sort", normalizedState.taskSort);
      }} else {{
        url.searchParams.delete("task_sort");
      }}
      if (normalizedState.providerSort !== "default") {{
        url.searchParams.set("provider_sort", normalizedState.providerSort);
      }} else {{
        url.searchParams.delete("provider_sort");
      }}

      history.replaceState(null, "", url.toString());

      try {{
        window.localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(normalizedState));
      }} catch {{
        // Ignore browser storage failures; URL state still carries the filters.
      }}
    }}

    function applyPersistedFilterState() {{
      const storageState = loadFilterStateFromStorage();
      const urlState = readFilterStateFromUrl();
      const mergedState = normalizeFilterState({{
        search: urlState.search || storageState.search,
        status: urlState.status !== "all" ? urlState.status : storageState.status,
        provider: urlState.provider !== "all" ? urlState.provider : storageState.provider,
        taskSort: urlState.taskSort !== "default" ? urlState.taskSort : storageState.taskSort,
        providerSort: urlState.providerSort !== "default" ? urlState.providerSort : storageState.providerSort,
      }});

      if (reportSearch) {{
        reportSearch.value = mergedState.search;
      }}
      if (taskStatusFilter) {{
        const hasStatusOption = Array.from(taskStatusFilter.options).some((option) => option.value === mergedState.status);
        taskStatusFilter.value = hasStatusOption ? mergedState.status : "all";
      }}
      if (providerFilter) {{
        const hasProviderOption = Array.from(providerFilter.options).some((option) => option.value === mergedState.provider);
        providerFilter.value = hasProviderOption ? mergedState.provider : "all";
      }}
      if (taskSortControl) {{
        const hasTaskSortOption = Array.from(taskSortControl.options).some((option) => option.value === mergedState.taskSort);
        taskSortControl.value = hasTaskSortOption ? mergedState.taskSort : "default";
      }}
      if (providerSortControl) {{
        const hasProviderSortOption = Array.from(providerSortControl.options).some((option) => option.value === mergedState.providerSort);
        providerSortControl.value = hasProviderSortOption ? mergedState.providerSort : "default";
      }}
    }}

    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }}

    function escapeRegExp(value) {{
      const specials = new Set(["\\", "^", "$", "*", "+", "?", ".", "(", ")", "|", "{{", "}}", "[", "]"]);
      let escaped = "";

      for (const character of String(value)) {{
        escaped += specials.has(character) ? `\\${{character}}` : character;
      }}

      return escaped;
    }}

    function renderHighlightedText(sourceText, searchQuery) {{
      const normalizedSource = typeof sourceText === "string" ? sourceText : "";
      if (!searchQuery) {{
        return escapeHtml(normalizedSource);
      }}

      const matcher = new RegExp(escapeRegExp(searchQuery), "ig");
      let cursor = 0;
      let html = "";

      for (const match of normalizedSource.matchAll(matcher)) {{
        const start = typeof match.index === "number" ? match.index : -1;
        if (start < 0) {{
          continue;
        }}
        html += escapeHtml(normalizedSource.slice(cursor, start));
        html += `<mark class="match-highlight">${{escapeHtml(match[0])}}</mark>`;
        cursor = start + match[0].length;
      }}

      html += escapeHtml(normalizedSource.slice(cursor));
      return html;
    }}

    function applyHighlights(searchQuery) {{
      for (const target of highlightTargets) {{
        const sourceText = target.dataset.highlightSource || "";
        target.innerHTML = renderHighlightedText(sourceText, searchQuery);
      }}
    }}

    function countVisible(cards) {{
      return cards.filter((card) => !card.classList.contains("is-hidden")).length;
    }}

    function numericSortValue(value, fallback = -1) {{
      const parsed = Number.parseFloat(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    }}

    function compareTextValues(left, right) {{
      return String(left || "").localeCompare(String(right || ""), undefined, {{ sensitivity: "base" }});
    }}

    function sortCards(container, cards, compareCards) {{
      if (!container) {{
        return;
      }}

      const sortedCards = [...cards].sort(compareCards);
      for (const card of sortedCards) {{
        container.appendChild(card);
      }}
    }}

    function sortTaskCards(selectedTaskSort) {{
      sortCards(taskGrid, taskCards, (left, right) => {{
        if (selectedTaskSort === "slowest-task") {{
          return (
            numericSortValue(right.dataset.taskDurationMs) - numericSortValue(left.dataset.taskDurationMs)
            || taskCardOrder.get(left) - taskCardOrder.get(right)
          );
        }}
        if (selectedTaskSort === "slowest-provider") {{
          return (
            numericSortValue(right.dataset.providerDurationMs) - numericSortValue(left.dataset.providerDurationMs)
            || taskCardOrder.get(left) - taskCardOrder.get(right)
          );
        }}
        if (selectedTaskSort === "title") {{
          return compareTextValues(left.dataset.taskTitle, right.dataset.taskTitle)
            || taskCardOrder.get(left) - taskCardOrder.get(right);
        }}

        return taskCardOrder.get(left) - taskCardOrder.get(right);
      }});
    }}

    function sortProviderCards(selectedProviderSort) {{
      sortCards(providerGrid, providerCards, (left, right) => {{
        if (selectedProviderSort === "most-failures") {{
          return (
            numericSortValue(right.dataset.failureCount) - numericSortValue(left.dataset.failureCount)
            || providerCardOrder.get(left) - providerCardOrder.get(right)
          );
        }}
        if (selectedProviderSort === "slowest-avg") {{
          return (
            numericSortValue(right.dataset.durationAvgMs) - numericSortValue(left.dataset.durationAvgMs)
            || providerCardOrder.get(left) - providerCardOrder.get(right)
          );
        }}
        if (selectedProviderSort === "name") {{
          return compareTextValues(left.dataset.providerName, right.dataset.providerName)
            || providerCardOrder.get(left) - providerCardOrder.get(right);
        }}

        return providerCardOrder.get(left) - providerCardOrder.get(right);
      }});
    }}

    function updateSectionState(cards, countNode, emptyNode, singularLabel, pluralLabel) {{
      const visibleCount = countVisible(cards);
      const totalCount = cards.length;
      const label = visibleCount === 1 ? singularLabel : pluralLabel;

      if (countNode) {{
        countNode.textContent = `Showing ${{visibleCount}} of ${{totalCount}} ${{label}}`;
      }}
      if (emptyNode) {{
        emptyNode.classList.toggle("is-hidden", visibleCount !== 0);
      }}

      return visibleCount;
    }}

    function renderSummaryChip(text) {{
      return `<span class="chip">${{escapeHtml(text)}}</span>`;
    }}

    function updateFilterSummary(state, visibleCounts) {{
      if (!filterSummary) {{
        return;
      }}

      const chips = [];
      if (state.search) {{
        chips.push(`search: ${{state.search}}`);
      }}
      if (state.status !== "all") {{
        chips.push(`status: ${{state.status}}`);
      }}
      if (state.provider !== "all") {{
        chips.push(`provider: ${{state.provider}}`);
      }}
      if (state.taskSort !== "default") {{
        chips.push(`task order: ${{TASK_SORT_LABELS[state.taskSort] || state.taskSort}}`);
      }}
      if (state.providerSort !== "default") {{
        chips.push(`provider order: ${{PROVIDER_SORT_LABELS[state.providerSort] || state.providerSort}}`);
      }}
      if (chips.length === 0) {{
        chips.push("filters: all");
      }}

      chips.push(`tasks: ${{visibleCounts.tasks}}/${{taskCards.length}}`);
      chips.push(`providers: ${{visibleCounts.providers}}/${{providerCards.length}}`);
      chips.push(`diagnostics: ${{visibleCounts.diagnostics}}/${{diagnosticCards.length}}`);

      filterSummary.innerHTML = chips.map(renderSummaryChip).join("");
    }}

    function resetFilters() {{
      if (reportSearch) {{
        reportSearch.value = "";
      }}
      if (taskStatusFilter) {{
        taskStatusFilter.value = "all";
      }}
      if (providerFilter) {{
        providerFilter.value = "all";
      }}
      if (taskSortControl) {{
        taskSortControl.value = "default";
      }}
      if (providerSortControl) {{
        providerSortControl.value = "default";
      }}
      applyFilters();
    }}

    function setShareLinkFeedback(message) {{
      if (shareLinkFeedback) {{
        shareLinkFeedback.textContent = message;
      }}
    }}

    async function copyFilterLink() {{
      const shareableUrl = window.location.href;

      try {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          await navigator.clipboard.writeText(shareableUrl);
          setShareLinkFeedback("Copied current report view link.");
          return;
        }}
      }} catch {{
        // Fall through to the prompt fallback below.
      }}

      if (window.prompt) {{
        window.prompt("Copy report link", shareableUrl);
        setShareLinkFeedback("Opened copy prompt for current report view link.");
        return;
      }}

      setShareLinkFeedback("Current report view link is available in the address bar.");
    }}

    function setVisibleDrilldownsExpanded(isExpanded) {{
      for (const drilldown of drilldownBlocks) {{
        const card = drilldown.closest(".task-card, .provider-card, .diagnostic-card");
        if (card && card.classList.contains("is-hidden")) {{
          continue;
        }}
        drilldown.open = isExpanded;
      }}
    }}

    function printCurrentReport() {{
      if (window.print) {{
        window.print();
      }}
    }}

    function applyFilters() {{
      const rawSearchQuery = reportSearch ? reportSearch.value.trim() : "";
      const searchQuery = rawSearchQuery.toLowerCase();
      const selectedStatus = taskStatusFilter ? taskStatusFilter.value : "all";
      const selectedProvider = providerFilter ? providerFilter.value : "all";
      const selectedTaskSort = taskSortControl ? taskSortControl.value : "default";
      const selectedProviderSort = providerSortControl ? providerSortControl.value : "default";

      for (const taskCard of taskCards) {{
        const matchesStatus = selectedStatus === "all" || taskCard.dataset.taskStatus === selectedStatus;
        const matchesProvider = selectedProvider === "all" || taskCard.dataset.provider === selectedProvider;
        const matchesSearch = !searchQuery || taskCard.dataset.searchText.includes(searchQuery);
        taskCard.classList.toggle("is-hidden", !(matchesStatus && matchesProvider && matchesSearch));
      }}

      for (const providerCard of providerCards) {{
        const matchesProvider = selectedProvider === "all" || providerCard.dataset.providerName === selectedProvider;
        const matchesSearch = !searchQuery || providerCard.dataset.searchText.includes(searchQuery);
        providerCard.classList.toggle("is-hidden", !(matchesProvider && matchesSearch));
      }}

      for (const diagnosticCard of diagnosticCards) {{
        const matchesSearch = !searchQuery || diagnosticCard.dataset.searchText.includes(searchQuery);
        diagnosticCard.classList.toggle("is-hidden", !matchesSearch);
      }}

      sortTaskCards(selectedTaskSort);
      sortProviderCards(selectedProviderSort);

      persistFilterState({{
        search: rawSearchQuery,
        status: selectedStatus,
        provider: selectedProvider,
        taskSort: selectedTaskSort,
        providerSort: selectedProviderSort,
      }});
      applyHighlights(rawSearchQuery);

      const visibleCounts = {{
        tasks: updateSectionState(taskCards, tasksVisibleCount, tasksEmptyState, "task", "tasks"),
        providers: updateSectionState(providerCards, providersVisibleCount, providersEmptyState, "provider", "providers"),
        diagnostics: updateSectionState(
          diagnosticCards,
          diagnosticsVisibleCount,
          diagnosticsEmptyState,
          "diagnostic",
          "diagnostics"
        ),
      }};
      updateFilterSummary(
        {{
          search: rawSearchQuery,
          status: selectedStatus,
          provider: selectedProvider,
          taskSort: selectedTaskSort,
          providerSort: selectedProviderSort,
        }},
        visibleCounts,
      );
      setShareLinkFeedback("Filter state is encoded in the URL. Treat this report as internal data.");
    }}

    if (reportSearch) {{
      reportSearch.addEventListener("input", applyFilters);
    }}
    if (taskStatusFilter) {{
      taskStatusFilter.addEventListener("change", applyFilters);
    }}
    if (providerFilter) {{
      providerFilter.addEventListener("change", applyFilters);
    }}
    if (taskSortControl) {{
      taskSortControl.addEventListener("change", applyFilters);
    }}
    if (providerSortControl) {{
      providerSortControl.addEventListener("change", applyFilters);
    }}
    if (resetFiltersButton) {{
      resetFiltersButton.addEventListener("click", resetFilters);
    }}
    if (copyFilterLinkButton) {{
      copyFilterLinkButton.addEventListener("click", () => {{
        void copyFilterLink();
      }});
    }}
    if (printReportButton) {{
      printReportButton.addEventListener("click", printCurrentReport);
    }}
    if (expandVisibleDetailsButton) {{
      expandVisibleDetailsButton.addEventListener("click", () => {{
        setVisibleDrilldownsExpanded(true);
      }});
    }}
    if (collapseVisibleDetailsButton) {{
      collapseVisibleDetailsButton.addEventListener("click", () => {{
        setVisibleDrilldownsExpanded(false);
      }});
    }}
    applyPersistedFilterState();
    applyFilters();
  </script>
</body>
</html>
"""


def write_html_report(path: Path, html_report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_report, encoding="utf-8")


def build_observability_http_server(
    state_file: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    class ObservabilityRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request_path = urlsplit(self.path).path or "/"

            if request_path == "/healthz":
                payload = b"ok\n"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if request_path not in {"/", "/index.html"}:
                payload = b"not found\n"
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            html_report = build_html_report(load_internal_observability_view(state_file))
            payload = html_report.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return ThreadingHTTPServer((host, port), ObservabilityRequestHandler)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.serve:
        server = build_observability_http_server(args.state_file, host=args.host, port=args.port)
        try:
            print(
                f"Serving internal_observability_report from {Path(args.state_file).name if args.state_file else 'none'} "
                f"at http://{args.host}:{server.server_port}",
                flush=True,
            )
            server.serve_forever()
        except KeyboardInterrupt:
            print("Stopped internal_observability_report server", flush=True)
        finally:
            server.server_close()
        return 0

    view = load_internal_observability_view(args.state_file)
    output_path = resolve_output_html_path(args.state_file, args.output_html)
    html_report = build_html_report(view)
    write_html_report(output_path, html_report)
    print(
        f"Wrote {output_path.name} from "
        f"{Path(args.state_file).name if args.state_file else 'none'}",
        flush=True,
    )
    return 0


def _render_task_card(task: Mapping[str, Any]) -> str:
    status = _none_label(task.get("status"))
    provider = _none_label(task.get("provider"))
    title = task.get("title") or task.get("task_id") or "unknown"
    card_anchor = _card_anchor_id("task", task.get("task_id") or title)
    description = task.get("description") or ""
    search_text = _search_text(
        task.get("task_id"),
        title,
        description,
        task.get("assigned_to"),
        task.get("provider"),
        task.get("model"),
        status,
        _format_csv(task.get("dependencies") or []),
    )
    drilldown = _render_details_block(
        "Task Drill-down",
        [
            ("Assigned To", _none_label(task.get("assigned_to"))),
            ("Repair Origin", _none_label(task.get("repair_origin_task_id"))),
            ("Started", _none_label(task.get("started_at"))),
            ("Last Attempt", _none_label(task.get("last_attempt_started_at"))),
            ("Completed", _none_label(task.get("completed_at"))),
            ("Success", _none_label(task.get("success"))),
        ],
    )
    task_details = _render_definition_list(
        [
            ("Task ID", task.get("task_id") or "unknown"),
            ("Dependencies", _format_csv(task.get("dependencies") or [])),
            ("Provider", _none_label(task.get("provider"))),
            ("Model", _none_label(task.get("model"))),
            ("Attempts", str(task.get("attempts_used", 0))),
            ("Retries", str(task.get("retry_attempt_count", 0))),
            ("Task Duration", _none_label(task.get("task_duration_ms"))),
            ("Provider Duration", _none_label(task.get("provider_duration_ms"))),
            ("Provider Latency", _none_label(task.get("provider_latency_ms"))),
            ("Usage", _format_metric_map(task.get("usage", {}))),
            ("Output", "present" if task.get("has_output") else "none"),
            ("Failure", "present" if task.get("has_failure") else "none"),
        ]
    )
    return f"""
      <article class="task-card" id="{_escape(card_anchor)}" data-task-status="{_escape(status)}" data-provider="{_escape(provider)}" data-search-text="{_escape(search_text)}" data-task-title="{_escape(title)}" data-task-duration-ms="{_escape(_sortable_number(task.get('task_duration_ms')))}" data-provider-duration-ms="{_escape(_sortable_number(task.get('provider_duration_ms')))}">
        <div class=\"card-top\">
          <div>
            <div class=\"eyebrow\">Task</div>
            <h3>{_highlightable_text(title)}</h3>
          </div>
          <div class="card-actions">
            <span class="badge {_status_badge_class(status)}">{_highlightable_text(status)}</span>
            <a class="card-link" href="#{_escape(card_anchor)}">Direct Link</a>
          </div>
        </div>
        <p>{_highlightable_text(description)}</p>
        {task_details}
        {drilldown}
      </article>
    """


def _render_provider_panel(panel: Mapping[str, Any]) -> str:
    status_counts = panel.get("status_counts", {})
    last_outcome_counts = panel.get("last_outcome_counts", {})
    panel_status = _provider_panel_status(panel)
    provider_name = panel.get("provider") or "unknown"
    card_anchor = _card_anchor_id("provider", provider_name)
    search_text = _search_text(
        provider_name,
        _format_csv(panel.get("models") or []),
        _format_count_map(status_counts),
        _format_count_map(last_outcome_counts),
        _format_metric_map(panel.get("usage", {})),
        panel_status,
    )
    drilldown = _render_details_block(
        "Provider Drill-down",
        [
            ("Attempts", str(panel.get("attempt_count", 0))),
            ("Retries", str(panel.get("retry_attempt_count", 0))),
            ("Retryable Failures", str(panel.get("retryable_failure_count", 0))),
            ("Active Health Checks", str(panel.get("active_health_check_count", 0))),
            ("Duration Summary", _format_duration_summary(panel.get("duration_ms", {}))),
        ],
    )
    provider_details = _render_definition_list(
        [
            ("Tasks", str(panel.get("task_count", 0))),
            ("Successes", str(panel.get("success_count", 0))),
            ("Failures", str(panel.get("failure_count", 0))),
            ("Models", _format_csv(panel.get("models") or [])),
            ("Status Counts", _format_count_map(status_counts)),
            ("Outcome Counts", _format_count_map(last_outcome_counts)),
            ("Usage", _format_metric_map(panel.get("usage", {}))),
            (
                "Active Checks",
                "present" if panel.get("active_health_check_count", 0) > 0 else "none",
            ),
        ]
    )
    return f"""
      <article class="provider-card" id="{_escape(card_anchor)}" data-provider-name="{_escape(provider_name)}" data-provider-status="{_escape(panel_status)}" data-search-text="{_escape(search_text)}" data-failure-count="{_escape(_sortable_number(panel.get('failure_count')))}" data-duration-avg-ms="{_escape(_sortable_number((panel.get('duration_ms') or {}).get('avg')))}">
        <div class=\"card-top\">
          <div>
            <div class=\"eyebrow\">Provider</div>
            <h3>{_highlightable_text(provider_name)}</h3>
          </div>
          <div class="card-actions">
            <span class="badge {_status_badge_class(panel_status)}">{_highlightable_text(panel_status)}</span>
            <a class="card-link" href="#{_escape(card_anchor)}">Direct Link</a>
          </div>
        </div>
        {provider_details}
        {drilldown}
      </article>
    """


def _provider_panel_status(panel: Mapping[str, Any]) -> str:
    status_counts = panel.get("status_counts", {})
    if isinstance(status_counts, Mapping):
        for preferred in ("open_circuit", "failing", "degraded", "healthy"):
            if int(status_counts.get(preferred, 0) or 0) > 0:
                return preferred
    if int(panel.get("failure_count", 0) or 0) > 0:
        return "failed"
    if int(panel.get("success_count", 0) or 0) > 0:
        return "healthy"
    return "idle"


def _status_value(status: Any) -> str:
    raw = getattr(status, "value", status)
    return str(raw) if raw is not None else "unknown"


def _status_badge_class(status: str) -> str:
    normalized = status.lower()
    if normalized in {"completed", "done", "healthy", "success"}:
        return "ok"
    if normalized in {"failed", "failure", "open_circuit", "failing"}:
        return "fail"
    if normalized in {"degraded", "paused", "review", "warning"}:
        return "warn"
    return ""


def _render_kv_chips(values: Mapping[str, Any]) -> str:
    return "".join(
        f'<span class="chip">{_escape(str(key))}: {_escape(str(values[key]))}</span>'
        for key in sorted(values)
    )


def _render_jump_links(sections: Iterable[tuple[str, str]]) -> str:
    return "".join(
        f'<a class="jump-link" href="#{_escape(section_id)}">{_escape(label)}</a>'
        for section_id, label in sections
    )


def _render_select_options(values: Iterable[Any], default_label: str) -> str:
    options = [f'<option value="all">{_escape(default_label)}</option>']
    for value in values:
        normalized = _none_label(value)
        if normalized == "none":
            continue
        options.append(f'<option value="{_escape(normalized)}">{_escape(normalized)}</option>')
    return "".join(options)


def _render_named_select_options(options: Iterable[tuple[str, str]]) -> str:
  return "".join(
    f'<option value="{_escape(value)}">{_escape(label)}</option>'
    for value, label in options
  )


def _card_anchor_id(prefix: str, value: Any) -> str:
  normalized = "item" if value in {None, ""} else str(value).strip().lower()
  slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "item"
  return f"{prefix}-{slug}"


def _render_details_block(title: str, entries: Iterable[tuple[str, str]]) -> str:
    return f"""
      <details class=\"drilldown\">
        <summary>{_highlightable_text(title)}</summary>
        {_render_definition_list(entries)}
      </details>
    """


def _render_diagnostic_card(
    title: str,
    metric_value: Any,
    detail_title: str,
    entries: Iterable[tuple[str, str]],
) -> str:
    normalized_entries = list(entries)
    card_anchor = _card_anchor_id("diagnostic", title)
    search_text = _search_text(title, detail_title, *(value for _, value in normalized_entries))
    return f"""
      <article class="diagnostic-card" id="{_escape(card_anchor)}" data-search-text="{_escape(search_text)}">
        <div class="card-top">
          <span class="meta-label">{_highlightable_text(title)}</span>
          <a class="card-link" href="#{_escape(card_anchor)}">Direct Link</a>
        </div>
        <div class="metric-value">{_escape(metric_value)}</div>
        {_render_details_block(detail_title, normalized_entries)}
      </article>
    """


def _render_definition_list(entries: Iterable[tuple[str, Any]]) -> str:
    rows = "".join(
        f"<dt>{_escape(label)}</dt><dd>{_highlightable_text(value)}</dd>"
        for label, value in entries
    )
    return f"<dl>{rows}</dl>"


def _format_duration_summary(values: Mapping[str, Any]) -> str:
    if not isinstance(values, Mapping) or not values:
        return "none"
    return ", ".join(
        f"{key}={values[key]}"
        for key in ("count", "total", "avg")
        if key in values and values[key] is not None
    ) or "none"


def _format_csv(values: Iterable[Any]) -> str:
    items = [str(value) for value in values if value is not None and str(value)]
    return ", ".join(items) if items else "none"


def _format_count_map(values: Mapping[str, Any]) -> str:
    if not isinstance(values, Mapping) or not values:
        return "none"
    parts = [f"{key}:{values[key]}" for key in sorted(values) if int(values[key] or 0) > 0]
    return ", ".join(parts) if parts else "none"


def _format_metric_map(values: Mapping[str, Any]) -> str:
    if not isinstance(values, Mapping) or not values:
        return "none"
    return ", ".join(f"{key}:{values[key]}" for key in sorted(values))


def _sortable_number(value: Any) -> str:
  if value in {None, ""}:
    return ""
  try:
    return str(float(value))
  except (TypeError, ValueError):
    return ""


def _search_text(*values: Any) -> str:
    items = []
    for value in values:
        if value in {None, ""}:
            continue
        normalized = str(value).strip().lower()
        if normalized:
            items.append(normalized)
    return " ".join(items)



def _highlightable_text(value: Any) -> str:
    normalized = "" if value in {None, ""} else str(value)
    return (
        f'<span class="search-highlight-target" data-highlight-source="{_escape(normalized)}">'
        f"{_escape(normalized)}"
        "</span>"
    )


def _none_label(value: Any) -> str:
    return "none" if value in {None, ""} else str(value)


def _escape(value: Any) -> str:
    return escape(str(value), quote=True)


if __name__ == "__main__":
    raise SystemExit(main())