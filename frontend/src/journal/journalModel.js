export function projectJournal(events = []) {
  const latest = {};
  const remembered = {};
  for (const event of events) {
    if (event.event_type !== "AGENT_NOTE") continue;
    const seat = event.from_seat;
    latest[seat] = event;
    const memory = remembered[seat] ||= {};
    delete memory[event.data?.revises_seq];
    if (event.data?.remember) memory[event.seq] = event;
  }
  return { latest, remembered: Object.fromEntries(Object.entries(remembered).map(([seat, items]) => [seat, Object.values(items)])) };
}

export function replayFrame(snapshot, position) {
  if (!snapshot) return null;
  const events = (snapshot.events || []).slice(0, position);
  const memories = {};
  for (const event of events) if (event.event_type === "MEMORY_UPDATE") {
    memories[event.from_seat] = { ...event.data, observed_at: event.timestamp };
  }
  return { ...snapshot, events, memories, journal: projectJournal(events), active_actions: {},
    round_num: events.at(-1)?.round_num || 1, replay_cursor: position, replay_time: events.at(-1)?.timestamp };
}
