import { useState } from "react";
import { Avatar } from "../avatars/Avatar.jsx";
import { ACTION_NAMES } from "../events/eventModel.js";
import { memoryChanges } from "./memoryModel.js";
import "./memory.css";

function NoteText({ text }) {
  return <div className="memory-document">{String(text || "").split("\n").map((line, index) => {
    const heading = line.match(/^#{1,6}\s+(.+)$/);
    return heading ? <h5 key={index}>{heading[1]}</h5> : <div className="memory-paragraph" key={index}>{line || <br />}</div>;
  })}</div>;
}

function AgentMemory({ seat, note, status, request, presets }) {
  const [view, setView] = useState("current");
  const changes = memoryChanges(note);
  const added = changes.filter(line => line.kind === "added").length;
  const removed = changes.length - added;
  const runtime = request ? `待${ACTION_NAMES[request.action_type] || "行动"}`
    : seat.connection_status === "LISTENING" ? "在线监听" : seat.connection_status === "RECENT" ? "最近活跃" : "等待连接";
  const written = note?.written_at || note?.observed_at;

  return <article className="memory-card">
    <header><Avatar seat={seat} presets={presets} className="memory-avatar" /><div><strong>{seat.name}</strong><span>{runtime}</span></div><span className="memory-revision">{note ? `第 ${note.revision || 1} 次写入` : "等待笔记"}</span></header>
    {note ? <>
      <p className="memory-time">{written ? new Date(written * 1000).toLocaleString() : ""} · 第 {note.round_num || 1} 回合</p>
      <div className="memory-view-switch"><button type="button" aria-pressed={view === "current"} onClick={() => setView("current")}>当前笔记</button><button type="button" aria-pressed={view === "changes"} onClick={() => setView("changes")}>本次变更{changes.length ? ` +${added} −${removed}` : ""}</button></div>
      {view === "current" ? <div className="memory-note" tabIndex="0" aria-label={`${seat.name} 当前思考与记忆`}><NoteText text={note.text || (note.exists === false ? "记忆文件已移除" : "笔记为空")} /></div>
        : <div className="memory-diff" tabIndex="0" aria-label={`${seat.name} 本次笔记变更`}>{changes.length ? changes.map((line, index) => <div className={`memory-line ${line.kind}`} key={index}><span className="memory-line-number">{line.kind === "added" ? `新 ${line.newLine}` : `旧 ${line.oldLine}`}</span><b aria-label={line.kind === "added" ? "新增" : "删除"}>{line.kind === "added" ? "+" : "−"}</b><span>{line.text}</span></div>) : <p className="subtle">{note.baseline ? "首次采集" : "格式调整"}</p>}</div>}
      {request && <p className="memory-action-state">{note.request_id === request.request_id ? "本次行动的自述已更新" : "当前展示最近一次写入"}</p>}
    </> : <p className="subtle">{status?.path ? "等待 Agent 写下当前判断与行动计划" : "登记工作目录后，显示 Agent 自述笔记"}</p>}
    {status?.state === "ERROR" && <p className="memory-read-error">笔记读取暂未完成：{status.error}</p>}
  </article>;
}

export function MemoryPanel({ snapshot }) {
  const seats = snapshot?.seats || {};
  const seatIds = snapshot?.perspective_seat ? [String(snapshot.perspective_seat)] : Object.keys(seats);
  return <section className="memory-panel" aria-label="思考与记忆">
    <div className="section-heading"><h3>思考与记忆</h3><span className="live-label">实时</span></div>
    <p className="subtle rail-hint">Agent 自述的当前判断、行动计划与记忆。</p>
    <div className="memory-list">{seatIds.map(id => <AgentMemory key={id} seat={seats[id]} note={snapshot?.memories?.[id]} status={snapshot?.memory_status?.[id]} request={snapshot?.active_actions?.[id]} presets={snapshot?.model_avatars} />)}</div>
  </section>;
}
