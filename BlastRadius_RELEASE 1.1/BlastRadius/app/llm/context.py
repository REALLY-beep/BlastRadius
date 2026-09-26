"""Build a focused local context for the GGUF model. Never dump huge trees blindly."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set

MAX_TOTAL_CHARS = 28000
MAX_FILE_CHARS = 7000
MAX_DIFF_CHARS = 12000
MAX_FILES = 18

DIFF_FILE = re.compile(r"^\+\+\+ b/(.+)$")
DIFF_GIT = re.compile(r"^diff --git a/(.+) b/(.+)$")
DEF_NAME = re.compile(r"\b(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")


def files_from_diff(diff_text: str) -> List[str]:
    found: List[str] = []
    seen: Set[str] = set()
    for line in (diff_text or "").splitlines():
        git = DIFF_GIT.match(line)
        if git:
            path = git.group(2).replace("\\", "/").lstrip("./")
            if path not in seen:
                seen.add(path)
                found.append(path)
            continue
        match = DIFF_FILE.match(line)
        if match:
            path = match.group(1).replace("\\", "/").lstrip("./")
            if path not in seen:
                seen.add(path)
                found.append(path)
    return found


def names_from_diff(diff_text: str) -> List[str]:
    names: List[str] = []
    seen: Set[str] = set()
    for line in (diff_text or "").splitlines():
        match = DEF_NAME.search(line)
        if match:
            name = match.group(1)
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def looks_like_unified_diff(diff_text: str) -> bool:
    text = diff_text or ""
    return "diff --git " in text or "\n@@" in text or text.startswith("@@") or "\n--- " in text


def _is_test_file(path: Path) -> bool:
    name = path.name
    parts = set(path.parts)
    return name.startswith("test_") or name.endswith("_test.py") or "tests" in parts or "test" in parts


def _iter_python_files(repo: Path) -> Iterable[Path]:
    skip = {".git", ".venv", "venv", "__pycache__", "node_modules", ".tox"}
    for path in repo.rglob("*.py"):
        if any(part in skip for part in path.parts):
            continue
        yield path


def _read_capped(path: Path, limit: int = MAX_FILE_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n# ... truncated ...\n"


def _mentions(text: str, names: Sequence[str]) -> bool:
    return any(re.search(rf"\b{re.escape(name)}\b", text) for name in names)


def build_analysis_context(repo_path: str, diff_text: str) -> Dict[str, str]:
    repo = Path(repo_path)
    changed_files = files_from_diff(diff_text)
    names = names_from_diff(diff_text)
    selected: List[Path] = []
    seen: Set[str] = set()

    def add(path: Path) -> None:
        try:
            resolved = str(path.resolve())
        except OSError:
            return
        if resolved in seen or not path.is_file():
            return
        seen.add(resolved)
        selected.append(path)

    for relative in changed_files:
        candidate = repo / relative
        if candidate.is_file():
            add(candidate)
        else:
            matches = list(repo.rglob(Path(relative).name))
            for match in matches[:2]:
                add(match)

    tests: List[Path] = []
    others: List[Path] = []
    for path in _iter_python_files(repo):
        if path.resolve() in {p.resolve() for p in selected if p.exists()}:
            continue
        try:
            snippet = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if names and not _mentions(snippet, names):
            continue
        if _is_test_file(path):
            tests.append(path)
        else:
            others.append(path)

    for path in others[:8] + tests[:6]:
        if len(selected) >= MAX_FILES:
            break
        add(path)

    source_parts: List[str] = []
    test_parts: List[str] = []
    modules: List[str] = []
    used = 0

    for path in selected:
        rel = path.relative_to(repo).as_posix()
        body = _read_capped(path)
        if not body:
            continue
        block = f"### {rel}\n{body}\n"
        if used + len(block) > MAX_TOTAL_CHARS:
            block = block[: max(0, MAX_TOTAL_CHARS - used)]
        if _is_test_file(path):
            test_parts.append(block)
        else:
            source_parts.append(block)
            modules.append(rel)
        used += len(block)
        if used >= MAX_TOTAL_CHARS:
            break

    diff = (diff_text or "")[:MAX_DIFF_CHARS]
    return {
        "diff": diff or "(empty diff)",
        "source": "\n".join(source_parts) or "(no matching source files)",
        "tests": "\n".join(test_parts) or "(no matching tests)",
        "modules": ", ".join(modules) if modules else "(unknown)",
    }
