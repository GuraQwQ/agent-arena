"""mock_agent.py —— 自动化模拟智能体 (用于单机联调、系统演示或缺席补位)

用法:
    python scripts/mock_agent.py --seat 1 --claim-token "主持人发放的令牌" --name "模拟博弈者A" --model "mock-llm-v1"
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = ROOT_DIR / "workspace"


def run_cmd(cwd: Path, args: list) -> tuple:
    p = subprocess.run([sys.executable, "agent.py"] + args, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def simulate_agent(seat: int, name: str, model: str, claim_token: str = ""):
    agent_dir = WORKSPACE_DIR / f"agent_{seat}"
    if not (agent_dir / "agent.py").exists():
        print(f"❌ 目录 {agent_dir} 未就绪，请先运行: python scripts/init_workspace.py --count {seat}")
        return

    print(f"🤖 模拟智能体启动: {seat}号位 [{name}]")

    if not claim_token:
        cfg_path = agent_dir / ".agent.json"
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}
        if not cfg.get("token"):
            print("❌ 请先在该工作目录执行主持人控制台复制的自举命令，或传入 --claim-token")
            return
    
    # 1. 入座
    join_args = ["join", "--seat", str(seat), "--name", name, "--model", model, "--harness", "MockHarness"]
    if claim_token:
        join_args.extend(["--claim-token", claim_token])
    code, out, _ = run_cmd(agent_dir, join_args)
    print(out)
    if code != 0:
        return

    # 2. 挂起循环
    turn_count = 0
    while True:
        print(f"[{name}] 进入长轮询挂起监听...")
        code, out, _ = run_cmd(agent_dir, ["watch", "--timeout", "30"])

        if code == 42:
            turn_count += 1
            print(f"\n⚡ [{name}] 捕获退出码 42 (轮到行动):")
            print(out)
            
            # 模拟思考 1~2 秒
            time.sleep(1.5)
            
            # 写入 action.txt
            content = f"我是{seat}号位【{name}】。根据当前事态推演，我决定支持全局提议，并在此留下推论记录 #{turn_count}。"
            (agent_dir / "action.txt").write_text(content, encoding="utf-8")
            
            # 提交行动
            reason = f"暗中策略: 第{turn_count}次试探性表态，观察他人反应。"
            pending = json.loads((agent_dir / ".agent.json").read_text(encoding="utf-8")).get("pending_action", {})
            act_args = ["act", "--reason", reason]
            if pending.get("action_type") in {"VOTE", "CHOOSE"}:
                act_args.extend(["--choice", pending["options"][0]])
            if pending.get("action_type") == "NUMBER":
                value = pending.get("min_value")
                if value is None:
                    value = min(0, pending.get("max_value") or 0)
                act_args.extend(["--value", str(value)])
            code_act, out_act, _ = run_cmd(agent_dir, act_args)
            print(out_act)
            print("-" * 50)

        elif code == 43:
            print(f"\n💭 [{name}] 捕获退出码 43 (收到观察更新):")
            print(out)
            # 记录到 memory.md
            mem_path = agent_dir / "memory.md"
            with open(mem_path, "a", encoding="utf-8") as f:
                f.write(f"\n- 观察到新动态，时间戳: {time.strftime('%H:%M:%S')}")
            print(f"[{name}] memory.md 更新完成，立即恢复监听。")
            print("-" * 50)

        elif code == 0:
            # 超时或正常退出，继续挂起
            pass
        else:
            print(f"[{name}] 异常退出码: {code}")
            break


def main():
    parser = argparse.ArgumentParser(description="运行单个模拟智能体")
    parser.add_argument("--seat", type=int, required=True, help="座次号")
    parser.add_argument("--name", type=str, default="", help="智能体名称")
    parser.add_argument("--model", type=str, default="mock-llm-3", help="模拟模型名称")
    parser.add_argument("--claim-token", type=str, default="", help="主持人发放的席位认领令牌")

    args = parser.parse_args()
    name = args.name or f"模拟者_{args.seat}"
    simulate_agent(seat=args.seat, name=name, model=args.model, claim_token=args.claim_token)


if __name__ == "__main__":
    main()
