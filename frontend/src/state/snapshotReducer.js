function expire(snapshot) {
  const { history_rounds: rounds, history_seconds: seconds } = snapshot.settings || {};
  if (!rounds && !seconds) return snapshot;
  const events = snapshot.events.filter(event => (!rounds || event.round_num >= Math.max(1, snapshot.round_num - rounds + 1)) &&
    (!seconds || event.timestamp >= (snapshot.server_time || Date.now() / 1000) - seconds));
  return events.length === snapshot.events.length ? snapshot : { ...snapshot, events };
}

export function applySnapshotMessage(current, message) {
  if (message.type === "SNAPSHOT") return expire({ ...message.data, revision: (current?.revision || 0) + 1 });
  if (!current) return current;
  if (message.type === "EVENT") {
    if (message.room_id !== current.room_id) return current;
    const event = message.data;
    if (event.seq <= (current.seq_counter || 0)) return current;
    let journal = current.journal;
    let memories = current.memories;
    if (event.event_type === "AGENT_NOTE") {
      const previous = journal || { latest: {}, remembered: {} };
      const notes = (previous.remembered[event.from_seat] || []).filter(item => item.seq !== event.data?.revises_seq);
      if (event.data?.remember) notes.push(event);
      journal = { latest: { ...previous.latest, [event.from_seat]: event },
        remembered: { ...previous.remembered, [event.from_seat]: notes } };
    }
    if (event.event_type === "MEMORY_UPDATE") memories = { ...memories, [event.from_seat]: { ...event.data, observed_at: event.timestamp, seq: event.seq } };
    return expire({ ...current, events: [...current.events, event], seq_counter: event.seq, journal, memories });
  }
  if (["STATE", "PRESENCE"].includes(message.type) && message.data.room_id === current.room_id) {
    return expire({ ...current, ...message.data, revision: (current.revision || 0) + (message.type === "STATE" ? 1 : 0) });
  }
  return current;
}
