# Persistence Guide

This guide explains how workflow state is persisted in `kycortex-agents`, how the built-in backends are selected, and how persisted state supports resume, inspection, and backward-compatible reload.

## Persistence Model

`ProjectState` is the public workflow state object. It owns the mutable state that changes while a workflow runs:

- task definitions and lifecycle status
- retry counts, errors, timestamps, and transition history
- structured task outputs and provider-call metadata
- project-level decisions, artifacts, and execution events
- workflow lifecycle timestamps such as started, finished, resumed, and updated times
- run-identity provenance captured when a workflow execution starts

`ProjectState.save()` serializes that state through the configured state-store backend, and `ProjectState.load(path)` restores it into the current runtime dataclasses.

Exact resume semantics stay in `ProjectState` plus the selected state-store payload. `ProjectSnapshot` is rebuilt from that state as a public normalized read model rather than serving as the authoritative checkpoint format.

The configured `output_dir` is related but separate: it is the root used for persisted task artifacts and validation files, and it is created lazily when the runtime first needs to write there.

## Backend Selection

The built-in backend is selected by the `state_file` path extension through `resolve_state_store(path)`.

- `.json` uses `JsonStateStore`
- `.sqlite` and `.db` use `SqliteStateStore`
- any other extension falls back to `JsonStateStore`

This keeps backend selection explicit without adding another configuration switch.

## JSON Backend

`JsonStateStore` is the lightweight file-based backend.

- saves project state as formatted JSON
- creates missing parent directories automatically
- writes to a temporary file first and replaces the target atomically
- raises `StatePersistenceError` for missing files, invalid JSON, or failed writes

This backend is the simplest choice for local development and inspection because the state file remains directly readable.

## SQLite Backend

`SqliteStateStore` is the durable transactional backend.

- stores the latest serialized payload in a `project_state` table
- overwrites the single canonical row transactionally
- creates missing parent directories automatically
- raises `StatePersistenceError` for missing files, invalid schema, SQLite errors, or malformed persisted payloads

This backend is useful when consumers want a more durable local store without introducing external infrastructure.

## Save And Load Lifecycle

The normal persistence lifecycle is:

1. create a `ProjectState` with a chosen `state_file`
2. execute work through `Orchestrator`
3. let the runtime call `project.save()` after task and workflow transitions
4. reload with `ProjectState.load(path)` when execution needs to resume or state needs to be inspected later

Example:

```python
from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task

config = KYCortexConfig(output_dir="./output")
project = ProjectState(
    project_name="Demo",
    goal="Build demo",
    state_file="./state/project_state.sqlite",
)

project.add_task(
    Task(
        id="arch",
        title="Architecture",
        description="Design the system architecture",
        assigned_to="architect",
    )
)

Orchestrator(config).execute_workflow(project)

reloaded = ProjectState.load("./state/project_state.sqlite")
snapshot = reloaded.snapshot()
```

## Resume And Recovery

Persistence is what makes resume behavior deterministic across processes.

- `resume_interrupted_tasks()` re-queues tasks that were left in `RUNNING`
- `resume_failed_tasks()` re-queues failed tasks and dependency-skipped descendants when `workflow_resume_policy="resume_failed"`
- `skip_dependent_tasks()` records dependency-driven skips so downstream resume behavior can distinguish them from manual skips

`Orchestrator.execute_workflow()` applies these hooks before normal scheduling begins, then keeps saving state after retries, failures, skips, and completions.

## Snapshot Inspection

`ProjectState.snapshot()` returns a normalized `ProjectSnapshot` built from persisted state.

It is the public read model for inspection code. Prompt-facing agent context is derived from `AgentView`, not from serializing the raw snapshot.

That snapshot exposes:

- `task_results` with `TaskResult`, `AgentOutput`, `FailureRecord`, and coarse public detail flags that preserve supported product-level signals without a separate public `resource_telemetry` surface
- normalized `DecisionRecord` and `ArtifactRecord` collections
- workflow lifecycle timestamps and overall `WorkflowStatus`
- durable execution-event audit trails for workflow and task transitions, including public workflow lifecycle details without embedded workflow telemetry

This is the preferred public read model for inspection code because it normalizes legacy payloads and backend-specific storage details. It is not the operator telemetry surface: exact workflow and task runtime telemetry lives behind `ProjectState.internal_runtime_telemetry()`, and public `workflow_telemetry`, public `resource_telemetry`, and public execution-event telemetry echoes are not part of the supported public contract.

`ProjectState.internal_runtime_telemetry()` is now the dedicated internal read path for operator and UI telemetry. It preserves exact per-task provider/model identities, usage, durations and latencies, repair-budget counters, and richer provider-health data without widening the public snapshot contract.

Repository-owned internal operator surfaces can layer read-only adapters over `ProjectState.load(...)` plus `ProjectState.internal_runtime_telemetry()` when they need panel-ready workflow, task, repair/resume, or provider-health views. That adapter layer is an internal composition detail, not a public snapshot contract.

## Legacy Compatibility

`ProjectState.load()` normalizes older persisted payloads so the runtime can keep loading historical state files.

Current compatibility behavior includes:

- inferring missing decision timestamps
- filling missing artifact timestamps deterministically
- preserving legacy string-only artifacts
- reconstructing structured outputs when only raw task text exists
- inferring legacy skip-reason types when older state files predate explicit skip metadata
- filtering malformed persisted decision and output entries instead of crashing snapshot reconstruction

This keeps the persistence layer tolerant of earlier saved states while still exposing the current public snapshot model.

When artifacts are persisted, the runtime also validates that every resolved artifact path stays inside `output_dir`, including through symlinked directories. This prevents persisted artifacts from escaping the configured output root.

## Execution Provenance

Persisted state records provenance metadata that supports later inspection of who ran a workflow and in what order events happened.

- `run_identity` is captured every time a workflow execution starts: an opaque `run_id`, the OS user, hostname, process id, package and Python versions, platform label, start timestamp, and clock metadata (wall-clock source, UTC timezone, and an `ntp_verified: false` marker signalling that clock trust is not independently attested).
- Every execution event carries a monotonic `sequence` number so event ordering no longer depends on list position or wall-clock comparisons. Legacy state files are backfilled with positional sequence numbers on load.
- Each finished task records an `execution_mode`: `provider` when a real provider call produced the output, `deterministic` when no provider call was involved (custom or scripted agents), and `manual_override` for operator-completed tasks. This keeps simulated or scripted runs distinguishable from real provider-backed runs in the persisted evidence.

Provenance metadata describes the recording environment; it is not a tamper-evidence or attestation mechanism on its own.

## Provider Call History

Each task keeps an append-only `provider_calls` list recording every provider call made during its execution, across retries and repair attempts.

- Every entry carries the call target (provider, model), outcome (`success`), duration, attempt counters, a per-agent `call_index`, and a `recorded_at` UTC timestamp. Entries are appended for failed calls as well as successful ones, so retried tasks preserve the full attempt trail instead of only the final call.
- `last_provider_call` remains available as a derived view of the most recent call for backward compatibility.
- Entries are sanitized according to `KYCortexConfig.evidence_sanitization_mode`:
  - `strict` (default): current behavior — error text and fallback model names are degraded to boolean presence flags.
  - `audit`: preserves the redacted error class and error message text plus fallback model names for evidence-grade histories. Secrets are redacted in both modes.
- `KYCortexConfig.evidence_capture_prompts` (default `False`) opts in to capturing the redacted system prompt, user message, and raw provider response for each call. Captured text is truncated to `evidence_prompt_capture_max_chars` characters (default 20000) and stores the original length and a truncation flag.
- Replaying a workflow clears each task's `provider_calls`; manual overrides and resumes preserve the accumulated history.

Prompt capture stores model inputs and outputs in the persisted state file; enable it only when the storage location satisfies your data-handling requirements.

## State Integrity Digest

Every `ProjectState.save()` embeds an `integrity` block in the persisted payload and writes a `<state_file>.sha256` sidecar next to the state file.

- The digest is a SHA-256 hash of the canonical JSON payload (sorted keys, compact separators), excluding the `integrity` block itself. For the SQLite backend the digest covers the stored payload, not the raw database file bytes.
- `verify_persisted_state_integrity(path)` recomputes the digest and returns whether it matches the recorded value; it returns `False` when the state was modified after saving or carries no integrity block (states saved by older versions).
- Generated workflow artifacts get a companion `artifacts_manifest.json` at the output-directory root with the SHA-256 digest, byte size, name, and type of every persisted artifact file.

The digest detects post-save modification of state content; it does not by itself prove who modified a file or prevent an attacker from recomputing digests. Event hash chaining (below) adds tamper evidence for the execution timeline.

## Event Hash Chaining

Execution events recorded by `ProjectState` form a tamper-evident hash chain.

- Each new event carries a `prev_hash` (the `event_hash` of the previous hashed event, or a genesis value of 64 zeros for the first one) and an `event_hash` computed as the SHA-256 of the canonical JSON of the event excluding `event_hash` itself.
- The integrity block persisted on save records the chain head as `event_chain_head`, binding the timeline to the state digest.
- `verify_execution_event_chain(events)` validates an in-memory event list; `verify_persisted_event_chain(path)` loads a persisted state and validates both the chain and the recorded chain head.
- Events recorded by older package versions carry no hashes. They are accepted only as a contiguous prefix before the chain starts; the chain is never backfilled onto legacy events, and once a hashed event appears every later event must be hashed and linked.

Editing any hashed event after the fact breaks verification for that event and every event after it.

## Snapshot History

Versioned snapshot history is opt-in via `ProjectState.snapshot_history_limit` (default `0`, disabled).

- When the limit is greater than zero, every `save()` also appends a full point-in-time copy of the persisted payload to the snapshot history, then prunes the oldest entries beyond the limit.
- The JSON backend stores snapshots as files under a `<state_file>.history/` directory; the SQLite backend appends rows to a `project_state_history` table in the same database.
- `list_state_snapshots(path)` returns available versions with timestamps; `load_state_snapshot(path, version)` returns the raw payload of a specific version, or raises `StatePersistenceError` for unknown versions.
- Snapshots are complete payloads: each one carries its own integrity digest and event chain, so a restored snapshot remains independently verifiable.
- Pruning removes only old snapshot copies; it never truncates or rewrites the execution event chain inside the live state.

The latest state remains the fast path: snapshot history never changes how `ProjectState.load()` resolves the current state.

## Retention And Legal Hold

Snapshot retention is governed by `snapshot_history_limit` and can be suspended with a legal hold.

- `ProjectState.legal_hold` (default `False`) marks the state as under preservation. While it is `True`, every save still appends a snapshot, but retention pruning is suspended: no snapshot history is deleted for either backend.
- Releasing the hold (setting `legal_hold = False`) resumes normal retention on the next save; accumulated snapshots beyond the limit are then pruned.
- The marker is persisted with the state and survives save/load round-trips, so a hold placed on a workflow remains effective across process restarts.
- Legal hold governs snapshot pruning only. It does not freeze the live state file, and it never affects the execution event chain, which is append-only in all modes.

## Evidence Verification And Export

The package ships an auditor-facing command line interface:

```bash
python -m kycortex_agents.evidence verify <state_file> [--artifacts-dir DIR]
python -m kycortex_agents.evidence export <state_file> <bundle.zip> [--artifacts-dir DIR]
```

`verify` recomputes and reports four checks, printing a JSON summary:

- `state_digest`: the embedded integrity digest matches the recomputed canonical payload hash.
- `event_chain`: the execution event hash chain is intact and matches the recorded `event_chain_head`.
- `integrity_sidecar`: the `<state_file>.sha256` sidecar matches the embedded digest (`skipped` when no sidecar exists).
- `artifact_manifest`: with `--artifacts-dir`, every artifact listed in `artifacts_manifest.json` re-hashes to its recorded SHA-256 (`skipped` without the flag).

Exit codes are CI-friendly: `0` when all checks pass or are skipped, `1` when any check fails, `2` on usage or file errors.

`export` writes a self-contained evidence bundle zip containing the state payload, the integrity sidecar, an evidence report (run identity, task outcomes, chain head), the verification summary computed at export time, and — when `--artifacts-dir` is given — the artifact manifest plus the artifact files it covers. A bundled README documents the contents and how to re-verify them. The exit code reflects the verification outcome, and a bundle is written even when verification fails so failing evidence can still be preserved.

The same functionality is available programmatically as `kycortex_agents.evidence.verify_evidence` and `kycortex_agents.evidence.export_evidence_bundle`. Exported bundles are operational evidence generated by an automated system; they are not certified audit records and do not constitute legal advice.

## Advisory File Locking

On POSIX systems, `save()` and `load()` take an advisory `fcntl` lock on a `<state_file>.lock` companion file (exclusive for writes, shared for reads).

- The lock serializes concurrent savers on the same host and prevents a reader from observing a mid-save sequence of state, sidecar, and snapshot writes.
- The lock is advisory: it protects cooperating `kycortex-agents` processes, not arbitrary external writers, and it does not span network filesystems reliably.
- The supported concurrency contract remains single-writer: one workflow process owns a given state file at a time. Locking is a safety net, not a multi-writer feature.
- On non-POSIX platforms the lock is a no-op and the single-writer contract must be enforced operationally.

## Failure Modes

Persistence failures are normalized into `StatePersistenceError`.

Common failure cases include:

- loading a missing state file
- loading invalid JSON
- loading invalid SQLite schema or malformed SQLite payloads
- write failures during atomic replacement

These failures are intentional hard stops because continuing with corrupted workflow state would be less safe than surfacing the persistence problem directly.

## Common Patterns

- Use JSON when human-readable local state matters most.
- Use SQLite when you want durable local storage with transactional replacement semantics.
- Set `state_file` explicitly instead of relying on the default filename when multiple workflows or tests may run in the same workspace.
- Do not rely on `KYCortexConfig` initialization as an output-directory side effect; `output_dir` appears when the first persisted artifact or validation file is written.
- Inspect persisted runs through `snapshot()` rather than directly decoding raw task payloads.
- Combine a persisted state file with `workflow_resume_policy="resume_failed"` when workflows should recover from terminal task failures on a later run.