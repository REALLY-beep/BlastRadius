# BlastRadius

**See what your Python change can break — before you merge.**

BlastRadius analyzes a Python unified diff, resolves the changed functions or methods against a matching project, finds real call sites, checks whether those callers are statically reachable from pytest entry points, assigns risk, and generates focused pytest checks for the dangerous gaps.

Built for the **IBM Bob 2.0 Hackathon**.

## Quick start

```bash
python -m venv venv
venv\\Scripts\\activate       # Windows
# source venv/bin/activate    # macOS / Linux
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

## Demo

Leave the project folder empty and click **Load demo**, then **Analyze blast radius**. The bundled `examples/sample_project` is analyzed automatically.

## Real project

Use either:

- a path to the local project folder;
- a ZIP containing the Python project.

Then paste the raw unified diff from the same revision. A GitHub PR URL can be used instead of pasting the diff when the matching project folder or ZIP is also supplied.

## What the analyzer does

- AST indexes functions and class methods with qualified names.
- Resolves direct calls, imported functions, module calls, `self.method()`, class methods, and simple `instance.method()` patterns.
- Builds a lightweight call graph and checks whether a production caller is reachable from pytest test functions or fixtures.
- Calculates per-call and overall risk scores from test gaps, fan-out, cross-module calls, and public/method callers.
- Generates pytest tests that monkeypatch the changed dependency and assert that the dangerous call is actually reached.

The analysis is static. It is intended to identify likely coverage gaps; it does not replace executing the full test suite.

## Project structure

```text
BlastRadius/
├── app/
│   ├── main.py
│   ├── analyzer.py
│   ├── test_generator.py
│   └── models.py
├── examples/
│   ├── sample_project/
│   └── change.diff
├── static/
├── templates/
│   └── index.html
├── requirements.txt
└── README.md
```
