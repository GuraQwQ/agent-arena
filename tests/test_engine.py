"""覆盖对局状态、事件确认和提交重试的关键边界。"""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import engine


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "room_state.json"
        self.patch = patch.object(engine, "SNAPSHOT_FILE", self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.room = engine.ArenaEngine(restore_from_disk=False)


class EngineTest(EngineCase):
    def test_observation_modes_preserve_events_and_actions_interrupt_batch(self):
        async def check():
            self.room.update_settings({"observation_mode": "action"})
            request = self.room.dispatch_action(1, "ACT", "行动")
            token = self.room.seats[1].token
            self.room.acknowledge(1, token, self.room.room_id, request and self.room.events[-1].seq)
            self.room.submit_action(1, token, "ACT", "自己的回答", request.request_id)
            self.assertEqual((await self.room.wait_turn(1, token, timeout=0.01))["code"], 0)
            self.room.record_event("ANNOUNCEMENT", "观察", "保留原文")
            self.assertEqual((await self.room.wait_turn(1, token, timeout=0.01))["code"], 0)
            self.room.update_settings({"observation_mode": "batch", "observation_batch_seconds": 10})
            task = asyncio.create_task(self.room.wait_turn(1, token, timeout=1))
            await asyncio.sleep(0)
            self.room.dispatch_action(1, "ACT", "立即行动")
            response = await asyncio.wait_for(task, 0.5)
            self.assertEqual(response["code"], 42)
            self.assertIn("保留原文", [event["content"] for event in response["recent_events"]])
        asyncio.run(check())

    def test_delivery_is_repeated_until_acknowledged(self):
        self.room.record_event("ANNOUNCEMENT", "消息", "线索")
        token = self.room.seats[1].token
        first = asyncio.run(self.room.wait_turn(1, token, timeout=1))
        second = asyncio.run(self.room.wait_turn(1, token, timeout=1))
        self.assertEqual(first["events"], second["events"])
        self.room.acknowledge(1, token, self.room.room_id, first["events"][-1]["seq"])
        restored = engine.ArenaEngine()
        self.assertEqual(restored.last_seen_seqs[1], 1)
        self.assertEqual(restored.filter_events_for_seat(1, 1), [])

    def test_submission_retry_does_not_duplicate_event(self):
        request = self.room.dispatch_action(1, "ACT", "发言")
        token = self.room.seats[1].token
        first = self.room.submit_action(1, token, "ACT", "回答", request.request_id)
        restored = engine.ArenaEngine()
        retried = restored.submit_action(1, token, "ACT", "回答", request.request_id)
        self.assertEqual(first.seq, retried.seq)
        self.assertEqual(len(restored.events), 2)
        with self.assertRaises(ValueError):
            restored.submit_action(1, token, "ACT", "另一个答案", request.request_id)

    def test_write_failure_restores_memory_and_disk(self):
        before = self.path.read_bytes()
        with patch.object(engine, "write_json", side_effect=OSError("磁盘错误")):
            with self.assertRaises(OSError):
                self.room.record_event("ANNOUNCEMENT", "消息", "线索")
        self.assertEqual(self.room.events, [])
        self.assertEqual(self.path.read_bytes(), before)

    def test_migration_is_repeatable_and_preserves_credentials(self):
        old = self.room.snapshot().model_dump(mode="json")
        old.pop("schema_version")
        old.pop("room_id")
        old.pop("receipts")
        self.path.write_text(json.dumps(old), encoding="utf-8")
        migrated = engine.ArenaEngine()
        again = engine.ArenaEngine()
        self.assertTrue(self.path.with_suffix(".v1.bak").exists())
        self.assertEqual(migrated.room_id, again.room_id)
        self.assertEqual(migrated.seats[1].token, old["seats"]["1"]["token"])

    def test_invalid_snapshot_is_not_overwritten(self):
        self.path.write_text("broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            engine.ArenaEngine()
        self.assertEqual(self.path.read_text(), "broken")


if __name__ == "__main__":
    unittest.main()
