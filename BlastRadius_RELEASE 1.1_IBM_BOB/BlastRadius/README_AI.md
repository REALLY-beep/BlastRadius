# BlastRadius — установка локального AI (GGUF)

Это отдельная инструкция только для режима **AI — Local GGUF**.  
Режим **AST** в этом файле не нужен: он работает без модели, без интернета и без llama-server.

BlastRadius **не загружает** `.gguf` сам. Он ходит по HTTP в локальный `llama-server` (llama.cpp) и больше никуда исходники не отправляет.

```text
GGUF-файл на диске
        ↓
llama.cpp llama-server   ←  вот сюда кладётся модель
        ↓  HTTP  127.0.0.1:8080/v1/chat/completions
BlastRadius (FastAPI)    ←  сюда модель НЕ класть
        ↓
UI: Connected / анализ / pytest
```

Если llama-server не запущен, AI-режим покажет ошибку и **не** переключится на AST.

---

## 1. Что должно получиться

Два процесса одновременно:

| Процесс | Порт по умолчанию | Зачем |
| --- | --- | --- |
| BlastRadius (`start.bat` / uvicorn) | **8000** | Сайт анализа |
| `llama-server` с GGUF | **8080** | Локальная модель |

В UI:

1. Analysis Engine → **AI — Local GGUF**
2. Server → `http://127.0.0.1:8080`
3. **Check connection** → **Connected**
4. Analyze

---

## 2. Что скачать заранее

Нужны три вещи:

1. **Python 3.10+** — уже нужен для BlastRadius.
2. **llama.cpp llama-server** — сервер, который читает `.gguf`.
3. **Файл модели `*.gguf`** — веса. Это не часть репозитория BlastRadius.

Рекомендуемые модели для анализа кода (хватит 7B–14B, квант Q4_K_M или Q5_K_M):

- Qwen2.5-Coder 7B Instruct
- Qwen2.5-Coder 14B Instruct (если есть 12+ ГБ VRAM / много RAM)
- Llama 3.1 8B Instruct
- Gemma 2 9B Instruct

Имена на Hugging Face обычно выглядят так:

```text
*-Instruct-Q4_K_M.gguf
*-Instruct-Q5_K_M.gguf
```

Не бери «сырой» base без Instruct, если можно Instruct. Для BlastRadius модель должна уметь отвечать JSON и писать pytest.

Где лежит файл — неважно. Удобно так:

```text
Windows:  C:\models\qwen2.5-coder-7b-instruct-q4_k_m.gguf
Linux:    ~/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf
macOS:    ~/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf
```

**Не клади `.gguf` в папку BlastRadius.** Приложению нужен только URL сервера.

Ориентир по памяти:

| Квант 7B | RAM / VRAM примерно | Комментарий |
| --- | --- | --- |
| Q4_K_M | 6–8 ГБ | Нормальный старт |
| Q5_K_M | 8–10 ГБ | Чуть точнее |
| Q8_0 | 10–14 ГБ | Обычно незачем для демо |

---

## 3. Установка llama-server

Нужен именно **llama-server** из llama.cpp. Он отдаёт OpenAI-совместимый endpoint:

```text
http://127.0.0.1:8080/v1/chat/completions
```

Репозиторий: [github.com/ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)

### Windows (самый простой путь)

1. Открой [Releases llama.cpp](https://github.com/ggml-org/llama.cpp/releases).
2. Скачай архив под своё железо:
   - есть NVIDIA GPU → сборка с CUDA (`cudart`, `cuBLAS` в имени релиза);
   - только CPU → CPU / `noavx` / обычный `bin`.
3. Распакуй, например в `C:\llama.cpp\`.
4. Внутри должен быть `llama-server.exe` (в новых релизах) или `server.exe` (в старых).

Проверка из `cmd`:

```bat
cd C:\llama.cpp
llama-server.exe -h
```

Если команда `llama-server` уже в PATH, можно не писать полный путь.

### Linux

Вариант A — готовый бинарник с GitHub Releases.

Вариант B — сборка:

```bash
sudo apt update
sudo apt install -y build-essential cmake git
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build -DGGML_CUDA=OFF
cmake --build build --config Release -t llama-server
```

Бинарник обычно здесь:

```text
build/bin/llama-server
```

Для NVIDIA замени флаг на `-DGGML_CUDA=ON` (нужны CUDA toolkit и драйвер).

### macOS (Apple Silicon)

```bash
brew install llama.cpp
```

или сборка из исходников. На M1/M2/M3 Metal подхватывается сам.

Проверка:

```bash
llama-server -h
```

---

## 4. Запуск модели

Сначала BlastRadius **не** запускай на порту 8080. `start.bat` поднимает его на **8000**, это правильно: 8080 оставляем модели.

### Windows

```bat
cd C:\llama.cpp
llama-server.exe -m C:\models\qwen2.5-coder-7b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8080 -c 4096 --jinja
```

### Linux / macOS

```bash
llama-server -m ~/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8080 -c 4096 --jinja
```

Полезные флаги:

| Флаг | Зачем |
| --- | --- |
| `-m файл.gguf` | путь к модели, обязателен |
| `--host 127.0.0.1` | только локально, исходники никуда не уходят |
| `--port 8080` | порт, который ждёт BlastRadius |
| `-c 4096` | контекст. Для дифа + исходников лучше 4096–8192 |
| `-ngl 99` | слить слои на GPU, если GPU есть |
| `--jinja` | шаблоны чата Instruct-моделей |

Окно с llama-server **не закрывай**. BlastRadius к нему подключается, пока процесс жив.

Успешный старт в логе выглядит примерно так:

```text
llama server listening at http://127.0.0.1:8080
```

Проверка без UI:

```bash
curl http://127.0.0.1:8080/v1/models
curl http://127.0.0.1:8080/health
```

Должен вернуться JSON со списком моделей / статусом ok, а не страница BlastRadius.

---

## 5. Связка с BlastRadius

Терминал 1 — приложение:

```bat
start.bat
```

или вручную:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Открой http://127.0.0.1:8000

Терминал 2 — модель, команда из раздела 4.

В интерфейсе:

1. Выбери **AI — Local GGUF**. Появится блок сервера.
2. **SERVER:** `http://127.0.0.1:8080`  
   Можно вставить и полный путь `http://127.0.0.1:8080/v1/chat/completions` — лишний суффикс обрежется.
3. **MODEL NAME:** `local-gguf`  
   llama.cpp часто игнорирует имя. Если `/v1/models` вернул конкретный id, вставь его.
4. **Check connection**.
5. Нужен статус **Connected**.
6. Load demo → **Run AI analysis**.

Код уходит только на этот URL. Cloud API нет.

---

## 6. Что означают статусы

| Статус в UI | Что случилось | Что делать |
| --- | --- | --- |
| **Connected** | llama-server отвечает, модель загружена | Можно анализировать |
| **Disconnected** | порт закрыт, не тот процесс, или URL указывает на сам BlastRadius | Запусти llama-server, проверь порт |
| **Invalid response** | что-то слушает порт, но это не llama-server | Не тот URL / не тот сервер |
| **Model unavailable** | сервер жив, GGUF ещё грузится или не загрузился | Подожди или проверь `-m` |

Типичная ошибка: и BlastRadius, и llama-server на 8080. Тогда Check connection напишет, что это BlastRadius, а не модель.

Решения:

- BlastRadius оставь на **8000** (`start.bat` так и делает);
- либо llama-server на другом порту:

```bash
llama-server -m ~/models/model.gguf --port 8081 --host 127.0.0.1
```

и в UI укажи `http://127.0.0.1:8081`.

Переменные окружения, если не хочешь каждый раз править форму:

```text
BLAST_RADIUS_LLM_URL=http://127.0.0.1:8080
BLAST_RADIUS_LLM_MODEL=local-gguf
BLAST_RADIUS_LLM_TIMEOUT=120
BLAST_RADIUS_LLM_RETRIES=2
```

---

## 7. Если анализ запустился, но тесты красные

Это нормально и не «фейковый успех». Пайплайн такой:

```text
модель пишет pytest
    → проверка синтаксиса
    → файл во временную папку
    → настоящий pytest
    → PASS / FAIL в UI
```

При FAIL модель получает вывод pytest и может исправить тест (1–2 попытки, не бесконечно).

Частые причины FAIL:

- модель выдумала функцию, которой нет в проекте;
- слишком слабый GGUF / маленький контекст (`-c` увеличь до 8192);
- не Instruct-модель, в ответ лезет проза вместо кода.

Режим AST при этом не включается сам.

---

## 8. Частые поломки

**Порт занят**

```text
error: failed to bind socket
```

Другой процесс уже на 8080. Смени `--port` или убей старый llama-server.

**Файл модели не найден**

```text
failed to load model
```

Проверь путь к `.gguf`. Пробелы в пути — в кавычки:

```bat
llama-server.exe -m "C:\My Models\model.gguf" --port 8080
```

**Connected есть, анализ висит**

Мало RAM, CPU-only 14B, или `-c` слишком большой. Возьми 7B Q4_K_M, увеличь `BLAST_RADIUS_LLM_TIMEOUT`.

**curl открывает HTML BlastRadius**

URL указывает на приложение, не на llama-server. Смотри порты: 8000 = UI, 8080 = модель.

**Антивирус / SmartScreen на Windows**

Иногда режет `llama-server.exe` из GitHub Releases. Разреши файл или собери из исходников.

---

## 9. Мини-чеклист перед демо

- [ ] `.gguf` скачан на диск (не в репозиторий)
- [ ] `llama-server -m ... --port 8080` запущен и не закрыт
- [ ] `curl http://127.0.0.1:8080/v1/models` отвечает JSON
- [ ] BlastRadius на **8000**
- [ ] В UI выбран AI, статус **Connected**
- [ ] Load demo → Run AI analysis
- [ ] В блоке теста видно `✓ Generated` и реальный `✓ Pytest passed` или `✕ Pytest failed`

AST всегда остаётся запасным движком: переключил радиокнопку — и модель больше не нужна.
