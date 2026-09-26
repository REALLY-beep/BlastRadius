"""
AST-based blast-radius analysis.
The analyzer stays deliberately small, but keeps enough symbol information
to distinguish functions, methods, modules and real test entry points.
"""

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .models import AnalysisResult, CallSite, ChangedFunction


@dataclass
class DefinitionInfo:
    name: str
    qualname: str
    file: str
    module: str
    lineno: int
    end_lineno: int
    class_name: Optional[str]
    params: List[str]
    required_params: List[str]

    @property
    def key(self) -> Tuple[str, str]:
        return self.module, self.qualname

    @property
    def is_method(self) -> bool:
        return self.class_name is not None


@dataclass
class SourceIndex:
    definitions: List[DefinitionInfo]
    by_name: Dict[str, List[DefinitionInfo]]
    by_key: Dict[Tuple[str, str], DefinitionInfo]


def _module_name(rel_path: str) -> str:
    path = Path(rel_path).with_suffix("")
    parts = list(path.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_import_module(
    current_module: str,
    module: Optional[str],
    level: int,
) -> str:
    if level == 0:
        return module or ""

    package = current_module.split(".")[:-1]
    if level > 1:
        package = package[: max(0, len(package) - (level - 1))]

    if module:
        package.append(module)

    return ".".join(p for p in package if p)


def _parameter_names(node: ast.FunctionDef) -> Tuple[List[str], List[str]]:
    positional = list(node.args.posonlyargs) + list(node.args.args)

    params = [
        arg.arg
        for arg in positional
        if arg.arg not in {"self", "cls"}
    ]
    params.extend(arg.arg for arg in node.args.kwonlyargs)

    positional_defaults = len(node.args.defaults)

    required_positional = params[
        : max(0, len(params) - positional_defaults)
    ]

    required_kwonly = [
        arg.arg
        for arg, default in zip(
            node.args.kwonlyargs,
            node.args.kw_defaults,
        )
        if default is None and arg.arg not in {"self", "cls"}
    ]

    return params, required_positional + required_kwonly


class _DefinitionCollector(ast.NodeVisitor):
    def __init__(self, rel_path: str, module: str) -> None:
        self.rel_path = rel_path
        self.module = module
        self.scope: List[str] = []
        self.current_class: Optional[str] = None
        self.items: List[DefinitionInfo] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        previous_class = self.current_class

        self.current_class = (
            ".".join(self.scope + [node.name])
            or node.name
        )

        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

        self.current_class = previous_class

    def _visit_function(self, node: ast.FunctionDef) -> None:
        qualname = ".".join(self.scope + [node.name]) or node.name

        params, required = _parameter_names(node)

        self.items.append(
            DefinitionInfo(
                name=node.name,
                qualname=qualname,
                file=self.rel_path,
                module=self.module,
                lineno=node.lineno,
                end_lineno=getattr(
                    node,
                    "end_lineno",
                    node.lineno,
                ),
                class_name=self.current_class,
                params=params,
                required_params=required,
            )
        )

        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function


def _build_source_index(repo_path: str) -> SourceIndex:
    definitions: List[DefinitionInfo] = []

    for root, _, files in os.walk(repo_path):
        for filename in files:
            if not filename.endswith(".py"):
                continue

            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(
                full_path,
                repo_path,
            )

            try:
                with open(
                    full_path,
                    "r",
                    encoding="utf-8",
                ) as handle:
                    source = handle.read()

                tree = ast.parse(source)

            except (
                OSError,
                SyntaxError,
                UnicodeDecodeError,
            ):
                continue

            collector = _DefinitionCollector(
                rel_path,
                _module_name(rel_path),
            )

            collector.visit(tree)
            definitions.extend(collector.items)

    by_name: Dict[str, List[DefinitionInfo]] = {}
    by_key: Dict[Tuple[str, str], DefinitionInfo] = {}

    for definition in definitions:
        by_name.setdefault(
            definition.name,
            [],
        ).append(definition)

        by_key[definition.key] = definition

    return SourceIndex(
        definitions,
        by_name,
        by_key,
    )


def find_function_definitions(
    repo_path: str,
) -> Dict[str, List[Tuple[str, int]]]:
    """Return all function and method definitions grouped by short name."""
    index = _build_source_index(repo_path)

    return {
        name: [
            (item.file, item.lineno)
            for item in items
        ]
        for name, items in index.by_name.items()
    }


def extract_changed_functions_from_diff(
    diff_text: str,
) -> List[ChangedFunction]:
    """
    Parse a raw unified diff and identify the functions/methods whose bodies
    are touched by changed lines. Hunk context is used to recover a function
    name when the `def` line itself is unchanged.
    """
    changed: List[ChangedFunction] = []

    current_file = "unknown.py"
    old_line = new_line = 0

    hunk_context_defs_new: List[Tuple[int, str]] = []
    hunk_context_defs_old: List[Tuple[int, str]] = []

    def add(name: str, file: str, lineno: int) -> None:
        changed.append(
            ChangedFunction(
                name=name,
                file=file,
                lineno=max(0, lineno),
            )
        )

    for line in diff_text.splitlines():

        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            continue

        if line.startswith("--- "):
            continue

        match = re.match(
            r"^@@ -(\d+)(?:,\d+)? "
            r"\+(\d+)(?:,\d+)? @@(?:\s*(.*))?$",
            line,
        )

        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(2))

            hunk_context_defs_new = []
            hunk_context_defs_old = []

            context = (match.group(3) or "").strip()

            def_match = re.search(
                r"\b(?:async\s+)?def\s+"
                r"([A-Za-z_]\w*)\s*\(",
                context,
            )

            if (
                def_match
                and current_file.endswith(".py")
            ):
                name = def_match.group(1)

                add(
                    name,
                    current_file,
                    new_line,
                )

                hunk_context_defs_new.append(
                    (new_line, name)
                )

                hunk_context_defs_old.append(
                    (old_line, name)
                )

            continue

        if not current_file.endswith(".py") or not line:
            continue

        marker = line[0]

        if marker not in " +-":
            continue

        code = line[1:]

        def_match = re.search(
            r"\b(?:async\s+)?def\s+"
            r"([A-Za-z_]\w*)\s*\(",
            code,
        )

        if marker == " ":
            if def_match:
                name = def_match.group(1)

                hunk_context_defs_new.append(
                    (new_line, name)
                )

                hunk_context_defs_old.append(
                    (old_line, name)
                )

        elif marker in "+-":

            if def_match:
                line_no = (
                    new_line
                    if marker == "+"
                    else old_line
                )

                add(
                    def_match.group(1),
                    current_file,
                    line_no,
                )

            else:
                defs = (
                    hunk_context_defs_new
                    if marker == "+"
                    else hunk_context_defs_old
                )

                coordinate = (
                    new_line
                    if marker == "+"
                    else old_line
                )

                before = [
                    item
                    for item in defs
                    if item[0] <= coordinate
                ]

                if before:
                    add(
                        before[-1][1],
                        current_file,
                        before[-1][0],
                    )

        if marker == "+":
            new_line += 1

        elif marker == "-":
            old_line += 1

        else:
            old_line += 1
            new_line += 1

    unique: List[ChangedFunction] = []
    seen: Set[Tuple[str, str, int]] = set()

    for item in changed:
        key = (
            item.file,
            item.name,
            item.lineno,
        )

        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


def _dotted_name(
    node: ast.AST,
) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        left = _dotted_name(node.value)

        return (
            f"{left}.{node.attr}"
            if left
            else None
        )

    return None


def _file_context(
    tree: ast.AST,
    module: str,
) -> Tuple[
    Dict[str, str],
    Dict[str, str],
    Dict[str, str],
]:
    """Resolve imports and simple `obj = Class()` / `obj: Class` bindings."""
    module_aliases: Dict[str, str] = {}
    symbol_aliases: Dict[str, str] = {}
    variable_classes: Dict[str, str] = {}

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                module_aliases[
                    alias.asname or alias.name.split(".")[0]
                ] = alias.name

        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_import_module(
                module,
                node.module,
                node.level,
            )

            for alias in node.names:
                if alias.name != "*":
                    symbol_aliases[
                        alias.asname or alias.name
                    ] = (
                        f"{imported_module}.{alias.name}"
                        .strip(".")
                    )

        elif isinstance(node, ast.Assign):
            if (
                len(node.targets) == 1
                and isinstance(
                    node.targets[0],
                    ast.Name,
                )
                and isinstance(node.value, ast.Call)
            ):
                expression = _dotted_name(
                    node.value.func
                )

                if expression:
                    variable_classes[
                        node.targets[0].id
                    ] = expression

        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
        ):
            expression = _dotted_name(
                node.annotation
            )

            if expression:
                variable_classes[
                    node.target.id
                ] = expression

    return (
        module_aliases,
        symbol_aliases,
        variable_classes,
    )


def _class_key(
    expression: str,
    module: str,
    module_aliases: Dict[str, str],
    symbol_aliases: Dict[str, str],
) -> Tuple[str, str]:
    root = expression.split(".")[0]

    if root in symbol_aliases:
        imported = symbol_aliases[root]
        owner, name = imported.rsplit(".", 1)

        return owner, name

    if root in module_aliases:
        imported = module_aliases[root]
        remainder = ".".join(
            expression.split(".")[1:]
        )

        return imported, remainder

    return module, expression


def _resolve_call(
    call: ast.Call,
    module: str,
    current_class: Optional[str],
    module_aliases: Dict[str, str],
    symbol_aliases: Dict[str, str],
    variable_classes: Dict[str, str],
) -> Tuple[
    Optional[Tuple[str, str]],
    str,
    bool,
]:
    """Resolve the best-known `(module, qualname)` for a call."""

    if isinstance(call.func, ast.Name):
        name = call.func.id

        imported = symbol_aliases.get(name)

        if imported and "." in imported:
            owner, member = imported.rsplit(".", 1)

            return (
                (owner, member),
                name,
                False,
            )

        return (
            (module, name),
            name,
            False,
        )

    if not isinstance(call.func, ast.Attribute):
        return None, "", False

    attr = call.func.attr

    receiver = _dotted_name(
        call.func.value
    )

    if not receiver:
        return None, attr, True

    if receiver == "self" and current_class:
        return (
            (
                module,
                f"{current_class}.{attr}",
            ),
            attr,
            True,
        )

    root = receiver.split(".")[0]

    if root in variable_classes:
        owner_module, owner_name = _class_key(
            variable_classes[root],
            module,
            module_aliases,
            symbol_aliases,
        )

        return (
            (
                owner_module,
                f"{owner_name}.{attr}",
            ),
            attr,
            True,
        )

    if root in module_aliases:
        imported_module = module_aliases[root]

        remainder = ".".join(
            receiver.split(".")[1:]
            + [attr]
        )

        return (
            (imported_module, remainder),
            attr,
            True,
        )

    if root in symbol_aliases:
        imported = symbol_aliases[root]

        owner, name = imported.rsplit(".", 1)

        return (
            (
                owner,
                f"{name}.{attr}",
            ),
            attr,
            True,
        )

    if (
        current_class
        and root == current_class.split(".")[-1]
    ):
        return (
            (
                module,
                f"{current_class}.{attr}",
            ),
            attr,
            True,
        )

    return None, attr, True


class _CallCollector(ast.NodeVisitor):
    def __init__(
        self,
        rel_path: str,
        module: str,
        index: SourceIndex,
        changed: Set[Tuple[str, str]],
    ) -> None:
        self.rel_path = rel_path
        self.module = module
        self.index = index
        self.changed = changed

        self.lines: List[str] = []

        self.module_aliases: Dict[str, str] = {}
        self.symbol_aliases: Dict[str, str] = {}
        self.variable_classes: Dict[str, str] = {}

        self.scope: List[str] = []
        self.current_class: Optional[str] = None

        self.call_sites: List[CallSite] = []

    def configure(
        self,
        tree: ast.AST,
        source: str,
    ) -> None:
        (
            self.module_aliases,
            self.symbol_aliases,
            self.variable_classes,
        ) = _file_context(
            tree,
            self.module,
        )

        self.lines = source.splitlines()

        self.visit(tree)

    def visit_ClassDef(
        self,
        node: ast.ClassDef,
    ) -> None:
        previous_class = self.current_class

        self.current_class = (
            ".".join(self.scope + [node.name])
            or node.name
        )

        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

        self.current_class = previous_class

    def _visit_function(
        self,
        node: ast.FunctionDef,
    ) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Call(
        self,
        node: ast.Call,
    ) -> None:
        (
            target_key,
            function_name,
            _,
        ) = _resolve_call(
            node,
            self.module,
            self.current_class,
            self.module_aliases,
            self.symbol_aliases,
            self.variable_classes,
        )

        if function_name not in self.index.by_name:
            self.generic_visit(node)
            return

        candidates = [
            definition.key
            for definition
            in self.index.by_name[function_name]
            if definition.key in self.changed
        ]

        if target_key is not None:
            if target_key not in candidates:
                self.generic_visit(node)
                return

            matched_key = target_key

        elif len(candidates) == 1:
            matched_key = candidates[0]

        else:
            self.generic_visit(node)
            return

        caller = self._caller_definition()

        code_line = (
            self.lines[node.lineno - 1].strip()
            if 0 < node.lineno <= len(self.lines)
            else ""
        )

        self.call_sites.append(
            CallSite(
                file=self.rel_path,
                lineno=node.lineno,
                function_name=function_name,
                code_line=code_line,
                caller_name=(
                    caller.name
                    if caller
                    else None
                ),
                caller_qualname=(
                    caller.qualname
                    if caller
                    else "<module>"
                ),
                target_qualname=matched_key[1],
                module=self.module,
                target_module=matched_key[0],
                caller_params=(
                    caller.required_params
                    if caller
                    else []
                ),
                caller_is_method=(
                    caller.is_method
                    if caller
                    else False
                ),
            )
        )

        self.generic_visit(node)

    def _caller_definition(
        self,
    ) -> Optional[DefinitionInfo]:
        if not self.scope:
            return None

        return self.index.by_key.get(
            (
                self.module,
                ".".join(self.scope),
            )
        )


def _collect_call_sites(
    repo_path: str,
    index: SourceIndex,
    changed: Set[Tuple[str, str]],
) -> List[CallSite]:
    call_sites: List[CallSite] = []

    for root, _, files in os.walk(repo_path):
        for filename in files:

            if not filename.endswith(".py"):
                continue

            full_path = os.path.join(
                root,
                filename,
            )

            rel_path = os.path.relpath(
                full_path,
                repo_path,
            )

            try:
                with open(
                    full_path,
                    "r",
                    encoding="utf-8",
                ) as handle:
                    source = handle.read()

                tree = ast.parse(source)

            except (
                OSError,
                SyntaxError,
                UnicodeDecodeError,
            ):
                continue

            collector = _CallCollector(
                rel_path,
                _module_name(rel_path),
                index,
                changed,
            )

            collector.configure(
                tree,
                source,
            )

            call_sites.extend(
                collector.call_sites
            )

    return call_sites


def find_call_sites(
    repo_path: str,
    function_names: Set[str],
) -> List[CallSite]:
    """Find calls to changed functions and methods across the repository."""
    index = _build_source_index(repo_path)

    changed = {
        definition.key
        for name in function_names
        for definition in index.by_name.get(
            name,
            [],
        )
    }

    return _collect_call_sites(
        repo_path,
        index,
        changed,
    )


def _is_test_file(path: str) -> bool:
    name = os.path.basename(path)

    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "tests" in Path(path).parts
    )


def _collect_test_entries(
    repo_path: str,
    index: SourceIndex,
) -> Set[Tuple[str, str]]:
    """Collect callable production entries actually invoked by test files."""
    entries: Set[Tuple[str, str]] = set()

    for root, _, files in os.walk(repo_path):
        for filename in files:

            if not filename.endswith(".py"):
                continue

            rel_path = os.path.relpath(
                os.path.join(root, filename),
                repo_path,
            )

            if not _is_test_file(rel_path):
                continue

            full_path = os.path.join(
                root,
                filename,
            )

            try:
                with open(
                    full_path,
                    "r",
                    encoding="utf-8",
                ) as handle:
                    source = handle.read()

                tree = ast.parse(source)

            except (
                OSError,
                SyntaxError,
                UnicodeDecodeError,
            ):
                continue

            module = _module_name(rel_path)

            (
                module_aliases,
                symbol_aliases,
                variable_classes,
            ) = _file_context(
                tree,
                module,
            )

            class Visitor(ast.NodeVisitor):
                current_class: Optional[str] = None

                def visit_ClassDef(
                    self,
                    node: ast.ClassDef,
                ) -> None:
                    previous = self.current_class
                    self.current_class = node.name
                    self.generic_visit(node)
                    self.current_class = previous

                def visit_Call(
                    self,
                    node: ast.Call,
                ) -> None:
                    key, _, _ = _resolve_call(
                        node,
                        module,
                        self.current_class,
                        module_aliases,
                        symbol_aliases,
                        variable_classes,
                    )

                    if key in index.by_key:
                        entries.add(key)

                    self.generic_visit(node)

            Visitor().visit(tree)

    return entries


def mark_tested_call_sites(
    call_sites: List[CallSite],
    repo_path: str,
) -> List[CallSite]:
    """
    Consider a production call site covered only if a test invokes its caller.

    Directly testing the changed function itself is not enough to mark
    `checkout() -> changed_function()` as covered.
    """
    index = _build_source_index(repo_path)
    test_entries = _collect_test_entries(
        repo_path,
        index,
    )

    for site in call_sites:

        if _is_test_file(site.file):
            site.is_tested = True
            site.risk_score = 5
            site.risk = "low"
            site.coverage_reason = (
                "call site is inside a test file"
            )
            continue

        caller_key = (
            site.module,
            site.caller_qualname
            or "<module>",
        )

        if caller_key in test_entries:
            site.is_tested = True
            site.risk_score = 10
            site.risk = "low"
            site.coverage_reason = (
                "a test invokes the caller"
            )
        else:
            site.is_tested = False
            site.coverage_reason = (
                "no test entry point for the caller "
                "was found"
            )

    target_fanout: Dict[
        Tuple[Optional[str], Optional[str]],
        int,
    ] = {}

    for site in call_sites:
        key = (
            site.target_module,
            site.target_qualname,
        )

        target_fanout[key] = (
            target_fanout.get(key, 0) + 1
        )

    for site in call_sites:

        if site.is_tested:
            continue

        score = 45

        if site.module != site.target_module:
            score += 10

        if site.caller_is_method:
            score += 10

        if (
            site.caller_name
            and not site.caller_name.startswith("_")
        ):
            score += 10

        score += min(
            15,
            max(
                0,
                target_fanout.get(
                    (
                        site.target_module,
                        site.target_qualname,
                    ),
                    1,
                )
                - 1,
            )
            * 5,
        )

        site.risk_score = min(
            100,
            score,
        )

        site.risk = (
            "high"
            if site.risk_score >= 70
            else "medium"
        )

    return call_sites


def calculate_risk_score(
    call_sites: List[CallSite],
) -> int:
    """Combine per-call exposure into one bounded 0..100 score."""
    untested = [
        site
        for site in call_sites
        if not site.is_tested
    ]

    if not untested:
        return 0

    highest = max(
        site.risk_score
        for site in untested
    )

    breadth_bonus = min(
        25,
        max(
            0,
            len(untested) - 1,
        )
        * 8,
    )

    file_bonus = min(
        10,
        len(
            {
                site.file
                for site in untested
                if site.file
            }
        )
        * 2,
    )

    return min(
        100,
        highest
        + breadth_bonus
        + file_bonus,
    )


def _resolve_changed_definitions(
    index: SourceIndex,
    changed_functions: List[ChangedFunction],
) -> List[ChangedFunction]:
    resolved: List[ChangedFunction] = []

    for changed in changed_functions:

        candidates = [
            definition
            for definition in index.by_name.get(
                changed.name,
                [],
            )
            if definition.file == changed.file
        ]

        selected: Optional[DefinitionInfo] = None

        if changed.lineno:
            in_range = [
                definition
                for definition in candidates
                if (
                    definition.lineno
                    <= changed.lineno
                    <= definition.end_lineno
                )
            ]

            if in_range:
                selected = min(
                    in_range,
                    key=lambda definition:
                        abs(
                            definition.lineno
                            - changed.lineno
                        ),
                )

        if selected is None and candidates:
            selected = min(
                candidates,
                key=lambda definition:
                    abs(
                        definition.lineno
                        - changed.lineno
                    ),
            )

        if selected is None:
            candidates = index.by_name.get(
                changed.name,
                [],
            )

            if len(candidates) == 1:
                selected = candidates[0]

        if selected:
            resolved.append(
                changed.model_copy(
                    update={
                        "file": selected.file,
                        "lineno": selected.lineno,
                        "end_lineno": selected.end_lineno,
                    }
                )
            )
        else:
            resolved.append(changed)

    return resolved


def analyze_local_repo(
    repo_path: str,
    changed_function_names: List[str],
    changed_functions: Optional[
        List[ChangedFunction]
    ] = None,
) -> AnalysisResult:
    """Run the full local repository analysis."""
    index = _build_source_index(repo_path)

    if changed_functions is None:
        changed_functions = [
            ChangedFunction(
                name=name,
                file=(
                    index.by_name[name][0].file
                    if index.by_name.get(name)
                    else "(from diff)"
                ),
                lineno=(
                    index.by_name[name][0].lineno
                    if index.by_name.get(name)
                    else 0
                ),
                end_lineno=(
                    index.by_name[name][0].end_lineno
                    if index.by_name.get(name)
                    else None
                ),
            )
            for name in changed_function_names
        ]

    changed_functions = _resolve_changed_definitions(
        index,
        changed_functions,
    )

    changed_keys: Set[
        Tuple[str, str]
    ] = set()

    for changed in changed_functions:

        candidates = [
            definition
            for definition in index.by_name.get(
                changed.name,
                [],
            )
            if definition.file == changed.file
        ]

        if changed.lineno:
            candidates = [
                definition
                for definition in candidates
                if (
                    definition.lineno
                    <= changed.lineno
                    <= definition.end_lineno
                )
                or definition.lineno == changed.lineno
            ]

        if not candidates:
            candidates = index.by_name.get(
                changed.name,
                [],
            )

        if len(candidates) == 1:
            changed_keys.add(
                candidates[0].key
            )
        else:
            changed_keys.update(
                definition.key
                for definition in candidates
            )

    call_sites = _collect_call_sites(
        repo_path,
        index,
        changed_keys,
    )

    call_sites = mark_tested_call_sites(
        call_sites,
        repo_path,
    )

    untested_high_risk = [
        site
        for site in call_sites
        if (
            not site.is_tested
            and site.risk == "high"
        )
    ]

    risk_score = calculate_risk_score(
        call_sites
    )

    summary = (
        f"Found {len(call_sites)} call sites "
        f"for the changed functions. "
        f"{len(untested_high_risk)} high-risk "
        f"call sites appear untested. "
        f"Risk score: {risk_score}/100."
    )

    return AnalysisResult(
        changed_functions=changed_functions,
        call_sites=call_sites,
        untested_high_risk=untested_high_risk,
        generated_tests=[],
        summary=summary,
        risk_score=risk_score,
    )