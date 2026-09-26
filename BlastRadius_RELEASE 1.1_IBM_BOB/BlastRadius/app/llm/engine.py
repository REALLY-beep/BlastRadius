"""AI analysis engine: local GGUF only. Does not call the AST analyzer."""

from __future__ import annotations

from typing import List

from ..models import AnalysisResult, CallSite, GeneratedTest
from ..pytest_runner import apply_pytest_outcome, run_pytest_source, summarize_test_runs
from .client import LLMInvalidResponse, LlamaClient
from .context import build_analysis_context, looks_like_unified_diff
from .parse import (
    call_site_from_dict,
    changed_function_from_dict,
    extract_json_object,
    extract_python_source,
    python_syntax_error,
)
from .prompts import ANALYSIS_SYSTEM, ANALYSIS_USER, REPAIR_USER, TEST_SYSTEM, TEST_USER


def run_ai_analysis(
    repo_path: str,
    diff_text: str,
    client: LlamaClient,
    max_tests: int = 3,
) -> AnalysisResult:
    if not looks_like_unified_diff(diff_text):
        raise ValueError(
            "The provided text does not look like a unified diff. Paste a git-style unified diff or load the demo."
        )

    context = build_analysis_context(repo_path, diff_text)
    analysis_text = client.chat(
        [
            {"role": "system", "content": ANALYSIS_SYSTEM},
            {"role": "user", "content": ANALYSIS_USER.format(**context)},
        ]
    )
    payload = extract_json_object(analysis_text)
    result = _result_from_payload(payload)

    targets = result.untested_high_risk or [
        site for site in result.call_sites if not site.is_tested
    ]
    generated: List[GeneratedTest] = []
    errors: List[str] = []
    attempts_allowed = max(0, client.config.correction_attempts)

    for index, site in enumerate(targets[:max_tests], start=1):
        test = _generate_one_test(
            client=client,
            site=site,
            context=context,
            repo_path=repo_path,
            index=index,
            attempts_allowed=attempts_allowed,
        )
        generated.append(test)
        if test.error:
            errors.append(f"{test.filename}: {test.error}")

    result.generated_tests = generated
    result.validation_errors = errors
    result.test_execution_status = summarize_test_runs(generated)
    if not result.summary:
        result.summary = (
            f"AI engine found {len(result.changed_functions)} changed function(s), "
            f"{len(result.call_sites)} affected path(s), "
            f"and {len(result.untested_high_risk)} high-risk untested path(s)."
        )
    return result


def _result_from_payload(payload: dict) -> AnalysisResult:
    changed = [
        item
        for item in (changed_function_from_dict(raw) for raw in payload.get("changed_functions") or [])
        if item is not None
    ]
    if not changed:
        raise LLMInvalidResponse(
            "The local model did not identify any changed functions. Check the diff, or switch to AST."
        )

    sites = [
        item
        for item in (call_site_from_dict(raw) for raw in payload.get("call_sites") or [])
        if item is not None
    ]
    risky_raw = payload.get("untested_high_risk")
    if isinstance(risky_raw, list) and risky_raw:
        risky = [
            item
            for item in (call_site_from_dict(raw) for raw in risky_raw)
            if item is not None
        ]
    else:
        risky = [site for site in sites if not site.is_tested and site.risk_score >= 60]

    try:
        risk_score = int(payload.get("risk_score") if payload.get("risk_score") is not None else 0)
    except (TypeError, ValueError):
        risk_score = 0
    risk_score = max(0, min(100, risk_score))
    if not risk_score and sites:
        untested = [site for site in sites if not site.is_tested]
        if untested:
            risk_score = max(site.risk_score for site in untested)

    explanation = str(payload.get("risk_explanation") or payload.get("explanation") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    return AnalysisResult(
        analysis_engine="ai",
        changed_functions=changed,
        call_sites=sites,
        untested_high_risk=risky,
        generated_tests=[],
        summary=summary,
        risk_score=risk_score,
        risk_explanation=explanation,
        test_execution_status="",
        validation_errors=[],
    )


def _generate_one_test(
    client: LlamaClient,
    site: CallSite,
    context: dict,
    repo_path: str,
    index: int,
    attempts_allowed: int,
) -> GeneratedTest:
    filename = _test_filename(site, index)
    prompt = TEST_USER.format(
        changed=site.function_name,
        caller=site.caller_qualname or site.caller_name or "(unknown caller)",
        reason=site.impact_reason or site.coverage_reason or "Untested affected path",
        source=context["source"],
        diff=context["diff"],
        tests=context["tests"],
    )
    messages = [
        {"role": "system", "content": TEST_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    last_code = ""
    last_error = "The local model did not return test code."
    last_output = ""
    attempts = 0
    max_rounds = 1 + attempts_allowed

    for round_index in range(max_rounds):
        attempts = round_index + 1
        raw = client.chat(messages, temperature=0.05 if round_index else 0.1)
        try:
            code = extract_python_source(raw)
        except LLMInvalidResponse as exc:
            last_error = str(exc)
            last_code = raw
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": REPAIR_USER.format(
                        filename=filename,
                        code=raw[:4000],
                        error=last_error,
                        output="",
                        source=context["source"],
                    ),
                }
            )
            continue

        last_code = code
        syntax = python_syntax_error(code)
        if syntax:
            last_error = syntax
            last_output = ""
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": REPAIR_USER.format(
                        filename=filename,
                        code=code[:4000],
                        error=syntax,
                        output="",
                        source=context["source"],
                    ),
                }
            )
            continue

        outcome = run_pytest_source(code, repo_path, filename=filename)
        test = GeneratedTest(
            filename=filename,
            content=code,
            target_call_site=f"{site.file}:{site.lineno}",
        )
        apply_pytest_outcome(test, outcome, attempts)
        if outcome.passed:
            return test

        last_error = outcome.error or "pytest failed"
        last_output = outcome.output or ""
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": REPAIR_USER.format(
                    filename=filename,
                    code=code[:4000],
                    error=last_error,
                    output=last_output[:2500],
                    source=context["source"],
                ),
            }
        )

    return GeneratedTest(
        filename=filename,
        content=last_code,
        target_call_site=f"{site.file}:{site.lineno}",
        generated=bool(last_code.strip()),
        syntax_ok=python_syntax_error(last_code) is None if last_code else False,
        pytest_passed=False,
        pytest_output=last_output or None,
        attempts=attempts,
        error=last_error,
    )


def _test_filename(site: CallSite, index: int) -> str:
    caller = (site.caller_name or site.function_name or "path").strip()
    safe = "".join(ch if ch.isalnum() else "_" for ch in caller).strip("_") or "path"
    return f"test_ai_blast_radius_{safe}_{index}.py"
