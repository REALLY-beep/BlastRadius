from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from typing import Optional
import os

from .models import AnalyzeRequest, AnalysisResult
from .analyzer import extract_changed_functions_from_diff, analyze_local_repo
from .test_generator import generate_tests_for_sites

app = FastAPI(title="BlastRadius", description="See what your change can break")

templates = Jinja2Templates(directory="templates")

# For demo purposes we use a local example repo
EXAMPLE_REPO = os.path.join(os.path.dirname(__file__), "..", "examples", "sample_project")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    pr_url: Optional[str] = Form(None),
    diff_text: Optional[str] = Form(None)
):
    """
    Main analysis endpoint.
    For the hackathon MVP we support:
    - pasting a raw diff
    - or using the built-in sample project
    """

    changed_names = []

    if diff_text and diff_text.strip():
        changed_funcs = extract_changed_functions_from_diff(diff_text)
        changed_names = [f.name for f in changed_funcs]
    else:
        # fallback demo mode – pretend we changed these functions
        changed_names = ["calculate_total", "apply_discount"]

    # Analyze the sample project (in real life this would be a cloned repo)
    if not os.path.exists(EXAMPLE_REPO):
        # create a tiny sample on the fly if missing
        os.makedirs(EXAMPLE_REPO, exist_ok=True)

    result: AnalysisResult = analyze_local_repo(EXAMPLE_REPO, changed_names)

    # Generate tests for the dangerous places
    result.generated_tests = generate_tests_for_sites(result.untested_high_risk)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "result": result,
        "pr_url": pr_url,
        "diff_text": diff_text or ""
    })


@app.get("/health")
async def health():
    return {"status": "ok", "service": "BlastRadius"}