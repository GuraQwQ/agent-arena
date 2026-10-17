import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { BlurText } from "./components/BlurText.jsx";
import { request, jsonRequest, arenaApi } from "./api/arenaClient.js";
import { useArenaSession } from "./state/useArenaSession.js";
import { ACTION_NAMES, EVENT_CATEGORIES } from "./events/eventModel.js";
import { EventItem, EventTimeline } from "./events/EventTimeline.jsx";
import { createModFrontend } from "./mods/modFrontend.js";

const DEFAULT_DISPLAY = {
  categories: ["results", "messages"],
  scopes: ["PUBLIC", "PRIVATE", "GROUP", "HOST_ONLY"],
  seat: "",
  query: "",
  autoScroll: true,
  showMemories: true,
  compact: false,
  theme: "light",
  fontSize: "normal",
  highContrast: false,
  reduceMotion: false
};

function clone(value) {
  return typeof structuredClone === "function" ? structuredClone(value) : JSON.parse(JSON.stringify(value));
}

function readDisplay() {
  try {
    const stored = JSON.parse(localStorage.getItem("arena_display_preferences") || "null");
    return { ...DEFAULT_DISPLAY, ...(stored || {}) };
  } catch {
    return clone(DEFAULT_DISPLAY);
  }
}

function App() {
  const arena = useArenaSession();
  const [display, setDisplay] = useState(readDisplay);
  const [perspective, setPerspective] = useState(null);
  const [panel, setPanel] = useState(null);
  const [tab, setTab] = useState("events");
  const [perspectiveSnapshot, setPerspectiveSnapshot] = useState(null);
  const [eventPresenter, setEventPresenter] = useState(null);

  const current = perspectiveSnapshot || arena.snapshot;
  const seats = current?.seats || {};

  useEffect(() => {
    document.documentElement.dataset.theme = display.theme;
    document.documentElement.dataset.fontSize = display.fontSize;
    document.documentElement.dataset.contrast = display.highContrast ? "high" : "normal";
    document.documentElement.dataset.motion = display.reduceMotion ? "reduced" : "full";
    document.documentElement.dataset.compact = display.compact ? "true" : "false";
    try { localStorage.setItem("arena_display_preferences", JSON.stringify(display)); } catch { /* 浏览器禁用存储时仍保留本次状态 */ }
  }, [display]);

  useEffect(() => {
    setPerspectiveSnapshot(null);
    if (perspective === null || !arena.snapshot) return;
    arenaApi.perspective(perspective).then(setPerspectiveSnapshot).catch(error => arena.showNotice(error.message, true));
  }, [arena.snapshot, perspective]);

  if (!arena.access?.authenticated) return <HostLogin access={arena.access} onJoin={arena.join} onRefresh={arena.refreshAccess} notice={arena.notice} />;
  return <>
    <AppHeader current={current} seats={seats} perspective={perspective} setPerspective={setPerspective} connected={arena.connected} debug={arena.access?.debug_mode} onSettings={() => setPanel("display")} />
    {arena.notice && <div className={`notice ${arena.notice.error ? "notice-error" : ""}`}>{arena.notice.message}</div>}
    <main className="app-shell">
      <SeatRail snapshot={current} onRefresh={() => request("/api/admin/snapshot").then(data => arena.showNotice(data ? "已刷新快照" : "刷新失败"))} onNotice={arena.showNotice} />
      <section className="workspace">
        <WorkspaceHeader current={current} tab={tab} setTab={setTab} />
        {tab === "events" && <EventTimeline snapshot={current} display={display} setDisplay={setDisplay} presenter={eventPresenter} />}
        {tab === "game" && <GameStage snapshot={current} onNotice={arena.showNotice} onPresenter={setEventPresenter} />}
        {tab === "replay" && <ReplayPlaceholder onNotice={arena.showNotice} />}
      </section>
      {display.showMemories && <MemoryRail snapshot={current} />}
    </main>
    {panel && <ControlPanel panel={panel} setPanel={setPanel} display={display} setDisplay={setDisplay} snapshot={current} onNotice={arena.showNotice} />}
  </>;
}

function HostLogin({ access, onJoin, onRefresh, notice }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async event => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try { await onJoin(password); setPassword(""); }
    catch (error) { setError(error.message); onRefresh().catch(() => {}); }
    finally { setBusy(false); }
  };
  return <div className="login-page">
    <div className="login-orbit orbit-one" /><div className="login-orbit orbit-two" />
    <section className="login-card">
      <div className="brand-mark" aria-hidden="true">A</div>
      <p className="eyebrow">LOCAL AGENT SANDBOX</p>
      <h1><BlurText>Agent Arena</BlurText></h1>
      <p className="login-copy">主持人控制台 · 本地实时观战</p>
      <form onSubmit={submit}>
        <label htmlFor="host-password">主持人令牌</label>
        <input id="host-password" type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" required autoFocus />
        <button className="button button-primary button-wide" disabled={busy}>{busy ? "正在验证…" : "进入控制台"}</button>
      </form>
      <div className="login-meta"><span>{access?.config_path || "读取本地令牌文件…"}</span><button className="text-button" type="button" onClick={() => onRefresh().catch(() => {})}>刷新状态</button></div>
      <p className="login-uses">{access ? `本服务剩余 ${access.remaining_uses} 次主持人加入机会 · 已使用 ${access.used_count} 次` : ""}</p>
      {(notice || error) && <p className="form-error">{error || notice?.message}</p>}
    </section>
  </div>;
}

function AppHeader({ current, seats, perspective, setPerspective, connected, debug, onSettings }) {
  return <header className="topbar">
    <div className="brand"><div className="brand-mark small">A</div><div><strong>Agent Arena</strong><span>主持人控制台</span></div></div>
    <div className="topbar-actions">
      <label className="perspective-control">观察视角<span className="select-shell"><select value={perspective ?? ""} onChange={event => setPerspective(event.target.value ? Number(event.target.value) : null)}><option value="">主持视角</option>{Object.values(seats).map(seat => <option key={seat.seat_id} value={seat.seat_id}>{seat.seat_id} 号位 · {seat.name}</option>)}</select></span></label>
      {debug && <span className="debug-badge">调试模式</span>}<div className={`connection ${connected ? "online" : "offline"}`}><span />{connected ? "实时连接" : "连接中"}</div>
      <button className="icon-button" title="打开设置" aria-label="打开设置" onClick={onSettings}>⚙</button>
    </div>
  </header>;
}

function WorkspaceHeader({ current, tab, setTab }) {
  return <div className="workspace-header">
    <div><p className="eyebrow">{current?.room_title || "竞技场"}</p><h2><BlurText>{current?.phase || "准备中"}</BlurText></h2><p className="subtle">第 {current?.round_num || 1} 回合 · {Object.keys(current?.active_actions || {}).length ? `${Object.keys(current.active_actions).length} 个待办行动` : "等待主持人调度"}</p></div>
    <nav className="view-tabs"><button className={tab === "events" ? "active" : ""} onClick={() => setTab("events")}>实时事件</button><button className={tab === "game" ? "active" : ""} onClick={() => setTab("game")}>游戏桌面</button><button className={tab === "replay" ? "active" : ""} onClick={() => setTab("replay")}>存档复盘</button></nav>
  </div>;
}

function SeatRail({ snapshot, onNotice }) {
  const [editing, setEditing] = useState(null);
  const seats = Object.values(snapshot?.seats || {});
  const [form, setForm] = useState({ seat_id: 1, name: "", role: "", group_id: "", init_prompt: "" });
  const open = seat => { setEditing(seat?.seat_id || "new"); setForm(seat ? { seat_id: seat.seat_id, name: seat.name || "", role: seat.role || "", group_id: seat.group_id || "", init_prompt: seat.init_prompt || "" } : { seat_id: Math.max(0, ...seats.map(item => item.seat_id)) + 1, name: "", role: "", group_id: "", init_prompt: "" }); };
  const save = async event => { event.preventDefault(); try { await jsonRequest("/api/admin/seats", form); setEditing(null); onNotice("席位已保存"); } catch (error) { onNotice(error.message, true); } };
  return <aside className="rail seat-rail"><div className="section-heading"><div><p className="eyebrow">ROOM ROSTER</p><h3>玩家 <span className="count">{seats.length}</span></h3></div><button className="text-button" onClick={() => open(null)}>+ 新增</button></div><p className="subtle rail-hint">连接状态、待办行动与模型席位。</p><div className="seat-list">{seats.map(seat => <article className="seat-card" key={seat.seat_id} onClick={() => open(seat)}><div className={`seat-avatar ${seat.connection_status?.toLowerCase() || "never"}`}>{seat.seat_id}</div><div className="seat-info"><strong>{seat.name}</strong><span>{seat.role || "未设置角色"}</span><div className="seat-status"><i className={seat.connection_status?.toLowerCase() || "never"} />{seat.connection_status === "LISTENING" ? "在线监听" : seat.connection_status === "RECENT" ? `${seat.seconds_since_seen || 0} 秒前活跃` : "等待连接"}</div></div>{snapshot?.active_actions?.[seat.seat_id] && <b className="action-dot">行动</b>}</article>)}</div>{editing && <div className="inline-editor"><div className="section-heading"><h4>{editing === "new" ? "新增席位" : `编辑 ${editing} 号位`}</h4><button className="icon-button" onClick={() => setEditing(null)} aria-label="关闭">×</button></div><form onSubmit={save}><label>席位号<input type="number" min="1" max="64" value={form.seat_id} onChange={event => setForm({ ...form, seat_id: Number(event.target.value) })} required /></label><label>名称<input value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} required /></label><label>角色<input value={form.role} onChange={event => setForm({ ...form, role: event.target.value })} /></label><label>阵营<input value={form.group_id} onChange={event => setForm({ ...form, group_id: event.target.value })} /></label><label>初始化提示<textarea rows="3" value={form.init_prompt} onChange={event => setForm({ ...form, init_prompt: event.target.value })} /></label><button className="button button-primary button-wide">保存席位</button></form></div>}</aside>;
}

function MemoryRail({ snapshot }) {
  const memories = snapshot?.memories || {};
  const seats = snapshot?.seats || {};
  const seatIds = snapshot?.perspective_seat ? [String(snapshot.perspective_seat)] : Object.keys(seats);
  return <aside className="rail memory-rail"><div className="section-heading"><div><p className="eyebrow">PRIVATE NOTES</p><h3>玩家笔记</h3></div><span className="live-label">LIVE</span></div><p className="subtle rail-hint">默认展示最近一次 memory.md 写入内容。</p><div className="memory-list">{seatIds.map(id => { const note = memories[id]; const status = snapshot?.memory_status?.[id]; return <article className="memory-card" key={id}><header><div className="memory-avatar">{id}</div><div><strong>{seats[id].name}</strong><span>{note ? note.baseline ? "首次采集" : "最新变更" : "等待写入"}</span></div>{note && <i className="memory-pulse" />}</header>{note ? <><p className="memory-time">{new Date((note.written_at || note.observed_at || 0) * 1000).toLocaleString()}</p><div className="memory-diff">{(note.changes || []).length ? note.changes.slice(-4).map((line, index) => <div className={`memory-line ${line.kind}`} key={`${line.kind}-${index}`}><b>{line.kind === "added" ? "+" : line.kind === "removed" ? "−" : "·"}</b>{line.text}</div>) : <span>{note.text || "文件为空"}</span>}</div><details><summary>查看全文</summary><pre>{note.text || ""}</pre></details></> : <p className="subtle">{status?.path ? "等待下一次写入" : "尚未登记工作目录"}</p>}</article>; })}</div></aside>;
}

function GameStage({ snapshot, onNotice, onPresenter }) {
  const container = useRef(null);
  const view = useRef(null);
  const bridge = useRef(null);
  const stylesheet = useRef(null);
  const [frontend, setFrontend] = useState(null);
  const gameKey = snapshot?.game ? `${snapshot.game.id}:${snapshot.game.name}:${snapshot.game.version}` : null;
  const payload = { state: snapshot?.game?.state, status: snapshot?.game?.status, perspective: snapshot?.perspective_seat ?? null, seats: snapshot?.seats, mod_settings: snapshot?.mod_settings?.[snapshot?.game?.name] || {} };
  useEffect(() => { if (!container.current) return; bridge.current = createModFrontend({ onNotice, onPresenter, container: container.current, stylesheetRef: stylesheet }); return () => { bridge.current?.destroy(); }; }, [onNotice, onPresenter]);
  useEffect(() => { let active = true; if (!gameKey) { setFrontend(null); bridge.current?.destroy(); return undefined; } arenaApi.gameFrontend().then(data => { if (active) setFrontend(data.frontend); }).catch(error => onNotice(error.message, true)); return () => { active = false; bridge.current?.destroy(); }; }, [gameKey, onNotice]);
  useEffect(() => { if (!frontend?.module || !bridge.current) return; bridge.current.mount(frontend, { ...payload, adminRequest: (url, body, method = "POST") => jsonRequest(url, body, method) }); }, [frontend, gameKey]);
  useEffect(() => { bridge.current?.update(payload); }, [snapshot]);
  return <div className="game-stage"><div className="stage-bar"><div><p className="eyebrow">GAME VIEW</p><strong>{snapshot?.game ? `${snapshot.game.name} · ${snapshot.game.status}` : "尚未加载游戏"}</strong></div>{snapshot?.game && <div className="stage-actions"><button type="button" className="button button-quiet" disabled={snapshot.game.status !== "RUNNING"} onClick={() => arenaApi.gameControl("pause").catch(error => onNotice(error.message, true))}>暂停</button><button type="button" className="button button-primary" disabled={snapshot.game.status !== "PAUSED"} onClick={() => arenaApi.gameControl("resume").catch(error => onNotice(error.message, true))}>继续</button></div>}</div><div ref={container} className="game-container" aria-busy={Boolean(snapshot?.game && !frontend)}>{!snapshot?.game && <div className="empty-state"><span>◇</span><strong>游戏桌面尚未启动</strong><p>启用游戏 Mod 后从控制台启动一局。</p></div>}{snapshot?.game && !frontend && <div className="loading-state">正在加载游戏界面…</div>}</div></div>;
}

function ReplayPlaceholder({ onNotice }) {
  const [archives, setArchives] = useState([]);
  const [selected, setSelected] = useState("");
  const [replay, setReplay] = useState(null);
  const [position, setPosition] = useState(0);
  const refresh = useCallback(() => request("/api/admin/archives").then(data => setArchives(data.archives || [])).catch(error => onNotice(error.message, true)), [onNotice]);
  useEffect(() => { refresh(); }, [refresh]);
  const load = async value => { setSelected(value); setPosition(0); if (!value) return setReplay(null); try { setReplay(await request(`/api/admin/archives/${encodeURIComponent(value)}`)); } catch (error) { onNotice(error.message, true); } };
  const events = replay?.events || [];
  return <div className="replay-view"><div className="replay-toolbar"><label>选择对局存档<select value={selected} onChange={event => load(event.target.value)}><option value="">选择存档</option>{archives.map(item => <option key={item.room_id} value={item.room_id}>{item.title} · {item.event_count} 条事件</option>)}</select></label><button className="button button-quiet" onClick={refresh}>刷新</button><button className="button button-quiet" onClick={() => jsonRequest("/api/admin/archives", {}, "POST").then(() => { onNotice("当前对局已保存"); refresh(); }).catch(error => onNotice(error.message, true))}>保存当前局</button></div>{replay ? <><div className="replay-progress"><span>事件 {position} / {events.length}</span><input type="range" min="0" max={events.length} value={position} onChange={event => setPosition(Number(event.target.value))} /></div><div className="replay-events">{events.slice(0, position).slice(-12).reverse().map(event => <EventItem event={event} key={event.seq} />)}{!position && <div className="empty-state"><span>◷</span><strong>拖动时间线开始复盘</strong></div>}</div></> : <div className="empty-state"><span>◷</span><strong>{archives.length ? "选择一个存档开始复盘" : "暂无对局存档"}</strong><p>实时事件会按主持人视角重新展开。</p></div>}</div>;
}

function ControlPanel({ panel, setPanel, display, setDisplay, snapshot, onNotice }) {
  const [active, setActive] = useState(panel === "mods" ? "mods" : panel === "room" ? "room" : panel === "director" ? "director" : "display");
  const panelRef = useRef(null);
  useEffect(() => { const closeOnEscape = event => event.key === "Escape" && setPanel(null); document.addEventListener("keydown", closeOnEscape); panelRef.current?.querySelector("button, input, select, textarea")?.focus(); return () => document.removeEventListener("keydown", closeOnEscape); }, [setPanel]);
  return <div className="panel-backdrop" onMouseDown={event => event.target === event.currentTarget && setPanel(null)}><aside className="control-panel" ref={panelRef} role="dialog" aria-modal="true" aria-label="主持人设置"><header className="control-header"><div><p className="eyebrow">CONTROL DECK</p><h3>主持人设置</h3></div><button type="button" className="icon-button" onClick={() => setPanel(null)} aria-label="关闭设置">×</button></header><nav className="control-tabs" aria-label="设置分类">{[["display", "显示"], ["mods", "Mod"], ["director", "调度"], ["room", "房间"]].map(([id, label]) => <button type="button" key={id} className={active === id ? "active" : ""} aria-pressed={active === id} onClick={() => setActive(id)}>{label}</button>)}</nav>{active === "display" && <DisplaySettings display={display} setDisplay={setDisplay} />}{active === "mods" && <ModSettings onNotice={onNotice} />}{active === "director" && <DirectorSettings snapshot={snapshot} onNotice={onNotice} />}{active === "room" && <RoomSettings snapshot={snapshot} onNotice={onNotice} />}</aside></div>;
}

function DisplaySettings({ display, setDisplay }) {
  const categories = Object.entries(EVENT_CATEGORIES);
  const toggle = (key, value) => setDisplay({ ...display, [key]: display[key].includes(value) ? display[key].filter(item => item !== value) : [...display[key], value] });
  return <div className="settings-content"><SettingsSection title="外观"><div className="settings-grid"><label>主题<select value={display.theme} onChange={event => setDisplay({ ...display, theme: event.target.value })}><option value="light">明亮 · 纸白</option><option value="dark">深色 · 石墨</option><option value="system">跟随系统</option></select></label><label>文字大小<select value={display.fontSize} onChange={event => setDisplay({ ...display, fontSize: event.target.value })}><option value="small">较小</option><option value="normal">标准</option><option value="large">较大</option></select></label></div><label className="check-row"><input type="checkbox" checked={display.highContrast} onChange={event => setDisplay({ ...display, highContrast: event.target.checked })} />增强文字对比</label><label className="check-row"><input type="checkbox" checked={display.reduceMotion} onChange={event => setDisplay({ ...display, reduceMotion: event.target.checked })} />减少动态效果</label></SettingsSection><SettingsSection title="事件类型"><div className="check-grid">{categories.map(([id, label]) => <label className="check-row" key={id}><input type="checkbox" checked={display.categories.includes(id)} onChange={() => toggle("categories", id)} />{label}</label>)}</div></SettingsSection><SettingsSection title="可见范围"><div className="check-grid">{[["PUBLIC", "全员公开"], ["PRIVATE", "定向私信"], ["GROUP", "阵营消息"], ["HOST_ONLY", "仅主持人"]].map(([id, label]) => <label className="check-row" key={id}><input type="checkbox" checked={display.scopes.includes(id)} onChange={() => toggle("scopes", id)} />{label}</label>)}</div></SettingsSection><SettingsSection title="阅读布局"><label className="check-row"><input type="checkbox" checked={display.showMemories} onChange={event => setDisplay({ ...display, showMemories: event.target.checked })} />显示玩家笔记侧栏</label><label className="check-row"><input type="checkbox" checked={display.compact} onChange={event => setDisplay({ ...display, compact: event.target.checked })} />紧凑事件间距</label></SettingsSection><button className="button button-quiet button-wide" onClick={() => setDisplay(clone(DEFAULT_DISPLAY))}>恢复默认显示</button></div>;
}

function SettingsSection({ title, children }) { return <section className="settings-section"><h4>{title}</h4>{children}</section>; }

function DirectorSettings({ snapshot, onNotice }) {
  const seats = Object.values(snapshot?.seats || {});
  const [phase, setPhase] = useState(snapshot?.phase || "");
  const [round, setRound] = useState(snapshot?.round_num || 1);
  const [target, setTarget] = useState(seats[0]?.seat_id || "");
  const [action, setAction] = useState("ACT");
  const [prompt, setPrompt] = useState("");
  const [timeout, setTimeoutValue] = useState(60);
  const sendPhase = async event => { event.preventDefault(); try { await jsonRequest("/api/admin/command", { command_type: "ADVANCE_PHASE", phase, round_num: Number(round) }); onNotice("场景阶段已变更"); } catch (error) { onNotice(error.message, true); } };
  const dispatch = async event => { event.preventDefault(); if (!target) return onNotice("请选择目标席位", true); try { await jsonRequest("/api/admin/command", { command_type: "DISPATCH_ACTION", target_seat: Number(target), action_type: action, prompt: prompt || "请依据当前局势独立做出行动。", timeout: Number(timeout), result_scope: "PUBLIC" }); onNotice(`已向 ${target} 号位发出行动指令`); } catch (error) { onNotice(error.message, true); } };
  return <div className="settings-content"><SettingsSection title="推进场景阶段"><form onSubmit={sendPhase}><label>新阶段名称<input value={phase} onChange={event => setPhase(event.target.value)} placeholder="例如：自由调查" required /></label><label>回合<input type="number" min="1" value={round} onChange={event => setRound(event.target.value)} required /></label><button className="button button-primary button-wide">变更阶段</button></form></SettingsSection><SettingsSection title="点名玩家行动"><form onSubmit={dispatch}><label>目标席位<select value={target} onChange={event => setTarget(event.target.value)}><option value="">选择席位</option>{seats.map(seat => <option key={seat.seat_id} value={seat.seat_id}>{seat.seat_id} 号位 · {seat.name}</option>)}</select></label><label>行动类型<select value={action} onChange={event => setAction(event.target.value)}>{Object.entries(ACTION_NAMES).map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select></label><label>行动指引<textarea rows="4" value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="请依据你目前的发现进行行动或发言。" /></label><label>限时（秒）<input type="number" min="10" max="300" value={timeout} onChange={event => setTimeoutValue(event.target.value)} /></label><button className="button button-primary button-wide">发出行动指令</button></form></SettingsSection></div>;
}

function ModSettings({ onNotice }) {
  const [status, setStatus] = useState(null);
  const [contentPacks, setContentPacks] = useState(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("idle");
  const [filter, setFilter] = useState("all");
  const refresh = useCallback(async () => {
    setPhase("checking");
    try {
      const [modsResult, packsResult] = await Promise.allSettled([arenaApi.mods(), arenaApi.contentPacks()]);
      if (modsResult.status === "rejected") throw modsResult.reason;
      setStatus(modsResult.value);
      if (packsResult.status === "fulfilled") setContentPacks(packsResult.value);
      setPhase("ready");
    }
    catch (error) { setPhase("error"); onNotice(error.message, true); }
  }, [onNotice]);
  useEffect(() => { refresh(); }, [refresh]);
  const toggle = async (id, checked) => {
    if (busy) return;
    setBusy(true); setPhase("reloading");
    try { setStatus(await arenaApi.applyMods(checked ? [...status.enabled, id] : status.enabled.filter(item => item !== id))); setPhase("ready"); onNotice("Mod 已重载"); }
    catch (error) { setPhase("error"); onNotice(error.message, true); await refresh(); }
    finally { setBusy(false); }
  };
  const reloadEnabled = async () => {
    if (busy) return;
    setBusy(true); setPhase("reloading");
    try { setStatus(await arenaApi.applyMods(status.enabled)); setPhase("ready"); onNotice("已重载启用的 Mod"); }
    catch (error) { setPhase("error"); onNotice(error.message, true); }
    finally { setBusy(false); }
  };
  const saveSettings = async (item, values) => {
    setBusy(true); setPhase("reloading");
    try { setStatus(await arenaApi.modSettings(item.id, values)); setPhase("ready"); onNotice(`${item.name} 设置已保存并重载`); }
    catch (error) { setPhase("error"); onNotice(error.message, true); }
    finally { setBusy(false); }
  };
  if (!status) return <div className="settings-content"><div className="loading-state">正在读取 Mod 清单…</div></div>;
  const visibleMods = status.mods.filter(mod => filter === "all" || filter === "enabled" && status.enabled.includes(mod.id) || filter === "issues" && (mod.error || status.issues?.some(issue => issue.mods?.includes(mod.id))) || filter === "disabled" && !status.enabled.includes(mod.id));
  const phaseLabel = { checking: "检查依赖…", reloading: "重载运行期…", error: "需要处理", ready: "运行期已同步", idle: "" }[phase];
  return <div className="settings-content"><SettingsSection title="运行状态"><div className="settings-actions"><button className="button button-quiet" onClick={refresh} disabled={busy}>刷新列表</button><button className="button button-quiet" onClick={reloadEnabled} disabled={busy}>重载已启用</button><span className={`mod-phase mod-phase-${phase}`} role="status">{phaseLabel}</span></div><div className="mod-filters" role="group" aria-label="Mod 状态筛选">{[["all", "全部"], ["enabled", "已启用"], ["disabled", "未启用"], ["issues", "有问题"]].map(([id, label]) => <button key={id} className={filter === id ? "active" : ""} onClick={() => setFilter(id)}>{label}</button>)}</div></SettingsSection>{contentPacks && <SettingsSection title="声明式内容包"><p className="subtle">已加载 {contentPacks.packs?.length || 0} 个内容包；内容包只提供数据，不执行代码。</p>{contentPacks.packs?.map(pack => <p className="field-state" key={pack.id}>{pack.name} · {pack.version} · {pack.hash?.slice(0, 12)}</p>)}{contentPacks.warnings?.map((warning, index) => <div className="issue warning" key={`pack-warning-${index}`}>{warning}</div>)}</SettingsSection>}{status.issues?.length > 0 && <div className="issue-list" aria-live="polite">{status.issues.map((issue, index) => <div className={`issue ${issue.severity || "error"}`} key={`${issue.code}-${index}`}><strong>{issue.message}</strong><span>{issue.mods?.join("、")}{issue.resource ? ` · ${issue.resource}` : ""}</span></div>)}</div>}<SettingsSection title="已发现的 Mod"><div className="mod-list">{visibleMods.length ? visibleMods.map(mod => <ModCard key={mod.id} mod={mod} status={status} busy={busy} onToggle={toggle} onSave={saveSettings} />) : <p className="subtle">当前筛选没有 Mod。</p>}</div></SettingsSection><SettingsSection title="加载顺序"><ol className="load-order">{(status.order || []).map(id => <li key={id}>{id}</li>)}</ol></SettingsSection></div>;
}

function ModCard({ mod, status, busy, onToggle, onSave }) {
  const item = status.settings?.find(setting => setting.id === mod.id);
  const [values, setValues] = useState(item?.values || {});
  useEffect(() => setValues(item?.values || {}), [item]);
  const dirty = item && JSON.stringify(values) !== JSON.stringify(item.values);
  const invalid = item && Object.entries(item.schema).some(([key, schema]) => { const value = values[key]; return (schema.type === "integer" && !Number.isInteger(value)) || (schema.type === "number" && !Number.isFinite(value)) || (schema.min !== undefined && value < schema.min) || (schema.max !== undefined && value > schema.max); });
  return <article className="mod-card"><header><div><strong>{mod.name}</strong><span>{mod.version || "配置错误"} · {mod.type === "game" ? "游戏" : "扩展"}</span></div><label className="switch"><input type="checkbox" checked={status.enabled.includes(mod.id)} disabled={busy || !!mod.error} onChange={event => onToggle(mod.id, event.target.checked)} /><i /></label></header><p>{mod.description || mod.error || ""}</p><details><summary>依赖与覆盖项</summary><p>编号：{mod.id}</p><p>依赖：{Object.entries(mod.dependencies || {}).map(([id, version]) => `${id} ${version || "任意版本"}`).join("、") || "未声明"}</p><p>覆盖：{(mod.overrides || []).join("、") || "未声明"}</p></details>{item && <div className="mod-form">{Object.entries(item.schema).map(([key, schema]) => <SettingField key={key} name={key} schema={schema} value={values[key]} onChange={value => setValues({ ...values, [key]: value })} />)}<div className="mod-form-actions"><button className="button button-primary" disabled={!dirty || invalid || busy} onClick={() => onSave(item, values)}>保存 Mod 设置</button>{dirty && <button className="button button-quiet" disabled={busy} onClick={() => setValues(item.values)}>撤销修改</button>}{!dirty && <span className="field-state">已同步</span>}{invalid && <span className="field-state field-state-error">请修正设置值</span>}</div></div>}</article>;
}

function SettingField({ name, schema, value, onChange }) {
  const label = schema.label || name;
  if (schema.type === "boolean") return <label className="check-row"><input type="checkbox" checked={Boolean(value)} onChange={event => onChange(event.target.checked)} />{label}</label>;
  if (schema.type === "select") return <label>{label}<select value={value ?? ""} onChange={event => onChange(schema.options?.find(option => String(option.value) === event.target.value)?.value ?? event.target.value)}>{(schema.options || []).map(option => <option key={String(option.value)} value={option.value}>{option.label || option.value}</option>)}</select>{schema.description && <small>{schema.description}</small>}</label>;
  const type = schema.type === "number" || schema.type === "integer" ? "number" : schema.type === "color" ? "color" : schema.type === "text" ? "textarea" : "text";
  return <label>{label}{type === "textarea" ? <textarea rows="3" value={value ?? ""} onChange={event => onChange(event.target.value)} /> : <input type={type} value={value ?? ""} min={schema.min} max={schema.max} step={schema.step} onChange={event => onChange(type === "number" ? Number(event.target.value) : event.target.value)} />}{schema.description && <small>{schema.description}</small>}</label>;
}

function RoomSettings({ snapshot, onNotice }) {
  const [values, setValues] = useState(snapshot?.settings || {});
  const [uses, setUses] = useState(1);
  useEffect(() => setValues(snapshot?.settings || {}), [snapshot?.settings]);
  const save = async event => { event.preventDefault(); try { await jsonRequest("/api/admin/settings", { allow_free_actions: values.allow_free_actions, history_rounds: values.history_rounds ? Number(values.history_rounds) : null, history_seconds: values.history_seconds ? Number(values.history_seconds) : null }); onNotice("房间设置已保存"); } catch (error) { onNotice(error.message, true); } };
  const addUses = async event => { event.preventDefault(); try { await jsonRequest("/api/admin/access", { additional_uses: Number(uses) }); onNotice(`已增加 ${uses} 次主持人加入机会`); } catch (error) { onNotice(error.message, true); } };
  return <div className="settings-content"><SettingsSection title="行动权限"><label className="check-row"><input type="checkbox" checked={Boolean(values.allow_free_actions)} onChange={event => setValues({ ...values, allow_free_actions: event.target.checked })} />允许 Agent 绕过主持人回合行动</label></SettingsSection><SettingsSection title="事件历史窗口"><p className="subtle">超过回合数或时间的事件会从实时板块隐藏，原始存档不受影响。</p><div className="settings-grid"><label>保留回合数<input type="number" min="1" placeholder="不过期" value={values.history_rounds ?? ""} onChange={event => setValues({ ...values, history_rounds: event.target.value })} /></label><label>保留分钟数<input type="number" min="1" placeholder="不过期" value={values.history_seconds ? Math.ceil(values.history_seconds / 60) : ""} onChange={event => setValues({ ...values, history_seconds: event.target.value ? Number(event.target.value) * 60 : "" })} /></label></div></SettingsSection><button className="button button-primary button-wide" onClick={save}>保存房间设置</button><SettingsSection title="主持人加入次数"><p className="subtle">当前服务的额外加入机会仅由已登录主持人增加。</p><form onSubmit={addUses}><div className="settings-grid"><label>增加次数<input type="number" min="1" max="1000" value={uses} onChange={event => setUses(event.target.value)} /></label><div /></div><button className="button button-quiet button-wide">增加可加入次数</button></form></SettingsSection></div>;
}

createRoot(document.getElementById("root")).render(<App />);
