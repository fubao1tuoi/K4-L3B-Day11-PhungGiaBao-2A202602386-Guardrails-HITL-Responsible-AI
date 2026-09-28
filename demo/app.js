const messages = document.querySelector("#messages");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendBtn");
const clientId = sessionStorage.getItem("vinbank-demo-id") || crypto.randomUUID();
sessionStorage.setItem("vinbank-demo-id", clientId);

function addMessage(text, role, decision = null, layer = null) {
  const row = document.createElement("div");
  row.className = `message ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  if (decision) {
    const badge = document.createElement("span");
    badge.className = `decision ${decision}`;
    badge.textContent = decision === "block" ? `BLOCK · ${layer || "GUARDRAIL"}` : "ALLOW · SAFE";
    bubble.appendChild(badge);
  }
  row.appendChild(bubble);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
  return row;
}

function showTyping() {
  const row = document.createElement("div");
  row.className = "message bot typing";
  row.innerHTML = '<div class="bubble">Đang kiểm tra an toàn <i></i><i></i><i></i></div>';
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
  return row;
}

function updateStats(stats = {}) {
  document.querySelector("#requestsMetric").textContent = stats.requests ?? 0;
  document.querySelector("#blockedMetric").textContent = stats.blocked ?? 0;
  document.querySelector("#rateMetric").textContent = `${stats.block_rate ?? 0}%`;
  document.querySelector("#hitsMetric").textContent = stats.rate_limit_hits ?? 0;
}

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();
    document.querySelector("#modelName").textContent = data.model;
    updateStats(data.stats);
    const pill = document.querySelector(".status-pill");
    if (data.ready) pill.classList.add("ready");
    document.querySelector("#statusText").textContent = data.ready ? "Blue online" : "Thiếu API key";
  } catch {
    document.querySelector("#statusText").textContent = "Server offline";
  }
}

async function submitMessage(message) {
  addMessage(message, "user");
  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;
  const typing = showTyping();
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, user_id: clientId }),
    });
    const data = await response.json();
    typing.remove();
    addMessage(data.reply || data.error || "Không nhận được phản hồi.", "bot", data.blocked ? "block" : "allow", data.layer);
    updateStats(data.stats);
  } catch {
    typing.remove();
    addMessage("Không kết nối được demo server.", "bot", "block", "NETWORK");
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (message) submitMessage(message);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 130)}px`;
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.dataset.prompt;
    input.focus();
  });
});

document.querySelector("#clearBtn").addEventListener("click", () => {
  messages.innerHTML = "";
  addMessage("Hội thoại đã được làm mới. Pipeline bảo vệ vẫn đang hoạt động.", "bot", "allow");
});

loadStatus();
