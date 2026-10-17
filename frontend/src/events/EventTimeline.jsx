import { useEffect, useMemo, useRef, useState } from "react";
import { categoryOf, describeEvent, EVENT_CATEGORIES, filterEvents, scopeLabel } from "./eventModel.js";

const PAGE_SIZE = 80;

export function EventTimeline({ snapshot, display, setDisplay, presenter }) {
  const events = useMemo(() => filterEvents(snapshot?.events || [], display), [snapshot?.events, display]);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const scrollRef = useRef(null);
  useEffect(() => setLimit(PAGE_SIZE), [display.categories, display.scopes, display.seat, display.query]);
  useEffect(() => { if (display.autoScroll && scrollRef.current) scrollRef.current.scrollTop = 0; }, [events.length, display.autoScroll]);
  const seats = Object.values(snapshot?.seats || {});
  const visible = events.slice(-limit).reverse();
  return <div className="timeline-view">
    <div className="feed-toolbar"><div className="search-box"><span aria-hidden="true">⌕</span><label className="sr-only" htmlFor="event-query">搜索事件</label><input id="event-query" value={display.query} onChange={event => setDisplay({ ...display, query: event.target.value })} placeholder="搜索事件、发言或笔记…" /></div><label className="sr-only" htmlFor="event-seat-filter">筛选席位</label><select id="event-seat-filter" value={display.seat} onChange={event => setDisplay({ ...display, seat: event.target.value })}><option value="">全部席位</option>{seats.map(seat => <option key={seat.seat_id} value={seat.seat_id}>{seat.seat_id} 号 · {seat.name}</option>)}</select><span className="event-count" aria-live="polite">{events.length} 条</span><label className="toggle-label"><input type="checkbox" checked={display.autoScroll} onChange={event => setDisplay({ ...display, autoScroll: event.target.checked })} />跟随最新</label></div>
    <div className="timeline" ref={scrollRef} aria-live="polite">{visible.length ? <>{events.length > limit && <button className="button button-quiet button-wide" onClick={() => setLimit(value => value + PAGE_SIZE)}>加载更早事件（{events.length - limit}）</button>}{visible.map(event => <EventItem event={event} presenter={presenter} key={event.seq} />)}</> : <div className="empty-state"><span aria-hidden="true">◌</span><strong>暂无匹配事件</strong><p>新的行动、消息和笔记会出现在这里。</p></div>}</div>
  </div>;
}

export function EventItem({ event, presenter }) {
  const [rawOpen, setRawOpen] = useState(false);
  const description = describeEvent(event, presenter);
  const category = categoryOf(event);
  const actor = event.from_seat ?? event.data?.seat ?? event.to_seat;
  return <article className={`event-item event-${category}`}><div className="event-avatar" aria-hidden="true">{actor ?? (category === "memory" ? "记" : "A")}</div><div className="event-content"><div className="event-head"><div><strong>{description.title}</strong><div className="event-meta"><span>{EVENT_CATEGORIES[category]}</span><span>{scopeLabel(event.scope, event.to_seat)}</span><span>#{event.seq}</span></div></div><time dateTime={event.timestamp ? new Date(event.timestamp * 1000).toISOString() : undefined}>{event.timestamp ? new Date(event.timestamp * 1000).toLocaleTimeString([], { hour12: false }) : "--:--:--"}</time></div>{description.text && <p className="event-text">{description.text}</p>}{category === "memory" && event.data?.text && <details className="memory-preview"><summary>本次 memory.md 写入</summary><pre>{event.data.text}</pre></details>}<details className="raw-detail" open={rawOpen} onToggle={item => setRawOpen(item.currentTarget.open)}><summary>原始详情</summary>{rawOpen && <pre>{JSON.stringify(event, null, 2)}</pre>}</details></div></article>;
}
