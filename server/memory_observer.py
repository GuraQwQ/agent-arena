"""观察主持人登记的本机工作目录，将记忆变化保存为主持人事件。"""

import difflib
import time
from pathlib import Path

from models import VisibilityScope


def memory_snapshots(events, previous=None):
    result = dict(previous or {})
    for event in events:
        if event.event_type == "MEMORY_UPDATE" and event.from_seat is not None:
            result[event.from_seat] = {**(event.data or {}), "seq": event.seq, "round_num": event.round_num,
                                       "observed_at": event.timestamp, "seat_id": event.from_seat}
    return result


class MemoryObserver:
    def __init__(self, room):
        self.room = room
        self.room_id = None
        self._fingerprints = {}
        self._pending = {}

    def tick(self):
        if self.room_id != self.room.room_id:
            self.room_id = self.room.room_id
            self._fingerprints.clear()
            self._pending.clear()
        previous = self.room.history_projections()["memories"]
        old_status = self.room.memory_status
        statuses = {}
        for seat_id, directory in self.room.workspace_paths.items():
            path = Path(directory) / "memory.md"
            try:
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    stat = None
                fingerprint = (str(path), stat.st_mtime_ns, stat.st_size) if stat else (str(path), None, None)
                statuses[seat_id] = {"state": "READY" if stat else "WAITING", "path": str(path)}
                if self._fingerprints.get(seat_id) == fingerprint:
                    continue
                now = time.monotonic()
                pending = self._pending.get(seat_id)
                if pending is None or pending[0] != fingerprint:
                    self._pending[seat_id] = (fingerprint, now)
                    continue
                if now - pending[1] < 0.25:
                    continue
                text = path.read_text(encoding="utf-8-sig") if stat else ""
                if stat and (path.stat().st_mtime_ns, path.stat().st_size) != fingerprint[1:]:
                    continue
                old = previous.get(seat_id)
                if old and old.get("path") != str(path):
                    old = None
                exists = stat is not None
                if old is None and not exists or old is not None and text == old.get("text", "") and exists == old.get("exists", True):
                    self._fingerprints[seat_id] = fingerprint
                    continue
                baseline = old is None
                old_text = old.get("text", "") if old else ""
                changes = [{"kind": {"+ ": "added", "- ": "removed", "  ": "same"}[line[:2]], "text": line[2:]}
                           for line in difflib.ndiff(old_text.splitlines(), text.splitlines()) if line[:2] in {"+ ", "- ", "  "}]
                if baseline:
                    changes = [{"kind": "same", "text": line} for line in text.splitlines()]
                data = {"text": text, "exists": exists, "baseline": baseline, "changes": changes, "path": str(path),
                        "revision": old.get("revision", 0) + 1 if old else 1,
                        "written_at": stat.st_mtime if stat else time.time(),
                        "request_id": self.room.active_actions[seat_id].request_id if seat_id in self.room.active_actions else None}
                self.room.record_event("MEMORY_UPDATE", f"【记忆更新】{seat_id}号位",
                    "首次采集记忆" if baseline else "记忆文件已更新" if exists else "记忆文件已移除",
                    from_seat=seat_id, scope=VisibilityScope.HOST_ONLY, data=data)
                self._fingerprints[seat_id] = fingerprint
            except (OSError, UnicodeError) as exc:
                statuses[seat_id] = {"state": "ERROR", "path": str(path), "error": str(exc)}
        self.room.memory_status = statuses
        if statuses != old_status:
            self.room.broadcast_host_update()
