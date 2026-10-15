"""对局完整存档与按发送时视野过滤的复盘导出。"""

import copy
import json
import os
import tempfile
import time
from math import isfinite
from pathlib import Path
from uuid import UUID


class ArchiveStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, room_id: str) -> Path:
        try:
            if not isinstance(room_id, str):
                raise ValueError("对局编号必须是 UUID")
            normalized = UUID(room_id).hex
        except (ValueError, AttributeError) as exc:
            raise ValueError("对局编号必须是 UUID") from exc
        return self.root / f"{normalized}.json"

    @staticmethod
    def _validate(snapshot: dict) -> dict:
        if not isinstance(snapshot, dict):
            raise ValueError("存档内容必须是对象")
        seats = snapshot.get("seats")
        events = snapshot.get("events")
        if not isinstance(seats, dict) or not all(isinstance(s, dict) for s in seats.values()):
            raise ValueError("存档席位格式无效")
        if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
            raise ValueError("存档事件格式无效")
        archived_at = snapshot.get("archived_at", 0)
        if not isinstance(archived_at, (int, float)) or not isfinite(archived_at):
            raise ValueError("存档时间格式无效")
        for event in events:
            recipients = event.get("recipient_seats")
            if recipients is not None and (
                not isinstance(recipients, list) or not all(isinstance(s, int) for s in recipients)
            ):
                raise ValueError("事件接收席位格式无效")
        return snapshot

    def save(self, snapshot: dict) -> str:
        self._validate(snapshot)
        path = self._path(snapshot.get("room_id"))
        saved = copy.deepcopy(snapshot)
        saved.update(room_id=path.stem, archived_at=time.time())
        content = json.dumps(saved, ensure_ascii=False, indent=2, allow_nan=False)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.root,
                prefix=f".{path.stem}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return path.stem

    def read(self, room_id: str) -> dict:
        path = self._path(room_id)
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"存档 {path.stem} 无法读取：{exc}") from exc
        self._validate(snapshot)
        if self._path(snapshot.get("room_id")) != path:
            raise ValueError("存档编号与文件名不一致")
        return snapshot

    def list(self) -> list[dict]:
        result = []
        for path in self.root.glob("*.json"):
            try:
                if self._path(path.stem) != path:
                    continue
            except ValueError:
                continue
            try:
                snapshot = self.read(path.stem)
                result.append({
                    "room_id": path.stem,
                    "title": snapshot.get("room_title", path.stem),
                    "phase": snapshot.get("phase", ""),
                    "round_num": snapshot.get("round_num", 1),
                    "event_count": len(snapshot["events"]),
                    "archived_at": snapshot.get("archived_at", 0),
                })
            except (ValueError, OSError) as exc:
                result.append({"room_id": path.stem, "title": path.stem, "error": str(exc)})
        return sorted(result, key=lambda row: row.get("archived_at", 0), reverse=True)

    def export(self, room_id: str, seat_id: int | None = None) -> dict:
        snapshot = self.read(room_id)
        seats = snapshot["seats"]
        if seat_id is not None and str(seat_id) not in seats:
            raise ValueError("存档中不存在该席位")
        exported = {key: snapshot[key] for key in (
            "schema_version", "room_id", "room_title", "phase", "round_num",
            "archived_at", "settings", "scenario_description",
        ) if key in snapshot}
        exported["seats"] = {
            key: {name: value for name, value in seat.items() if name not in {"token", "claim_token"}}
            for key, seat in seats.items() if seat_id is None or key == str(seat_id)
        }
        exported["events"] = []
        for event in snapshot["events"]:
            scope = event.get("scope")
            if seat_id is not None:
                if scope == "HOST_ONLY":
                    continue
                if scope != "PUBLIC" and seat_id not in (event.get("recipient_seats") or []):
                    continue
            item = dict(event)
            if seat_id is not None:
                item["secret_reason"] = None
            exported["events"].append(item)
        return exported
