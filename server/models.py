"""数据模型定义 (Pydantic v2)

定义 Agent Arena 的事件、座次、视野范围与行动调度结构。
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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
    secret_reason: Optional[str] = Field(None, description="仅主持人可见的深层思考链/战术意图")
    data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="结构化附加元数据")


class Seat(BaseModel):
    """座次与智能体注册信息"""
    seat_id: int
    name: str = ""
    role: str = "玩家"
    model: str = "未知模型"
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
    deadline: float = 0.0     # 截止时间戳


class ActionSubmission(BaseModel):
    """Agent 提交的行动结果"""
    seat_id: int
    token: str
    action_type: str
    content: str
    secret_reason: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class HostCommand(BaseModel):
    """主持人控制指令"""
    command_type: str  # ADVANCE_PHASE, BROADCAST, SEND_PRIVATE, DISPATCH_ACTION, RESET
    phase: Optional[str] = None
    target_seat: Optional[int] = None
    content: Optional[str] = None
    secret_reason: Optional[str] = None
    prompt: Optional[str] = None
    options: Optional[List[str]] = None
    timeout: Optional[int] = Field(60, ge=1, le=86400)
    round_num: Optional[int] = Field(None, ge=1)


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


class RoomSnapshot(BaseModel):
    """落盘持久化快照模型"""
    room_title: str
    phase: str
    round_num: int
    seq_counter: int
    seats: Dict[int, Seat]
    events: List[Event]
    active_actions: Dict[int, ActionRequest] = Field(default_factory=dict)
    last_seen_seqs: Dict[int, int] = Field(default_factory=dict)
    settings: ArenaSettings = Field(default_factory=ArenaSettings)

