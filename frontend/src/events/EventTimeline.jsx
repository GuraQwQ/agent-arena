import { useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { categoryOf, describeEvent, EVENT_CATEGORIES, filterEvents, scopeLabel } from "./eventModel.js";

import { Avatar } from "../avatars/Avatar.jsx";

const PAGE_SIZE = 80;

export function EventTimeline({ snapshot, display, setDisplay, presenter }) {
  const query = useDeferredValue(display.query);
  const filterDisplay = useMemo(() => ({ ...display, query }), [display, query]);
  const events = useMemo(() => filterEvents(snapshot?.events || [], filterDisplay), [snapshot?.events, filterDisplay]);
  const [startSeq, setStartSeq] = useState(null);
  const scrollRef = useRef(null);
  const historyAnchor = useRef(null);
  const visible = !display.autoScroll && startSeq !== null ? events.filter(event => event.seq >= startSeq) : events.slice(-PAGE_SIZE);
  const earlierCount = events.length - visible.length;
  useEffect(() => setStartSeq(null), [display.categories, display.scopes, display.seat, display.query]);
  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    if (historyAnchor.current) {
      const { height, top } = historyAnchor.current;
      element.scrollTop = top + element.scrollHeight - height;
      historyAnchor.current = null;
    } else if (display.autoScroll) element.scrollTop = element.scrollHeight;
    if (!display.autoScroll && startSeq === null && visible.length) setStartSeq(visible[0].seq);
  }, [events, display.autoScroll, startSeq]);
  const loadEarlier = () => {
    const element = scrollRef.current;
    if (element) historyAnchor.current = { height: element.scrollHeight, top: element.scrollTop };
    setDisplay(previous => ({ ...previous, autoScroll: false }));
    setStartSeq(events[Math.max(0, earlierCount - PAGE_SIZE)]?.seq ?? null);
  };
  const trackScroll = event => {
    const element = event.currentTarget;
    if (display.autoScroll && element.scrollHeight - element.scrollTop - element.clientHeight > 64) {
      setStartSeq(visible[0]?.seq ?? null);
      setDisplay(previous => ({ ...previous, autoScroll: false }));
    }
  };
  const seats = Object.values(snapshot?.seats || {});
  return <div className="timeline-view">
    <div className="feed-toolbar"><div className="search-box"><span aria-hidden="true">⌕</span><label className="sr-only" htmlFor="event-query">搜索事件</label><input id="event-query" value={display.query} onChange={event => setDisplay({ ...display, query: event.target.value })} placeholder="搜索事件、发言或笔记…" /></div><label className="sr-only" htmlFor="event-seat-filter">筛选席位</label><select id="event-seat-filter" value={display.seat} onChange={event => setDisplay({ ...display, seat: event.target.value })}><option value="">全部席位</option>{seats.map(seat => <option key={seat.seat_id} value={seat.seat_id}>{seat.seat_id} 号 · {seat.name}</option>)}</select><span className="event-count" aria-live="polite">{events.length} 条</span><label className="toggle-label"><input type="checkbox" checked={display.autoScroll} onChange={event => setDisplay({ ...display, autoScroll: event.target.checked })} />跟随最新</label></div>
    <div className="timeline" ref={scrollRef} onScroll={trackScroll} aria-live="polite" aria-busy={query !== display.query}>{visible.length ? <>{earlierCount > 0 && <button className="button button-quiet button-wide" onClick={loadEarlier}>加载更早事件（{earlierCount}）</button>}{visible.map(event => <EventItem event={event} snapshot={snapshot} presenter={presenter} key={event.seq} />)}</> : <div className="empty-state"><span aria-hidden="true">◌</span><strong>暂无匹配事件</strong><p>新的行动、消息和笔记会出现在这里。</p></div>}</div>
    {!display.autoScroll && events.length > 0 && <button type="button" className="button button-primary timeline-latest" onClick={() => setDisplay(previous => ({ ...previous, autoScroll: true }))}>回到最新消息</button>}
  </div>;
}

export function EventItem({ event, presenter, snapshot }) {
  const [rawOpen, setRawOpen] = useState(false);
  const description = describeEvent(event, presenter);
  const category = categoryOf(event);
  const actor = event.from_seat ?? event.data?.seat ?? event.to_seat;
  return <article className={`event-item event-${category}`}><Avatar seat={snapshot?.seats?.[actor]} presets={snapshot?.model_avatars} fallback={actor ?? (category === "memory" ? "记" : "A")} className="event-avatar" /><div className="event-content"><div className="event-head"><div><strong>{description.title}</strong><div className="event-meta"><span>{EVENT_CATEGORIES[category]}</span><span>{scopeLabel(event.scope, event.to_seat)}</span><span>#{event.seq}</span></div></div><time dateTime={event.timestamp ? new Date(event.timestamp * 1000).toISOString() : undefined}>{event.timestamp ? new Date(event.timestamp * 1000).toLocaleTimeString([], { hour12: false }) : "--:--:--"}</time></div>{description.text && <p className="event-text">{description.text}</p>}{category === "memory" && event.data?.text && <details className="memory-preview"><summary>本次 memory.md 写入</summary><pre>{event.data.text}</pre></details>}<details className="raw-detail" open={rawOpen} onToggle={item => setRawOpen(item.currentTarget.open)}><summary>原始详情</summary>{rawOpen && <pre>{JSON.stringify(event, null, 2)}</pre>}</details></div></article>;
}
