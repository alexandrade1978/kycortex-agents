# Incident Log - 8bfdc29

Status: incident and rollback decision recorded

The canary window opened on `2026-04-13T00:56:30Z` and was aborted on `2026-04-13T01:34:53.543209+00:00`.

## Entries

- 2026-04-13T00:56:52.840533Z: No provider-health incident before traffic. OpenAI, Anthropic, and Ollama all reported `status=healthy` in the live preflight checkpoint.
- 2026-04-13T00:57:23.746148+00:00: No canary incident at the first controlled checkpoint. `release_user_smoke_openai` finished `completed`, remained externally valid, and did not trigger any rollback rule.
- 2026-04-13T01:34:53.543209+00:00: `SEV1` code-validation incident on controlled workflow `run_04_openai`. The workflow completed all 3 tasks internally, but `examples/example_release_user_smoke.py` rewrote the persisted result to `phase=failed`, `terminal_outcome=failed`, `failure_category=code_validation`, and `acceptance_criteria_met=false` because importing `artifacts/code_implementation.py` raised `ModuleNotFoundError: No module named 'click'`. Impact: accepted workflow rate fell to `75.0%` (3 of 4), missing the `>=95.0%` SLO and consuming more than half of the non-zero accepted-workflow error budget in the first half of the observation window. Containment: freeze canary expansion at 4 eligible workflows, stop admitting new traffic, and abort the current `v1.0.13a4` window while keeping rollback target `v1.0.13a2` pinned.