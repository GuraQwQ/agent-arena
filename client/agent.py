"""agent.py —— 通用智能体沙盒客户端 (纯 Python 3 标准库实现)

在智能体的独立工作目录 (如 workspace/agent_N/) 下运行。
配置保存在本目录的 .agent.json (包含 server / seat / token)。

退出码规范:
  0 : 成功 / 超时无事
  42: 轮到你正式行动 (ACTION_REQUIRED) -> 打印主持人指引并唤醒 Agent
  43: 观察更新 (OBSERVE_UPDATE) -> 读取新事件，再重启 watch
  1 : 业务拒绝或参数错误
  2 : 无法连接服务器
"""

import argparse
import json
import os
import tempfile
import uuid
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
EVENTS_FILE = Path("events.jsonl")
DEFAULT_SERVER = "http://127.0.0.1:8000"


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            raise ValueError("配置内容必须是 JSON 对象")
    except FileNotFoundError:
        cfg = {}
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"❌ 无法读取配置 {CONFIG_FILE}: {exc}")
        sys.exit(EXIT_ERROR)
    cfg["server"] = os.environ.get("ARENA_SERVER") or cfg.get("server") or DEFAULT_SERVER
    if os.environ.get("ARENA_SEAT"):
        try:
            cfg["seat"] = int(os.environ["ARENA_SEAT"])
        except ValueError:
            print("❌ ARENA_SEAT 必须是整数座次号")
            sys.exit(EXIT_ERROR)
    return cfg


def save_config(cfg: dict):
    descriptor, name = tempfile.mkstemp(prefix=".agent-", suffix=".tmp", dir=CONFIG_FILE.resolve().parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        Path(name).replace(CONFIG_FILE)
    finally:
        Path(name).unlink(missing_ok=True)


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


def persist_events(room_id: str, events: list) -> list:
    """确认接收前写入日志，重试去重并修复中断留下的最后半行。"""
    if not events:
        return []
    fresh = []
    with EVENTS_FILE.open("a+b") as handle:
        handle.seek(0)
        lines = handle.readlines()
        known = set()
        valid_end = 0
        missing_newline = False
        for index, line in enumerate(lines):
            try:
                item = json.loads(line.decode("utf-8"))
                if not isinstance(item, dict) or not isinstance(item.get("seq"), int) or not item.get("room_id"):
                    raise ValueError("缺少对局编号或事件序号")
            except (UnicodeError, ValueError) as exc:
                if index == len(lines) - 1 and not line.endswith(b"\n"):
                    break
                raise ValueError(f"事件日志第 {index + 1} 行损坏：{exc}") from exc
            known.add((item["room_id"], item["seq"]))
            valid_end += len(line)
            missing_newline = not line.endswith(b"\n")
        handle.seek(valid_end)
        handle.truncate()
        if missing_newline:
            handle.write(b"\n")
        for event in events:
            key = (room_id, event["seq"])
            if key in known:
                continue
            record = dict(event, room_id=room_id)
            handle.write((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
            known.add(key)
            fresh.append(event)
        handle.flush()
        os.fsync(handle.fileno())
    return fresh


def cmd_join(args):
    cfg = load_config()
    if args.server:
        cfg["server"] = args.server.rstrip("/")
    seat_id = args.seat or cfg.get("seat")
    if seat_id is None:
        print("❌ 错误: 未指定座次号。请先执行主持人提供的自举命令，或使用 join --claim-token")
        sys.exit(EXIT_ERROR)

    payload = {
        "seat_id": int(seat_id),
        "name": args.name or f"Agent_{seat_id}",
        "role": args.role or "探索者",
        "model": args.model or "未指定模型",
        "harness": args.harness or "命令行",
        "token": cfg.get("token"),
        "claim_token": args.claim_token
    }

    res = api_request(cfg, "POST", "/api/player/join", body=payload)
    cfg["seat"] = res["seat_id"]
    cfg["token"] = res["token"]
    cfg["room_id"] = res["room_id"]
    save_config(cfg)

    print("=" * 60)
    print(f"🎉 成功接入竞技场 [{res['room_title']}]")
    print(f"座次: {res['seat_id']}号位 | 昵称: {res['name']} | 角色: {res['role']}")
    print(f"当前阶段: {res['phase']}")
    print("=" * 60)
    print("💡 下一步: 请用后台任务执行: python agent.py watch")
    sys.exit(EXIT_OK)


def receive_update(timeout: int):
    cfg = load_config()
    seat_id = cfg.get("seat")
    if not seat_id or not cfg.get("token"):
        print("❌ 未入座或缺少令牌，请先执行主持人提供的自举命令")
        sys.exit(EXIT_ERROR)

    res = api_request(cfg, "GET", "/api/player/wait", params={"seat_id": seat_id, "timeout": timeout}, timeout=timeout + 15)
    code = res.get("code", 0)
    events = res.get("events", res.get("recent_events", []))
    try:
        fresh_events = persist_events(res["room_id"], events) if events else []
    except (OSError, ValueError) as exc:
        print(f"❌ 事件日志未能保存，本次不确认接收: {exc}")
        sys.exit(EXIT_ERROR)
    cfg = load_config()
    previous_cfg = dict(cfg)
    if res.get("room_id"):
        cfg["room_id"] = res["room_id"]
    action = res.get("action") if code == EXIT_ACT else None
    for event in fresh_events:
        if action and event.get("event_type") == "ACTION_REQUEST" and event.get("data", {}).get("request_id") == action["request_id"]:
            continue
        print(f"#{event['seq']} {event['title']}: {event['content']}")

    if code == EXIT_ACT:
        cfg["pending_action"] = action
        deadline = time.strftime("%H:%M:%S", time.localtime(action["deadline"])) if action.get("deadline") else "未设置"
        print(f"行动 {action['request_id']} · {action.get('phase', '当前')} · {action.get('action_type', 'ACT')} · 截止 {deadline}")
        print(action.get("prompt", "请做出行动。"))
        if action.get("options"):
            print(f"可选分支: {', '.join(action['options'])}")
            print('提交选择: arena act --choice "候选项"')
        elif action.get("action_options"):
            for option in action["action_options"]:
                details = {key: option[key] for key in ("value", "targets", "value_schema", "text_schema", "risk_tags") if option.get(key) is not None and option.get(key) != []}
                print(f"{option['option_id']}: {option.get('text', '')}" + (" " + json.dumps(details, ensure_ascii=False) if details else ""))
            print('提交选择: arena act --choice "选项编号" --watch')
        if action.get("action_type") == "NUMBER":
            print(f"允许范围: {action.get('min_value')} 至 {action.get('max_value')}")
            print("提交数值: arena act --value 10")
        print('提交并继续监听: python agent.py act "回答" --watch；长文使用 --file action.txt。')

    elif code == EXIT_OBSERVE:
        print('观察更新；有新想法时用 note 记录，随后 watch。')
    sys.stdout.flush()
    if cfg != previous_cfg:
        save_config(cfg)
    if events:
        api_request(cfg, "POST", "/api/player/ack", body={
            "seat_id": seat_id, "room_id": res["room_id"], "seq": events[-1]["seq"]
        })
    return code


def cmd_wait(args):
    follow = args.command == "watch" or args.follow
    delay = 1
    try:
        while True:
            try:
                code = receive_update(args.timeout or 50)
            except SystemExit as exc:
                if not follow or exc.code != EXIT_CONN_FAIL:
                    raise
                print(f"连接中断，{delay} 秒后重新连接。", flush=True)
                time.sleep(delay)
                delay = min(delay * 2, 15)
                continue
            delay = 1
            if not follow or code in (EXIT_ACT, EXIT_OBSERVE):
                sys.exit(code)
    except KeyboardInterrupt:
        sys.exit(130)


def cmd_act(args):
    cfg = load_config()
    seat_id = cfg.get("seat")
    if not seat_id or not cfg.get("token"):
        print("❌ 未入座或缺少令牌，请先执行主持人提供的自举命令")
        sys.exit(EXIT_ERROR)

    content = ""
    action_file = Path(args.file) if args.file else Path("action.txt")

    used_file = False
    if args.file:
        content = action_file.read_text(encoding="utf-8").strip()
        used_file = True
    elif args.content:
        content = " ".join(args.content).strip()
    elif args.choice is None and args.value is None and not args.data and action_file.exists():
        content = action_file.read_text(encoding="utf-8").strip()
        used_file = True

    structured = {}
    if args.choice is not None:
        structured["choice"] = args.choice
        content = content or args.choice
    if args.value is not None:
        structured["value"] = args.value
        content = content or str(args.value)
    if args.data:
        try:
            extra = json.loads(Path(args.data).read_text(encoding="utf-8"))
            if not isinstance(extra, dict):
                raise ValueError("结构化数据必须是 JSON 对象")
            structured.update(extra)
            content = content or json.dumps(extra, ensure_ascii=False)
        except (OSError, ValueError) as exc:
            print(f"❌ 结构化数据无效: {exc}")
            sys.exit(EXIT_ERROR)

    if not content:
        print("❌ 错误: 提交内容为空！请将内容写入 action.txt 或通过命令行参数传入。")
        sys.exit(EXIT_ERROR)

    payload = {
        "seat_id": seat_id,
        "token": cfg["token"],
        "action_type": args.type or cfg.get("pending_action", {}).get("action_type", "ACT"),
        "content": content,
        "secret_reason": args.reason or None,
        "data": structured or None
    }

    pending_submission = cfg.get("pending_submission", {})
    previous_payload = {key: value for key, value in pending_submission.items() if key != "request_id"}
    payload["request_id"] = args.request_id or cfg.get("pending_action", {}).get("request_id") or (
        pending_submission.get("request_id") if previous_payload == payload else uuid.uuid4().hex
    )
    cfg = load_config()
    cfg["pending_submission"] = payload
    save_config(cfg)

    res = api_request(cfg, "POST", "/api/player/act", body=payload)
    cfg = load_config()
    previous_cfg = dict(cfg)
    for key in ("pending_action", "pending_submission"):
        if cfg.get(key, {}).get("request_id") == payload["request_id"]:
            cfg.pop(key)
    if cfg != previous_cfg:
        save_config(cfg)
    print(f"✅ 行动已成功提交！(事件序列号: #{res.get('event_seq')})")

    # 归档 action.txt
    if used_file and action_file.name == "action.txt":
        try:
            action_file.replace(action_file.with_name("action.sent.txt"))
        except OSError as exc:
            print(f"行动已提交，文件归档失败：{exc}")

    if getattr(args, "watch", False):
        cmd_wait(argparse.Namespace(command="watch", follow=True, timeout=50))
    sys.exit(EXIT_OK)


def cmd_log(args):
    cfg = load_config()
    seat_id = cfg.get("seat")
    if not seat_id or not cfg.get("token"):
        print("❌ 未入座或缺少令牌")
        sys.exit(EXIT_ERROR)

    res = api_request(cfg, "GET", "/api/player/log", params={"seat_id": seat_id, "limit": args.limit, **({"since_seq": args.since} if args.since is not None else {})})
    events = res.get("events", [])

    print(f"=== {seat_id}号位 可见事件流 (共 {len(events)} 条) ===")
    for ev in events:
        time_str = time.strftime("%H:%M:%S", time.localtime(ev["timestamp"]))
        scope_tag = "[私信]" if ev["scope"] == "PRIVATE" else "[公开]"
        print(f"#{ev['seq']} [{time_str}] {scope_tag} {ev['title']}")
        print(f"  {ev['content']}")
    if res.get("has_more"):
        print(f"继续：python agent.py log --since {res['next_seq']}")
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


def cmd_note(args):
    cfg = load_config()
    if not cfg.get("seat") or not cfg.get("token") or not cfg.get("room_id"):
        print("❌ 请先执行主持人提供的自举命令")
        sys.exit(EXIT_ERROR)
    text = " ".join(args.content).strip()
    queue = cfg.get("pending_notes", [])
    if args.discard:
        cfg["pending_notes"] = [item for item in queue if item["note_id"] != args.discard]
        save_config(cfg)
        print("待确认记录已撤下")
        sys.exit(EXIT_OK)
    if len(text) > 8000:
        print("❌ 一条自述最多 8000 字符")
        sys.exit(EXIT_ERROR)
    if text:
        fields = {"content": text, "remember": args.remember, "revises_seq": args.revises,
                  "related_seq": args.about, "request_id": args.request_id or cfg.get("pending_action", {}).get("request_id")}
        if not any(item["room_id"] == cfg["room_id"] and item["seat_id"] == cfg["seat"]
                   and all(item.get(key) == value for key, value in fields.items()) for item in queue):
            queue.append({**fields, "seat_id": cfg["seat"], "room_id": cfg["room_id"],
                          "note_id": uuid.uuid4().hex, "created_at": time.time(), "channel": "cli"})
            cfg["pending_notes"] = queue
            save_config(cfg)
    elif not args.retry or not any(item["room_id"] == cfg["room_id"] and item["seat_id"] == cfg["seat"] for item in queue):
        print('❌ 请使用 note "此刻的想法"，或用 note --retry 补发待确认记录')
        sys.exit(EXIT_ERROR)
    for entry in queue:
        if entry["room_id"] != cfg["room_id"] or entry["seat_id"] != cfg["seat"]:
            continue
        try:
            result = api_request(cfg, "POST", "/api/player/notes", body={**entry, "token": cfg["token"]})
        except SystemExit:
            print(f"自述仍待确认：{entry['note_id']}；可用 note --retry 重试，或 note --discard {entry['note_id']} 撤下")
            raise
        latest = load_config()
        remaining = [item for item in latest.get("pending_notes", []) if item["note_id"] != entry["note_id"]]
        if remaining:
            latest["pending_notes"] = remaining
        else:
            latest.pop("pending_notes", None)
        save_config(latest)
        print(f"💭 自述已记录 #{result['event_seq']}")
    sys.exit(EXIT_OK)


def cmd_notes(args):
    cfg = load_config()
    if not cfg.get("seat") or not cfg.get("token") or not cfg.get("room_id"):
        print("❌ 请先执行主持人提供的自举命令")
        sys.exit(EXIT_ERROR)
    result = api_request(cfg, "GET", "/api/player/notes", params={
        "seat_id": cfg["seat"], "room_id": cfg["room_id"], "view": args.view, "limit": args.limit,
        **({"since_seq": args.since} if args.since is not None else {})})
    remembered = set(result["remembered_seqs"])
    for event in result["events"]:
        stamp = time.strftime("%H:%M:%S", time.localtime(event["timestamp"]))
        tag = " [保留记忆]" if event["seq"] in remembered else ""
        print(f"#{event['seq']} {stamp}{tag} {event['content']}")
    if result.get("pending_action"):
        action = result["pending_action"]
        print("当前待办：" + json.dumps(action, ensure_ascii=False, separators=(",", ":")))
    print(f"读取游标：{result['next_seq']}")
    if result.get("has_more"):
        print(f"继续：python agent.py notes --view history --since {result['next_seq']}")
    sys.exit(EXIT_OK)


def cmd_game(args):
    cfg = load_config()
    if not cfg.get("seat") or not cfg.get("token") or not cfg.get("room_id"):
        print("❌ 请先执行主持人提供的自举命令，获取本局房间和席位凭证")
        sys.exit(EXIT_ERROR)
    view = api_request(cfg, "GET", "/api/player/game", params={"seat_id": cfg["seat"], "room_id": cfg["room_id"]})
    print(json.dumps(view, ensure_ascii=False, indent=2))
    sys.exit(EXIT_OK)


def main():
    parser = argparse.ArgumentParser(description="Agent Arena 客户端")
    subparsers = parser.add_subparsers(dest="command")

    # join
    p_join = subparsers.add_parser("join", help="接入竞技场席位")
    p_join.add_argument("--server", type=str, help="竞技场服务端地址")
    p_join.add_argument("--seat", type=int, help="座次号")
    p_join.add_argument("--name", type=str, help="智能体名称")
    p_join.add_argument("--role", type=str, help="角色名/职能")
    p_join.add_argument("--model", type=str, help="运行的模型名 (如 claude-3-7-sonnet / deepseek-v3)")
    p_join.add_argument("--harness", type=str, help="运行环境 (如 Claude Code / ZCode)")
    p_join.add_argument("--claim-token", type=str, help="主持人发放的席位认领令牌")

    # wait
    p_wait = subparsers.add_parser("wait", aliases=["watch"], help="后台长轮询挂起等待行动 (退出码 42/43)")
    p_wait.add_argument("--timeout", type=int, default=50, help="单次挂起超时秒数")
    p_wait.add_argument("--follow", action="store_true", help="超时续接，断线自动重连，收到行动或观察事件后退出；watch 默认启用")

    # act
    p_act = subparsers.add_parser("act", help="提交正式行动")
    p_act.add_argument("--type", type=str, help="动作类型，默认使用主持人指令")
    p_act.add_argument("--request-id", type=str, help="行动编号，默认使用最近收到的指令")
    p_act.add_argument("--choice", type=str, help="投票或选择题的候选项")
    p_act.add_argument("--value", type=float, help="数值决策")
    p_act.add_argument("--data", type=str, help="结构化 JSON 数据文件")
    p_act.add_argument("--file", type=str, help="从文件读取行动内容 (默认 action.txt)")
    p_act.add_argument("--reason", type=str, help="仅主持人可见的行动附注")
    p_act.add_argument("--watch", action="store_true", help="提交成功后继续监听")
    p_act.add_argument("content", nargs="*", help="命令行直接传入的内容")

    # log
    p_log = subparsers.add_parser("log", help="查看自身视野内的历史记录")
    p_log.add_argument("--since", type=int, help="只查看该序列号之后的事件；0 从头读取")
    p_log.add_argument("--limit", type=int, default=30, help="单页条数，默认读取最近 30 条")

    p_note = subparsers.add_parser("note", help="记录一次此刻的想法")
    p_note.add_argument("content", nargs="*", help="第一人称简短自述")
    p_note.add_argument("--remember", action="store_true", help="将这条自述同时保留为记忆")
    p_note.add_argument("--revises", type=int, help="修正自己的某条自述序号")
    p_note.add_argument("--about", type=int, help="关联某条已收到的事件")
    p_note.add_argument("--request-id", help="关联行动编号，默认使用当前待办")
    p_note.add_argument("--retry", action="store_true", help="补发未确认的自述")
    p_note.add_argument("--discard", help="撤下指定编号的未确认记录")
    p_notes = subparsers.add_parser("notes", help="读取自己的自述与保留记忆")
    p_notes.add_argument("--since", type=int, help="从此序号之后继续读取")
    p_notes.add_argument("--limit", type=int, default=20, help="单页历程条数")
    p_notes.add_argument("--view", choices=["recent", "memory", "history"], default="recent", help="最近历程及记忆、仅保留记忆、完整历程分页")

    # status
    subparsers.add_parser("status", help="查看当前状态")
    subparsers.add_parser("game", help="查看自己的游戏状态与手牌")

    args = parser.parse_args()
    if args.command == "join":
        cmd_join(args)
    elif args.command in ("wait", "watch"):
        cmd_wait(args)
    elif args.command == "act":
        cmd_act(args)
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "game":
        cmd_game(args)
    elif args.command == "note":
        cmd_note(args)
    elif args.command == "notes":
        cmd_notes(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
