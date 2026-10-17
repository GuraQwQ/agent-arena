"""覆盖通用行动选项的稳定标识、注册筛选与兼容序列化。"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from capabilities import ActionOption, CapabilityRegistry
from models import ActionRequest


class CapabilityTest(unittest.TestCase):
    def test_option_id_is_stable_and_serializable(self):
        first = ActionOption(text="调查", value={"kind": "search"})
        second = ActionOption(text="调查", value={"kind": "search"})
        self.assertEqual(first.option_id, second.option_id)
        self.assertEqual(json.loads(first.to_json())["text"], "调查")

    def test_registry_filters_by_seat_and_context(self):
        registry = CapabilityRegistry()
        global_option = ActionOption(option_id="pass", text="跳过", value="pass")
        private_option = ActionOption(option_id="inspect", text="调查", value="inspect", risk_tags=["low"])
        registry.register(global_option)
        registry.register(private_option, seat_id=2, context={"phase": "night"})
        self.assertEqual([item.option_id for item in registry.filter(seat_id=1)], ["pass"])
        self.assertEqual([item.option_id for item in registry.filter(seat_id=2, context={"phase": "night", "round": 1})], ["pass", "inspect"])
        self.assertEqual([item.option_id for item in registry.filter(seat_id=2, context={"phase": "day"})], ["pass"])

    def test_action_request_keeps_legacy_options(self):
        request = ActionRequest(
            request_id="req-1",
            target_seat=1,
            phase="day",
            options=["旧选项"],
            action_options=[ActionOption(option_id="new", text="新选项", value="new")],
        )
        self.assertEqual(request.options, ["旧选项"])
        self.assertEqual(request.action_options[0].option_id, "new")


if __name__ == "__main__":
    unittest.main()
