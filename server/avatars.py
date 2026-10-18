"""实例级模型头像库；图片按内容寻址，快照只保存引用。"""

import base64
import binascii
import hashlib
import json
import re
import threading
from pathlib import Path

from storage import write_json


def model_key(model):
    return model.strip().lower()


class AvatarStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"models": {}, "images": {}}

    def _commit(self, data):
        write_json(self.path, data)
        self.data = data

    def upload(self, data_url):
        match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", data_url)
        if not match or len(data_url) > 400_000:
            raise ValueError("请上传裁剪后的 PNG、JPEG 或 WebP 头像（不超过 300 KB）")
        try:
            raw = base64.b64decode(match[2], validate=True)
        except binascii.Error as exc:
            raise ValueError("头像编码无效，请重新选择图片") from exc
        signatures = {"png": raw.startswith(b"\x89PNG\r\n\x1a\n"), "jpeg": raw.startswith(b"\xff\xd8\xff"),
                      "webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"}
        if not signatures[match[1]] or len(raw) > 300_000:
            raise ValueError("头像格式或大小无效，请重新裁剪")
        avatar_id = hashlib.sha256(raw).hexdigest()
        with self._lock:
            if avatar_id not in self.data["images"]:
                images = {**self.data["images"], avatar_id: {"mime": f"image/{match[1]}", "base64": match[2]}}
                self._commit({**self.data, "images": images})
        return avatar_id

    def require_image(self, avatar_id):
        if avatar_id is not None and avatar_id not in self.data["images"]:
            raise ValueError("头像图片不存在，请重新上传")

    def image(self, avatar_id):
        item = self.data["images"].get(avatar_id)
        return (base64.b64decode(item["base64"]), item["mime"]) if item else None

    def set_model(self, model, avatar_id):
        model = model.strip()
        if not model or len(model) > 200:
            raise ValueError("请填写 1 至 200 字符的模型名称")
        with self._lock:
            self.require_image(avatar_id)
            models = dict(self.data["models"])
            if avatar_id is None:
                models.pop(model_key(model), None)
            else:
                models[model_key(model)] = {"model": model, "avatar_id": avatar_id}
            self._commit({**self.data, "models": models})

    def presets(self):
        return {key: value["avatar_id"] for key, value in self.data["models"].items()}

    def catalog(self):
        return list(self.data["models"].values())
