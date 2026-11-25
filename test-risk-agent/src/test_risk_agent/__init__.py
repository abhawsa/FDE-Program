"""AI Test Coverage & Regression Risk Agent.

Analyzes git history + a coverage.py report together, ranks untested code
paths by risk (change frequency x complexity x coverage gap), and drafts
candidate pytest tests for human review. Nothing is ever auto-merged into
the test suite - see cli.py for the review/apply workflow.
"""

__version__ = "0.1.0"
