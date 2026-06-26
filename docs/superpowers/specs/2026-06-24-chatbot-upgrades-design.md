# Design: Conversational Memory, Cache Invalidation, and CI

**Date:** 2026-06-24
**Status:** Approved

## Overview

Three self-contained upgrades to the Company Regulations Chatbot:

1. **Conversational memory** — feed the last 3 turns of a session back into the
   prompt so follow-up questions have context.
2. **Cache invalidation by document hash** — drop cached answers when the rules
   document changes, and reconcile the cache with conversational memory.
3. **GitHub Actions CI** — run the offline pytest suite on every push and PR.

Out of scope: real retrieval/RAG, authentication, rate limiting, linting.

## #1 — Conversational memory (last 3 turns)

### Behavior
- On each request, fetch the most recent **3 turns** for the session
  (`storage.get_history(session_id, limit=3)`, returned in chronological order)
  **before** storing the current turn, so history reflects prior context only.
- Render those turns into a history block and inject it into the prompt.
- A session's first message has no prior history, so the rendered block is an
  empty string and single-turn behavior is unchanged.

### Changes
**`app/rag_chain.py`**
- Prompt template gains a `{history}` variable, placed above the regulations
  block. `input_variables=["context", "question", "history"]`.
- New helper `format_history(turns: list[dict]) -> str`:
  - Empty list → empty string `""`.
  - Otherwise a block, e.g.:
    ```
    ===== LỊCH SỬ HỘI THOẠI =====
    Người dùng: <question>
    Trợ lý: <answer>
    ...
    =============================
    ```
  - `turns` are dicts shaped like `storage.get_history` output:
    `{"user": ..., "bot": ..., "timestamp": ...}`.

**`app/main.py`**
- `build_answer(question, history)` (was `build_answer(question)`): formats the
  prompt with `history=format_history(history)`.
- `HISTORY_LIMIT = 3` constant.
- Request flow (`/ask` and `/ask_stream`):
  ```
  question = validate_question(...)
  prior = storage.get_history(session_id, limit=HISTORY_LIMIT)
  is_first_turn = (len(prior) == 0)
  # cache logic gated on is_first_turn (see #2)
  answer = build_answer(question, prior)
  store turn in SQLite
  ```
- Streaming endpoint builds the prompt the same way (with history) before
  streaming; history is still fetched before the current turn is stored.

### Token budget
Bounded to 3 turns by design. The existing `check_context_fits` warning still
covers the document; history is accepted as additional bounded overhead. No
per-turn truncation in this iteration (YAGNI).

## #2 — Cache invalidation by document hash

### Behavior
- Compute `doc_hash = sha256(context_text).hexdigest()` when components load.
- `cache.json` format changes from a flat map to:
  ```json
  { "doc_hash": "<hex>", "entries": { "<normalized question>": { "answer": "...", "timestamp": "..." } } }
  ```
- On load, if the stored `doc_hash` differs from the current one — or the file is
  in the old flat format (no `doc_hash` key) — entries are dropped (return `{}`).
  This guarantees stale answers cannot survive a rules edit.
- **Cache is consulted and written only on the first turn of a session**
  (`is_first_turn`). First-turn answers carry no conversational history, so they
  are safe to share as global FAQ entries. Follow-ups never read or write the
  cache and always call the LLM.

### Changes
**`app/rag_chain.py`**
- `create_qa_components()` adds `"doc_hash"` to its returned dict.
- `load_cache(doc_hash)` reads `cache.json`; returns the `entries` dict only when
  the stored hash matches, otherwise `{}`. Tolerates missing file / legacy
  format / corrupt JSON (returns `{}`, logs a warning as today).
- `save_cache(entries, doc_hash)` writes `{"doc_hash": doc_hash, "entries": entries}`.

**`app/main.py`**
- `DOC_HASH = components["doc_hash"]`; `CACHE = load_cache(DOC_HASH)`.
- Cache read on `/ask` and `/ask_stream` only when `is_first_turn`.
- `store_answer` writes to SQLite always; writes to `CACHE` + `save_cache(CACHE, DOC_HASH)`
  only when `is_first_turn`.

## #8 — GitHub Actions CI

**`.github/workflows/ci.yml`**
- Triggers: `push` and `pull_request`.
- Runner: `ubuntu-latest`, Python `3.11`.
- Steps: checkout → setup-python → `pip install -r requirements-dev.txt` →
  `pytest`.
- Rationale: the suite mocks the LLM and runs offline; `app.main` import
  constructs `OllamaLLM` lazily (no network call) and reads the committed
  `data/company_rules.txt`, so no Ollama server is required in CI.

## Testing (TDD)

Existing tests are updated for the two signature changes:
- `build_answer(question)` → `build_answer(question, history)` — the `fake_llm`
  fixture's `fake_build_answer` gains a `history` parameter.
- `save_cache(entries)` → `save_cache(entries, doc_hash)` — the `isolate_state`
  fixture's monkeypatched lambda accepts the extra argument.

New tests:
1. **Follow-up not cached:** within one session, asking the same question twice
   (so the second ask has prior history) calls the LLM both times and the second
   response is `cached: false`. Contrast with the existing cross-cold-start cache
   test, which uses fresh sessions.
2. **History reaches the LLM:** on turn 2, the captured `history` argument to the
   faked `build_answer` contains the prior turn's question/answer.
3. **Cache busts on doc change:** `load_cache` returns `{}` when the stored
   `doc_hash` differs from the requested one; returns saved entries when it
   matches. (Unit test against a temp `cache.json`.)

CI itself has no automated test (it is configuration); it is validated by the
suite passing on the first push.

## Files touched
- `app/rag_chain.py` — prompt `{history}`, `format_history`, `doc_hash`,
  `load_cache`/`save_cache` signatures.
- `app/main.py` — history fetch, `is_first_turn` gating, `build_answer` signature,
  cache wiring.
- `tests/test_api.py` — updated fixtures + 2 new behavior tests.
- `tests/test_rag_chain.py` (new) — `load_cache` hash test, `format_history` test.
- `.github/workflows/ci.yml` (new).
- `README.md` — note the env defaults / behavior if needed (minor).
