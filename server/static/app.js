/**
 * 主持人中枢前端逻辑
 * 通过 SSE 获取实时增量事件与座次快照，并向 REST API 发送控制指令。
 */

let eventSource = null;
let currentSeats = {};
let currentPhase = "准备中";
let activeMsgTab = "broadcast";
let latestSnapshot = null;
const ADMIN_TOKEN_KEY = "arena_admin_token";
const ACTION_NAMES = { ACT: "通用行动", SPEAK: "发言", VOTE: "投票", CHOOSE: "选择", NUMBER: "数值" };
const SCOPE_NAMES = { PUBLIC: "全员公开", PRIVATE: "指定席位", GROUP: "指定阵营", HOST_ONLY: "仅主持人" };

// 初始化连接
window.addEventListener("DOMContentLoaded", async () => {
  document.addEventListener("input", (event) => {
    if (event.target.matches("input, textarea, select")) event.target.dataset.dirty = "true";
  });
  try {
    if (await ensureAdminSession()) {
      connectSSE();
    } else {
      document.getElementById("conn-pill").textContent = "等待主持人令牌";
    }
  } catch (error) {
    showNotice(error.message, true);
  }
});

window.addEventListener("unhandledrejection", (event) => {
  showNotice(event.reason?.message || "请求失败，请重试", true);
  event.preventDefault();
});

async function ensureAdminSession() {
  let token = sessionStorage.getItem(ADMIN_TOKEN_KEY);
  if (!token) {
    token = window.prompt("请输入服务端启动日志中的主持人管理令牌:");
  }
  if (!token) return false;

  const res = await fetch("/api/admin/session", {
    method: "POST",
    headers: { "X-Admin-Token": token }
  });
  if (!res.ok) {
    sessionStorage.removeItem(ADMIN_TOKEN_KEY);
    alert("主持人管理令牌无效");
    return false;
  }
  sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
  return true;
}

function adminFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = sessionStorage.getItem(ADMIN_TOKEN_KEY);
  if (token) headers.set("X-Admin-Token", token);
  return fetch(url, { ...options, headers });
}

async function adminRequest(url, body, method = "POST") {
  const response = await adminFetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) })
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `请求失败 (${response.status})`);
  }
  return data;
}

function showNotice(message, isError = false) {
  const notice = document.getElementById("action-notice");
  notice.textContent = message;
  notice.classList.toggle("notice-error", isError);
  notice.hidden = false;
}

function syncInput(id, value, checkbox = false) {
  const input = document.getElementById(id);
  if (input.dataset.dirty || document.activeElement === input) return;
  input[checkbox ? "checked" : "value"] = value;
}

function clearDirty(ids) {
  ids.forEach(id => delete document.getElementById(id).dataset.dirty);
}

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
  latestSnapshot = data;
  currentPhase = data.phase || "准备中";
  document.getElementById("current-phase").textContent = currentPhase;
  syncInput("input-round", data.round_num || 1);
  syncInput("scenario-title", data.room_title || "竞技场剧本");
  syncInput("scenario-description", data.scenario_description || "");
  currentSeats = data.seats || {};
  renderSettings(data.settings || {});

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
    const action = latestSnapshot?.active_actions?.[sid];
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
          <div>阵营: <strong>${escapeHtml(s.group_id || "未分组")}</strong></div>
          <div>模型: <code>${escapeHtml(s.model)}</code></div>
          <div>环境: <span>${escapeHtml(s.harness)}</span></div>
        </div>
        ${action ? `<div class="pending-action"><strong>${escapeHtml(ACTION_NAMES[action.action_type] || action.action_type)}</strong> · ${escapeHtml(SCOPE_NAMES[action.result_scope] || action.result_scope || "全员公开")}<div>截止 ${new Date(action.deadline * 1000).toLocaleTimeString()}</div><button class="btn btn-secondary btn-sm w-100" onclick="cancelAction(${s.seat_id})">取消待办行动</button></div>` : ""}
        <div class="form-row seat-actions"><button class="btn btn-secondary btn-sm flex-1" onclick="editSeat(${s.seat_id})">编辑</button><button class="btn btn-danger btn-sm" onclick="removeSeat(${s.seat_id})">移除</button></div>
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
  const seat = currentSeats[seatId];
  if (!seat || !seat.claim_token) {
    return alert("该席位没有可用的主持人自举令牌");
  }
  const bootstrapUrl = `${window.location.origin}/bootstrap/${seatId}?claim_token=${encodeURIComponent(seat.claim_token)}`;
  const cmd = `python -c "import urllib.request as u; exec(u.urlopen('${bootstrapUrl}').read().decode('utf-8'))"`;
  navigator.clipboard.writeText(cmd).then(() => {
    alert(`已复制 ${seatId}号位 启动命令！\n\n直接在终端运行，或在聊天中发送给 Agent 执行即可：\n${cmd}`);
  }).catch(() => {
    prompt("请手动复制启动命令:", cmd);
  });
}

// 更新下拉框
function updateSeatSelects(seats) {
  for (const id of ["select-target-seat", "select-private-seat", "action-recipient"]) {
    const select = document.getElementById(id);
    const selected = select.value;
    const options = [new Option("-- 选择座次 --", ""), ...Object.values(seats).map(seat => new Option(`${seat.seat_id}号位 (${seat.name} - ${seat.model || "待连接"})`, seat.seat_id))];
    select.replaceChildren(...options);
    select.value = selected;
  }
  const groups = [...new Set(Object.values(seats).map(seat => seat.group_id).filter(Boolean))].sort();
  for (const id of ["select-message-group", "action-team"]) {
    const groupSelect = document.getElementById(id);
    const selectedGroup = groupSelect.value;
    groupSelect.replaceChildren(new Option("-- 选择阵营 --", ""), ...groups.map(group => new Option(group, group)));
    groupSelect.value = selectedGroup;
  }
}

function renderSettings(settings) {
  syncInput("setting-free-actions", Boolean(settings.allow_free_actions), true);
  syncInput("setting-history-rounds", settings.history_rounds ?? "");
  syncInput("setting-history-seconds", settings.history_seconds ?? "");
}

function nullablePositiveInt(id) {
  const value = document.getElementById(id).value.trim();
  if (!value) return null;
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1) {
    throw new Error("窗口设置必须是正整数，留空表示不过期");
  }
  return number;
}

async function saveSettings() {
  try {
    const res = await adminFetch("/api/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        allow_free_actions: document.getElementById("setting-free-actions").checked,
        history_rounds: nullablePositiveInt("setting-history-rounds"),
        history_seconds: nullablePositiveInt("setting-history-seconds")
      })
    });
    if (!res.ok) throw new Error((await res.text()) || "保存设置失败");
    clearDirty(["setting-free-actions", "setting-history-rounds", "setting-history-seconds"]);
    showNotice("房间设置已保存");
  } catch (err) {
    alert(err.message || "保存设置失败");
  }
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
  } else if (ev.scope === "GROUP") {
    tagClass = "tag-private";
    scopeTag = `<span style="color: var(--accent)">[阵营: ${escapeHtml(ev.group_id)}]</span>`;
  } else if (ev.scope === "HOST_ONLY") {
    tagClass = "tag-private";
    scopeTag = '<span style="color: var(--purple)">[仅主持人]</span>';
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
        <strong>战术意图 (仅主持人可见):</strong>
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
    ${ev.data && (Object.hasOwn(ev.data, "choice") || Object.hasOwn(ev.data, "value")) ? `<div class="result-data">${Object.hasOwn(ev.data, "choice") ? `选择：${escapeHtml(ev.data.choice)}` : `数值：${escapeHtml(String(ev.data.value))}`}</div>` : ""}
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
  
  await adminRequest("/api/admin/command", {
    command_type: "ADVANCE_PHASE",
    phase,
    round_num: parseInt(document.getElementById("input-round").value) || 1
  });
  clearDirty(["input-round"]);
  showNotice(`已切换到 ${phase}`);
}

async function dispatchAction() {
  const targetSeat = document.getElementById("select-target-seat").value;
  if (!targetSeat) return alert("请先选择目标座次");
  
  const prompt = document.getElementById("input-prompt").value.trim();
  const timeout = parseInt(document.getElementById("input-timeout").value) || 60;
  const actionType = document.getElementById("action-type").value;
  const scope = document.getElementById("action-scope").value;
  const options = ["VOTE", "CHOOSE"].includes(actionType) ? document.getElementById("action-options").value.split("\n").map(value => value.trim()).filter(Boolean) : [];
  if (["VOTE", "CHOOSE"].includes(actionType) && options.length < 2) return showNotice("投票或选择需要至少两个候选项", true);
  const recipient = document.getElementById("action-recipient").value;
  const group = document.getElementById("action-team").value;
  if (scope === "PRIVATE" && !recipient) return showNotice("请选择结果接收席位", true);
  if (scope === "GROUP" && !group) return showNotice("请选择结果接收阵营", true);
  const minValue = actionType === "NUMBER" ? optionalNumber("action-min") : null;
  const maxValue = actionType === "NUMBER" ? optionalNumber("action-max") : null;
  if (minValue !== null && maxValue !== null && minValue > maxValue) return showNotice("最小值不能大于最大值", true);

  await adminRequest("/api/admin/command", {
    command_type: "DISPATCH_ACTION",
    target_seat: parseInt(targetSeat),
    prompt,
    timeout,
    action_type: actionType,
    options,
    result_scope: scope,
    result_target_seat: scope === "PRIVATE" ? Number(recipient) : null,
    result_group_id: scope === "GROUP" ? group : null,
    min_value: minValue,
    max_value: maxValue
  });

  document.getElementById("input-prompt").value = "";
  showNotice(`已向 ${targetSeat} 号席位派发${ACTION_NAMES[actionType]}`);
}

function optionalNumber(id) {
  const value = document.getElementById(id).value.trim();
  if (!value) return null;
  const number = Number(value);
  if (!Number.isFinite(number)) throw new Error("数值上下界必须是有效数字");
  return number;
}

function updateActionFields() {
  const type = document.getElementById("action-type").value;
  const scope = document.getElementById("action-scope").value;
  document.getElementById("action-options-group").hidden = !["VOTE", "CHOOSE"].includes(type);
  document.getElementById("action-number-group").hidden = type !== "NUMBER";
  document.getElementById("action-recipient-group").hidden = scope !== "PRIVATE";
  document.getElementById("action-team-group").hidden = scope !== "GROUP";
}

async function cancelAction(seatId) {
  await adminRequest("/api/admin/command", { command_type: "CANCEL_ACTION", target_seat: seatId });
  showNotice(`已取消 ${seatId} 号席位的待办行动`);
}

function switchMsgTab(tab) {
  activeMsgTab = tab;
  for (const name of ["broadcast", "private", "group"]) {
    document.getElementById(`tab-${name}`).classList.toggle("active", tab === name);
    document.getElementById(`tab-${name}`).setAttribute("aria-pressed", String(tab === name));
  }
  document.getElementById("group-private-seat").style.display = tab === "private" ? "block" : "none";
  document.getElementById("group-message-target").hidden = tab !== "group";
}

async function sendMessage() {
  const content = document.getElementById("input-msg-content").value.trim();
  if (!content) return alert("消息内容不能为空");

  const command = { command_type: "BROADCAST", content };
  if (activeMsgTab === "private") {
    const seat = document.getElementById("select-private-seat").value;
    if (!seat) return alert("请选择私信接收人");
    command.command_type = "SEND_PRIVATE";
    command.target_seat = Number(seat);
  } else if (activeMsgTab === "group") {
    const group = document.getElementById("select-message-group").value;
    if (!group) return alert("请先为席位配置阵营，再选择接收阵营");
    command.command_type = "SEND_GROUP";
    command.group_id = group;
  }
  await adminRequest("/api/admin/command", command);
  document.getElementById("input-msg-content").value = "";
  showNotice("消息已发送");
}

async function resetRoom() {
  if (!confirm("确定开启新局吗？当前对局将归档，席位令牌将重新生成。")) return;
  await adminRequest("/api/admin/command", { command_type: "RESET" });
  showNotice("已归档当前对局并开启新局");
}

function newSeat() {
  if (Object.keys(currentSeats).length >= 64) return showNotice("每个剧本最多可配置 64 个席位", true);
  const id = Array.from({ length: 64 }, (_, index) => index + 1).find(value => !currentSeats[value]);
  editSeat(id);
}

function editSeat(id) {
  const seat = currentSeats[id] || { seat_id: id };
  for (const [field, value] of Object.entries({ "seat-id": seat.seat_id, "seat-name": seat.name || "", "seat-role": seat.role || "", "seat-group": seat.group_id || "", "seat-prompt": seat.init_prompt || "" })) {
    document.getElementById(field).value = value;
  }
  document.getElementById("seat-id").readOnly = Boolean(currentSeats[id]);
  const editor = document.getElementById("seat-editor");
  editor.open = true;
  editor.scrollIntoView({ block: "nearest" });
  document.getElementById("seat-name").focus();
}

function closeSeatEditor() {
  document.getElementById("seat-editor").open = false;
}

async function saveSeat(event) {
  event.preventDefault();
  const fields = document.getElementById("seat-fields");
  fields.disabled = true;
  try {
    await adminRequest("/api/admin/seats", {
      seat_id: Number(document.getElementById("seat-id").value),
      name: document.getElementById("seat-name").value.trim(),
      role: document.getElementById("seat-role").value.trim(),
      group_id: document.getElementById("seat-group").value.trim() || null,
      init_prompt: document.getElementById("seat-prompt").value
    });
    closeSeatEditor();
    showNotice("席位配置已保存");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    fields.disabled = false;
  }
}

async function removeSeat(id) {
  if (!confirm(`确定移除 ${id} 号席位吗？该席位的连接凭据将失效，已有事件会保留。`)) return;
  await adminRequest(`/api/admin/seats/${id}`, undefined, "DELETE");
  if (Number(document.getElementById("seat-id").value) === id) closeSeatEditor();
  showNotice(`已移除 ${id} 号席位`);
}

async function applyScenario(event) {
  event.preventDefault();
  if (!confirm("应用剧本并开启新局？当前对局将归档，Agent 需要使用新的启动指令连接。")) return;
  const fields = document.getElementById("scenario-fields");
  fields.disabled = true;
  try {
    const scenario = await adminRequest("/api/admin/scenario", undefined, "GET");
    scenario.title = document.getElementById("scenario-title").value.trim();
    scenario.description = document.getElementById("scenario-description").value;
    await adminRequest("/api/admin/scenario", scenario);
    clearDirty(["scenario-title", "scenario-description", "input-round"]);
    showNotice("剧本已应用，新局已开启");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    fields.disabled = false;
  }
}

async function exportScenario() {
  const scenario = await adminRequest("/api/admin/scenario", undefined, "GET");
  const url = URL.createObjectURL(new Blob([JSON.stringify(scenario, null, 2)], { type: "application/json;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "arena-scenario.json";
  link.click();
  URL.revokeObjectURL(url);
  showNotice("剧本模板已导出");
}

async function importScenario(event) {
  const file = event.target.files[0];
  if (!file) return;
  const fields = document.getElementById("scenario-fields");
  try {
    const scenario = JSON.parse(await file.text());
    if (!scenario || typeof scenario.title !== "string" || !Array.isArray(scenario.seats)) throw new Error("模板需要包含 title 标题和 seats 席位列表");
    if (!confirm(`导入「${scenario.title}」并开启新局？当前对局将归档。`)) return;
    fields.disabled = true;
    await adminRequest("/api/admin/scenario", scenario);
    clearDirty(["scenario-title", "scenario-description", "input-round"]);
    syncInput("scenario-title", scenario.title);
    syncInput("scenario-description", scenario.description || "");
    showNotice("剧本模板已导入，新局已开启");
  } catch (error) {
    showNotice(error instanceof SyntaxError ? "模板不是有效的 JSON 文件" : error.message, true);
  } finally {
    fields.disabled = false;
    event.target.value = "";
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
