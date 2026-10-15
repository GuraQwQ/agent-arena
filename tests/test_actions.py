"""行动类型、主持人决定的可见性与取消边界。"""

from test_engine import EngineCase
from models import SeatDefinition, VisibilityScope


class ActionTest(EngineCase):
    def test_secret_vote_is_not_visible_to_other_agents(self):
        request = self.room.dispatch_action(1, "VOTE", "投票", ["甲", "乙"], result_scope=VisibilityScope.HOST_ONLY)
        token = self.room.seats[1].token
        with self.assertRaises(ValueError):
            self.room.submit_action(1, token, "VOTE", "丙", request.request_id, data={"choice": "丙"})
        self.assertIn(1, self.room.active_actions)
        self.room.submit_action(1, token, "VOTE", "甲", request.request_id, data={"choice": "甲"})
        self.assertEqual(self.room.filter_events_for_seat(2), [])
        self.assertEqual(self.room.events[-1].data["choice"], "甲")

    def test_result_recipients_are_frozen_at_dispatch(self):
        self.room.update_seat(SeatDefinition(seat_id=2, group_id="红方"))
        request = self.room.dispatch_action(1, "ACT", "分析", result_scope=VisibilityScope.GROUP, result_group_id="红方")
        self.room.update_seat(SeatDefinition(seat_id=3, group_id="红方"))
        self.room.submit_action(1, self.room.seats[1].token, "ACT", "秘密", request.request_id)
        self.assertEqual(len(self.room.filter_events_for_seat(2)), 1)
        self.assertEqual(self.room.filter_events_for_seat(3), [])

    def test_number_bounds_and_cancelled_request(self):
        request = self.room.dispatch_action(1, "NUMBER", "报价", min_value=1, max_value=10)
        token = self.room.seats[1].token
        for value in (0, 11, True, float("nan")):
            with self.assertRaises(ValueError):
                self.room.submit_action(1, token, "NUMBER", str(value), request.request_id, data={"value": value})
        self.room.cancel_action(1)
        with self.assertRaises(PermissionError):
            self.room.submit_action(1, token, "NUMBER", "5", request.request_id, data={"value": 5})
