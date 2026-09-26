"""
Core blast-radius analysis logic.
This is the heart of the project – designed so IBM Bob can easily extend it.
"""

import ast
import os
import re
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from .models import ChangedFunction, CallSite, AnalysisResult, GeneratedTest


def extract_changed_functions_from_diff(diff_text: str) -> List[ChangedFunction]:
    """
    Very simplified diff parser.
    Looks for lines that start with '+' and contain 'def '.
    In a real version Bob would make this much smarter (using gitpython + ast).
    """
    changed = []
    current_file = "unknown.py"

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
        elif line.startswith("+") and "def " in line:
            # crude extraction
            match = re.search(r"def\s+(\w+)\s*\(", line)
            if match:
                changed.append(ChangedFunction(
                    name=match.group(1),
                    file=current_file,
                    lineno=0  # we don't have real line numbers from pure diff easily
                ))
    return changed


def find_function_definitions(repo_path: str) -> Dict[str, List[Tuple[str, int]]]:
    """
    Walk the repository and collect all function definitions.
    Returns: {function_name: [(file, lineno), ...]}
    """
    definitions: Dict[str, List[Tuple[str, int]]] = {}

    for root, _, files in os.walk(repo_path):
        for file in files:
            if not file.endswith(".py"):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, repo_path)

            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        definitions.setdefault(node.name, []).append((rel_path, node.lineno))
            except Exception:
                # skip files that can't be parsed
                continue

    return definitions


def find_call_sites(repo_path: str, function_names: Set[str]) -> List[CallSite]:
    """
    Find all places where the given functions are called.
    """
    call_sites: List[CallSite] = []

    for root, _, files in os.walk(repo_path):
        for file in files:
            if not file.endswith(".py"):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, repo_path)

            # Skip test files for call-site discovery? 
            # Actually we want to know about them later.
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source)
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func_name = None
                        if isinstance(node.func, ast.Name):
                            func_name = node.func.id
                        elif isinstance(node.func, ast.Attribute):
                            func_name = node.func.attr

                        if func_name and func_name in function_names:
                            code_line = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                            call_sites.append(CallSite(
                                file=rel_path,
                                lineno=node.lineno,
                                function_name=func_name,
                                code_line=code_line,
                                is_tested=False,  # will be updated later
                                risk="medium"
                            ))
            except Exception:
                continue

    return call_sites


def mark_tested_call_sites(call_sites: List[CallSite], repo_path: str) -> List[CallSite]:
    """
    Very simple heuristic:
    If there is a test file that imports or mentions the same function name,
    we consider the call site "possibly tested".
    This is intentionally simple so Bob can improve it later.
    """
    test_files_content = []

    for root, _, files in os.walk(repo_path):
        for file in files:
            if file.startswith("test_") or file.endswith("_test.py"):
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        test_files_content.append(f.read())
                except Exception:
                    pass

    combined_tests = "\n".join(test_files_content)

    for site in call_sites:
        # crude check
        if site.function_name in combined_tests:
            site.is_tested = True
            site.risk = "low"
        else:
            site.is_tested = False
            # higher risk if the call is not in a test file itself
            if "test_" not in site.file:
                site.risk = "high"
            else:
                site.risk = "medium"

    return call_sites


def calculate_risk_score(call_sites: List[CallSite]) -> int:
    if not call_sites:
        return 10  # almost nothing changed

    high = sum(1 for c in call_sites if c.risk == "high" and not c.is_tested)
    medium = sum(1 for c in call_sites if c.risk == "medium" and not c.is_tested)

    score = min(100, high * 25 + medium * 10)
    return score


def analyze_local_repo(repo_path: str, changed_function_names: List[str]) -> AnalysisResult:
    """
    Main entry point for local analysis.
    """
    function_set = set(changed_function_names)

    call_sites = find_call_sites(repo_path, function_set)
    call_sites = mark_tested_call_sites(call_sites, repo_path)

    untested_high_risk = [c for c in call_sites if c.risk == "high" and not c.is_tested]

    risk_score = calculate_risk_score(call_sites)

    summary = (
        f"Found {len(call_sites)} call sites for the changed functions. "
        f"{len(untested_high_risk)} of them are high-risk and appear untested."
    )

    return AnalysisResult(
        changed_functions=[ChangedFunction(name=n, file="(from diff)", lineno=0) for n in changed_function_names],
        call_sites=call_sites,
        untested_high_risk=untested_high_risk,
        generated_tests=[],  # filled later by test_generator
        summary=summary,
        risk_score=risk_score
    )