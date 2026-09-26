# BlastRadius

**See what a code change can break — then generate the missing pytest checks.**

BlastRadius analyzes a Python unified diff against the matching project and returns a blast-radius map: changed functions, affected callers, untested paths, a risk score, and focused pytest files. Those generated tests are actually run with pytest; a green badge means pytest passed, not that a model merely returned code.

Built for the **IBM Bob 2.0 Hackathon**.

Two **explicit** analysis engines share one result view. They are not fallbacks of each other:

| Engine | How it works | Needs |
| --- | --- | --- |
| **AST** | Deterministic call-graph, coverage, risk, and pytest templates | Nothing but the project |
| **AI — Local GGUF** | llama.cpp `llama-server` over HTTP | A local GGUF model served at the URL you set |

If AI is selected and the local model is down, BlastRadius shows an error and **does not** silently switch to AST.

Code is analyzed on this machine. AI mode sends a focused context only to the llama-server URL you configure — not to a cloud API.

## Run it

Windows: double-click `start.bat`.

Manual:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000

Do **not** open `templates/index.html` as a file. It is a Jinja2 template served by FastAPI.

## Demo

### AST

1. Leave **AST** selected.
2. Click **Load demo**.
3. Analyze. The bundled shop project tests `calculate_total()` directly but not `checkout()` / `process_order()`. Those production callers should show as untested, with deterministic pytest files that are then executed.

### AI

1. Start llama.cpp `llama-server` with a GGUF model, typically:

   ```bash
   llama-server -m /path/to/model.gguf --port 8080
   ```

2. In BlastRadius choose **AI — Local GGUF**.
3. Confirm server URL `http://127.0.0.1:8080` and **Check connection** until it reads **Connected**.
4. Load the demo (or your own diff) and run AI analysis.
5. The model explains impact, generates pytest, and BlastRadius runs pytest. Expect **Generated** plus **Pytest passed** or the real failure output.

If BlastRadius itself is bound to port 8080, point the AI URL at whatever port `llama-server` actually uses.

## Analyze your own project

1. Choose AST or AI.
2. Paste a raw unified diff (or a public GitHub PR URL).
3. Provide the matching Python project folder, or upload a ZIP (up to 20 MB).
4. Analyze.

The ZIP is extracted into a temporary directory and deleted afterwards.

## What the result means

- **Engine** — `AST` or `AI (local GGUF)`, whichever you selected.
- **Changed functions** — functions/methods touched by the diff.
- **Call sites** — callers and other affected paths.
- **Test path found** — AST: a source-graph path from a pytest entry point. AI: the model's coverage judgment from the provided tests.
- **Risk score** — 0–100 prioritization signal, not a runtime failure probability.
- **Generated pytest** — AST uses templates; AI uses the local model. Both are syntax-checked and executed.
- **Pytest passed / failed** — actual `pytest` result.

## Local GGUF settings

Default completion endpoint:

```text
http://127.0.0.1:8080/v1/chat/completions
```

Override with the UI fields or:

```text
BLAST_RADIUS_LLM_URL=http://127.0.0.1:8080
BLAST_RADIUS_LLM_MODEL=local-gguf
BLAST_RADIUS_LLM_TIMEOUT=120
BLAST_RADIUS_LLM_RETRIES=2
```

BlastRadius never uses the OpenAI cloud API.

## Project structure

```text
BlastRadius/
├── app/
│   ├── main.py
│   ├── analyzer.py
│   ├── test_generator.py
│   ├── models.py
│   ├── pytest_runner.py
│   └── llm/
│       ├── client.py
│       ├── config.py
│       ├── prompts.py
│       ├── context.py
│       └── engine.py
├── examples/
│   ├── change.diff
│   └── sample_project/
├── templates/
│   └── index.html
├── tests/
├── requirements.txt
└── start.bat
```

## Tests

```bash
python -m pytest
```

The suite covers AST detection/coverage/risk/generation, AI client availability, malformed/timeout/connection failures, Python fence stripping, pytest validation, and AI mode end-to-end with a mocked llama-server. A real GGUF file is not required.

---

Made for the IBM Bob 2.0 Hackathon.
