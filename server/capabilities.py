"""通用行动能力与选项注册。

能力选项只描述可供 Agent 选择的动作，不承担动作执行或权限判断。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _stable_id_payload(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


class ActionOption(BaseModel):
    """一个可供 Agent 选择的行动选项。"""

    model_config = ConfigDict(extra="ignore")

    option_id: Optional[str] = Field(None, min_length=1)
    text: str = ""
    value: Any = None
    targets: List[Any] = Field(default_factory=list)
    value_schema: Optional[Dict[str, Any]] = None
    text_schema: Optional[Dict[str, Any]] = None
    risk_tags: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        result = dict(data)
        if "text" not in result and "label" in result:
            result["text"] = result["label"]
        if "targets" not in result and "target_choices" in result:
            result["targets"] = result["target_choices"]
        if "risk_tags" not in result:
            risk = result.pop("risk", result.pop("risk_label", None))
            if risk is not None:
                result["risk_tags"] = risk if isinstance(risk, list) else [risk]
        elif isinstance(result["risk_tags"], str):
            result["risk_tags"] = [result["risk_tags"]]
        if "schema" in result:
            schema = result.pop("schema")
            if isinstance(schema, Mapping):
                result.setdefault("value_schema", schema.get("value"))
                result.setdefault("text_schema", schema.get("text"))
        if result.get("option_id") is not None:
            result["option_id"] = str(result["option_id"])
        if not result.get("option_id"):
            payload = {
                "text": result.get("text", ""),
                "value": result.get("value"),
                "targets": result.get("targets", []),
            }
            digest = hashlib.sha256(_stable_id_payload(payload).encode("utf-8")).hexdigest()[:16]
            result["option_id"] = f"opt_{digest}"
        return result

    @model_validator(mode="after")
    def normalize_values(self) -> "ActionOption":
        self.risk_tags = list(dict.fromkeys(self.risk_tags))
        return self

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    serialize = to_dict


@dataclass(frozen=True)
class _Registration:
    option: ActionOption
    seat_id: Optional[int | str]
    context: Optional[Dict[str, Any]]


class CapabilityRegistry:
    """按席位和上下文保存并筛选行动选项。"""

    def __init__(self, options: Optional[Iterable[ActionOption | Mapping[str, Any]]] = None):
        self._entries: Dict[Tuple[str, Optional[int | str], str], _Registration] = {}
        if options:
            for option in options:
                self.register(option)

    @staticmethod
    def _context_key(context: Optional[Mapping[str, Any]]) -> str:
        return _stable_id_payload(dict(context or {}))

    def register(
        self,
        option: ActionOption | Mapping[str, Any],
        *,
        seat_id: Optional[int | str] = None,
        seat: Optional[int | str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> ActionOption:
        """注册或更新一个选项；相同作用域重复注册是幂等的。"""
        if seat_id is not None and seat is not None and seat_id != seat:
            raise ValueError("seat_id 与 seat 不能同时指定不同值")
        selected_seat = seat_id if seat_id is not None else seat
        normalized = option if isinstance(option, ActionOption) else ActionOption.model_validate(option)
        normalized_context = dict(context) if context else None
        key = (normalized.option_id, selected_seat, self._context_key(normalized_context))
        self._entries[key] = _Registration(normalized, selected_seat, normalized_context)
        return normalized

    def register_many(
        self,
        options: Iterable[ActionOption | Mapping[str, Any]],
        *,
        seat_id: Optional[int | str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> List[ActionOption]:
        return [self.register(option, seat_id=seat_id, context=context) for option in options]

    def unregister(
        self,
        option_id: str,
        *,
        seat_id: Optional[int | str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        key = (str(option_id), seat_id, self._context_key(context))
        return self._entries.pop(key, None) is not None

    @staticmethod
    def _context_matches(registered: Optional[Mapping[str, Any]], requested: Optional[Mapping[str, Any]]) -> bool:
        if not registered:
            return True
        if not requested:
            return False
        return all(requested.get(key) == value for key, value in registered.items())

    def filter(
        self,
        *,
        seat_id: Optional[int | str] = None,
        seat: Optional[int | str] = None,
        context: Optional[Mapping[str, Any]] = None,
        target: Any = None,
        targets: Optional[Iterable[Any]] = None,
    ) -> List[ActionOption]:
        if seat_id is not None and seat is not None and seat_id != seat:
            raise ValueError("seat_id 与 seat 不能同时指定不同值")
        selected_seat = seat_id if seat_id is not None else seat
        requested_targets = list(targets) if targets is not None else None
        if target is not None:
            requested_targets = [target] if requested_targets is None else requested_targets + [target]
        result: List[ActionOption] = []
        for entry in self._entries.values():
            if entry.seat_id is not None and entry.seat_id != selected_seat:
                continue
            if not self._context_matches(entry.context, context):
                continue
            if requested_targets is not None and entry.option.targets and not any(
                requested == available for requested in requested_targets for available in entry.option.targets
            ):
                continue
            result.append(entry.option)
        return result

    available = filter
    get_available = filter
    for_seat = filter

    def to_dict(self) -> List[Dict[str, Any]]:
        result = []
        for entry in self._entries.values():
            item = entry.option.to_dict()
            if entry.seat_id is not None:
                item["seat_id"] = entry.seat_id
            if entry.context is not None:
                item["context"] = entry.context
            result.append(item)
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    serialize = to_dict

    def __len__(self) -> int:
        return len(self._entries)

