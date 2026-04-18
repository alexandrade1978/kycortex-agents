"""Validation-runtime helpers used by the Orchestrator facade."""

from __future__ import annotations

from typing import Any, Optional, cast

from kycortex_agents.providers.base import redact_sensitive_data, sanitize_provider_call_metadata
from kycortex_agents.types import AgentOutput


def summarize_pytest_output(stdout: str, stderr: str, returncode: int) -> str:
    combined_lines = [line.strip() for line in f"{stdout}\n{stderr}".splitlines() if line.strip()]
    if not combined_lines:
        return f"pytest exited with code {returncode}"
    for line in reversed(combined_lines):
        if line.startswith("=") or line.startswith("FAILED") or line.startswith("ERROR") or "passed" in line:
            return line
    return combined_lines[-1][:240]


def redact_validation_execution_result(result: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], redact_sensitive_data(result))


def sanitize_output_provider_call_metadata(output: AgentOutput) -> AgentOutput:
    provider_call = output.metadata.get("provider_call") if isinstance(output.metadata, dict) else None
    if not isinstance(provider_call, dict):
        return output
    output.metadata = dict(output.metadata)
    output.metadata["provider_call"] = sanitize_provider_call_metadata(provider_call)
    return output


def provider_call_metadata(agent: Any, output: Optional[AgentOutput] = None) -> Optional[dict[str, Any]]:
    if output is not None:
        output_provider_call = output.metadata.get("provider_call")
        if isinstance(output_provider_call, dict):
            return sanitize_provider_call_metadata(output_provider_call)
    getter = getattr(agent, "get_last_provider_call_metadata", None)
    if callable(getter):
        metadata = getter()
        if isinstance(metadata, dict):
            return sanitize_provider_call_metadata(metadata)
    return None