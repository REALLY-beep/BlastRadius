from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
import os
import re
import zipfile

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analyzer import analyze_local_repo, build_risk_explanation, extract_changed_functions_from_diff
from .llm.client import LLMError, LLMInvalidResponse, LLMTimeout, LLMUnavailable, LlamaClient
from .llm.config import DEFAULT_MODEL, DEFAULT_SERVER_URL, LLMConfig
from .llm.engine import run_ai_analysis
from .models import AnalysisResult, LLMStatus
from .pytest_runner import apply_pytest_to_tests, summarize_test_runs
from .test_generator import generate_tests_for_sites



BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
EXAMPLE_REPO = BASE_DIR / "examples" / "sample_project"
DEMO_DIFF = BASE_DIR / "examples" / "change.diff"

app = FastAPI(title="BlastRadius", description="See what can break before you merge")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
_static_dir = BASE_DIR / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


def _render(request: Request, **context):
    defaults = {
        "engine": "ast",
        "llm_url": DEFAULT_SERVER_URL,
        "llm_model": DEFAULT_MODEL,
        "result": None,
        "diff_text": "",
        "repo_path": "",
        "pr_url": "",
        "error": None,
        "source_label": "Demo project",
    }
    defaults.update(context)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, **defaults},
    )


def _safe_zip_extract(upload: UploadFile, destination: Path) -> None:
    if not upload.filename or not upload.filename.lower().endswith(".zip"):
        raise ValueError("Project upload must be a .zip file.")

    data = upload.file.read()
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("Project ZIP is too large. Maximum size is 20 MB.")

    temp_zip = destination / "project.zip"
    temp_zip.write_bytes(data)

    try:
        archive = zipfile.ZipFile(temp_zip)
    except zipfile.BadZipFile as exc:
        raise ValueError("Project upload is not a valid ZIP file.") from exc

    with archive:
        root = destination.resolve()
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if os.path.commonpath((str(root), str(target))) != str(root):
                raise ValueError("Unsafe ZIP path detected.")
        archive.extractall(destination)

    temp_zip.unlink(missing_ok=True)


def _find_project_root(extracted: Path) -> Path:
    candidates = [extracted] + [path for path in extracted.rglob("*") if path.is_dir()]
    for candidate in candidates:
        if any(candidate.glob("*.py")) or any((candidate / "app").glob("*.py")):
            return candidate
    return extracted


def _fetch_github_diff(pr_url: str) -> str:
    match = re.fullmatch(
        r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:/.*)?",
        pr_url.strip(),
    )
    if not match:
        raise ValueError("PR URL must look like https://github.com/owner/repo/pull/123")

    owner, repo, number = match.groups()
    diff_url = f"https://github.com/{owner}/{repo}/pull/{number}.diff"
    request = UrlRequest(
        diff_url,
        headers={"User-Agent": "BlastRadius-Hackathon"},
    )

    try:
        with urlopen(request, timeout=10) as response:
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ValueError(f"Could not fetch GitHub PR diff: {exc}") from exc


def _load_demo_diff() -> str:
    if DEMO_DIFF.exists():
        return DEMO_DIFF.read_text(encoding="utf-8")
    return """diff --git a/shop.py b/shop.py
--- a/shop.py
+++ b/shop.py
@@ -4,7 +4,7 @@
 def calculate_total(prices: list[float]) -> float:
     \"\"\"Sum all prices.\"\"\"
-    return sum(prices)
+    return sum(prices) * 1.0
"""


def _normalize_engine(engine: Optional[str]) -> str:
    value = (engine or "ast").strip().lower()
    if value in {"ai", "gguf", "llm", "local-gguf"}:
        return "ai"
    if value in {"ast", ""}:
        return "ast"
    raise ValueError("Analysis engine must be AST or AI.")


def _run_ast_engine(repo: Path, changed_functions) -> AnalysisResult:
    result = analyze_local_repo(
        str(repo),
        [item.name for item in changed_functions],
        changed_functions=changed_functions,
    )
    result.analysis_engine = "ast"
    result.risk_explanation = build_risk_explanation(result)
    result.generated_tests = generate_tests_for_sites(result.untested_high_risk)
    result.generated_tests = apply_pytest_to_tests(result.generated_tests, str(repo))

    result.test_execution_status = summarize_test_runs(result.generated_tests)
    result.validation_errors = [
        f"{test.filename}: {test.error}"
        for test in result.generated_tests
        if test.error
    ]
    return result


def _run_ai_engine(repo: Path, diff_text: str, llm_url: str, llm_model: str) -> AnalysisResult:
    config = LLMConfig.from_form(llm_url, llm_model)
    with LlamaClient(config) as client:
        client.require_available()
        return run_ai_analysis(str(repo), diff_text, client)


def _analyze_repo(
    repo: Path,
    diff_text: str,
    engine: str,
    llm_url: str,
    llm_model: str,
) -> AnalysisResult:
    if not any(repo.rglob("*.py")):
        raise ValueError("The selected project does not contain any Python files.")

    if engine == "ai":
        return _run_ai_engine(repo, diff_text, llm_url, llm_model)

    changed_functions = extract_changed_functions_from_diff(diff_text)
    if not changed_functions:
        raise ValueError(
            "No changed Python functions were found in the diff. "
            "Paste a unified diff containing a Python hunk (for example @@ ... @@ def checkout(...))."
        )

    result = _run_ast_engine(repo, changed_functions)
    resolved_keys = {(item.file, item.name) for item in result.changed_functions}
    unresolved = [
        item for item in changed_functions
        if (item.file, item.name) not in resolved_keys
    ]
    if unresolved:
        names = ", ".join(sorted({item.name for item in unresolved}))
        raise ValueError(
            f"The diff references {names}, but the selected project does not contain the matching current function. "
            "Make sure the diff and project are from the same revision."
        )
    return result


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return _render(request)


@app.post("/analyze", response_class=HTMLResponse)
def analyze(

    request: Request,
    pr_url: Optional[str] = Form(None),
    diff_text: Optional[str] = Form(None),
    repo_path: Optional[str] = Form(None),
    project_zip: Optional[UploadFile] = File(None),
    engine: Optional[str] = Form("ast"),
    llm_url: Optional[str] = Form(None),
    llm_model: Optional[str] = Form(None),
):
    diff_text = (diff_text or "").strip()
    repo_path = (repo_path or "").strip()
    pr_url = (pr_url or "").strip()
    llm_url = (llm_url or DEFAULT_SERVER_URL).strip() or DEFAULT_SERVER_URL
    llm_model = (llm_model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    source_label = "Demo project"
    selected_engine = "ast"

    try:
        selected_engine = _normalize_engine(engine)

        if not diff_text and pr_url:
            diff_text = _fetch_github_diff(pr_url)
            source_label = "GitHub PR diff"

        if pr_url and not repo_path and not (project_zip is not None and project_zip.filename):
            raise ValueError("A GitHub PR needs the matching project folder or a project ZIP. Paste the diff instead when using the built-in demo project.")

        if not diff_text:
            diff_text = _load_demo_diff()
            source_label = "Demo diff"

        if project_zip is not None and project_zip.filename:
            with TemporaryDirectory(prefix="blastradius_") as temp_dir:
                temp_root = Path(temp_dir)
                _safe_zip_extract(project_zip, temp_root)
                repo = _find_project_root(temp_root)
                source_label = "Uploaded project ZIP"
                result = _analyze_repo(repo, diff_text, selected_engine, llm_url, llm_model)
        else:
            repo = Path(repo_path).expanduser() if repo_path else EXAMPLE_REPO
            if not repo.is_dir():
                raise ValueError(f"Project folder not found: {repo}")
            if repo != EXAMPLE_REPO:
                source_label = "Local project folder"
            result = _analyze_repo(repo, diff_text, selected_engine, llm_url, llm_model)

        return _render(
            request,
            result=result,
            diff_text=diff_text,
            repo_path=repo_path,
            pr_url=pr_url,
            error=None,
            source_label=source_label,
            engine=selected_engine,
            llm_url=llm_url,
            llm_model=llm_model,
        )

    except (LLMUnavailable, LLMTimeout) as exc:
        return _render(
            request,
            result=None,
            diff_text=diff_text,
            repo_path=repo_path,
            pr_url=pr_url,
            error=(
                f"AI engine unavailable: {str(exc).rstrip('.')}. "
                "BlastRadius will not silently fall back to AST. "
                "Point the server URL at llama.cpp llama-server, or switch the analysis engine to AST."
            ),
            source_label=source_label,
            engine=selected_engine,
            llm_url=llm_url,
            llm_model=llm_model,
        )
    except LLMInvalidResponse as exc:
        return _render(
            request,
            result=None,
            diff_text=diff_text,
            repo_path=repo_path,
            pr_url=pr_url,
            error=f"The local GGUF model returned an unusable response: {exc}",
            source_label=source_label,
            engine=selected_engine,
            llm_url=llm_url,
            llm_model=llm_model,
        )
    except LLMError as exc:
        return _render(
            request,
            result=None,
            diff_text=diff_text,
            repo_path=repo_path,
            pr_url=pr_url,
            error=f"AI engine failed: {exc}",
            source_label=source_label,
            engine=selected_engine,
            llm_url=llm_url,
            llm_model=llm_model,
        )
    except ValueError as exc:
        return _render(
            request,
            result=None,
            diff_text=diff_text,
            repo_path=repo_path,
            pr_url=pr_url,
            error=str(exc),
            source_label=source_label,
            engine=selected_engine,
            llm_url=llm_url,
            llm_model=llm_model,
        )
    except Exception as exc:
        return _render(
            request,
            result=None,
            diff_text=diff_text,
            repo_path=repo_path,
            pr_url=pr_url,
            error=f"Analysis failed: {exc}",
            source_label=source_label,
            engine=selected_engine,
            llm_url=llm_url,
            llm_model=llm_model,
        )


@app.get("/api/llm/status")
def llm_status(
    server_url: Optional[str] = None,
    model: Optional[str] = None,
):

    config = LLMConfig.from_form(server_url, model)
    try:
        with LlamaClient(config) as client:
            status = client.check_status()
    except LLMError as exc:
        status = LLMStatus(
            status="disconnected",
            detail=str(exc),
            server_url=config.server_url,
            model=config.model,
        )
    return JSONResponse(status.model_dump())


@app.get("/health")
def health():
    return {"status": "ok", "service": "BlastRadius", "engines": ["ast", "ai"]}

