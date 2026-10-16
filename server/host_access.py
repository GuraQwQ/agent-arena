"""本地可编辑的加入口令，与当前服务内的主持人会话分开保存。"""

import hashlib
import json
import secrets
import threading
from pathlib import Path

from storage import write_json


class JoinClosed(PermissionError):
    pass


class HostAccess:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path).resolve()
        self.service_id = secrets.token_hex(12)
        self.remaining_uses = 1
        self.used_count = 0
        self._sessions = set()
        self._lock = threading.RLock()
        if not self.config_path.exists():
            write_json(self.config_path, {"password": secrets.token_urlsafe(9)})

    @staticmethod
    def _digest(session):
        return hashlib.sha256(session.encode("utf-8")).digest()

    def authenticated(self, session):
        with self._lock:
            return bool(session and self._digest(session) in self._sessions)

    def info(self):
        with self._lock:
            return {"service_id": self.service_id, "remaining_uses": self.remaining_uses,
                    "used_count": self.used_count, "config_path": str(self.config_path)}

    def join(self, password, current_session=None):
        with self._lock:
            if self.authenticated(current_session):
                return current_session
            if self.remaining_uses == 0:
                raise JoinClosed("当前服务的主持人加入次数已用完，请由已登录的主持人增加次数")
            try:
                config = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
                expected = config.get("password") if isinstance(config, dict) else None
                if not isinstance(expected, str) or not expected.strip():
                    raise ValueError("password 必须是非空字符串")
            except (UnicodeError, ValueError) as exc:
                raise ValueError(f"请修正主持人登录文件：{exc}") from exc
            if not secrets.compare_digest(password.encode("utf-8"), expected.encode("utf-8")):
                raise PermissionError("主持人加入口令不正确")
            session = secrets.token_urlsafe(32)
            self._sessions.add(self._digest(session))
            self.remaining_uses -= 1
            self.used_count += 1
            return session

    def add_uses(self, count):
        if type(count) is not int or count < 1:
            raise ValueError("增加次数必须是正整数")
        with self._lock:
            self.remaining_uses += count
            return self.info()
