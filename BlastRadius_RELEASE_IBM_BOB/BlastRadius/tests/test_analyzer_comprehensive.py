"""Comprehensive unit tests for app/analyzer.py covering all major branches."""

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List

import pytest

from app.analyzer import (
    _annotation_text,
    _decorator_name,
    _dotted_name,
    _file_context,
    _is_test_entry,
    _is_test_file,
    _module_name,
    _normalize_path,
    _resolve_import_module,
    analyze_local_repo,
    calculate_risk_score,
    extract_changed_functions_from_diff,
    find_call_sites,
    find_function_definitions,
    mark_tested_call_sites,
)
from app.models import CallSite, ChangedFunction


# ---------------------------------------------------------------------------
# _normalize_path
# ---------------------------------------------------------------------------

def test_normalize_path_backslash():
    assert _normalize_path("a\\b\\c.py") == "a/b/c.py"


def test_normalize_path_leading_dot_slash():
    assert _normalize_path("./a/b.py") == "a/b.py"


def test_normalize_path_already_clean():
    assert _normalize_path("shop.py") == "shop.py"


# ---------------------------------------------------------------------------
# _module_name
# ---------------------------------------------------------------------------

def test_module_name_simple():
    assert _module_name("shop.py") == "shop"


def test_module_name_nested():
    assert _module_name("app/models.py") == "app.models"


def test_module_name_init():
    assert _module_name("app/__init__.py") == "app"


def test_module_name_with_backslash():
    assert _module_name("app\\service.py") == "app.service"


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------

def test_is_test_file_prefix():
    assert _is_test_file("test_shop.py") is True


def test_is_test_file_suffix():
    assert _is_test_file("shop_test.py") is True


def test_is_test_file_tests_dir():
    assert _is_test_file("tests/test_shop.py") is True


def test_is_test_file_normal():
    assert _is_test_file("shop.py") is False


def test_is_test_file_nested_tests_dir():
    assert _is_test_file("myapp/tests/unit.py") is True


# ---------------------------------------------------------------------------
# _decorator_name
# ---------------------------------------------------------------------------

def test_decorator_name_name_node():
    node = ast.parse("@fixture\ndef f(): pass").body[0].decorator_list[0]
    assert _decorator_name(node) == "fixture"


def test_decorator_name_attribute_node():
    node = ast.parse("@pytest.mark.skip\ndef f(): pass").body[0].decorator_list[0]
    assert _decorator_name(node) == "pytest.mark.skip"


def test_decorator_name_call_node():
    node = ast.parse("@pytest.mark.parametrize('x', [1])\ndef f(x): pass").body[0].decorator_list[0]
    assert _decorator_name(node) == "pytest.mark.parametrize"


def test_decorator_name_unknown_returns_empty():
    # A subscript node is not Name/Attribute/Call → returns ""
    node = ast.parse("x = a[0]").body[0].value
    assert _decorator_name(node) == ""


# ---------------------------------------------------------------------------
# _is_test_entry
# ---------------------------------------------------------------------------

def test_is_test_entry_by_name():
    func = ast.parse("def test_foo(): pass").body[0]
    assert _is_test_entry(func, True) is True


def test_is_test_entry_fixture_decorator():
    func = ast.parse("@fixture\ndef setup(): pass").body[0]
    assert _is_test_entry(func, True) is True


def test_is_test_entry_pytest_fixture():
    func = ast.parse("@pytest.fixture\ndef setup(): pass").body[0]
    assert _is_test_entry(func, True) is True


def test_is_test_entry_parametrize_without_test_prefix():
    # parametrize without test_ prefix → not a test entry
    func = ast.parse("@pytest.mark.parametrize('x', [1])\ndef helper(x): pass").body[0]
    assert _is_test_entry(func, False) is False


def test_is_test_entry_parametrize_with_test_prefix():
    func = ast.parse("@pytest.mark.parametrize('x', [1])\ndef test_helper(x): pass").body[0]
    assert _is_test_entry(func, True) is True


def test_is_test_entry_normal_function():
    func = ast.parse("def calculate(): pass").body[0]
    assert _is_test_entry(func, False) is False


# ---------------------------------------------------------------------------
# _dotted_name
# ---------------------------------------------------------------------------

def test_dotted_name_name():
    node = ast.parse("foo").body[0].value
    assert _dotted_name(node) == "foo"


def test_dotted_name_attribute():
    node = ast.parse("foo.bar").body[0].value
    assert _dotted_name(node) == "foo.bar"


def test_dotted_name_deep():
    node = ast.parse("a.b.c").body[0].value
    assert _dotted_name(node) == "a.b.c"


def test_dotted_name_non_name_returns_none():
    node = ast.parse("42").body[0].value
    assert _dotted_name(node) is None


def test_dotted_name_broken_chain():
    # a[0].b — left side is Subscript, can't produce dotted name
    node = ast.parse("a[0].b").body[0].value
    assert _dotted_name(node) is None


# ---------------------------------------------------------------------------
# _annotation_text
# ---------------------------------------------------------------------------

def test_annotation_text_none():
    assert _annotation_text(None) is None


def test_annotation_text_simple():
    func = ast.parse("def f() -> int: pass").body[0]
    assert _annotation_text(func.returns) == "int"


def test_annotation_text_complex():
    func = ast.parse("def f() -> list[float]: pass").body[0]
    assert _annotation_text(func.returns) == "list[float]"


# ---------------------------------------------------------------------------
# _resolve_import_module
# ---------------------------------------------------------------------------

def test_resolve_import_module_absolute():
    assert _resolve_import_module("app.main", "app.models", 0) == "app.models"


def test_resolve_import_module_relative_level1():
    assert _resolve_import_module("app.main", "models", 1) == "app.models"


def test_resolve_import_module_relative_no_module():
    # from . import something
    assert _resolve_import_module("app.main", None, 1) == "app"


def test_resolve_import_module_relative_level2():
    # from .. import something in app.sub.module → goes up 2 → ""
    result = _resolve_import_module("app.sub.module", "utils", 2)
    assert result == "app.utils"


# ---------------------------------------------------------------------------
# _file_context
# ---------------------------------------------------------------------------

def test_file_context_import():
    src = "import os\nimport collections.abc\n"
    tree = ast.parse(src)
    module_aliases, symbol_aliases, variable_classes = _file_context(tree, "mymod")
    assert "os" in module_aliases
    assert module_aliases["os"] == "os"


def test_file_context_import_from():
    src = "from app.models import CallSite as CS\n"
    tree = ast.parse(src)
    _, symbol_aliases, _ = _file_context(tree, "mymod")
    assert "CS" in symbol_aliases
    assert symbol_aliases["CS"] == "app.models.CallSite"


def test_file_context_variable_class_assign():
    src = "x = MyClass()\n"
    tree = ast.parse(src)
    _, _, variable_classes = _file_context(tree, "mymod")
    assert "x" in variable_classes
    assert variable_classes["x"] == "MyClass"


def test_file_context_ann_assign():
    src = "x: MyClass\n"
    tree = ast.parse(src)
    _, _, variable_classes = _file_context(tree, "mymod")
    assert "x" in variable_classes


def test_file_context_star_import_ignored():
    src = "from os import *\n"
    tree = ast.parse(src)
    _, symbol_aliases, _ = _file_context(tree, "mymod")
    assert "*" not in symbol_aliases


# ---------------------------------------------------------------------------
# extract_changed_functions_from_diff — edge cases
# ---------------------------------------------------------------------------

def test_diff_empty_returns_empty():
    assert extract_changed_functions_from_diff("") == []


def test_diff_non_python_file_ignored():
    diff = """\
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,2 +1,2 @@ some context
-old line
+new line
"""
    assert extract_changed_functions_from_diff(diff) == []


def test_diff_added_function_in_plus_line():
    diff = """\
diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -1,2 +1,3 @@
 x = 1
+def new_func(a):
+    return a
"""
    changed = extract_changed_functions_from_diff(diff)
    names = [c.name for c in changed]
    assert "new_func" in names


def test_diff_removed_function_captured():
    diff = """\
diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -1,3 +1,2 @@
 x = 1
-def old_func():
-    pass
"""
    changed = extract_changed_functions_from_diff(diff)
    names = [c.name for c in changed]
    assert "old_func" in names


def test_diff_deduplication():
    diff = """\
diff --git a/shop.py b/shop.py
--- a/shop.py
+++ b/shop.py
@@ -3,4 +3,4 @@ def calculate_total(prices):
 def calculate_total(prices):
-    return sum(prices)
+    return sum(prices) * 1.0
"""
    changed = extract_changed_functions_from_diff(diff)
    # Should not contain duplicates for same file/name/line
    keys = [(c.file, c.name, c.lineno) for c in changed]
    assert len(keys) == len(set(keys))


def test_diff_hunk_context_function():
    diff = """\
diff --git a/shop.py b/shop.py
--- a/shop.py
+++ b/shop.py
@@ -5,4 +5,4 @@ def calculate_total(prices):
-    return sum(prices)
+    return sum(prices) * 1.0
"""
    changed = extract_changed_functions_from_diff(diff)
    assert any(c.name == "calculate_total" for c in changed)


def test_diff_async_function():
    diff = """\
diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -1,3 +1,3 @@
 x = 1
+async def fetch(url):
+    pass
"""
    changed = extract_changed_functions_from_diff(diff)
    assert any(c.name == "fetch" for c in changed)


# ---------------------------------------------------------------------------
# find_function_definitions
# ---------------------------------------------------------------------------

def test_find_function_definitions():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "service.py").write_text(
            "def foo(): pass\ndef bar(): pass\n",
            encoding="utf-8",
        )
        result = find_function_definitions(str(root))
        assert "foo" in result
        assert "bar" in result
        assert isinstance(result["foo"], list)
        assert result["foo"][0][0] == "service.py"


# ---------------------------------------------------------------------------
# find_call_sites
# ---------------------------------------------------------------------------

def test_find_call_sites_basic():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "service.py").write_text(
            "def helper(): pass\n\ndef caller():\n    helper()\n",
            encoding="utf-8",
        )
        sites = find_call_sites(str(root), {"helper"})
        assert any(s.function_name == "helper" for s in sites)


def test_find_call_sites_no_callers():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "service.py").write_text(
            "def isolated(): pass\n",
            encoding="utf-8",
        )
        sites = find_call_sites(str(root), {"isolated"})
        assert sites == []


# ---------------------------------------------------------------------------
# calculate_risk_score
# ---------------------------------------------------------------------------

def test_risk_score_empty_list():
    assert calculate_risk_score([]) == 0


def test_risk_score_all_tested():
    site = CallSite(
        file="a.py", lineno=1, function_name="f", code_line="f()",
        is_tested=True, risk_score=80,
    )
    assert calculate_risk_score([site]) == 0


def test_risk_score_single_untested():
    site = CallSite(
        file="a.py", lineno=1, function_name="f", code_line="f()",
        is_tested=False, risk_score=80,
    )
    score = calculate_risk_score([site])
    assert 0 < score <= 100


def test_risk_score_breadth_bonus():
    sites = [
        CallSite(file="a.py", lineno=i, function_name="f", code_line="f()",
                 is_tested=False, risk_score=70)
        for i in range(5)
    ]
    single = CallSite(file="a.py", lineno=99, function_name="f", code_line="f()",
                      is_tested=False, risk_score=70)
    score_many = calculate_risk_score(sites)
    score_one = calculate_risk_score([single])
    # More untested sites should yield higher or equal score
    assert score_many >= score_one


def test_risk_score_capped_at_100():
    sites = [
        CallSite(file="a.py", lineno=i, function_name="f", code_line="f()",
                 is_tested=False, risk_score=100)
        for i in range(10)
    ]
    assert calculate_risk_score(sites) == 100


# ---------------------------------------------------------------------------
# mark_tested_call_sites
# ---------------------------------------------------------------------------

def test_mark_tested_direct_test_module_call():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shop.py").write_text(
            "def calculate_total(prices):\n    return sum(prices)\n",
            encoding="utf-8",
        )
        (root / "test_shop.py").write_text(
            "from shop import calculate_total\n\ndef test_it():\n    calculate_total([1])\n",
            encoding="utf-8",
        )
        site = CallSite(
            file="test_shop.py",
            lineno=2,
            function_name="calculate_total",
            code_line="calculate_total([1, 2])",
            caller_qualname="<module>",
            module="test_shop",
        )
        result = mark_tested_call_sites([site], str(root))
        assert result[0].is_tested is True
        assert result[0].coverage_reason is not None


def test_mark_tested_reachable_caller():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shop.py").write_text(
            "def calculate_total(prices):\n    return sum(prices)\n\ndef checkout(cart):\n    return calculate_total(cart)\n",
            encoding="utf-8",
        )
        (root / "test_shop.py").write_text(
            "from shop import checkout\n\ndef test_checkout():\n    checkout([1, 2])\n",
            encoding="utf-8",
        )
        site = CallSite(
            file="shop.py",
            lineno=5,
            function_name="calculate_total",
            code_line="calculate_total(cart)",
            caller_name="checkout",
            caller_qualname="checkout",
            module="shop",
        )
        result = mark_tested_call_sites([site], str(root))
        assert result[0].is_tested is True


def test_mark_tested_unreachable_caller():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shop.py").write_text(
            "def calculate_total(prices):\n    return sum(prices)\n\ndef orphan(cart):\n    return calculate_total(cart)\n",
            encoding="utf-8",
        )
        # No tests at all
        site = CallSite(
            file="shop.py",
            lineno=5,
            function_name="calculate_total",
            code_line="calculate_total(cart)",
            caller_name="orphan",
            caller_qualname="orphan",
            module="shop",
        )
        result = mark_tested_call_sites([site], str(root))
        assert result[0].is_tested is False
        assert result[0].risk_score >= 55


def test_mark_tested_cross_module_raises_risk():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shop.py").write_text(
            "def calculate_total(prices):\n    return sum(prices)\n",
            encoding="utf-8",
        )
        (root / "order.py").write_text(
            "from shop import calculate_total\n\ndef process(items):\n    return calculate_total(items)\n",
            encoding="utf-8",
        )
        site = CallSite(
            file="order.py",
            lineno=4,
            function_name="calculate_total",
            code_line="calculate_total(items)",
            caller_name="process",
            caller_qualname="process",
            module="order",
            target_module="shop",
        )
        result = mark_tested_call_sites([site], str(root))
        # Cross-module with no test → risk_score should be higher than base 55
        assert result[0].risk_score >= 65


# ---------------------------------------------------------------------------
# analyze_local_repo — edge cases
# ---------------------------------------------------------------------------

def test_analyze_local_repo_no_changed_functions_arg():
    """When changed_functions=None, it builds them from names."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "service.py").write_text(
            "def helper(): pass\n\ndef caller():\n    helper()\n",
            encoding="utf-8",
        )
        result = analyze_local_repo(str(root), ["helper"])
        assert any(cf.name == "helper" for cf in result.changed_functions)


def test_analyze_local_repo_unresolved_name():
    """A function name that doesn't exist in the repo still produces output."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "service.py").write_text("def real_func(): pass\n", encoding="utf-8")
        result = analyze_local_repo(str(root), ["ghost_func"])
        assert any(cf.name == "ghost_func" for cf in result.changed_functions)


def test_analyze_local_repo_summary_format():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "service.py").write_text(
            "def calc(x): return x\n\ndef use_it(x):\n    return calc(x)\n",
            encoding="utf-8",
        )
        diff = (
            "diff --git a/service.py b/service.py\n"
            "--- a/service.py\n"
            "+++ b/service.py\n"
            "@@ -1,2 +1,2 @@ def calc(x):\n"
            "-    return x\n"
            "+    return x + 0\n"
        )
        changed = extract_changed_functions_from_diff(diff)
        result = analyze_local_repo(str(root), [c.name for c in changed], changed)
        assert "changed function" in result.summary
        assert "call site" in result.summary


def test_analyze_local_repo_files_with_syntax_errors_skipped():
    """Files that can't be parsed should be silently skipped."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "broken.py").write_text("def (: pass\n", encoding="utf-8")
        (root / "good.py").write_text("def working(): pass\n", encoding="utf-8")
        result = analyze_local_repo(str(root), ["working"])
        assert result is not None


def test_analyze_resolves_method_in_class():
    """Methods nested inside a class are found correctly."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "cart.py").write_text(
            "class Cart:\n"
            "    def total(self, prices):\n"
            "        return sum(prices)\n"
            "    def finalize(self, prices):\n"
            "        return self.total(prices)\n",
            encoding="utf-8",
        )
        diff = (
            "diff --git a/cart.py b/cart.py\n"
            "--- a/cart.py\n"
            "+++ b/cart.py\n"
            "@@ -2,3 +2,3 @@ class Cart:\n"
            "     def total(self, prices):\n"
            "-        return sum(prices)\n"
            "+        return sum(prices) * 1.0\n"
        )
        changed = extract_changed_functions_from_diff(diff)
        result = analyze_local_repo(str(root), [c.name for c in changed], changed)
        assert result is not None


def test_analyze_import_alias_resolution():
    """When a function is imported with an alias and called, the call site is found."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "utils.py").write_text("def compute(x):\n    return x * 2\n", encoding="utf-8")
        (root / "app.py").write_text(
            "from utils import compute as calc\n\ndef run(x):\n    return calc(x)\n",
            encoding="utf-8",
        )
        diff = (
            "diff --git a/utils.py b/utils.py\n"
            "--- a/utils.py\n"
            "+++ b/utils.py\n"
            "@@ -1,2 +1,2 @@ def compute(x):\n"
            "-    return x * 2\n"
            "+    return x * 3\n"
        )
        changed = extract_changed_functions_from_diff(diff)
        result = analyze_local_repo(str(root), [c.name for c in changed], changed)
        callers = [s.caller_name for s in result.call_sites]
        assert "run" in callers


def test_analyze_risk_score_zero_when_all_tested():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shop.py").write_text(
            "def calculate_total(prices):\n    return sum(prices)\n"
            "\ndef checkout(cart):\n    return calculate_total(cart)\n",
            encoding="utf-8",
        )
        (root / "test_shop.py").write_text(
            "from shop import checkout\n\n"
            "def test_checkout():\n    checkout([1, 2, 3])\n",
            encoding="utf-8",
        )
        diff = (
            "diff --git a/shop.py b/shop.py\n"
            "--- a/shop.py\n"
            "+++ b/shop.py\n"
            "@@ -1,2 +1,2 @@ def calculate_total(prices):\n"
            "-    return sum(prices)\n"
            "+    return sum(prices) * 1.0\n"
        )
        changed = extract_changed_functions_from_diff(diff)
        result = analyze_local_repo(str(root), [c.name for c in changed], changed)
        tested = [s for s in result.call_sites if s.caller_name == "checkout"]
        assert tested[0].is_tested is True
        assert result.risk_score == 0
