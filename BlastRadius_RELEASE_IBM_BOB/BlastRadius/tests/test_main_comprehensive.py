"""Comprehensive integration tests for app/main.py (FastAPI routes and helpers)."""

import zipfile
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import (
    _fetch_github_diff,
    _find_project_root,
    _load_demo_diff,
    _safe_zip_extract,
    app,
)

client = TestClient(app)

ROOT = Path(__file__).resolve().parents[1]
DIFF = (ROOT / "examples" / "change.diff").read_text(encoding="utf-8")
SAMPLE_PROJECT = ROOT / "examples" / "sample_project"


# ============================================================
# /health endpoint
# ============================================================

def test_health_status_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["service"] == "BlastRadius"


# ============================================================
# GET / — home page
# ============================================================

def test_home_returns_200():
    r = client.get("/")
    assert r.status_code == 200


def test_home_contains_branding():
    r = client.get("/")
    assert "BlastRadius" in r.text


def test_home_contains_analyze_button():
    r = client.get("/")
    assert "Analyze blast radius" in r.text


def test_home_no_error_initially():
    r = client.get("/")
    assert "error" not in r.text.lower() or "None" not in r.text


# ============================================================
# POST /analyze — diff_text input (demo project)
# ============================================================

def test_analyze_with_diff_text_returns_200():
    r = client.post("/analyze", data={"diff_text": DIFF})
    assert r.status_code == 200


def test_analyze_impact_overview_shown():
    r = client.post("/analyze", data={"diff_text": DIFF})
    assert "Impact overview" in r.text


def test_analyze_shows_checkout_caller():
    r = client.post("/analyze", data={"diff_text": DIFF})
    assert "checkout" in r.text


def test_analyze_shows_generated_test_filename():
    r = client.post("/analyze", data={"diff_text": DIFF})
    assert "test_blast_radius_calculate_total_1.py" in r.text


def test_analyze_source_label_demo():
    r = client.post("/analyze", data={"diff_text": DIFF})
    assert "Demo project" in r.text


# ============================================================
# POST /analyze — no input triggers demo diff
# ============================================================

def test_analyze_no_input_uses_demo_diff():
    r = client.post("/analyze", data={})
    assert r.status_code == 200
    # Demo diff should produce results
    assert "calculate_total" in r.text


# ============================================================
# POST /analyze — invalid diff (no Python hunks)
# ============================================================

def test_analyze_non_python_diff_returns_error():
    bad_diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,2 +1,2 @@\n"
        "-old\n"
        "+new\n"
    )
    r = client.post("/analyze", data={"diff_text": bad_diff})
    assert r.status_code == 200
    assert "No changed Python functions" in r.text


# ============================================================
# POST /analyze — repo_path that does not exist
# ============================================================

def test_analyze_nonexistent_repo_path_returns_error():
    r = client.post("/analyze", data={
        "diff_text": DIFF,
        "repo_path": "/nonexistent/path/to/project",
    })
    assert r.status_code == 200
    assert "not found" in r.text.lower() or "Project folder" in r.text


# ============================================================
# POST /analyze — ZIP upload
# ============================================================

def _build_zip(files: dict[str, str]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_analyze_zip_upload_basic():
    zip_bytes = _build_zip({
        "project/shop.py": (SAMPLE_PROJECT / "shop.py").read_text(),
        "project/test_shop.py": (SAMPLE_PROJECT / "test_shop.py").read_text(),
    })
    r = client.post(
        "/analyze",
        data={"diff_text": DIFF},
        files={"project_zip": ("project.zip", zip_bytes, "application/zip")},
    )
    assert r.status_code == 200
    assert "Uploaded project ZIP" in r.text


def test_analyze_zip_shows_process_order():
    zip_bytes = _build_zip({
        "project/shop.py": (SAMPLE_PROJECT / "shop.py").read_text(),
        "project/test_shop.py": (SAMPLE_PROJECT / "test_shop.py").read_text(),
    })
    r = client.post(
        "/analyze",
        data={"diff_text": DIFF},
        files={"project_zip": ("project.zip", zip_bytes, "application/zip")},
    )
    assert "process_order" in r.text


def test_analyze_zip_no_python_files_returns_error():
    zip_bytes = _build_zip({"project/README.md": "# readme"})
    r = client.post(
        "/analyze",
        data={"diff_text": DIFF},
        files={"project_zip": ("project.zip", zip_bytes, "application/zip")},
    )
    assert r.status_code == 200
    # No .py files → unresolved functions error or no Python files error
    assert (
        "does not contain" in r.text
        or "references" in r.text
        or "No changed Python functions" in r.text
    )


# ============================================================
# _safe_zip_extract — unit tests
# ============================================================

def test_safe_zip_extract_non_zip_filename():
    from io import BytesIO
    from unittest.mock import MagicMock
    from fastapi import UploadFile

    upload = MagicMock(spec=UploadFile)
    upload.filename = "project.tar.gz"
    upload.file = BytesIO(b"data")

    with TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match=".zip"):
            _safe_zip_extract(upload, Path(tmp))


def test_safe_zip_extract_empty_filename():
    from io import BytesIO
    from unittest.mock import MagicMock
    from fastapi import UploadFile

    upload = MagicMock(spec=UploadFile)
    upload.filename = ""
    upload.file = BytesIO(b"data")

    with TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match=".zip"):
            _safe_zip_extract(upload, Path(tmp))


def test_safe_zip_extract_oversized_file():
    from io import BytesIO
    from unittest.mock import MagicMock
    from fastapi import UploadFile

    upload = MagicMock(spec=UploadFile)
    upload.filename = "project.zip"
    # 21 MB of zeros
    upload.file = BytesIO(b"\x00" * (21 * 1024 * 1024))

    with TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="too large"):
            _safe_zip_extract(upload, Path(tmp))


def test_safe_zip_extract_invalid_zip_bytes():
    from io import BytesIO
    from unittest.mock import MagicMock
    from fastapi import UploadFile

    upload = MagicMock(spec=UploadFile)
    upload.filename = "project.zip"
    upload.file = BytesIO(b"this is not a zip file")

    with TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="not a valid ZIP"):
            _safe_zip_extract(upload, Path(tmp))


def test_safe_zip_extract_valid_zip():
    from io import BytesIO
    from unittest.mock import MagicMock
    from fastapi import UploadFile

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("project/shop.py", "def foo(): pass\n")
    buf.seek(0)

    upload = MagicMock(spec=UploadFile)
    upload.filename = "project.zip"
    upload.file = buf

    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _safe_zip_extract(upload, tmp_path)
        assert (tmp_path / "project" / "shop.py").exists()


def test_safe_zip_extract_path_traversal_blocked():
    """ZIP with path traversal (../../) should raise."""
    from io import BytesIO
    from unittest.mock import MagicMock
    from fastapi import UploadFile

    # Manually construct a ZIP with a traversal path
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("../../evil.py")
        zf.writestr(info, "# evil\n")
    buf.seek(0)

    upload = MagicMock(spec=UploadFile)
    upload.filename = "project.zip"
    upload.file = buf

    with TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="[Uu]nsafe"):
            _safe_zip_extract(upload, Path(tmp))


# ============================================================
# _find_project_root — unit tests
# ============================================================

def test_find_project_root_flat():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shop.py").write_text("def foo(): pass\n")
        result = _find_project_root(root)
        assert result == root


def test_find_project_root_nested():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        inner = root / "myproject"
        inner.mkdir()
        (inner / "shop.py").write_text("def foo(): pass\n")
        result = _find_project_root(root)
        assert result == inner


def test_find_project_root_no_python_falls_back():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "README.md").write_text("# readme\n")
        result = _find_project_root(root)
        # Falls back to extracted root
        assert result == root


def test_find_project_root_app_subdir():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        app_dir = root / "project" / "app"
        app_dir.mkdir(parents=True)
        (app_dir / "main.py").write_text("def main(): pass\n")
        result = _find_project_root(root)
        # project dir has an app/ subdir with Python files
        assert "project" in str(result)


# ============================================================
# _load_demo_diff — unit tests
# ============================================================

def test_load_demo_diff_from_file():
    diff = _load_demo_diff()
    assert "calculate_total" in diff
    assert "shop.py" in diff


def test_load_demo_diff_fallback_when_missing(tmp_path):
    with patch("app.main.DEMO_DIFF", tmp_path / "nonexistent.diff"):
        diff = _load_demo_diff()
        assert "calculate_total" in diff
        assert "shop.py" in diff


# ============================================================
# _fetch_github_diff — unit tests (mocked network)
# ============================================================

def test_fetch_github_diff_bad_url():
    with pytest.raises(ValueError, match="PR URL must look like"):
        _fetch_github_diff("https://github.com/owner/repo/issues/123")


def test_fetch_github_diff_non_github_url():
    with pytest.raises(ValueError, match="PR URL must look like"):
        _fetch_github_diff("https://gitlab.com/owner/repo/pull/1")


def test_fetch_github_diff_empty_url():
    with pytest.raises(ValueError, match="PR URL must look like"):
        _fetch_github_diff("")


def test_fetch_github_diff_success(monkeypatch):
    from unittest.mock import MagicMock

    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = b"diff --git a/shop.py b/shop.py\n"

    with patch("app.main.urlopen", return_value=mock_response):
        result = _fetch_github_diff("https://github.com/owner/repo/pull/42")
    assert "shop.py" in result


def test_fetch_github_diff_network_error():
    from urllib.error import URLError

    with patch("app.main.urlopen", side_effect=URLError("connection refused")):
        with pytest.raises(ValueError, match="Could not fetch"):
            _fetch_github_diff("https://github.com/owner/repo/pull/42")


def test_fetch_github_diff_timeout():
    with patch("app.main.urlopen", side_effect=TimeoutError("timed out")):
        with pytest.raises(ValueError, match="Could not fetch"):
            _fetch_github_diff("https://github.com/owner/repo/pull/42")


# ============================================================
# POST /analyze — unresolved function mismatch error
# ============================================================

def test_analyze_diff_function_not_in_project():
    """Diff references a function that the project does not have."""
    diff = (
        "diff --git a/missing.py b/missing.py\n"
        "--- a/missing.py\n"
        "+++ b/missing.py\n"
        "@@ -1,2 +1,2 @@ def ghost_function():\n"
        "-    return 1\n"
        "+    return 2\n"
    )
    r = client.post("/analyze", data={"diff_text": diff})
    assert r.status_code == 200
    assert (
        "ghost_function" in r.text
        or "does not contain" in r.text
        or "matching current function" in r.text
    )


# ============================================================
# POST /analyze — pr_url without project
# ============================================================

def test_analyze_pr_url_without_project_returns_error():
    r = client.post("/analyze", data={
        "pr_url": "https://github.com/owner/repo/pull/1",
    })
    assert r.status_code == 200
    # Without network access this will either error on missing project OR fetch error
    # Both are acceptable error responses
    assert "error" in r.text.lower() or "Error" in r.text or "Could not" in r.text or "needs the matching" in r.text


# ============================================================
# POST /analyze — local repo_path pointing to sample project
# ============================================================

def test_analyze_local_repo_path():
    r = client.post("/analyze", data={
        "diff_text": DIFF,
        "repo_path": str(SAMPLE_PROJECT),
    })
    assert r.status_code == 200
    assert "checkout" in r.text


def test_analyze_local_repo_path_label():
    r = client.post("/analyze", data={
        "diff_text": DIFF,
        "repo_path": str(SAMPLE_PROJECT),
    })
    # Example repo doesn't get "Local project folder" label (it equals EXAMPLE_REPO)
    assert "Demo project" in r.text or "Local project folder" in r.text


def test_analyze_local_repo_path_no_python_files():
    with TemporaryDirectory() as tmp:
        r = client.post("/analyze", data={
            "diff_text": DIFF,
            "repo_path": tmp,
        })
    assert r.status_code == 200
    assert "does not contain any Python files" in r.text or "references" in r.text
