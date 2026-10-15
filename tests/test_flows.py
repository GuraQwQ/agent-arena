"""编排推进、同时行动封存、暂停恢复与持久化。"""

from unittest.mock import patch

from test_engine import EngineCase
from engine import ArenaEngine
from models import FlowStep


class FlowTest(EngineCase):
    def submit(self, seat_id):
        action = self.room.active_actions[seat_id]
        return self.room.submit_action(seat_id, self.room.seats[seat_id].token,
            action.action_type, f"答复{seat_id}", action.request_id)

    def test_sequence_manual_and_invalid_plan(self):
        with self.assertRaises(ValueError):
            self.room.start_flow([FlowStep(phase="错误", target_seats=[99])])
        self.assertEqual(self.room.flow.status, "IDLE")
        self.room.start_flow([FlowStep(phase="依次发言", target_seats=[1, 2]),
                              FlowStep(phase="裁决", mode="MANUAL")])
        self.assertEqual(list(self.room.active_actions), [1])
        self.submit(1)
        self.assertEqual(list(self.room.active_actions), [2])
        self.submit(2)
        self.assertEqual(self.room.flow.status, "AWAITING_HOST")
        self.room.control_flow("advance")
        self.assertEqual(self.room.flow.status, "COMPLETED")

    def test_simultaneous_reveal_uses_new_sequences_after_ack(self):
        self.room.start_flow([FlowStep(phase="密封", mode="SIMULTANEOUS", target_seats=[1, 2])])
        event = self.submit(1)
        self.assertFalse(any(e["content"] == "答复1" for e in self.room.filter_events_for_seat(2)))
        cursor = self.room._seq_counter
        self.room.acknowledge(2, self.room.seats[2].token, self.room.room_id, cursor)
        self.room = ArenaEngine()
        self.submit(2)
        revealed = [e for e in self.room.filter_events_for_seat(2, cursor) if e["event_type"] == "ACTION_RESULT"]
        self.assertEqual([e["content"] for e in revealed], ["答复1", "答复2"])
        self.assertEqual(event.scope, "HOST_ONLY")

    def test_pause_freezes_timeout_and_defers_progress(self):
        with patch("engine.time.time", return_value=100):
            self.room.start_flow([FlowStep(phase="暂停", target_seats=[1, 2], timeout=10)])
            self.room.control_flow("pause")
        with patch("engine.time.time", return_value=200):
            self.room.tick()
            self.submit(1)
            self.assertEqual(self.room.active_actions, {})
            self.room.control_flow("resume")
            self.assertEqual(self.room.active_actions[2].deadline, 210)
        with patch("engine.time.time", return_value=211):
            self.room.tick()
        self.assertEqual(self.room.flow.status, "COMPLETED")
        self.assertTrue(any(e.event_type == "ACTION_CANCEL" for e in self.room.events))

    def test_stop_and_restart_during_pause(self):
        self.room.start_flow([FlowStep(phase="同时", mode="SIMULTANEOUS", target_seats=[1, 2])])
        self.room.control_flow("pause")
        self.room = ArenaEngine()
        self.assertEqual(self.room.flow.status, "PAUSED")
        self.room.control_flow("stop")
        self.assertFalse(self.room.active_actions)
        self.assertEqual(self.room.flow.status, "IDLE")
