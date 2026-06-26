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
