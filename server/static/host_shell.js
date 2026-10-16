/** 主持人会话、观察视角和游戏挂载共用同一个控制台。 */
let perspectiveSeat = null;
let hostSnapshot = null;
let perspectiveSerial = 0;
let timelineView = "live";
let gameView = null;
let gameViewKey = null;
let gameLoadSerial = 0;
let gameStylesheet = null;
let memoryRenderKey = null;
for (const key of ["arena_admin_token", "ddz_key", "ddz_identity"]) sessionStorage.removeItem(key);

function adminFetch(url, options = {}) {
  return fetch(url, { ...options, credentials: "same-origin" });
}

function renderHostAccess(data) {
  document.getElementById("host-config-path").textContent = data.config_path;
  const text = `当前服务可再加入 ${data.remaining_uses} 次 · 已加入 ${data.used_count} 次`;
  document.getElementById("host-login-uses").textContent = text;
  document.getElementById("host-access-count").textContent = text;
}

function showHostSession(authenticated) {
  document.getElementById("host-login").hidden = authenticated;
  document.getElementById("arena-dashboard").hidden = !authenticated;
  document.getElementById("host-perspective").disabled = !authenticated;
  document.getElementById("btn-settings").hidden = !authenticated;
  if (!authenticated && document.getElementById("controls-panel").matches(":popover-open")) document.getElementById("controls-panel").hidePopover();
  if (!authenticated) document.getElementById("conn-pill").textContent = "等待加入主持人";
}

async function ensureAdminSession() {
  const response = await adminFetch("/api/host/access");
  if (!response.ok) throw new Error("无法读取主持人加入状态");
  const access = await response.json();
  renderHostAccess(access);
  showHostSession(access.authenticated);
  return access.authenticated;
}

async function refreshHostSession() {
  if (await ensureAdminSession()) connectSSE();
}

async function joinHost(event) {
  event.preventDefault();
  const input = document.getElementById("host-password");
  const button = event.target.querySelector('[type="submit"]');
  button.disabled = true;
  try {
    const access = await adminRequest("/api/admin/session", { password: input.value });
    input.value = "";
    renderHostAccess(access);
    showHostSession(true);
    connectSSE();
    document.getElementById("action-notice").hidden = true;
  } catch (error) {
    showNotice(error.message, true);
    await ensureAdminSession();
  } finally {
    button.disabled = false;
  }
}

async function addHostUses() {
  const additional_uses = Number(document.getElementById("host-extra-uses").value);
  if (!Number.isInteger(additional_uses) || additional_uses < 1 || additional_uses > 1000) throw new Error("增加次数应为 1 至 1000 的整数");
  renderHostAccess(await adminRequest("/api/admin/access", { additional_uses }));
  showNotice(`当前服务已增加 ${additional_uses} 次主持人加入机会`);
}

async function receiveHostSnapshot(data) {
  hostSnapshot = data;
  const selector = document.getElementById("host-perspective");
  if (perspectiveSeat !== null && !data.seats?.[perspectiveSeat]) perspectiveSeat = null;
  selector.replaceChildren(new Option("上帝视角", ""), ...Object.values(data.seats || {}).map(seat => new Option(`${seat.seat_id} 号位 · ${seat.name}`, seat.seat_id)));
  selector.value = perspectiveSeat ?? "";
  await refreshPerspective();
}

async function changePerspective() {
  const value = document.getElementById("host-perspective").value;
  perspectiveSeat = value ? Number(value) : null;
  await refreshPerspective();
}

async function refreshPerspective() {
  const serial = ++perspectiveSerial;
  const snapshot = perspectiveSeat === null ? hostSnapshot : await adminRequest(`/api/admin/perspective?seat_id=${perspectiveSeat}`, undefined, "GET");
  if (serial !== perspectiveSerial || !snapshot) return;
  renderSnapshot(snapshot);
}

function showWorkspace() {
  const seat = document.getElementById("workspace-seat").value;
  const input = document.getElementById("workspace-directory");
  input.value = hostSnapshot?.workspace_paths?.[seat] || "";
  delete input.dataset.dirty;
}

async function saveWorkspace(event) {
  event.preventDefault();
  const seat_id = Number(document.getElementById("workspace-seat").value);
  if (!seat_id) throw new Error("请选择席位");
  await adminRequest("/api/admin/workspaces", { seat_id, directory: document.getElementById("workspace-directory").value.trim() });
  showNotice(`${seat_id} 号位记忆目录已登记`);
}

async function operateGame(operation) {
  if (operation === "stop" && !confirm("停止游戏并保留当前记录？")) return;
  await adminRequest(`/api/admin/game/${operation}`, {});
  showNotice({ pause: "游戏已暂停", resume: "游戏已继续", stop: "游戏已停止" }[operation]);
}

function renderHostStage(data) {
  const game = data.game;
  const status = game?.status;
  const labels = { RUNNING: "进行中", PAUSED: "已暂停", FINISHED: "已结束", STOPPED: "已停止" };
  document.getElementById("game-status").textContent = game ? `${game.name} · ${labels[status] || status}` : "尚未加载游戏";
  document.getElementById("game-pause").disabled = status !== "RUNNING";
  document.getElementById("game-resume").disabled = status !== "PAUSED";
  document.getElementById("game-stop").disabled = !["RUNNING", "PAUSED"].includes(status);
  const key = game ? `${game.id}:${game.name}:${game.version}` : null;
  if (key !== gameViewKey) loadGameView(game, key).catch(error => showNotice(error.message, true));
  else if (gameView) {
    try { gameView.update(gamePayload(data)); }
    catch (error) { showNotice(`游戏界面更新失败：${error.message}`, true); }
  }
}

function gamePayload(data) {
  return { state: data.game?.state, status: data.game?.status, perspective: perspectiveSeat, seats: data.seats };
}

async function loadGameView(game, key) {
  const serial = ++gameLoadSerial;
  gameViewKey = key;
  gameView?.destroy?.();
  gameView = null;
  gameEventPresenter = null;
  gameStylesheet?.remove();
  gameStylesheet = null;
  const container = document.getElementById("game-container");
  container.replaceChildren();
  if (!game) return;
  try {
    const { frontend } = await adminRequest("/api/admin/game/frontend", undefined, "GET");
    if (serial !== gameLoadSerial) return;
    if (frontend?.module) {
      const module = await import(frontend.module);
      if (serial !== gameLoadSerial) return;
      gameEventPresenter = typeof module.describeEvent === "function" ? module.describeEvent : null;
      if (frontend.stylesheet) {
        gameStylesheet = document.createElement("link");
        gameStylesheet.rel = "stylesheet";
        gameStylesheet.href = frontend.stylesheet;
        document.head.appendChild(gameStylesheet);
      }
      gameView = module.mount(container, { adminRequest, showNotice });
    } else {
      const pre = document.createElement("pre");
      pre.className = "game-state-json";
      container.appendChild(pre);
      gameView = { update: payload => { pre.textContent = JSON.stringify(payload.state, null, 2); } };
    }
    gameView.update(gamePayload(latestSnapshot));
    renderEventFeed(timelineView === "replay");
  } catch (error) {
    if (serial !== gameLoadSerial) return;
    container.textContent = `游戏界面加载失败：${error.message}`;
    throw error;
  }
}

function renderMemories(memories, seats, statuses = {}, replay = false) {
  const key = JSON.stringify([memories, Object.values(seats || {}).map(seat => [seat.seat_id, seat.name]), statuses, replay ? replayPosition : false, perspectiveSeat, Object.keys(latestSnapshot?.active_actions || {})]);
  if (key === memoryRenderKey) return;
  memoryRenderKey = key;
  document.getElementById("memory-context").textContent = replay ? `回放 · 第 ${replayPosition} 条事件` : "实时";
  const container = document.getElementById("memory-cards");
  const expanded = new Set([...container.querySelectorAll("details[open]")].map(node => node.dataset.memorySeat));
  const ids = perspectiveSeat !== null && !replay ? [String(perspectiveSeat)] : Object.keys(seats || {});
  container.innerHTML = ids.map(sid => {
    const note = memories[sid];
    const status = statuses[sid];
    const active = !replay && latestSnapshot?.active_actions?.[sid];
    const fresh = note && !note.baseline && Date.now() / 1000 - note.observed_at < 30;
    const changes = note?.changes || [];
    const body = changes.map(line => `<div class="memory-line memory-${line.kind}"><span aria-hidden="true">${line.kind === "added" ? "+" : line.kind === "removed" ? "−" : " "}</span><span>${escapeHtml(line.text) || " "}</span></div>`).join("");
    return `<article class="memory-card ${fresh ? "memory-fresh" : ""}"><header><strong>${escapeHtml(sid)} 号 · ${escapeHtml(seats[sid]?.name || "玩家")}</strong>${active ? '<span class="memory-badge">正在行动</span>' : ""}<span class="memory-badge">${note ? note.baseline ? "首次采集" : "最新变更" : "等待笔记"}</span></header>${note ? `<p class="memory-time">${new Date(note.written_at * 1000).toLocaleString()} · 第 ${note.round_num} 回合采集 · 第 ${note.revision} 版</p><div class="memory-diff">${body || '<span class="field-hint">文件为空</span>'}</div><details data-memory-seat="${sid}" ${expanded.has(sid) ? "open" : ""}><summary>当前全文${note.exists ? "" : " · 文件已移除"}</summary><pre>${escapeHtml(note.text)}</pre></details>` : `<p class="field-hint">${status?.path ? "等待 memory.md 写入" : replay ? "此时尚未采集记忆" : "请在右侧登记玩家工作目录"}</p>`}${status?.state === "ERROR" ? `<p class="memory-error">读取暂未成功：${escapeHtml(status.error)}</p>` : ""}</article>`;
  }).join("") || '<p class="field-hint">暂无记忆记录。</p>';
  for (const diff of container.querySelectorAll(".memory-diff")) diff.scrollTop = diff.scrollHeight;
}

function renderReplayMemories() {
  const memories = {};
  for (const event of (replayData?.events || []).slice(0, replayPosition)) {
    if (event.event_type === "MEMORY_UPDATE" && event.from_seat !== null) memories[event.from_seat] = { ...event.data, seq: event.seq, round_num: event.round_num, observed_at: event.timestamp };
  }
  renderMemories(memories, replayData?.seats || {}, {}, true);
}
