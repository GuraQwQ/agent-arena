"""即时自述的统一入口；界面、记忆和存档引用同一条事件。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from models import VisibilityScope


class AgentNote(BaseModel):
    seat_id: int
    room_id: str
    token: str
    note_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=8000)
    created_at: float = Field(allow_inf_nan=False)
    channel: Literal["cli", "native"] = "cli"
    request_id: str | None = Field(None, min_length=1, max_length=128)
    related_seq: int | None = Field(None, ge=1)
    revises_seq: int | None = Field(None, ge=1)
    remember: bool = False

    @field_validator("content")
    @classmethod
    def trim_content(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请写下当前想法")
        return value


def append_note(room, note: AgentNote):
    if note.room_id != room.room_id or not room.verify_token(note.seat_id, note.token):
        raise PermissionError("房间或席位凭证不匹配")
    payload = note.model_dump(exclude={"seat_id", "room_id", "token", "content"})
    for event in room.events:
        if event.event_type == "AGENT_NOTE" and event.from_seat == note.seat_id and event.data.get("note_id") == note.note_id:
            if event.content != note.content or event.data["submission"] != payload:
                raise ValueError("同一自述编号不能提交不同内容")
            return event

    by_seq = {event.seq: event for event in room.events}
    for seq in (note.related_seq, note.revises_seq):
        if seq is None:
            continue
        event = by_seq.get(seq)
        own_note = event is not None and event.event_type == "AGENT_NOTE" and event.from_seat == note.seat_id
        own_action = event is not None and event.event_type == "ACTION_SUBMIT" and event.from_seat == note.seat_id
        if event is None or not (own_note or own_action or room._is_event_visible_to_seat(event, note.seat_id)):
            raise ValueError("关联记录不在本席位视野中")
        if seq == note.revises_seq and not own_note:
            raise ValueError("只能修正自己的自述")

    timing = "current"
    if note.request_id:
        request = next((event for event in room.events if event.event_type == "ACTION_REQUEST"
                        and event.to_seat == note.seat_id and event.data.get("request_id") == note.request_id), None)
        if request is None:
            raise ValueError("未找到本席位的关联行动")
        pending = room.active_actions.get(note.seat_id)
        if pending is None or pending.request_id != note.request_id:
            timing = "after_action"

    seat = room.seats[note.seat_id]
    author = {"seat_id": seat.seat_id, "name": seat.name, "model": seat.model, "harness": seat.harness,
              "avatar_id": seat.avatar_id or room.avatars.presets().get(seat.model.strip().lower())}
    return room.record_event(
        "AGENT_NOTE", f"{note.seat_id}号位的即时自述", note.content,
        from_seat=note.seat_id, scope=VisibilityScope.HOST_ONLY,
        data={**payload, "timing": timing, "author": author, "submission": payload},
    )


def journal_projection(events):
    latest = {}
    remembered = {}
    for event in events:
        if event.event_type != "AGENT_NOTE":
            continue
        seat_id = event.from_seat
        item = event.model_dump(exclude={"secret_reason"})
        item["data"] = {key: value for key, value in item["data"].items() if key != "submission"}
        latest[seat_id] = item
        memory = remembered.setdefault(seat_id, {})
        memory.pop(event.data.get("revises_seq"), None)
        if event.data.get("remember"):
            memory[event.seq] = item
    return {"latest": latest, "remembered": {seat: list(items.values()) for seat, items in remembered.items()}}
