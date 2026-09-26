from pathlib import Path

from app.analyzer import analyze_local_repo, extract_changed_functions_from_diff
from app.test_generator import generate_tests_for_sites


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "examples" / "sample_project"
DIFF = (ROOT / "examples" / "change.diff").read_text(encoding="utf-8")


def test_diff_finds_body_change():
    changed = extract_changed_functions_from_diff(DIFF)
    assert [(item.file, item.name) for item in changed] == [("shop.py", "calculate_total")]


def test_blast_radius_does_not_confuse_direct_unit_test_with_caller_coverage():
    changed = extract_changed_functions_from_diff(DIFF)
    result = analyze_local_repo(str(REPO), [item.name for item in changed], changed)

    production = {
        site.caller_name: site
        for site in result.call_sites
        if site.file == "shop.py"
    }

    assert production["checkout"].is_tested is False
    assert production["process_order"].is_tested is False
    assert production["checkout"].risk_score >= 70
    assert result.risk_score >= 70


def test_generated_tests_are_not_empty_stubs():
    changed = extract_changed_functions_from_diff(DIFF)
    result = analyze_local_repo(str(REPO), [item.name for item in changed], changed)
    generated = generate_tests_for_sites(result.untested_high_risk)

    assert generated
    assert "assert target_mock.assert_called_once" not in generated[0].content
    assert "target_mock.assert_called_once()" in generated[0].content
    assert "assert True" not in generated[0].content
    assert "import shop" in generated[0].content


def test_same_named_methods_are_resolved_by_class():
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "service.py").write_text(
            """class A:\n    def save(self, value):\n        return value\n\nclass B:\n    def save(self, value):\n        return value\n\ndef checkout(value):\n    item = A()\n    return item.save(value)\n""",
            encoding="utf-8",
        )
        (root / "test_service.py").write_text(
            "from service import A\n\ndef test_save():\n    assert A().save(1) == 1\n",
            encoding="utf-8",
        )

        diff = """diff --git a/service.py b/service.py\n--- a/service.py\n+++ b/service.py\n@@ -1,3 +1,3 @@\n class A:\n     def save(self, value):\n-        return value\n+        return value + 1\n"""
        changed = extract_changed_functions_from_diff(diff)
        result = analyze_local_repo(str(root), [item.name for item in changed], changed)

        sites = [site for site in result.call_sites if site.caller_name == "checkout"]
        assert len(sites) == 1
        assert sites[0].target_qualname == "A.save"
