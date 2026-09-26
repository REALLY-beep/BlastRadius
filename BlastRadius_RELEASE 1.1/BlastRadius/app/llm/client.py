"""HTTP client for a local llama.cpp llama-server (OpenAI-compatible)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from ..models import LLMStatus
from .config import LLMConfig


class LLMError(Exception):
    """Base error for the local GGUF client."""


class LLMUnavailable(LLMError):
    """llama-server is not reachable or has no loaded model."""


class LLMTimeout(LLMError):
    """The local model did not respond in time."""


class LLMInvalidResponse(LLMError):
    """The local model returned an empty or unusable payload."""


def normalize_base_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        raise LLMUnavailable("No llama-server URL was provided.")
    value = value.rstrip("/")
    suffixes = (
        "/v1/chat/completions",
        "/chat/completions",
        "/v1/completions",
        "/completion",
        "/v1",
    )
    for suffix in suffixes:
        if value.lower().endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value.rstrip("/")


class LlamaClient:
    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.config = config or LLMConfig()
        self.base_url = normalize_base_url(self.config.server_url)
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(self.config.timeout, connect=min(8.0, self.config.timeout)),
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "LlamaClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def check_status(self) -> LLMStatus:
        """Probe llama-server. Never report connected unless a model endpoint looks real."""
        try:
            models_response = self._http.get(
                f"{self.base_url}/v1/models",
                timeout=self.config.status_timeout,
            )
        except httpx.ConnectError as exc:
            return LLMStatus(
                status="disconnected",
                detail=f"Could not connect to {self.base_url}: {exc}",
                server_url=self.base_url,
            )
        except httpx.TimeoutException:
            return LLMStatus(
                status="disconnected",
                detail=f"Timed out reaching {self.base_url}",
                server_url=self.base_url,
            )
        except httpx.HTTPError as exc:
            return LLMStatus(
                status="disconnected",
                detail=str(exc),
                server_url=self.base_url,
            )

        if models_response.status_code == 200:
            parsed = _safe_json(models_response)
            if parsed is None:
                return LLMStatus(
                    status="invalid_response",
                    detail="llama-server /v1/models did not return JSON.",
                    server_url=self.base_url,
                )
            if _looks_like_blastradius(parsed):
                return LLMStatus(
                    status="disconnected",
                    detail="That URL is BlastRadius itself, not llama-server. Start llama.cpp llama-server and point this field at its port.",
                    server_url=self.base_url,
                )
            model_ids = _model_ids(parsed)
            if not model_ids:
                health = self._health_status()
                if health is not None:
                    return health
                return LLMStatus(
                    status="model_unavailable",
                    detail="llama-server responded but no model is loaded.",
                    server_url=self.base_url,
                )
            requested = self.config.model
            if requested and requested not in {"local-gguf", "default"} and not _model_matches(requested, model_ids):
                return LLMStatus(
                    status="model_unavailable",
                    detail=f"Connected, but '{requested}' is not among loaded models: {', '.join(model_ids)}",
                    model=model_ids[0],
                    server_url=self.base_url,
                )
            return LLMStatus(
                status="connected",
                detail=f"llama-server reachable. Loaded: {', '.join(model_ids)}",
                model=model_ids[0],
                server_url=self.base_url,
            )

        health = self._health_status()
        if health is not None:
            return health

        if models_response.status_code in {401, 403}:
            return LLMStatus(
                status="invalid_response",
                detail=f"llama-server rejected the request (HTTP {models_response.status_code}).",
                server_url=self.base_url,
            )

        snippet = (models_response.text or "")[:180]
        return LLMStatus(
            status="invalid_response",
            detail=f"Unexpected response from {self.base_url} (HTTP {models_response.status_code}): {snippet}",
            server_url=self.base_url,
        )

    def require_available(self) -> LLMStatus:
        status = self.check_status()
        if status.status == "connected":
            return status
        raise LLMUnavailable(status.detail or f"llama-server is {status.status}")

    def chat(self, messages: List[Dict[str, str]], temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        try:
            response = self._http.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=self.config.timeout,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"Local GGUF request timed out after {self.config.timeout:.0f}s") from exc
        except httpx.ConnectError as exc:
            raise LLMUnavailable(f"Could not connect to llama-server at {self.base_url}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"llama-server request failed: {exc}") from exc

        if response.status_code >= 500:
            raise LLMUnavailable(
                f"llama-server error HTTP {response.status_code}: {(response.text or '')[:300]}"
            )
        if response.status_code == 404:
            raise LLMUnavailable(
                "llama-server has no /v1/chat/completions endpoint. Use an OpenAI-compatible llama.cpp llama-server."
            )
        if response.status_code >= 400:
            raise LLMInvalidResponse(
                f"llama-server rejected the completion (HTTP {response.status_code}): {(response.text or '')[:300]}"
            )

        data = _safe_json(response)
        if data is None:
            raise LLMInvalidResponse("llama-server did not return JSON.")
        if _looks_like_blastradius(data):
            raise LLMUnavailable("That URL is BlastRadius, not llama-server.")

        text = _message_text(data)
        if not text.strip():
            raise LLMInvalidResponse("The local model returned an empty completion.")
        return text

    def _health_status(self) -> Optional[LLMStatus]:
        try:
            response = self._http.get(
                f"{self.base_url}/health",
                timeout=self.config.status_timeout,
            )
        except httpx.HTTPError:
            return None

        parsed = _safe_json(response)
        if _looks_like_blastradius(parsed):
            return LLMStatus(
                status="disconnected",
                detail="That URL is BlastRadius itself, not llama-server. Start llama.cpp llama-server and point this field at its port.",
                server_url=self.base_url,
            )
        if response.status_code == 503:
            return LLMStatus(
                status="model_unavailable",
                detail="llama-server is running but the GGUF model is still loading or unavailable.",
                server_url=self.base_url,
            )
        if response.status_code == 200:
            status_value = ""
            if isinstance(parsed, dict):
                status_value = str(parsed.get("status") or parsed.get("error") or "").lower()
            if status_value in {"loading", "no slot available", "error"}:
                return LLMStatus(
                    status="model_unavailable",
                    detail=f"llama-server health: {status_value or 'unavailable'}",
                    server_url=self.base_url,
                )
            if parsed is None and not (response.text or "").strip():
                return LLMStatus(
                    status="invalid_response",
                    detail="Empty health response from the server.",
                    server_url=self.base_url,
                )
            return LLMStatus(
                status="connected",
                detail="llama-server health endpoint reports ready.",
                model=self.config.model,
                server_url=self.base_url,
            )
        return None


def _safe_json(response: httpx.Response) -> Optional[Any]:
    try:
        return response.json()
    except ValueError:
        return None


def _looks_like_blastradius(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("service") == "BlastRadius"


def _model_ids(payload: Any) -> List[str]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data") or payload.get("models") or []
    ids: List[str] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, str) and row.strip():
                ids.append(row.strip())
            elif isinstance(row, dict):
                name = row.get("id") or row.get("name") or row.get("model")
                if name:
                    ids.append(str(name))
    return ids


def _model_matches(requested: str, loaded: List[str]) -> bool:
    requested_l = requested.lower()
    return any(
        requested_l == item.lower() or requested_l in item.lower() or item.lower() in requested_l
        for item in loaded
    )


def _message_text(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] or {}
        message = first.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in {None, "text"}:
                    parts.append(str(item.get("text") or ""))
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
        text = first.get("text")
        if isinstance(text, str):
            return text
    if isinstance(payload.get("content"), str):
        return payload["content"]
    return ""
