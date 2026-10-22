"""数据模型定义 (Pydantic v2)

定义 Agent Arena 的事件、座次、视野范围与行动调度结构。
"""

from enum import Enum
from uuid import uuid4
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

try:
    from .capabilities import ActionOption
except ImportError:
    from capabilities import ActionOption


class VisibilityScope(str, Enum):
    """事件视野可见性枚举"""
    PUBLIC = "PUBLIC"          # 全员可见
    PRIVATE = "PRIVATE"        # 仅目标 Agent 可见 (由 to_seat 确定)
    GROUP = "GROUP"            # 仅指定阵营/分组可见 (由 group_id 确定)
    HOST_ONLY = "HOST_ONLY"    # 仅主持人可见 (秘密动作、Agent心声)


class Event(BaseModel):
    """全局事件条目"""
    seq: int = Field(..., description="自增全局序号")
    timestamp: float = Field(..., description="产生时间戳")
    round_num: int = Field(1, ge=1, description="产生时所在回合")
    event_type: str = Field(..., description="事件类型 (ANNOUNCEMENT, SPEECH, ACTION, SYSTEM)")
    title: str = Field(..., description="事件概要或标题")
    content: str = Field(..., description="公开或给接收者看的内容主体")
    from_seat: Optional[int] = Field(None, description="发送者座次，None表示主持人/系统")
    to_seat: Optional[int] = Field(None, description="接收者座次 (PRIVATE 模式时必填)")
    group_id: Optional[str] = Field(None, description="所属分组 (GROUP 模式时使用)")
    scope: VisibilityScope = Field(VisibilityScope.PUBLIC, description="可见性范围")
    recipient_seats: Optional[List[int]] = None
    secret_reason: Optional[str] = Field(None, description="仅主持人可见的行动附注")
    data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="结构化附加元数据")


class Seat(BaseModel):
    """座次与智能体注册信息"""
    seat_id: int
    name: str = ""
    role: str = "玩家"
    model: str = "未知模型"
    avatar_id: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")
    harness: str = "未知环境"
    token: str = ""
    claim_token: str = ""
    status: str = "IDLE"  # IDLE (空闲), THINKING (行动思考中), WAITING (长轮询等待中)
    group_id: Optional[str] = None
    init_prompt: str = ""  # 主持人预设的专属初始提示词/目标
    last_seen: float = 0.0


class ActionRequest(BaseModel):
    """主持人向特定 Agent 下达的行动指令"""
    request_id: str
    target_seat: int
    phase: str
    action_type: str = "ACT"  # SPEAK(公开发言), ACT(执行动作/技能), VOTE(投票), FREE(自由阐述)
    prompt: str = ""          # 主持人下发的行动指引与要求
    options: List[str] = []   # 可选动作列表 (如有)
    action_options: Optional[List[ActionOption]] = None
    deadline: float = 0.0     # 截止时间戳
    result_scope: VisibilityScope = VisibilityScope.PUBLIC
    result_target_seat: Optional[int] = None
    result_group_id: Optional[str] = None
    result_recipients: Optional[List[int]] = None
    min_value: Optional[float] = Field(None, allow_inf_nan=False)
    max_value: Optional[float] = Field(None, allow_inf_nan=False)
    flow_index: Optional[int] = None
    game_id: Optional[str] = None
    game_key: Optional[str] = None


class ActionSubmission(BaseModel):
    """Agent 提交的行动结果"""
    seat_id: int
    token: str
    request_id: str = Field(..., min_length=1, max_length=128)
    action_type: str
    content: str
    secret_reason: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class HostCommand(BaseModel):
    """主持人控制指令"""
    command_type: str  # ADVANCE_PHASE, BROADCAST, SEND_PRIVATE, DISPATCH_ACTION, RESET
    phase: Optional[str] = None
    target_seat: Optional[int] = None
    group_id: Optional[str] = None
    content: Optional[str] = None
    secret_reason: Optional[str] = None
    prompt: Optional[str] = None
    options: Optional[List[str]] = None
    action_options: Optional[List[ActionOption]] = None
    timeout: Optional[int] = Field(60, ge=1, le=86400)
    round_num: Optional[int] = Field(None, ge=1)
    action_type: Literal["ACT", "SPEAK", "VOTE", "CHOOSE", "NUMBER"] = "ACT"
    result_scope: VisibilityScope = VisibilityScope.PUBLIC
    result_target_seat: Optional[int] = None
    result_group_id: Optional[str] = None
    min_value: Optional[float] = Field(None, allow_inf_nan=False)
    max_value: Optional[float] = Field(None, allow_inf_nan=False)


class ArenaSettings(BaseModel):
    """房间行为和事件历史窗口设置"""
    allow_free_actions: bool = False
    history_rounds: Optional[int] = Field(None, ge=1)
    history_seconds: Optional[int] = Field(None, ge=1)


class ArenaSettingsUpdate(BaseModel):
    """主持人可修改的房间设置；窗口为 None 时表示不过期"""
    allow_free_actions: Optional[bool] = None
    history_rounds: Optional[int] = Field(None, ge=1)
    history_seconds: Optional[int] = Field(None, ge=1)


class SeatDefinition(BaseModel):
    seat_id: int = Field(..., ge=1)
    name: str = Field("", max_length=200)
    role: str = Field("玩家", max_length=200)
    model: str = Field("未知模型", max_length=200)
    avatar_id: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")
    group_id: Optional[str] = Field(None, max_length=200)
    init_prompt: str = ""


class SeatAppearance(BaseModel):
    model: Optional[str] = Field(None, min_length=1, max_length=200)
    avatar_id: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")


class FlowStep(BaseModel):
    phase: str = Field(..., min_length=1)
    round_num: int = Field(1, ge=1)
    mode: Literal["SEQUENTIAL", "SIMULTANEOUS", "MANUAL"] = "SEQUENTIAL"
    target_seats: List[int] = Field(default_factory=list, max_length=64)
    action_type: Literal["ACT", "SPEAK", "VOTE", "CHOOSE", "NUMBER"] = "ACT"
    prompt: str = ""
    options: List[str] = Field(default_factory=list)
    action_options: Optional[List[ActionOption]] = None
    timeout: int = Field(60, ge=1, le=86400)
    result_scope: VisibilityScope = VisibilityScope.PUBLIC
    result_target_seat: Optional[int] = None
    result_group_id: Optional[str] = None
    min_value: Optional[float] = Field(None, allow_inf_nan=False)
    max_value: Optional[float] = Field(None, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_targets(self):
        if self.mode != "MANUAL" and not self.target_seats:
            raise ValueError("自动行动步骤必须选择目标席位")
        if len(set(self.target_seats)) != len(self.target_seats):
            raise ValueError("流程目标席位不能重复")
        return self


class FlowPlan(BaseModel):
    steps: List[FlowStep] = Field(..., min_length=1, max_length=100)


class FlowState(BaseModel):
    steps: List[FlowStep] = Field(default_factory=list)
    index: int = 0
    status: Literal["IDLE", "RUNNING", "PAUSED", "AWAITING_HOST", "COMPLETED"] = "IDLE"
    pending_seats: List[int] = Field(default_factory=list)
    paused_at: Optional[float] = None
    resume_status: str = "RUNNING"
    sealed_results: List[dict] = Field(default_factory=list)


class Scenario(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    seats: List[SeatDefinition] = Field(..., min_length=1, max_length=64)
    settings: ArenaSettings = Field(default_factory=ArenaSettings)
    flow_steps: List[FlowStep] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_seats(self):
        ids = [seat.seat_id for seat in self.seats]
        if len(ids) != len(set(ids)):
            raise ValueError("剧本中的席位编号不能重复")
        return self


class RoomSnapshot(BaseModel):
    """落盘持久化快照模型"""
    schema_version: int = 2
    room_id: str = Field(default_factory=lambda: uuid4().hex)
    room_title: str
    scenario_description: str = ""
    phase: str
    round_num: int
    seq_counter: int
    seats: Dict[int, Seat]
    events: List[Event]
    active_actions: Dict[int, ActionRequest] = Field(default_factory=dict)
    last_seen_seqs: Dict[int, int] = Field(default_factory=dict)
    settings: ArenaSettings = Field(default_factory=ArenaSettings)
    receipts: Dict[str, dict] = Field(default_factory=dict)
    flow: FlowState = Field(default_factory=FlowState)
    game: Optional[dict] = None
    workspace_paths: Dict[int, str] = Field(default_factory=dict)
    mod_profile: List[dict] = Field(default_factory=list)
    mod_settings: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    model_avatars: Dict[str, str] = Field(default_factory=dict)


class EventAcknowledgement(BaseModel):
    seat_id: int
    room_id: str
    seq: int = Field(..., ge=0)

