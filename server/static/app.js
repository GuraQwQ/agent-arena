/**
 * 主持人中枢前端逻辑
 * 通过 SSE 获取实时增量事件与座次快照，并向 REST API 发送控制指令。
 */

let eventSource = null;
let currentSeats = {};
let currentPhase = "准备中";
let activeMsgTab = "broadcast";

// 初始化连接
window.addEventListener("DOMContentLoaded", () => {
  connectSSE();
});

function connectSSE() {
  const pill = document.getElementById("conn-pill");
  
  if (eventSource) {
    eventSource.close();
  }

  eventSource = new EventSource("/api/admin/stream");

  eventSource.onopen = () => {
    pill.innerHTML = '<span class="dot"></span> SSE 实时在线';
    pill.style.color = "var(--success)";
  };

  eventSource.onmessage = (e) => {
    try {
      const payload = JSON.parse(e.data);
      if (payload.type === "SNAPSHOT") {
        renderSnapshot(payload.data);
      } else if (payload.type === "EVENT") {
        appendEvent(payload.data);
      }
    } catch (err) {
      console.error("解析 SSE 数据失败:", err, e.data);
    }
  };

  eventSource.onerror = () => {
    pill.innerHTML = '<span class="dot" style="background-color: var(--danger)"></span> 连接重试中...';
    pill.style.color = "var(--danger)";
  };
}

// 渲染快照
function renderSnapshot(data) {
  currentPhase = data.phase || "准备中";
  document.getElementById("current-phase").textContent = currentPhase;
  currentSeats = data.seats || {};

  // 渲染座次卡片
  renderSeatsList(currentSeats);
  // 更新下拉框选项
  updateSeatSelects(currentSeats);

  // 渲染全量事件
  const container = document.getElementById("timeline-container");
  container.innerHTML = "";
  if (data.events && data.events.length > 0) {
    data.events.forEach(appendEvent);
  } else {
    container.innerHTML = '<div class="empty-state">暂无事件记录，请推进阶段或发出指示。</div>';
  }
}

// 渲染座次列表
function renderSeatsList(seats) {
  const listEl = document.getElementById("seats-list");
  const countEl = document.getElementById("seat-count");
  const sids = Object.keys(seats);
  countEl.textContent = sids.length;

  if (sids.length === 0) {
    listEl.innerHTML = '<div class="empty-state">暂无 Agent 入座，等待连接...</div>';
    return;
  }

  listEl.innerHTML = sids.map(sid => {
    const s = seats[sid];
    let badgeClass = "badge-idle";
    let statusText = "空闲";
    if (s.status === "THINKING") {
      badgeClass = "badge-thinking";
      statusText = "思考行动中";
    } else if (s.status === "WAITING") {
      badgeClass = "badge-waiting";
      statusText = "挂起等待中";
    }

    return `
      <div class="seat-card">
        <div class="seat-top">
          <span class="seat-title">${s.seat_id}号位 · ${escapeHtml(s.name)}</span>
          <span class="badge ${badgeClass}">${statusText}</span>
        </div>
        <div class="seat-meta">
          <div>身份: <strong>${escapeHtml(s.role)}</strong></div>
          <div>模型: <code>${escapeHtml(s.model)}</code></div>
          <div>环境: <span>${escapeHtml(s.harness)}</span></div>
        </div>
        <div style="margin-top: 10px;">
          <button class="btn btn-secondary btn-sm w-100" onclick="copyBootstrapCmd(${s.seat_id})">
            📋 复制 Agent 启动指令
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function copyBootstrapCmd(seatId) {
  const cmd = `python -c "import urllib.request as u; exec(u.urlopen('${window.location.origin}/bootstrap/${seatId}').read().decode('utf-8'))"`;
  navigator.clipboard.writeText(cmd).then(() => {
    alert(`已复制 ${seatId}号位 启动命令！\n\n直接在终端运行，或在聊天中发送给 Agent 执行即可：\n${cmd}`);
  }).catch(() => {
    prompt("请手动复制启动命令:", cmd);
  });
}

// 更新下拉框
function updateSeatSelects(seats) {
  const targetSelect = document.getElementById("select-target-seat");
  const privateSelect = document.getElementById("select-private-seat");
  
  const currentTarget = targetSelect.value;
  const currentPrivate = privateSelect.value;

  const optionsHtml = '<option value="">-- 选择目标座次 --</option>' + 
    Object.keys(seats).map(sid => {
      const s = seats[sid];
      return `<option value="${s.seat_id}">${s.seat_id}号位 (${s.name} - ${s.model})</option>`;
    }).join("");

  targetSelect.innerHTML = optionsHtml;
  privateSelect.innerHTML = optionsHtml;

  if (currentTarget) targetSelect.value = currentTarget;
  if (currentPrivate) privateSelect.value = currentPrivate;
}

// 渲染单个事件追加
function appendEvent(ev) {
  const container = document.getElementById("timeline-container");
  
  // 移除空提示
  const empty = container.querySelector(".empty-state");
  if (empty) empty.remove();

  let tagClass = "tag-public";
  let scopeTag = '<span style="color: var(--success)">[全员公开]</span>';
  
  if (ev.scope === "PRIVATE") {
    tagClass = "tag-private";
    scopeTag = `<span style="color: var(--accent)">[私信: ${ev.to_seat}号位]</span>`;
  } else if (ev.event_type === "ACTION_REQUEST" || ev.event_type === "ACTION_SUBMIT") {
    tagClass = "tag-action";
    scopeTag = '<span style="color: var(--warning)">[行动事件]</span>';
  } else if (ev.event_type === "SYSTEM") {
    tagClass = "tag-system";
    scopeTag = '<span style="color: var(--text-muted)">[系统]</span>';
  }

  const timeStr = new Date(ev.timestamp * 1000).toLocaleTimeString();

  let secretHtml = "";
  if (ev.secret_reason) {
    secretHtml = `
      <div class="secret-box">
        <strong>💡 隐藏思考链 / 战术意图 (仅主持人可见):</strong>
        <div>${escapeHtml(ev.secret_reason)}</div>
      </div>
    `;
  }

  const itemEl = document.createElement("div");
  itemEl.className = `event-item ${tagClass}`;
  itemEl.innerHTML = `
    <div class="event-header">
      <div class="event-title">
        ${scopeTag}
        <span>${escapeHtml(ev.title)}</span>
      </div>
      <div class="event-time">#${ev.seq} ${timeStr}</div>
    </div>
    <div class="event-body">${escapeHtml(ev.content)}</div>
    ${secretHtml}
  `;

  container.appendChild(itemEl);

  if (document.getElementById("chk-auto-scroll").checked) {
    container.scrollTop = container.scrollHeight;
  }
}

// API 指令交互
async function advancePhase() {
  const phase = document.getElementById("input-phase").value.trim();
  if (!phase) return alert("阶段名不能为空");
  
  await fetch("/api/admin/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      command_type: "ADVANCE_PHASE",
      phase: phase
    })
  });
}

async function dispatchAction() {
  const targetSeat = document.getElementById("select-target-seat").value;
  if (!targetSeat) return alert("请先选择目标座次");
  
  const prompt = document.getElementById("input-prompt").value.trim();
  const timeout = parseInt(document.getElementById("input-timeout").value) || 60;

  await fetch("/api/admin/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      command_type: "DISPATCH_ACTION",
      target_seat: parseInt(targetSeat),
      prompt: prompt,
      timeout: timeout
    })
  });

  document.getElementById("input-prompt").value = "";
}

function switchMsgTab(tab) {
  activeMsgTab = tab;
  document.getElementById("tab-broadcast").classList.toggle("active", tab === "broadcast");
  document.getElementById("tab-private").classList.toggle("active", tab === "private");
  document.getElementById("group-private-seat").style.display = tab === "private" ? "block" : "none";
}

async function sendMessage() {
  const content = document.getElementById("input-msg-content").value.trim();
  if (!content) return alert("消息内容不能为空");

  if (activeMsgTab === "broadcast") {
    await fetch("/api/admin/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command_type: "BROADCAST",
        content: content
      })
    });
  } else {
    const seat = document.getElementById("select-private-seat").value;
    if (!seat) return alert("请选择私信接收人");
    await fetch("/api/admin/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command_type: "SEND_PRIVATE",
        target_seat: parseInt(seat),
        content: content
      })
    });
  }

  document.getElementById("input-msg-content").value = "";
}

async function resetRoom() {
  if (!confirm("确定要重置当前竞技场房间吗？所有座次和记录将被清空。")) return;
  await fetch("/api/admin/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command_type: "RESET" })
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
