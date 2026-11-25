"""Drafts candidate pytest tests for the highest-risk untested paths.

Every draft is traced (test-generation call -> LangFuse span) and run
through the low-value detector before it ever reaches the human review
queue, so a reviewer sees the low-value flag immediately instead of having
to notice it themselves.
"""
from __future__ import annotations

import re
import textwrap
from typing import Optional

from . import llm_client
from . import low_value_detector
from .config import Settings
from .models import FunctionSpan, RiskCandidate, TestDraft, new_draft_id
from .tracing import tracer

_PROMPT_TEMPLATE = """You are a senior Python test engineer adding a missing pytest test to an \
existing suite. The suite uses plain pytest (no unittest.TestCase), already imports fixtures \
from conftest.py where needed, and follows PEP 8.

Context:
- File: {file}
- Function under test: {qualname}
- Why this path was flagged high risk: {rationale}
- Source lines NOT currently covered by any test: {missing_lines}

Function source:
```python
{source}
```

Write ONE pytest test module covering the behavior on the uncovered lines above (not just the \
happy path, which is likely already tested elsewhere). Requirements:
- Start with: {import_stmt}
- Use REAL assertions that compare to a specific expected value (e.g. `assert result == 42`), \
never only "no exception was raised" or "result is not None".
- If the function is expected to raise, use `pytest.raises(SpecificException)` and additionally \
assert something about the resulting state or exception message/args.
- No network calls, no sleeps, no unseeded randomness, no file or environment side effects.
- Output ONLY raw Python source. No markdown fences, no prose before or after the code.
"""

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n|\n```$", re.MULTILINE)


def _strip_markdown_fences(code: str) -> str:
    return _FENCE_RE.sub("", code).strip() + "\n"


def _import_statement(file_rel: str, qualname: str) -> str:
    module = file_rel[:-3].replace("/", ".").replace("\\", ".") if file_rel.endswith(".py") else file_rel
    top_level_name = qualname.split(".")[0]
    return f"from {module} import {top_level_name}"


def _template_draft(candidate: RiskCandidate, span: FunctionSpan) -> str:
    """Dependency-free fallback used when no LLM credentials are configured.

    Deliberately produces an *honest* TODO stub rather than a fake test that
    would pass against any implementation - see low_value_detector, which
    will correctly flag this stub so a reviewer never mistakes it for real
    coverage.
    """
    func_name = candidate.qualname.split(".")[-1]
    import_stmt = _import_statement(candidate.file, candidate.qualname)
    test_name = re.sub(r"\W+", "_", candidate.qualname).strip("_").lower()
    missing = candidate.missing_lines
    body = textwrap.dedent(
        f'''\
        """Auto-drafted stub for {candidate.qualname} ({candidate.file}).

        TEMPLATE STUB: no LLM credentials were configured (ANTHROPIC_API_KEY unset),
        so this was generated without model reasoning about expected behavior.
        It intentionally asserts nothing yet - replace the body before approving.

        Risk rationale: {candidate.rationale}
        Uncovered lines targeted: {missing}
        """
        {import_stmt}


        def test_{test_name}_todo_needs_review():
            # TODO(reviewer): call {func_name}(...) with inputs that exercise
            # lines {missing}, then assert the SPECIFIC expected result, e.g.:
            #     result = {func_name}(...)
            #     assert result == <expected value>
            pass
        '''
    )
    return body


def generate_draft(candidate: RiskCandidate, span: FunctionSpan, settings: Settings) -> TestDraft:
    import_stmt = _import_statement(candidate.file, candidate.qualname)
    prompt = _PROMPT_TEMPLATE.format(
        file=candidate.file,
        qualname=candidate.qualname,
        rationale=candidate.rationale,
        missing_lines=candidate.missing_lines,
        source=span.source,
        import_stmt=import_stmt,
    )

    generated_by = "template"
    trace_id: Optional[str] = None
    with tracer.span(
        "test_generation",
        metadata={
            "file": candidate.file,
            "qualname": candidate.qualname,
            "risk_score": candidate.risk_score,
            "risk_components": candidate.risk_components,
        },
    ) as span_ctx:
        trace_id = span_ctx.trace_id
        try:
            code = llm_client.generate_with_claude(prompt, settings)
            code = _strip_markdown_fences(code)
            generated_by = "llm"
        except llm_client.LLMUnavailable as exc:
            code = _template_draft(candidate, span)
            generated_by = "template"
            span_ctx.set_output({"fallback_reason": str(exc)})

        low_value_reasons = low_value_detector.evaluate_test_code(code)
        span_ctx.set_output(
            {
                "generated_by": generated_by,
                "low_value": bool(low_value_reasons),
                "code_preview": code[:500],
            }
        )

    return TestDraft(
        id=new_draft_id(),
        candidate=candidate.to_dict(),
        code=code,
        generated_by=generated_by,
        low_value=bool(low_value_reasons),
        low_value_reasons=low_value_reasons,
        trace_id=trace_id,
    )
