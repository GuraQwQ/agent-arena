"""剧本替换、身份配置和发送时阵营视野。"""

from test_engine import EngineCase
from models import Scenario, SeatDefinition, VisibilityScope
from archives import ArchiveStore


class ScenarioTest(EngineCase):
    def test_scenario_round_trip_and_archives_before_replacement(self):
        self.room.record_event("ANNOUNCEMENT", "旧对局", "内容")
        old_room = self.room.room_id
        scenario = Scenario(title="暗标拍卖", description="报价保密", seats=[
            SeatDefinition(seat_id=1, name="甲", role="买家", init_prompt="赢得拍卖"),
            SeatDefinition(seat_id=2, name="乙", role="买家", group_id="红方")
        ])
        self.room.load_scenario(scenario)
        self.assertEqual(self.room.get_scenario(), scenario)
        self.assertNotEqual(self.room.room_id, old_room)
        exported = self.room.get_scenario().model_dump_json()
        self.assertNotIn("token", exported)
        self.assertEqual(ArchiveStore(self.path.parent / "archives").read(old_room)["events"][0]["title"], "旧对局")

    def test_membership_change_does_not_reveal_past_group_messages(self):
        self.room.update_seat(SeatDefinition(seat_id=1, group_id="红方"))
        self.room.record_event("GROUP_MESSAGE", "阵营线索", "旧消息", group_id="红方", scope=VisibilityScope.GROUP)
        self.room.update_seat(SeatDefinition(seat_id=2, group_id="红方"))
        self.assertEqual(len(self.room.filter_events_for_seat(1)), 1)
        self.assertEqual(self.room.filter_events_for_seat(2), [])

    def test_agent_cannot_replace_host_assigned_role(self):
        self.room.update_seat(SeatDefinition(seat_id=1, role="裁判", init_prompt="保留目标"))
        seat = self.room.seats[1]
        self.room.join_seat(1, "重连", "玩家", "模型", "CLI", token=seat.token)
        self.assertEqual(self.room.seats[1].role, "裁判")
        self.assertEqual(self.room.seats[1].init_prompt, "保留目标")
