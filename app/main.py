import os
import time
import uuid
import logging
import urllib.request
from datetime import datetime
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import storage
from app.rag_chain import (
    create_qa_components,
    load_cache,
    save_cache,
    format_history,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot_api")

app = FastAPI(title="Company Chatbot API", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_HISTORY = 50
MAX_QUESTION_LEN = 1000
HISTORY_LIMIT = 3


class QuestionRequest(BaseModel):
    question: str
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    stream: bool = Field(False, description="Nếu true dùng streaming endpoint")


# Load components (llm, prompt, full-document context)
components = create_qa_components()
prompt = components["prompt"]
llm = components["llm"]
context_text = components["context"]
context_fits = components.get("context_fits", True)

DOC_HASH = components["doc_hash"]
CACHE = load_cache(DOC_HASH)  # normalized question -> {answer, timestamp}

logger.info("🌟 QA components loaded thành công")


def normalize_question(question: str) -> str:
    """Chuẩn hoá câu hỏi để dùng làm khoá cache (gộp khoảng trắng, bỏ hoa/thường)."""
    return " ".join(question.lower().split())


def validate_question(question: str) -> str:
    question = question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống.")
    if len(question) > MAX_QUESTION_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Câu hỏi quá dài (tối đa {MAX_QUESTION_LEN} ký tự).",
        )
    return question


def call_llm(formatted: str) -> str:
    """Gọi LLM và trả về text. OllamaLLM.invoke trả về str."""
    out = llm.invoke(formatted)
    return out if isinstance(out, str) else str(out)


def build_answer(question: str, history) -> str:
    formatted = prompt.format(
        context=context_text,
        question=question,
        history=format_history(history),
    )
    return call_llm(formatted).strip()


def store_answer(session_id: str, question: str, answer: str, is_first_turn: bool) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    storage.add_turn(session_id, question, answer, timestamp)
    if is_first_turn:
        CACHE[normalize_question(question)] = {"answer": answer, "timestamp": timestamp}
        save_cache(CACHE, DOC_HASH)
    return timestamp


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


@app.get("/history/{session_id}")
async def get_history(session_id: str):
    return {
        "session_id": session_id,
        "history": storage.get_history(session_id, limit=MAX_HISTORY),
    }


@app.get("/health")
async def health():
    """Kiểm tra cả API lẫn kết nối tới Ollama."""
    base_url = os.getenv("BASE_URL", "http://127.0.0.1:11434")
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=3) as resp:
            ollama_ok = resp.status == 200
    except Exception as e:
        logger.warning("Ollama không phản hồi: %s", e)
        ollama_ok = False

    status = "ok" if ollama_ok else "degraded"
    return JSONResponse(
        status_code=200 if ollama_ok else 503,
        content={
            "status": status,
            "ollama": ollama_ok,
            "context_chars": len(context_text),
            "context_fits": context_fits,
        },
    )


# Static & Root
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")
