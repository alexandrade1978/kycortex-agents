# Environment Parity - 1e68a8b

Status: preflight parity captured; canary traffic admitted through daily-review day-1

## Candidate and Runtime

- candidate tag: `v1.0.13b2`
- candidate commit: `1e68a8bc8e6371b6b425e1ac9ce04e3677141628`
- parity capture time: `2026-05-11T11:02:46Z`
- execution host class: maintainer-operated pre-production runtime

## Provider Parity

- enabled providers for admitted evidence: `anthropic`, `openai`, `ollama`
- provider models used across smoke01-smoke36 and the targeted `smoke36_retry1` replay:
  - anthropic: `claude-haiku-4-5-20251001`
  - openai: `gpt-4o-mini`
  - ollama: `qwen2.5-coder:7b`
- the first thirty-five smoke batches completed with all admitted provider/scenario cells accepted, including repeated clean passes on the formerly held `anthropic=baseline` path and the two-provider `smoke35` close-out used to reach `100/100`.
- `smoke36` admitted the next rotated daily-review slice (`anthropic=many_expenses`, `openai=baseline`, `ollama=tight_margin`); OpenAI and Ollama passed on the first root, while Anthropic recorded a retryable `ProviderTransientError` before code-task validation and then passed cleanly on fresh-root replay `smoke36_retry1`.

## Persistence and Validation Parity

- persisted workflow state evidence is available under:
  - `output/canary_1e68a8b_smoke01/`
  - `output/canary_1e68a8b_smoke02/`
  - `output/canary_1e68a8b_smoke03/`
  - `output/canary_1e68a8b_smoke04/`
  - `output/canary_1e68a8b_smoke05/`
  - `output/canary_1e68a8b_smoke06/`
  - `output/canary_1e68a8b_smoke07/`
  - `output/canary_1e68a8b_smoke08/`
  - `output/canary_1e68a8b_smoke09/`
  - `output/canary_1e68a8b_smoke10/`
  - `output/canary_1e68a8b_smoke11/`
  - `output/canary_1e68a8b_smoke12/`
  - `output/canary_1e68a8b_smoke13/`
  - `output/canary_1e68a8b_smoke14/`
  - `output/canary_1e68a8b_smoke15/`
  - `output/canary_1e68a8b_smoke16/`
  - `output/canary_1e68a8b_smoke17/`
  - `output/canary_1e68a8b_smoke18/`
  - `output/canary_1e68a8b_smoke19/`
  - `output/canary_1e68a8b_smoke20/`
  - `output/canary_1e68a8b_smoke21/`
  - `output/canary_1e68a8b_smoke22/`
  - `output/canary_1e68a8b_smoke23/`
  - `output/canary_1e68a8b_smoke24/`
  - `output/canary_1e68a8b_smoke25/`
  - `output/canary_1e68a8b_smoke26/`
  - `output/canary_1e68a8b_smoke27/`
  - `output/canary_1e68a8b_smoke28/`
  - `output/canary_1e68a8b_smoke29/`
  - `output/canary_1e68a8b_smoke30/`
  - `output/canary_1e68a8b_smoke31/`
  - `output/canary_1e68a8b_smoke32/`
  - `output/canary_1e68a8b_smoke33/`
  - `output/canary_1e68a8b_smoke34/`
  - `output/canary_1e68a8b_smoke35/`
  - `output/canary_1e68a8b_smoke36/`
  - `output/canary_1e68a8b_smoke36_retry1/`
- every accepted run retained repository-owned artifacts, `acceptance_criteria_met=true`, and code-task validation metadata proving the task public-contract preflight and import checks passed.
- the only non-accepted admitted run in the active bundle is the retryable `anthropic=many_expenses` provider-transient failure inside `output/canary_1e68a8b_smoke36/`, which terminated before code-task validation and was replayed cleanly on `output/canary_1e68a8b_smoke36_retry1/`.

## Sandbox and Release Settings Parity

- release candidate identity is fixed to published `v1.0.13b2`
- admission runs use the repository-standard workflow generation and validation contracts
- no environment override is recorded at bundle-open time

## Gate Interpretation

Parity evidence remains sufficient to keep the replacement beta canary window open.
The `daily-review day-1` slice is now recorded with one recovered retryable provider incident and no environment drift; the next operational step is `daily-review day-2` while the minimum `7`-day window remains open.