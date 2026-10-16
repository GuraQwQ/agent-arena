/** 事件的阅读摘要与浏览器显示偏好，实时和回放共用。 */
const EVENT_CATEGORIES = { results: "结果与进程", messages: "消息与发言", memory: "记忆写入", requests: "行动指令", submissions: "原始提交", system: "系统记录" };
const DISPLAY_KEY = "arena_display_preferences";
const DEFAULT_DISPLAY = { categories: ["results", "messages"], scopes: ["PUBLIC", "PRIVATE", "GROUP", "HOST_ONLY"], seat: "", query: "", autoScroll: true, showMemories: true, compact: false, theme: "light", fontSize: "normal", highContrast: false, reduceMotion: false };
let displayPreferences = readDisplayPreferences();
let gameEventPresenter = null;

function readDisplayPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem(DISPLAY_KEY));
    if (!saved || typeof saved !== "object") return structuredClone(DEFAULT_DISPLAY);
    return {
      categories: Array.isArray(saved.categories) ? saved.categories.filter(value => Object.hasOwn(EVENT_CATEGORIES, value)) : [...DEFAULT_DISPLAY.categories],
      scopes: Array.isArray(saved.scopes) ? saved.scopes.filter(value => DEFAULT_DISPLAY.scopes.includes(value)) : [...DEFAULT_DISPLAY.scopes],
      seat: typeof saved.seat === "string" ? saved.seat : "",
      query: typeof saved.query === "string" ? saved.query : "",
      autoScroll: saved.autoScroll !== false, showMemories: saved.showMemories !== false, compact: saved.compact === true,
      theme: ["light", "dark", "system"].includes(saved.theme) ? saved.theme : "light",
      fontSize: ["small", "normal", "large"].includes(saved.fontSize) ? saved.fontSize : "normal",
      highContrast: saved.highContrast === true, reduceMotion: saved.reduceMotion === true
    };
  } catch (_) { return structuredClone(DEFAULT_DISPLAY); }
}

function eventCategory(event) {
  if (event.event_type === "ACTION_REQUEST") return "requests";
  if (event.event_type === "ACTION_SUBMIT") return "submissions";
  if (event.event_type === "MEMORY_UPDATE") return "memory";
  if (["ANNOUNCEMENT", "PRIVATE_MESSAGE", "GROUP_MESSAGE"].includes(event.event_type)) return "messages";
  if (["GAME_EVENT", "GAME_START", "GAME_CONTROL", "PHASE_CHANGE", "FLOW_CONTROL", "FLOW_REVEAL", "ACTION_CANCEL", "ACTION_RESULT"].includes(event.event_type)) return "results";
  return "system";
}

function eventSeatIds(event) {
  return [...new Set([event.from_seat, event.to_seat, event.data?.seat, event.data?.seat_id, ...(event.recipient_seats || [])].filter(value => value !== null && value !== undefined).map(String))];
}

function eventMatches(event, preferences = displayPreferences) {
  if (!preferences.categories.includes(eventCategory(event)) || !preferences.scopes.includes(event.scope)) return false;
  if (preferences.seat && !eventSeatIds(event).includes(preferences.seat)) return false;
  const query = preferences.query.trim().toLocaleLowerCase();
  return !query || [event.title, event.content, event.secret_reason, JSON.stringify(event.data || {})].join("\n").toLocaleLowerCase().includes(query);
}

function splitEventContent(content) {
  const text = String(content || "").trim();
  const starts = [0, ...Array.from(text.matchAll(/\n(?=\s*[\[{])/g), match => match.index + 1)];
  for (const start of starts) {
    try {
      const data = JSON.parse(text.slice(start));
      if (data !== null && typeof data === "object") return { text: text.slice(0, start).trim(), data };
    } catch (_) { /* 普通正文保持原样，只有完整 JSON 后缀进入详情。 */ }
  }
  return { text, data: null };
}

function describeEvent(event) {
  const parsed = splitEventContent(event.content);
  const data = event.data || {};
  let title = String(event.title || event.event_type).replace(/【([^】]+)】/g, "$1 ").trim();
  let text = parsed.text;
  if (event.event_type === "ACTION_REQUEST") {
    title = `等待 ${event.to_seat} 号位行动`;
    text = `已派发${ACTION_NAMES[data.action_type] || data.action_type || "行动"}指令`;
  } else if (event.event_type === "ACTION_SUBMIT") {
    title = `${event.from_seat} 号位提交${ACTION_NAMES[data.action_type] || "行动"}`;
    if (!text) text = Object.hasOwn(data, "choice") ? `选择 ${data.choice}` : Object.hasOwn(data, "value") ? `提交数值 ${data.value}` : "已提交，查看详情了解原始内容";
  } else if (event.event_type === "MEMORY_UPDATE") {
    title = `${event.from_seat} 号位${data.baseline ? "的笔记快照" : "更新了笔记"}`;
    const added = (data.changes || []).filter(line => line.kind === "added").map(line => line.text);
    const lines = (added.length ? added : String(data.text || "").split("\n")).filter(line => line.trim() && !/^#{1,6}\s/.test(line));
    text = lines.slice(-3).join("\n") || (data.exists === false ? "记忆文件已移除" : "笔记为空");
  }
  if (gameEventPresenter) {
    try {
      const custom = gameEventPresenter(event, parsed);
      if (custom) { title = custom.title || title; text = custom.text ?? text; }
    } catch (error) { console.warn("游戏事件摘要未生成", error); }
  }
  return { title, text, parsed };
}

function initDisplaySettings() {
  document.getElementById("display-categories").innerHTML = Object.entries(EVENT_CATEGORIES).map(([key, label]) => `<label class="check-option"><input type="checkbox" name="event-category" value="${key}" onchange="changeDisplaySettings()">${label}</label>`).join("");
  syncDisplaySettings();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyAppearance);
}

function applyAppearance() {
  document.body.dataset.theme = displayPreferences.theme === "system" ? matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light" : displayPreferences.theme;
  document.body.dataset.fontSize = displayPreferences.fontSize;
  document.body.classList.toggle("high-contrast", displayPreferences.highContrast);
  document.body.classList.toggle("reduce-motion", displayPreferences.reduceMotion);
}

function syncDisplaySettings() {
  for (const input of document.querySelectorAll('[name="event-category"]')) input.checked = displayPreferences.categories.includes(input.value);
  for (const input of document.querySelectorAll('[name="event-scope"]')) input.checked = displayPreferences.scopes.includes(input.value);
  for (const [id, key] of [["chk-auto-scroll", "autoScroll"], ["display-memories", "showMemories"], ["display-compact", "compact"]]) document.getElementById(id).checked = displayPreferences[key];
  document.getElementById("event-search").value = displayPreferences.query;
  const categories = [...displayPreferences.categories].sort().join();
  document.getElementById("event-preset").value = categories === [...DEFAULT_DISPLAY.categories].sort().join() ? "focus" : categories === Object.keys(EVENT_CATEGORIES).sort().join() ? "all" : "custom";
  document.getElementById("arena-dashboard").classList.toggle("memories-hidden", !displayPreferences.showMemories);
  document.getElementById("memory-rail").hidden = !displayPreferences.showMemories;
  document.body.classList.toggle("feed-compact", displayPreferences.compact);
  for (const [id, key] of [["display-theme", "theme"], ["display-font-size", "fontSize"]]) document.getElementById(id).value = displayPreferences[key];
  document.getElementById("display-contrast").checked = displayPreferences.highContrast;
  document.getElementById("display-reduce-motion").checked = displayPreferences.reduceMotion;
  applyAppearance();
}

function persistDisplaySettings() {
  try { localStorage.setItem(DISPLAY_KEY, JSON.stringify(displayPreferences)); }
  catch (_) { showNotice("当前浏览器无法保存显示偏好，本次设置仍然生效", true); }
  syncDisplaySettings();
  renderEventFeed();
  if (timelineView === "replay") renderEventFeed(true);
}

function changeDisplaySettings() {
  displayPreferences.categories = [...document.querySelectorAll('[name="event-category"]:checked')].map(input => input.value);
  displayPreferences.scopes = [...document.querySelectorAll('[name="event-scope"]:checked')].map(input => input.value);
  displayPreferences.showMemories = document.getElementById("display-memories").checked;
  displayPreferences.compact = document.getElementById("display-compact").checked;
  displayPreferences.theme = document.getElementById("display-theme").value;
  displayPreferences.fontSize = document.getElementById("display-font-size").value;
  displayPreferences.highContrast = document.getElementById("display-contrast").checked;
  displayPreferences.reduceMotion = document.getElementById("display-reduce-motion").checked;
  persistDisplaySettings();
}

function changeEventPreset(value) {
  if (value === "custom") { openDisplaySettings(); return; }
  displayPreferences.categories = value === "all" ? Object.keys(EVENT_CATEGORIES) : [...DEFAULT_DISPLAY.categories];
  persistDisplaySettings();
}

function changeEventSearch(value) { displayPreferences.query = value; persistDisplaySettings(); }
function changeEventSeat(value) { displayPreferences.seat = value; persistDisplaySettings(); }
function changeAutoScroll(value) { displayPreferences.autoScroll = value; persistDisplaySettings(); }
function resetDisplaySettings() { displayPreferences = structuredClone(DEFAULT_DISPLAY); updateEventSeatOptions(); persistDisplaySettings(); }

function updateEventSeatOptions() {
  const seats = timelineView === "replay" && replayData ? replayData.seats || {} : currentSeats;
  const select = document.getElementById("event-seat");
  select.replaceChildren(new Option("全部席位", ""), ...Object.values(seats).map(seat => new Option(`${seat.seat_id} 号 · ${seat.name}`, seat.seat_id)));
  if (displayPreferences.seat && !seats[displayPreferences.seat]) displayPreferences.seat = "";
  select.value = displayPreferences.seat;
}

function switchControlSection(section) {
  for (const name of ["display", "mods", "director", "room"]) {
    document.getElementById(`control-${name}`).hidden = name !== section;
    const tab = document.getElementById(`control-tab-${name}`);
    tab.classList.toggle("active", name === section);
    tab.setAttribute("aria-pressed", String(name === section));
  }
}

function openDisplaySettings() {
  switchControlSection("display");
  document.getElementById("controls-panel").showPopover();
}

function renderEventFeed(replay = false) {
  const container = document.getElementById(replay ? "replay-timeline" : "timeline-container");
  const events = replay ? (replayData?.events || []).slice(0, replayPosition) : latestSnapshot?.events || [];
  const visible = events.filter(event => eventMatches(event));
  const scrollTop = container.scrollTop;
  const open = new Set([...container.querySelectorAll("details[open]")].map(node => node.dataset.eventDetail));
  container.replaceChildren();
  let lastRound = null;
  for (const event of visible) {
    if (event.round_num !== lastRound) {
      const divider = document.createElement("div");
      divider.className = "event-round";
      divider.textContent = `第 ${event.round_num} 回合`;
      container.appendChild(divider);
      lastRound = event.round_num;
    }
    appendEvent(event, replay ? "replay-timeline" : "timeline-container", open);
  }
  if (!visible.length) container.innerHTML = `<div class="empty-state"><strong>${events.length ? "没有符合筛选条件的事件" : "等待本局的第一条事件"}</strong><p>${events.length ? "调整显示设置，或恢复默认后查看。" : "玩家行动、消息与记忆会出现在这里。"}</p>${events.length ? '<button class="btn btn-secondary btn-sm" onclick="resetDisplaySettings()">恢复默认显示</button>' : ""}</div>`;
  container.scrollTop = replay || displayPreferences.autoScroll ? container.scrollHeight : scrollTop;
  if (replay === (timelineView === "replay")) {
    document.getElementById("event-count").textContent = `${visible.length} / ${events.length} 条事件`;
    const filtered = displayPreferences.scopes.length !== 4 || displayPreferences.seat || displayPreferences.query || displayPreferences.categories.length !== 6;
    document.getElementById("feed-filter-state").textContent = filtered ? "已按显示设置筛选" : "全部事件";
  }
}

function appendEvent(event, targetId = "timeline-container", open = new Set()) {
  const category = eventCategory(event);
  const description = describeEvent(event);
  const actor = event.from_seat ?? event.data?.seat ?? event.to_seat;
  const scope = { PUBLIC: "公开", PRIVATE: "私信", GROUP: "阵营", HOST_ONLY: "主持人" }[event.scope] || event.scope;
  const detailId = `${event.seq}:raw`;
  const noteId = `${event.seq}:note`;
  const item = document.createElement("article");
  item.className = `event-item event-${category}`;
  item.dataset.eventSeq = event.seq;
  item.dataset.eventCategory = category;
  item.innerHTML = `<div class="event-avatar" aria-hidden="true">${actor ?? (category === "memory" ? "记" : "A")}</div><div class="event-main"><header class="event-header"><h3>${escapeHtml(description.title)}</h3><time datetime="${new Date(event.timestamp * 1000).toISOString()}">${new Date(event.timestamp * 1000).toLocaleTimeString([], { hour12: false })}</time></header><div class="event-meta"><span class="event-category">${EVENT_CATEGORIES[category]}</span><span>${escapeHtml(scope)}${event.scope === "PRIVATE" && event.to_seat ? ` · ${event.to_seat} 号位` : ""}</span><span>#${event.seq}</span></div>${description.text ? `<div class="event-body">${escapeHtml(description.text)}</div>` : ""}${event.secret_reason ? `<blockquote class="event-note"><span>玩家备注</span>${escapeHtml(event.secret_reason)}</blockquote>` : ""}${category === "memory" ? `<details class="event-detail" data-event-detail="${noteId}" ${open.has(noteId) ? "open" : ""}><summary>本次笔记全文${event.data?.baseline ? " · 首次采集" : ""}</summary><pre>${escapeHtml(event.data?.text || "")}</pre></details>` : ""}<details class="event-detail" data-event-detail="${detailId}" ${open.has(detailId) ? "open" : ""}><summary>原始详情</summary><pre>${escapeHtml(JSON.stringify({ ...event, content: description.parsed.data && !description.parsed.text ? description.parsed.data : event.content }, null, 2))}</pre></details></div>`;
  document.getElementById(targetId).appendChild(item);
}
