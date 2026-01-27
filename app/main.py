import os
import time
import uuid
import logging
from datetime import datetime
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.rag_chain import (
    create_qa_components,
    load_cache,
    save_cache,
    rewrite_query_with_history,
    get_top_docs_vectorstore,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot_api")

app = FastAPI(title="Company Chatbot API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory caches / histories (lightweight)
CACHE = load_cache()  # question -> {answer, timestamp}
HISTORY = {}  # session_id -> list of {"user": "...", "bot": "..."}

# Request model
class QuestionRequest(BaseModel):
    question: str
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    stream: bool = Field(False, description="Nếu true dùng streaming endpoint (không bắt buộc)")

# Load components (retriever, prompt, llm, vectorstore, embeddings)
components = create_qa_components()
retriever = components["retriever"]
prompt = components["prompt"]
llm = components["llm"]
vectorstore = components["vectorstore"]
embeddings = components.get("embeddings", None)

logger.info("🌟 QA components loaded thành công")


# Helper: call LLM robustly (sync) and extract text
def call_llm_sync(llm_obj, text):
    try:
        out = None
        try:
            out = llm_obj.invoke(text)
        except Exception:
            try:
                gen = llm_obj.generate([text])
                # extract text
                if hasattr(gen, "generations"):
                    out = gen.generations[0][0].text
                else:
                    out = str(gen)
            except Exception:
                try:
                    out = llm_obj(text)
                except Exception as e:
                    out = str(e)
        # normalize
        if isinstance(out, dict):
            return out.get("text") or out.get("output_text") or str(out)
        if hasattr(out, "generations"):
            try:
                return out.generations[0][0].text
            except Exception:
                return str(out)
        return str(out)
    except Exception as e:
        logger.exception("Lỗi khi gọi LLM sync:")
        return f"Error: {e}"


# Helper: streaming generator (best-effort)
def stream_answer_generator(answer_text, chunk_size=120):
    """
    Nếu LLM không hỗ trợ streaming, chúng ta chunk text thành các phần nhỏ để gửi dần.
    Nếu LLM wrapper hỗ trợ stream natively, bạn có thể thay phần này bằng stream từ llm.
    """
    i = 0
    text = answer_text or ""
    while i < len(text):
        chunk = text[i : i + chunk_size]
        i += chunk_size
        yield chunk
        time.sleep(0.01)  # very small sleep so client gets chunks smoothly


@app.post("/ask")
async def ask_question(req: QuestionRequest):
    question = req.question.strip()
    session_id = req.session_id
    start = time.time()
    logger.info("Nhận câu hỏi: %s (session=%s)", question, session_id)

    # Ensure history exists
    if session_id not in HISTORY:
        HISTORY[session_id] = []

    # 1) Cache check
    if question in CACHE:
        logger.info("Lấy câu trả lời từ cache")
        cached = CACHE[question]
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

    # 2) Rewrite query using history (improve retrieval)
    try:
        rewritten = rewrite_query_with_history(llm, prompt, HISTORY[session_id], question)
        logger.info("Query rewritten: %s", rewritten)
    except Exception:
        rewritten = question

    # 3) Get top docs with rerank by vectorstore scores
    docs, scores = get_top_docs_vectorstore(vectorstore, rewritten, top_k=3, rerank_k=8)
    context = "\n\n".join(d.page_content.strip() for d in docs if getattr(d, "page_content", None))
    if not context:
        context = "Không tìm thấy thông tin liên quan trong tài liệu."

    # 4) Format prompt
    formatted = prompt.format(context=context, question=question)

    # 5) Call LLM sync and return
    try:
        answer = call_llm_sync(llm, formatted)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # update history & cache
        HISTORY[session_id].append({"user": question, "bot": answer})
        CACHE[question] = {"answer": answer, "timestamp": timestamp}
        save_cache(CACHE)

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
    """
    Streaming endpoint: trả từng chunk. Nếu llm wrapper hỗ trợ streaming natively
    bạn có thể sửa phần call_llm_sync => call_llm_stream.
    """
    question = req.question.strip()
    session_id = req.session_id
    logger.info("Nhận (stream) câu hỏi: %s (session=%s)", question, session_id)

    if session_id not in HISTORY:
        HISTORY[session_id] = []

    # rewrite
    rewritten = rewrite_query_with_history(llm, prompt, HISTORY[session_id], question)

    docs, scores = get_top_docs_vectorstore(vectorstore, rewritten, top_k=3, rerank_k=8)
    context = "\n\n".join(d.page_content.strip() for d in docs if getattr(d, "page_content", None))
    if not context:
        context = "Không tìm thấy thông tin liên quan trong tài liệu."

    formatted = prompt.format(context=context, question=question)

    # Try to use streaming API on LLM if exists
    # Best-effort: if llm has 'stream' method or 'stream_generate', use it.
    try:
        # Example: llm.stream_generate([...]) -> yields parts (depends on wrapper)
        if hasattr(llm, "stream") or hasattr(llm, "stream_generate"):
            # wrapper-specific call: try a few names
            stream_fn = None
            if hasattr(llm, "stream"):
                stream_fn = getattr(llm, "stream")
            elif hasattr(llm, "stream_generate"):
                stream_fn = getattr(llm, "stream_generate")

            if stream_fn:
                def generator():
                    try:
                        for part in stream_fn([formatted]):
                            # try to extract text
                            if isinstance(part, dict):
                                chunk = part.get("text") or str(part)
                            else:
                                chunk = str(part)
                            yield chunk
                    except Exception as e:
                        logger.warning("Stream from LLM failed, fallback chunking: %s", e)
                        # fallback: call sync and chunk
                        ans = call_llm_sync(llm, formatted)
                        for c in stream_answer_generator(ans):
                            yield c
                return StreamingResponse(generator(), media_type="text/plain")
        # Fallback: call sync and chunk the answer
        answer = call_llm_sync(llm, formatted)
        # update history and cache
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        HISTORY[session_id].append({"user": question, "bot": answer})
        CACHE[question] = {"answer": answer, "timestamp": timestamp}
        save_cache(CACHE)

        return StreamingResponse(stream_answer_generator(answer), media_type="text/plain")
    except Exception as e:
        logger.exception("❌ Lỗi streaming")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history/{session_id}")
async def get_history(session_id: str):
    return {"session_id": session_id, "history": HISTORY.get(session_id, [])}


@app.get("/health")
async def health():
    return {"status": "ok", "message": "running"}


# Static & Root
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")
