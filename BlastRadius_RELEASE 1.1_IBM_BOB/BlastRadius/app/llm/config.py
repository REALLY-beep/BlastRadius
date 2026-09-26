"""Local llama.cpp llama-server settings. No cloud endpoints."""

from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_SERVER_URL = os.environ.get(
    "BLAST_RADIUS_LLM_URL",
    "http://127.0.0.1:8080",
)
DEFAULT_MODEL = os.environ.get("BLAST_RADIUS_LLM_MODEL", "local-gguf")
DEFAULT_TEMPERATURE = float(os.environ.get("BLAST_RADIUS_LLM_TEMPERATURE", "0.1"))
DEFAULT_MAX_TOKENS = int(os.environ.get("BLAST_RADIUS_LLM_MAX_TOKENS", "2048"))
DEFAULT_TIMEOUT = float(os.environ.get("BLAST_RADIUS_LLM_TIMEOUT", "120"))
DEFAULT_STATUS_TIMEOUT = float(os.environ.get("BLAST_RADIUS_LLM_STATUS_TIMEOUT", "4"))
DEFAULT_CORRECTION_ATTEMPTS = int(os.environ.get("BLAST_RADIUS_LLM_RETRIES", "2"))


@dataclass(frozen=True)
class LLMConfig:
    server_url: str = DEFAULT_SERVER_URL
    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout: float = DEFAULT_TIMEOUT
    status_timeout: float = DEFAULT_STATUS_TIMEOUT
    correction_attempts: int = DEFAULT_CORRECTION_ATTEMPTS

    @classmethod
    def from_form(
        cls,
        server_url: str | None = None,
        model: str | None = None,
    ) -> "LLMConfig":
        return cls(
            server_url=(server_url or DEFAULT_SERVER_URL).strip() or DEFAULT_SERVER_URL,
            model=(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        )
