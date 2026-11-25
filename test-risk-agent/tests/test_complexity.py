from pathlib import Path

from test_risk_agent.complexity import cyclomatic_complexity, extract_function_spans
import ast


def test_extract_function_spans_finds_top_level_and_nested(tmp_path: Path):
    source = """
def outer(x):
    if x > 0:
        return 1
    return -1


class Thing:
    def method(self, y):
        for i in range(y):
            if i % 2 == 0:
                continue
        return y
"""
    file_path = tmp_path / "mod.py"
    file_path.write_text(source, encoding="utf-8")

    spans = extract_function_spans(file_path)
    qualnames = {s.qualname for s in spans}

    assert qualnames == {"outer", "Thing.method"}


def test_cyclomatic_complexity_counts_branches():
    tree = ast.parse(
        """
def f(x):
    if x > 0:
        return 1
    elif x < 0:
        return -1
    return 0
"""
    )
    func = tree.body[0]
    # base 1 + if + elif(counted as its own If node) = 3
    assert cyclomatic_complexity(func) == 3


def test_cyclomatic_complexity_counts_boolop_branches():
    tree = ast.parse(
        """
def f(a, b, c):
    if a and b and c:
        return True
    return False
"""
    )
    func = tree.body[0]
    # base 1 + if(1) + boolop with 3 values -> +2 = 4
    assert cyclomatic_complexity(func) == 4


def test_simple_function_has_complexity_one():
    tree = ast.parse("def f(x):\n    return x + 1\n")
    func = tree.body[0]
    assert cyclomatic_complexity(func) == 1
