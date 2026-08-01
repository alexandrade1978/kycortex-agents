"""Auditor-facing evidence verification and export for persisted workflow state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from kycortex_agents.exceptions import StatePersistenceError
from kycortex_agents.memory.project_state import (
    compute_state_digest,
    verify_execution_event_chain,
)
from kycortex_agents.memory.state_store import _public_state_path_label, resolve_state_store
from kycortex_agents.orchestration.artifacts import ARTIFACT_MANIFEST_FILENAME

__all__ = ["export_evidence_bundle", "main", "verify_evidence"]

CHECK_PASSED = "passed"
CHECK_FAILED = "failed"
CHECK_SKIPPED = "skipped"

_BUNDLE_README = """# KYCortex Agents Evidence Bundle

This archive is a self-contained evidence bundle exported from a persisted
kycortex-agents workflow state.

## Contents

- `state.json`: the persisted workflow state payload, including its embedded
  `integrity` block (state digest and event-chain head).
- `state.sha256`: copy of the integrity sidecar written next to the original
  state file, when one was present at export time.
- `evidence_report.json`: run identity, workflow status, task outcomes, and
  execution-event summary extracted from the state payload.
- `verification_summary.json`: the result of every verification check executed
  at export time (state digest, event hash chain, sidecar, artifact manifest).
- `artifacts_manifest.json` and `artifacts/`: the artifact manifest and the
  artifact files it covers, when an artifacts directory was supplied.

## How to verify

Run the bundled state through the evidence verifier:

    python -m kycortex_agents.evidence verify <extracted>/state.json

The verifier recomputes the state digest, validates the tamper-evident
execution event chain, and, when given `--artifacts-dir`, recomputes the
SHA-256 digest of every artifact listed in the manifest.

## Scope

This bundle is operational workflow evidence produced by an automated system.
It is not a certified audit record and does not constitute legal advice.
"""


def _load_state_payload(state_file: str) -> Dict[str, Any]:
    payload = resolve_state_store(state_file).load(state_file)
    if not isinstance(payload, dict):
        raise StatePersistenceError(
            f"Project state data is invalid: {_public_state_path_label(state_file)}"
        )
    return payload


def _check_state_digest(payload: Dict[str, Any]) -> str:
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict):
        return CHECK_FAILED
    recorded = integrity.get("state_sha256")
    if not isinstance(recorded, str) or not recorded:
        return CHECK_FAILED
    content = {key: value for key, value in payload.items() if key != "integrity"}
    return CHECK_PASSED if compute_state_digest(content) == recorded else CHECK_FAILED


def _check_event_chain(payload: Dict[str, Any]) -> str:
    events = payload.get("execution_events")
    if not isinstance(events, list):
        return CHECK_FAILED
    if not verify_execution_event_chain(events):
        return CHECK_FAILED
    integrity = payload.get("integrity")
    recorded_head = integrity.get("event_chain_head") if isinstance(integrity, dict) else None
    actual_head = None
    for event in reversed(events):
        event_hash = event.get("event_hash") if isinstance(event, dict) else None
        if isinstance(event_hash, str) and event_hash:
            actual_head = event_hash
            break
    if recorded_head is None:
        return CHECK_PASSED
    return CHECK_PASSED if recorded_head == actual_head else CHECK_FAILED


def _check_sidecar(state_file: str, payload: Dict[str, Any]) -> str:
    sidecar_path = f"{state_file}.sha256"
    if not os.path.exists(sidecar_path):
        return CHECK_SKIPPED
    try:
        with open(sidecar_path, encoding="utf-8") as file_handle:
            recorded = file_handle.read().split()
    except OSError:
        return CHECK_FAILED
    if not recorded:
        return CHECK_FAILED
    integrity = payload.get("integrity")
    embedded = integrity.get("state_sha256") if isinstance(integrity, dict) else None
    return CHECK_PASSED if recorded[0] == embedded else CHECK_FAILED


def _check_artifact_manifest(artifacts_dir: Optional[str]) -> str:
    if artifacts_dir is None:
        return CHECK_SKIPPED
    manifest_path = os.path.join(artifacts_dir, ARTIFACT_MANIFEST_FILENAME)
    try:
        with open(manifest_path, encoding="utf-8") as file_handle:
            manifest = json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return CHECK_FAILED
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if not isinstance(entries, dict):
        return CHECK_FAILED
    for relative_path, entry in entries.items():
        if not isinstance(entry, dict):
            return CHECK_FAILED
        artifact_path = os.path.join(artifacts_dir, relative_path)
        try:
            with open(artifact_path, "rb") as file_handle:
                digest = hashlib.sha256(file_handle.read()).hexdigest()
        except OSError:
            return CHECK_FAILED
        if digest != entry.get("sha256"):
            return CHECK_FAILED
    return CHECK_PASSED


def verify_evidence(state_file: str, artifacts_dir: Optional[str] = None) -> Dict[str, Any]:
    """Verify state digest, event chain, sidecar, and artifact manifest for a persisted state."""

    payload = _load_state_payload(state_file)
    checks = {
        "state_digest": _check_state_digest(payload),
        "event_chain": _check_event_chain(payload),
        "integrity_sidecar": _check_sidecar(state_file, payload),
        "artifact_manifest": _check_artifact_manifest(artifacts_dir),
    }
    return {
        "state_file": _public_state_path_label(state_file),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "passed": all(status != CHECK_FAILED for status in checks.values()),
    }


def _build_evidence_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_tasks = payload.get("tasks")
    tasks = raw_tasks if isinstance(raw_tasks, list) else []
    raw_events = payload.get("execution_events")
    events = raw_events if isinstance(raw_events, list) else []
    raw_integrity = payload.get("integrity")
    integrity: Dict[str, Any] = raw_integrity if isinstance(raw_integrity, dict) else {}
    task_summaries = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_summaries.append(
            {
                "id": task.get("id"),
                "status": task.get("status"),
                "execution_mode": task.get("execution_mode"),
                "provider_call_count": len(task.get("provider_calls") or []),
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_name": payload.get("project_name"),
        "workflow_status": payload.get("phase"),
        "schema_version": payload.get("schema_version"),
        "run_identity": payload.get("run_identity"),
        "legal_hold": payload.get("legal_hold", False),
        "execution_event_count": len(events),
        "event_chain_head": integrity.get("event_chain_head"),
        "state_sha256": integrity.get("state_sha256"),
        "tasks": task_summaries,
        "disclaimer": (
            "Automated operational evidence generated by kycortex-agents. "
            "Not a certified audit record and not legal advice."
        ),
    }


def export_evidence_bundle(
    state_file: str,
    bundle_path: str,
    artifacts_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Export a self-contained evidence bundle zip and return the verification summary."""

    payload = _load_state_payload(state_file)
    summary = verify_evidence(state_file, artifacts_dir)
    bundle_dir = os.path.dirname(bundle_path)
    if bundle_dir:
        os.makedirs(bundle_dir, exist_ok=True)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("README.md", _BUNDLE_README)
        bundle.writestr("state.json", json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
        sidecar_path = f"{state_file}.sha256"
        if os.path.exists(sidecar_path):
            with open(sidecar_path, encoding="utf-8") as file_handle:
                bundle.writestr("state.sha256", file_handle.read())
        bundle.writestr(
            "evidence_report.json",
            json.dumps(_build_evidence_report(payload), indent=2, sort_keys=True, default=str) + "\n",
        )
        bundle.writestr(
            "verification_summary.json",
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
        )
        if artifacts_dir is not None:
            manifest_path = os.path.join(artifacts_dir, ARTIFACT_MANIFEST_FILENAME)
            if os.path.exists(manifest_path):
                with open(manifest_path, encoding="utf-8") as file_handle:
                    manifest_text = file_handle.read()
                bundle.writestr(ARTIFACT_MANIFEST_FILENAME, manifest_text)
                try:
                    manifest_entries = json.loads(manifest_text).get("entries", {})
                except json.JSONDecodeError:
                    manifest_entries = {}
                if isinstance(manifest_entries, dict):
                    for relative_path in manifest_entries:
                        artifact_path = os.path.join(artifacts_dir, relative_path)
                        if os.path.isfile(artifact_path):
                            bundle.write(artifact_path, os.path.join("artifacts", relative_path))
    try:
        os.chmod(bundle_path, 0o600)
    except OSError:
        pass
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    """Command-line entry point: verify persisted evidence or export an evidence bundle."""

    parser = argparse.ArgumentParser(
        prog="python -m kycortex_agents.evidence",
        description="Verify or export tamper-evident workflow evidence.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="Verify a persisted workflow state.")
    verify_parser.add_argument("state_file", help="Path to the persisted state file (.json or .sqlite).")
    verify_parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Workflow output directory containing artifacts_manifest.json to verify.",
    )
    export_parser = subparsers.add_parser("export", help="Export a self-contained evidence bundle zip.")
    export_parser.add_argument("state_file", help="Path to the persisted state file (.json or .sqlite).")
    export_parser.add_argument("bundle_path", help="Destination path for the evidence bundle zip.")
    export_parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Workflow output directory whose manifest and artifacts should be bundled.",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            summary = verify_evidence(args.state_file, args.artifacts_dir)
        else:
            summary = export_evidence_bundle(args.state_file, args.bundle_path, args.artifacts_dir)
    except (StatePersistenceError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
