"""Ollama A/B wall-time diagnostic for qwen3.5:9b vs qwen2.5-coder:7b.

Builds the exact architect prompt used by the release smoke test and measures
inference time per model directly against the Ollama API, bypassing orchestrator
overhead. Outputs a structured timing report to stdout and optionally to a JSON
file.

Usage::

    python scripts/ollama_ab_timing.py
    python scripts/ollama_ab_timing.py --models qwen3.5:9b qwen2.5-coder:7b
    python scripts/ollama_ab_timing.py --base-url http://localhost:11434 --num-ctx 4096
    python scripts/ollama_ab_timing.py --output-json /tmp/ab_report.json
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Prompts — must match exactly what ArchitectAgent produces for the smoke task
# ---------------------------------------------------------------------------

_ARCHITECT_SYSTEM_PROMPT = (
    "You are a Senior Software Architect at KYCortex AI Software House.\n"
    "Your job is to design modular, scalable Python project architectures.\n"
    "Output structured architecture documents including: module breakdown, file structure,\n"
    "interfaces, data flows, technology choices and rationale.\n"
    "Always think about extensibility, testability and open-source best practices.\n"
    "If the task asks for a single Python module or single file, keep the architecture scoped to that single module and do not invent a multi-file package layout.\n"
    "When a target module filename is provided, describe only that file and avoid directory trees.\n"
    "For compact single-module service tasks, prefer one cohesive public service surface plus domain models over separate helper-only collaborators or interface sections.\n"
    "Do not invent standalone RiskScorer, AuditLogger, BatchProcessor, Manager, Processor, or similar public helper types unless the task explicitly requires those public surfaces.\n"
    "When describing typed entities or dataclasses, list required fields before defaulted fields and call out defaults explicitly so downstream code generation does not infer an invalid constructor order.\n"
    "Prefer @dataclass for data containers and typed collections such as list[SpecificType] over generic dicts. Include type annotations on all public methods so test generation can match return shapes precisely.\n"
    "Example: describe AuditLog as action, details, timestamp(default now) rather than action, timestamp, details.\n"
    "When a task-level public contract anchor is provided, treat it as the exact public API ground truth. Preserve listed facade, model, method, and constructor-field names exactly and do not invent alternate aliases or competing public entrypoints."
)

_PUBLIC_CONTRACT_ANCHOR = (
    "\n\nPublic contract anchor:\n"
    "- Primary workflow function: calculate_budget_balance(income: float, expenses: list[float]) -> float\n"
    "- Supporting helper: format_currency(amount: float) -> str\n"
    '- Required CLI entrypoint: main() -> None with a literal if __name__ == "__main__": block\n'
    "- Keep these names exact. Do not rename calculate_budget_balance(...), format_currency(...), or main().\n"
    "- Do not wrap income and expenses in a request object, dataclass, dict, tuple, or alternate signature. Keep calculate_budget_balance(...) callable with exactly two arguments named income and expenses.\n"
    "- Use only the Python standard library."
)

_ARCHITECT_TASK_DESCRIPTION = (
    "Design a concise single-module architecture for a Python budget planner that exposes "
    "`calculate_budget_balance(income: float, expenses: list[float]) -> float`, one formatting helper, and a minimal CLI entrypoint. "
    "Use only the Python standard library and do not introduce third-party runtime dependencies or imports. "
    "Keep the architecture practical and compact."
    + _PUBLIC_CONTRACT_ANCHOR
)

_ARCHITECT_USER_MESSAGE = f"""Project Name: ReleaseUserSmokeOllama
Project Goal: Create a single-file Python budget planner using only the standard library that exposes a function named `calculate_budget_balance(income: float, expenses: list[float]) -> float` and a minimal CLI entrypoint.
Constraints: Python 3.10+, production-ready dependencies, licensing suitable for open-source or commercial distribution
    Target module: Not specified
Task: {_ARCHITECT_TASK_DESCRIPTION}

Provide a detailed architecture document.
    Respect the task scope exactly: if the requested deliverable is a single Python module, the architecture must describe a single-module design.
    If a target module is provided, document only that one file and do not include a package tree.
    Prefer one cohesive public service surface plus domain models over separate helper interfaces for scoring, logging, or batch processing.
    Do not introduce standalone RiskScorer, AuditLogger, BatchProcessor, Manager, or Processor collaborators unless the task explicitly requires those public types.
    If you describe typed entities or dataclasses, list required fields before defaulted fields and mark defaulted fields explicitly so the document does not imply an invalid constructor order.
    If a task-level public contract anchor is provided, preserve every listed facade, model, method, and constructor field name exactly.
    Do not rename anchored symbols, invent aliases, or introduce alternate public entrypoints that compete with the anchor.
    If the broader task wording and the task-level public contract anchor pull in different directions, keep the anchor exact and adjust the rest of the architecture around it."""


# ---------------------------------------------------------------------------
# Ollama direct client
# ---------------------------------------------------------------------------

def _call_ollama(
    base_url: str,
    model: str,
    system_prompt: str,
    user_message: str,
    num_ctx: int,
    timeout: float,
    think: bool | None = None,
) -> dict[str, Any]:
    """Call Ollama /api/generate directly and return timing + metadata."""
    endpoint = f"{base_url.rstrip('/')}/api/generate"
    payload: dict[str, Any] = {
        "model": model,
        "system": system_prompt,
        "prompt": user_message,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_ctx": num_ctx,
        },
    }
    if think is not None:
        payload["think"] = think
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    wall_start = perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            wall_end = perf_counter()
    except (TimeoutError, socket.timeout) as exc:
        wall_end = perf_counter()
        return {
            "model": model,
            "status": "timeout",
            "wall_time_s": round(wall_end - wall_start, 3),
            "error": str(exc),
        }
    except (HTTPError, URLError, OSError) as exc:
        wall_end = perf_counter()
        return {
            "model": model,
            "status": "error",
            "wall_time_s": round(wall_end - wall_start, 3),
            "error": str(exc),
        }
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "model": model,
            "status": "json_error",
            "wall_time_s": round(wall_end - wall_start, 3),
            "error": str(exc),
        }
    prompt_tokens = data.get("prompt_eval_count")
    output_tokens = data.get("eval_count")
    total_tokens = (prompt_tokens or 0) + (output_tokens or 0) if (prompt_tokens or output_tokens) else None
    total_duration_ms = (
        round(data["total_duration"] / 1_000_000, 1) if isinstance(data.get("total_duration"), (int, float)) else None
    )
    load_duration_ms = (
        round(data["load_duration"] / 1_000_000, 1) if isinstance(data.get("load_duration"), (int, float)) else None
    )
    response_text = data.get("response", "")
    return {
        "model": model,
        "status": "ok",
        "wall_time_s": round(wall_end - wall_start, 3),
        "prompt_chars": len(system_prompt) + len(user_message),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "total_duration_ms": total_duration_ms,
        "load_duration_ms": load_duration_ms,
        "done_reason": data.get("done_reason"),
        "response_chars": len(response_text),
        "response_snippet": (response_text[:200] + "...") if len(response_text) > 200 else response_text,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A/B wall-time measurement for Ollama models on the architect task prompt."
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=["qwen2.5-coder:7b", "qwen3.5:9b"],
        metavar="MODEL",
        help="Ordered list of Ollama model tags to test. Default: qwen2.5-coder:7b qwen3.5:9b",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:11434",
        help="Ollama base URL. Default: http://localhost:11434",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=4096,
        help="Ollama num_ctx context window. Default: 4096",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Per-model request timeout in seconds. Default: 300",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        metavar="PATH",
        help="Optional path to write the JSON report.",
    )
    parser.add_argument(
        "--think",
        choices=["true", "false", "default"],
        default="default",
        help=(
            "Ollama think parameter. 'default' omits it (model decides), "
            "'true' enables chain-of-thought, 'false' disables it. Default: default"
        ),
    )
    return parser


def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    system_prompt = _ARCHITECT_SYSTEM_PROMPT
    user_message = _ARCHITECT_USER_MESSAGE

    think: bool | None = None
    if args.think == "true":
        think = True
    elif args.think == "false":
        think = False

    print(f"Prompt sizes: system={len(system_prompt)} chars, user={len(user_message)} chars, total={len(system_prompt)+len(user_message)} chars")
    print(f"Estimated tokens (÷4): ~{(len(system_prompt)+len(user_message))//4}")
    print(f"num_ctx: {args.num_ctx}  |  timeout: {args.timeout}s  |  think: {args.think}  |  base_url: {args.base_url}")
    print()

    results: list[dict[str, Any]] = []
    for model in args.models:
        print(f"  [{model}] calling Ollama ...", flush=True)
        result = _call_ollama(
            base_url=args.base_url,
            model=model,
            system_prompt=system_prompt,
            user_message=user_message,
            num_ctx=args.num_ctx,
            timeout=args.timeout,
            think=think,
        )
        results.append(result)
        status = result["status"]
        if status == "ok":
            print(
                f"  [{model}] OK — wall={result['wall_time_s']}s  "
                f"prompt_tokens={result['prompt_tokens']}  output_tokens={result['output_tokens']}  "
                f"total_duration_ms={result['total_duration_ms']}  load_duration_ms={result['load_duration_ms']}  "
                f"done_reason={result['done_reason']}"
            )
            print(f"  [{model}] snippet: {result['response_snippet'][:120]}")
        elif status == "timeout":
            print(f"  [{model}] TIMEOUT after {result['wall_time_s']}s — {result['error']}")
        else:
            print(f"  [{model}] ERROR ({status}) after {result['wall_time_s']}s — {result['error']}")
        print()

    return results


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    results = run(args)

    if args.output_json:
        out = {
            "prompt_chars_system": len(_ARCHITECT_SYSTEM_PROMPT),
            "prompt_chars_user": len(_ARCHITECT_USER_MESSAGE),
            "prompt_chars_total": len(_ARCHITECT_SYSTEM_PROMPT) + len(_ARCHITECT_USER_MESSAGE),
            "num_ctx": args.num_ctx,
            "timeout_s": args.timeout,
            "base_url": args.base_url,
            "results": results,
        }
        import pathlib
        pathlib.Path(args.output_json).write_text(json.dumps(out, indent=2))
        print(f"Report written to {args.output_json}")

    any_ok = any(r["status"] == "ok" for r in results)
    sys.exit(0 if any_ok else 1)


if __name__ == "__main__":
    main()
