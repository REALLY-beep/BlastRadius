import json
from pathlib import Path

import pytest

from app.llm.client import LLMInvalidResponse, LLMTimeout, LLMUnavailable
from app.llm.config import LLMConfig
from app.llm.context import build_analysis_context, looks_like_unified_diff
from app.llm.engine import run_ai_analysis
from app.models import LLMStatus


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "examples" / "sample_project"
DIFF = (ROOT / "examples" / "change.diff").read_text(encoding="utf-8")

ANALYSIS = {
    "changed_functions": [{"name": "calculate_total", "file": "shop.py", "lineno": 5}],
    "call_sites": [
        {
            "file": "shop.py",
            "lineno": 26,
            "function_name": "calculate_total",
            "code_line": "total = calculate_total(cart)",
            "caller_name": "checkout",
            "caller_qualname": "checkout",
            "is_tested": False,
            "risk": "high",
            "risk_score": 82,
            "coverage_reason": "existing tests call calculate_total directly",
            "impact_reason": "checkout is the customer-facing path",
            "module": "shop",
            "caller_params": ["cart", "discount"],
        }
    ],
    "untested_high_risk": [
        {
            "file": "shop.py",
            "lineno": 26,
            "function_name": "calculate_total",
            "caller_name": "checkout",
            "caller_qualname": "checkout",
            "is_tested": False,
            "risk": "high",
            "risk_score": 82,
            "impact_reason": "checkout is untested",
            "module": "shop",
            "caller_params": ["cart", "discount"],
        }
    ],
    "risk_score": 82,
    "risk_explanation": "Production checkout is untested.",
    "summary": "calculate_total changed; checkout is untested.",
}

PASSING_TEST = """from shop import checkout

def test_checkout_path():
    assert checkout([10.0, 20.0], 0) == "$30.00"
"""

FAILING_TEST = """from shop import checkout

def test_checkout_path():
    assert checkout([10.0, 20.0], 0) == "WRONG"
"""


class FakeLLM:
    def __init__(self, analysis=None, tests=None, error=None, correction_attempts=2):
        self.config = LLMConfig(correction_attempts=correction_attempts, timeout=5)
        self.analysis = analysis if analysis is not None else json.dumps(ANALYSIS)
        self.tests = list(tests or [PASSING_TEST])
        self.error = error
        self.calls = []

    def check_status(self):
        return LLMStatus(status="connected", detail="ok")

    def require_available(self):
        return self.check_status()

    def chat(self, messages, **kwargs):
        if self.error:
            raise self.error
        self.calls.append(messages)
        system = messages[0]["content"].lower()
        user = messages[-1]["content"]
        if "test generator" in system or "corrected pytest" in user.lower() or "previous pytest file" in user.lower():
            if not self.tests:
                return PASSING_TEST
            return self.tests.pop(0)
        return self.analysis


def test_context_is_focused_not_empty():
    context = build_analysis_context(str(REPO), DIFF)
    assert "calculate_total" in context["source"]
    assert "shop.py" in context["modules"]
    assert looks_like_unified_diff(DIFF)


def test_ai_engine_success_and_pytest_pass():
    client = FakeLLM()
    result = run_ai_analysis(str(REPO), DIFF, client, max_tests=1)
    assert result.analysis_engine == "ai"
    assert result.changed_functions[0].name == "calculate_total"
    assert result.call_sites[0].caller_name == "checkout"
    assert result.generated_tests
    assert result.generated_tests[0].syntax_ok
    assert result.generated_tests[0].pytest_passed is True
    assert "```" not in result.generated_tests[0].content


def test_ai_engine_strips_markdown_and_retries_pytest_failure():
    fenced = "```python\n" + PASSING_TEST + "\n```"
    client = FakeLLM(tests=[FAILING_TEST, fenced], correction_attempts=2)
    result = run_ai_analysis(str(REPO), DIFF, client, max_tests=1)
    assert result.generated_tests[0].pytest_passed is True
    assert result.generated_tests[0].attempts == 2
    assert "```" not in result.generated_tests[0].content


def test_ai_engine_malformed_analysis():
    client = FakeLLM(analysis="I cannot produce JSON today")
    with pytest.raises(LLMInvalidResponse):
        run_ai_analysis(str(REPO), DIFF, client)


def test_ai_engine_timeout_bubbles():
    client = FakeLLM(error=LLMTimeout("timed out"))
    with pytest.raises(LLMTimeout):
        run_ai_analysis(str(REPO), DIFF, client)


def test_ai_engine_connection_bubbles():
    client = FakeLLM(error=LLMUnavailable("refused"))
    with pytest.raises(LLMUnavailable):
        run_ai_analysis(str(REPO), DIFF, client)


def test_ai_engine_rejects_non_diff():
    client = FakeLLM()
    with pytest.raises(ValueError):
        run_ai_analysis(str(REPO), "hello world", client)
