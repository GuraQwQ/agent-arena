"""即时自述的时间关联、单一记录与保留记忆。"""

from unittest.mock import patch

from test_engine import EngineCase
from agent_journal import AgentNote, journal_projection
from engine import ArenaEngine
from models import VisibilityScope
from archives import ArchiveStore


class AgentJournalTest(EngineCase):
    def note(self, note_id="first", **fields):
        return AgentNote(seat_id=1, token=self.room.seats[1].token, room_id=self.room.room_id,
                         note_id=note_id, content="我准备先核对公开事实。", created_at=100, **fields)

    def test_current_note_does_not_consume_action_and_survives_retry(self):
        action = self.room.dispatch_action(1, "SPEAK", "请回应")
        note = self.note(request_id=action.request_id, remember=True)
        first = self.room.record_agent_note(note)
        self.assertEqual(first.data["timing"], "current")
        self.assertIn(1, self.room.active_actions)
        restored = ArenaEngine()
        restored.seats[1].name = "改过的席位名称"
        self.assertEqual(restored.record_agent_note(note).seq, first.seq)
        self.assertNotEqual(first.data["author"]["name"], restored.seats[1].name)
        self.assertEqual(len([e for e in restored.events if e.event_type == "AGENT_NOTE"]), 1)
        with self.assertRaises(ValueError):
            restored.record_agent_note(note.model_copy(update={"content": "另一段话"}))

    def test_delayed_note_keeps_original_action_and_is_marked_as_supplement(self):
        first = self.room.dispatch_action(1, "ACT", "先行动", result_scope=VisibilityScope.HOST_ONLY)
        submitted = self.room.submit_action(1, self.room.seats[1].token, "ACT", "已完成", first.request_id)
        note = self.note(request_id=first.request_id, related_seq=submitted.seq)
        second = self.room.dispatch_action(1, "ACT", "下一次行动")
        event = self.room.record_agent_note(note)
        self.assertEqual(event.data["request_id"], first.request_id)
        self.assertEqual(event.data["timing"], "after_action")
        self.assertEqual(self.room.active_actions[1].request_id, second.request_id)

    def test_own_history_and_memory_share_the_same_event(self):
        first = self.room.record_agent_note(self.note(remember=True))
        revised = self.room.record_agent_note(self.note("revision", revises_seq=first.seq, remember=True))
        frame = journal_projection(self.room.events)
        self.assertEqual(frame["latest"][1]["seq"], revised.seq)
        self.assertEqual([e["seq"] for e in frame["remembered"][1]], [revised.seq])
        self.assertEqual(journal_projection([first])["remembered"][1][0]["seq"], first.seq)
        self.assertEqual(self.room.filter_events_for_seat(2), [])
        self.assertEqual(self.room.filter_events_for_seat(1), [])

    def test_cross_room_and_other_players_private_records_are_rejected(self):
        with self.assertRaises(PermissionError):
            self.room.record_agent_note(self.note().model_copy(update={"room_id": "other"}))
        secret = self.room.dispatch_action(2, "ACT", "专属提示")
        with self.assertRaises(ValueError):
            self.room.record_agent_note(self.note(related_seq=self.room.events[-1].seq))
        with self.assertRaises(ValueError):
            self.room.record_agent_note(self.note(request_id=secret.request_id))

    def test_failed_write_can_retry_without_a_phantom_note(self):
        note = self.note()
        before = self.path.read_bytes()
        with patch("engine.write_json", side_effect=OSError("磁盘繁忙")):
            with self.assertRaises(OSError):
                self.room.record_agent_note(note)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.room.events, [])
        self.assertEqual(self.room.record_agent_note(note).seq, 1)

    def test_archive_preserves_author_notes_without_exposing_other_players(self):
        own = self.room.record_agent_note(self.note(remember=True))
        other = self.note("other").model_copy(update={"seat_id": 2, "token": self.room.seats[2].token})
        self.room.record_agent_note(other)
        store = ArchiveStore(self.path.parent / "archives")
        store.save(self.room.snapshot().model_dump(mode="json"))
        exported = store.export(self.room.room_id, seat_id=1)
        self.assertEqual([event["seq"] for event in exported["events"]], [own.seq])
