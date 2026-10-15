"""存档原子保存、错误处理与历史视野测试。"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from server.archives import ArchiveStore


class ArchiveStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "archives"
        self.store = ArchiveStore(self.root)
        self.room_id = uuid4().hex
        self.snapshot = {
            "room_id": self.room_id, "room_title": "秘密投票", "phase": "投票", "round_num": 2,
            "seats": {
                "1": {"seat_id": 1, "group_id": "红", "token": "player-one", "claim_token": "claim-one"},
                "2": {"seat_id": 2, "group_id": "蓝", "token": "player-two", "claim_token": "claim-two"},
            },
            "events": [
                {"seq": 1, "scope": "PUBLIC", "content": "公开", "secret_reason": "主持人笔记"},
                {"seq": 2, "scope": "GROUP", "group_id": "蓝", "recipient_seats": [1], "content": "旧阵营"},
                {"seq": 3, "scope": "PRIVATE", "recipient_seats": [2], "content": "私信"},
                {"seq": 4, "scope": "HOST_ONLY", "recipient_seats": [1], "content": "主持人秘密"},
                {"seq": 5, "scope": "GROUP", "group_id": "红", "content": "未冻结的旧记录"},
            ],
            "active_actions": {"1": {"prompt": "秘密目标"}},
            "last_seen_seqs": {"1": 4}, "receipts": {"secret": "receipt"},
            "flow": {"steps": ["秘密流程"]}, "settings": {"history_rounds": None},
        }

    def test_empty_and_idempotent_save_preserve_input(self):
        self.assertEqual(self.store.list(), [])
        original = copy.deepcopy(self.snapshot)
        self.assertEqual(self.store.save(self.snapshot), self.room_id)
        self.assertEqual(self.snapshot, original)
        self.snapshot["phase"] = "结算"
        self.store.save(self.snapshot)
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.read(self.room_id)["phase"], "结算")
        self.assertEqual(self.store.list()[0]["event_count"], 5)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_failed_replace_keeps_previous_archive_and_can_retry(self):
        self.store.save(self.snapshot)
        self.snapshot["phase"] = "结算"
        with patch("server.archives.os.replace", side_effect=OSError("保存中断")):
            with self.assertRaises(OSError):
                self.store.save(self.snapshot)
        self.assertEqual(self.store.read(self.room_id)["phase"], "投票")
        self.assertEqual(len(list(self.root.iterdir())), 1)
        self.store.save(self.snapshot)
        self.assertEqual(self.store.read(self.room_id)["phase"], "结算")

    def test_invalid_paths_and_missing_archives(self):
        for room_id in ("../room_state", "", "C:\\secrets", None):
            with self.subTest(room_id=room_id), self.assertRaises(ValueError):
                self.store.read(room_id)
        with self.assertRaises(FileNotFoundError):
            self.store.read(uuid4().hex)

    def test_export_freezes_visibility_and_removes_runtime_secrets(self):
        self.store.save(self.snapshot)
        player = self.store.export(self.room_id, seat_id=1)
        self.assertEqual(list(player["seats"]), ["1"])
        self.assertEqual([event["seq"] for event in player["events"]], [1, 2])
        self.assertTrue(all(event["secret_reason"] is None for event in player["events"]))
        host = self.store.export(self.room_id)
        self.assertEqual(len(host["events"]), 5)
        self.assertEqual(host["events"][0]["secret_reason"], "主持人笔记")
        for exported in (host, player):
            for key in ("active_actions", "last_seen_seqs", "receipts", "flow"):
                self.assertNotIn(key, exported)
            for seat in exported["seats"].values():
                self.assertNotIn("token", seat)
                self.assertNotIn("claim_token", seat)
        self.assertIn("token", self.store.read(self.room_id)["seats"]["1"])
        with self.assertRaises(ValueError):
            self.store.export(self.room_id, seat_id=3)

    def test_corrupt_archive_is_reported_without_blocking_valid_archives(self):
        self.store.save(self.snapshot)
        damaged_id = uuid4().hex
        (self.root / f"{damaged_id}.json").write_text("{坏档", encoding="utf-8")
        (self.root / "unrelated.json").write_text("{}", encoding="utf-8")
        rows = self.store.list()
        self.assertEqual(len(rows), 2)
        self.assertIn("error", next(row for row in rows if row["room_id"] == damaged_id))
        with self.assertRaises(ValueError):
            self.store.read(damaged_id)
        (self.root / f"{damaged_id}.json").write_text(json.dumps([]), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.read(damaged_id)
        malformed = dict(self.snapshot, room_id=damaged_id, archived_at="坏时间")
        (self.root / f"{damaged_id}.json").write_text(json.dumps(malformed), encoding="utf-8")
        self.assertIn("error", next(row for row in self.store.list() if row["room_id"] == damaged_id))


if __name__ == "__main__":
    unittest.main()
