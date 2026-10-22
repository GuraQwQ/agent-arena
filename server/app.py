"""FastAPI 主服务入口与路由配置

提供玩家 Agent 交互端点、视野隔离 API 以及主持人 Web 控制台和 SSE 流。
"""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

# 确保服务端当前目录在模块搜索路径中
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from engine import ArenaEngine, SNAPSHOT_FILE
from archives import ArchiveStore
from models import ActionSubmission, ArenaSettingsUpdate, EventAcknowledgement, FlowPlan, HostCommand, RoomSnapshot, Scenario, SeatDefinition, SeatAppearance, VisibilityScope
from cli_mount import mount_cli, unmount_cli
from gameplay import GAMES_ROOT, GameDriver, load_mod
from mods import ModConflict, ModManager, ModRuntime, mod_file, read_manifest, snapshot_mods
from mod_settings import ModSettingsError
from host_access import HostAccess, JoinClosed
from memory_observer import MemoryObserver
from content_packs import scan_content_packs
from observer import build_event_page, build_room_summary, build_runtime_snapshot
from agent_journal import AgentNote, journal_projection


host_access = HostAccess(Path(os.environ.get("ARENA_HOST_CONFIG") or Path(__file__).resolve().parents[1] / "host-login.json"))
DEBUG_MODE = os.environ.get("ARENA_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def admin_cookie_name(request: Request):
    # Cookie 不按端口隔离；不同本机实例各用自己的名称。
    return f"arena_admin_{request.url.port or (443 if request.url.scheme == 'https' else 80)}"


def admin_session_key(request: Request):
    return request.headers.get("X-Admin-Session") or request.cookies.get(admin_cookie_name(request))


def require_admin(request: Request):
    """管理接口只接受当前服务签发的主持人会话。"""
    if DEBUG_MODE:
        return
    if not host_access.authenticated(admin_session_key(request)):
        raise HTTPException(status_code=403, detail="请先加入本服务的主持人会话")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务生命周期管理器：启动时挂载全局 arena CLI，关闭时自动清理"""
    cli_path = mount_cli()
    if cli_path:
        print(f"🚀 已自动挂载全局 arena CLI 入口: {cli_path}")
    print(f"主持人加入口令文件：{host_access.config_path}；当前服务初始可加入一次")
    maintenance = asyncio.create_task(maintain_actions())
    try:
        yield
    finally:
        maintenance.cancel()
        try:
            await maintenance
        except asyncio.CancelledError:
            pass
        unmount_cli()


async def maintain_actions():
    while True:
        await asyncio.sleep(0.5)
        try:
            engine.tick()
        except (OSError, ValueError) as exc:
            print(f"超时处理未保存，将重试: {exc}", file=sys.stderr)
        memory_observer.tick()


app = FastAPI(title="Agent Arena", description="通用多智能体独立操作与沙盒博弈基座", lifespan=lifespan)


@app.exception_handler(OSError)
async def storage_error(request: Request, exc: OSError):
    print(f"快照写入失败: {exc}", file=sys.stderr)
    return JSONResponse(status_code=503, content={"detail": "状态保存失败，请检查存储后重试；本次操作尚未提交"})


@app.exception_handler(ValueError)
async def invalid_operation(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ModConflict)
async def mod_conflict(request: Request, exc: ModConflict):
    return JSONResponse(status_code=409, content={"detail": str(exc), "issues": exc.issues})

# 启用 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局引擎单例 (自动加载历史快照)
engine = ArenaEngine()
memory_observer = MemoryObserver(engine)
archives = ArchiveStore(SNAPSHOT_FILE.parent / "archives")

STATIC_DIR = Path(__file__).parent / "static"
CLIENT_FILE = Path(__file__).parent.parent / "client" / "agent.py"


# ----------------------------------------------------------------------
# 智能体自举装配 (Bootstrap) 与快速接入
# ----------------------------------------------------------------------

@app.get("/client/agent.py")
def get_client_agent():
    """提供纯标准库客户端 agent.py 下载"""
    if CLIENT_FILE.exists():
        return HTMLResponse(content=CLIENT_FILE.read_text(encoding="utf-8"), media_type="text/plain; charset=utf-8")
    raise HTTPException(status_code=404, detail="客户端文件不存在")


@app.get("/api/player/bootstrap/{seat_id}")
async def get_player_bootstrap(seat_id: int, request: Request, claim_token: str = Query(...)):
    """获取指定席位的初始配置与专属提示词"""
    seat = engine.seats.get(seat_id)
    if not seat:
        raise HTTPException(status_code=404, detail="未找到该席位")
    if not engine.verify_claim_token(seat_id, claim_token):
        raise HTTPException(status_code=403, detail="席位自举令牌无效")
    base_url = str(request.base_url).rstrip("/")
    return {
        "seat_id": seat.seat_id,
        "token": seat.token,
        "name": seat.name,
        "role": seat.role,
        "init_prompt": seat.init_prompt,
        "room_title": engine.room_title,
        "room_id": engine.room_id,
        "server": base_url
    }


@app.get("/bootstrap/{seat_id}")
async def get_bootstrap_script(seat_id: int, request: Request, claim_token: str = Query(...)):
    """动态生成一键自举 Python 脚本 (Agent 单行命令自动接入)"""
    seat = engine.seats.get(seat_id)
    if not seat:
        raise HTTPException(status_code=404, detail="未找到该席位")
    if not engine.verify_claim_token(seat_id, claim_token):
        raise HTTPException(status_code=403, detail="席位自举令牌无效")
    base_url = str(request.base_url).rstrip("/")

    script = f'''# -*- coding: utf-8 -*-
"""Agent Arena 一键自举装配器 (席位: {seat_id})"""
import urllib.request
import json
import os
import tempfile
from pathlib import Path

SERVER = "{base_url}"
SEAT = {seat_id}
CLAIM_TOKEN = "{claim_token}"

print(f"🚀 正在连接竞技场服务器 {{SERVER}} 接入 {{SEAT}}号席位...")

# 1. 原子更新项目管理的客户端，重复执行可恢复部分安装
agent_py = Path("agent.py")
content = urllib.request.urlopen(f"{{SERVER}}/client/agent.py", timeout=30).read().decode("utf-8")
compile(content, "agent.py", "exec")
descriptor, temporary = tempfile.mkstemp(prefix=".agent-install-", dir=Path.cwd())
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    Path(temporary).replace(agent_py)
finally:
    Path(temporary).unlink(missing_ok=True)
print("  ✓ 已更新 agent.py 客户端")

# 2. 拉取席位设定
try:
    url_boot = f"{{SERVER}}/api/player/bootstrap/{{SEAT}}?claim_token={{CLAIM_TOKEN}}"
    data = json.loads(urllib.request.urlopen(url_boot).read().decode("utf-8"))
    
    # 写入 .agent.json
    import runpy
    client = runpy.run_path(str(agent_py))
    cfg = client["load_config"]()
    if cfg.get("token") != data["token"]:
        cfg = {{"pending_notes": cfg["pending_notes"]}} if cfg.get("pending_notes") else {{}}
    cfg.update({{"server": SERVER, "seat": SEAT, "token": data["token"], "room_id": data["room_id"]}})
    client["save_config"](cfg)
    print("  ✓ 已配置 .agent.json 身份令牌")

    # 写入 memory.md
    mem = Path("memory.md")
    init_notes = (
        f"# {{data['name']}} ({{SEAT}}号位 · {{data['role']}}) 角色资料\\n\\n"
        f"## 专属目标与初始设定\\n{{data['init_prompt']}}\\n\\n"
    )
    if not mem.exists():
        mem.write_text(init_notes, encoding="utf-8")
    print("  ✓ 已初始化 memory.md 私有笔记")

    print("=" * 60)
    print(f"🎉 成功接入 [{{data['room_title']}}] {{SEAT}}号位！")
    print(f"角色身份: {{data['role']}} | 令牌: {{data['token'][:10]}}***")
    print("-" * 60)
    print("📝 你的初始目标与提示词:")
    print(data["init_prompt"])
    print("-" * 60)
    print('💭 即时自述：python agent.py note "此刻的想法"；需要保留时加 --remember，恢复历程用 notes。memory.md 存放角色资料，工具排错写入 runtime.log。')
    print("⚡ 指引: 请立即以后台任务运行监听，并结束当前回合:")
    print("   python agent.py watch")
    print("=" * 60)
except Exception as e:
    print(f"❌ 自举装配失败: {{e}}")
'''
    return HTMLResponse(content=script, media_type="text/plain; charset=utf-8")



# ----------------------------------------------------------------------
# 玩家 Agent API 端点
# ----------------------------------------------------------------------

class JoinRequest(BaseModel):
    seat_id: int
    name: str = ""
    role: str = "玩家"
    model: str = "未知模型"
    harness: str = "命令行"
    token: Optional[str] = None
    claim_token: Optional[str] = None


@app.post("/api/player/join")
async def player_join(req: JoinRequest):
    """Agent 入座或使用既有令牌重连"""
    try:
        seat = engine.join_seat(
            seat_id=req.seat_id,
            name=req.name,
            role=req.role,
            model=req.model,
            harness=req.harness,
            token=req.token,
            claim_token=req.claim_token
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {
        "success": True,
        "seat_id": seat.seat_id,
        "token": seat.token,
        "room_id": engine.room_id,
        "name": seat.name,
        "role": seat.role,
        "room_title": engine.room_title,
        "phase": engine.phase,
        "message": f"成功进入 {seat.seat_id}号席位。"
    }


@app.get("/api/player/wait")
async def player_wait(
    seat_id: int = Query(...),
    timeout: int = Query(50, ge=1, le=60),
    x_player_token: str = Header(...)
):
    """长轮询挂起等待行动或新观察"""
    try:
        res = await engine.wait_turn(seat_id=seat_id, token=x_player_token, timeout=timeout)
        return res
    except PermissionError:
        raise HTTPException(status_code=403, detail="令牌无效或无权访问")


@app.get("/api/player/log")
async def player_log(
    seat_id: int = Query(...),
    since_seq: Optional[int] = Query(None, ge=0),
    limit: int = Query(30, ge=1, le=500),
    x_player_token: str = Header(...)
):
    """拉取本 Agent 视野范围内的所有历史记录 (严格过滤)"""
    if not engine.verify_token(seat_id, x_player_token):
        raise HTTPException(status_code=403, detail="令牌无效")
    events = engine.filter_events_for_seat(seat_id, since_seq=since_seq or 0)
    page = events[-limit:] if since_seq is None else events[:limit]
    return {"events": page, "next_seq": page[-1]["seq"] if page else since_seq or 0,
            "has_more": since_seq is not None and len(events) > limit}


@app.post("/api/player/ack")
async def player_ack(ack: EventAcknowledgement, x_player_token: str = Header(...)):
    try:
        engine.acknowledge(ack.seat_id, x_player_token, ack.room_id, ack.seq)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"success": True}


@app.post("/api/player/notes")
async def player_note(note: AgentNote):
    try:
        event = engine.record_agent_note(note)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"success": True, "event_seq": event.seq, "recorded_at": event.timestamp}


@app.get("/api/player/notes")
async def player_notes(seat_id: int, room_id: str, since_seq: Optional[int] = Query(None, ge=0),
                       limit: int = Query(20, ge=1, le=500), view: str = Query("recent", pattern="^(recent|memory|history)$"),
                       x_player_token: str = Header(...)):
    if room_id != engine.room_id or not engine.verify_token(seat_id, x_player_token):
        raise HTTPException(status_code=403, detail="房间或席位凭证不匹配")
    events = [event for event in engine.events if event.event_type == "AGENT_NOTE" and event.from_seat == seat_id]
    eligible = [event for event in events if since_seq is None or event.seq > since_seq]
    page = eligible[:limit] if since_seq is not None or view == "history" else eligible[-limit:]
    if view == "memory":
        page = []
    memories = journal_projection(events)["remembered"].get(seat_id, []) if view != "history" else []
    selected = {event.seq: event.model_dump(exclude={"secret_reason"}) for event in page}
    for memory in memories:
        selected[memory["seq"]] = memory
    for event in selected.values():
        event["data"].pop("submission", None)
    pending = engine.active_actions.get(seat_id)
    return {"events": sorted(selected.values(), key=lambda event: event["seq"]),
            "remembered_seqs": [event["seq"] for event in memories],
            "pending_action": pending.model_dump(exclude={"result_recipients"}) if pending and view == "recent" else None,
            "next_seq": page[-1].seq if page else since_seq or 0,
            "has_more": view != "memory" and (since_seq is not None or view == "history") and len(eligible) > limit}


@app.get("/api/player/status")
async def player_status(
    seat_id: int = Query(...),
    x_player_token: str = Header(...)
):
    """获取当前自身状态与活跃行动"""
    if not engine.verify_token(seat_id, x_player_token):
        raise HTTPException(status_code=403, detail="令牌无效")
    seat = engine.seats.get(seat_id)
    action = engine.active_actions.get(seat_id)
    return {
        "seat_id": seat_id,
        "phase": engine.phase,
        "room_id": engine.room_id,
        "round": engine.round_num,
        "status": seat.status if seat else "UNKNOWN",
        "pending_action": action.model_dump(exclude={"result_recipients"}) if action else None
    }


@app.post("/api/player/act")
async def player_submit_act(sub: ActionSubmission):
    """提交行动结果与仅主持人可见的 secret_reason"""
    try:
        event = engine.submit_action(
            seat_id=sub.seat_id,
            token=sub.token,
            action_type=sub.action_type,
            content=sub.content,
            request_id=sub.request_id,
            secret_reason=sub.secret_reason,
            data=sub.data
        )
        return {"success": True, "event_seq": event.seq}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except TimeoutError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/player/game")
async def player_game(seat_id: int, room_id: str, x_player_token: str = Header(...)):
    if room_id != engine.room_id or not engine.verify_token(seat_id, x_player_token):
        raise HTTPException(status_code=403, detail="房间或席位密钥不匹配")
    return GameDriver(engine).observe(seat_id)


# ----------------------------------------------------------------------
# 主持人 (Host) 管理与控制台 API
# ----------------------------------------------------------------------

@app.get("/api/admin/snapshot")
async def admin_snapshot(request: Request):
    """获取主持人全知视角快照"""
    require_admin(request)
    return engine.get_host_snapshot()


@app.get("/api/admin/summary")
async def admin_summary(request: Request):
    require_admin(request)
    return build_room_summary(engine.snapshot())


@app.get("/api/admin/runtime")
async def admin_runtime(request: Request, since_seq: Optional[int] = Query(None, ge=0), limit: int = Query(30, ge=1, le=500)):
    require_admin(request)
    return build_runtime_snapshot(engine.snapshot(), since_seq=since_seq, limit=limit)


@app.get("/api/admin/events")
async def admin_events(request: Request, since_seq: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    require_admin(request)
    events = [event for event in engine.events if event.seq > since_seq and engine._is_event_in_history_window(event)]
    return build_event_page(events, cursor=since_seq, limit=limit)


@app.get("/api/admin/perspective")
async def admin_perspective(request: Request, seat_id: Optional[int] = Query(None, ge=1)):
    require_admin(request)
    snapshot = engine.get_host_snapshot()
    snapshot["perspective_seat"] = seat_id
    if seat_id is not None:
        if seat_id not in engine.seats:
            raise ValueError("观察席位不存在")
        snapshot["events"] = engine.filter_events_for_seat(seat_id)
        snapshot["active_actions"] = {sid: action for sid, action in snapshot["active_actions"].items() if sid == seat_id}
        snapshot["memories"] = {sid: memory for sid, memory in snapshot["memories"].items() if sid == seat_id}
        snapshot["events"] += [event.model_dump() for event in engine.events
                               if event.event_type == "AGENT_NOTE" and event.from_seat == seat_id
                               and engine._is_event_in_history_window(event)]
        snapshot["events"].sort(key=lambda event: event["seq"])
        snapshot["journal"] = {key: {sid: value for sid, value in items.items() if sid == seat_id}
                               for key, items in snapshot["journal"].items()}
        if engine.game:
            snapshot["game"] = {**engine.game, "state": GameDriver(engine).observe(seat_id)["state"]}
    return snapshot


@app.get("/api/admin/game/frontend")
async def game_frontend(request: Request):
    require_admin(request)
    if not engine.game:
        return {"frontend": None}
    config = getattr(load_mod(engine.game["name"]), "CLIENT", None)
    metadata = read_manifest(GAMES_ROOT, engine.game["name"])
    query = urlencode({"mod": engine.game["name"], "version": metadata["ui_hash"], "generation": mod_manager.generation})
    return {"frontend": {key: "/game/" + str(value) + "?" + query for key, value in config.items()} if config else None}


@app.get("/api/admin/stream")
async def admin_stream(request: Request):
    """主持人控制台 SSE 实时增量流"""
    require_admin(request)
    queue: asyncio.Queue = asyncio.Queue()
    engine.sse_queues.append(queue)

    async def event_generator():
        try:
            # 建立连接时立即发送一次全量快照
            initial = json.dumps({"type": "SNAPSHOT", "data": engine.get_host_snapshot()}, ensure_ascii=False)
            yield f"data: {initial}\n\n"
            
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 心跳同时刷新时间窗口，及时隐藏过期事件
                    snapshot = json.dumps({"type": "SNAPSHOT", "data": engine.get_host_snapshot()}, ensure_ascii=False)
                    yield f"data: {snapshot}\n\n"
                    yield ": ping\n\n"
        finally:
            if queue in engine.sse_queues:
                engine.sse_queues.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/admin/command")
async def admin_command(cmd: HostCommand, request: Request):
    """执行主持人控制动作"""
    require_admin(request)
    c_type = cmd.command_type.upper()
    
    if c_type == "ADVANCE_PHASE":
        engine.advance_phase(cmd.phase, cmd.round_num)
        return {"success": True, "phase": engine.phase}

    elif c_type == "DISPATCH_ACTION":
        if cmd.target_seat is None:
            raise HTTPException(status_code=400, detail="必须指定目标席位 target_seat")
        try:
            req = engine.dispatch_action(
                target_seat=cmd.target_seat,
                action_type=cmd.action_type,
                prompt=cmd.prompt or "请针对当前局势做出你的行动与分析。",
                options=cmd.options or [],
                action_options=cmd.action_options,
                timeout=cmd.timeout if cmd.timeout is not None else 60,
                result_scope=cmd.result_scope, result_target_seat=cmd.result_target_seat,
                result_group_id=cmd.result_group_id, min_value=cmd.min_value, max_value=cmd.max_value
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"success": True, "request": req.model_dump()}

    elif c_type == "CANCEL_ACTION":
        if cmd.target_seat is None:
            raise ValueError("必须指定目标席位")
        engine.cancel_action(cmd.target_seat)
        return {"success": True}

    elif c_type == "BROADCAST":
        engine.record_event(
            event_type="ANNOUNCEMENT",
            title="【全员公告】主持人广播",
            content=cmd.content or "",
            scope=VisibilityScope.PUBLIC
        )
        return {"success": True}

    elif c_type == "SEND_PRIVATE":
        if cmd.target_seat is None:
            raise HTTPException(status_code=400, detail="必须指定目标席位 target_seat")
        if cmd.target_seat not in engine.seats:
            raise HTTPException(status_code=400, detail="目标席位不存在")
        engine.record_event(
            event_type="PRIVATE_MESSAGE",
            title=f"【私信指令】主持人 -> {cmd.target_seat}号位",
            content=cmd.content or "",
            to_seat=cmd.target_seat,
            scope=VisibilityScope.PRIVATE
        )
        return {"success": True}

    elif c_type == "SEND_GROUP":
        if not cmd.group_id or not any(seat.group_id == cmd.group_id for seat in engine.seats.values()):
            raise HTTPException(status_code=400, detail="目标阵营不存在")
        engine.record_event("GROUP_MESSAGE", f"【阵营消息】{cmd.group_id}", cmd.content or "",
                            group_id=cmd.group_id, scope=VisibilityScope.GROUP)
        return {"success": True}

    elif c_type == "RESET":
        engine.reset()
        engine.broadcast_host_update()
        return {"success": True, "message": "房间已重置并清除快照"}

    raise HTTPException(status_code=400, detail=f"未知的命令类型: {cmd.command_type}")


@app.post("/api/admin/flow")
async def start_flow(plan: FlowPlan, request: Request):
    require_admin(request)
    engine.start_flow(plan.steps)
    return {"success": True, "flow": engine.flow.model_dump()}


class GameStartRequest(BaseModel):
    name: str
    seats: List[int]
    options: Dict[str, Any] = {}


@app.get("/api/admin/games")
async def list_game_mods(request: Request):
    require_admin(request)
    return {"games": [mod["id"] for mod in mod_manager.catalog().values() if mod.get("type") == "game" and not mod.get("error")]}


@app.post("/api/admin/game")
async def start_game(body: GameStartRequest, request: Request):
    require_admin(request)
    if body.name not in mod_manager.enabled:
        mod_manager.apply([*mod_manager.enabled, body.name])
    engine.start_game(body.name, body.seats, body.options)
    return {"success": True, "game": engine.game}


@app.post("/api/admin/game/{operation}")
async def control_game(operation: str, request: Request):
    require_admin(request)
    engine.control_game(operation)
    return {"success": True, "game": engine.game}


@app.get("/game/{asset:path}")
async def game_page(asset: str):
    if not engine.game:
        raise HTTPException(status_code=404, detail="当前未加载游戏")
    load_mod(engine.game["name"])
    directory = (GAMES_ROOT / engine.game["name"] / "ui").resolve()
    path = (directory / asset).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise HTTPException(status_code=404, detail="游戏页面不存在")
    return FileResponse(path)


@app.post("/api/admin/flow/{operation}")
async def control_flow(operation: str, request: Request):
    require_admin(request)
    engine.control_flow(operation)
    return {"success": True, "flow": engine.flow.model_dump()}


@app.get("/api/admin/archives")
async def list_archives(request: Request):
    require_admin(request)
    return {"archives": archives.list()}


@app.post("/api/admin/archives")
async def archive_current(request: Request):
    require_admin(request)
    room_id = archives.save(engine.snapshot().model_dump(mode="json"))
    return {"success": True, "room_id": room_id}


@app.get("/api/admin/archives/{room_id}")
async def read_archive(room_id: str, request: Request, seat_id: Optional[int] = Query(None, ge=1)):
    require_admin(request)
    try:
        return archives.export(room_id, seat_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="存档不存在")


class ModSelection(BaseModel):
    enabled: List[str] = Field(default_factory=list, max_length=100)


class ModSettingsUpdate(BaseModel):
    values: Dict[str, Any]


@app.get("/api/admin/mods")
async def list_mods(request: Request):
    require_admin(request)
    return mod_manager.status()


@app.get("/api/admin/content-packs")
async def list_content_packs(request: Request):
    require_admin(request)
    return scan_content_packs()


@app.post("/api/admin/mods/validate")
async def validate_mods(body: ModSelection, request: Request):
    require_admin(request)
    result = mod_manager.plan(body.enabled)
    return {key: result[key] for key in ("valid", "issues", "order")}


@app.post("/api/admin/mods")
async def apply_mods(body: ModSelection, request: Request):
    require_admin(request)
    return mod_manager.apply(body.enabled)


@app.get("/api/admin/mod-settings")
async def list_mod_settings(request: Request):
    require_admin(request)
    settings, issues = mod_manager.settings_status()
    return {"settings": settings, "issues": issues, "generation": mod_manager.generation}


@app.put("/api/admin/mods/{mod_id}/settings")
async def update_mod_settings(mod_id: str, body: ModSettingsUpdate, request: Request):
    require_admin(request)
    try:
        return mod_manager.update_settings(mod_id, body.values)
    except ModSettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/admin/mods/frontend")
async def mod_frontends(request: Request):
    require_admin(request)
    frontends = []
    for mod_id in mod_manager.enabled:
        metadata = read_manifest(GAMES_ROOT, mod_id)
        if metadata["type"] != "extension" or not metadata["frontend"].get("module"):
            continue
        query = urlencode({"version": metadata["ui_hash"], "generation": mod_manager.generation})
        frontends.append({"id": mod_id, **{key: f"/mods/assets/{mod_id}/" + value + "?" + query for key, value in metadata["frontend"].items()}})
    return {"generation": mod_manager.generation, "frontends": frontends}


@app.get("/mods/assets/{mod_id}/{asset:path}")
async def mod_asset(mod_id: str, asset: str):
    if mod_id not in mod_manager.enabled:
        raise HTTPException(status_code=404, detail="Mod 未启用")
    return FileResponse(mod_file(GAMES_ROOT, mod_id, "ui/" + asset))


@app.get("/api/admin/archives/{room_id}/mods")
async def archive_mods(room_id: str, request: Request):
    require_admin(request)
    try:
        raw = archives.read(room_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="存档不存在")
    required = snapshot_mods(raw)
    plan = mod_manager.plan([mod["id"] for mod in required], locked=required)
    warnings = [{"code": "unverified", "severity": "warning", "mods": [mod["id"]], "message": f"旧存档仅记录了 {mod['id']} {mod['version']}，无法核对历史源码"} for mod in required if not mod.get("rules_hash")]
    return {"required": required, "valid": plan["valid"], "issues": plan["issues"] + warnings, "order": plan["order"]}


@app.post("/api/admin/archives/{room_id}/restore")
async def restore_archive(room_id: str, request: Request):
    require_admin(request)
    try:
        raw = archives.read(room_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="存档不存在")
    required = snapshot_mods(raw)
    raw["mod_profile"] = required
    RoomSnapshot.model_validate(raw)
    plan = mod_manager.plan([mod["id"] for mod in required], locked=required)
    if not plan["valid"]:
        raise ModConflict(plan["issues"])
    archives.backup(engine.snapshot().model_dump(mode="json"))
    mod_manager.apply([mod["id"] for mod in required], locked=required, restore_snapshot=raw)
    return {"success": True, "room_id": engine.room_id}


class HostJoin(BaseModel):
    password: str = Field("", max_length=4096)


class HostUses(BaseModel):
    additional_uses: int = Field(..., ge=1, le=1000)


@app.get("/api/host/access")
async def host_access_status(request: Request):
    return {**host_access.info(), "debug_mode": DEBUG_MODE,
            "authenticated": DEBUG_MODE or host_access.authenticated(admin_session_key(request))}


def broadcast_host_access():
    for queue in engine.sse_queues:
        queue.put_nowait({"type": "HOST_ACCESS", "data": host_access.info()})


@app.post("/api/admin/session")
async def admin_session(body: HostJoin, request: Request, response: Response):
    if DEBUG_MODE:
        response.set_cookie(admin_cookie_name(request), "debug", httponly=True, samesite="lax", secure=False)
        return {"success": True, **host_access.info(), "debug_mode": True}
    try:
        session = host_access.join(body.password, admin_session_key(request))
    except JoinClosed as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    response.set_cookie(
        admin_cookie_name(request),
        session,
        httponly=True,
        samesite="lax",
        secure=False
    )
    broadcast_host_access()
    return {"success": True, **host_access.info()}


@app.get("/api/admin/access")
async def admin_access(request: Request):
    require_admin(request)
    return host_access.info()


@app.post("/api/admin/access")
async def add_host_uses(body: HostUses, request: Request):
    require_admin(request)
    result = host_access.add_uses(body.additional_uses)
    broadcast_host_access()
    return result


class WorkspaceRegistration(BaseModel):
    seat_id: int = Field(..., ge=1)
    directory: str = Field(..., min_length=1)


@app.post("/api/admin/workspaces")
async def register_workspace(body: WorkspaceRegistration, request: Request):
    require_admin(request)
    engine.register_workspace(body.seat_id, body.directory)
    return {"success": True, "workspace_paths": engine.workspace_paths}


@app.get("/api/admin/settings")
async def admin_settings(request: Request):
    require_admin(request)
    return engine.settings.model_dump()


@app.post("/api/admin/settings")
async def update_admin_settings(update: ArenaSettingsUpdate, request: Request):
    require_admin(request)
    fields = update.model_dump(exclude_unset=True)
    if fields.get("allow_free_actions") is None:
        fields.pop("allow_free_actions", None)
    engine.update_settings(fields)
    return {"success": True, "settings": engine.settings.model_dump()}


@app.post("/api/admin/seats")
async def admin_update_seat(definition: SeatDefinition, request: Request):
    require_admin(request)
    seat = engine.update_seat(definition)
    return {"success": True, "seat": seat.model_dump(exclude={"token"})}


class AvatarUpload(BaseModel):
    data_url: str = Field(..., max_length=400_000)


class ModelAvatarUpdate(BaseModel):
    model: str = Field(..., min_length=1, max_length=200)
    avatar_id: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")


@app.get("/api/avatars/{avatar_id}")
async def avatar_image(avatar_id: str):
    image = engine.avatars.image(avatar_id)
    if image is None:
        raise HTTPException(status_code=404, detail="头像不存在")
    content, mime = image
    return Response(content, media_type=mime, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.post("/api/admin/avatars/images")
async def upload_avatar(body: AvatarUpload, request: Request):
    require_admin(request)
    return {"avatar_id": engine.avatars.upload(body.data_url)}


@app.get("/api/admin/avatars/models")
async def model_avatars(request: Request):
    require_admin(request)
    return {"models": engine.avatars.catalog()}


@app.put("/api/admin/avatars/models")
async def update_model_avatar(body: ModelAvatarUpdate, request: Request):
    require_admin(request)
    engine.avatars.set_model(body.model, body.avatar_id)
    engine.broadcast_host_update()
    return {"models": engine.avatars.catalog()}


@app.patch("/api/admin/seats/{seat_id}/appearance")
async def update_seat_appearance(seat_id: int, body: SeatAppearance, request: Request):
    require_admin(request)
    engine.update_appearance(seat_id, body.model_dump(exclude_unset=True))
    return {"success": True}


@app.delete("/api/admin/seats/{seat_id}")
async def admin_remove_seat(seat_id: int, request: Request):
    require_admin(request)
    engine.remove_seat(seat_id)
    return {"success": True}


@app.get("/api/admin/scenario")
async def admin_scenario(request: Request):
    require_admin(request)
    return engine.get_scenario().model_dump(mode="json")


@app.post("/api/admin/scenario")
async def admin_load_scenario(scenario: Scenario, request: Request):
    require_admin(request)
    engine.load_scenario(scenario)
    return {"success": True, "room_id": engine.room_id}


# 挂载静态文件与默认页面
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    @app.get("/game", response_class=HTMLResponse)
    def index():
        react_index = STATIC_DIR / "react" / "index.html"
        if react_index.exists():
            return HTMLResponse(react_index.read_text(encoding="utf-8"), headers={
                "Cache-Control": "no-store"
            })
        return HTMLResponse("<h1>Agent Arena 服务已启动</h1><p>请在项目目录运行 npm --prefix frontend run build 构建控制台。</p>", status_code=503)


mod_manager = ModManager(GAMES_ROOT, engine, app)
initial_mods = [mod["id"] for mod in engine.mod_profile] or ([engine.game["name"]] if engine.game else [])
try:
    mod_manager.apply(initial_mods)
except ModConflict as exc:
    print(f"Mod 需要处理：{exc}；可从控制台查看详情", file=sys.stderr)
app = ModRuntime(mod_manager)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True, ws="none")
