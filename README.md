# Company Regulations Chatbot

A lightweight chatbot that answers questions about a company's internal
regulations, powered by a local large language model (LLM) served through
[Ollama](https://ollama.com/). The whole rules document is fed directly into the
model's context, so answers stay grounded in the source text instead of being
made up.

Built with **FastAPI**, **LangChain**, and **Ollama**. Answers are produced in
Vietnamese, matching the language of the source regulations.

## Features

- **Grounded answers** — the model is instructed to reply only from the supplied
  regulations and to say so when the information is not covered.
- **Source citation** — each answer references the relevant section of the rules.
- **Streaming responses** — token-by-token output via a dedicated endpoint.
- **Answer cache** — repeated questions are served instantly from a JSON cache.
- **Persistent history** — conversations are stored in SQLite and survive
  restarts.
- **Health check** — verifies both the API and the Ollama connection.
- **Web UI** — a simple static front end is served from `/`.

## How it works

Because the regulations document is small, the app skips vector search /
retrieval and loads the **entire document into the model's context** on startup.
This avoids retrieving the wrong passage. A rough token estimate
(`check_context_fits`) warns you if the document risks overflowing the context
window so you can raise `LLM_NUM_CTX` or switch to a retrieval approach.

## Tech stack

| Component        | Purpose                                  |
| ---------------- | ---------------------------------------- |
| FastAPI + Uvicorn | HTTP API and ASGI server                |
| LangChain (`langchain-ollama`, `langchain-core`) | Prompt + LLM orchestration |
| Ollama           | Local LLM runtime (default `qwen2.5:3b`) |
| SQLite           | Persistent conversation history          |
| Pydantic         | Request validation                       |
| python-dotenv    | Environment configuration                |

## Project structure

```
.
├── app/
│   ├── main.py        # FastAPI app and HTTP endpoints
│   ├── rag_chain.py   # LLM setup, prompt, document loading, cache
│   └── storage.py     # SQLite conversation history
├── data/
│   └── company_rules.txt   # Source regulations (edit this)
├── static/            # Web UI (index.html, script.js, style.css)
├── tests/             # pytest suite
├── .env.example       # Configuration template
├── requirements.txt
└── requirements-dev.txt
```

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/) installed and running
- A pulled model (the default is `qwen2.5:3b`, which handles Vietnamese well):

  ```bash
  ollama pull qwen2.5:3b
  ```

## Getting started

```bash
# 1. Clone the repository
git clone https://github.com/manh3001/chatbot-company-regulations.git
cd chatbot-company-regulations

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env        # then edit .env as needed

# 5. Start the Ollama server (in a separate terminal)
ollama serve

# 6. Run the API
uvicorn app.main:app --reload
```

Once running, open <http://127.0.0.1:8000/> for the web UI, or explore the
interactive API docs at <http://127.0.0.1:8000/docs>.

## Configuration

Copy `.env.example` to `.env` and adjust as needed:

| Variable             | Default                  | Description                              |
| -------------------- | ------------------------ | ---------------------------------------- |
| `OLLAMA_MODEL`       | `qwen2.5:3b`             | Ollama model name                        |
| `BASE_URL`           | `http://127.0.0.1:11434` | Ollama server URL                        |
| `LLM_TEMPERATURE`    | `0.1`                    | Sampling temperature                     |
| `LLM_REPEAT_PENALTY` | `1.2`                    | Repetition penalty                       |
| `LLM_NUM_CTX`        | `4096`                   | Context window size (tokens)             |
| `HISTORY_DB`         | `history.db`             | SQLite file for conversation history     |
| `LOG_LEVEL`          | `INFO`                   | Logging level                            |

> `.env` holds local settings only and is git-ignored — never commit it.

## API endpoints

| Method | Path                   | Description                                    |
| ------ | ---------------------- | ---------------------------------------------- |
| `POST` | `/ask`                 | Ask a question, get a single JSON answer       |
| `POST` | `/ask_stream`          | Ask a question, stream the answer as plain text|
| `GET`  | `/history/{session_id}`| Retrieve conversation history for a session    |
| `GET`  | `/health`              | API and Ollama connectivity check              |
| `GET`  | `/`                    | Web UI                                          |

### Example request

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the working hours?"}'
```

```json
{
  "session_id": "…",
  "question": "What are the working hours?",
  "answer": "…",
  "response_time": 1.234,
  "cached": false,
  "timestamp": "2026-06-24 10:00:00"
}
```

The request body accepts an optional `session_id` (auto-generated if omitted) to
group a conversation, and a `stream` flag.

## Updating the regulations

Edit `data/company_rules.txt` with your own content, then restart the server so
the new document is loaded into context.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## License

This project is provided as-is for internal and educational use.
