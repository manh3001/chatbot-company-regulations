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

let sessionId = getSessionId();

function setSessionId(id) {
  sessionId = id;
  localStorage.setItem(SESSION_KEY, id);
}

let isStreaming = false;

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
  if (isStreaming) return;

  appendUserMessage(question);
  userInput.value = "";
  autoResize();
  isStreaming = true;
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
    answer += decoder.decode();

    if (answer.trim()) {
      bot.finalize(answer);
    } else {
      bot.error("Xin lỗi, tôi chưa có câu trả lời phù hợp.");
    }
  } catch (err) {
    console.error(err);
    bot.error("Lỗi kết nối đến server.");
  } finally {
    isStreaming = false;
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
