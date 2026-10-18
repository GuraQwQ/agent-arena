"""事件规范化与运行时观察数据构建。

本模块只负责把现有事件/快照转换为稳定的观察结构，不参与房间状态修改。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
from typing import Any, Iterable, Mapping, Optional


_MESSAGE_TYPES = {"CHAT", "PRIVATE_MESSAGE", "GROUP_MESSAGE", "ANNOUNCEMENT", "SPEECH"}
_RESULT_TYPES = {
    "GAME_EVENT",
    "GAME_START",
    "GAME_STARTED",
    "GAME_CONTROL",
    "GAME_FINISHED",
    "GAME_RESULT",
    "GAME_STATUS",
    "PHASE_CHANGE",
    "FLOW_CONTROL",
    "FLOW_REVEAL",
    "ACTION_CANCEL",
    "ACTION_CANCELLED",
    "ACTION_RESULT",
}
_IMPORTANT_TYPES = {"ACTION_REQUEST", "ACTION_SUBMIT", "GAME_RESULT", "GAME_FINISHED"}


def _mapping(value: Any) -> dict[str, Any]:
    """将 Pydantic 模型、字典或普通对象读取为浅字典。"""
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dict(dump(mode="json"))
        except TypeError:
            return dict(dump())
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise TypeError("观察数据必须是映射或带属性的对象")


def _json_value(value: Any) -> Any:
    """把枚举等模型值变成可 JSON 化的值。"""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return value


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True)
    return str(value)


def _scope(event: Mapping[str, Any]) -> str:
    value = event.get("scope", "PUBLIC")
    return str(value.value if isinstance(value, Enum) else value)


def _category(event_type: str) -> str:
    if event_type == "MEMORY_UPDATE":
        return "memory"
    if event_type in {"ACTION_REQUEST", "ACTION_CANCELLED"}:
        return "requests"
    if event_type == "ACTION_SUBMIT":
        return "submissions"
    if event_type in _MESSAGE_TYPES:
        return "messages"
    if event_type.startswith("GAME") or event_type in _RESULT_TYPES:
        return "results"
    return "system"


def _importance(event: Mapping[str, Any], event_type: str) -> str:
    explicit = event.get("importance")
    payload = event.get("data")
    if explicit is None and isinstance(payload, Mapping):
        explicit = payload.get("importance")
    if explicit is not None:
        return _text(explicit)
    if event_type in {"GAME_FINISHED", "GAME_RESULT"}:
        return "critical"
    if event_type in _IMPORTANT_TYPES:
        return "high"
    if event_type in {"MEMORY_UPDATE", "PHASE_CHANGE"}:
        return "normal"
    return "low" if event_type in {"HEARTBEAT", "PRESENCE"} else "normal"


def _state_delta(event: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    value = event.get("state_delta")
    if value is None:
        value = payload.get("state_delta", {})
    return dict(_json_value(value)) if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class EventEnvelope:
    """供主持人、Agent 和公共观察者共用的事件结构。"""

    seq: Optional[int]
    timestamp: Optional[float]
    round_num: Optional[int]
    event_type: str
    title: str
    content: str
    scope: str
    from_seat: Optional[int]
    to_seat: Optional[int]
    group_id: Optional[str]
    recipient_seats: Optional[list[int]]
    public_text: str
    agent_text: str
    host_text: str
    payload: dict[str, Any]
    importance: str
    category: str
    state_delta: dict[str, Any]
    no_state_changed: bool
    secret_reason: Optional[str] = None
    raw: Optional[dict[str, Any]] = None

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        value = asdict(self)
        value["data"] = value["payload"]
        if not include_raw:
            value.pop("raw", None)
        return _json_value(value)

    def model_dump(self, *, mode: str = "python", include_raw: bool = False, **_: Any) -> dict[str, Any]:
        value = self.to_dict(include_raw=include_raw)
        return _json_value(value) if mode == "json" else value

    def __getitem__(self, key: str) -> Any:
        return self.to_dict(include_raw=True)[key]

    def __iter__(self):
        return iter(self.to_dict(include_raw=True))

    def __len__(self) -> int:
        return len(self.to_dict(include_raw=True))

    def keys(self):
        return self.to_dict(include_raw=True).keys()

    def items(self):
        return self.to_dict(include_raw=True).items()

    def values(self):
        return self.to_dict(include_raw=True).values()

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict(include_raw=True).get(key, default)

    @property
    def data(self) -> dict[str, Any]:
        """旧 Event.data 的兼容别名。"""
        return self.payload


def normalize_event(event: Any, include_raw: bool = False) -> EventEnvelope:
    """规范化旧版 Event，同时统一文本、载荷和状态变化字段。"""
    source = _mapping(event)
    payload_value = source.get("payload", source.get("data", {}))
    payload = dict(_json_value(payload_value)) if isinstance(payload_value, Mapping) else {}
    event_type = _text(source.get("event_type", source.get("type", "SYSTEM")))
    scope = _scope(source)
    content = _text(source.get("content", source.get("text", "")))
    secret_reason = source.get("secret_reason")
    explicit_public = source.get("public_text")
    explicit_agent = source.get("agent_text")
    explicit_host = source.get("host_text")
    public_text = _text(explicit_public) if explicit_public is not None else (content if scope == "PUBLIC" else "")
    agent_text = _text(explicit_agent) if explicit_agent is not None else ("" if scope == "HOST_ONLY" else content)
    host_text = _text(explicit_host) if explicit_host is not None else content
    if explicit_host is None and secret_reason:
        host_text = f"{host_text}\n{_text(secret_reason)}" if host_text else _text(secret_reason)
    delta = _state_delta(source, payload)
    explicit_no_change = source.get("no_state_changed")
    if explicit_no_change is None:
        explicit_no_change = payload.get("no_state_changed")
    no_state_changed = bool(explicit_no_change) if explicit_no_change is not None else not bool(delta)
    raw = _json_value(source) if include_raw else None
    recipients = source.get("recipient_seats")
    return EventEnvelope(
        seq=source.get("seq"),
        timestamp=source.get("timestamp"),
        round_num=source.get("round_num", source.get("round", 1)),
        event_type=event_type,
        title=_text(source.get("title", event_type)),
        content=content,
        scope=scope,
        from_seat=source.get("from_seat"),
        to_seat=source.get("to_seat"),
        group_id=source.get("group_id"),
        recipient_seats=list(recipients) if isinstance(recipients, (list, tuple)) else None,
        public_text=public_text,
        agent_text=agent_text,
        host_text=host_text,
        payload=payload,
        importance=_importance(source, event_type),
        category=_text(source.get("category", _category(event_type))),
        state_delta=delta,
        no_state_changed=no_state_changed,
        secret_reason=_text(secret_reason) if secret_reason is not None else None,
        raw=raw,
    )


def _snapshot_mapping(snapshot: Any) -> dict[str, Any]:
    snapshot_method = getattr(snapshot, "snapshot", None)
    if callable(snapshot_method):
        snapshot = snapshot_method()
    source = _mapping(snapshot)
    return source


def _safe_seat(value: Any) -> dict[str, Any]:
    seat = _mapping(value)
    return {
        key: _json_value(seat[key])
        for key in ("seat_id", "name", "role", "model", "harness", "status", "group_id", "last_seen", "avatar_id")
        if key in seat
    }


def build_room_summary(snapshot: Any) -> dict[str, Any]:
    """从快照提取不含令牌和事件正文的房间摘要。"""
    source = _snapshot_mapping(snapshot)
    seats = source.get("seats", {})
    seat_values = list(seats.values()) if isinstance(seats, Mapping) else list(seats or [])
    seat_dicts = [_mapping(seat) for seat in seat_values]
    events = list(source.get("events") or [])
    return {
        "room_id": source.get("room_id"),
        "model_avatars": _json_value(source.get("model_avatars") or {}),
        "room_title": source.get("room_title", ""),
        "phase": source.get("phase", ""),
        "round_num": source.get("round_num", 1),
        "seq_counter": source.get("seq_counter", max((normalize_event(event).seq or 0 for event in events), default=0)),
        "event_count": len(events),
        "active_action_count": len(source.get("active_actions") or {}),
        "seat_count": len(seat_values),
        "seat_statuses": {
            status: sum(1 for seat in seat_dicts if seat.get("status", "UNKNOWN") == status)
            for status in sorted({seat.get("status", "UNKNOWN") for seat in seat_dicts})
        },
        "seats": [_safe_seat(seat) for seat in seat_values],
        "game": _json_value(source.get("game")),
        "flow": _json_value(source.get("flow")),
    }


def build_runtime_snapshot(snapshot: Any) -> dict[str, Any]:
    """构建给运行时观察者使用的完整但已脱敏快照。"""
    source = _snapshot_mapping(snapshot)
    summary = build_room_summary(source)
    active = source.get("active_actions") or {}
    seats = source.get("seats") or {}
    seat_values = list(seats.values()) if isinstance(seats, Mapping) else list(seats)
    timestamps = [normalize_event(event).timestamp for event in source.get("events") or []]
    timestamps = [value for value in timestamps if value is not None]
    actions = {}
    for key, value in active.items() if isinstance(active, Mapping) else []:
        item = _mapping(value)
        actions[str(key)] = {field: _json_value(item[field]) for field in item if field not in {"result_recipients"}}
    return {
        **summary,
        "events": [normalize_event(event).to_dict() for event in source.get("events") or []],
        "active_actions": actions,
        "last_seen_seqs": _json_value(source.get("last_seen_seqs") or {}),
        "settings": _json_value(source.get("settings") or {}),
        "metrics": {
            "seat_count": len(seat_values),
            "online_seats": sum(1 for seat in seat_values if _mapping(seat).get("connection_status") in {"LISTENING", "RECENT"}),
            "active_action_count": len(active) if isinstance(active, Mapping) else 0,
            "event_count": len(source.get("events") or []),
            "last_event_at": max(timestamps) if timestamps else None,
        },
    }


def build_event_page(events: Iterable[Any], cursor: Any = None, limit: int = 50) -> dict[str, Any]:
    """按事件序号构建稳定分页结果；cursor 表示已消费的 seq。"""
    if limit < 1:
        raise ValueError("limit 必须大于 0")
    normalized = [normalize_event(event) for event in events]
    normalized.sort(key=lambda event: (event.seq is None, event.seq or 0))
    try:
        after = int(cursor) if cursor is not None else 0
    except (TypeError, ValueError):
        raise ValueError("cursor 必须是事件序号") from None
    eligible = [event for event in normalized if (event.seq or 0) > after]
    page = eligible[:limit]
    next_cursor = page[-1].seq if page else after
    return {
        "events": [event.to_dict() for event in page],
        "cursor": after,
        "next_cursor": next_cursor,
        "has_more": len(eligible) > len(page),
        "total": len(normalized),
    }


__all__ = [
    "EventEnvelope",
    "normalize_event",
    "build_room_summary",
    "build_runtime_snapshot",
    "build_event_page",
]
