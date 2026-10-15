"""连接状态与待办状态分别反映，取消轮询后及时移除监听状态。"""

import asyncio
from unittest.mock import patch

from test_engine import EngineCase


class PresenceTest(EngineCase):
    def test_connection_is_derived_from_recent_requests(self):
        self.assertEqual(self.room.get_host_snapshot()["seats"][1]["connection_status"], "NEVER")
        with patch("engine.time.time", return_value=100):
            self.room.join_seat(1, "", "", "", "", token=self.room.seats[1].token)
        with patch("engine.time.time", return_value=174):
            self.assertEqual(self.room.get_host_snapshot()["seats"][1]["connection_status"], "RECENT")
        with patch("engine.time.time", return_value=176):
            self.assertEqual(self.room.get_host_snapshot()["seats"][1]["connection_status"], "OFFLINE")

    def test_wait_cancel_removes_listener(self):
        async def check():
            waiter = asyncio.create_task(self.room.wait_turn(1, self.room.seats[1].token, 50))
            await asyncio.sleep(0)
            self.assertEqual(self.room.get_host_snapshot()["seats"][1]["connection_status"], "LISTENING")
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertEqual(self.room.get_host_snapshot()["seats"][1]["connection_status"], "RECENT")
            self.assertEqual(self.room.seats[1].status, "IDLE")
        asyncio.run(check())
