"""Flags generated tests that provide false confidence.

A test that only checks "no exception was thrown" or "result is not None"
passes trivially against almost any implementation, including a buggy one.
This module statically inspects generated test code (via AST, never by
executing it) and returns a list of human-readable reasons it looks
low-value - empty list means it looks substantive.
"""
from __future__ import annotations

import ast
from typing import List

_MEANINGFUL_COMPARE_OPS = (
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
)
_TRIVIAL_CALL_NAMES = {"isinstance", "hasattr", "callable"}


def _is_meaningful_assert(node: ast.Assert) -> bool:
    test = node.test

    if isinstance(test, ast.Constant):
        return False  # `assert True`, `assert 1`

    if isinstance(test, ast.Compare):
        for op, comparator in zip(test.ops, test.comparators):
            is_none_identity_check = (
                isinstance(op, (ast.Is, ast.IsNot))
                and isinstance(comparator, ast.Constant)
                and comparator.value is None
            )
            if is_none_identity_check:
                continue  # `is (not) None` alone says nothing about the actual value
            if isinstance(op, _MEANINGFUL_COMPARE_OPS):
                return True
        return False

    if isinstance(test, ast.BoolOp):
        return True  # combinations of conditions are rarely vacuous

    if isinstance(test, ast.Call):
        func_name = getattr(test.func, "attr", None) or getattr(test.func, "id", "")
        return func_name not in _TRIVIAL_CALL_NAMES

    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = test.operand
        # `assert not result` is weak; `assert not (a == b)` is a real check.
        return isinstance(inner, (ast.Compare, ast.BoolOp, ast.Call))

    # A bare Name/Attribute, e.g. `assert result` - only proves truthiness.
    return False


def _is_pytest_raises(expr: ast.AST) -> bool:
    if isinstance(expr, ast.Call):
        func = expr.func
        name = getattr(func, "attr", None) or getattr(func, "id", "")
        return name == "raises"
    return False


def evaluate_test_code(code: str) -> List[str]:
    """Returns low-value reasons for the generated code; [] means it looks fine."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"generated code has a syntax error and cannot be parsed: {exc}"]

    test_funcs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")
    ]
    if not test_funcs:
        return ["no test_* function was found in the generated code"]

    reasons: List[str] = []
    for func in test_funcs:
        if all(isinstance(stmt, (ast.Pass,)) for stmt in func.body):
            reasons.append(f"{func.name}: body is an empty TODO stub with no executable assertions")
            continue

        asserts = [n for n in ast.walk(func) if isinstance(n, ast.Assert)]
        raises_blocks = [
            n
            for n in ast.walk(func)
            if isinstance(n, ast.With) and any(_is_pytest_raises(item.context_expr) for item in n.items)
        ]
        meaningful_asserts = [a for a in asserts if _is_meaningful_assert(a)]

        if not asserts and not raises_blocks:
            reasons.append(
                f"{func.name}: no assert statements and no pytest.raises - the test cannot "
                "fail against a broken implementation"
            )
        elif raises_blocks and not meaningful_asserts and not asserts:
            reasons.append(
                f"{func.name}: only verifies that *some* exception is raised, without "
                "checking its type, message, or resulting state"
            )
        elif not meaningful_asserts:
            reasons.append(
                f"{func.name}: assertions are trivial (e.g. assert True / is not None) and "
                "never compare against a specific expected value"
            )

    return reasons
