export const EVENT_CATEGORIES = {
  results: "结果与进程",
  messages: "消息与发言",
  thoughts: "即时自述",
  memory: "文档记录",
  requests: "行动指令",
  submissions: "原始提交",
  system: "系统记录"
};

export const ACTION_NAMES = { ACT: "行动", SPEAK: "发言", VOTE: "投票", CHOOSE: "选择", NUMBER: "数值" };

export function categoryOf(event) {
  if (event.event_type === "AGENT_NOTE") return "thoughts";
  if (event.event_type === "MEMORY_UPDATE") return "memory";
  if (["ACTION_REQUEST", "ACTION_CANCELLED"].includes(event.event_type)
    || (event.event_type === "PRIVATE_MESSAGE" && event.from_seat == null)) return "requests";
  if (event.event_type === "ACTION_SUBMIT") return event.data?.action_type === "SPEAK" ? "messages" : "submissions";
  if (["CHAT", "PRIVATE_MESSAGE", "GROUP_MESSAGE", "ANNOUNCEMENT"].includes(event.event_type)) return "messages";
  if (event.event_type.startsWith("GAME") || ["PHASE_CHANGE", "GAME_STARTED", "GAME_FINISHED", "GAME_STATUS", "GAME_RESULT"].includes(event.event_type)) return "results";
  return "system";
}

function seatsIn(event) {
  return [event.from_seat, event.to_seat, event.data?.seat, event.data?.target_seat]
    .filter(value => value !== null && value !== undefined).map(String);
}

function cardText(cards) {
  return (cards || []).map(card => ({ SJ: "小王", BJ: "大王" }[card] || card)).join("  ");
}

function parseContent(content) {
  const text = String(content || "").trim();
  const starts = [0, ...Array.from(text.matchAll(/\n(?=\s*[\[{])/g), match => match.index + 1)];
  for (const start of starts) {
    try {
      const data = JSON.parse(text.slice(start));
      if (data !== null && typeof data === "object") return { text: text.slice(0, start).trim(), data };
    } catch {
      // 非 JSON 正文继续保留为原文。
    }
  }
  return { text, data: null };
}

function defaultDescription(event) {
  const data = event.data || {};
  const parsed = parseContent(event.content);
  let title = String(event.title || event.event_type || "系统事件").replace(/【([^】]+)】/g, "$1 ").trim();
  let text = parsed.text || (typeof event.content === "string" ? event.content : event.content ? JSON.stringify(event.content) : "");
  if (event.event_type === "ACTION_REQUEST") {
    title = `等待 ${event.to_seat} 号位行动`;
    text = `已派发${ACTION_NAMES[data.action_type] || data.action_type || "行动"}指令`;
  } else if (event.event_type === "ACTION_SUBMIT") {
    title = `${event.from_seat} 号位提交${ACTION_NAMES[data.action_type] || "行动"}`;
    if (Array.isArray(data.cards)) text = `出牌 ${cardText(data.cards)}${data.cards.length} 张`;
    else if (!text) text = Object.hasOwn(data, "choice") ? `选择 ${data.choice}` : Object.hasOwn(data, "value") ? `提交数值 ${data.value}` : "已提交，展开原始详情查看内容";
  } else if (event.event_type === "MEMORY_UPDATE") {
    title = `${event.from_seat} 号位${data.baseline ? "的笔记快照" : "更新了笔记"}`;
    const added = (data.changes || []).filter(line => line.kind === "added").map(line => line.text);
    text = (added.length ? added : String(data.text || "").split("\n")).filter(line => line.trim() && !/^#{1,6}\s/.test(line)).slice(-3).join("\n") || (data.exists === false ? "记忆文件已移除" : "笔记为空");
  } else if (event.event_type === "GAME_EVENT") {
    if (Array.isArray(data.cards)) {
      title = `${data.seat ?? event.from_seat ?? ""} 号位出${data.combination?.name || "牌"}`;
      text = `${cardText(data.cards)}${data.remaining === undefined ? "" : ` · 余 ${data.remaining} 张`}`;
    } else if (event.title?.includes("过牌")) {
      title = `${data.seat ?? event.from_seat ?? ""} 号位过牌`;
      text = "放弃跟牌，等待下一位行动";
    }
  }
  return { title, text, parsed };
}

export function describeEvent(event, presenter) {
  const result = defaultDescription(event);
  if (typeof presenter !== "function") return result;
  try {
    const custom = presenter(event, result.parsed);
    if (custom) return { title: custom.title || result.title, text: custom.text ?? result.text };
  } catch (error) {
    console.warn("Mod 事件摘要渲染失败", error);
  }
  return result;
}

export function filterEvents(events, display) {
  const query = display.query.trim().toLocaleLowerCase();
  return events.filter(event => {
    if (!display.categories.includes(categoryOf(event)) || !display.scopes.includes(event.scope)) return false;
    if (display.seat && !seatsIn(event).includes(String(display.seat))) return false;
    return !query || [event.title, event.content, event.secret_reason, JSON.stringify(event.data || {})]
      .join("\n").toLocaleLowerCase().includes(query);
  });
}

export function scopeLabel(scope, toSeat) {
  const names = { PUBLIC: "全员公开", PRIVATE: "私信", GROUP: "阵营", HOST_ONLY: "仅主持人" };
  return `${names[scope] || scope || "系统"}${scope === "PRIVATE" && toSeat ? ` · ${toSeat} 号位` : ""}`;
}
