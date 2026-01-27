#  Chatbot Nội Quy Công Ty (RAG + Ollama + LangChain + FastAPI)

##  Mục tiêu
Dự án xây dựng chatbot thông minh giúp trả lời câu hỏi về **nội quy công ty** dựa trên mô hình ngôn ngữ lớn (LLM).

##  Công nghệ
- FastAPI (triển khai API)
- LangChain (RAG pipeline)
- ChromaDB (vector database)
- HuggingFace Embeddings
- Ollama (LLM LLaMA3 hoặc phi3)
- Python dotenv, pydantic

##  Cách chạy
```bash
# 1. Clone dự án
git clone 
cd chatbot_noiquy

# 2. Tạo môi trường ảo
python -m venv .venv
* Kích hoạt
.venv\Scripts\activate
* Khởi động lại
deactivate
.\.venv\Scripts\activate


pip install -r requirements.txt

# 3. Chạy Ollama server
ollama serve

# 4. Khởi động API
uvicorn app.main:app --reload
