"""init_workspace.py —— 一键生成多智能体物理隔离工作目录

用法:
    python scripts/init_workspace.py --count 4 --server http://127.0.0.1:8000
"""

import argparse
import json
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CLIENT_SRC = ROOT_DIR / "client" / "agent.py"
GUIDE_SRC = ROOT_DIR / "templates" / "AGENT_GUIDE.md"
WORKSPACE_DIR = ROOT_DIR / "workspace"


def init_workspaces(count: int, server: str, clean: bool = False, root: Path = WORKSPACE_DIR):
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    print(f"🚀 正在为 {count} 个智能体准备独立工作目录...")

    for i in range(1, count + 1):
        agent_dir = root / f"agent_{i}"
        agent_dir.mkdir(parents=True, exist_ok=True)

        # 复制 agent.py
        shutil.copy2(CLIENT_SRC, agent_dir / "agent.py")
        # 复制 AGENT_GUIDE.md
        shutil.copy2(GUIDE_SRC, agent_dir / "AGENT_GUIDE.md")

        # 初始 .agent.json
        cfg_file = agent_dir / ".agent.json"
        if clean or not cfg_file.exists():
            cfg_file.write_text(json.dumps({
                "server": server,
                "seat": i
            }, ensure_ascii=False, indent=2), encoding="utf-8")

        # 初始空 memory.md
        mem_file = agent_dir / "memory.md"
        if clean or not mem_file.exists():
            mem_file.write_text(f"# Agent {i} 私有思考笔记\n\n- 身份职责:\n- 观察推论:\n", encoding="utf-8")

        print(f"  ✓ 已就绪: {agent_dir} (seat={i})")

    print("\n✅ 所有智能体独立物理工作目录已生成完毕！")
    print(f"👉 启动智能体时，请分别切换工作目录至: {root}/agent_N/")


def main():
    parser = argparse.ArgumentParser(description="一键生成多智能体隔离目录")
    parser.add_argument("--count", type=int, default=4, help="智能体席位数量 (默认 4)")
    parser.add_argument("--server", type=str, default="http://127.0.0.1:8000", help="竞技场服务端地址")
    parser.add_argument("--clean", action="store_true", help="强制覆盖已有的配置文件与笔记")
    parser.add_argument("--root", type=Path, default=WORKSPACE_DIR, help="玩家工作目录的父目录")

    args = parser.parse_args()
    init_workspaces(count=args.count, server=args.server, clean=args.clean, root=args.root)


if __name__ == "__main__":
    main()
