import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { arenaApi } from "../api/arenaClient.js";
import { EventItem } from "../events/EventTimeline.jsx";

export function ReplayView({ onNotice }) {
  const [archives, setArchives] = useState([]);
  const [selected, setSelected] = useState("");
  const [replay, setReplay] = useState(null);
  const [position, setPosition] = useState(0);
  const scrollRef = useRef(null);
  const selectionRef = useRef("");
  const refresh = useCallback(() => arenaApi.archives().then(data => setArchives(data.archives || [])).catch(error => onNotice(error.message, true)), [onNotice]);
  useEffect(() => { refresh(); }, [refresh]);
  useLayoutEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [position]);
  const load = async value => {
    selectionRef.current = value;
    setSelected(value);
    setPosition(0);
    setReplay(null);
    if (!value) return;
    try {
      const data = await arenaApi.archive(value);
      if (selectionRef.current === value) setReplay(data);
    } catch (error) { if (selectionRef.current === value) onNotice(error.message, true); }
  };
  const save = async () => {
    try { await arenaApi.saveArchive(); onNotice("当前对局已保存"); await refresh(); }
    catch (error) { onNotice(error.message, true); }
  };
  const events = replay?.events || [];

  return <div className="replay-view">
    <div className="replay-toolbar"><div className="replay-selection"><label htmlFor="replay-archive">选择对局存档</label><select id="replay-archive" value={selected} onChange={event => load(event.target.value)}><option value="">选择存档</option>{archives.map(item => <option key={item.room_id} value={item.room_id}>{item.title} · {item.event_count} 条事件</option>)}</select></div><button className="button button-quiet" onClick={refresh}>刷新</button><button className="button button-quiet" onClick={save}>保存当前局</button></div>
    {replay ? <>
      <div className="replay-progress"><label htmlFor="replay-position">事件 {position} / {events.length}</label><input id="replay-position" type="range" min="0" max={events.length} value={position} onChange={event => setPosition(Number(event.target.value))} /></div>
      <div className="replay-events" ref={scrollRef}>{events.slice(0, position).slice(-12).map(event => <EventItem event={event} snapshot={replay} key={event.seq} />)}{!position && <div className="empty-state"><span aria-hidden="true">◷</span><strong>拖动时间线开始复盘</strong></div>}</div>
    </> : <div className="empty-state"><span aria-hidden="true">◷</span><strong>{archives.length ? "选择一个存档开始复盘" : "暂无对局存档"}</strong><p>实时事件会按主持人视角重新展开。</p></div>}
  </div>;
}
