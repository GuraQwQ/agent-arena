"""客户端续接、可靠接收与配置并发更新测试。"""

import argparse
import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import call, patch

from client import agent


class ClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch.object(agent, "CONFIG_FILE", self.root / ".agent.json").start()
        patch.object(agent, "EVENTS_FILE", self.root / "events.jsonl").start()
        patch.dict(agent.os.environ, {"ARENA_SERVER": "", "ARENA_SEAT": ""}).start()
        self.cfg = {"seat": 1, "token": "player", "server": "http://arena", "room_id": "room-one"}
        agent.save_config(self.cfg)
        self.output = io.StringIO()
        redirected = contextlib.redirect_stdout(self.output)
        redirected.__enter__()
        self.addCleanup(redirected.__exit__, None, None, None)
        self.event = {"seq": 1, "title": "新消息", "content": "可见内容"}

    def wait_args(self, follow=True, command="wait"):
        return argparse.Namespace(command=command, follow=follow, timeout=50)

    def journal(self):
        return [json.loads(line) for line in agent.EVENTS_FILE.read_text(encoding="utf-8").splitlines()]

    def test_follow_retries_connections_and_resets_backoff_after_timeout(self):
        outcomes = [SystemExit(2)] * 6 + [0, SystemExit(2), 43]
        with patch.object(agent, "receive_update", side_effect=outcomes), patch.object(agent.time, "sleep") as sleep:
            with self.assertRaises(SystemExit) as raised:
                agent.cmd_wait(self.wait_args())
        self.assertEqual(raised.exception.code, 43)
        self.assertEqual(sleep.call_args_list, [call(1), call(2), call(4), call(8), call(15), call(15), call(1)])

    def test_business_error_is_not_retried(self):
        with patch.object(agent, "receive_update", side_effect=SystemExit(1)), patch.object(agent.time, "sleep") as sleep:
            with self.assertRaises(SystemExit) as raised:
                agent.cmd_wait(self.wait_args())
        self.assertEqual(raised.exception.code, 1)
        sleep.assert_not_called()

    def test_http_denial_remains_a_business_error(self):
        denial = urllib.error.HTTPError("http://arena", 403, "Forbidden", {}, io.BytesIO(b'{"detail":"bad token"}'))
        with patch.object(agent.urllib.request, "urlopen", side_effect=denial):
            with self.assertRaises(SystemExit) as raised:
                agent.api_request(self.cfg, "GET", "/api/player/wait")
        self.assertEqual(raised.exception.code, 1)

    def test_wait_without_follow_keeps_single_timeout_behavior(self):
        with patch.object(agent, "receive_update", return_value=0) as receive:
            with self.assertRaises(SystemExit) as raised:
                agent.cmd_wait(self.wait_args(follow=False))
        self.assertEqual(raised.exception.code, 0)
        receive.assert_called_once_with(50)

    def test_ctrl_c_exits_without_a_traceback(self):
        with patch.object(agent, "receive_update", side_effect=KeyboardInterrupt):
            with self.assertRaises(SystemExit) as raised:
                agent.cmd_wait(self.wait_args(command="watch", follow=False))
        self.assertEqual(raised.exception.code, 130)

    def test_watch_alias_is_parsed(self):
        with patch.object(agent.sys, "argv", ["agent.py", "watch"]), patch.object(agent, "cmd_wait") as wait:
            agent.main()
        self.assertEqual(wait.call_args.args[0].command, "watch")

    def test_events_are_durable_before_ack_and_deduplicated_after_lost_ack(self):
        acknowledgement_attempts = []
        response = {"room_id": "room-one", "code": 43, "events": [self.event]}

        def request(cfg, method, path, **kwargs):
            if path.endswith("/wait"):
                return response
            self.assertEqual(self.journal(), [dict(self.event, room_id="room-one")])
            acknowledgement_attempts.append(kwargs["body"])
            if len(acknowledgement_attempts) == 1:
                raise SystemExit(2)
            return {}

        with patch.object(agent, "api_request", side_effect=request), patch.object(agent.time, "sleep"):
            with self.assertRaises(SystemExit) as raised:
                agent.cmd_wait(self.wait_args())
        self.assertEqual(raised.exception.code, 43)
        self.assertEqual(len(self.journal()), 1)
        self.assertEqual(len(acknowledgement_attempts), 2)

    def test_journal_deduplicates_per_room_and_repairs_an_interrupted_last_line(self):
        first = json.dumps(dict(self.event, room_id="room-one"), ensure_ascii=False).encode("utf-8") + b"\n"
        agent.EVENTS_FILE.write_bytes(first + b'{"seq": 2, "content": "\xe6\x96')
        second = dict(self.event, seq=2)
        self.assertEqual(agent.persist_events("room-one", [self.event, second, second]), [second])
        self.assertEqual([item["seq"] for item in self.journal()], [1, 2])
        self.assertEqual(agent.persist_events("room-two", [self.event]), [self.event])
        self.assertEqual([item["room_id"] for item in self.journal()], ["room-one", "room-one", "room-two"])

    def test_valid_final_record_without_newline_is_preserved(self):
        agent.EVENTS_FILE.write_text(json.dumps(dict(self.event, room_id="room-one")), encoding="utf-8")
        agent.persist_events("room-one", [dict(self.event, seq=2)])
        self.assertEqual([item["seq"] for item in self.journal()], [1, 2])

    def test_corrupt_interior_log_is_not_acknowledged(self):
        agent.EVENTS_FILE.write_text("损坏记录\n", encoding="utf-8")
        response = {"room_id": "room-one", "code": 43, "events": [self.event]}
        with patch.object(agent, "api_request", return_value=response) as request:
            with self.assertRaises(SystemExit) as raised:
                agent.receive_update(50)
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(agent.EVENTS_FILE.read_text(encoding="utf-8"), "损坏记录\n")

    def test_silent_timeout_does_not_rewrite_unchanged_configuration(self):
        with patch.object(agent, "api_request", return_value={"code": 0, "room_id": "room-one"}), patch.object(agent, "save_config") as save:
            self.assertEqual(agent.receive_update(50), 0)
        save.assert_not_called()

    def test_invalid_configuration_is_preserved(self):
        for damaged in ("{中断", "[]"):
            agent.CONFIG_FILE.write_text(damaged, encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                agent.load_config()
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(agent.CONFIG_FILE.read_text(encoding="utf-8"), damaged)

    def test_note_retry_preserves_one_id_and_original_action(self):
        self.cfg["pending_action"] = {"request_id": "original", "action_type": "SPEAK"}
        agent.save_config(self.cfg)
        with patch.object(agent.sys, "argv", ["agent.py", "note", "我现在准备先验证这个假设", "--remember"]), \
                patch.object(agent, "api_request", side_effect=SystemExit(2)):
            with self.assertRaises(SystemExit) as failure:
                agent.main()
        self.assertEqual(failure.exception.code, 2)
        pending = agent.load_config()["pending_notes"][0]
        current = agent.load_config()
        current["pending_action"] = {"request_id": "next", "action_type": "ACT"}
        agent.save_config(current)
        with patch.object(agent.sys, "argv", ["agent.py", "note", "--retry"]), \
                patch.object(agent, "api_request", return_value={"event_seq": 3}) as api:
            with self.assertRaises(SystemExit) as done:
                agent.main()
        self.assertEqual(done.exception.code, 0)
        sent = api.call_args.kwargs["body"]
        self.assertEqual(sent["note_id"], pending["note_id"])
        self.assertEqual(sent["created_at"], pending["created_at"])
        self.assertEqual(sent["request_id"], "original")
        self.assertNotIn("pending_notes", agent.load_config())
        self.assertEqual(agent.load_config()["pending_action"]["request_id"], "next")

    def test_successful_action_preserves_a_newer_pending_action(self):
        self.cfg["pending_action"] = {"request_id": "old-request", "action_type": "ACT"}
        agent.save_config(self.cfg)
        args = argparse.Namespace(
            file=None, content=["我的回答"], choice=None, value=None,
            data=None, type=None, reason=None, request_id=None,
        )

        def submitted(cfg, method, path, **kwargs):
            self.assertEqual(kwargs["body"]["request_id"], "old-request")
            latest = agent.load_config()
            latest["pending_action"] = {"request_id": "new-request", "action_type": "VOTE"}
            latest["room_title"] = "另一个进程的新配置"
            agent.save_config(latest)
            return {"event_seq": 2}

        with patch.object(agent, "api_request", side_effect=submitted):
            with self.assertRaises(SystemExit) as raised:
                agent.cmd_act(args)
        self.assertEqual(raised.exception.code, 0)
        current = agent.load_config()
        self.assertEqual(current["pending_action"]["request_id"], "new-request")
        self.assertEqual(current["room_title"], "另一个进程的新配置")
        self.assertNotIn("pending_submission", current)

    def test_other_room_unconfirmed_notes_are_retained_without_blocking_current_room(self):
        self.cfg["pending_notes"] = [{"note_id": "old", "room_id": "old-room", "seat_id": 1}]
        agent.save_config(self.cfg)
        with patch.object(agent.sys, "argv", ["agent.py", "note", "本局的新想法"]), \
                patch.object(agent, "api_request", return_value={"event_seq": 4}) as api:
            with self.assertRaises(SystemExit) as done:
                agent.main()
        self.assertEqual(done.exception.code, 0)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(api.call_args.kwargs["body"]["room_id"], "room-one")
        self.assertEqual(agent.load_config()["pending_notes"], self.cfg["pending_notes"])

    def test_action_prompt_once_and_structured_options_are_visible(self):
        action = {"request_id": "request", "prompt": "唯一指令", "action_type": "CHOOSE",
                  "action_options": [{"option_id": "choice-a", "text": "甲"}]}
        event = {**self.event, "content": "唯一指令", "event_type": "ACTION_REQUEST", "data": {"request_id": "request"}}
        with patch.object(agent, "api_request", return_value={"room_id": "room-one", "code": 42, "action": action, "events": [event]}):
            self.assertEqual(agent.receive_update(1), 42)
        self.assertEqual(self.output.getvalue().count("唯一指令"), 1)
        self.assertIn("choice-a: 甲", self.output.getvalue())

    def test_explicit_content_ignores_old_file_and_watch_follows_success(self):
        stale = self.root / "action.txt"
        stale.write_text("旧答案", encoding="utf-8")
        args = argparse.Namespace(file=None, content=["新答案"], choice=None, value=None,
                                  data=None, type=None, reason=None, request_id=None, watch=True)
        with patch.object(agent, "Path", return_value=stale), patch.object(agent, "save_config"), \
                patch.object(agent, "api_request", return_value={"event_seq": 1}) as api, \
                patch.object(agent, "cmd_wait", side_effect=SystemExit(42)) as wait:
            with self.assertRaises(SystemExit):
                agent.cmd_act(args)
        self.assertEqual(api.call_args.kwargs["body"]["content"], "新答案")
        self.assertEqual(stale.read_text(encoding="utf-8"), "旧答案")
        wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
