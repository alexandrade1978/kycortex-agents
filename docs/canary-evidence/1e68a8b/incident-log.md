# Incident Log - 1e68a8b

Status: open

No canary incident is recorded through the 25-workflows checkpoint.
No canary incident is recorded through the 50-workflows checkpoint.
No canary incident is recorded through the 100-workflows checkpoint.

## 2026-05-11T12:39:35Z - provider_transient incident on anthropic many_expenses

- batch: `canary_1e68a8b_smoke36`
- provider/scenario: `anthropic` / `many_expenses`
- severity after policy review: `SEV2`
- classification: `provider_transient`
- public symptom: Anthropic `arch` task failed before code-task validation with retryable `ProviderTransientError` while the paired OpenAI and Ollama daily-review cells continued cleanly
- terminal outcome: `failed`
- immediate canary impact: the daily-review slice retained one non-accepted workflow; final cumulative state after the paired fresh-root replay is `103/104` accepted workflows, `1` incident, and `0` rollbacks
- containment: a fresh-root targeted replay of the same provider/scenario pair (`canary_1e68a8b_smoke36_retry1`) passed cleanly at `2026-05-11T12:41:39Z`
- policy reading: isolated retryable incident remained inside the `>=95.0%` accepted-workflow SLO, below the `>50%` early-window burn threshold, and outside every zero-budget incident class
- immediate action after policy review: retain the incident evidence, continue daily-review observation, and treat repetition on the same provider/scenario pair as escalation input before any broader rollout claim

- 2026-05-11T12:58:41Z follow-up note: `canary_1e68a8b_smoke37` passed cleanly on all three providers, so the cumulative incident count remains `1` with no new canary incident introduced by the same-day follow-up review.

- 2026-05-12T10:52:48Z follow-up note: `canary_1e68a8b_smoke38` passed cleanly on all three providers during `daily-review day-2`, so the cumulative incident count remains `1` with no new canary incident introduced by the next-day review.

- 2026-05-13T19:52:04Z follow-up note: `canary_1e68a8b_smoke39` passed cleanly on all three providers during `daily-review day-3`, so the cumulative incident count remains `1` with no new canary incident introduced by the next-day review.

- 2026-05-14T14:20:59Z follow-up note: `canary_1e68a8b_smoke40` passed cleanly on all three providers during `daily-review day-4`, so the cumulative incident count remains `1` with no new canary incident introduced by the next-day review.

- 2026-05-15T16:08:20Z follow-up note: `canary_1e68a8b_smoke41` passed cleanly on all three providers during `daily-review day-5`, so the cumulative incident count remains `1` with no new canary incident introduced by the next-day review.

Update this file immediately if any later checkpoint or admitted workflow records a canary-impacting defect.