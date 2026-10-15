"""核心竞技场与状态调度引擎 (ArenaEngine)

负责座次管理、权限校验、严格视野过滤、长轮询挂起唤醒以及事件持久化。
"""

import asyncio
import json
import threading
import time
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional

from models import ActionRequest, ArenaSettings, Event, RoomSnapshot, Scenario, Seat, SeatDefinition, VisibilityScope
from archives import ArchiveStore
from storage import write_json

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data"
SNAPSHOT_FILE = SNAPSHOT_DIR / "room_state.json"


def mutating(method):
    """状态与快照一起提交，写入失败时还原内存，再发送通知。"""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._state_lock:
            if self._changing:
                return method(self, *args, **kwargs)
            before = self.snapshot().model_copy(deep=True)
            generation = self._reset_generation
            self._changing = True
            try:
                result = method(self, *args, **kwargs)
                self._changing = False
                self.save_snapshot()
            except BaseException:
                self._changing = False
                self._apply_snapshot(before)
                self._reset_generation = generation
                raise
            if generation != self._reset_generation:
                for waiter in list(self._wait_events.values()):
                    waiter.set()
            for event in self.events:
                if self.room_id == before.room_id and event.seq <= before.seq_counter:
                    continue
                self._notify_relevant_waiters(event)
                self._notify_sse(event)
            self.broadcast_host_update()
            return result
    return wrapped


class ArenaEngine:
    def __init__(self, room_title: str = "通用多智能体竞技场", restore_from_disk: bool = True):
        self.room_title = room_title
        self.scenario_description = ""
        self.room_id = uuid.uuid4().hex
        self.phase = "准备中"
        self.round_num = 1
        self.settings = ArenaSettings()
        self._snapshot_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._changing = False
        self.receipts = {}
        self._reset_generation = 0
        
        # 座次映射: seat_id -> Seat
        self.seats: Dict[int, Seat] = {}
        # 历史事件全局流
        self.events: List[Event] = []
        # 自增序列号
        self._seq_counter = 0
        
        # 长轮询等待唤醒字典: seat_id -> asyncio.Event
        self._wait_events: Dict[int, asyncio.Event] = {}
        
        # 当前活跃的行动指令: seat_id -> ActionRequest
        self.active_actions: Dict[int, ActionRequest] = {}
        
        # 智能体未读观察事件游标: seat_id -> last_seen_seq
        self.last_seen_seqs: Dict[int, int] = {}
        
        # 主持人 Web 控制台 SSE 订阅队列列表
        self.sse_queues: List[asyncio.Queue] = []

        # 尝试从磁盘快照恢复对局
        if restore_from_disk and self.load_snapshot():
            print(f"📦 已从磁盘恢复历史对局状态: {len(self.seats)} 个席位, {len(self.events)} 条事件")
        else:
            self._initialize_seats()
            self.save_snapshot()

    def _initialize_seats(self):
        """初始化主持人预留的四个席位"""
        for i in range(1, 5):
            self.seats[i] = Seat(
                seat_id=i,
                name=f"Agent_{i}",
                role=f"探索者_{i}",
                model="未接入",
                harness="未接入",
                token=f"token-{i}-{uuid.uuid4().hex[:6]}",
                claim_token=uuid.uuid4().hex,
                status="IDLE",
                init_prompt=f"你是本局沙盒推演的 {i}号智能体。你的目标是仔细观察公开局势与私信情报，在主持人点名时做出最佳决策。",
                last_seen=0.0
            )
            self.last_seen_seqs[i] = 0

    def snapshot(self) -> RoomSnapshot:
        return RoomSnapshot(
            room_id=self.room_id, room_title=self.room_title, phase=self.phase,
            round_num=self.round_num, seq_counter=self._seq_counter, seats=self.seats,
            events=self.events, active_actions=self.active_actions,
            last_seen_seqs=self.last_seen_seqs, settings=self.settings, receipts=self.receipts,
            scenario_description=self.scenario_description
        )

    def _apply_snapshot(self, snapshot: RoomSnapshot):
        self.room_id = snapshot.room_id
        self.room_title = snapshot.room_title
        self.scenario_description = snapshot.scenario_description
        self.phase = snapshot.phase
        self.round_num = snapshot.round_num
        self._seq_counter = snapshot.seq_counter
        self.seats = snapshot.seats
        self.events = snapshot.events
        self.active_actions = snapshot.active_actions
        self.last_seen_seqs = snapshot.last_seen_seqs
        self.settings = snapshot.settings
        self.receipts = snapshot.receipts

    def save_snapshot(self):
        """原子落盘保存当前对局全量快照"""
        if self._changing:
            return
        with self._snapshot_lock:
            write_json(SNAPSHOT_FILE, self.snapshot().model_dump(mode="json"))

    def load_snapshot(self) -> bool:
        """从磁盘加载恢复快照"""
        if not SNAPSHOT_FILE.exists():
            return False
        raw = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
        if raw.get("schema_version", 1) > 2:
            raise ValueError("快照版本高于当前服务版本，请使用对应版本启动")
        snapshot = RoomSnapshot.model_validate(raw)
        if raw.get("schema_version", 1) < 2:
            backup = SNAPSHOT_FILE.with_suffix(".v1.bak")
            if not backup.exists():
                write_json(backup, raw)
            snapshot.last_seen_seqs = {sid: 0 for sid in snapshot.seats}
            snapshot.schema_version = 2
        self._apply_snapshot(snapshot)
        for event in self.events:
            if event.recipient_seats is None and event.scope != VisibilityScope.PUBLIC:
                event.recipient_seats = self._recipients(event.scope, event.from_seat, event.to_seat, event.group_id)
        for sid, seat in self.seats.items():
            if not seat.claim_token:
                seat.claim_token = uuid.uuid4().hex
            self.last_seen_seqs.setdefault(sid, 0)
            if seat.status == "WAITING":
                seat.status = "IDLE"
        self.save_snapshot()
        return True

    def clear_snapshot(self):
        """清空磁盘快照"""
        try:
            if SNAPSHOT_FILE.exists():
                SNAPSHOT_FILE.unlink()
        except OSError as e:
            print(f"⚠️ 清理快照失败: {e}")

    def _next_seq(self) -> int:
        self._seq_counter += 1
        return self._seq_counter

    @mutating
    def join_seat(
        self,
        seat_id: int,
        name: str,
        role: str,
        model: str,
        harness: str,
        token: Optional[str] = None,
        claim_token: Optional[str] = None
    ) -> Seat:
        """Agent 使用主持人发放的认领令牌入座，或使用玩家令牌重连"""
        now = time.time()
        existing = self.seats.get(seat_id)

        if not existing:
            raise ValueError("席位不存在，只能使用主持人预留的席位")

        if token and existing.token == token:
            # 携带有效 token 重连
            existing.name = name or existing.name
            existing.model = model or existing.model
            existing.harness = harness or existing.harness
            existing.last_seen = now
            existing.status = "IDLE"
            self.save_snapshot()
            self.broadcast_host_update()
            return existing

        if claim_token and existing.claim_token == claim_token:
            existing.name = name or existing.name
            existing.model = model or existing.model
            existing.harness = harness or existing.harness
            existing.last_seen = now
            existing.status = "IDLE"
            self.record_event(
                event_type="SYSTEM",
                title=f"【入座】{seat_id}号位已接入",
                content=f"{seat_id}号位 [{existing.name}] 已入座 (模型: {existing.model}, 环境: {existing.harness})",
                from_seat=seat_id,
                scope=VisibilityScope.PUBLIC
            )
            return existing

        raise PermissionError("席位已被认领，请使用主持人发放的自举口令或已有玩家令牌")

    def verify_token(self, seat_id: int, token: str) -> bool:
        """验证座次令牌有效性"""
        seat = self.seats.get(seat_id)
        return bool(seat and seat.token == token)

    def verify_claim_token(self, seat_id: int, claim_token: str) -> bool:
        """验证主持人发放的席位认领令牌"""
        seat = self.seats.get(seat_id)
        return bool(seat and claim_token and seat.claim_token == claim_token)

    def get_scenario(self) -> Scenario:
        return Scenario(
            title=self.room_title, description=self.scenario_description,
            seats=[SeatDefinition.model_validate(seat.model_dump()) for seat in self.seats.values()],
            settings=self.settings
        )

    @mutating
    def update_seat(self, definition: SeatDefinition):
        seat = self.seats.get(definition.seat_id)
        if seat is None:
            if len(self.seats) >= 64:
                raise ValueError("最多支持 64 个席位")
            seat = Seat(seat_id=definition.seat_id, token=uuid.uuid4().hex, claim_token=uuid.uuid4().hex)
            self.seats[seat.seat_id] = seat
            self.last_seen_seqs[seat.seat_id] = 0
        for key, value in definition.model_dump().items():
            setattr(seat, key, value)
        return seat

    @mutating
    def remove_seat(self, seat_id: int):
        if seat_id not in self.seats:
            raise ValueError("席位不存在")
        if len(self.seats) == 1:
            raise ValueError("至少保留一个席位")
        if seat_id in self.active_actions:
            raise ValueError("请先完成或取消该席位的待办行动")
        self.seats.pop(seat_id)
        self.last_seen_seqs.pop(seat_id, None)

    @mutating
    def load_scenario(self, scenario: Scenario):
        self.reset()
        self.room_title = scenario.title
        self.scenario_description = scenario.description
        self.settings = scenario.settings.model_copy(deep=True)
        self.seats = {}
        self.last_seen_seqs = {}
        for seat in scenario.seats:
            self.update_seat(seat)

    def _recipients(self, scope, from_seat=None, to_seat=None, group_id=None):
        if scope == VisibilityScope.PUBLIC:
            return None
        if scope == VisibilityScope.PRIVATE:
            return sorted({sid for sid in (from_seat, to_seat) if sid is not None})
        if scope == VisibilityScope.GROUP:
            return [sid for sid, seat in self.seats.items() if group_id and seat.group_id == group_id]
        return []

    @mutating
    def update_settings(self, fields: dict):
        self.settings = ArenaSettings.model_validate({**self.settings.model_dump(), **fields})

    @mutating
    def advance_phase(self, phase: Optional[str], round_num: Optional[int]):
        self.phase = phase or self.phase
        self.round_num = round_num if round_num is not None else self.round_num
        self.record_event("PHASE_CHANGE", f"【阶段变更】进入阶段: {self.phase}", f"主持人已将当前场景切换为: {self.phase}")

    @mutating
    def record_event(
        self,
        event_type: str,
        title: str,
        content: str,
        from_seat: Optional[int] = None,
        to_seat: Optional[int] = None,
        group_id: Optional[str] = None,
        scope: VisibilityScope = VisibilityScope.PUBLIC,
        secret_reason: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Event:
        """记录事件并精准触发通知"""
        event = Event(
            seq=self._next_seq(),
            timestamp=time.time(),
            round_num=self.round_num,
            event_type=event_type,
            title=title,
            content=content,
            from_seat=from_seat,
            to_seat=to_seat,
            group_id=group_id,
            scope=scope,
            recipient_seats=self._recipients(scope, from_seat, to_seat, group_id),
            secret_reason=secret_reason,
            data=data or {}
        )
        self.events.append(event)

        # 先完成快照，再唤醒 Agent，避免通知到未持久化的事件
        self.save_snapshot()
        self._notify_relevant_waiters(event)
        self._notify_sse(event)
        return event

    def _notify_relevant_waiters(self, event: Event):
        """精准唤醒相关 Agent 的长轮询"""
        if self._changing:
            return
        for seat_id, waiter in self._wait_events.items():
            if waiter.is_set():
                continue
            
            # 判断该座次是否对该事件可见
            if self._is_event_visible_to_seat(event, seat_id):
                waiter.set()

    def _is_event_visible_to_seat(self, event: Event, seat_id: int) -> bool:
        """判定单个事件是否对指定座次可见 (严格视野隔离)"""
        # 仅主持人可见的事件，对任何普通智能体不可见
        if event.scope == VisibilityScope.HOST_ONLY:
            return False
        
        # 全员公开
        if event.scope == VisibilityScope.PUBLIC:
            return True
        
        # 私信定向
        if event.scope == VisibilityScope.PRIVATE:
            return seat_id in (event.recipient_seats or [])
        
        # 分组阵营
        if event.scope == VisibilityScope.GROUP:
            return seat_id in (event.recipient_seats or [])
            
        return False

    def _is_event_in_history_window(self, event: Event, now: Optional[float] = None) -> bool:
        """按当前设置判断事件是否仍在可见历史窗口内"""
        if self.settings.history_rounds is not None:
            first_round = max(1, self.round_num - self.settings.history_rounds + 1)
            if event.round_num < first_round:
                return False
        if self.settings.history_seconds is not None:
            current_time = time.time() if now is None else now
            if event.timestamp < current_time - self.settings.history_seconds:
                return False
        return True

    def filter_events_for_seat(self, seat_id: int, since_seq: int = 0) -> List[Dict[str, Any]]:
        """为特定座次拉取可见事件流，严格抹除 secret_reason 与不可见条目"""
        result = []
        now = time.time()
        for e in self.events:
            if e.seq <= since_seq:
                continue
            if not self._is_event_in_history_window(e, now):
                continue
            if self._is_event_visible_to_seat(e, seat_id):
                item = e.model_dump()
                # 即使是自己发出的事件，对外分发时也绝不携带 secret_reason 避免回显污染
                item["secret_reason"] = None
                result.append(item)
        return result

    @mutating
    def dispatch_action(self, target_seat: int, action_type: str, prompt: str, options: Optional[List[str]] = None, timeout: int = 60) -> ActionRequest:
        """主持人向指定 Agent 下达行动命令 (点名)"""
        if target_seat not in self.seats:
            raise ValueError("目标席位不存在")
        if target_seat in self.active_actions:
            raise ValueError("该席位已有未完成行动")
        if timeout <= 0:
            raise ValueError("行动限时必须大于 0 秒")
        req_id = str(uuid.uuid4())[:8]
        req = ActionRequest(
            request_id=req_id,
            target_seat=target_seat,
            phase=self.phase,
            action_type=action_type,
            prompt=prompt,
            options=options or [],
            deadline=time.time() + timeout
        )
        self.active_actions[target_seat] = req
        
        if target_seat in self.seats:
            self.seats[target_seat].status = "THINKING"

        # 记录行动下达事件 (仅被点名者与主持人可见)
        self.record_event(
            event_type="ACTION_REQUEST",
            title=f"【行动指引】轮到 {target_seat}号位 行动",
            content=f"主持人指示 {target_seat}号位 执行 [{action_type}]: {prompt}",
            to_seat=target_seat,
            scope=VisibilityScope.PRIVATE,
            data={"request_id": req_id, "action_type": action_type}
        )

        # 唤醒该 Agent 的长轮询 (触发退出码 42)
        if not self._changing and target_seat in self._wait_events:
            self._wait_events[target_seat].set()

        self.broadcast_host_update()
        return req

    @mutating
    def submit_action(self, seat_id: int, token: str, action_type: str, content: str, request_id: str, secret_reason: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> Event:
        """处理 Agent 提交的行动结果"""
        if not self.verify_token(seat_id, token):
            raise PermissionError("无效的座次令牌")

        receipt_key = f"{seat_id}:{request_id}"
        payload = {"action_type": action_type, "content": content, "secret_reason": secret_reason, "data": data}
        if receipt_key in self.receipts:
            receipt = self.receipts[receipt_key]
            if receipt["payload"] != payload:
                raise ValueError("同一行动编号不能重复提交不同内容")
            return next(event for event in self.events if event.seq == receipt["event_seq"])

        pending = self.active_actions.get(seat_id)
        if pending:
            if pending.request_id != request_id or pending.phase != self.phase:
                raise ValueError("行动编号或阶段已变更，请重新获取主持人指令")
            if pending.action_type != action_type:
                raise ValueError("提交的动作类型与主持人指令不匹配")
            if pending.deadline <= time.time():
                self.active_actions.pop(seat_id, None)
                raise TimeoutError("行动已超过截止时间")
        elif not self.settings.allow_free_actions:
            raise PermissionError("当前没有待办行动")

        # 检查并清除待办行动
        self.active_actions.pop(seat_id, None)
        if seat_id in self.seats:
            self.seats[seat_id].status = "IDLE"

        # 记录行动事件
        event = self.record_event(
            event_type="ACTION_SUBMIT",
            title=f"【行动提交】{seat_id}号位 完成行动 [{action_type}]",
            content=content,
            from_seat=seat_id,
            scope=VisibilityScope.PUBLIC,
            secret_reason=secret_reason,
            data=data or {"action_type": action_type}
        )
        self.receipts[receipt_key] = {"event_seq": event.seq, "payload": payload}
        self.broadcast_host_update()
        return event

    @mutating
    def acknowledge(self, seat_id: int, token: str, room_id: str, seq: int):
        if not self.verify_token(seat_id, token):
            raise PermissionError("无效的座次令牌")
        if room_id != self.room_id or not 0 <= seq <= self._seq_counter:
            raise ValueError("确认游标不属于当前对局")
        self.last_seen_seqs[seat_id] = max(self.last_seen_seqs.get(seat_id, 0), seq)

    async def wait_turn(self, seat_id: int, token: str, timeout: int = 50) -> Dict[str, Any]:
        """长轮询挂起等待核心逻辑"""
        if not self.verify_token(seat_id, token):
            raise PermissionError("无效的座次令牌")

        seat = self.seats[seat_id]
        seat.last_seen = time.time()
        seat.status = "WAITING"

        # 1. 如果已有待办行动，立即返回 42 (ACTION_REQUIRED)
        action = self.active_actions.get(seat_id)
        if action and action.deadline <= time.time():
            self.active_actions.pop(seat_id, None)
            action = None
            seat.status = "IDLE"
        if action:
            seat.status = "THINKING"
            last_seq = self.last_seen_seqs.get(seat_id, 0)
            new_events = self.filter_events_for_seat(seat_id, since_seq=last_seq)
            return {
                "room_id": self.room_id,
                "code": 42,
                "status": "ACTION_REQUIRED",
                "action": action.model_dump(),
                "recent_events": new_events
            }

        # 2. 检查是否有未读的观察更新 (Pre-think 43)
        last_seq = self.last_seen_seqs.get(seat_id, 0)
        unseen_events = self.filter_events_for_seat(seat_id, since_seq=last_seq)
        if unseen_events:
            return {
                "room_id": self.room_id,
                "code": 43,
                "status": "OBSERVE_UPDATE",
                "events": unseen_events,
                "message": "视野内有新事件发生，请简短更新本地 memory.md 并立即重启 wait。"
            }

        # 3. 进入挂起等待
        wait_event = asyncio.Event()
        generation = self._reset_generation
        self._wait_events[seat_id] = wait_event

        try:
            await asyncio.wait_for(wait_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            if self._wait_events.get(seat_id) is wait_event:
                self._wait_events.pop(seat_id, None)

        seat.last_seen = time.time()

        if generation != self._reset_generation:
            return {
                "code": 0,
                "status": "RESET",
                "message": "房间已重置，请重新开始监听。"
            }

        # 4. 唤醒后再次检查行动指令
        action = self.active_actions.get(seat_id)
        if action and action.deadline <= time.time():
            self.active_actions.pop(seat_id, None)
            action = None
        if action:
            seat.status = "THINKING"
            recent = self.filter_events_for_seat(seat_id, since_seq=self.last_seen_seqs.get(seat_id, 0))
            return {
                "room_id": self.room_id,
                "code": 42,
                "status": "ACTION_REQUIRED",
                "action": action.model_dump(),
                "recent_events": recent
            }

        # 5. 唤醒后检查是否是观察更新
        fresh_events = self.filter_events_for_seat(seat_id, since_seq=self.last_seen_seqs.get(seat_id, 0))
        if fresh_events:
            return {
                "room_id": self.room_id,
                "code": 43,
                "status": "OBSERVE_UPDATE",
                "events": fresh_events,
                "message": "收到新事件更新，更新私有思考后重启 wait。"
            }

        # 6. 超时静默退出
        seat.status = "IDLE"
        return {
            "code": 0,
            "status": "TIMEOUT",
            "message": "长轮询超时无事件，请自动重启 wait。"
        }

    def _notify_sse(self, event: Event):
        """向所有连接的 Web 控制台推送增量事件"""
        if self._changing:
            return
        data = event.model_dump()
        for q in self.sse_queues:
            q.put_nowait({"type": "EVENT", "data": data})

    def broadcast_host_update(self):
        """推送全量座次状态快照更新"""
        if self._changing:
            return
        snapshot = self.get_host_snapshot()
        for q in self.sse_queues:
            q.put_nowait({"type": "SNAPSHOT", "data": snapshot})

    @mutating
    def reset(self):
        """在保留现有 SSE 连接的情况下重置房间"""
        if self.events or self.active_actions:
            ArchiveStore(SNAPSHOT_FILE.parent / "archives").save(self.snapshot().model_dump(mode="json"))
        self._reset_generation += 1
        self.room_id = uuid.uuid4().hex
        self.receipts = {}
        self.phase = "准备中"
        self.scenario_description = ""
        self.round_num = 1
        self.settings = ArenaSettings()
        self.seats = {}
        self.events = []
        self._seq_counter = 0
        self.active_actions = {}
        self.last_seen_seqs = {}
        self._initialize_seats()
        self.save_snapshot()

    def get_host_snapshot(self) -> Dict[str, Any]:
        """获取主持人上帝视角全量快照"""
        now = time.time()
        return {
            "room_id": self.room_id,
            "room_title": self.room_title,
            "scenario_description": self.scenario_description,
            "phase": self.phase,
            "round_num": self.round_num,
            "settings": self.settings.model_dump(),
            "seats": {
                sid: s.model_dump(exclude={"token"})
                for sid, s in self.seats.items()
            },
            "active_actions": {sid: a.model_dump() for sid, a in self.active_actions.items()},
            "events": [
                e.model_dump()
                for e in self.events
                if self._is_event_in_history_window(e, now)
            ]
        }
