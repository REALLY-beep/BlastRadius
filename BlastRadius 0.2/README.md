# BlastRadius

**Before you merge — see what can break, and get the missing tests.**

BlastRadius analyzes a code change (diff or GitHub PR), finds the real blast radius of the modified functions, checks which risky call sites are untested, and generates focused pytest tests for them.

Built for the **IBM Bob 2.0 Hackathon**.

## Problem

Developers change a function → all existing tests stay green → after merge something breaks in a completely different place.  
The tests exist, but they never exercised the paths that the change actually affected.

## Solution

1. Paste a GitHub PR URL or upload a diff
2. BlastRadius finds every place the changed functions are called
3. It checks which of those places have no tests
4. It generates targeted pytest tests for the highest-risk untested call sites
5. You get a clear risk report + ready-to-run tests

## Quick Start

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000

## Project Structure

```
BlastRadius/
├── app/
│   ├── main.py              # FastAPI application
│   ├── analyzer.py          # Core blast-radius logic
│   ├── test_generator.py    # Generates pytest tests with help of patterns
│   └── models.py            # Pydantic models
├── templates/
│   └── index.html           # Simple web UI
├── examples/
│   └── sample_diff.py       # Example for local testing
├── requirements.txt
└── README.md
```

## How IBM Bob was used

- Architecture planning (Plan mode)
- Writing the AST-based caller finder
- Generating the test templates
- Refactoring and adding error handling
- Creating the submission statements and video script

## Demo flow

1. Open the web UI
2. Paste a public GitHub PR link (Python repo works best)
3. Click "Analyze"
4. See the risk report and generated tests
5. Copy the tests into your project and run `pytest`

---

Made for IBM Bob 2.0 Hackathon · 2026