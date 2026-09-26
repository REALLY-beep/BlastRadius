from pathlib import Path

from app.models import GeneratedTest
from app.pytest_runner import run_pytest_source, summarize_test_runs


REPO = Path(__file__).resolve().parents[1] / "examples" / "sample_project"


def test_syntax_failure():
    outcome = run_pytest_source("def broken(:\n    pass\n", str(REPO))
    assert outcome.syntax_ok is False
    assert outcome.passed is False
    assert "SyntaxError" in (outcome.error or "")


def test_pytest_pass_and_fail():
    passing = "from shop import calculate_total\n\ndef test_ok():\n    assert calculate_total([1, 2]) == 3\n"
    failing = "from shop import calculate_total\n\ndef test_bad():\n    assert calculate_total([1, 2]) == 0\n"
    ok = run_pytest_source(passing, str(REPO), filename="test_ok.py")
    bad = run_pytest_source(failing, str(REPO), filename="test_bad.py")
    assert ok.passed is True
    assert bad.passed is False
    assert "assert" in (bad.output or "").lower() or bad.error


def test_summary():
    tests = [
        GeneratedTest(filename="a.py", content="x", target_call_site="a:1", pytest_passed=True),
        GeneratedTest(filename="b.py", content="x", target_call_site="b:1", pytest_passed=False),
    ]
    text = summarize_test_runs(tests)
    assert "1 passed" in text
    assert "1 failed" in text
