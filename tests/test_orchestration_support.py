import os
import re
import stat

import pytest

from kycortex_agents.exceptions import AgentExecutionError
from kycortex_agents.orchestration.artifacts import ArtifactPersistenceSupport
from kycortex_agents.orchestration.private_files import (
	harden_private_directory_permissions,
	harden_private_file_permissions,
)
from kycortex_agents.types import ArtifactRecord, ArtifactType


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")
def test_harden_private_file_permissions_sets_mode_600(tmp_path):
	artifact_path = tmp_path / "artifact.txt"
	artifact_path.write_text("secret", encoding="utf-8")
	artifact_path.chmod(0o644)

	harden_private_file_permissions(artifact_path)

	assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")
def test_harden_private_directory_permissions_sets_mode_700(tmp_path):
	directory_path = tmp_path / "artifacts"
	directory_path.mkdir()
	directory_path.chmod(0o755)

	harden_private_directory_permissions(directory_path)

	assert stat.S_IMODE(directory_path.stat().st_mode) == 0o700


def test_artifact_persistence_support_redacts_and_updates_relative_path(tmp_path):
	support = ArtifactPersistenceSupport(output_dir=str(tmp_path / "output"))
	artifacts = [
		ArtifactRecord(
			name="Report Draft",
			artifact_type=ArtifactType.DOCUMENT,
			content="Authorization: Bearer sk-ant-secret-987654",
			path="reports/final draft.md",
		)
	]

	support.persist_artifacts(artifacts)

	persisted_path = tmp_path / "output" / "reports" / "final_draft.md"
	persisted_content = persisted_path.read_text(encoding="utf-8")

	assert artifacts[0].path == "reports/final_draft.md"
	assert artifacts[0].content == persisted_content
	assert persisted_content == "Authorization: Bearer [REDACTED]"


def test_artifact_persistence_support_rejects_symlink_escape(tmp_path):
	support = ArtifactPersistenceSupport(output_dir=str(tmp_path / "output"))
	escaped_root = tmp_path / "escaped"
	escaped_root.mkdir()
	(tmp_path / "output").mkdir()
	linked_dir = tmp_path / "output" / "artifacts"
	linked_dir.symlink_to(escaped_root, target_is_directory=True)
	artifacts = [
		ArtifactRecord(
			name="Report Draft",
			artifact_type=ArtifactType.DOCUMENT,
			content="hello",
			path="artifacts/final.md",
		)
	]

	with pytest.raises(AgentExecutionError, match="resolves outside the output directory"):
		support.persist_artifacts(artifacts)

	assert not (escaped_root / "final.md").exists()
	assert artifacts[0].path == "artifacts/final.md"


def test_artifact_persistence_support_rejects_invalid_segment_from_injected_sanitizer(tmp_path):
	def fake_sub(pattern: str, replacement: str, value: str) -> str:
		if value == "unsafe":
			return "."
		return re.sub(pattern, replacement, value)

	support = ArtifactPersistenceSupport(
		output_dir=str(tmp_path / "output"),
		sanitize_sub=fake_sub,
	)

	with pytest.raises(AgentExecutionError, match="artifact path contains an invalid segment"):
		support.sanitize_artifact_relative_path("reports/unsafe/summary.md")