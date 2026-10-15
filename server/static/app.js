/**
 * 主持人中枢前端逻辑
 * 通过 SSE 获取实时增量事件与座次快照，并向 REST API 发送控制指令。
 */

let eventSource = null;
let currentSeats = {};
let currentPhase = "准备中";
let activeMsgTab = "broadcast";
let latestSnapshot = null;
let flowDraft = [];
let flowDraftRoom = null;
let flowDraftDirty = false;
let editingFlowStep = -1;
let replayHost = null;
let replayData = null;
let replayPosition = 0;
let replayTimer = null;
let replayLoadSerial = 0;
let snapshotReceivedAt = Date.now();
const ADMIN_TOKEN_KEY = "arena_admin_token";
const ACTION_NAMES = { ACT: "通用行动", SPEAK: "发言", VOTE: "投票", CHOOSE: "选择", NUMBER: "数值" };
const SCOPE_NAMES = { PUBLIC: "全员公开", PRIVATE: "指定席位", GROUP: "指定阵营", HOST_ONLY: "仅主持人" };

// 初始化连接
window.addEventListener("DOMContentLoaded", async () => {
  setInterval(updateSeatIndicators, 1000);
  document.addEventListener("input", (event) => {
    if (event.target.matches("input, textarea, select")) event.target.dataset.dirty = "true";
    if (event.target.closest("#flow-step-form")) flowDraftDirty = true;
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
  snapshotReceivedAt = Date.now();
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
  renderFlow(data.flow || {});

  // 渲染全量事件
  const container = document.getElementById("timeline-container");
  container.innerHTML = "";
  if (data.events && data.events.length > 0) {
    data.events.forEach(event => appendEvent(event));
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
      statusText = "待提交行动";
    } else if (s.status === "WAITING") {
      badgeClass = "badge-waiting";
      statusText = "监听等待中";
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
          <div class="connection-status" data-seat-connection="${s.seat_id}"></div>
          <div data-seat-seen="${s.seat_id}"></div>
        </div>
        ${action ? `<div class="pending-action"><strong>${escapeHtml(ACTION_NAMES[action.action_type] || action.action_type)}</strong> · ${escapeHtml(SCOPE_NAMES[action.result_scope] || action.result_scope || "全员公开")}<div>截止 ${new Date(action.deadline * 1000).toLocaleTimeString()}</div><div class="action-countdown" data-action-countdown="${s.seat_id}"></div><button class="btn btn-secondary btn-sm w-100" onclick="cancelAction(${s.seat_id})">取消待办行动</button></div>` : ""}
        <div class="form-row seat-actions"><button class="btn btn-secondary btn-sm flex-1" onclick="editSeat(${s.seat_id})">编辑</button><button class="btn btn-danger btn-sm" onclick="removeSeat(${s.seat_id})">移除</button></div>
        <div style="margin-top: 10px;">
          <button class="btn btn-secondary btn-sm w-100" onclick="copyBootstrapCmd(${s.seat_id})">
            📋 复制 Agent 启动指令
          </button>
        </div>
      </div>
    `;
  }).join("");
  updateSeatIndicators();
}

function updateSeatIndicators() {
  const elapsed = Math.max(0, Math.floor((Date.now() - snapshotReceivedAt) / 1000));
  for (const node of document.querySelectorAll("[data-seat-connection]")) {
    const seat = currentSeats[node.dataset.seatConnection];
    if (!seat) continue;
    const seconds = seat.seconds_since_seen === null || seat.seconds_since_seen === undefined ? null : seat.seconds_since_seen + elapsed;
    const status = seat.connection_status === "RECENT" && seconds > 75 ? "OFFLINE" : seat.connection_status || "NEVER";
    const labels = { NEVER: "未接入", LISTENING: "正在监听服务端", RECENT: "最近有服务请求", OFFLINE: "超过 75 秒未活动" };
    node.textContent = `连接：${labels[status] || status}`;
    node.className = `connection-status connection-${status.toLowerCase()}`;
  }
  for (const node of document.querySelectorAll("[data-seat-seen]")) {
    const seat = currentSeats[node.dataset.seatSeen];
    const seconds = seat?.seconds_since_seen;
    node.textContent = seconds === null || seconds === undefined ? "最近请求：尚无记录" : `最近请求：${seconds + elapsed} 秒前`;
  }
  for (const node of document.querySelectorAll("[data-action-countdown]")) {
    const action = latestSnapshot?.active_actions?.[node.dataset.actionCountdown];
    if (!action) continue;
    const paused = latestSnapshot?.flow?.status === "PAUSED";
    const seconds = Math.ceil(action.deadline - Date.now() / 1000);
    node.textContent = paused ? "流程已暂停，截止时间冻结" : seconds > 0 ? `剩余 ${seconds} 秒` : "已超时，等待服务端处理";
    node.classList.toggle("countdown-expired", !paused && seconds <= 0);
  }
}

function copyBootstrapCmd(seatId) {
  const seat = currentSeats[seatId];
  if (!seat || !seat.claim_token) {
    return alert("该席位没有可用的主持人自举令牌");
  }
  const bootstrapUrl = `${window.location.origin}/bootstrap/${seatId}?claim_token=${encodeURIComponent(seat.claim_token)}`;
  const cmd = `python -c "import urllib.request as u; exec(u.urlopen('${bootstrapUrl}').read().decode('utf-8'))"`;
  navigator.clipboard.writeText(cmd).then(() => {
    alert(`已复制 ${seatId}号位 启动命令！\n\n直接在终端运行，或在聊天中发送给 Agent 执行即可：\n${cmd}\n\n接入后运行 arena watch 持续监听，超时继续等待，断线自动重连。`);
  }).catch(() => {
    prompt("请手动复制启动命令:", cmd);
  });
}

// 更新下拉框
function updateSeatSelects(seats) {
  for (const id of ["select-target-seat", "select-private-seat", "action-recipient", "flow-recipient"]) {
    const select = document.getElementById(id);
    const selected = select.value;
    const options = [new Option("-- 选择座次 --", ""), ...Object.values(seats).map(seat => new Option(`${seat.seat_id}号位 (${seat.name} - ${seat.model || "待连接"})`, seat.seat_id))];
    select.replaceChildren(...options);
    select.value = selected;
  }
  const groups = [...new Set(Object.values(seats).map(seat => seat.group_id).filter(Boolean))].sort();
  for (const id of ["select-message-group", "action-team", "flow-team"]) {
    const groupSelect = document.getElementById(id);
    const selectedGroup = groupSelect.value;
    groupSelect.replaceChildren(new Option("-- 选择阵营 --", ""), ...groups.map(group => new Option(group, group)));
    groupSelect.value = selectedGroup;
  }
  const targets = document.getElementById("flow-targets");
  const selectedTargets = Array.from(targets.selectedOptions, option => option.value);
  targets.replaceChildren(...Object.values(seats).map(seat => new Option(`${seat.seat_id}号位 · ${seat.name}`, seat.seat_id, false, selectedTargets.includes(String(seat.seat_id)))));
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
function appendEvent(ev, targetId = "timeline-container") {
  const container = document.getElementById(targetId);
  
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

  if (targetId === "replay-timeline" || document.getElementById("chk-auto-scroll").checked) {
    container.scrollTop = container.scrollHeight;
  }
}

async function switchTimelineView(view) {
  const replay = view === "replay";
  for (const name of ["live", "replay"]) {
    document.getElementById(`view-${name}`).classList.toggle("active", name === view);
    document.getElementById(`view-${name}`).setAttribute("aria-pressed", String(name === view));
  }
  document.getElementById("timeline-heading").textContent = replay ? "存档复盘" : "实时事件";
  document.getElementById("timeline-filters").hidden = replay;
  document.getElementById("timeline-container").hidden = replay;
  document.getElementById("replay-controls").hidden = !replay;
  document.getElementById("replay-timeline").hidden = !replay;
  if (replay) await refreshArchives();
  else pauseReplay();
}

async function refreshArchives() {
  const data = await adminRequest("/api/admin/archives", undefined, "GET");
  const select = document.getElementById("replay-archive");
  const selected = select.value;
  const archives = data.archives || [];
  const options = archives.map(archive => {
    const date = archive.archived_at ? new Date(archive.archived_at * 1000).toLocaleString() : "";
    const option = new Option(archive.error ? `${archive.title} · 读取失败` : `${archive.title} · ${archive.event_count} 条事件 · ${date}`, archive.room_id);
    option.disabled = Boolean(archive.error);
    return option;
  });
  select.replaceChildren(new Option(archives.length ? "-- 选择对局存档 --" : "-- 暂无存档，请先保存对局 --", ""), ...options);
  if (archives.some(archive => archive.room_id === selected && !archive.error)) select.value = selected;
  const errors = archives.filter(archive => archive.error);
  if (errors.length) showNotice(errors.map(archive => `${archive.title}：${archive.error}`).join("；"), true);
}

async function saveArchive() {
  const saved = await adminRequest("/api/admin/archives", {});
  await refreshArchives();
  document.getElementById("replay-archive").value = saved.room_id;
  await loadReplayArchive();
  showNotice("当前对局已保存，可在复盘中查看");
}

function clearReplay(message) {
  pauseReplay();
  replayData = null;
  replayPosition = 0;
  for (const id of ["replay-perspective", "replay-round", "replay-position", "replay-play", "replay-download"]) document.getElementById(id).disabled = true;
  const container = document.getElementById("replay-timeline");
  container.replaceChildren();
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = message;
  container.appendChild(empty);
  document.getElementById("replay-position-label").textContent = message;
}

async function loadReplayArchive() {
  const roomId = document.getElementById("replay-archive").value;
  const serial = ++replayLoadSerial;
  replayHost = null;
  clearReplay(roomId ? "正在加载对局存档…" : "选择存档开始复盘。");
  if (!roomId) return;
  try {
    const host = await adminRequest(`/api/admin/archives/${encodeURIComponent(roomId)}`, undefined, "GET");
    if (serial !== replayLoadSerial) return;
    replayHost = host;
    const perspectives = document.getElementById("replay-perspective");
    perspectives.replaceChildren(new Option("主持人", ""), ...Object.values(host.seats || {}).map(seat => new Option(`${seat.seat_id} 号位 · ${seat.name}`, seat.seat_id)));
    perspectives.disabled = false;
    await loadReplayPerspective();
  } catch (error) {
    if (serial !== replayLoadSerial) return;
    clearReplay("存档加载失败，请刷新后重试。");
    showNotice(error.message, true);
  }
}

async function loadReplayPerspective() {
  if (!replayHost) return;
  const roomId = document.getElementById("replay-archive").value;
  const seatId = document.getElementById("replay-perspective").value;
  const serial = ++replayLoadSerial;
  clearReplay("正在加载所选视角…");
  document.getElementById("replay-perspective").disabled = false;
  try {
    const data = seatId ? await adminRequest(`/api/admin/archives/${encodeURIComponent(roomId)}?seat_id=${encodeURIComponent(seatId)}`, undefined, "GET") : replayHost;
    if (serial !== replayLoadSerial) return;
    replayData = data;
    const events = data.events || [];
    const rounds = [...new Set(events.map(event => event.round_num))].sort((a, b) => a - b);
    const roundSelect = document.getElementById("replay-round");
    roundSelect.replaceChildren(...rounds.map(round => new Option(`第 ${round} 回合`, round)));
    roundSelect.disabled = !events.length;
    const slider = document.getElementById("replay-position");
    slider.max = events.length;
    slider.disabled = !events.length;
    document.getElementById("replay-play").disabled = !events.length;
    document.getElementById("replay-download").disabled = false;
    seekReplay(events.length ? 1 : 0);
  } catch (error) {
    if (serial !== replayLoadSerial) return;
    clearReplay("该视角加载失败，请重新选择视角。");
    document.getElementById("replay-perspective").disabled = false;
    showNotice(error.message, true);
  }
}

function seekReplay(position) {
  const events = replayData?.events || [];
  replayPosition = Math.max(0, Math.min(events.length, Number(position) || 0));
  document.getElementById("replay-position").value = replayPosition;
  const container = document.getElementById("replay-timeline");
  container.replaceChildren();
  events.slice(0, replayPosition).forEach(event => appendEvent(event, "replay-timeline"));
  const current = events[replayPosition - 1];
  if (current) {
    document.getElementById("replay-round").value = current.round_num;
    document.getElementById("replay-position-label").textContent = `事件 ${replayPosition}/${events.length} · 第 ${current.round_num} 回合 · ${new Date(current.timestamp * 1000).toLocaleString()}`;
  } else {
    container.innerHTML = '<div class="empty-state">此视角在当前位置没有可见事件。</div>';
    document.getElementById("replay-position-label").textContent = events.length ? `事件 0/${events.length} · 对局开始` : "此视角没有可见事件。";
  }
  if (replayPosition >= events.length) pauseReplay();
}

function jumpReplayRound() {
  pauseReplay();
  const round = Number(document.getElementById("replay-round").value);
  const index = (replayData?.events || []).findIndex(event => event.round_num === round);
  if (index >= 0) seekReplay(index + 1);
}

function pauseReplay() {
  if (replayTimer) clearInterval(replayTimer);
  replayTimer = null;
  document.getElementById("replay-play").textContent = "自动播放";
}

function toggleReplayPlayback() {
  if (replayTimer) return pauseReplay();
  const events = replayData?.events || [];
  if (!events.length) return;
  if (replayPosition >= events.length) seekReplay(0);
  document.getElementById("replay-play").textContent = "暂停播放";
  replayTimer = setInterval(() => seekReplay(replayPosition + 1), 1000);
}

function downloadReplay() {
  if (!replayData) return;
  const seatId = document.getElementById("replay-perspective").value;
  downloadJSON(replayData, `arena-${replayData.room_id || "archive"}-${seatId ? `seat-${seatId}` : "host"}.json`);
}

function downloadJSON(data, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
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
  const definition = readActionFields("action");

  await adminRequest("/api/admin/command", {
    command_type: "DISPATCH_ACTION",
    target_seat: parseInt(targetSeat),
    prompt,
    timeout,
    ...definition
  });

  document.getElementById("input-prompt").value = "";
  showNotice(`已向 ${targetSeat} 号席位派发${ACTION_NAMES[definition.action_type]}`);
}

function readActionFields(prefix) {
  const actionType = document.getElementById(`${prefix}-type`).value;
  const scope = document.getElementById(`${prefix}-scope`).value;
  const options = ["VOTE", "CHOOSE"].includes(actionType) ? document.getElementById(`${prefix}-options`).value.split("\n").map(value => value.trim()).filter(Boolean) : [];
  if (["VOTE", "CHOOSE"].includes(actionType) && !options.length) throw new Error("投票或选择需要填写候选项");
  const recipient = document.getElementById(`${prefix}-recipient`).value;
  const group = document.getElementById(`${prefix}-team`).value;
  if (scope === "PRIVATE" && !recipient) throw new Error("请选择结果接收席位");
  if (scope === "GROUP" && !group) throw new Error("请选择结果接收阵营");
  const minValue = actionType === "NUMBER" ? optionalNumber(`${prefix}-min`) : null;
  const maxValue = actionType === "NUMBER" ? optionalNumber(`${prefix}-max`) : null;
  if (minValue !== null && maxValue !== null && minValue > maxValue) throw new Error("最小值不能大于最大值");
  return { action_type: actionType, options, result_scope: scope, result_target_seat: scope === "PRIVATE" ? Number(recipient) : null, result_group_id: scope === "GROUP" ? group : null, min_value: minValue, max_value: maxValue };
}

function optionalNumber(id) {
  const value = document.getElementById(id).value.trim();
  if (!value) return null;
  const number = Number(value);
  if (!Number.isFinite(number)) throw new Error("数值上下界必须是有效数字");
  return number;
}

function updateActionFields(prefix = "action") {
  const type = document.getElementById(`${prefix}-type`).value;
  const scope = document.getElementById(`${prefix}-scope`).value;
  document.getElementById(`${prefix}-options-group`).hidden = !["VOTE", "CHOOSE"].includes(type);
  document.getElementById(`${prefix}-number-group`).hidden = type !== "NUMBER";
  document.getElementById(`${prefix}-recipient-group`).hidden = scope !== "PRIVATE";
  document.getElementById(`${prefix}-team-group`).hidden = scope !== "GROUP";
}

async function cancelAction(seatId) {
  await adminRequest("/api/admin/command", { command_type: "CANCEL_ACTION", target_seat: seatId });
  showNotice(`已取消 ${seatId} 号席位的待办行动`);
}

function renderFlow(flow) {
  const status = flow.status || "IDLE";
  const names = { IDLE: "未启动", RUNNING: "进行中", PAUSED: "已暂停", AWAITING_HOST: "等待主持人裁决", COMPLETED: "已完成" };
  document.getElementById("flow-status").textContent = names[status] || status;
  const pending = flow.pending_seats || [];
  const step = flow.steps?.[flow.index];
  document.getElementById("flow-progress").textContent = step ? `当前第 ${flow.index + 1}/${flow.steps.length} 步：${step.phase}。${pending.length ? `待提交：${pending.join("、")} 号席位` : names[status] || status}` : status === "COMPLETED" ? `全部 ${flow.steps?.length || 0} 步已完成。` : "添加步骤后可预览并启动流程。";
  const active = ["RUNNING", "PAUSED", "AWAITING_HOST"].includes(status);
  document.getElementById("flow-pause").disabled = !["RUNNING", "AWAITING_HOST"].includes(status);
  document.getElementById("flow-resume").disabled = status !== "PAUSED";
  document.getElementById("flow-advance").disabled = status !== "AWAITING_HOST";
  document.getElementById("flow-stop").disabled = !active;
  if (flowDraftRoom !== latestSnapshot?.room_id) {
    flowDraftRoom = latestSnapshot?.room_id;
    flowDraftDirty = false;
    resetFlowEditor();
  }
  if (!flowDraftDirty) flowDraft = structuredClone(flow.steps || []);
  renderFlowSteps();
  document.getElementById("flow-start").disabled = active || !flowDraft.length;
}

function renderFlowSteps() {
  const modeNames = { SEQUENTIAL: "依次行动", SIMULTANEOUS: "同时决策", MANUAL: "主持人裁决" };
  const list = document.getElementById("flow-steps");
  list.innerHTML = flowDraft.map((step, index) => `<li class="flow-step"><strong>${index + 1}. ${escapeHtml(step.phase)}</strong><div class="field-hint">第 ${step.round_num} 回合 · ${modeNames[step.mode] || escapeHtml(step.mode)}${step.mode === "MANUAL" ? "" : ` · ${escapeHtml(ACTION_NAMES[step.action_type] || step.action_type)}<br>席位 ${step.target_seats.join(" → ")} · ${step.timeout} 秒 · ${escapeHtml(SCOPE_NAMES[step.result_scope] || step.result_scope)}`}</div>${step.prompt ? `<div class="flow-prompt">${escapeHtml(step.prompt)}</div>` : ""}<div class="form-row"><button class="btn btn-secondary btn-sm" onclick="editFlowStep(${index})">编辑</button><button class="btn btn-secondary btn-sm" aria-label="步骤 ${index + 1} 上移" onclick="moveFlowStep(${index}, -1)" ${index === 0 ? "disabled" : ""}>上移</button><button class="btn btn-secondary btn-sm" aria-label="步骤 ${index + 1} 下移" onclick="moveFlowStep(${index}, 1)" ${index === flowDraft.length - 1 ? "disabled" : ""}>下移</button><button class="btn btn-danger btn-sm" onclick="removeFlowStep(${index})">删除</button></div></li>`).join("");
  if (!flowDraft.length) list.innerHTML = '<li class="field-hint">尚未添加流程步骤。</li>';
  document.getElementById("flow-start").disabled = !flowDraft.length || ["RUNNING", "PAUSED", "AWAITING_HOST"].includes(latestSnapshot?.flow?.status);
}

function updateFlowFields() {
  document.getElementById("flow-action-fields").hidden = document.getElementById("flow-mode").value === "MANUAL";
  updateActionFields("flow");
}

function resetFlowEditor() {
  editingFlowStep = -1;
  document.getElementById("flow-step-form").reset();
  document.getElementById("flow-editor-heading").textContent = "新增步骤";
  document.getElementById("flow-step-editor").open = false;
  updateFlowFields();
}

function editFlowStep(index) {
  const step = flowDraft[index];
  if (!step) return;
  editingFlowStep = index;
  flowDraftDirty = true;
  const values = { phase: step.phase, round: step.round_num, mode: step.mode, type: step.action_type, scope: step.result_scope, prompt: step.prompt, timeout: step.timeout, options: (step.options || []).join("\n"), recipient: step.result_target_seat ?? "", team: step.result_group_id || "", min: step.min_value ?? "", max: step.max_value ?? "" };
  for (const [id, value] of Object.entries(values)) document.getElementById(`flow-${id}`).value = value;
  for (const option of document.getElementById("flow-targets").options) option.selected = step.target_seats.includes(Number(option.value));
  document.getElementById("flow-editor-heading").textContent = `编辑第 ${index + 1} 步`;
  document.getElementById("flow-step-editor").open = true;
  updateFlowFields();
  document.getElementById("flow-phase").focus();
}

function saveFlowStep(event) {
  event.preventDefault();
  try {
    const mode = document.getElementById("flow-mode").value;
    const targets = mode === "MANUAL" ? [] : Array.from(document.getElementById("flow-targets").selectedOptions, option => Number(option.value));
    if (mode !== "MANUAL" && !targets.length) throw new Error("请选择至少一个参与席位");
    const step = {
      phase: document.getElementById("flow-phase").value.trim(),
      round_num: Number(document.getElementById("flow-round").value),
      mode, target_seats: targets,
      prompt: document.getElementById("flow-prompt").value.trim(),
      timeout: Number(document.getElementById("flow-timeout").value),
      ...(mode === "MANUAL" ? { action_type: "ACT", options: [], result_scope: "PUBLIC" } : readActionFields("flow"))
    };
    if (!step.phase) throw new Error("请填写阶段名称");
    if (!Number.isInteger(step.round_num) || step.round_num < 1) throw new Error("回合必须是正整数");
    if (!Number.isInteger(step.timeout) || step.timeout < 1) throw new Error("行动限时必须是正整数秒");
    if (editingFlowStep < 0) flowDraft.push(step);
    else flowDraft[editingFlowStep] = step;
    flowDraftDirty = true;
    resetFlowEditor();
    renderFlowSteps();
    showNotice("步骤已保存到流程预览");
  } catch (error) {
    showNotice(error.message, true);
  }
}

function moveFlowStep(index, direction) {
  const target = index + direction;
  if (target < 0 || target >= flowDraft.length) return;
  [flowDraft[index], flowDraft[target]] = [flowDraft[target], flowDraft[index]];
  flowDraftDirty = true;
  resetFlowEditor();
  renderFlowSteps();
}

function removeFlowStep(index) {
  flowDraft.splice(index, 1);
  flowDraftDirty = true;
  resetFlowEditor();
  renderFlowSteps();
}

async function startFlow() {
  if (!flowDraft.length) return showNotice("请先添加流程步骤", true);
  await adminRequest("/api/admin/flow", { steps: flowDraft });
  flowDraftDirty = false;
  showNotice(`已启动 ${flowDraft.length} 步回合流程`);
}

async function operateFlow(operation) {
  if (operation === "stop" && !confirm("停止流程并取消本流程未完成的行动？已产生的事件会保留。")) return;
  await adminRequest(`/api/admin/flow/${operation}`, {});
  const messages = { pause: "流程已暂停，已有行动的截止时间已冻结", resume: "流程已继续", advance: "已按主持人裁决推进流程", stop: "流程已停止" };
  showNotice(messages[operation]);
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
    const scenario = await readScenarioDraft();
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
  const scenario = await readScenarioDraft();
  downloadJSON(scenario, "arena-scenario.json");
  showNotice("剧本模板已导出");
}

async function readScenarioDraft() {
  const scenario = await adminRequest("/api/admin/scenario", undefined, "GET");
  scenario.title = document.getElementById("scenario-title").value.trim();
  scenario.description = document.getElementById("scenario-description").value;
  scenario.flow_steps = structuredClone(flowDraft);
  return scenario;
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
