"""Comprehensive unit tests for app/test_generator.py."""

import pytest

from app.models import CallSite
from app.test_generator import (
    _argument_for,
    _caller_call,
    _module_for_file,
    _patch_expression,
    _return_value,
    _safe_name,
    generate_tests_for_sites,
)


# ---------------------------------------------------------------------------
# _module_for_file
# ---------------------------------------------------------------------------

def test_module_for_file_simple():
    assert _module_for_file("shop.py") == "shop"


def test_module_for_file_nested():
    assert _module_for_file("app/service.py") == "app.service"


def test_module_for_file_backslash():
    assert _module_for_file("app\\service.py") == "app.service"


def test_module_for_file_init():
    assert _module_for_file("app/__init__.py") == "app"


def test_module_for_file_no_extension():
    # No ".py" suffix — parts are passed through as-is
    result = _module_for_file("app/service")
    assert result == "app.service"


# ---------------------------------------------------------------------------
# _safe_name
# ---------------------------------------------------------------------------

def test_safe_name_clean():
    assert _safe_name("calculate_total") == "calculate_total"


def test_safe_name_strips_special():
    assert _safe_name("my-func!") == "my_func"


def test_safe_name_empty_fallback():
    assert _safe_name("!!!") == "call"


def test_safe_name_leading_trailing_underscores_stripped():
    result = _safe_name("__something__")
    assert result == "something"


# ---------------------------------------------------------------------------
# _argument_for — all branches
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("cart",      "[10.0, 20.0]"),
    ("items",     "[10.0, 20.0]"),
    ("prices",    "[10.0, 20.0]"),
    ("values",    "[10.0, 20.0]"),
    ("numbers",   "[10.0, 20.0]"),
    ("ids",       "[10.0, 20.0]"),
    ("discount",  "10.0"),
    ("percent",   "10.0"),
    ("rate",      "10.0"),
    ("ratio",     "10.0"),
    ("price",     "10.0"),
    ("amount",    "10.0"),
    ("total",     "10.0"),
    ("value",     "10.0"),
    ("count",     "10.0"),
    ("limit",     "10.0"),
    ("index",     "10.0"),
    ("id",        "10.0"),
    ("name",      '"example"'),
    ("text",      '"example"'),
    ("message",   '"example"'),
    ("email",     '"example"'),
    ("token",     '"example"'),
    ("query",     '"example"'),
    ("data",      '{"example": 1}'),
    ("payload",   '{"example": 1}'),
    ("options",   '{"example": 1}'),
    ("config",    '{"example": 1}'),
    ("params",    '{"example": 1}'),
    ("flag",      "True"),
    ("enabled",   "True"),
    ("active",    "True"),
    ("debug",     "True"),
    ("force",     "True"),
    ("something_unknown", "Mock()"),
])
def test_argument_for_all_branches(name, expected):
    assert _argument_for(name) == expected


# ---------------------------------------------------------------------------
# _return_value
# ---------------------------------------------------------------------------

def test_return_value_format_target():
    site = CallSite(
        file="a.py", lineno=1, function_name="format_price", code_line="x()",
        target_qualname="format_price",
    )
    assert _return_value(site) == '"generated"'


def test_return_value_list_target():
    site = CallSite(
        file="a.py", lineno=1, function_name="get_items", code_line="x()",
        target_qualname="get_items",
    )
    assert _return_value(site) == "[]"


def test_return_value_dict_target():
    site = CallSite(
        file="a.py", lineno=1, function_name="get_config", code_line="x()",
        target_qualname="get_config",
    )
    assert _return_value(site) == "{}"


def test_return_value_scalar_fallback():
    site = CallSite(
        file="a.py", lineno=1, function_name="calculate", code_line="x()",
        target_qualname="calculate",
    )
    assert _return_value(site) == "1.0"


def test_return_value_uses_function_name_when_no_qualname():
    site = CallSite(
        file="a.py", lineno=1, function_name="get_name", code_line="x()",
        target_qualname=None,
    )
    assert _return_value(site) == '"generated"'


# ---------------------------------------------------------------------------
# _caller_call
# ---------------------------------------------------------------------------

def test_caller_call_module_level_returns_none():
    site = CallSite(
        file="a.py", lineno=1, function_name="helper", code_line="helper()",
        caller_qualname="<module>",
        caller_params=[],
        caller_is_method=False,
        caller_name=None,
    )
    assert _caller_call(site, "mymod") is None


def test_caller_call_no_caller_returns_none():
    site = CallSite(
        file="a.py", lineno=1, function_name="helper", code_line="helper()",
        caller_qualname=None,
        caller_params=[],
        caller_is_method=False,
    )
    assert _caller_call(site, "mymod") is None


def test_caller_call_plain_function():
    site = CallSite(
        file="shop.py", lineno=5, function_name="calculate_total", code_line="calculate_total(cart)",
        caller_qualname="checkout",
        caller_name="checkout",
        caller_params=["cart", "discount"],
        caller_is_method=False,
    )
    result = _caller_call(site, "shop")
    assert result is not None
    assert "checkout" in result
    assert "shop.checkout" in result


def test_caller_call_method():
    site = CallSite(
        file="cart.py", lineno=5, function_name="calculate_total", code_line="self.calculate_total(cart)",
        caller_qualname="Cart.finalize",
        caller_name="finalize",
        caller_params=["prices"],
        caller_is_method=True,
    )
    result = _caller_call(site, "cart")
    assert result is not None
    assert "instance.finalize" in result


def test_caller_call_with_multiple_params():
    site = CallSite(
        file="shop.py", lineno=5, function_name="apply_discount", code_line="apply_discount(total, discount)",
        caller_qualname="checkout",
        caller_name="checkout",
        caller_params=["cart", "discount"],
        caller_is_method=False,
    )
    result = _caller_call(site, "shop")
    assert result is not None
    # cart → [10.0, 20.0], discount → 10.0
    assert "[10.0, 20.0]" in result
    assert "10.0" in result


# ---------------------------------------------------------------------------
# _patch_expression
# ---------------------------------------------------------------------------

def test_patch_expression_with_dotted_patch_target():
    site = CallSite(
        file="shop.py", lineno=5, function_name="calculate_total", code_line="x()",
        patch_target="shop.calculate_total",
    )
    owner, attr = _patch_expression(site, "shop")
    assert owner == "shop"
    assert attr == "calculate_total"


def test_patch_expression_no_patch_target_uses_module():
    site = CallSite(
        file="shop.py", lineno=5, function_name="compute", code_line="x()",
        patch_target=None,
    )
    owner, attr = _patch_expression(site, "shop")
    assert owner == "shop"
    assert attr == "compute"


def test_patch_expression_non_dotted_patch_target():
    site = CallSite(
        file="shop.py", lineno=5, function_name="compute", code_line="x()",
        patch_target="mymod",
    )
    owner, attr = _patch_expression(site, "shop")
    assert owner == "mymod"
    assert attr == "compute"


# ---------------------------------------------------------------------------
# generate_tests_for_sites — integration
# ---------------------------------------------------------------------------

def _make_site(
    file="shop.py",
    lineno=5,
    fname="calculate_total",
    code="calculate_total(cart)",
    caller_name="checkout",
    caller_qualname="checkout",
    params=None,
    is_method=False,
    patch_target="shop.calculate_total",
    module="shop",
    target_qualname="calculate_total",
    risk_score=80,
) -> CallSite:
    return CallSite(
        file=file,
        lineno=lineno,
        function_name=fname,
        code_line=code,
        caller_name=caller_name,
        caller_qualname=caller_qualname,
        caller_params=params or ["cart"],
        caller_is_method=is_method,
        patch_target=patch_target,
        module=module,
        target_qualname=target_qualname,
        is_tested=False,
        risk_score=risk_score,
    )


def test_generate_tests_produces_output():
    sites = [_make_site()]
    result = generate_tests_for_sites(sites)
    assert len(result) >= 1


def test_generate_tests_content_has_monkeypatch():
    sites = [_make_site()]
    result = generate_tests_for_sites(sites)
    assert "monkeypatch" in result[0].content


def test_generate_tests_content_has_import():
    sites = [_make_site()]
    result = generate_tests_for_sites(sites)
    assert "import shop" in result[0].content


def test_generate_tests_content_has_assert_called():
    sites = [_make_site()]
    result = generate_tests_for_sites(sites)
    assert "target_mock.assert_called_once()" in result[0].content


def test_generate_tests_filename_pattern():
    sites = [_make_site()]
    result = generate_tests_for_sites(sites)
    assert result[0].filename.startswith("test_blast_radius_")
    assert result[0].filename.endswith(".py")


def test_generate_tests_max_limit():
    sites = [_make_site(lineno=i, params=["cart"]) for i in range(1, 20)]
    result = generate_tests_for_sites(sites, max_tests=3)
    assert len(result) <= 3


def test_generate_tests_sorted_by_risk_desc():
    low = _make_site(lineno=1, fname="low_risk", risk_score=55)
    high = _make_site(lineno=2, fname="high_risk", risk_score=95)
    result = generate_tests_for_sites([low, high])
    assert "high_risk" in result[0].content


def test_generate_tests_deduplication():
    site = _make_site()
    result = generate_tests_for_sites([site, site, site])
    assert len(result) == 1


def test_generate_tests_for_method_caller():
    site = _make_site(
        caller_qualname="Cart.finalize",
        caller_name="finalize",
        is_method=True,
        params=["prices"],
        fname="total",
        patch_target="cart.Cart.total",
        module="cart",
        target_qualname="Cart.total",
    )
    result = generate_tests_for_sites([site])
    assert result
    # Should include class instantiation via __new__
    assert "__new__" in result[0].content


def test_generate_tests_module_level_caller_skipped():
    """Module-level callers (caller_qualname=None) should be skipped."""
    site = CallSite(
        file="shop.py",
        lineno=1,
        function_name="helper",
        code_line="helper()",
        caller_qualname=None,
        caller_name=None,
        caller_params=[],
        caller_is_method=False,
        module="shop",
        risk_score=80,
        is_tested=False,
    )
    result = generate_tests_for_sites([site])
    assert result == []


def test_generate_tests_target_call_site_field():
    sites = [_make_site(file="shop.py", lineno=42)]
    result = generate_tests_for_sites(sites)
    assert "shop.py:42" in result[0].target_call_site


def test_generate_tests_empty_input():
    assert generate_tests_for_sites([]) == []
