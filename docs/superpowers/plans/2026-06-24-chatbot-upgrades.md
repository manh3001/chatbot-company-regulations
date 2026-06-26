# Chatbot Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add conversational memory (last 3 turns), document-hash cache invalidation, and GitHub Actions CI to the Company Regulations Chatbot.

**Architecture:** Keep the existing "whole document in context" QA design. Inject a bounded history block into the prompt; fetch history from SQLite before storing the current turn. Version the JSON answer cache by a SHA-256 hash of the rules document and gate cache use to a session's first turn. Add a CI workflow that runs the existing offline pytest suite.

**Tech Stack:** FastAPI, LangChain (`langchain-ollama`), Ollama, SQLite (stdlib), pytest, GitHub Actions.

## Global Constraints

- Python 3.10+ (CI pins 3.11).
- No new runtime dependencies — use stdlib `hashlib` only.
- Tests must run offline (LLM is mocked); never require a running Ollama server.
- `cache.json`, `history.db`, `chroma_db/` stay git-ignored.
- Source/answer language is Vietnamese; prompt text stays Vietnamese.

---

### Task 1: Document-hash cache invalidation

**Files:**
- Modify: `app/rag_chain.py` (`load_cache`, `save_cache`, `create_qa_components`, imports, `__all__`)
- Modify: `app/main.py` (cache wiring: `DOC_HASH`, `CACHE`, `store_answer`)
- Modify: `tests/test_api.py` (`isolate_state` fixture lambda signature)
- Test: `tests/test_rag_chain.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `rag_chain.compute_doc_hash(context_text: str) -> str`
  - `rag_chain.load_cache(doc_hash: str) -> dict` (returns the `entries` map)
  - `rag_chain.save_cache(entries: dict, doc_hash: str) -> None`
  - `create_qa_components()` return dict gains `"doc_hash": str`
  - `main.DOC_HASH: str`, `main.CACHE: dict`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rag_chain.py`:

```python
"""Unit tests cho tầng cache trong rag_chain (chạy offline, không cần Ollama)."""
import json

from app import rag_chain


def test_load_cache_returns_entries_when_hash_matches(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        json.dumps({"doc_hash": "abc", "entries": {"q": {"answer": "a", "timestamp": "t"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(rag_chain, "CACHE_FILE", str(cache_file))
    assert rag_chain.load_cache("abc") == {"q": {"answer": "a", "timestamp": "t"}}


def test_load_cache_busts_when_hash_differs(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        json.dumps({"doc_hash": "old", "entries": {"q": {"answer": "a", "timestamp": "t"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(rag_chain, "CACHE_FILE", str(cache_file))
    assert rag_chain.load_cache("new") == {}


def test_load_cache_busts_on_legacy_flat_format(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        json.dumps({"q": {"answer": "a", "timestamp": "t"}}), encoding="utf-8"
    )
    monkeypatch.setattr(rag_chain, "CACHE_FILE", str(cache_file))
    assert rag_chain.load_cache("any") == {}


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr(rag_chain, "CACHE_FILE", str(cache_file))
    rag_chain.save_cache({"q": {"answer": "a", "timestamp": "t"}}, "h1")
    assert rag_chain.load_cache("h1") == {"q": {"answer": "a", "timestamp": "t"}}
    assert rag_chain.load_cache("h2") == {}


def test_compute_doc_hash_is_stable_and_sensitive():
    assert rag_chain.compute_doc_hash("abc") == rag_chain.compute_doc_hash("abc")
    assert rag_chain.compute_doc_hash("abc") != rag_chain.compute_doc_hash("abd")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rag_chain.py -v`
Expected: FAIL — `load_cache()` currently takes no `doc_hash` argument and `compute_doc_hash` does not exist (`TypeError` / `AttributeError`).

- [ ] **Step 3: Implement rag_chain changes**

In `app/rag_chain.py`, add `import hashlib` to the imports block (top of file, near `import json`).

Replace the existing `load_cache` and `save_cache` functions:

```python
def compute_doc_hash(context_text: str) -> str:
    """Hash nội dung tài liệu để phát hiện khi nội quy thay đổi."""
    return hashlib.sha256(context_text.encode("utf-8")).hexdigest()


def load_cache(doc_hash: str) -> dict:
    """Đọc cache.json và chỉ trả về entries nếu doc_hash khớp tài liệu hiện tại.
    Nếu tài liệu đã đổi (hoặc file ở định dạng cũ/hỏng) thì coi như cache rỗng."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("doc_hash") == doc_hash:
                return data.get("entries") or {}
        except Exception as e:
            logger.warning("❌ Lỗi khi đọc cache: %s", e)
    return {}


def save_cache(entries: dict, doc_hash: str) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"doc_hash": doc_hash, "entries": entries},
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception as e:
        logger.warning("❌ Lỗi khi ghi cache: %s", e)
```

In `create_qa_components`, add `doc_hash` to the returned dict:

```python
    return {
        "llm": llm,
        "prompt": prompt,
        "context": context_text,
        "context_fits": context_fits,
        "doc_hash": compute_doc_hash(context_text),
    }
```

Update `__all__` to include the new helper:

```python
__all__ = [
    "create_qa_components",
    "load_cache",
    "save_cache",
    "compute_doc_hash",
    "load_document",
    "check_context_fits",
]
```

- [ ] **Step 4: Wire the cache into `app/main.py`**

Remove the early cache load line (currently `CACHE = load_cache()  # normalized ...`, around line 38).

After the components are created (the block with `components = create_qa_components()` … `context_fits = components.get("context_fits", True)`), add:

```python
DOC_HASH = components["doc_hash"]
CACHE = load_cache(DOC_HASH)  # normalized question -> {answer, timestamp}
```

Keep `MAX_HISTORY = 50` and `MAX_QUESTION_LEN = 1000` where they are (move them next to the new lines if needed so `CACHE` is defined before first use).

Update `store_answer` to pass the hash to `save_cache`:

```python
def store_answer(session_id: str, question: str, answer: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    storage.add_turn(session_id, question, answer, timestamp)
    CACHE[normalize_question(question)] = {"answer": answer, "timestamp": timestamp}
    save_cache(CACHE, DOC_HASH)
    return timestamp
```

- [ ] **Step 5: Update the `isolate_state` fixture in `tests/test_api.py`**

Change the monkeypatched `save_cache` lambda to accept the new argument:

```python
    monkeypatch.setattr(main_module, "save_cache", lambda data, doc_hash=None: None)
```

- [ ] **Step 6: Run the full suite to verify it passes**

Run: `pytest -v`
Expected: PASS — all `tests/test_rag_chain.py` tests pass and the existing `tests/test_api.py` suite remains green.

- [ ] **Step 7: Commit**

```bash
git add app/rag_chain.py app/main.py tests/test_api.py tests/test_rag_chain.py
git commit -m "feat: invalidate answer cache when rules document changes"
```

---

### Task 2: Conversational memory (last 3 turns) + first-turn cache gating

**Files:**
- Modify: `app/rag_chain.py` (`format_history`, prompt `{history}` variable, `__all__`)
- Modify: `app/main.py` (`HISTORY_LIMIT`, `build_answer`, `store_answer`, `/ask`, `/ask_stream`)
- Modify: `tests/test_api.py` (`fake_llm` fixture + 2 new tests)

**Interfaces:**
- Consumes (from Task 1): `main.CACHE`, `main.DOC_HASH`, `rag_chain.save_cache(entries, doc_hash)`.
- Produces:
  - `rag_chain.format_history(turns: list[dict]) -> str`
  - `main.build_answer(question: str, history: list[dict]) -> str`
  - `main.store_answer(session_id, question, answer, is_first_turn: bool) -> str`
  - `main.HISTORY_LIMIT: int`

- [ ] **Step 1: Write the failing tests**

Replace the `fake_llm` fixture in `tests/test_api.py` so it matches the new `build_answer(question, history)` signature and records the history it received:

```python
@pytest.fixture
def fake_llm(monkeypatch):
    """Thay LLM thật bằng câu trả lời cố định; ghi lại history nhận được."""
    calls = {"count": 0, "last_history": None}

    def fake_build_answer(question: str, history) -> str:
        calls["count"] += 1
        calls["last_history"] = history
        return f"Trả lời cho: {question}"

    monkeypatch.setattr(main_module, "build_answer", fake_build_answer)
    return calls
```

Append two new tests to `tests/test_api.py`:

```python
def test_followup_in_session_is_not_cached(client, fake_llm):
    """Lượt 2 trong cùng session có lịch sử -> không dùng cache, gọi LLM lại."""
    sid = "conv-session"
    payload = {"question": "Giờ làm việc?", "session_id": sid}
    first = client.post("/ask", json=payload).json()
    second = client.post("/ask", json=payload).json()
    assert first["cached"] is False
    assert second["cached"] is False
    assert fake_llm["count"] == 2


def test_history_passed_to_llm_on_followup(client, fake_llm):
    """Lượt sau phải nhận lịch sử của lượt trước trong cùng session."""
    sid = "conv-session-2"
    client.post("/ask", json={"question": "Giờ làm việc?", "session_id": sid})
    client.post("/ask", json={"question": "Còn nghỉ trưa?", "session_id": sid})
    history = fake_llm["last_history"]
    assert history is not None
    assert any(turn["user"] == "Giờ làm việc?" for turn in history)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_api.py::test_followup_in_session_is_not_cached tests/test_api.py::test_history_passed_to_llm_on_followup -v`
Expected: FAIL — current `build_answer` takes one argument and the second identical in-session question is served from cache (`cached` would be `True`, and `count` would be `1`).

- [ ] **Step 3: Add `format_history` and the prompt variable in `app/rag_chain.py`**

Add the helper (place it near `create_qa_components`):

```python
def format_history(turns) -> str:
    """Dựng khối lịch sử hội thoại để chèn vào prompt. Rỗng nếu không có lượt nào."""
    if not turns:
        return ""
    lines = ["===== LỊCH SỬ HỘI THOẠI ====="]
    for turn in turns:
        lines.append(f"Người dùng: {turn['user']}")
        lines.append(f"Trợ lý: {turn['bot']}")
    lines.append("=============================")
    return "\n".join(lines)
```

In `create_qa_components`, change the prompt template to add `{history}` above the regulations block, and add `history` to `input_variables`:

```python
    template = """Bạn là trợ lý trả lời câu hỏi về nội quy công ty.
Chỉ dựa vào NỘI QUY bên dưới để trả lời. Tuyệt đối không bịa thêm thông tin.
Nếu nội quy không đề cập, hãy trả lời đúng một câu: "Không có thông tin trong nội quy." (không cần ghi nguồn).
Khi có thông tin, sau câu trả lời hãy xuống dòng và ghi nguồn theo dạng:
Nguồn: <tên mục liên quan, ví dụ: "Mục 2. Thời gian làm việc">

{history}
===== NỘI QUY =====
{context}
===================

Câu hỏi: {question}
Trả lời (ngắn gọn, bằng tiếng Việt, chỉ nêu đúng thông tin được hỏi):"""
    prompt = PromptTemplate(
        template=template, input_variables=["context", "question", "history"]
    )
```

Add `format_history` to `__all__`:

```python
__all__ = [
    "create_qa_components",
    "load_cache",
    "save_cache",
    "compute_doc_hash",
    "format_history",
    "load_document",
    "check_context_fits",
]
```

- [ ] **Step 4: Update `app/main.py` imports and `build_answer`**

Add `format_history` to the `from app.rag_chain import (...)` block.

Add the history-limit constant next to `MAX_HISTORY`:

```python
HISTORY_LIMIT = 3
```

Change `build_answer` to accept and format history:

```python
def build_answer(question: str, history) -> str:
    formatted = prompt.format(
        context=context_text,
        question=question,
        history=format_history(history),
    )
    return call_llm(formatted).strip()
```

- [ ] **Step 5: Gate the cache by first turn in `store_answer` and both endpoints**

Update `store_answer` to only touch the cache on the first turn:

```python
def store_answer(session_id: str, question: str, answer: str, is_first_turn: bool) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    storage.add_turn(session_id, question, answer, timestamp)
    if is_first_turn:
        CACHE[normalize_question(question)] = {"answer": answer, "timestamp": timestamp}
        save_cache(CACHE, DOC_HASH)
    return timestamp
```

Rewrite the body of `/ask` (`ask_question`) so history is fetched first and cache is gated:

```python
@app.post("/ask")
async def ask_question(req: QuestionRequest):
    question = validate_question(req.question)
    session_id = req.session_id
    start = time.time()
    logger.info("Nhận câu hỏi: %s (session=%s)", question, session_id)

    prior = storage.get_history(session_id, limit=HISTORY_LIMIT)
    is_first_turn = len(prior) == 0

    if is_first_turn:
        cached = CACHE.get(normalize_question(question))
        if cached:
            logger.info("Lấy câu trả lời từ cache")
            return JSONResponse(
                {
                    "session_id": session_id,
                    "question": question,
                    "answer": cached["answer"],
                    "response_time": round(time.time() - start, 3),
                    "cached": True,
                    "timestamp": cached["timestamp"],
                }
            )

    try:
        answer = build_answer(question, prior)
        timestamp = store_answer(session_id, question, answer, is_first_turn)
        elapsed = round(time.time() - start, 3)
        logger.info("Trả lời xong trong %ss", elapsed)

        return JSONResponse(
            {
                "session_id": session_id,
                "question": question,
                "answer": answer,
                "response_time": elapsed,
                "cached": False,
                "timestamp": timestamp,
            }
        )
    except Exception as e:
        logger.exception("❌ Lỗi xử lý câu hỏi")
        raise HTTPException(status_code=500, detail=str(e))
```

Rewrite the body of `/ask_stream` (`ask_question_stream`) the same way:

```python
@app.post("/ask_stream")
async def ask_question_stream(req: QuestionRequest):
    """Streaming endpoint: trả token dần bằng API streaming gốc của Ollama."""
    question = validate_question(req.question)
    session_id = req.session_id
    logger.info("Nhận (stream) câu hỏi: %s (session=%s)", question, session_id)

    prior = storage.get_history(session_id, limit=HISTORY_LIMIT)
    is_first_turn = len(prior) == 0

    if is_first_turn:
        cached = CACHE.get(normalize_question(question))
        if cached:
            logger.info("Stream câu trả lời từ cache")

            def cached_gen():
                yield cached["answer"]

            return StreamingResponse(cached_gen(), media_type="text/plain")

    formatted = prompt.format(
        context=context_text,
        question=question,
        history=format_history(prior),
    )

    def generator():
        parts = []
        try:
            for chunk in llm.stream(formatted):
                text = chunk if isinstance(chunk, str) else str(chunk)
                parts.append(text)
                yield text
        except Exception as e:
            logger.exception("❌ Lỗi streaming")
            yield f"\n[Lỗi: {e}]"
            return
        answer = "".join(parts).strip()
        if answer:
            store_answer(session_id, question, answer, is_first_turn)

    return StreamingResponse(generator(), media_type="text/plain")
```

- [ ] **Step 6: Run the full suite to verify it passes**

Run: `pytest -v`
Expected: PASS — the two new tests pass; existing cache tests (`test_second_identical_question_is_cached`, `test_cache_key_is_normalized`) still pass because they post without a `session_id`, so each request is a fresh first-turn session.

- [ ] **Step 7: Commit**

```bash
git add app/rag_chain.py app/main.py tests/test_api.py
git commit -m "feat: add conversational memory and gate FAQ cache to first turn"
```

---

### Task 3: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `requirements-dev.txt`, the pytest suite from Tasks 1–2.
- Produces: nothing imported by other tasks (configuration only).

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: pip install -r requirements-dev.txt
      - name: Run tests
        run: pytest
```

- [ ] **Step 2: Validate the suite locally the way CI will**

Run: `pytest`
Expected: PASS — same green suite CI will run (offline, no Ollama needed).

- [ ] **Step 3: Commit and push**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run pytest on push and pull requests"
git push company main
```

- [ ] **Step 4: Confirm the workflow ran**

Open the repository's **Actions** tab on GitHub and confirm the **CI** workflow succeeded on the pushed commit.

---

## Self-Review

**Spec coverage:**
- #1 conversational memory → Task 2 (history fetch, `format_history`, `{history}` prompt var, `build_answer` signature). ✓
- #2 cache invalidation by doc hash → Task 1 (`compute_doc_hash`, versioned `cache.json`, `load_cache`/`save_cache`). ✓
- #2 first-turn cache gating (memory interaction) → Task 2 (`is_first_turn` in both endpoints + `store_answer`). ✓
- #8 CI → Task 3. ✓
- Signature-change test updates → Task 1 (Step 5 fixture), Task 2 (Step 1 fixture). ✓
- New tests (follow-up not cached, history reaches LLM, doc-hash bust) → Task 2 Step 1, Task 1 Step 1. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `load_cache(doc_hash)`/`save_cache(entries, doc_hash)`/`compute_doc_hash` used consistently across Task 1 and Task 2; `build_answer(question, history)` and `store_answer(..., is_first_turn)` consistent between definition and call sites; `format_history(turns)` consumes `storage.get_history` output shape `{"user","bot","timestamp"}`. ✓
