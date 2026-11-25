from test_risk_agent.low_value_detector import evaluate_test_code


def test_flags_empty_todo_stub():
    code = """
def test_something_todo_needs_review():
    pass
"""
    reasons = evaluate_test_code(code)
    assert reasons
    assert any("TODO" in r or "empty" in r for r in reasons)


def test_flags_no_assertions_at_all():
    code = """
def test_calls_function_but_checks_nothing():
    some_function(1, 2, 3)
"""
    reasons = evaluate_test_code(code)
    assert reasons
    assert any("no assert" in r for r in reasons)


def test_flags_only_not_none_assertion():
    code = """
def test_result_exists():
    result = some_function(1, 2)
    assert result is not None
"""
    reasons = evaluate_test_code(code)
    assert reasons
    assert any("trivial" in r for r in reasons)


def test_flags_bare_exception_raise_with_no_further_checks():
    code = """
import pytest

def test_raises_something():
    with pytest.raises(Exception):
        risky_call()
"""
    reasons = evaluate_test_code(code)
    assert reasons
    assert any("only verifies that" in r for r in reasons)


def test_accepts_real_equality_assertion():
    code = """
def test_adds_numbers():
    result = add(2, 3)
    assert result == 5
"""
    assert evaluate_test_code(code) == []


def test_accepts_raises_with_message_check():
    code = """
import pytest

def test_rejects_negative():
    with pytest.raises(ValueError) as excinfo:
        validate(-1)
    assert "negative" in str(excinfo.value)
"""
    assert evaluate_test_code(code) == []


def test_flags_syntax_error():
    reasons = evaluate_test_code("def test_broken(:\n    pass")
    assert reasons
    assert "syntax error" in reasons[0]


def test_flags_no_test_function_found():
    reasons = evaluate_test_code("x = 1\n")
    assert reasons == ["no test_* function was found in the generated code"]
