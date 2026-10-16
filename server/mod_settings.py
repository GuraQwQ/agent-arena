"""Mod 设置 schema 与值校验；不依赖 FastAPI 或具体游戏。"""

import math
import re
from copy import deepcopy


SETTING_TYPES = {"boolean", "integer", "number", "string", "text", "color", "select"}
SETTING_KEY = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
SETTING_FIELDS = {"type", "label", "description", "default", "min", "max", "step", "options", "restart_required"}


class ModSettingsError(ValueError):
    pass


def normalize_schema(raw):
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > 100:
        raise ModSettingsError("settings 必须是最多 100 项的对象")
    normalized = {}
    for key, item in raw.items():
        if not isinstance(key, str) or not SETTING_KEY.fullmatch(key):
            raise ModSettingsError(f"设置键 {key!r} 无效，只能使用小写字母、数字、点、短横线和下划线")
        if not isinstance(item, dict):
            raise ModSettingsError(f"设置 {key} 必须是对象")
        unknown = set(item) - SETTING_FIELDS
        if unknown:
            raise ModSettingsError(f"设置 {key} 含未知字段：{', '.join(sorted(unknown))}")
        setting_type = item.get("type")
        if setting_type not in SETTING_TYPES:
            raise ModSettingsError(f"设置 {key} 的 type 必须是 {', '.join(sorted(SETTING_TYPES))}")
        label = item.get("label", key)
        description = item.get("description", "")
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ModSettingsError(f"设置 {key} 的 label 无效")
        if not isinstance(description, str) or len(description) > 1000:
            raise ModSettingsError(f"设置 {key} 的 description 无效")
        result = {"type": setting_type, "label": label, "description": description,
                  "restart_required": bool(item.get("restart_required", False))}
        if setting_type == "select":
            options = item.get("options")
            if not isinstance(options, list) or not options or len(options) > 100:
                raise ModSettingsError(f"设置 {key} 的 options 必须是非空列表")
            normalized_options = []
            for option in options:
                if isinstance(option, str):
                    option = {"value": option, "label": option}
                if not isinstance(option, dict) or not isinstance(option.get("value"), (str, int, float, bool)) or not isinstance(option.get("label"), str):
                    raise ModSettingsError(f"设置 {key} 的选项格式无效")
                normalized_options.append({"value": option["value"], "label": option["label"]})
            result["options"] = normalized_options
        for name in ("min", "max", "step"):
            if name in item:
                value = item[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ModSettingsError(f"设置 {key} 的 {name} 必须是有限数值")
                result[name] = value
        if "min" in result and "max" in result and result["min"] > result["max"]:
            raise ModSettingsError(f"设置 {key} 的 min 不能大于 max")
        if "step" in result and result["step"] <= 0:
            raise ModSettingsError(f"设置 {key} 的 step 必须为正数")
        if setting_type not in {"integer", "number"} and any(name in result for name in ("min", "max", "step")):
            raise ModSettingsError(f"设置 {key} 只有 integer 或 number 可以声明数值范围")
        if setting_type in {"string", "text", "color"} and "max" in result:
            raise ModSettingsError(f"设置 {key} 的 max 不能用于文本设置")
        if "default" not in item:
            raise ModSettingsError(f"设置 {key} 必须声明 default")
        result["default"] = item["default"]
        normalized[key] = result
    defaults_for(normalized)
    return normalized


def _validate_one(key, schema, value):
    setting_type = schema["type"]
    if setting_type == "boolean":
        valid = type(value) is bool
    elif setting_type == "integer":
        valid = type(value) is int
    elif setting_type == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    elif setting_type == "select":
        valid = any(value == option["value"] and type(value) is type(option["value"]) for option in schema["options"])
    else:
        valid = isinstance(value, str)
        if valid and setting_type == "color" and not re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value):
            valid = False
    if not valid:
        raise ModSettingsError(f"设置 {key} 的值不符合 {setting_type} 类型")
    if setting_type in {"integer", "number"}:
        if "min" in schema and value < schema["min"]:
            raise ModSettingsError(f"设置 {key} 不能小于 {schema['min']}")
        if "max" in schema and value > schema["max"]:
            raise ModSettingsError(f"设置 {key} 不能大于 {schema['max']}")
        if setting_type == "integer" and any(isinstance(schema.get(name), float) and not schema[name].is_integer() for name in ("min", "max", "step") if name in schema):
            raise ModSettingsError(f"设置 {key} 的 integer 范围必须是整数")
    return value


def defaults_for(schema):
    return validate_values(schema, {key: item["default"] for key, item in schema.items()})


def validate_values(schema, values, partial=False):
    if not isinstance(values, dict):
        raise ModSettingsError("Mod 设置值必须是对象")
    unknown = set(values) - set(schema)
    if unknown:
        raise ModSettingsError(f"包含未声明的设置：{', '.join(sorted(unknown))}")
    result = {} if partial else defaults_for_without_defaults(schema)
    for key, value in values.items():
        result[key] = _validate_one(key, schema[key], value)
    if not partial:
        for key in schema:
            if key not in values:
                result[key] = _validate_one(key, schema[key], schema[key]["default"])
    return deepcopy(result)


def defaults_for_without_defaults(schema):
    return {key: item["default"] for key, item in schema.items()}
