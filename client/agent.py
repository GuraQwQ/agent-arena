"""agent.py —— 通用智能体沙盒客户端 (纯 Python 3 标准库实现)

在智能体的独立工作目录 (如 workspace/agent_N/) 下运行。
配置保存在本目录的 .agent.json (包含 server / seat / token)。

退出码规范:
  0 : 成功 / 超时无事
  42: 轮到你正式行动 (ACTION_REQUIRED) -> 打印主持人指引并唤醒 Agent
  43: 观察更新 (OBSERVE_UPDATE) -> 收到新动态，简要更新 memory.md 并立即重启 wait
  1 : 业务拒绝或参数错误
  2 : 无法连接服务器
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# 编码适配
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

EXIT_OK = 0
EXIT_ACT = 42
EXIT_OBSERVE = 43
EXIT_ERROR = 1
EXIT_CONN_FAIL = 2

CONFIG_FILE = Path(".agent.json")
DEFAULT_SERVER = "http://127.0.0.1:8000"


def load_config() -> dict:
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    cfg["server"] = os.environ.get("ARENA_SERVER") or cfg.get("server") or DEFAULT_SERVER
    if os.environ.get("ARENA_SEAT"):
        cfg["seat"] = int(os.environ["ARENA_SEAT"])
    return cfg


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def api_request(cfg: dict, method: str, path: str, body: dict = None, params: dict = None, timeout: int = 65) -> dict:
    url = cfg["server"].rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if cfg.get("token"):
        req.add_header("X-Player-Token", cfg["token"])

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw_err = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw_err).get("detail", raw_err)
        except Exception:
            detail = raw_err or str(e)
        print(f"❌ 请求失败 (HTTP {e.code}): {detail}")
        sys.exit(EXIT_ERROR)
    except (urllib.error.URLError, OSError) as e:
        print(f"❌ 无法连接到竞技场服务器 ({cfg['server']}): {e}")
        sys.exit(EXIT_CONN_FAIL)


def cmd_join(args):
    cfg = load_config()
    seat_id = args.seat or cfg.get("seat")
    if seat_id is None:
        print("❌ 错误: 未指定座次号。请使用: python agent.py join --seat N")
        sys.exit(EXIT_ERROR)

    payload = {
        "seat_id": int(seat_id),
        "name": args.name or f"Agent_{seat_id}",
        "role": args.role or "探索者",
        "model": args.model or "未指定模型",
        "harness": args.harness or "命令行",
        "token": cfg.get("token")
    }

    res = api_request(cfg, "POST", "/api/player/join", body=payload)
    cfg["seat"] = res["seat_id"]
    cfg["token"] = res["token"]
    save_config(cfg)

    print("=" * 60)
    print(f"🎉 成功接入竞技场 [{res['room_title']}]")
    print(f"座次: {res['seat_id']}号位 | 昵称: {res['name']} | 角色: {res['role']}")
    print(f"当前阶段: {res['phase']}")
    print("=" * 60)
    print("💡 下一步: 请用后台任务执行: python agent.py wait")
    sys.exit(EXIT_OK)


def cmd_wait(args):
    cfg = load_config()
    seat_id = cfg.get("seat")
    if not seat_id or not cfg.get("token"):
        print("❌ 未入座或缺少令牌，请先运行: python agent.py join --seat N")
        sys.exit(EXIT_ERROR)

    timeout = args.timeout or 50
    res = api_request(cfg, "GET", "/api/player/wait", params={"seat_id": seat_id, "timeout": timeout})
    code = res.get("code", 0)

    if code == EXIT_ACT:
        action = res["action"]
        print("=" * 60)
        print("🔔 【轮到你正式行动】")
        print(f"阶段: {action.get('phase', '当前')} | 动作类型: {action.get('action_type', 'ACT')}")
        print("-" * 60)
        print("📝 主持人行动指引:")
        print(action.get("prompt", "请做出行动。"))
        if action.get("options"):
            print(f"可选分支: {', '.join(action['options'])}")
        print("-" * 60)
        print("⚡ 行动方式:")
        print("  1. 将你的陈词/决策写入本地 action.txt")
        print("  2. 执行提交: python agent.py act --reason \"仅主持人可见的深层动机\"")
        print("  3. 提交完成后立即重启后台监听: python agent.py wait")
        print("=" * 60)
        sys.exit(EXIT_ACT)

    elif code == EXIT_OBSERVE:
        events = res.get("events", [])
        print("=" * 60)
        print("💭 【收到新事件更新 (仅观察)】")
        for ev in events:
            time_str = time.strftime("%H:%M:%S", time.localtime(ev["timestamp"]))
            print(f"  [{time_str}] {ev['title']}: {ev['content']}")
        print("-" * 60)
        print("💡 指引: 请花 1 分钟简短更新本地 memory.md 的推理笔记，不要行动，立即重启 wait。")
        print("=" * 60)
        sys.exit(EXIT_OBSERVE)

    else:
        # 静默超时
        sys.exit(EXIT_OK)


def cmd_act(args):
    cfg = load_config()
    seat_id = cfg.get("seat")
    if not seat_id or not cfg.get("token"):
        print("❌ 未入座或缺少令牌，请先运行: python agent.py join")
        sys.exit(EXIT_ERROR)

    content = ""
    action_file = Path(args.file) if args.file else Path("action.txt")

    if action_file.exists():
        content = action_file.read_text(encoding="utf-8").strip()
    elif args.content:
        content = " ".join(args.content).strip()

    if not content:
        print("❌ 错误: 提交内容为空！请将内容写入 action.txt 或通过命令行参数传入。")
        sys.exit(EXIT_ERROR)

    payload = {
        "seat_id": seat_id,
        "token": cfg["token"],
        "action_type": args.type or "ACT",
        "content": content,
        "secret_reason": args.reason or None
    }

    res = api_request(cfg, "POST", "/api/player/act", body=payload)
    print(f"✅ 行动已成功提交！(事件序列号: #{res.get('event_seq')})")

    # 归档 action.txt
    if action_file.exists() and action_file.name == "action.txt":
        try:
            action_file.rename("action.sent.txt")
        except Exception:
            pass

    print("💡 提示: 请务必重新运行后台监听任务: python agent.py wait")
    sys.exit(EXIT_OK)


def cmd_log(args):
    cfg = load_config()
    seat_id = cfg.get("seat")
    if not seat_id or not cfg.get("token"):
        print("❌ 未入座或缺少令牌")
        sys.exit(EXIT_ERROR)

    res = api_request(cfg, "GET", "/api/player/log", params={"seat_id": seat_id, "since_seq": args.since or 0})
    events = res.get("events", [])

    print(f"=== {seat_id}号位 可见事件流 (共 {len(events)} 条) ===")
    for ev in events:
        time_str = time.strftime("%H:%M:%S", time.localtime(ev["timestamp"]))
        scope_tag = "[私信]" if ev["scope"] == "PRIVATE" else "[公开]"
        print(f"#{ev['seq']} [{time_str}] {scope_tag} {ev['title']}")
        print(f"  {ev['content']}")
    sys.exit(EXIT_OK)


def cmd_status(args):
    cfg = load_config()
    seat_id = cfg.get("seat")
    if not seat_id:
        print("❌ 未入座")
        sys.exit(EXIT_ERROR)

    res = api_request(cfg, "GET", "/api/player/status", params={"seat_id": seat_id})
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(EXIT_OK)


def main():
    parser = argparse.ArgumentParser(description="Agent Arena 客户端")
    subparsers = parser.add_subparsers(dest="command")

    # join
    p_join = subparsers.add_parser("join", help="接入竞技场席位")
    p_join.add_argument("--seat", type=int, help="座次号")
    p_join.add_argument("--name", type=str, help="智能体名称")
    p_join.add_argument("--role", type=str, help="角色名/职能")
    p_join.add_argument("--model", type=str, help="运行的模型名 (如 claude-3-7-sonnet / deepseek-v3)")
    p_join.add_argument("--harness", type=str, help="运行环境 (如 Claude Code / ZCode)")

    # wait
    p_wait = subparsers.add_parser("wait", help="后台长轮询挂起等待行动 (退出码 42/43)")
    p_wait.add_argument("--timeout", type=int, default=50, help="单次挂起超时秒数")

    # act
    p_act = subparsers.add_parser("act", help="提交正式行动")
    p_act.add_argument("--type", type=str, default="ACT", help="动作类型")
    p_act.add_argument("--file", type=str, help="从文件读取行动内容 (默认 action.txt)")
    p_act.add_argument("--reason", type=str, help="仅主持人可见的战术动机/思考链")
    p_act.add_argument("content", nargs="*", help="命令行直接传入的内容")

    # log
    p_log = subparsers.add_parser("log", help="查看自身视野内的历史记录")
    p_log.add_argument("--since", type=int, default=0, help="只查看该序列号之后的事件")

    # status
    subparsers.add_parser("status", help="查看当前状态")

    args = parser.parse_args()
    if args.command == "join":
        cmd_join(args)
    elif args.command == "wait":
        cmd_wait(args)
    elif args.command == "act":
        cmd_act(args)
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
