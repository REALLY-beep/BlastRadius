import httpx
import pytest

from app.llm.client import (
    LLMTimeout,
    LLMUnavailable,
    LlamaClient,
    normalize_base_url,
)
from app.llm.config import LLMConfig


def _client(handler) -> LlamaClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return LlamaClient(
        LLMConfig(server_url="http://127.0.0.1:8080", model="local-gguf", timeout=2, status_timeout=1),
        http_client=http,
    )


def test_normalize_strips_chat_suffix():
    assert normalize_base_url("http://127.0.0.1:8080/v1/chat/completions") == "http://127.0.0.1:8080"


def test_status_connected_from_models():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "qwen2.5-coder"}]})

    status = _client(handler).check_status()
    assert status.status == "connected"
    assert status.model == "qwen2.5-coder"


def test_status_model_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": []})
        if request.url.path == "/health":
            return httpx.Response(503, json={"status": "loading"})
        return httpx.Response(404)

    status = _client(handler).check_status()
    assert status.status == "model_unavailable"


def test_status_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    status = _client(handler).check_status()
    assert status.status == "invalid_response"


def test_status_detects_blastradius_self():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(404, json={"detail": "Not Found"})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "service": "BlastRadius"})
        return httpx.Response(404)

    status = _client(handler).check_status()
    assert status.status == "disconnected"
    assert "BlastRadius" in status.detail


def test_status_disconnected_on_connect_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    status = _client(handler).check_status()
    assert status.status == "disconnected"


def test_chat_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello from gguf"}}]},
        )

    text = _client(handler).chat([{"role": "user", "content": "hi"}])
    assert text == "hello from gguf"


def test_chat_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout", request=request)

    with pytest.raises(LLMTimeout):
        _client(handler).chat([{"role": "user", "content": "hi"}])


def test_chat_connection_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMUnavailable):
        _client(handler).chat([{"role": "user", "content": "hi"}])


def test_chat_empty_completion():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    with pytest.raises(Exception):
        _client(handler).chat([{"role": "user", "content": "hi"}])
