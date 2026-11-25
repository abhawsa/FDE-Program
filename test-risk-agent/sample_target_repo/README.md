# Sample Target Repo (synthetic seed data)

A tiny, fully synthetic "storefront" codebase used to demonstrate the AI
Test Coverage & Regression Risk Agent end-to-end. Nothing here is real
business logic, customer data, or production code - it exists purely so
the agent has git history, a coverage gap, and varying complexity to
analyze.

- `billing/calculator.py` - simple, well-tested helper functions.
- `billing/discounts.py` - **no tests at all**, and (per its commit
  history) changes far more often than the rest of the codebase - this is
  the path the agent should rank highest.
- `inventory/stock.py` - also untested, but simple and rarely changed - it
  should rank lower than `discounts.py` despite having the same raw
  coverage gap.
