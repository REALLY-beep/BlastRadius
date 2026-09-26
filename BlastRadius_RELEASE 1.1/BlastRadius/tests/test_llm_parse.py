import pytest

from app.llm.client import LLMInvalidResponse
from app.llm.parse import extract_json_object, extract_python_source, python_syntax_error


def test_extract_json_from_fence():
    raw = """Here you go\n```json\n{"changed_functions": [{"name": "foo", "file": "a.py", "lineno": 1}]}\n```\n"""
    data = extract_json_object(raw)
    assert data["changed_functions"][0]["name"] == "foo"


def test_extract_json_from_prose():
    raw = 'noise {"summary": "ok", "risk_score": 3} trailing'
    data = extract_json_object(raw)
    assert data["summary"] == "ok"


def test_malformed_json_raises():
    with pytest.raises(LLMInvalidResponse):
        extract_json_object("sorry I cannot help")


def test_empty_response_raises():
    with pytest.raises(LLMInvalidResponse):
        extract_json_object("   ")


def test_extract_python_strips_fence():
    raw = """```python\nfrom shop import checkout\n\ndef test_it():\n    assert checkout([1], 0)\n```"""
    source = extract_python_source(raw)
    assert source.startswith("from shop import checkout")
    assert "```" not in source
    assert python_syntax_error(source) is None


def test_invalid_python_is_detected():
    source = extract_python_source("```python\ndef broken(\n```")
    assert python_syntax_error(source)
