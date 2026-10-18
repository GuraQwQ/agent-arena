"""覆盖头像复用、席位优先级、持久化与旧快照的渐进读取。"""

import base64
from unittest.mock import patch

from test_engine import EngineCase
from archives import ArchiveStore
from avatars import AvatarStore, model_key
from engine import ArenaEngine
from models import SeatDefinition


PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=="


class AvatarTest(EngineCase):
    def test_model_defaults_follow_join_reconnect_and_new_room(self):
        avatar_id = self.room.avatars.upload(PNG)
        self.room.avatars.set_model("GPT-6.1-Sol", avatar_id)
        for sid in (1, 2):
            self.room.join_seat(sid, f"玩家{sid}", "玩家", "  gpt-6.1-sol  ", "CLI", claim_token=self.room.seats[sid].claim_token)
        snapshot = self.room.get_host_snapshot()
        for sid in (1, 2):
            seat = snapshot["seats"][sid]
            self.assertIsNone(seat["avatar_id"])
            self.assertEqual(snapshot["model_avatars"][model_key(seat["model"])], avatar_id)
        self.assertNotIn("gpt-6.1-sol-high", snapshot["model_avatars"])
        restored = ArenaEngine()
        self.assertEqual(restored.avatars.presets()["gpt-6.1-sol"], avatar_id)
        restored.join_seat(1, "玩家1", "玩家", "未指定模型", "CLI", token=restored.seats[1].token)
        self.assertEqual(model_key(restored.seats[1].model), "gpt-6.1-sol")
        restored.reset()
        self.assertEqual(restored.avatars.presets()["gpt-6.1-sol"], avatar_id)

    def test_seat_override_and_archive_keep_references(self):
        avatar_id = self.room.avatars.upload(PNG)
        self.room.update_appearance(1, {"model": "模型 A", "avatar_id": avatar_id})
        self.room.avatars.set_model("模型 A", avatar_id)
        store = ArchiveStore(self.path.parent / "archives")
        room_id = store.save(self.room.snapshot().model_dump(mode="json"))
        exported = store.export(room_id)
        self.assertEqual(exported["seats"]["1"]["avatar_id"], avatar_id)
        self.assertEqual(exported["model_avatars"]["模型 a"], avatar_id)
        self.room.game = {"status": "RUNNING"}
        self.room.update_appearance(1, {"avatar_id": None})
        self.assertIsNone(self.room.seats[1].avatar_id)
        self.assertEqual(self.room.seats[1].model, "模型 A")

    def test_old_snapshot_and_seat_editor_keep_configured_avatar(self):
        avatar_id = self.room.avatars.upload(PNG)
        self.room.update_appearance(1, {"model": "模型 A", "avatar_id": avatar_id})
        self.room.update_seat(SeatDefinition(seat_id=1, name="重命名"))
        self.assertEqual(self.room.seats[1].avatar_id, avatar_id)
        self.assertEqual(self.room.seats[1].model, "模型 A")
        raw = self.room.snapshot().model_dump(mode="json")
        raw.pop("model_avatars")
        for seat in raw["seats"].values():
            seat.pop("avatar_id")
        import json
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        restored = ArenaEngine()
        self.assertIsNone(restored.seats[1].avatar_id)
        self.assertEqual(restored.seats[1].token, raw["seats"]["1"]["token"])

    def test_invalid_images_and_failed_save_keep_library(self):
        for value in ("data:image/svg+xml;base64,PHN2Zy8+", "data:image/png;base64,YmFk", "data:image/png;base64,invalid=="):
            with self.assertRaises(ValueError):
                self.room.avatars.upload(value)
        avatar_id = self.room.avatars.upload(PNG)
        self.assertEqual(self.room.avatars.upload(PNG), avatar_id)
        before = self.room.avatars.path.read_bytes()
        with patch("avatars.write_json", side_effect=OSError("磁盘忙")):
            with self.assertRaises(OSError):
                self.room.avatars.set_model("model", avatar_id)
        self.assertEqual(self.room.avatars.presets(), {})
        self.assertEqual(self.room.avatars.path.read_bytes(), before)
        self.assertEqual(AvatarStore(self.room.avatars.path).image(avatar_id)[0], base64.b64decode(PNG.split(",")[1]))
        with self.assertRaises(ValueError):
            self.room.update_appearance(1, {"avatar_id": "a" * 64})
