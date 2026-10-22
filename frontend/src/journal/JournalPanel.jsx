import { useLayoutEffect, useRef, useState } from "react";
import { Avatar } from "../avatars/Avatar.jsx";
import { ThoughtBubble } from "./ThoughtBubble.jsx";
import { projectJournal } from "./journalModel.js";

export function JournalPanel({ snapshot, expanded = false, onExpand }) {
  const [view, setView] = useState(expanded ? "history" : "current");
  const [selected, setSelected] = useState("");
  const historyRef = useRef(null);
  const followRef = useRef(true);
  const [limit, setLimit] = useState(60);
  const seats = snapshot?.seats || {};
  const seatIds = snapshot?.perspective_seat ? [String(snapshot.perspective_seat)] : Object.keys(seats);
  const seat = seatIds.includes(selected) ? selected : "";
  const ids = seat ? [seat] : seatIds;
  const notes = (snapshot?.events || []).filter(event => event.event_type === "AGENT_NOTE" && ids.includes(String(event.from_seat)));
  const journal = snapshot?.journal || projectJournal(snapshot?.events);
  const memories = ids.flatMap(id => journal.remembered[id] || []).sort((a, b) => a.seq - b.seq);
  const replay = snapshot?.replay_cursor !== undefined;
  useLayoutEffect(() => {
    if (historyRef.current && followRef.current) historyRef.current.scrollTop = historyRef.current.scrollHeight;
  }, [notes.at(-1)?.seq, view, seat, limit]);

  return <section className={`journal-panel ${expanded ? "is-expanded" : ""}`} aria-label="心路历程">
    <header className="journal-heading"><div><h3>心路历程</h3><p>{replay ? snapshot.replay_time ? `复盘至 ${new Date(snapshot.replay_time * 1000).toLocaleTimeString([], { hour12: false })}` : "复盘起点" : "Agent 当时写下的想法"}</p></div>{onExpand && <button type="button" className="text-button" onClick={onExpand}>展开</button>}</header>
    <div className="journal-controls"><nav aria-label="历程视图">{[["current", "此刻"], ["history", "历程"], ["memory", "记忆"]].map(([id, label]) => <button type="button" key={id} aria-pressed={view === id} onClick={() => { followRef.current = true; setView(id); }}>{label}</button>)}</nav><label className="sr-only" htmlFor={expanded ? "journal-seat-main" : "journal-seat-rail"}>观察 Agent</label><select id={expanded ? "journal-seat-main" : "journal-seat-rail"} value={seat} onChange={event => { followRef.current = true; setSelected(event.target.value); }}><option value="">全部 Agent</option>{seatIds.map(id => <option key={id} value={id}>{seats[id].name}</option>)}</select></div>
    {view === "current" && <div className="journal-agents">{ids.map(id => <section className="journal-agent" key={id}><header><Avatar seat={seats[id]} presets={snapshot?.model_avatars} size={40} /><div><strong>{seats[id].name}</strong><span>{replay ? "复盘" : snapshot?.active_actions?.[id] ? "有待办行动" : seats[id].connection_status === "LISTENING" ? "在线监听" : "等待连接"}</span></div></header>{journal.latest[id] ? <ThoughtBubble event={journal.latest[id]} snapshot={snapshot} compact /> : <p className="journal-empty">尚未收到即时自述</p>}</section>)}</div>}
    {view === "history" && <div className="journal-history" ref={historyRef} onScroll={event => { const el = event.currentTarget; followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48; }}>
      {notes.length > limit && <button type="button" className="text-button" onClick={() => setLimit(value => value + 60)}>展开更早自述</button>}{notes.slice(-limit).map(event => <ThoughtBubble event={event} snapshot={snapshot} key={event.seq} />)}{!notes.length && <p className="journal-empty">新的想法会带着时间戳出现在这里。</p>}
    </div>}
    {view === "memory" && <div className="journal-memory">{memories.map(event => <ThoughtBubble event={event} snapshot={snapshot} key={event.seq} />)}{!memories.length && <p className="journal-empty">Agent 标记保留的自述会出现在这里。</p>}</div>}
    {ids.some(id => snapshot?.memories?.[id]) && <details className="journal-documents"><summary>文档记录 · memory.md</summary>{ids.filter(id => snapshot.memories[id]).map(id => <section key={id}><h4>{seats[id].name} · 文档快照</h4><pre>{snapshot.memories[id].text}</pre></section>)}</details>}
  </section>;
}
