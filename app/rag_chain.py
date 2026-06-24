import os
import json
import logging
from dotenv import load_dotenv

from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate

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
            logger.warning("❌ Lỗi khi đọc cache: %s", e)
    return {}


def save_cache(cache_data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("❌ Lỗi khi ghi cache: %s", e)


def load_document(docs_path="data/company_rules.txt"):
    """
    Đọc toàn bộ tài liệu nội quy. Vì tài liệu nhỏ nên ta nạp nguyên văn vào context
    thay vì dùng vector search (tránh việc truy hồi sai đoạn).
    """
    with open(docs_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def check_context_fits(context_text: str, num_ctx: int) -> bool:
    """
    Phương pháp nạp nguyên văn chỉ an toàn khi tài liệu đủ nhỏ so với cửa sổ ngữ cảnh.
    Ước lượng thô: tiếng Việt ~2.5 ký tự/token. Để dành ~512 token cho prompt + câu trả lời.
    Trả về True nếu vừa, False (kèm cảnh báo) nếu có nguy cơ tràn ngữ cảnh.
    """
    budget_tokens = max(num_ctx - 512, 0)
    approx_tokens = len(context_text) / 2.5
    if approx_tokens > budget_tokens:
        logger.warning(
            "⚠️ Tài liệu (~%d token) có thể vượt ngân sách ngữ cảnh (~%d token của num_ctx=%d). "
            "Câu trả lời có thể bị cắt. Hãy tăng LLM_NUM_CTX hoặc chuyển sang cơ chế truy hồi (retrieval).",
            int(approx_tokens), budget_tokens, num_ctx,
        )
        return False
    return True


def create_qa_components(docs_path="data/company_rules.txt"):
    """
    Trả về dict: { "llm": llm, "prompt": prompt, "context": context_text, "context_fits": bool }
    """
    logger.info("🚀 Khởi tạo QA components...")

    context_text = load_document(docs_path)
    logger.info("📄 Đã load tài liệu (%d ký tự)", len(context_text))

    num_ctx = int(os.getenv("LLM_NUM_CTX", "4096"))
    context_fits = check_context_fits(context_text, num_ctx)

    llm = OllamaLLM(
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        base_url=os.getenv("BASE_URL", "http://127.0.0.1:11434"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        repeat_penalty=float(os.getenv("LLM_REPEAT_PENALTY", "1.2")),
        num_ctx=num_ctx,
    )

    template = """Bạn là trợ lý trả lời câu hỏi về nội quy công ty.
Chỉ dựa vào NỘI QUY bên dưới để trả lời. Tuyệt đối không bịa thêm thông tin.
Nếu nội quy không đề cập, hãy trả lời đúng một câu: "Không có thông tin trong nội quy." (không cần ghi nguồn).
Khi có thông tin, sau câu trả lời hãy xuống dòng và ghi nguồn theo dạng:
Nguồn: <tên mục liên quan, ví dụ: "Mục 2. Thời gian làm việc">

===== NỘI QUY =====
{context}
===================

Câu hỏi: {question}
Trả lời (ngắn gọn, bằng tiếng Việt, chỉ nêu đúng thông tin được hỏi):"""
    prompt = PromptTemplate(template=template, input_variables=["context", "question"])

    logger.info("✅ Components đã sẵn sàng")
    return {
        "llm": llm,
        "prompt": prompt,
        "context": context_text,
        "context_fits": context_fits,
    }


__all__ = [
    "create_qa_components",
    "load_cache",
    "save_cache",
    "load_document",
    "check_context_fits",
]
