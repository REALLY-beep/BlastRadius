# BlastRadius — Local AI Setup (GGUF)

This is a dedicated guide for the **AI — Local GGUF** mode only.  
The **AST** mode is not covered here: it works without a model, without internet access, and without llama-server.

BlastRadius **does not load** `.gguf` files itself. It communicates over HTTP with a local `llama-server` (llama.cpp) and sends source code nowhere else.

```text
GGUF file on disk
        ↓
llama.cpp llama-server   ←  this is where the model goes
        ↓  HTTP  127.0.0.1:8080/v1/chat/completions
BlastRadius (FastAPI)    ←  do NOT put the model here
        ↓
UI: Connected / analysis / pytest
```

If llama-server is not running, AI mode will show an error and will **not** fall back to AST.

---

## 1. Expected end state

Two processes running simultaneously:

| Process | Default port | Purpose |
| --- | --- | --- |
| BlastRadius (`start.bat` / uvicorn) | **8000** | Analysis web app |
| `llama-server` with GGUF | **8080** | Local model |

In the UI:

1. Analysis Engine → **AI — Local GGUF**
2. Server → `http://127.0.0.1:8080`
3. **Check connection** → **Connected**
4. Analyze

---

## 2. What to download beforehand

Three things are needed:

1. **Python 3.10+** — already required for BlastRadius.
2. **llama.cpp llama-server** — the server that reads `.gguf` files.
3. **A model file `*.gguf`** — the weights. This is not part of the BlastRadius repository.

Recommended models for code analysis (7B–14B is sufficient, quantization Q4_K_M or Q5_K_M):

- Qwen2.5-Coder 7B Instruct
- Qwen2.5-Coder 14B Instruct (if you have 12+ GB VRAM / plenty of RAM)
- Llama 3.1 8B Instruct
- Gemma 2 9B Instruct

Names on Hugging Face typically look like:

```text
*-Instruct-Q4_K_M.gguf
*-Instruct-Q5_K_M.gguf
```

Prefer an Instruct variant over a raw base model when available. BlastRadius requires the model to respond in JSON and write pytest code.

The file can live anywhere. A convenient convention:

```text
Windows:  C:\models\qwen2.5-coder-7b-instruct-q4_k_m.gguf
Linux:    ~/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf
macOS:    ~/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf
```

**Do not place the `.gguf` inside the BlastRadius folder.** The application only needs the server URL.

Memory reference:

| 7B quant | Approx. RAM / VRAM | Notes |
| --- | --- | --- |
| Q4_K_M | 6–8 GB | Good starting point |
| Q5_K_M | 8–10 GB | Slightly more accurate |
| Q8_0 | 10–14 GB | Usually unnecessary for demos |

---

## 3. Installing llama-server

You need the **llama-server** binary from llama.cpp specifically. It exposes an OpenAI-compatible endpoint:

```text
http://127.0.0.1:8080/v1/chat/completions
```

Repository: [github.com/ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)

### Windows (easiest path)

1. Open [llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases).
2. Download the archive that matches your hardware:
   - NVIDIA GPU → build with CUDA (`cudart`, `cuBLAS` in the release name);
   - CPU only → CPU / `noavx` / standard `bin`.
3. Extract it, e.g. to `C:\llama.cpp\`.
4. Inside you should find `llama-server.exe` (newer releases) or `server.exe` (older releases).

Verify from `cmd`:

```bat
cd C:\llama.cpp
llama-server.exe -h
```

If `llama-server` is already on your PATH you can omit the full path.

### Linux

Option A — pre-built binary from GitHub Releases.

Option B — build from source:

```bash
sudo apt update
sudo apt install -y build-essential cmake git
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build -DGGML_CUDA=OFF
cmake --build build --config Release -t llama-server
```

The binary is typically at:

```text
build/bin/llama-server
```

For NVIDIA, change the flag to `-DGGML_CUDA=ON` (requires CUDA toolkit and driver).

### macOS (Apple Silicon)

```bash
brew install llama.cpp
```

or build from source. On M1/M2/M3, Metal acceleration is picked up automatically.

Verify:

```bash
llama-server -h
```

---

## 4. Starting the model

Do **not** start BlastRadius on port 8080. `start.bat` binds it to **8000**, which is correct: port 8080 is reserved for the model.

### Windows

```bat
cd C:\llama.cpp
llama-server.exe -m C:\models\qwen2.5-coder-7b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8080 -c 4096 --jinja
```

### Linux / macOS

```bash
llama-server -m ~/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8080 -c 4096 --jinja
```

Useful flags:

| Flag | Purpose |
| --- | --- |
| `-m file.gguf` | path to the model file, required |
| `--host 127.0.0.1` | local only — source code never leaves the machine |
| `--port 8080` | the port BlastRadius expects |
| `-c 4096` | context size. For diffs + source code, 4096–8192 is recommended |
| `-ngl 99` | offload layers to GPU if one is available |
| `--jinja` | enables chat templates for Instruct models |

Keep the llama-server window **open**. BlastRadius connects to it as long as the process is alive.

A successful start looks like this in the log:

```text
llama server listening at http://127.0.0.1:8080
```

Verify without the UI:

```bash
curl http://127.0.0.1:8080/v1/models
curl http://127.0.0.1:8080/health
```

These should return a JSON model list / status `ok`, not a BlastRadius HTML page.

---

## 5. Connecting to BlastRadius

Terminal 1 — the application:

```bat
start.bat
```

or manually:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

Terminal 2 — the model, using the command from section 4.

In the UI:

1. Select **AI — Local GGUF**. The server block will appear.
2. **SERVER:** `http://127.0.0.1:8080`  
   You can also paste the full path `http://127.0.0.1:8080/v1/chat/completions` — the extra suffix will be stripped.
3. **MODEL NAME:** `local-gguf`  
   llama.cpp often ignores the name. If `/v1/models` returned a specific id, use that instead.
4. **Check connection**.
5. Wait for **Connected** status.
6. Load demo → **Run AI analysis**.

Code is sent only to this URL. No cloud API is used.

---

## 6. Status meanings

| UI status | What happened | What to do |
| --- | --- | --- |
| **Connected** | llama-server is responding and the model is loaded | Ready to analyze |
| **Disconnected** | port is closed, wrong process, or the URL points to BlastRadius itself | Start llama-server, verify the port |
| **Invalid response** | something is listening on the port but it is not llama-server | Wrong URL / wrong server |
| **Model unavailable** | server is alive but the GGUF is still loading or failed to load | Wait, or check the `-m` flag |

Common mistake: both BlastRadius and llama-server bound to port 8080. In that case, Check connection will report that it sees BlastRadius, not the model.

Solutions:

- Keep BlastRadius on **8000** (`start.bat` already does this);
- or run llama-server on a different port:

```bash
llama-server -m ~/models/model.gguf --port 8081 --host 127.0.0.1
```

and set `http://127.0.0.1:8081` in the UI.

Environment variables (to avoid editing the form every time):

```text
BLAST_RADIUS_LLM_URL=http://127.0.0.1:8080
BLAST_RADIUS_LLM_MODEL=local-gguf
BLAST_RADIUS_LLM_TIMEOUT=120
BLAST_RADIUS_LLM_RETRIES=2
```

---

## 7. Analysis ran but tests are red

This is normal and not a "fake success". The pipeline is:

```text
model writes pytest
    → syntax check
    → file written to a temp directory
    → real pytest run
    → PASS / FAIL shown in UI
```

On FAIL the model receives the pytest output and may fix the test (1–2 attempts, not indefinitely).

Common reasons for FAIL:

- the model invented a function that does not exist in the project;
- GGUF is too weak or context is too small (increase `-c` to 8192);
- non-Instruct model — prose comes back instead of code.

AST mode does not activate automatically in this case.

---

## 8. Common failures

**Port already in use**

```text
error: failed to bind socket
```

Another process is already on port 8080. Change `--port` or kill the existing llama-server.

**Model file not found**

```text
failed to load model
```

Check the path to the `.gguf` file. If the path contains spaces, wrap it in quotes:

```bat
llama-server.exe -m "C:\My Models\model.gguf" --port 8080
```

**Connected but analysis hangs**

Not enough RAM, CPU-only 14B model, or `-c` is too large. Use 7B Q4_K_M and increase `BLAST_RADIUS_LLM_TIMEOUT`.

**curl returns BlastRadius HTML**

The URL is pointing at the application, not at llama-server. Check ports: 8000 = UI, 8080 = model.

**Antivirus / SmartScreen on Windows**

Sometimes blocks `llama-server.exe` downloaded from GitHub Releases. Allow the file or build from source.

---

## 9. Pre-demo checklist

- [ ] `.gguf` downloaded to disk (not into the repository)
- [ ] `llama-server -m ... --port 8080` is running and the window is open
- [ ] `curl http://127.0.0.1:8080/v1/models` returns JSON
- [ ] BlastRadius is on **8000**
- [ ] AI is selected in the UI, status shows **Connected**
- [ ] Load demo → Run AI analysis
- [ ] In the test block you can see `✓ Generated` and either `✓ Pytest passed` or `✕ Pytest failed`

AST always remains as a fallback engine: switch the radio button and the model is no longer needed.
