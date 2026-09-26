# BlastRadius

**See what a code change can break — then generate the missing pytest checks.**

BlastRadius analyzes a Python unified diff, resolves the changed functions and methods against the matching project, maps their call sites, checks whether those callers are reachable from pytest entry points, calculates a risk score, and generates focused tests for high-risk untested paths.

Built for the **IBM Bob 2.0 Hackathon**.

## Run it on Windows

The easiest way is to double-click:

```text
start.bat
```

It creates a local virtual environment, installs the dependencies once, starts FastAPI, and opens the browser.

Do **not** double-click `templates/index.html`. It is a Jinja2 server template and is not meant to be opened directly.

The manual commands are:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000

## Demo

Open the app and click **Load demo**. The bundled project intentionally has tests for `calculate_total()` itself but no test path through `checkout()` and `process_order()`. BlastRadius should therefore show those production callers as untested and generate focused pytest checks.

## Analyze your own project

1. Paste a raw unified diff.
2. Provide the matching Python project folder, or upload the project as a ZIP (up to 20 MB).
3. Click **Analyze blast radius**.

The ZIP is extracted into a temporary directory and is deleted after analysis.

### GitHub PR

A public GitHub pull request can be supplied instead of pasting the diff. BlastRadius downloads the PR's unified diff automatically. The matching project folder or ZIP is still required so the diff can be resolved against real source code.

## What the analysis means

- **Changed functions** — functions/methods touched by the diff and resolved against the selected checkout.
- **Call sites** — production and direct test references to those changed functions.
- **Test path found** — a source-graph path reaches that caller from a pytest test entry point.
- **Risk score** — a 0–100 heuristic based on untested exposure and call-site breadth. It is a prioritization signal, not a runtime failure probability.
- **Generated pytest checks** — small tests aimed at exercising high-risk callers and verifying that the changed function is reached.

Coverage is static reachability analysis. It does not replace running the real test suite.

## Project structure

```text
BlastRadius/
├── app/
│   ├── main.py
│   ├── analyzer.py
│   ├── test_generator.py
│   └── models.py
├── examples/
│   ├── change.diff
│   └── sample_project/
├── templates/
│   └── index.html
├── tests/
│   ├── test_analyzer.py
│   └── test_main.py
├── requirements.txt
└── start.bat
```

## Verify before submission

```bash
python -m pytest -q
```

The repository includes regression tests for diff parsing, caller coverage, class-method resolution, ZIP analysis, the FastAPI UI, and generated test output.

---

Made for the IBM Bob 2.0 Hackathon.
