"""Validate generated pytest files by parsing them and actually running pytest."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from .models import GeneratedTest


@dataclass
class PytestOutcome:
    syntax_ok: bool
    passed: Optional[bool]
    output: str
    error: Optional[str]


def validate_python_syntax(source: str) -> Optional[str]:
    if not source or not source.strip():
        return "Generated test was empty."
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg} (line {exc.lineno})"
    return None


def run_pytest_source(
    source: str,
    project_root: str,
    filename: str = "test_blast_radius_generated.py",
    timeout: int = 25,
) -> PytestOutcome:
    syntax_error = validate_python_syntax(source)
    if syntax_error:
        return PytestOutcome(syntax_ok=False, passed=False, output="", error=syntax_error)

    project = Path(project_root)
    with TemporaryDirectory(prefix="blastradius_pytest_") as temp_dir:
        test_path = Path(temp_dir) / filename
        test_path.write_text(source, encoding="utf-8")
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(project), existing) if part
        )
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env.pop("PYTEST_ADDOPTS", None)

        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "-p",
                    "no:cacheprovider",
                    "--rootdir",
                    str(Path(temp_dir)),
                    "-o",
                    "addopts=",
                    "-o",
                    "testpaths=",
                    str(test_path),
                ],
                cwd=str(Path(temp_dir)),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            output = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()
            return PytestOutcome(
                syntax_ok=True,
                passed=False,
                output=output,
                error=f"pytest timed out after {timeout}s",
            )
        except OSError as exc:
            return PytestOutcome(
                syntax_ok=True,
                passed=False,
                output="",
                error=f"Could not start pytest: {exc}",
            )

        output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        passed = completed.returncode == 0
        return PytestOutcome(
            syntax_ok=True,
            passed=passed,
            output=output,
            error=None if passed else "pytest failed",
        )


def apply_pytest_outcome(test: GeneratedTest, outcome: PytestOutcome, attempts: int) -> GeneratedTest:
    test.syntax_ok = outcome.syntax_ok
    test.pytest_passed = outcome.passed
    test.pytest_output = outcome.output or None
    test.attempts = attempts
    test.error = outcome.error
    test.generated = True
    return test


def apply_pytest_to_tests(tests: list[GeneratedTest], project_root: str) -> list[GeneratedTest]:
    updated: list[GeneratedTest] = []
    for test in tests:
        outcome = run_pytest_source(test.content, project_root, filename=test.filename)
        updated.append(apply_pytest_outcome(test, outcome, attempts=1))
    return updated


def summarize_test_runs(tests: list[GeneratedTest]) -> str:
    if not tests:
        return "No tests generated."
    passed = sum(1 for test in tests if test.pytest_passed is True)
    failed = sum(1 for test in tests if test.pytest_passed is False)
    pending = len(tests) - passed - failed
    if failed == 0 and pending == 0:
        return f"{passed} pytest file(s) passed"
    if passed == 0 and pending == 0:
        return f"{failed} pytest file(s) failed"
    return f"{passed} passed, {failed} failed, {pending} not run"

