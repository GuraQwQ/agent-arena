import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { arenaApi } from "../api/arenaClient.js";
import { EventItem } from "../events/EventTimeline.jsx";
import { replayFrame } from "../journal/journalModel.js";

export function ReplayView({ onNotice, onFrame }) {
  const [archives, setArchives] = useState([]);
  const [selected, setSelected] = useState("");
  const [replay, setReplay] = useState(null);
  const [position, setPosition] = useState(0);
  const [modReport, setModReport] = useState(null);
  const [restoring, setRestoring] = useState(false);
  const [confirmRestore, setConfirmRestore] = useState(false);
  const scrollRef = useRef(null);
  const selectionRef = useRef("");
  const frame = useMemo(() => replayFrame(replay, position), [replay, position]);
  useEffect(() => { onFrame(frame); }, [frame, onFrame]);
  useEffect(() => () => onFrame(null), [onFrame]);
  const refresh = useCallback(() => arenaApi.archives().then(data => setArchives(data.archives || [])).catch(error => onNotice(error.message, true)), [onNotice]);
  useEffect(() => { refresh(); }, [refresh]);
  useLayoutEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [position]);
  const load = async value => {
    selectionRef.current = value;
    setSelected(value);
    setPosition(0);
    setReplay(null);
    setModReport(null);
    setConfirmRestore(false);
    if (!value) return;
    try {
      const [data, mods] = await Promise.all([arenaApi.archive(value), arenaApi.archiveMods(value)]);
      if (selectionRef.current === value) { setReplay(data); setModReport(mods); }
    } catch (error) { if (selectionRef.current === value) onNotice(error.message, true); }
  };
  const save = async () => {
    try { await arenaApi.saveArchive(); onNotice("当前对局已保存"); await refresh(); }
    catch (error) { onNotice(error.message, true); }
  };
  const events = replay?.events || [];
  const restore = async () => {
    setRestoring(true);
    try { await arenaApi.restoreArchive(selected); setConfirmRestore(false); onNotice("存档已恢复，请重新接入玩家后继续"); }
    catch (error) { onNotice(error.message, true); }
    finally { setRestoring(false); }
  };

  return <div className="replay-view">
    <div className="replay-toolbar"><div className="replay-selection"><label htmlFor="replay-archive">选择对局存档</label><select id="replay-archive" value={selected} onChange={event => load(event.target.value)}><option value="">选择存档</option>{archives.map(item => <option key={item.room_id} value={item.room_id}>{item.title} · {item.event_count} 条事件</option>)}</select></div><button className="button button-quiet" onClick={refresh}>刷新</button><button className="button button-quiet" onClick={save}>保存当前局</button></div>
    {replay ? <>
      <details className="archive-mods"><summary>存档 Mod · {modReport?.valid ? "可恢复" : "需要处理"}</summary><p>{modReport?.required?.map(mod => `${mod.id} ${mod.version}`).join("、") || "核心规则"}</p>{modReport?.issues?.map((issue, index) => <p className={`issue ${issue.severity}`} key={index}>{issue.message}</p>)}<button className="button button-quiet" disabled={!modReport?.valid || restoring} onClick={() => setConfirmRestore(true)}>恢复此存档</button>{confirmRestore && <div className="director-confirm"><p>当前局将自动备份，恢复后玩家需要重新接入，运行中的游戏将暂停。</p><button className="button button-primary" disabled={restoring} onClick={restore}>确认恢复</button><button className="button button-quiet" disabled={restoring} onClick={() => setConfirmRestore(false)}>取消</button></div>}</details>
      <div className="replay-progress"><label htmlFor="replay-position">事件 {position} / {events.length}</label><input id="replay-position" type="range" min="0" max={events.length} value={position} onChange={event => setPosition(Number(event.target.value))} /></div>
      <div className="replay-events" ref={scrollRef}>{events.slice(0, position).slice(-12).map(event => <EventItem event={event} snapshot={replay} key={event.seq} />)}{!position && <div className="empty-state"><span aria-hidden="true">◷</span><strong>拖动时间线开始复盘</strong></div>}</div>
    </> : <div className="empty-state"><span aria-hidden="true">◷</span><strong>{archives.length ? "选择一个存档开始复盘" : "暂无对局存档"}</strong><p>实时事件会按主持人视角重新展开。</p></div>}
  </div>;
}
