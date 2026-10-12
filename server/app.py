"""FastAPI 主服务入口与路由配置

提供玩家 Agent 交互端点、视野隔离 API 以及主持人 Web 控制台和 SSE 流。
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保服务端当前目录在模块搜索路径中
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import ArenaEngine
from models import ActionSubmission, HostCommand, VisibilityScope

app = FastAPI(title="Agent Arena", description="通用多智能体独立操作与沙盒博弈基座")

# 启用 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局引擎单例
engine = ArenaEngine()

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
def get_player_bootstrap(seat_id: int, request: Request):
    """获取指定席位的初始配置与专属提示词"""
    seat = engine.seats.get(seat_id)
    if not seat:
        raise HTTPException(status_code=404, detail="未找到该席位")
    base_url = str(request.base_url).rstrip("/")
    return {
        "seat_id": seat.seat_id,
        "token": seat.token,
        "name": seat.name,
        "role": seat.role,
        "init_prompt": seat.init_prompt,
        "room_title": engine.room_title,
        "server": base_url
    }


@app.get("/bootstrap/{seat_id}")
def get_bootstrap_script(seat_id: int, request: Request):
    """动态生成一键自举 Python 脚本 (Agent 单行命令自动接入)"""
    seat = engine.seats.get(seat_id)
    if not seat:
        raise HTTPException(status_code=404, detail="未找到该席位")
    base_url = str(request.base_url).rstrip("/")

    script = f'''# -*- coding: utf-8 -*-
"""Agent Arena 一键自举装配器 (席位: {seat_id})"""
import urllib.request
import json
from pathlib import Path

SERVER = "{base_url}"
SEAT = {seat_id}

print(f"🚀 正在连接竞技场服务器 {{SERVER}} 接入 {{SEAT}}号席位...")

# 1. 下载 client/agent.py (若不存在)
agent_py = Path("agent.py")
if not agent_py.exists():
    url_client = f"{{SERVER}}/client/agent.py"
    try:
        content = urllib.request.urlopen(url_client).read().decode("utf-8")
        agent_py.write_text(content, encoding="utf-8")
        print("  ✓ 已下载 agent.py 客户端")
    except Exception as e:
        print(f"  ❌ 下载 agent.py 失败: {{e}}")

# 2. 拉取席位设定
try:
    url_boot = f"{{SERVER}}/api/player/bootstrap/{{SEAT}}"
    data = json.loads(urllib.request.urlopen(url_boot).read().decode("utf-8"))
    
    # 写入 .agent.json
    cfg = {{"server": SERVER, "seat": SEAT, "token": data["token"]}}
    Path(".agent.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  ✓ 已配置 .agent.json 身份令牌")

    # 写入 memory.md
    mem = Path("memory.md")
    init_notes = (
        f"# {{data['name']}} ({{SEAT}}号位 · {{data['role']}}) 私有笔记\\n\\n"
        f"## 专属目标与初始设定\\n{{data['init_prompt']}}\\n\\n"
        f"## 局势推演笔记\\n"
    )
    mem.write_text(init_notes, encoding="utf-8")
    print("  ✓ 已初始化 memory.md 私有笔记")

    print("=" * 60)
    print(f"🎉 成功接入 [{{data['room_title']}}] {{SEAT}}号位！")
    print(f"角色身份: {{data['role']}} | 令牌: {{data['token'][:10]}}***")
    print("-" * 60)
    print("📝 你的初始目标与提示词:")
    print(data["init_prompt"])
    print("-" * 60)
    print("⚡ 指引: 请立即以后台任务运行监听，并结束当前回合:")
    print("   python agent.py wait")
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


@app.post("/api/player/join")
def player_join(req: JoinRequest):
    """Agent 入座或使用既有令牌重连"""
    seat = engine.join_seat(
        seat_id=req.seat_id,
        name=req.name,
        role=req.role,
        model=req.model,
        harness=req.harness,
        token=req.token
    )
    return {
        "success": True,
        "seat_id": seat.seat_id,
        "token": seat.token,
        "name": seat.name,
        "role": seat.role,
        "room_title": engine.room_title,
        "phase": engine.phase,
        "message": f"成功进入 {seat.seat_id}号席位。"
    }


@app.get("/api/player/wait")
async def player_wait(
    seat_id: int = Query(...),
    timeout: int = Query(50, le=60),
    x_player_token: str = Header(...)
):
    """长轮询挂起等待行动或新观察"""
    try:
        res = await engine.wait_turn(seat_id=seat_id, token=x_player_token, timeout=timeout)
        return res
    except PermissionError:
        raise HTTPException(status_code=403, detail="令牌无效或无权访问")


@app.get("/api/player/log")
def player_log(
    seat_id: int = Query(...),
    since_seq: int = Query(0),
    x_player_token: str = Header(...)
):
    """拉取本 Agent 视野范围内的所有历史记录 (严格过滤)"""
    if not engine.verify_token(seat_id, x_player_token):
        raise HTTPException(status_code=403, detail="令牌无效")
    events = engine.filter_events_for_seat(seat_id, since_seq=since_seq)
    return {"events": events}


@app.get("/api/player/status")
def player_status(
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
        "round": engine.round_num,
        "status": seat.status if seat else "UNKNOWN",
        "pending_action": action.model_dump() if action else None
    }


@app.post("/api/player/act")
def player_submit_act(sub: ActionSubmission):
    """提交行动结果与仅主持人可见的 secret_reason"""
    try:
        event = engine.submit_action(
            seat_id=sub.seat_id,
            token=sub.token,
            action_type=sub.action_type,
            content=sub.content,
            secret_reason=sub.secret_reason,
            data=sub.data
        )
        return {"success": True, "event_seq": event.seq}
    except PermissionError:
        raise HTTPException(status_code=403, detail="令牌无效")


# ----------------------------------------------------------------------
# 主持人 (Host) 管理与控制台 API
# ----------------------------------------------------------------------

@app.get("/api/admin/snapshot")
def admin_snapshot():
    """获取主持人全知视角快照"""
    return engine.get_host_snapshot()


@app.get("/api/admin/stream")
async def admin_stream(request: Request):
    """主持人控制台 SSE 实时增量流"""
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
                    # 发送心跳保活
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
def admin_command(cmd: HostCommand):
    """执行主持人控制动作"""
    global engine
    c_type = cmd.command_type.upper()
    
    if c_type == "ADVANCE_PHASE":
        if cmd.phase:
            engine.phase = cmd.phase
        engine.record_event(
            event_type="PHASE_CHANGE",
            title=f"【阶段变更】进入阶段: {engine.phase}",
            content=f"主持人已将当前场景切换为: {engine.phase}",
            scope=VisibilityScope.PUBLIC
        )
        engine.broadcast_host_update()
        return {"success": True, "phase": engine.phase}

    elif c_type == "DISPATCH_ACTION":
        if cmd.target_seat is None:
            raise HTTPException(status_code=400, detail="必须指定目标席位 target_seat")
        req = engine.dispatch_action(
            target_seat=cmd.target_seat,
            action_type="ACT",
            prompt=cmd.prompt or "请针对当前局势做出你的行动与分析。",
            options=cmd.options or [],
            timeout=cmd.timeout or 60
        )
        return {"success": True, "request": req.model_dump()}

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
        engine.record_event(
            event_type="PRIVATE_MESSAGE",
            title=f"【私信指令】主持人 -> {cmd.target_seat}号位",
            content=cmd.content or "",
            to_seat=cmd.target_seat,
            scope=VisibilityScope.PRIVATE
        )
        return {"success": True}

    elif c_type == "RESET":
        engine = ArenaEngine(engine.room_title)
        return {"success": True, "message": "房间已重置"}

    raise HTTPException(status_code=400, detail=f"未知的命令类型: {cmd.command_type}")


# 挂载静态文件与默认页面
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return index_file.read_text(encoding="utf-8")
        return "<h1>Agent Arena 服务已启动</h1>"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
