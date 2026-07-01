# Frontend Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the minimal static chat UI with a modern, responsive, themeable interface that surfaces the backend's existing capabilities (streaming, history, citations).

**Architecture:** Stay vanilla — three static files plus one new pure-logic file (`static/lib.js`) shared between the browser and Node tests. The pure functions (markdown rendering, citation parsing) are unit-tested with Node's built-in runner; the DOM glue in `script.js` is verified by running the app. No backend changes.

**Tech Stack:** Plain HTML5, CSS custom properties, vanilla ES2020 JavaScript, Node `node:test` for unit tests, GitHub Actions (existing CI) extended with a Node step.

## Global Constraints

- Vanilla only — no bundler, no `node_modules` runtime deps, no CDN. `static/lib.js` must work both as a browser `<script>` (functions become globals) and as a Node CommonJS module (via a `module.exports` guard).
- No backend changes — only `static/*`, `tests/frontend/*`, CI, and README may change. Endpoints used: `POST /ask_stream`, `GET /history/{session_id}`.
- XSS-safe — escape HTML before applying any markdown transform.
- Session id persists in `localStorage` under key `chat_session_id` (unchanged).
- Theme preference persists in `localStorage` under key `chat_theme`; default follows OS `prefers-color-scheme`.
- Citation contract — the model ends grounded answers with a trailing line `Nguồn: <section>`. The no-info reply `Không có thông tin trong nội quy.` has no such line.
- All user-facing copy stays in Vietnamese, matching the existing UI.

---

### Task 1: Pure JS library + unit tests + CI

**Files:**
- Create: `static/lib.js`
- Create: `tests/frontend/lib.test.js`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing.
- Produces (used by Task 3 and Task 4):
  - `escapeHtml(text: string) -> string`
  - `renderMarkdown(text: string) -> string` (returns HTML; escapes first)
  - `parseCitation(text: string) -> { answer: string, source: string | null }`

- [ ] **Step 1: Write the failing tests**

Create `tests/frontend/lib.test.js`:

```js
const test = require("node:test");
const assert = require("node:assert/strict");
const { escapeHtml, renderMarkdown, parseCitation } = require("../../static/lib.js");

test("escapeHtml neutralizes HTML", () => {
  assert.equal(
    escapeHtml('<script>"x"&\'</script>'),
    "&lt;script&gt;&quot;x&quot;&amp;&#39;&lt;/script&gt;"
  );
});

test("renderMarkdown escapes before transforming", () => {
  const html = renderMarkdown("<b>hi</b>");
  assert.ok(html.includes("&lt;b&gt;hi&lt;/b&gt;"));
  assert.ok(!html.includes("<b>hi</b>"));
});

test("renderMarkdown handles bold, italic, and inline code", () => {
  assert.ok(renderMarkdown("**bold**").includes("<strong>bold</strong>"));
  assert.ok(renderMarkdown("*it*").includes("<em>it</em>"));
  assert.ok(renderMarkdown("`code`").includes("<code>code</code>"));
});

test("renderMarkdown builds an unordered list", () => {
  const html = renderMarkdown("- a\n- b");
  assert.ok(html.includes("<ul>"));
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.ok(html.includes("</ul>"));
});

test("renderMarkdown builds an ordered list", () => {
  const html = renderMarkdown("1. a\n2. b");
  assert.ok(html.includes("<ol>"));
  assert.ok(html.includes("</ol>"));
});

test("renderMarkdown renders headings", () => {
  assert.ok(renderMarkdown("## Title").includes("<h2>Title</h2>"));
});

test("parseCitation splits off a trailing Nguồn line", () => {
  const { answer, source } = parseCitation(
    "Giờ làm việc là 8h.\nNguồn: Mục 2. Thời gian làm việc"
  );
  assert.equal(answer, "Giờ làm việc là 8h.");
  assert.equal(source, "Mục 2. Thời gian làm việc");
});

test("parseCitation returns null source when absent", () => {
  const { answer, source } = parseCitation("Không có thông tin trong nội quy.");
  assert.equal(answer, "Không có thông tin trong nội quy.");
  assert.equal(source, null);
});

test("parseCitation ignores trailing blank lines after the source", () => {
  const { source } = parseCitation("Trả lời.\nNguồn: Mục 1\n\n");
  assert.equal(source, "Mục 1");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/frontend/lib.test.js`
Expected: FAIL — `Cannot find module '../../static/lib.js'`.

- [ ] **Step 3: Implement `static/lib.js`**

Create `static/lib.js`:

```js
// Pure, DOM-free helpers shared by the browser UI (script.js) and Node tests.
// In the browser these become globals; under Node they are exported below.

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdown(text) {
  const lines = escapeHtml(text).split("\n");
  const out = [];
  let listType = null; // "ul" | "ol" | null

  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`);
      listType = null;
    }
  };

  const inline = (s) =>
    s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");

  for (const line of lines) {
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    const ulItem = line.match(/^\s*[-*]\s+(.*)$/);
    const olItem = line.match(/^\s*\d+\.\s+(.*)$/);

    if (heading) {
      closeList();
      const level = heading[1].length;
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
    } else if (ulItem) {
      if (listType !== "ul") {
        closeList();
        out.push("<ul>");
        listType = "ul";
      }
      out.push(`<li>${inline(ulItem[1])}</li>`);
    } else if (olItem) {
      if (listType !== "ol") {
        closeList();
        out.push("<ol>");
        listType = "ol";
      }
      out.push(`<li>${inline(olItem[1])}</li>`);
    } else if (line.trim() === "") {
      closeList();
    } else {
      closeList();
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  return out.join("\n");
}

function parseCitation(text) {
  const raw = String(text);
  const lines = raw.split("\n");
  let last = lines.length - 1;
  while (last >= 0 && lines[last].trim() === "") last--;
  if (last >= 0) {
    const match = lines[last].match(/^\s*Nguồn:\s*(.+)$/);
    if (match) {
      return {
        answer: lines.slice(0, last).join("\n").trim(),
        source: match[1].trim(),
      };
    }
  }
  return { answer: raw.trim(), source: null };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { escapeHtml, renderMarkdown, parseCitation };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test tests/frontend/lib.test.js`
Expected: PASS — 9 tests passing.

- [ ] **Step 5: Add a Node test step to CI**

In `.github/workflows/ci.yml`, after the existing `Run tests` step (still inside the `test` job's `steps:` list), append:

```yaml
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Run frontend unit tests
        run: node --test tests/frontend/
```

- [ ] **Step 6: Commit**

```bash
git add static/lib.js tests/frontend/lib.test.js .github/workflows/ci.yml
git commit -m "feat: add tested pure JS lib for markdown + citation parsing"
```

---

### Task 2: HTML shell + CSS redesign

**Files:**
- Modify: `static/index.html` (full rewrite)
- Modify: `static/style.css` (full rewrite)

**Interfaces:**
- Produces (used by Task 3–5) the following element ids/classes:
  - `#chat-box` (message list container)
  - `#user-input` (the `<textarea>` composer)
  - `#send-btn`, `#new-chat-btn`, `#theme-toggle` (buttons in the header)
  - message markup classes: `.message`, `.user`, `.bot`, `.message-body`, `.message-meta`, `.source-chip`, `.copy-btn`, `.typing`
  - theme is driven by `data-theme="dark"` on `<html>`.

- [ ] **Step 1: Rewrite `static/index.html`**

```html
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Chatbot Nội Quy Công Ty</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <div class="app">
    <header class="app-header">
      <h1>Chatbot Nội Quy Công Ty</h1>
      <div class="header-actions">
        <button id="new-chat-btn" type="button" title="Cuộc trò chuyện mới">
          + Mới
        </button>
        <button id="theme-toggle" type="button" title="Đổi giao diện sáng/tối"
                aria-label="Đổi giao diện sáng/tối">🌙</button>
      </div>
    </header>

    <main id="chat-box" class="chat-box" aria-live="polite"></main>

    <footer class="composer">
      <textarea id="user-input" rows="1"
                placeholder="Nhập câu hỏi về nội quy..."></textarea>
      <button id="send-btn" type="button">Gửi</button>
    </footer>
  </div>

  <script src="/static/lib.js"></script>
  <script src="/static/script.js"></script>
</body>
</html>
```

- [ ] **Step 2: Rewrite `static/style.css`**

```css
:root {
  --bg: #f0f2f5;
  --surface: #ffffff;
  --surface-2: #fafafa;
  --border: #e0e0e0;
  --text: #1c1e21;
  --text-muted: #65676b;
  --user-bubble: #dcf8c6;
  --bot-bubble: #e9ebee;
  --accent: #0078ff;
  --accent-hover: #005ecb;
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
}

[data-theme="dark"] {
  --bg: #18191a;
  --surface: #242526;
  --surface-2: #1c1d1e;
  --border: #3a3b3c;
  --text: #e4e6eb;
  --text-muted: #b0b3b8;
  --user-bubble: #2b5278;
  --bot-bubble: #3a3b3c;
  --accent: #2d88ff;
  --accent-hover: #5aa1ff;
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: "Segoe UI", Tahoma, sans-serif;
  background: var(--bg);
  color: var(--text);
  height: 100vh;
}

.app {
  max-width: 760px;
  height: 100vh;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  box-shadow: var(--shadow);
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.app-header h1 {
  font-size: 1.1rem;
  margin: 0;
}

.header-actions { display: flex; gap: 8px; }

.header-actions button {
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 0.9rem;
}

.header-actions button:hover { border-color: var(--accent); }

.chat-box {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--surface-2);
}

.empty-state {
  margin: auto;
  text-align: center;
  color: var(--text-muted);
  max-width: 80%;
}

.message {
  max-width: 80%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.message.user { align-self: flex-end; align-items: flex-end; }
.message.bot { align-self: flex-start; align-items: flex-start; }

.message-body {
  padding: 10px 14px;
  border-radius: 14px;
  white-space: pre-wrap;
  word-wrap: break-word;
  line-height: 1.45;
}

.message.user .message-body { background: var(--user-bubble); }
.message.bot .message-body { background: var(--bot-bubble); }

.message-body p { margin: 0 0 8px; }
.message-body p:last-child { margin-bottom: 0; }
.message-body ul, .message-body ol { margin: 4px 0; padding-left: 20px; }
.message-body code {
  background: rgba(127, 127, 127, 0.25);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.9em;
}

.source-chip {
  font-size: 0.78rem;
  color: var(--text-muted);
  background: rgba(127, 127, 127, 0.12);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px 10px;
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.72rem;
  color: var(--text-muted);
}

.copy-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.72rem;
  padding: 0;
}
.copy-btn:hover { color: var(--accent); }

.typing { display: inline-flex; gap: 4px; padding: 4px 0; }
.typing span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-muted);
  animation: blink 1.2s infinite both;
}
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink {
  0%, 80%, 100% { opacity: 0.3; }
  40% { opacity: 1; }
}

.composer {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}

#user-input {
  flex: 1;
  resize: none;
  max-height: 140px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text);
  font-family: inherit;
  font-size: 1rem;
  line-height: 1.4;
}

#user-input:focus { outline: 2px solid var(--accent); border-color: var(--accent); }

#send-btn {
  align-self: flex-end;
  background: var(--accent);
  color: #fff;
  border: none;
  padding: 10px 18px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1rem;
}
#send-btn:hover { background: var(--accent-hover); }
#send-btn:disabled { opacity: 0.6; cursor: default; }

@media (max-width: 600px) {
  .app { max-width: 100%; }
  .message { max-width: 90%; }
}
```

- [ ] **Step 3: Verify the static shell loads**

Run: `python -m uvicorn app.main:app` (Ollama need not be running for this check), then open `http://127.0.0.1:8000/`.
Expected: full-height app with a header (title, "+ Mới", 🌙), an empty message area, and a composer with a textarea and "Gửi". No console errors. (Sending won't work yet — that's Task 3.)

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/style.css
git commit -m "feat: redesign chat UI shell with themeable layout"
```

---

### Task 3: Core chat — send, stream, render, composer

**Files:**
- Modify: `static/script.js` (full rewrite; this task establishes the file, later tasks extend it)

**Interfaces:**
- Consumes: `renderMarkdown`, `parseCitation` (globals from `lib.js`); ids/classes from Task 2.
- Produces (used by Task 4 and Task 5):
  - `getSessionId() -> string`
  - `setSessionId(id: string) -> void`
  - `appendUserMessage(text: string, timestamp?: string) -> void`
  - `appendBotMessage(rawAnswer: string, timestamp?: string) -> void`
  - `clearChat() -> void`
  - `autoResize() -> void`

- [ ] **Step 1: Write `static/script.js`**

```js
const chatBox = document.getElementById("chat-box");
const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");

const SESSION_KEY = "chat_session_id";

function getSessionId() {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function setSessionId(id) {
  localStorage.setItem(SESSION_KEY, id);
}

let sessionId = getSessionId();

function nowStamp() {
  return new Date().toLocaleString("vi-VN");
}

function scrollToBottom() {
  chatBox.scrollTop = chatBox.scrollHeight;
}

function clearChat() {
  chatBox.innerHTML = "";
}

function autoResize() {
  userInput.style.height = "auto";
  userInput.style.height = Math.min(userInput.scrollHeight, 140) + "px";
}

function appendUserMessage(text, timestamp) {
  const msg = document.createElement("div");
  msg.className = "message user";

  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text;

  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = timestamp || nowStamp();

  msg.append(body, meta);
  chatBox.appendChild(msg);
  scrollToBottom();
}

// Builds an empty bot message with a typing indicator. Returns helpers to
// stream text in and to finalize with markdown + citation + copy + timestamp.
function startBotMessage() {
  const msg = document.createElement("div");
  msg.className = "message bot";

  const body = document.createElement("div");
  body.className = "message-body";
  body.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';

  msg.appendChild(body);
  chatBox.appendChild(msg);
  scrollToBottom();

  let started = false;
  return {
    pushToken(fullText) {
      if (!started) {
        body.innerHTML = "";
        started = true;
      }
      body.textContent = fullText;
      scrollToBottom();
    },
    finalize(rawAnswer, timestamp) {
      const { answer, source } = parseCitation(rawAnswer);
      body.innerHTML = renderMarkdown(answer);

      if (source) {
        const chip = document.createElement("div");
        chip.className = "source-chip";
        chip.textContent = "Nguồn: " + source;
        msg.appendChild(chip);
      }

      const meta = document.createElement("div");
      meta.className = "message-meta";
      const time = document.createElement("span");
      time.textContent = timestamp || nowStamp();
      const copy = document.createElement("button");
      copy.className = "copy-btn";
      copy.type = "button";
      copy.textContent = "Sao chép";
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(answer);
          copy.textContent = "Đã sao chép";
        } catch {
          copy.textContent = "Không sao chép được";
        }
        setTimeout(() => (copy.textContent = "Sao chép"), 1500);
      });
      meta.append(time, copy);
      msg.appendChild(meta);
      scrollToBottom();
    },
    error(message) {
      body.textContent = message;
    },
  };
}

// Renders a fully-known bot answer (used when restoring history in Task 4).
function appendBotMessage(rawAnswer, timestamp) {
  const handle = startBotMessage();
  handle.finalize(rawAnswer, timestamp);
}

async function sendMessage() {
  const question = userInput.value.trim();
  if (!question) return;

  appendUserMessage(question);
  userInput.value = "";
  autoResize();
  sendBtn.disabled = true;

  const bot = startBotMessage();
  try {
    const response = await fetch("/ask_stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: sessionId }),
    });
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let answer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      answer += decoder.decode(value, { stream: true });
      bot.pushToken(answer);
    }

    if (answer.trim()) {
      bot.finalize(answer);
    } else {
      bot.error("Xin lỗi, tôi chưa có câu trả lời phù hợp.");
    }
  } catch (err) {
    console.error(err);
    bot.error("Lỗi kết nối đến server.");
  } finally {
    sendBtn.disabled = false;
    userInput.focus();
  }
}

sendBtn.addEventListener("click", sendMessage);

userInput.addEventListener("input", autoResize);
userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
```

- [ ] **Step 2: Verify streaming, markdown, citation, copy, and composer**

Start Ollama and run `python -m uvicorn app.main:app`; open `http://127.0.0.1:8000/`.
Ask a real question (e.g. "Giờ làm việc là khi nào?"). Expected:
- Typing dots appear, then tokens stream into the bubble.
- On completion, the answer renders (markdown formatting applied), a "Nguồn: …" chip appears below it, plus a timestamp and a "Sao chép" button.
- Clicking "Sao chép" shows "Đã sao chép" briefly and the answer is on the clipboard.
- The textarea grows as you type multiple lines (Shift+Enter), and Enter sends.

- [ ] **Step 3: Commit**

```bash
git add static/script.js
git commit -m "feat: streaming chat with markdown, citations, copy, auto-resize"
```

---

### Task 4: Restore history on reload

**Files:**
- Modify: `static/script.js` (append history-loading logic + welcome state)

**Interfaces:**
- Consumes: `appendUserMessage`, `appendBotMessage`, `clearChat`, `sessionId` (from Task 3).
- Produces: `loadHistory() -> Promise<void>`, `showWelcome() -> void`.

- [ ] **Step 1: Append history + welcome logic to `static/script.js`**

Add at the end of the file (after the existing event listeners):

```js
function showWelcome() {
  const div = document.createElement("div");
  div.className = "empty-state";
  div.textContent = "Xin chào! Hãy đặt câu hỏi về nội quy công ty.";
  chatBox.appendChild(div);
}

async function loadHistory() {
  try {
    const res = await fetch(`/history/${sessionId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const turns = (data && data.history) || [];
    clearChat();
    if (turns.length === 0) {
      showWelcome();
      return;
    }
    for (const turn of turns) {
      appendUserMessage(turn.user, turn.timestamp);
      appendBotMessage(turn.bot, turn.timestamp);
    }
  } catch (err) {
    console.error(err);
    clearChat();
    showWelcome();
  }
}

loadHistory();
```

- [ ] **Step 2: Verify history restore**

With the server running, ask a couple of questions, then refresh the page.
Expected: the prior conversation reappears (user + bot bubbles, citation chips, timestamps from the stored turns). A brand-new session (or after clearing `localStorage`) shows the welcome message instead.

- [ ] **Step 3: Commit**

```bash
git add static/script.js
git commit -m "feat: restore conversation history on page load"
```

---

### Task 5: Header controls — dark mode + new chat

**Files:**
- Modify: `static/script.js` (append theme + new-chat logic)

**Interfaces:**
- Consumes: `clearChat`, `showWelcome`, `setSessionId` (from Tasks 3–4); `#theme-toggle`, `#new-chat-btn` (from Task 2).
- Produces: `applyTheme(theme: string) -> void`.

- [ ] **Step 1: Append theme + new-chat logic to `static/script.js`**

Add at the end of the file:

```js
const THEME_KEY = "chat_theme";
const themeToggle = document.getElementById("theme-toggle");
const newChatBtn = document.getElementById("new-chat-btn");

function applyTheme(theme) {
  if (theme === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
    themeToggle.textContent = "☀️";
  } else {
    document.documentElement.removeAttribute("data-theme");
    themeToggle.textContent = "🌙";
  }
}

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  const prefersDark =
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (prefersDark ? "dark" : "light"));
}

themeToggle.addEventListener("click", () => {
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  const next = isDark ? "light" : "dark";
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
});

newChatBtn.addEventListener("click", () => {
  const id = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
  setSessionId(id);
  sessionId = id;
  clearChat();
  showWelcome();
  userInput.focus();
});

initTheme();
```

- [ ] **Step 2: Verify theme toggle and new chat**

With the server running and the page open:
- Click 🌙/☀️ — the whole UI switches between light and dark; the icon flips; refreshing keeps the chosen theme.
- With no saved theme, the initial theme matches the OS setting.
- Click "+ Mới" — the conversation clears to the welcome state and a new `chat_session_id` is stored (verify in DevTools → Application → Local Storage). The previous session's history is still retrievable by asking again under the old id only if restored, but new questions go to the new session.

- [ ] **Step 3: Commit**

```bash
git add static/script.js
git commit -m "feat: add dark-mode toggle and new-chat button"
```

---

### Task 6: Update README

**Files:**
- Modify: `README.md` (the Features and Web UI description)

**Interfaces:** none.

- [ ] **Step 1: Update the Features list and Web UI mention**

In `README.md`, replace the `- **Web UI** — a simple static front end is served from `/`.` bullet with:

```markdown
- **Modern web UI** — a responsive, vanilla front end served from `/` with
  light/dark themes, streamed answers, markdown rendering, visible source
  citations, conversation history restored on reload, copy-to-clipboard, and a
  "new chat" button. No build step.
```

Then, under `## Running tests`, after the existing pytest block, add:

````markdown
Front-end pure functions (markdown rendering, citation parsing) have their own
Node-based unit tests:

```bash
node --test tests/frontend/
```
````

- [ ] **Step 2: Verify the docs read correctly**

Re-read the changed sections of `README.md`. Expected: the Features list reflects the new UI and the test instructions mention `node --test tests/frontend/`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: describe the new web UI and frontend tests"
```

---

## Self-Review

**Spec coverage:**
- Vanilla / no build → Global Constraints; all tasks. ✓
- No backend changes → Global Constraints. ✓
- Visual redesign (layout, responsive, theming, polish) → Task 2. ✓
- Load history on reload + empty state → Task 4. ✓
- Render markdown (escape first) → Task 1 (logic) + Task 3 (use). ✓
- Dark mode toggle (persist + prefers-color-scheme) → Task 2 (CSS) + Task 5. ✓
- New chat → Task 5. ✓
- Copy-to-clipboard → Task 3. ✓
- Timestamps (history + live) → Task 3 + Task 4. ✓
- Typing indicator → Task 3. ✓
- Auto-resizing input → Task 2 (CSS) + Task 3. ✓
- Source-citation display → Task 1 (parse) + Task 3 (chip). ✓
- Unit tests for markdown + citation parser → Task 1. ✓
- Error handling (stream/history/clipboard) → Task 3 + Task 4. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `getSessionId`/`setSessionId`/`clearChat`/`showWelcome`/`appendUserMessage`/`appendBotMessage`/`autoResize`/`parseCitation`/`renderMarkdown`/`escapeHtml` are defined once and referenced consistently across tasks. The `sessionId` mutable global is declared in Task 3 and reassigned in Tasks 4–5. ✓
