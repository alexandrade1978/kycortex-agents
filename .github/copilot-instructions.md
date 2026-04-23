# Copilot Instructions

## Mandatory Documentation Discipline

Documentation updates are mandatory at every meaningful step, but each update must go to the correct document class.

- Before treating any meaningful step as complete, update the relevant documentation to reflect the current code, decisions, validation status, CI state, and operational risk.
- Do not defer documentation updates until the end of the task.
- If code changes, tests, lint results, CI outcomes, backup status, or implementation decisions change, the matching documentation must be updated in the same working slice.
- Keep related documents synchronized when one of them changes, but do not duplicate the same historical narrative across multiple files.
- Never consider a task finished, a checkpoint publishable, or a slice ready to hand off if the required documentation is stale.
- Local working notes under `.local-docs/` must stay untracked; update them when needed, but never stage or commit them.

## Document Taxonomy

Use the repository documents according to these roles.

### Public entry and release documents

- `README.md`: public product entry point only. Keep it focused on product positioning, installation, quick start, supported public runtime surface, and high-level release posture. Do not turn it into an operations log, canary diary, CI transcript, or branch-status journal.
- `docs/README.md`: public documentation index only. Keep it as a navigation page for stable public guides. Do not include rolling status, evidence history, operator workflow, or branch-maintenance narrative.
- `RELEASE_STATUS.md`: current release-state snapshot only. Keep it short and current. It may state the current published baseline, whether the branch is release-ready, and the next release-facing action. Do not store detailed historical timelines, empirical campaign logs, CI run lists, or canary incident narratives here.
- `RELEASE.md`: repository-owned package release procedure only. Keep it limited to validation, tagging, publish, and verification procedure. Do not use it as a go-live log or candidate history file.
- `CHANGELOG.md`: release-facing product and repository change history only. Do not use it as a working notebook.
- `MIGRATION.md`: user upgrade guidance only.

### Public guides under `docs/`

- `docs/architecture.md`: stable architecture, boundaries, and supported extension seams only. Do not describe the current branch as having just completed or still undergoing a specific refactor slice.
- `docs/providers.md`: public provider configuration and behavior only. Avoid repository-local validation diary content, benchmark storytelling, and host-specific operational commentary.
- `docs/workflows.md`: public workflow behavior and supported runtime semantics only. Avoid campaign narration and local maintenance notes.
- `docs/persistence.md`: public persistence and snapshot semantics only. Internal telemetry may be described only as a supported boundary, never as an operator runbook.
- `docs/extensions.md`: supported extension surface only.
- `docs/troubleshooting.md`: public failure classes, diagnosis, and recovery guidance only.
- `docs/go-live-policy.md`: policy only. Keep it abstract and decision-oriented. Do not append historical candidate bundles, past abort chronologies, or host-specific evidence references.

### Repository-owned operational and historical material

- `docs/canary-operations.md`: repository-owned operational runbook, not a primary public product guide.
- `docs/canary-evidence/**`: repository-owned historical evidence, not a primary public product guide.
- Do not surface operational canary runbooks or evidence bundles as core public entry points from `README.md` or `docs/README.md` unless the specific task is release or canary operations.

### Local operational notes under `.local-docs/`

- `.local-docs/plan.md`: current plan only. Keep it short. It must contain the active objective, current slice, next 1 to 3 steps, blockers, current validation state, and a safe restart point. Do not append full historical narratives here.
- `.local-docs/context.md`: current operational context only. Keep it short and current: active branch state, important constraints, open risks, and the immediate working set. Do not use it as a chronological activity log.
- `.local-docs/evolution-log.md`: append-only detailed change log for local reasoning, decisions, validation checkpoints, and chronology.
- `.local-docs/history.md`: macro project milestones only.
- `.local-docs/roadmap.md`: medium and long horizon work only.
- `.local-docs/campaign.md`: empirical campaign records only.
- `.local-docs/usb-backup.md`: backup runbook, current backup expectations, last verified status, and recovery/troubleshooting notes.
- `.local-docs/release-checklist.md`: internal release-preparation checklist only.

## Public Versus Internal Boundary Rules

Do not leak internal operational detail into public-facing documents.

- Public docs must not contain branch-only diary language such as "current head completed", "this branch is now in", or similar local maintenance narration.
- Public docs must not accumulate CI run identifiers, local hostnames, operator names, private paths, workspace-specific file locations outside the repository, or rolling incident transcripts.
- Public docs must not act as empirical evidence bundles. Historical empirical detail belongs in dedicated historical or local records, not in public entry pages.
- Public docs may describe supported public APIs and supported internal boundaries at a high level, but must not become operator playbooks.
- If a document contains both policy and history, split the history out or delete it from the public document.

## Working-Note Hygiene

- `plan.md` and `context.md` must be rewritten in place when the active state changes; do not keep stacking stale entries below the live state.
- Detailed chronology belongs in `evolution-log.md`, not in `plan.md` or `context.md`.
- When a slice ends, record the durable details once in the correct historical file instead of echoing the same checkpoint across multiple `.local-docs` files.

## Backup Safety Gate

Backups are a release-blocking operational safety dependency for long or risky sessions.

- Before starting or continuing a meaningful slice, verify that the local USB backup system has a recent successful run when that infrastructure is available on the host.
- Treat the backup system as the combination of the external script, the user `systemd` service, the user `systemd` timer, and the backup log; do not assume the timer is healthy without evidence.
- Record the latest verified backup status and any detected issue in `.local-docs/usb-backup.md`.
- If the backup freshness is stale or the timer appears stopped, stop widening the worktree, report the risk clearly, and prioritize diagnosis or user confirmation before continuing large edits.

## Checkpoint Publication Discipline

Validated slices should not accumulate locally without control.

- Each meaningful validated slice should end with a commit and push unless the user explicitly asked not to publish yet or a concrete blocker prevents publication.
- If a validated slice cannot be committed or pushed, record that blocker immediately in `.local-docs/plan.md` and `.local-docs/context.md` before continuing.
- Do not silently stack multiple large validated slices in the worktree.
- Before starting a new slice, check whether older validated local changes are still unpublished and surface that risk explicitly.

## Language

- Reply to the user in Portuguese.
- Write source code, code comments, commit messages, Markdown, plans, runbooks, and project documentation in English unless the user explicitly requests another language for the generated artifact.
