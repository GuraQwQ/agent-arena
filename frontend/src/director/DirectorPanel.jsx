import { useState } from "react";
import { arenaApi } from "../api/arenaClient.js";
import { ACTION_NAMES } from "../events/eventModel.js";
import "./director.css";

export function DirectorPanel({ snapshot, onNotice, onClose }) {
  const seats = Object.values(snapshot?.seats || {});
  const [phase, setPhase] = useState(snapshot?.phase || "");
  const [round, setRound] = useState(snapshot?.round_num || 1);
  const [target, setTarget] = useState("");
  const [action, setAction] = useState("SPEAK");
  const [prompt, setPrompt] = useState("");
  const [timeout, setTimeoutValue] = useState(60);
  const [options, setOptions] = useState("");
  const [minimum, setMinimum] = useState("");
  const [maximum, setMaximum] = useState("");
  const [scope, setScope] = useState("PUBLIC");
  const [recipient, setRecipient] = useState("");
  const [group, setGroup] = useState("");
  const [busy, setBusy] = useState(false);
  const selected = seats.find(seat => String(seat.seat_id) === target) || seats[0];
  const pending = snapshot?.active_actions?.[selected?.seat_id];

  const sendPhase = async event => {
    event.preventDefault();
    setBusy(true);
    try {
      await arenaApi.command({ command_type: "ADVANCE_PHASE", phase, round_num: Number(round) });
      onNotice("场景阶段已变更");
    } catch (error) { onNotice(error.message, true); }
    finally { setBusy(false); }
  };
  const dispatch = async event => {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    try {
      await arenaApi.command({ command_type: "DISPATCH_ACTION", target_seat: selected.seat_id,
        action_type: action, prompt: prompt || "请依据当前局势独立做出行动。",
        timeout: Number(timeout), result_scope: scope,
        options: ["VOTE", "CHOOSE"].includes(action) ? options.split("\n").map(item => item.trim()).filter(Boolean) : [],
        min_value: action === "NUMBER" && minimum !== "" ? Number(minimum) : null,
        max_value: action === "NUMBER" && maximum !== "" ? Number(maximum) : null,
        result_target_seat: scope === "PRIVATE" ? Number(recipient) : null,
        result_group_id: scope === "GROUP" ? group : null });
      onNotice(`已向 ${selected.seat_id} 号位发出${ACTION_NAMES[action]}指令`);
    } catch (error) { onNotice(error.message, true); }
    finally { setBusy(false); }
  };

  return <section className="director-panel" aria-label="主持调度面板">
    <header className="director-heading"><div><h3>主持调度</h3><p>{snapshot?.phase} · 第 {snapshot?.round_num || 1} 回合</p></div><button type="button" className="icon-button" aria-label="收起主持调度" onClick={onClose}><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg></button></header>
    <section className="director-section"><h4>推进阶段</h4><form onSubmit={sendPhase}>
      <label htmlFor="director-phase">新阶段名称</label><input id="director-phase" value={phase} onChange={event => setPhase(event.target.value)} placeholder="例如：交锋回应" required />
      <label htmlFor="director-round">回合</label><input id="director-round" type="number" min="1" value={round} onChange={event => setRound(event.target.value)} required />
      <button className="button button-quiet button-wide" disabled={busy}>变更阶段</button>
    </form></section>
    <section className="director-section"><h4>点名玩家行动</h4><form onSubmit={dispatch}>
      <label htmlFor="director-target">目标席位</label><select id="director-target" value={selected?.seat_id || ""} onChange={event => setTarget(event.target.value)} required><option value="" disabled>选择席位</option>{seats.map(seat => <option key={seat.seat_id} value={seat.seat_id}>{seat.seat_id} 号位 · {seat.name}</option>)}</select>
      <label htmlFor="director-action">行动类型</label><select id="director-action" value={action} onChange={event => setAction(event.target.value)}>{Object.entries(ACTION_NAMES).map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select>
      <label htmlFor="director-prompt">行动指引</label><textarea id="director-prompt" rows="4" value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="为当前阶段给出清楚的行动目标。" />
      {["VOTE", "CHOOSE"].includes(action) && <><label htmlFor="director-options">候选项（每行一项）</label><textarea id="director-options" required value={options} onChange={event => setOptions(event.target.value)} /></>}
      {action === "NUMBER" && <><label htmlFor="director-min">最小值</label><input id="director-min" type="number" step="any" value={minimum} onChange={event => setMinimum(event.target.value)} /><label htmlFor="director-max">最大值</label><input id="director-max" type="number" step="any" min={minimum === "" ? undefined : minimum} value={maximum} onChange={event => setMaximum(event.target.value)} /></>}
      <label htmlFor="director-scope">结果可见范围</label><select id="director-scope" value={scope} onChange={event => setScope(event.target.value)}><option value="PUBLIC">全员公开</option><option value="HOST_ONLY">仅主持人</option><option value="PRIVATE">指定席位</option><option value="GROUP">指定阵营</option></select>
      {scope === "PRIVATE" && <><label htmlFor="director-recipient">接收席位</label><select id="director-recipient" required value={recipient} onChange={event => setRecipient(event.target.value)}><option value="">选择席位</option>{seats.map(seat => <option key={seat.seat_id} value={seat.seat_id}>{seat.name}</option>)}</select></>}
      {scope === "GROUP" && <><label htmlFor="director-group">接收阵营</label><select id="director-group" required value={group} onChange={event => setGroup(event.target.value)}><option value="">选择阵营</option>{[...new Set(seats.map(seat => seat.group_id).filter(Boolean))].map(id => <option key={id}>{id}</option>)}</select></>}
      <label htmlFor="director-timeout">限时（秒）</label><input id="director-timeout" type="number" min="10" max="300" value={timeout} onChange={event => setTimeoutValue(event.target.value)} required />
      {pending && <p className="director-pending">{selected.name} 正在等待本次{ACTION_NAMES[pending.action_type] || "行动"}提交</p>}
      <button className="button button-primary button-wide" disabled={busy || !selected || Boolean(pending)}>{busy ? "正在发送…" : "发出行动指令"}</button>
    </form></section>
  </section>;
}
