# Decisions Log

This file documents (1) the risk-ranking weight configuration and why those
values were chosen, (2) the actual reviewer decisions made during the
reference run against `sample_target_repo/` (with overrides and reasoning),
and (3) the key engineering decisions behind the implementation, for anyone
auditing *why* the system behaves the way it does rather than just *what*
it does.

## 1. Risk-ranking weight configuration

`config/risk_weights.yaml`:

```yaml
weights:
  change_frequency: 0.4
  complexity: 0.3
  coverage_gap: 0.3
```

```
risk_score = 0.4 * normalize(log(change_frequency))
           + 0.3 * normalize(log(cyclomatic_complexity))
           + 0.3 * coverage_gap
```

**Why change_frequency gets the largest weight (0.4):** the project
scenario (a production bug in an untested branch that had changed 12 times
in a quarter) is specifically about regression risk from *churn*, not just
complexity or raw coverage. A function that changes constantly is the one
most likely to have a recent, untested edge case - complexity and coverage
gap matter, but churn is the strongest leading indicator of *when* the next
regression lands.

**Why complexity and coverage_gap are weighted equally (0.3 each):** a
highly complex function is harder to reason about and more likely to hide
an untested branch, but a simple function with a real coverage gap is still
a real gap. Weighting them equally avoids letting either signal dominate
the other.

**Why log-scale + min-max normalize change_frequency and complexity, but
not coverage_gap:** change frequency and complexity are open-ended counts
(a function could change 50 times, or have complexity of 20) - log-scaling
compresses outliers before min-max normalizing across the candidate set so
one extreme value doesn't swamp the score. `coverage_gap` is already a
clean `[0, 1]` fraction and needs no transformation.

These weights are a starting point, not a universal constant - a team with
a history of complexity-driven bugs (vs. churn-driven ones) should raise
`complexity` and lower `change_frequency` in `config/risk_weights.yaml`
accordingly. See README "Known Limitations" for where this heuristic can
mislead.

## 2. Reviewer decisions log (reference run)

Run against `sample_target_repo` on 2026-11-25, reviewer: Abhishek Bhawsar.
Full machine-readable record: `audit/generation_audit_log.json` and
`data/audit_log.jsonl`. Risk ranking for this run:

| Rank | Function | Risk Score | Change Freq | Complexity | Coverage Gap |
|---|---|---|---|---|---|
| 1 | `billing/discounts.py::apply_discount` | 0.927 | 4 | 3 | 100% |
| 2 | `billing/discounts.py::bulk_discount_rate` | 0.777 | 2 | 4 | 100% |
| 3 | `billing/discounts.py::coupon_discount_rate` | 0.610 | 2 | 2 | 100% |
| 4 | `inventory/stock.py::reorder_point` | 0.527 | 1 | 3 | 100% |
| 5 | `billing/calculator.py::calculate_total` | 0.313 | 1 | 3 | 29% |
| 6 | `inventory/stock.py::is_low_stock` | 0.300 | 1 | 1 | 100% |

Decisions:

| Function | Draft generated as | Decision | Override / reasoning |
|---|---|---|---|
| `apply_discount` | template TODO stub (no `ANTHROPIC_API_KEY` configured) | **Edited** | Stub replaced with real assertions covering stacking, the non-stacking mode, and the 50% cap. First edit still tripped the low-value detector (`pytest.raises` with no message check on the negative-subtotal case) - fixed by asserting on the exception message before approving. |
| `bulk_discount_rate` | template TODO stub | **Edited** | Replaced with explicit tier-boundary assertions (`5→0%, 10→5%, 50→10%, 100→15%`). |
| `coupon_discount_rate` | template TODO stub | **Edited** | Replaced with assertions for known codes, the case-insensitivity fix, unknown codes, and `None`. |
| `reorder_point` | template TODO stub | **Edited** | Replaced with a real expected-value assertion and an exception-message check. |
| `calculate_total` | template TODO stub | **Rejected** | Reviewer override: lower risk this sprint (rank 5, smallest coverage gap at 29%); an existing happy-path test already covers most of it. Deferred, not ignored - it stays in the next risk report since it's still untested. |
| `is_low_stock` | template TODO stub | **Rejected** | Reviewer override: a one-line, complexity-1 function; not worth a generated test right now despite 100% coverage gap - this is exactly the kind of low-complexity, low-churn gap the risk ranking is designed to *de-prioritize* versus `discounts.py`. |

Net effect: 4 of 6 drafts applied, coverage on the seed repo went from
23.9% to 93.5%, counted only from the applied (approved/edited) tests. No
draft was auto-merged; every one of the six went through an explicit human
decision recorded above and in the audit log.

## 3. Key engineering decisions

- **Python track, not Java.** Either is supported by the assessment; Python
  was chosen for a lighter dependency footprint (pytest/coverage.py are
  stdlib-adjacent) and because LangGraph/LangFuse are Python-native.
- **`git` CLI via subprocess, not GitPython.** One less dependency; `git` is
  already a required tool for this track, and shelling out to a pinned set
  of read-only commands (`log`, `show`) is simple to audit.
- **Per-commit historical re-parsing for function-level change frequency**
  (`agents/history_analyzer.py`). An early version matched each commit's
  diff hunks against *today's* function line ranges and produced
  nonsensical results once the file had grown via later edits (a classic
  line-drift bug). Fixed by re-parsing the function spans from each
  commit's own blob and matching qualnames, not line numbers, across time.
- **AST-based complexity instead of a `radon` dependency**
  (`agents/complexity.py`). Small and auditable: a reviewer can read the
  ~40 lines and know exactly what "complexity" means here, rather than
  trusting a third-party library's definition.
- **Honest template fallback instead of a fabricated test when no LLM key
  is configured** (`agents/test_generator.py`). The fallback produces a
  clearly-labeled TODO stub (`# TODO(reviewer): ...`) rather than a test
  that merely imports the function and asserts nothing meaningful - the
  low-value detector then correctly flags it, so a reviewer is never
  given false confidence by a stub.
- **`langfuse>=3.0.0` is required, not `2.x`** (`core/tracing.py`). The
  package was originally pinned to `langfuse>=2.53.0,<3.0.0`. That SDK's
  `.trace()/.span()` API targets Langfuse's old (pre-OpenTelemetry) data
  model, which Langfuse Cloud deprecated and began removing in November
  2026 - read endpoints (`fetch_traces`, `fetch_observations`) now return
  `410 LANGFUSE_V3_API_REMOVED`, and since every call in `tracing.py` was
  wrapped in a broad `try/except Exception` (by design, so a tracing
  outage never breaks the pipeline), a failure there would have degraded
  silently to a no-op with no visible error - exactly the kind of gap this
  project's own audit trail is supposed to catch, just in a dependency
  instead of a test. Caught by directly authenticating against the live
  API (`Langfuse.auth_check()`) and querying the new
  `GET /api/public/v2/observations` endpoint for a real span after a run,
  rather than trusting "no exception was raised." Fixed by upgrading to
  `langfuse>=3.0.0,<5.0.0` and rewriting `core/tracing.py` against the
  current OpenTelemetry-based API (`start_as_current_observation(...)` as
  a context manager, in place of the old `StatefulTraceClient`).
  Re-verified end-to-end: 6 real `test_generation` traces from a live
  `analyze` run were fetched back via the v2 API by trace id.
- **A new constant needs a new test monkeypatch, every time.** Adding
  `audit_log.GENERATION_AUDIT_LOG_JSON_PATH` (for the export above) without
  also adding it to `tests/test_pipeline_simple_engine.py`'s isolation
  fixture meant that test was writing its synthetic fixture data
  (`pkg/mod.py`, reviewer `"test-reviewer"`) directly over the real
  `audit/generation_audit_log.json` on every `pytest` run - a real
  dependency-free-engine test polluting a tracked project file. Fixed by
  patching the new path alongside the others in that fixture, and
  confirmed fixed by hashing the file before and after a full test run.
- **Two orchestration engines, one set of step functions**
  (`workflow/pipeline.py` + `workflow/langgraph_orchestrator.py`). The
  LangGraph `StateGraph` with `interrupt()` + a SQLite checkpointer gives a
  genuine cross-process human-in-the-loop pause; a dependency-free
  sequential engine runs the identical step functions so the CLI still
  works end-to-end if `langgraph` isn't installed.
- **Credentials never enter persisted state.** `step_generate()` calls
  `Settings.from_env()` directly instead of threading API keys through the
  LangGraph checkpoint or the simple engine's JSON state file, so neither
  `data/graph_checkpoints.sqlite` nor `data/simple_pipeline_state.json` can
  ever leak a secret.
- **Conflict-safe apply, never silent overwrite** (`review/apply_tests.py`).
  If a generated test's target filename already exists with *different*
  content, it's reported as a conflict for manual resolution - never
  overwritten.
