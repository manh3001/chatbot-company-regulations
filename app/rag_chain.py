import os
import json
import logging
from dotenv import load_dotenv

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import PromptTemplate
from langchain_ollama import OllamaLLM
from langchain_core.runnables import RunnablePassthrough  # only if needed

# chromadb errors
try:
    import chromadb
    from chromadb.errors import InvalidArgumentError
except Exception:
    chromadb = None
    InvalidArgumentError = Exception

load_dotenv()
logger = logging.getLogger(__name__)

CACHE_FILE = "cache.json"


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data or {}
        except Exception as e:
            print("❌ Lỗi khi đọc cache:", e)
    return {}


def save_cache(cache_data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("❌ Lỗi khi ghi cache:", e)


def _create_embeddings():
    """
    Tạo embedding object (HuggingFace). Bạn có thể đổi model_name nếu cần.
    """
    embeddings = HuggingFaceEmbeddings(
        model_name=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2"),
        model_kwargs={"device": os.getenv("EMBEDDING_DEVICE", "cuda")},
        encode_kwargs={"normalize_embeddings": True},
    )
    return embeddings


def _ensure_vectorstore(split_docs, embeddings, persist_dir="./chroma_db"):
    """
    Tải Chroma từ disk nếu có, nếu mismatch dimension -> recreate DB.
    Trả về instance Chroma.
    """
    if os.path.exists(persist_dir):
        logger.info("📂 Đang tải lại Chroma DB đã lưu...")
        try:
            vectordb = Chroma(persist_directory=persist_dir, embedding_function=embeddings)
            # quick test: similarity_search with a dummy str to surface dimension errors early
            try:
                vectordb.similarity_search("test", k=1)
            except InvalidArgumentError as e:
                # dimension mismatch -> recreate
                logger.warning("⚠️ Dimension mismatch in existing Chroma DB, sẽ tạo mới DB với embedding hiện tại.")
                vectordb = Chroma.from_documents(split_docs, embeddings, persist_directory=persist_dir)
            return vectordb
        except Exception as e:
            logger.warning("⚠️ Không thể load Chroma từ disk, sẽ tạo mới. Chi tiết: %s", e)
            vectordb = Chroma.from_documents(split_docs, embeddings, persist_directory=persist_dir)
            return vectordb
    else:
        logger.info("📁 Tạo mới Chroma DB...")
        vectordb = Chroma.from_documents(split_docs, embeddings, persist_directory=persist_dir)
        return vectordb


def create_qa_components(
    docs_path="data/company_rules.txt",
    chunk_size=1000,
    chunk_overlap=200,
    persist_dir="./chroma_db",
    retriever_k=5,
):
    """
    Tạo components và trả về dict:
    { "retriever": retriever, "prompt": prompt, "llm": llm, "vectorstore": vectordb, "embeddings": embeddings }
    """
    logger.info("🚀 Bắt đầu khởi tạo RAG components...")

    # 1) Load documents
    loader = TextLoader(docs_path, encoding="utf-8")
    documents = loader.load()
    logger.info(f"📄 Đã load {len(documents)} document(s)")

    # 2) Split
    splitter = CharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    split_docs = splitter.split_documents(documents)
    logger.info(f"📌 Số đoạn sau khi chia: {len(split_docs)}")

    # 3) Embeddings
    embeddings = _create_embeddings()
    logger.info("🔧 Embedding đã sẵn sàng")

    # 4) Vector DB (Chroma)
    vectordb = _ensure_vectorstore(split_docs, embeddings, persist_dir=persist_dir)
    retriever = vectordb.as_retriever(search_kwargs={"k": retriever_k})

    # 5) LLM (Ollama)
    llm = OllamaLLM(
        model=os.getenv("OLLAMA_MODEL", "phi3"),
        base_url=os.getenv("BASE_URL", "http://127.0.0.1:11434"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
        top_k=int(os.getenv("LLM_TOP_K", "40")),
        repeat_penalty=float(os.getenv("LLM_REPEAT_PENALTY", "1.2")),
        num_ctx=int(os.getenv("LLM_NUM_CTX", "1024")),
    )

    # 6) Prompt (bạn có thể sửa prompt ở đây)
    template = """
Bạn là trợ lý AI hiểu rõ nội quy công ty.
Dựa trên thông tin sau (chỉ sử dụng nội dung trong context để trả lời, nếu không có thông tin thì trả về 'Không tìm thấy thông tin liên quan'):
{context}

Question: {question}

Answer (ngắn gọn, chính xác):
"""
    prompt = PromptTemplate(template=template, input_variables=["context", "question"])

    logger.info("✅ Components RAG đã sẵn sàng")
    return {
        "retriever": retriever,
        "prompt": prompt,
        "llm": llm,
        "vectorstore": vectordb,
        "embeddings": embeddings,
    }


# --- Utility: rewrite query bằng LLM (dùng lịch sử) ---
def rewrite_query_with_history(llm, prompt_template, history: list, question: str):
    """
    Sử dụng LLM để rewrite câu hỏi dựa trên lịch sử (nếu có).
    history: list of dicts [{"user": "...", "bot": "..."}]
    Trả về câu query đã rewrite (string).
    """
    # Build a compact conversation context
    conv = ""
    for turn in (history or [])[-6:]:  # chỉ lấy 6 turn gần nhất
        u = turn.get("user", "").strip()
        b = turn.get("bot", "").strip()
        if u:
            conv += f"User: {u}\n"
        if b:
            conv += f"Assistant: {b}\n"

    rewrite_prompt = (
        "Bạn là một trợ lý giúp biến câu hỏi ngắn gọn, rõ ràng để tìm thông tin trong tài liệu.\n"
        "Dựa trên lịch sử hội thoại sau và câu hỏi của user, hãy viết lại câu hỏi (1 câu ngắn gọn) "
        "thật rõ ràng để dùng cho truy vấn sematic search.\n\n"
        f"History:\n{conv}\n"
        f"Original question: {question}\n\n"
        "Rewritten question:"
    )
    try:
        # Thử một vài cách gọi LLM (tùy wrapper)
        try:
            out = llm.invoke(rewrite_prompt)
        except Exception:
            try:
                gen = llm.generate([rewrite_prompt])
                # try to extract text
                if hasattr(gen, "generations"):
                    out = gen.generations[0][0].text
                else:
                    out = str(gen)
            except Exception:
                out = llm(rewrite_prompt)
        if isinstance(out, dict):
            candidate = out.get("text") or out.get("output_text") or str(out)
        elif hasattr(out, "generations"):
            try:
                candidate = out.generations[0][0].text
            except Exception:
                candidate = str(out)
        else:
            candidate = str(out)
        # strip and single-line
        candidate = " ".join(candidate.strip().splitlines())
        # fallback: if rewrite is empty, return original
        return candidate if candidate else question
    except Exception as e:
        logger.warning("⚠️ Lỗi khi rewrite query: %s — fallback dùng original", e)
        return question


# --- Utility: rerank docs by score (we rely on vectorstore scores) ---
def get_top_docs_vectorstore(vectorstore, query, top_k=3, rerank_k=10):
    """
    Lấy top_k document dựa trên similarity scores từ vectorstore.
    Sử dụng similarity_search_with_score nếu có (trả về list of (doc, score)).
    """
    try:
        # nhiều vectorstores hỗ trợ similarity_search_with_score(query, k)
        docs_and_scores = vectorstore.similarity_search_with_score(query, k=rerank_k)
        # docs_and_scores: list of (doc, score)
        # sắp xếp theo score (tốt nhất đầu)
        docs_and_scores_sorted = sorted(docs_and_scores, key=lambda x: x[1], reverse=True)
        top = docs_and_scores_sorted[:top_k]
        docs = [d for d, s in top]
        scores = [s for d, s in top]
        return docs, scores
    except Exception as e:
        logger.warning("⚠️ Rerank bằng score thất bại (%s). Fallback dùng retriever.get_relevant_documents", e)
        try:
            docs = vectorstore.as_retriever().get_relevant_documents(query)  # fallback
            return docs[:top_k], [None] * min(top_k, len(docs))
        except Exception:
            logger.exception("🔴 Rerank fallback thất bại")
            return [], []


# Export helpers used bởi main.py
__all__ = ["create_qa_components", "load_cache", "save_cache", "rewrite_query_with_history", "get_top_docs_vectorstore"]

