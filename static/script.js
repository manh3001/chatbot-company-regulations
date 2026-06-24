const chatBox = document.getElementById("chat-box");
const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");

// Một session_id ổn định cho mỗi tab để giữ lịch sử hội thoại phía server.
const sessionId =
  localStorage.getItem("chat_session_id") ||
  (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
localStorage.setItem("chat_session_id", sessionId);

function appendMessage(sender, text) {
  const msg = document.createElement("div");
  msg.classList.add("message", sender);
  msg.textContent = text;
  chatBox.appendChild(msg);
  chatBox.scrollTop = chatBox.scrollHeight;
  return msg;
}

async function sendMessage() {
  const question = userInput.value.trim();
  if (!question) return;

  appendMessage("user", question);
  userInput.value = "";

  sendBtn.disabled = true;
  const botMsg = appendMessage("bot", "…");

  try {
    const response = await fetch("/ask_stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: sessionId }),
    });

    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`);
    }

    // Đọc token streaming và hiển thị dần.
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let answer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      answer += decoder.decode(value, { stream: true });
      botMsg.textContent = answer;
      chatBox.scrollTop = chatBox.scrollHeight;
    }

    if (!answer.trim()) {
      botMsg.textContent = "Xin lỗi, tôi chưa có câu trả lời phù hợp.";
    }
  } catch (err) {
    console.error(err);
    botMsg.textContent = "Lỗi kết nối đến server.";
  } finally {
    sendBtn.disabled = false;
    userInput.focus();
  }
}

sendBtn.addEventListener("click", sendMessage);

userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
