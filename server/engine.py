"""核心竞技场与状态调度引擎 (ArenaEngine)

负责座次管理、权限校验、严格视野过滤、长轮询挂起唤醒以及事件持久化。
"""

import asyncio
import errno
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from models import ActionRequest, ArenaSettings, Event, RoomSnapshot, Seat, VisibilityScope

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data"
SNAPSHOT_FILE = SNAPSHOT_DIR / "room_state.json"


class ArenaEngine:
    def __init__(self, room_title: str = "通用多智能体竞技场", restore_from_disk: bool = True):
        self.room_title = room_title
        self.phase = "准备中"
        self.round_num = 1
        self.settings = ArenaSettings()
        self._snapshot_lock = threading.Lock()
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

    def save_snapshot(self):
        """原子落盘保存当前对局全量快照"""
        with self._snapshot_lock:
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            snapshot = RoomSnapshot(
                room_title=self.room_title,
                phase=self.phase,
                round_num=self.round_num,
                seq_counter=self._seq_counter,
                seats=self.seats,
                events=self.events,
                active_actions=self.active_actions,
                last_seen_seqs=self.last_seen_seqs,
                settings=self.settings
            )
            tmp_file = SNAPSHOT_FILE.with_name(f".{SNAPSHOT_FILE.name}.{uuid.uuid4().hex}.tmp")
            try:
                with tmp_file.open("w", encoding="utf-8") as handle:
                    handle.write(snapshot.model_dump_json(indent=2))
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except OSError as exc:
                        if exc.errno != errno.EBADF:
                            raise
                tmp_file.replace(SNAPSHOT_FILE)
            finally:
                try:
                    tmp_file.unlink()
                except FileNotFoundError:
                    pass

    def load_snapshot(self) -> bool:
        """从磁盘加载恢复快照"""
        if not SNAPSHOT_FILE.exists():
            return False
        try:
            content = SNAPSHOT_FILE.read_text(encoding="utf-8")
            snapshot = RoomSnapshot.model_validate_json(content)
            self.room_title = snapshot.room_title
            self.phase = snapshot.phase
            self.round_num = snapshot.round_num
            self._seq_counter = snapshot.seq_counter
            self.seats = snapshot.seats
            self.events = snapshot.events
            self.active_actions = snapshot.active_actions
            self.last_seen_seqs = snapshot.last_seen_seqs or {sid: 0 for sid in self.seats}
            self.settings = snapshot.settings
            migrated = False
            for sid, seat in self.seats.items():
                if not seat.claim_token:
                    seat.claim_token = uuid.uuid4().hex
                    migrated = True
                self.last_seen_seqs.setdefault(sid, 0)
            if migrated:
                self.save_snapshot()
            return True
        except Exception as e:
            print(f"⚠️ 读取历史快照失败，将初始化新对局: {e}")
            return False

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
            existing.role = role or existing.role
            existing.model = model or existing.model
            existing.harness = harness or existing.harness
            existing.last_seen = now
            existing.status = "IDLE"
            self.save_snapshot()
            self.broadcast_host_update()
            return existing

        if claim_token and existing.claim_token == claim_token:
            existing.name = name or existing.name
            existing.role = role or existing.role
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
            return event.to_seat == seat_id or event.from_seat == seat_id
        
        # 分组阵营
        if event.scope == VisibilityScope.GROUP:
            seat = self.seats.get(seat_id)
            return bool(seat and seat.group_id and seat.group_id == event.group_id)
            
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
        if target_seat in self._wait_events:
            self._wait_events[target_seat].set()

        self.broadcast_host_update()
        return req

    def submit_action(self, seat_id: int, token: str, action_type: str, content: str, secret_reason: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> Event:
        """处理 Agent 提交的行动结果"""
        if not self.verify_token(seat_id, token):
            raise PermissionError("无效的座次令牌")

        pending = self.active_actions.get(seat_id)
        if pending:
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
        self.broadcast_host_update()
        return event

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
            if new_events:
                self.last_seen_seqs[seat_id] = new_events[-1]["seq"]
            return {
                "code": 42,
                "status": "ACTION_REQUIRED",
                "action": action.model_dump(),
                "recent_events": new_events
            }

        # 2. 检查是否有未读的观察更新 (Pre-think 43)
        last_seq = self.last_seen_seqs.get(seat_id, 0)
        unseen_events = self.filter_events_for_seat(seat_id, since_seq=last_seq)
        if unseen_events:
            self.last_seen_seqs[seat_id] = unseen_events[-1]["seq"]
            return {
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
            if recent:
                self.last_seen_seqs[seat_id] = recent[-1]["seq"]
            return {
                "code": 42,
                "status": "ACTION_REQUIRED",
                "action": action.model_dump(),
                "recent_events": recent
            }

        # 5. 唤醒后检查是否是观察更新
        fresh_events = self.filter_events_for_seat(seat_id, since_seq=self.last_seen_seqs.get(seat_id, 0))
        if fresh_events:
            self.last_seen_seqs[seat_id] = fresh_events[-1]["seq"]
            return {
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
        data = event.model_dump()
        for q in self.sse_queues:
            q.put_nowait({"type": "EVENT", "data": data})

    def broadcast_host_update(self):
        """推送全量座次状态快照更新"""
        snapshot = self.get_host_snapshot()
        for q in self.sse_queues:
            q.put_nowait({"type": "SNAPSHOT", "data": snapshot})

    def reset(self):
        """在保留现有 SSE 连接的情况下重置房间"""
        self.clear_snapshot()
        for waiter in self._wait_events.values():
            waiter.set()
        self._reset_generation += 1
        self.phase = "准备中"
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
            "room_title": self.room_title,
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
