# AI Test Coverage & Regression Risk Agent

Ranks untested code paths by **change frequency x complexity x coverage
gap** (not coverage gap alone), drafts candidate pytest tests for the
riskiest ones, and requires a human to approve, edit, or reject every
single draft before it ever touches the real test suite. Nothing auto-merges.

> **Data privacy note:** everything this repo analyzes is synthetic demo
> data (`sample_target_repo/`) created specifically for this exercise. Do
> not point it at real production code containing customer or confidential
> data without your own review of these privacy requirements.

## Why this exists

Coverage reports tell you *where* the gaps are, not which ones matter. A
rarely-touched utility function and a payment-calculation branch that
changes every sprint look identical on a coverage report - but only one of
them is likely to cause the next regression. This agent combines three
signals so the riskiest gaps surface first:

```
risk_score = w1 * normalize(log(change_frequency))
           + w2 * normalize(log(cyclomatic_complexity))
           + w3 * coverage_gap                      # already in [0, 1]
```

## Architecture

```
 git history ─┐
              ├─▶ analyze ─▶ rank ─▶ generate ─▶ human_review ─▶ apply ─▶ coverage_delta ─▶ report
 coverage.json┘                        │             │              │
                                   LangFuse       (interrupt,    only approved/
                                    traces         on-disk       edited drafts
                                                   review         ever written
                                                   queue)         to tests_dir
```

Orchestrated as a **LangGraph** `StateGraph` (`src/test_risk_agent/graph.py`)
with a genuine human-in-the-loop pause: the `human_review` node calls
`interrupt()`, backed by a SQLite checkpointer, so the pipeline really stops
- across separate CLI invocations/process runs - until a human has acted.

Every pipeline step is also a plain Python function in
`src/test_risk_agent/pipeline.py`, so the exact same logic runs through a
**dependency-free sequential engine** if `langgraph` isn't installed
(`--engine simple`, or automatic fallback). Both engines are tested.

## Project layout

```
src/test_risk_agent/
  analyzer.py          # walks source files, ties git history + coverage + complexity together
  git_history.py        # change-frequency via `git` CLI (no GitPython dependency)
  complexity.py          # AST-based function discovery + cyclomatic complexity
  coverage_ingest.py     # parses `coverage json` reports, maps lines -> functions
  risk_ranker.py         # combines the three signals into one score
  test_generator.py      # drafts pytest tests (LLM, with an honest template fallback)
  low_value_detector.py  # flags drafts with no real assertions
  review_queue.py        # the human review gate (on-disk JSON queue)
  apply_tests.py         # writes ONLY approved/edited drafts to the test suite
  coverage_delta.py      # re-runs coverage, reports the improvement
  audit_log.py           # append-only log: every draft <-> its risk score <-> its reviewer
  tracing.py             # LangFuse wrapper (safe no-op if not configured)
  pipeline.py            # the step functions, shared by both engines
  graph.py               # LangGraph wiring (StateGraph + interrupt + SqliteSaver)
  cli.py                 # `python -m test_risk_agent.cli ...`
sample_target_repo/      # synthetic seed repo used for the demo (see its own README)
tests/                   # 53 unit/integration tests for the agent itself
config/risk_weights.yaml # tune the three risk weights
```

## Setup

```bash
cd test-risk-agent
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash / macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                # fill in keys below if you have them - all optional
```

### Environment variables (`.env`, all optional)

| Variable | Purpose | If unset |
|---|---|---|
| `ANTHROPIC_API_KEY` | Lets Claude draft real test bodies | Falls back to an honest, clearly-labeled TODO template (never a fake passing test) |
| `ANTHROPIC_MODEL` | Model id (default `claude-sonnet-5`) | uses default |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Traces every generation call + review decision | Tracing becomes a safe no-op |
| `LANGFUSE_HOST` | Self-hosted LangFuse | defaults to LangFuse Cloud |
| `RISK_LOOKBACK_DAYS` / `RISK_TOP_N` | Tuning | 180 days / top 10 |

Never commit `.env` - it's already in `.gitignore`.

## Quickstart walkthrough

All commands assume `cd test-risk-agent && source .venv/Scripts/activate`.

```bash
# 1. Produce the input coverage report for the seed repo
python -m test_risk_agent.cli baseline

# 2. Analyze -> rank -> generate candidate tests, then pause for review
python -m test_risk_agent.cli analyze

# 3. Interactively approve / edit / reject each draft
python -m test_risk_agent.cli review

# 4. Resume: write approved/edited tests to the suite, measure the coverage
#    delta, and write the final report
python -m test_risk_agent.cli apply

# Anytime: check queue counts, or re-print the last report
python -m test_risk_agent.cli status
python -m test_risk_agent.cli report
```

Example output from a real run against `sample_target_repo` (see
`data/reports/latest_report.md` after you run it yourself):

| Rank | Function | Risk Score | Change Freq | Complexity | Coverage Gap |
|---|---|---|---|---|---|
| 1 | `billing/discounts.py::apply_discount` | 0.927 | 4 | 3 | 100% |
| 2 | `billing/discounts.py::bulk_discount_rate` | 0.777 | 2 | 4 | 100% |
| 3 | `billing/discounts.py::coupon_discount_rate` | 0.610 | 2 | 2 | 100% |
| 4 | `inventory/stock.py::reorder_point` | 0.527 | 1 | 3 | 100% |
| 5 | `billing/calculator.py::calculate_total` | 0.313 | 1 | 3 | 29% |
| 6 | `inventory/stock.py::is_low_stock` | 0.300 | 1 | 1 | 100% |

`billing/discounts.py` dominates the top of the ranking even though every
function above has a 100% coverage gap, because it is also the
highest-change-frequency, highest-complexity file - exactly the scenario
from the problem statement where a naive "largest coverage gap" sort would
have missed the actual regression risk.

After `review` + `apply` in that same run: 4 drafts were edited (by the
reviewer, adding real expected-value assertions) and applied, 2 were
rejected as lower priority, and overall coverage on the seed repo went from
**23.9% -> 93.5%** - counted only from the approved/edited tests, never the
rejected ones.

## Key features (mapped to the spec)

| Feature | Where |
|---|---|
| Risk-ranked untested path report | `risk_ranker.py`, `reporting.render_risk_table` |
| Candidate test generation (pytest) | `test_generator.py` |
| Human review queue (approve/edit/reject) | `review_queue.py`, `cli.py review` |
| Coverage delta (approved tests only) | `coverage_delta.py` - `apply_tests.py` only ever writes approved/edited drafts to disk, so re-running coverage afterwards measures exactly that |
| Low-value test detection | `low_value_detector.py` - AST-based, flags empty stubs, "no real assertion" tests, and bare `pytest.raises` with no message/state check |
| CI integration hook | `coverage_delta.run_coverage()` is a plain subprocess call to `pytest`/`coverage`; wire it into your CI step of choice to confirm applied tests still pass before merge |
| Audit trail | `audit_log.py` - append-only JSONL, every entry carries `risk_score` + `risk_components` + `reviewer` |

## Anti-patterns this deliberately avoids

- **Never auto-merges**: `apply_tests.py` only writes drafts whose status
  is `approved` or `edited`; `pending`/`rejected` drafts are never written
  anywhere outside the review queue.
- **Never ranks by coverage gap alone**: every candidate in the demo above
  has a 100% coverage gap, yet they're ranked by change-frequency and
  complexity too (see `test_risk_ranker.py::test_high_change_frequency_outranks_coverage_gap_alone`).
- **Never silently overwrites existing tests**: `apply_tests.py` refuses to
  overwrite a pre-existing file with different content; it reports a
  conflict for manual resolution instead.
- **Flags its own low-value output**: the no-LLM-key fallback honestly
  produces a TODO stub (never a fabricated passing assertion), and the
  low-value detector runs on every draft - LLM-written or template - before
  it reaches the reviewer.
- **Audit trail always present**: every draft and every review decision is
  logged with its risk score and components, not just a pass/fail.

## Where this still needs a human

- **Test intent vs. current behavior**: an LLM- or human-drafted test can
  assert the code's *current* (possibly buggy) behavior instead of its
  *correct* behavior. Review the rationale and the function source, not
  just whether the draft passes.
- **Risk scoring is a heuristic**, not a guarantee - it approximates where
  regressions are likely.
- **Change-frequency attribution is commit-overlap based**: a function
  rename is treated as a brand-new function with no history (see
  `git_history.py` docstring). A module-level constant edit (e.g. adding a
  dict entry outside any function body) correctly does **not** count
  toward a function's change frequency, even if it changes that function's
  behavior.

## Running the agent's own test suite

```bash
cd test-risk-agent
source .venv/Scripts/activate
pytest           # 53 tests: complexity, risk ranking, coverage parsing,
                 # low-value detection, review queue, apply/conflict
                 # handling, real git-history fixtures, both orchestration
                 # engines, and a real coverage.py subprocess round-trip
```

## Engines

| | `--engine langgraph` (default if installed) | `--engine simple` |
|---|---|---|
| Dependency | `langgraph` + `langgraph-checkpoint-sqlite` | stdlib only |
| Pause mechanism | `interrupt()` + SQLite checkpoint, survives across CLI invocations | a JSON state file (`data/simple_pipeline_state.json`) |
| Review step | identical - operates on the on-disk review queue either way | identical |

`--engine auto` (the CLI default) picks `langgraph` if it's importable,
otherwise `simple` - so the tool still runs end-to-end even in an
environment where you can't install LangGraph.
