"""AST-based blast-radius analysis for Python repositories."""

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .models import AnalysisResult, CallSite, ChangedFunction


@dataclass
class Definition:
    name: str
    qualname: str
    file: str
    module: str
    lineno: int
    end_lineno: int
    class_name: Optional[str]
    params: List[str]
    required_params: List[str]
    return_type: Optional[str]
    is_test_file: bool
    is_test_entry: bool

    @property
    def key(self) -> Tuple[str, str]:
        return self.module, self.qualname

    @property
    def is_method(self) -> bool:
        return self.class_name is not None


@dataclass
class CallRecord:
    source: Optional[Tuple[str, str]]
    target: Optional[Tuple[str, str]]
    file: str
    lineno: int
    function_name: str
    code_line: str
    patch_target: Optional[str]


@dataclass
class FileInfo:
    path: str
    module: str
    source: str
    tree: ast.Module
    module_aliases: Dict[str, str]
    symbol_aliases: Dict[str, str]
    variable_classes: Dict[str, str]


@dataclass
class ProjectIndex:
    definitions: List[Definition]
    by_key: Dict[Tuple[str, str], Definition]
    by_name: Dict[str, List[Definition]]
    files: List[FileInfo]
    edges: List[CallRecord]
    module_roots: Set[Tuple[str, str]]


DIFF_HUNK = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:\s*(.*))?$"
)
DEF_PATTERN = re.compile(
    r"\b(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("
)


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _module_name(rel_path: str) -> str:
    parts = Path(_normalize_path(rel_path)).with_suffix("").parts
    parts = list(parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(part for part in parts if part not in {"", "."})


def _is_test_file(path: str) -> bool:
    parts = Path(_normalize_path(path)).parts
    name = parts[-1] if parts else path
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "tests" in parts
    )


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _is_test_entry(node: ast.FunctionDef, is_test_file: bool) -> bool:
    if node.name.startswith("test_"):
        return True
    for decorator in node.decorator_list:
        name = _decorator_name(decorator)
        if name in {"pytest.fixture", "fixture", "pytest.mark.parametrize"}:
            return name != "pytest.mark.parametrize" or node.name.startswith("test_")
    return False


def _dotted_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _dotted_name(node.value)
        return f"{left}.{node.attr}" if left else None
    return None


def _parameter_info(node: ast.FunctionDef) -> Tuple[List[str], List[str]]:
    args = list(node.args.posonlyargs) + list(node.args.args)
    names = [arg.arg for arg in args if arg.arg not in {"self", "cls"}]
    names.extend(arg.arg for arg in node.args.kwonlyargs if arg.arg not in {"self", "cls"})

    default_count = len(node.args.defaults)
    positional_required = names[: max(0, len(names) - default_count)]
    keyword_required = [
        arg.arg
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
        if default is None and arg.arg not in {"self", "cls"}
    ]
    return names, positional_required + keyword_required


def _annotation_text(annotation: Optional[ast.expr]) -> Optional[str]:
    if annotation is None:
        return None
    try:
        return ast.unparse(annotation)
    except Exception:
        return None


def _resolve_import_module(current_module: str, module: Optional[str], level: int) -> str:
    if level == 0:
        return module or ""
    package = current_module.split(".")[:-1]
    if level > 1:
        package = package[: max(0, len(package) - (level - 1))]
    if module:
        package.append(module)
    return ".".join(p for p in package if p)


def _file_context(tree: ast.Module, module: str) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    module_aliases: Dict[str, str] = {}
    symbol_aliases: Dict[str, str] = {}
    variable_classes: Dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_aliases[alias.asname or alias.name.split(".")[0]] = alias.name

        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_import_module(module, node.module, node.level)
            for alias in node.names:
                if alias.name != "*":
                    symbol_aliases[alias.asname or alias.name] = f"{imported_module}.{alias.name}".strip(".")

        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                expression = _dotted_name(node.value.func)
                if expression:
                    variable_classes[node.targets[0].id] = expression

        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            expression = _dotted_name(node.annotation)
            if expression:
                variable_classes[node.target.id] = expression

    return module_aliases, symbol_aliases, variable_classes


def _collect_definitions(files: List[FileInfo]) -> Tuple[List[Definition], Dict[Tuple[str, str], Definition], Dict[str, List[Definition]]]:
    definitions: List[Definition] = []

    class Collector(ast.NodeVisitor):
        def __init__(self, info: FileInfo) -> None:
            self.info = info
            self.scope: List[str] = []
            self.current_class: Optional[str] = None

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            previous = self.current_class
            self.scope.append(node.name)
            self.current_class = ".".join(self.scope)
            self.generic_visit(node)
            self.scope.pop()
            self.current_class = previous

        def _function(self, node: ast.FunctionDef) -> None:
            qualname = ".".join(self.scope + [node.name]) or node.name
            params, required = _parameter_info(node)
            definitions.append(
                Definition(
                    name=node.name,
                    qualname=qualname,
                    file=self.info.path,
                    module=self.info.module,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", node.lineno),
                    class_name=self.current_class,
                    params=params,
                    required_params=required,
                    return_type=_annotation_text(node.returns),
                    is_test_file=_is_test_file(self.info.path),
                    is_test_entry=_is_test_entry(node, _is_test_file(self.info.path)),
                )
            )
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        visit_FunctionDef = _function
        visit_AsyncFunctionDef = _function

    for info in files:
        Collector(info).visit(info.tree)

    by_key = {definition.key: definition for definition in definitions}
    by_name: Dict[str, List[Definition]] = {}
    for definition in definitions:
        by_name.setdefault(definition.name, []).append(definition)
    return definitions, by_key, by_name


def _class_reference(expression: str, module: str, module_aliases: Dict[str, str], symbol_aliases: Dict[str, str]) -> Tuple[str, str]:
    root = expression.split(".", 1)[0]
    if root in symbol_aliases:
        imported = symbol_aliases[root]
        if "." in imported:
            owner, class_name = imported.rsplit(".", 1)
            return owner, class_name
    if root in module_aliases:
        imported_module = module_aliases[root]
        rest = expression.split(".", 1)[1] if "." in expression else ""
        return imported_module, rest or root
    return module, expression


def _resolve_call(
    call: ast.Call,
    info: FileInfo,
    current_scope: Optional[Tuple[str, str]],
    index: ProjectIndex,
) -> Tuple[Optional[Tuple[str, str]], str, Optional[str]]:
    func = call.func

    if isinstance(func, ast.Name):
        name = func.id
        imported = info.symbol_aliases.get(name)
        if imported and "." in imported:
            owner, member = imported.rsplit(".", 1)
            return (owner, member), name, f"{info.module}.{name}"

        same_module = (info.module, name)
        if same_module in index.by_key:
            return same_module, name, f"{info.module}.{name}"

        candidates = index.by_name.get(name, [])
        if len(candidates) == 1:
            return candidates[0].key, name, info.module

        return None, name, None

    if not isinstance(func, ast.Attribute):
        return None, "", None

    name = func.attr
    receiver = _dotted_name(func.value)
    if not receiver:
        return None, name, None

    if receiver == "self" and current_scope:
        module, qualname = current_scope
        owner = qualname.rsplit(".", 1)[0] if "." in qualname else None
        if owner:
            key = (module, f"{owner}.{name}")
            if key in index.by_key:
                return key, name, f"{info.module}.{owner}.{name}"
        return None, name, None

    root = receiver.split(".")[0]
    if root in info.variable_classes:
        owner_module, class_name = _class_reference(
            info.variable_classes[root],
            info.module,
            info.module_aliases,
            info.symbol_aliases,
        )
        key = (owner_module, f"{class_name}.{name}")
        if key in index.by_key:
            patch_owner = f"{info.module}.{class_name}" if owner_module == info.module else f"{owner_module}.{class_name}"
            return key, name, f"{patch_owner}.{name}"

    if root in info.module_aliases:
        imported_module = info.module_aliases[root]
        rest = receiver.split(".")[1:]
        qualname = ".".join(rest + [name])
        key = (imported_module, qualname)
        if key in index.by_key:
            return key, name, f"{info.module}.{root}.{name}"

    if root in info.symbol_aliases:
        imported = info.symbol_aliases[root]
        owner_module, class_name = imported.rsplit(".", 1)
        key = (owner_module, f"{class_name}.{name}")
        if key in index.by_key:
            return key, name, f"{info.module}.{root}.{name}"

    # Class.method() in the current module or an imported class.
    if "." not in receiver and current_scope:
        key = (info.module, f"{receiver}.{name}")
        if key in index.by_key:
            return key, name, f"{info.module}.{receiver}.{name}"

    if "." not in receiver:
        candidates = [d for d in index.by_name.get(name, []) if d.is_method and d.qualname.endswith(f".{name}")]
        if len(candidates) == 1:
            return candidates[0].key, name, f"{candidates[0].module}.{candidates[0].class_name}"

    return None, name, None


def _index_calls(files: List[FileInfo], definitions: List[Definition], by_key: Dict[Tuple[str, str], Definition], by_name: Dict[str, List[Definition]]) -> Tuple[List[CallRecord], Set[Tuple[str, str]]]:
    placeholder = ProjectIndex(definitions, by_key, by_name, files, [], set())
    edges: List[CallRecord] = []
    module_roots: Set[Tuple[str, str]] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self, info: FileInfo) -> None:
            self.info = info
            self.scope: List[str] = []
            self.class_scope: Optional[str] = None
            self.current_definition: Optional[Tuple[str, str]] = None

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            previous = self.class_scope
            self.scope.append(node.name)
            self.class_scope = ".".join(self.scope)
            self.generic_visit(node)
            self.scope.pop()
            self.class_scope = previous

        def _function(self, node: ast.FunctionDef) -> None:
            previous = self.current_definition
            self.scope.append(node.name)
            self.current_definition = (self.info.module, ".".join(self.scope))
            self.generic_visit(node)
            self.scope.pop()
            self.current_definition = previous

        visit_FunctionDef = _function
        visit_AsyncFunctionDef = _function

        def visit_Call(self, node: ast.Call) -> None:
            target, name, patch_target = _resolve_call(
                node,
                self.info,
                self.current_definition,
                placeholder,
            )
            line = self.info.source.splitlines()
            code_line = line[node.lineno - 1].strip() if 0 < node.lineno <= len(line) else ""
            edges.append(
                CallRecord(
                    source=self.current_definition,
                    target=target,
                    file=self.info.path,
                    lineno=node.lineno,
                    function_name=name,
                    code_line=code_line,
                    patch_target=patch_target,
                )
            )
            if _is_test_file(self.info.path) and self.current_definition is None and target:
                module_roots.add(target)
            self.generic_visit(node)

    for info in files:
        Visitor(info).visit(info.tree)

    return edges, module_roots


def _load_project(repo_path: str) -> ProjectIndex:
    files: List[FileInfo] = []
    for root, _, names in os.walk(repo_path):
        for filename in names:
            if not filename.endswith(".py"):
                continue
            full = os.path.join(root, filename)
            rel = _normalize_path(os.path.relpath(full, repo_path))
            try:
                with open(full, "r", encoding="utf-8") as handle:
                    source = handle.read()
                tree = ast.parse(source)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            module = _module_name(rel)
            module_aliases, symbol_aliases, variable_classes = _file_context(tree, module)
            files.append(FileInfo(rel, module, source, tree, module_aliases, symbol_aliases, variable_classes))

    definitions, by_key, by_name = _collect_definitions(files)
    edges, module_roots = _index_calls(files, definitions, by_key, by_name)
    return ProjectIndex(definitions, by_key, by_name, files, edges, module_roots)


def extract_changed_functions_from_diff(diff_text: str) -> List[ChangedFunction]:
    """Extract changed Python functions from a unified diff, including changed bodies."""
    changed: List[ChangedFunction] = []
    current_file: Optional[str] = None
    old_line = 0
    new_line = 0
    context_name: Optional[str] = None
    context_new_line = 0
    context_old_line = 0

    def add(name: str, file: str, line: int) -> None:
        changed.append(ChangedFunction(name=name, file=_normalize_path(file), lineno=max(line, 0)))

    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_file = _normalize_path(raw[6:].strip())
            continue
        if raw.startswith("--- "):
            continue

        hunk = DIFF_HUNK.match(raw)
        if hunk:
            old_line = int(hunk.group(1))
            new_line = int(hunk.group(3))
            context_name = None
            context_new_line = new_line
            context_old_line = old_line
            context = (hunk.group(5) or "").strip()
            match = DEF_PATTERN.search(context)
            if match:
                context_name = match.group(1)
                if current_file and current_file.endswith(".py"):
                    add(context_name, current_file, new_line)
            continue

        if current_file is None or not current_file.endswith(".py") or not raw:
            continue

        marker = raw[0]
        code = raw[1:] if marker in " +-" else raw
        match = DEF_PATTERN.search(code)

        if marker in "+-" and match:
            add(match.group(1), current_file, new_line if marker == "+" else old_line)
        elif marker in "+-" and context_name:
            add(context_name, current_file, new_line if marker == "+" else old_line)

        if marker == "+":
            new_line += 1
        elif marker == "-":
            old_line += 1
        elif marker == " ":
            old_line += 1
            new_line += 1
            if match:
                context_name = match.group(1)
                context_new_line = new_line - 1
                context_old_line = old_line - 1

    unique: List[ChangedFunction] = []
    seen: Set[Tuple[str, str, int]] = set()
    for item in changed:
        key = (item.file, item.name, item.lineno)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def find_function_definitions(repo_path: str) -> Dict[str, List[Tuple[str, int]]]:
    index = _load_project(repo_path)
    return {
        name: [(d.file, d.lineno) for d in definitions]
        for name, definitions in index.by_name.items()
    }


def _resolve_changed_keys(index: ProjectIndex, changed: Iterable[ChangedFunction]) -> Tuple[List[ChangedFunction], Set[Tuple[str, str]]]:
    resolved: List[ChangedFunction] = []
    keys: Set[Tuple[str, str]] = set()

    for item in changed:
        candidates = [d for d in index.by_name.get(item.name, []) if _normalize_path(d.file) == _normalize_path(item.file)]
        if not candidates:
            candidates = index.by_name.get(item.name, [])

        selected: Optional[Definition] = None
        if candidates and item.lineno:
            in_range = [d for d in candidates if d.lineno <= item.lineno <= d.end_lineno]
            if in_range:
                selected = min(in_range, key=lambda d: abs(d.lineno - item.lineno))
        if selected is None and len(candidates) == 1:
            selected = candidates[0]
        if selected is None and candidates:
            selected = min(candidates, key=lambda d: abs(d.lineno - item.lineno))

        if selected:
            resolved.append(
                item.model_copy(update={
                    "file": selected.file,
                    "lineno": selected.lineno,
                    "end_lineno": selected.end_lineno,
                })
            )
            keys.add(selected.key)
        else:
            resolved.append(item)

    return resolved, keys


def _changed_call_records(index: ProjectIndex, changed_keys: Set[Tuple[str, str]]) -> List[Tuple[CallRecord, Definition]]:
    result: List[Tuple[CallRecord, Definition]] = []
    for edge in index.edges:
        if edge.target in changed_keys and edge.source:
            source = index.by_key.get(edge.source)
            if source:
                result.append((edge, source))
    return result


def find_call_sites(repo_path: str, function_names: Set[str]) -> List[CallSite]:
    index = _load_project(repo_path)
    changed_keys = {
        d.key
        for name in function_names
        for d in index.by_name.get(name, [])
    }
    return _make_call_sites(index, changed_keys)


def _make_call_sites(index: ProjectIndex, changed_keys: Set[Tuple[str, str]]) -> List[CallSite]:
    sites: List[CallSite] = []
    for edge, caller in _changed_call_records(index, changed_keys):
        target = index.by_key.get(edge.target) if edge.target else None
        sites.append(
            CallSite(
                file=caller.file,
                lineno=edge.lineno,
                function_name=edge.function_name,
                code_line=edge.code_line,
                caller_name=caller.name,
                caller_qualname=caller.qualname,
                target_qualname=target.qualname if target else None,
                module=caller.module,
                target_module=target.module if target else None,
                caller_params=caller.required_params,
                caller_is_method=caller.is_method,
                patch_target=edge.patch_target,
            )
        )

    # Keep direct calls inside tests visible too.
    for edge in index.edges:
        if edge.target not in changed_keys or edge.source is not None:
            continue
        file_info = next((f for f in index.files if f.path == edge.file), None)
        if not file_info or not _is_test_file(file_info.path):
            continue
        target = index.by_key.get(edge.target)
        if target:
            sites.append(
                CallSite(
                    file=file_info.path,
                    lineno=edge.lineno,
                    function_name=edge.function_name,
                    code_line=edge.code_line,
                    caller_name=None,
                    caller_qualname="<module>",
                    target_qualname=target.qualname,
                    module=file_info.module,
                    target_module=target.module,
                    caller_params=[],
                    caller_is_method=False,
                    patch_target=edge.patch_target,
                )
            )

    unique: List[CallSite] = []
    seen: Set[Tuple[str, int, str, Optional[str]]] = set()
    for site in sites:
        key = (site.file, site.lineno, site.function_name, site.caller_qualname)
        if key not in seen:
            seen.add(key)
            unique.append(site)
    return unique


def _test_reachable_nodes(index: ProjectIndex) -> Set[Tuple[str, str]]:
    graph: Dict[Tuple[str, str], Set[Tuple[str, str]]] = {}
    for edge in index.edges:
        if edge.source and edge.target and edge.target in index.by_key:
            graph.setdefault(edge.source, set()).add(edge.target)

    roots = {
        d.key
        for d in index.definitions
        if d.is_test_entry
    }
    roots.update(index.module_roots)

    reachable: Set[Tuple[str, str]] = set(roots)
    stack = list(roots)
    while stack:
        node = stack.pop()
        for child in graph.get(node, set()):
            if child not in reachable:
                reachable.add(child)
                stack.append(child)
    return reachable


def calculate_risk_score(call_sites: List[CallSite]) -> int:
    """Calculate a bounded 0..100 score from exposed, untested call sites."""
    if not call_sites:
        return 0

    untested = [site for site in call_sites if not site.is_tested]
    if not untested:
        return 0

    highest = max(site.risk_score for site in untested)
    mean = sum(site.risk_score for site in untested) / len(untested)
    breadth = min(20, max(0, len(untested) - 1) * 6)
    return min(100, round(highest * 0.65 + mean * 0.35 + breadth))


def mark_tested_call_sites(call_sites: List[CallSite], repo_path: str) -> List[CallSite]:
    index = _load_project(repo_path)
    reachable = _test_reachable_nodes(index)

    fanout: Dict[Tuple[Optional[str], Optional[str]], int] = {}
    for site in call_sites:
        key = (site.target_module, site.target_qualname)
        fanout[key] = fanout.get(key, 0) + 1

    for site in call_sites:
        caller_key = (site.module or "", site.caller_qualname or "")
        if site.caller_qualname == "<module>" and _is_test_file(site.file):
            site.is_tested = True
            site.coverage_reason = "call appears directly in a test module"
        else:
            site.is_tested = caller_key in reachable
            site.coverage_reason = (
                "caller is reachable from a pytest entry point"
                if site.is_tested
                else "no pytest entry point reaches this caller"
            )

        if site.is_tested:
            site.risk_score = 10
            site.risk = "low"
            continue

        score = 55
        if site.module != site.target_module:
            score += 10
        if site.caller_is_method:
            score += 10
        if site.caller_name and not site.caller_name.startswith("_"):
            score += 10
        score += min(15, max(0, fanout.get((site.target_module, site.target_qualname), 1) - 1) * 5)

        site.risk_score = min(100, score)
        site.risk = "high" if site.risk_score >= 70 else "medium"

    return call_sites


def analyze_local_repo(
    repo_path: str,
    changed_function_names: List[str],
    changed_functions: Optional[List[ChangedFunction]] = None,
) -> AnalysisResult:
    index = _load_project(repo_path)

    if changed_functions is None:
        changed_functions = [
            ChangedFunction(
                name=name,
                file=index.by_name[name][0].file if index.by_name.get(name) else "(from diff)",
                lineno=index.by_name[name][0].lineno if index.by_name.get(name) else 0,
                end_lineno=index.by_name[name][0].end_lineno if index.by_name.get(name) else None,
            )
            for name in changed_function_names
        ]

    resolved, changed_keys = _resolve_changed_keys(index, changed_functions)
    call_sites = _make_call_sites(index, changed_keys)
    call_sites = mark_tested_call_sites(call_sites, repo_path)
    untested_high_risk = [site for site in call_sites if not site.is_tested and site.risk_score >= 60]
    risk_score = calculate_risk_score(call_sites)

    summary = (
        f"Found {len(resolved)} changed function(s), "
        f"{len(call_sites)} relevant call site(s), "
        f"and {len(untested_high_risk)} high-risk untested path(s)."
    )

    return AnalysisResult(
        changed_functions=resolved,
        call_sites=call_sites,
        untested_high_risk=untested_high_risk,
        generated_tests=[],
        summary=summary,
        risk_score=risk_score,
    )


def build_risk_explanation(result: AnalysisResult) -> str:
    """Deterministic explanation for AST mode. Does not use an LLM."""
    if not result.changed_functions:
        return "No changed functions were resolved against the selected project."
    names = ", ".join(item.name for item in result.changed_functions[:4])
    if not result.call_sites:
        return (
            f"{names} changed, but no callers were found in the selected project. "
            "The function may be unused, or the diff and checkout may be from different revisions."
        )
    untested = [site for site in result.call_sites if not site.is_tested]
    if not untested:
        return (
            f"{names} changed and every resolved caller is reachable from a pytest entry point "
            "in the source graph."
        )
    top = sorted(untested, key=lambda site: site.risk_score, reverse=True)[:3]
    bits = [
        f"{site.caller_qualname or site.caller_name or '<module>'} → {site.function_name}()"
        for site in top
    ]
    return (
        f"{names} sits on untested production path(s): "
        + "; ".join(bits)
        + ". Direct unit tests of the changed function do not cover those callers."
    )
