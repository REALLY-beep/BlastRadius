"""End-to-end AI mode against a mocked local llama-server."""

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.llm.engine import run_ai_analysis
from app.main import app
from app.models import LLMStatus
from tests.test_llm_engine import ANALYSIS, PASSING_TEST, FakeLLM



client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]
DIFF = (ROOT / "examples" / "change.diff").read_text(encoding="utf-8")
REPO = ROOT / "examples" / "sample_project"


class FakeClientCM(FakeLLM):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        return None


def test_ai_mode_end_to_end_with_mocked_llama_server():
    fake = FakeClientCM(analysis=json.dumps(ANALYSIS), tests=[PASSING_TEST])

    def factory(config, http_client=None):
        fake.config = config
        return fake

    with patch("app.main.LlamaClient", factory):
        response = client.post(
            "/analyze",
            data={
                "engine": "ai",
                "diff_text": DIFF,
                "llm_url": "http://127.0.0.1:9999",
                "llm_model": "local-gguf",
            },
        )

    assert response.status_code == 200
    assert "Engine · AI" in response.text
    assert "checkout" in response.text
    assert "AI TEST" in response.text
    assert "Pytest passed" in response.text
    assert "✓ Pytest passed" in response.text
    assert "AI TEST" in response.text
    assert "test_blast_radius_calculate_total_1.py" not in response.text
    assert fake.calls, "expected the local model to be invoked"


def test_ai_mode_mocked_llama_does_not_call_ast_generator():
    result = run_ai_analysis(str(REPO), DIFF, FakeLLM(), max_tests=1)
    assert result.analysis_engine == "ai"
    assert all(test.filename.startswith("test_ai_blast_radius_") for test in result.generated_tests)


def test_llm_status_endpoint_uses_client():
    class StatusClient:
        def __init__(self, config, http_client=None):
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def check_status(self):
            return LLMStatus(status="connected", detail="Loaded qwen", model="qwen", server_url=self.config.server_url)

    with patch("app.main.LlamaClient", StatusClient):
        response = client.get(
            "/api/llm/status",
            params={"server_url": "http://127.0.0.1:9999", "model": "qwen"},
        )
    assert response.json()["status"] == "connected"
    assert "qwen" in response.json()["detail"]
