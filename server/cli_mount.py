"""动态 CLI 入口挂载与生命周期管理 (cli_mount.py)

在服务端启动时自动挂载全局 `arena` CLI 入口到当前 Python 环境。
在服务端关闭时自动清理注销，杜绝常驻污染。
"""

import atexit
import os
import stat
import sys
from pathlib import Path
from typing import Optional

CLIENT_SCRIPT = Path(__file__).resolve().parent.parent / "client" / "agent.py"


def get_scripts_dir() -> Path:
    """获取当前 Python 环境的可执行脚本目录"""
    if sys.platform == "win32":
        return Path(sys.prefix) / "Scripts"
    return Path(sys.prefix) / "bin"


def get_cli_entry_path() -> Path:
    """获取平台对应的 CLI 文件路径"""
    scripts_dir = get_scripts_dir()
    if sys.platform == "win32":
        return scripts_dir / "arena.cmd"
    return scripts_dir / "arena"


def mount_cli() -> Optional[Path]:
    """服务端启动时：挂载全局 arena 命令行入口"""
    try:
        scripts_dir = get_scripts_dir()
        scripts_dir.mkdir(parents=True, exist_ok=True)
        cli_file = get_cli_entry_path()
        python_exe = sys.executable

        if sys.platform == "win32":
            content = f'@echo off\n"{python_exe}" "{CLIENT_SCRIPT.resolve()}" %*\n'
            cli_file.write_text(content, encoding="utf-8")
        else:
            content = f'#!/bin/sh\nexec "{python_exe}" "{CLIENT_SCRIPT.resolve()}" "$@"\n'
            cli_file.write_text(content, encoding="utf-8")
            cli_file.chmod(cli_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        return cli_file
    except Exception as e:
        print(f"⚠️ 动态挂载 arena CLI 失败 (可能需要写入权限): {e}")
        return None


def unmount_cli():
    """服务端关闭时：自动注销并清理 arena 命令行入口"""
    try:
        cli_file = get_cli_entry_path()
        if cli_file.exists():
            cli_file.unlink()
            print(f"🧹 已自动注销并清理 arena CLI 入口: {cli_file}")
    except Exception as e:
        print(f"⚠️ 注销 arena CLI 失败: {e}")


# 注册 Python 退出自动清理
atexit.register(unmount_cli)
