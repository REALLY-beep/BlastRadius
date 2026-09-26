"""Parse local-model output into JSON and Python without trusting fences."""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Dict, List, Optional

from ..models import CallSite, ChangedFunction
from .client import LLMInvalidResponse


FENCE_RE = re.compile(r"```([A-Za-z0-9_-]*)\s*\r?\n([\s\S]*?)```", re.MULTILINE)


def strip_code_fence(text: str, prefer: Optional[str] = None) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    blocks = FENCE_RE.findall(raw)
    if blocks:
        if prefer:
            preferred = [body for lang, body in blocks if lang.lower() in {prefer.lower(), "py"}]
            if preferred:
                return preferred[0].strip()
        return blocks[0][1].strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return raw


def extract_json_object(text: str) -> Dict[str, Any]:
    if not (text or "").strip():
        raise LLMInvalidResponse("The local model returned an empty response.")
    candidates = [strip_code_fence(text, prefer="json"), (text or "").strip()]
    errors: List[str] = []
    for candidate in candidates:
        parsed = _try_json(candidate)
        if isinstance(parsed, dict):
            return parsed
        if parsed is not None:
            errors.append("JSON root was not an object.")
            continue
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            parsed = _try_json(candidate[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
            if parsed is not None:
                errors.append("JSON root was not an object.")
            else:
                errors.append("Could not parse JSON object.")
    raise LLMInvalidResponse(
        "Malformed AI response: expected a JSON object. "
        + (errors[-1] if errors else "No JSON object was found.")
    )


def extract_python_source(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        raise LLMInvalidResponse("The local model returned empty test code.")
    blocks = FENCE_RE.findall(raw)
    python_blocks = [
        body.strip()
        for lang, body in blocks
        if lang.lower() in {"", "python", "py"}
    ]
    if python_blocks:
        return python_blocks[0]
    stripped = strip_code_fence(raw, prefer="python")
    if stripped:
        return stripped
    return raw


def python_syntax_error(source: str) -> Optional[str]:
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg} (line {exc.lineno})"
    return None


def changed_function_from_dict(raw: Any) -> Optional[ChangedFunction]:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or raw.get("function") or "").strip()
    if not name:
        return None
    file_name = str(raw.get("file") or raw.get("path") or "").strip() or "(from AI)"
    try:
        lineno = int(raw.get("lineno") or raw.get("line") or 0)
    except (TypeError, ValueError):
        lineno = 0
    end_lineno = raw.get("end_lineno")
    try:
        end_value = int(end_lineno) if end_lineno is not None else None
    except (TypeError, ValueError):
        end_value = None
    return ChangedFunction(name=name, file=file_name, lineno=max(lineno, 0), end_lineno=end_value)


def call_site_from_dict(raw: Any) -> Optional[CallSite]:
    if not isinstance(raw, dict):
        return None
    function_name = str(raw.get("function_name") or raw.get("target") or raw.get("name") or "").strip()
    caller = raw.get("caller_name") or raw.get("caller")
    if not function_name and not caller:
        return None
    try:
        lineno = int(raw.get("lineno") or raw.get("line") or 0)
    except (TypeError, ValueError):
        lineno = 0
    try:
        risk_score = int(raw.get("risk_score") if raw.get("risk_score") is not None else 50)
    except (TypeError, ValueError):
        risk_score = 50
    risk_score = max(0, min(100, risk_score))
    is_tested = _as_bool(raw.get("is_tested"), default=False)
    risk = str(raw.get("risk") or "").strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "low" if is_tested or risk_score < 30 else ("high" if risk_score >= 70 else "medium")
    params = raw.get("caller_params") or []
    if not isinstance(params, list):
        params = []
    return CallSite(
        file=str(raw.get("file") or raw.get("path") or "").strip() or "(from AI)",
        lineno=max(lineno, 0),
        function_name=function_name or "unknown",
        code_line=str(raw.get("code_line") or raw.get("code") or "").strip(),
        is_tested=is_tested,
        risk=risk,
        risk_score=10 if is_tested else risk_score,
        caller_name=str(caller).strip() if caller else None,
        caller_qualname=str(raw.get("caller_qualname") or caller or "").strip() or None,
        target_qualname=str(raw.get("target_qualname") or function_name).strip() or None,
        module=str(raw.get("module")).strip() if raw.get("module") else None,
        target_module=str(raw.get("target_module")).strip() if raw.get("target_module") else None,
        caller_params=[str(item) for item in params],
        caller_is_method=_as_bool(raw.get("caller_is_method"), default=False),
        patch_target=str(raw.get("patch_target")).strip() if raw.get("patch_target") else None,
        coverage_reason=str(raw.get("coverage_reason") or "").strip() or None,
        impact_reason=str(raw.get("impact_reason") or raw.get("why") or raw.get("reason") or "").strip() or None,
    )


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "tested"}:
        return True
    if text in {"false", "no", "0", "untested"}:
        return False
    return default
