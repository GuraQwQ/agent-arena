"""观察层的事件规范化、脱敏快照和分页契约。"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from models import Event, VisibilityScope
from observer import (
    build_event_page,
    build_room_summary,
    build_runtime_snapshot,
    normalize_event,
)


class ObserverTest(unittest.TestCase):
    def test_normalize_existing_event_and_layer_text(self):
        event = Event(
            seq=3,
            timestamp=10.5,
            round_num=2,
            event_type="ACTION_SUBMIT",
            title="提交",
            content="公开答案",
            from_seat=1,
            scope=VisibilityScope.PUBLIC,
            secret_reason="主持人策略",
            data={"state_delta": {"score": 1}},
        )
        envelope = normalize_event(event, include_raw=True)
        self.assertEqual(envelope.category, "submissions")
        self.assertEqual(envelope.importance, "high")
        self.assertEqual(envelope.public_text, "公开答案")
        self.assertEqual(envelope.agent_text, "公开答案")
        self.assertIn("主持人策略", envelope.host_text)
        self.assertEqual(envelope.state_delta, {"score": 1})
        self.assertFalse(envelope.no_state_changed)
        self.assertEqual(envelope["raw"]["seq"], 3)

    def test_host_only_event_is_hidden_from_public_and_agent(self):
        envelope = normalize_event(
            {
                "seq": 1,
                "event_type": "ACTION_SUBMIT",
                "content": "秘密提交",
                "scope": "HOST_ONLY",
                "secret_reason": "战术理由",
            }
        )
        self.assertEqual(envelope.public_text, "")
        self.assertEqual(envelope.agent_text, "")
        self.assertEqual(envelope.host_text, "秘密提交\n战术理由")

    def test_snapshot_summary_and_runtime_snapshot_strip_tokens(self):
        snapshot = {
            "room_id": "room",
            "room_title": "测试房间",
            "phase": "准备中",
            "round_num": 1,
            "seq_counter": 1,
            "seats": {1: {"seat_id": 1, "name": "A", "token": "secret", "status": "IDLE"}},
            "events": [{"seq": 1, "event_type": "ANNOUNCEMENT", "content": "你好"}],
            "active_actions": {},
        }
        original = copy.deepcopy(snapshot)
        summary = build_room_summary(snapshot)
        runtime = build_runtime_snapshot(snapshot)
        self.assertNotIn("token", summary["seats"][0])
        self.assertNotIn("token", runtime["events"][0])
        self.assertEqual(snapshot, original)

    def test_event_page_uses_seq_cursor(self):
        events = [{"seq": seq, "event_type": "CHAT", "content": str(seq)} for seq in range(1, 5)]
        page = build_event_page(events, cursor=1, limit=2)
        self.assertEqual([event["seq"] for event in page["events"]], [2, 3])
        self.assertEqual(page["next_cursor"], 3)
        self.assertTrue(page["has_more"])


if __name__ == "__main__":
    unittest.main()
