"""Artifact persistence helpers used by the Orchestrator facade."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.orchestration.private_files import (
    harden_private_directory_permissions,
    harden_private_file_permissions,
)
from kycortex_agents.providers.base import redact_sensitive_text
from kycortex_agents.types import ArtifactRecord, ArtifactType

SegmentSanitizer = Callable[[str, str, str], str]


def failed_artifact_content(
    output: object,
    output_payload: object,
    artifact_type: ArtifactType | None = None,
) -> str:
    if not isinstance(output_payload, dict):
        return output if isinstance(output, str) else ""
    artifacts = output_payload.get("artifacts")
    if not isinstance(artifacts, list):
        raw_content = output_payload.get("raw_content")
        if isinstance(raw_content, str):
            return raw_content
        return output if isinstance(output, str) else ""
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact_type is not None and artifact.get("artifact_type") != artifact_type.value:
            continue
        content = artifact.get("content")
        if isinstance(content, str) and content.strip():
            return content
    raw_content = output_payload.get("raw_content")
    if isinstance(raw_content, str):
        return raw_content
    return output if isinstance(output, str) else ""


@dataclass(frozen=True)
class ArtifactPersistenceSupport:
    """Persist artifacts safely within the configured output directory."""

    output_dir: str
    sanitize_sub: SegmentSanitizer = field(default=re.sub, repr=False, compare=False)

    def persist_artifacts(self, artifacts: list[ArtifactRecord]) -> None:
        for artifact in artifacts:
            content = artifact.content
            if not isinstance(content, str) or not content.strip():
                continue
            persisted_content = redact_sensitive_text(content)
            target_path = self.resolve_artifact_output_path(artifact)
            self.validate_artifact_output_path(target_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            harden_private_directory_permissions(target_path.parent)
            self.validate_artifact_output_path(target_path)
            target_path.write_text(persisted_content, encoding="utf-8")
            harden_private_file_permissions(target_path)
            artifact.content = persisted_content
            artifact.path = self.artifact_record_path(target_path)

    def resolve_artifact_output_path(self, artifact: ArtifactRecord) -> Path:
        output_root = self._output_root()
        relative_path = self.sanitize_artifact_relative_path(
            artifact.path if artifact.path else self.default_artifact_path(artifact)
        )
        return output_root / relative_path

    def validate_artifact_output_path(self, target_path: Path) -> None:
        output_root = self._output_root()
        resolved_target = target_path.resolve(strict=False)
        try:
            resolved_target.relative_to(output_root)
        except ValueError as exc:
            raise AgentExecutionError(
                "Artifact persistence failed: artifact path resolves outside the output directory"
            ) from exc

    def sanitize_artifact_relative_path(self, artifact_path: str) -> Path:
        candidate = Path(artifact_path)
        if candidate.is_absolute():
            raise AgentExecutionError("Artifact persistence failed: absolute artifact paths are not allowed")

        sanitized_parts: list[str] = []
        for part in candidate.parts:
            if part == "..":
                raise AgentExecutionError(
                    "Artifact persistence failed: parent-directory traversal is not allowed"
                )
            cleaned = self.sanitize_sub(r"[^A-Za-z0-9._-]+", "_", part).strip()
            if not cleaned or cleaned in (".", ".."):
                raise AgentExecutionError(
                    "Artifact persistence failed: artifact path contains an invalid segment"
                )
            sanitized_parts.append(cleaned)

        if not sanitized_parts:
            raise AgentExecutionError("Artifact persistence failed: artifact path must not be empty")

        return Path(*sanitized_parts)

    def artifact_record_path(self, target_path: Path) -> str:
        output_root = self._output_root()
        resolved_target = target_path.resolve()
        try:
            return str(resolved_target.relative_to(output_root))
        except ValueError:
            return str(resolved_target)

    @staticmethod
    def default_artifact_path(artifact: ArtifactRecord) -> str:
        suffix_map = {
            ArtifactType.DOCUMENT: ".md",
            ArtifactType.CODE: ".py",
            ArtifactType.TEST: ".py",
            ArtifactType.CONFIG: ".json",
            ArtifactType.TEXT: ".txt",
            ArtifactType.OTHER: ".artifact",
        }
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", artifact.name).strip("._") or "artifact"
        return f"artifacts/{safe_name}{suffix_map.get(artifact.artifact_type, '.artifact')}"

    def _output_root(self) -> Path:
        return Path(self.output_dir).resolve()