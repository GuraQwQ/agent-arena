import { Avatar } from "../avatars/Avatar.jsx";
import "./journal.css";

export function ThoughtBubble({ event, snapshot, compact = false }) {
  const data = event.data || {};
  const seat = data.author || snapshot?.seats?.[event.from_seat];
  const stamp = new Date(event.timestamp * 1000);
  return <article className={`thought-item ${compact ? "is-compact" : ""}`} data-event-seq={event.seq}>
    {!compact && <Avatar seat={seat} presets={snapshot?.model_avatars} fallback={event.from_seat} className="thought-avatar" size={44} />}
    <div className="thought-message">
      <header className="thought-heading">{(!compact || seat?.name !== snapshot?.seats?.[event.from_seat]?.name) && <strong>{seat?.name || `${event.from_seat} 号位`}</strong>}<time dateTime={stamp.toISOString()} title={`记录于 ${stamp.toLocaleString()}`}>{stamp.toLocaleTimeString([], { hour12: false })}</time></header>
      <div className="thought-body"><p>{event.content}</p></div>
      <footer className="thought-meta"><span>{data.timing === "after_action" ? "行动后补充" : "即时自述"}</span><span>#{event.seq}</span>{data.remember && <span>记忆写入</span>}{data.revises_seq && <span>修正 #{data.revises_seq}</span>}{data.related_seq && <span>关联 #{data.related_seq}</span>}</footer>
      <details className="thought-origin"><summary>记录来源</summary><p>{data.channel === "native" ? "原生工作台自述" : "Agent 自述入口"} · {data.note_id}</p>{data.created_at && <p>发送端时间：{new Date(data.created_at * 1000).toLocaleString()}</p>}<p>服务记录时间：{stamp.toLocaleString()}</p>{data.request_id && <p>关联行动：{data.request_id}</p>}</details>
    </div>
  </article>;
}
