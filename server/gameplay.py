"""主持人加载的本地游戏 Mod；状态仍由 Arena 的事务和快照管理。"""

from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from models import VisibilityScope
from mods import load_entry, read_manifest

GAMES_ROOT = Path(__file__).resolve().parents[1] / "games"
ACTIVE_MODULES = {}


def load_mod(name: str):
    return ACTIVE_MODULES[name] if name in ACTIVE_MODULES else _load_unmanaged(name)


@lru_cache(maxsize=32)
def _load_unmanaged(name):
    return load_entry(GAMES_ROOT, read_manifest(GAMES_ROOT, name))


class GameDriver:
    def __init__(self, room):
        self.room = room

    def module(self):
        module = load_mod(self.room.game["name"])
        if str(module.VERSION) != str(self.room.game["version"]):
            raise ValueError("游戏规则版本已改变，请恢复对应版本的 Mod 后继续")
        return module

    def start(self, name, seat_ids, options):
        if self.room.active_actions or self.room.flow.status in {"RUNNING", "PAUSED", "AWAITING_HOST"} or self.room.game_active():
            raise ValueError("请先结束当前行动、流程或游戏")
        if len(set(seat_ids)) != len(seat_ids) or any(sid not in self.room.seats for sid in seat_ids):
            raise ValueError("游戏参与席位必须存在且不能重复")
        module = load_mod(name)
        game_options = dict(options)
        game_options.setdefault("mod_settings", dict(self.room.mod_settings.get(name, {})))
        state = module.create(seat_ids, game_options)
        self.room.game = {"id": uuid4().hex, "name": name, "version": module.VERSION,
                          "status": "RUNNING", "state": state}
        self.room.record_event("GAME_START", f"【游戏开始】{name}", f"参与席位：{seat_ids}")
        self.advance()

    def advance(self):
        game = self.room.game
        state = game["state"]
        self.room.phase = state.get("phase", self.room.phase)
        self.room.round_num = state.get("turn", self.room.round_num)
        if state.get("finished"):
            game["status"] = "FINISHED"
        specifications = [] if game["status"] != "RUNNING" else self.module().requests(state)
        targets = {}
        for specification in specifications:
            specification = dict(specification)
            seat_id = specification.pop("target_seat")
            key = str(specification.pop("key", state.get("turn", 0)))
            action_options = specification.pop("action_options", None)
            if seat_id in targets:
                raise ValueError("每个席位只能有一个当前游戏行动")
            targets[seat_id] = (key, specification, action_options)
        for seat_id, pending in list(self.room.active_actions.items()):
            if pending.game_id != game["id"]:
                continue
            if seat_id not in targets or pending.game_key != targets[seat_id][0]:
                self.room.active_actions.pop(seat_id)
                self.room.seats[seat_id].status = "IDLE"
                self.room.record_event("ACTION_CANCEL", "【游戏行动更新】", "游戏局势已更新，请重新获取当前指令",
                    to_seat=seat_id, scope=VisibilityScope.PRIVATE, data={"request_id": pending.request_id})
        for seat_id, (key, specification, action_options) in targets.items():
            if seat_id not in self.room.active_actions:
                specification.setdefault("action_type", "ACT")
                specification.setdefault("result_scope", VisibilityScope.HOST_ONLY)
                self.room.dispatch_action(seat_id, game_id=game["id"], game_key=key,
                                          action_options=action_options, **specification)

    def submit(self, seat_id, data):
        game = self.room.game
        if game["status"] != "RUNNING":
            raise ValueError("游戏当前未运行")
        events = self.module().step(game["state"], seat_id, data)
        for event in events:
            self.room.record_event(event_type="GAME_EVENT", **event)
        self.advance()

    def control(self, operation):
        game = self.room.game
        if not game:
            raise ValueError("当前没有游戏")
        if operation == "resume" and game["status"] == "PAUSED":
            game["status"] = "RUNNING"
        elif operation in {"pause", "stop"} and game["status"] in {"RUNNING", "PAUSED"}:
            game["status"] = "PAUSED" if operation == "pause" else "STOPPED"
        else:
            raise ValueError("当前游戏状态不支持该操作")
        self.advance()
        self.room.record_event("GAME_CONTROL", "【游戏控制】", {"pause": "游戏已暂停", "resume": "游戏已继续", "stop": "游戏已停止"}[operation])

    def observe(self, seat_id):
        game = self.room.game
        if not game:
            return {"room_id": self.room.room_id, "game": None}
        pending = self.room.active_actions.get(seat_id)
        return {"room_id": self.room.room_id, "name": game["name"], "status": game["status"],
                "state": self.module().observe(game["state"], seat_id),
                "action": pending.model_dump(exclude={"result_recipients"}) if pending else None}
