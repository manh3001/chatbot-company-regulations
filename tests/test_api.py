"""
Test cho API chatbot.

Các test này chạy OFFLINE: ta thay (mock) LLM bằng một hàm giả nên không cần
Ollama đang chạy. Mục tiêu là khoá hành vi của tầng API (validate, cache,
chuẩn hoá câu hỏi, health, history) để tránh hồi quy.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app import storage
from app.main import app


@pytest.fixture(autouse=True)
def isolate_state(monkeypatch):
    """Mỗi test bắt đầu với cache/history sạch và không ghi cache ra đĩa."""
    main_module.CACHE.clear()
    storage.clear_all()
    monkeypatch.setattr(main_module, "save_cache", lambda data, doc_hash=None: None)
    yield
    main_module.CACHE.clear()
    storage.clear_all()


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


@pytest.fixture
def client():
    return TestClient(app)


def test_ask_returns_answer(client, fake_llm):
    r = client.post("/ask", json={"question": "Giờ làm việc?"})
    assert r.status_code == 200
    data = r.json()
    assert data["answer"] == "Trả lời cho: Giờ làm việc?"
    assert data["cached"] is False
    assert fake_llm["count"] == 1


def test_empty_question_rejected(client, fake_llm):
    r = client.post("/ask", json={"question": "   "})
    assert r.status_code == 400


def test_too_long_question_rejected(client, fake_llm):
    r = client.post("/ask", json={"question": "a" * 1001})
    assert r.status_code == 400


def test_second_identical_question_is_cached(client, fake_llm):
    payload = {"question": "Nghỉ trưa mấy giờ?"}
    first = client.post("/ask", json=payload).json()
    second = client.post("/ask", json=payload).json()
    assert first["cached"] is False
    assert second["cached"] is True
    # LLM chỉ được gọi một lần — lần thứ hai lấy từ cache
    assert fake_llm["count"] == 1


def test_cache_key_is_normalized(client, fake_llm):
    client.post("/ask", json={"question": "Giờ làm việc?"})
    # Khác hoa/thường và khoảng trắng nhưng phải trúng cùng một cache entry
    second = client.post("/ask", json={"question": "  giờ   làm việc?  "}).json()
    assert second["cached"] is True
    assert fake_llm["count"] == 1


def test_history_records_turn(client, fake_llm):
    sid = "test-session"
    client.post("/ask", json={"question": "Giờ làm việc?", "session_id": sid})
    hist = client.get(f"/history/{sid}").json()
    assert len(hist["history"]) == 1
    assert hist["history"][0]["user"] == "Giờ làm việc?"


def test_health_reports_ollama_up(client, monkeypatch):
    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "app.main.urllib.request.urlopen", lambda url, timeout=3: FakeResp()
    )
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ollama"] is True
    assert "context_chars" in body


def test_health_reports_ollama_down(client, monkeypatch):
    def boom(url, timeout=3):
        raise OSError("connection refused")

    monkeypatch.setattr("app.main.urllib.request.urlopen", boom)
    r = client.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["ollama"] is False


def test_history_persists_across_storage_calls(client, fake_llm):
    """Lịch sử ghi vào SQLite phải đọc lại được (không phụ thuộc bộ nhớ tiến trình)."""
    sid = "persist-session"
    client.post("/ask", json={"question": "Giờ làm việc?", "session_id": sid})
    client.post("/ask", json={"question": "Nghỉ trưa mấy giờ?", "session_id": sid})
    # đọc trực tiếp từ tầng storage, không qua dict trong main
    rows = storage.get_history(sid)
    assert [r["user"] for r in rows] == ["Giờ làm việc?", "Nghỉ trưa mấy giờ?"]
    assert all("timestamp" in r for r in rows)


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
