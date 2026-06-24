"""
Lưu trữ lịch sử hội thoại bằng SQLite (chuẩn thư viện, không cần cài thêm).
Lịch sử tồn tại qua các lần restart server.
"""
import os
import sqlite3
import threading

DB_PATH = os.getenv("HISTORY_DB", "history.db")

_lock = threading.Lock()
_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS turns (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                question    TEXT NOT NULL,
                answer      TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            )
            """
        )
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON turns(session_id)")
        _conn.commit()
    return _conn


def add_turn(session_id: str, question: str, answer: str, timestamp: str):
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO turns (session_id, question, answer, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, question, answer, timestamp),
        )
        conn.commit()


def get_history(session_id: str, limit: int = 50):
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT question, answer, timestamp FROM turns "
            "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    rows.reverse()  # trả về theo thứ tự thời gian tăng dần
    return [{"user": q, "bot": a, "timestamp": t} for q, a, t in rows]


def clear_all():
    """Xoá toàn bộ lịch sử (dùng cho test)."""
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM turns")
        conn.commit()
