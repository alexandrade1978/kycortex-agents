# Evidence Semantics

This guide defines what evidence `kycortex-agents` records during workflow execution, what guarantees that evidence carries, what its limits are, and how to verify it.

## What Is Recorded

Every workflow run persists the following evidence inside the project state:

- **Run identity**: a unique run id, OS user, hostname, process id, package and Python versions, platform, and clock metadata (timezone, wall-clock and monotonic readings) captured when the workflow starts.
- **Execution events**: an append-only timeline of workflow and task lifecycle events, each carrying a monotonic `sequence` number and tamper-evident hash chaining (`prev_hash` and `event_hash`).
- **Execution mode per task**: whether a task result came from a live provider call (`provider`), a deterministic local run (`deterministic`), or a manual operator override (`manual_override`).
- **Provider call history per task**: an append-only `provider_calls` list covering every provider call across retries — target provider and model, outcome, duration, attempt counters, per-agent call index, and recorded-at timestamp. `last_provider_call` remains available as a derived view.
- **Integrity block**: a SHA-256 digest of the canonical state payload and the head of the event hash chain, embedded on every save, plus a `<state_file>.sha256` sidecar.
- **Artifact manifest**: an `artifacts_manifest.json` at the output-directory root recording the SHA-256 digest, byte size, name, and type of every persisted artifact file.

Optional evidence, disabled by default:

- **Prompt and response capture** (`evidence_capture_prompts` on `KYCortexConfig`): redacted, size-limited copies of the system prompt, user message, and raw provider response per call.
- **Snapshot history** (`ProjectState.snapshot_history_limit`): versioned point-in-time copies of the full state payload on every save, with retention pruning.

## Sanitization Modes

Provider call histories are sanitized before exposure, controlled by `evidence_sanitization_mode` on `KYCortexConfig`:

- `strict` (default): error details are reduced to presence flags and fallback model names are removed.
- `audit`: redacted error text and fallback model names are preserved so an audit trail keeps diagnostic value. Secrets are redacted in both modes.

Persisted state and reports declare that redaction was applied; redaction is always on and cannot be disabled.

## Guarantees

- **Post-save modification of state content is detectable.** The embedded digest and sidecar no longer match a modified payload, and `verify_persisted_state_integrity` returns `False`.
- **Reordering, editing, or deleting hashed execution events is detectable.** Each event is hash-linked to its predecessor from a genesis value; breaking any link fails `verify_execution_event_chain` and `verify_persisted_event_chain`.
- **Artifact substitution is detectable.** Any persisted artifact that no longer matches its manifest digest fails verification.
- **Provider history is append-only.** Retries never overwrite earlier call records; replaying a workflow clears history explicitly, while overrides and resumes preserve it.
- **Defaults are backward compatible.** States saved by older versions load with automatic schema migration; evidence recorded before hash chaining existed is accepted as a pre-chain prefix and is never retroactively hashed.

## Limits

Be explicit about what this evidence is **not**:

- **It is not a certified audit record.** The evidence is operational telemetry produced by an automated system; no external party attests to it.
- **Hashes prove integrity, not authorship.** There is no signing key: an attacker with write access to the state file could recompute digests and rebuild the chain. Tamper evidence protects against accidental or unsophisticated modification and supports detection workflows, not cryptographic non-repudiation.
- **Clock metadata is best-effort.** Timestamps come from the local system clock; NTP synchronization is not verified.
- **File locking is advisory and POSIX-only.** It serializes cooperating processes on one host; the supported contract is single-writer per state file.
- **Redaction is pattern-based.** It targets known secret shapes and sensitive keys; it cannot guarantee that free-form model output contains no sensitive data.
- **Legal outputs are not legal advice.** Legal-analysis artifacts are LLM-generated, carry an explicit disclaimer header, and require review by a qualified lawyer.

## Verification Workflow

Verify a persisted state and its artifacts:

```bash
python -m kycortex_agents.evidence verify output/project_state.json --artifacts-dir output
```

The command recomputes the state digest, validates the event hash chain against the recorded chain head, checks the integrity sidecar, and re-hashes every artifact in the manifest. Exit codes are CI-friendly: `0` all checks passed or skipped, `1` any check failed, `2` usage or file error.

Export a self-contained evidence bundle for an auditor:

```bash
python -m kycortex_agents.evidence export output/project_state.json evidence_bundle.zip --artifacts-dir output
```

The bundle contains the state payload, integrity sidecar, an evidence report, the verification summary computed at export time, the artifact manifest with its artifacts, and a README describing how to re-verify everything offline.

The same operations are available programmatically via `kycortex_agents.evidence.verify_evidence` and `kycortex_agents.evidence.export_evidence_bundle`, and the underlying primitives (`verify_persisted_state_integrity`, `verify_persisted_event_chain`, `list_state_snapshots`, `load_state_snapshot`) are public API.

## Retention And Legal Hold

Snapshot history retention is bounded by `snapshot_history_limit`. Setting `ProjectState.legal_hold = True` suspends snapshot pruning while preserving all other behavior; the marker persists with the state until explicitly released. Pruning never truncates the execution event chain. See [persistence.md](persistence.md) for the full persistence semantics.
