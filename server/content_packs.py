"""本地内容包清单扫描。

内容包只在扫描阶段读取清单，不会解压或执行包内文件；单个坏包不会阻塞其它包。
"""

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path

from packaging.version import InvalidVersion, Version


DEFAULT_CONTENT_PACKS_DIR = Path(__file__).resolve().parents[1] / "data" / "content-packs"
CONTENT_PACKS_ENV = "ARENA_CONTENT_PACKS_DIR"
_ZIP_MANIFEST_NAMES = {"manifest.json", "content-pack.json", "mod.json"}
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_:\-]{1,119}$")


def _manifest_from_zip(path):
    with zipfile.ZipFile(path) as archive:
        candidates = [
            name for name in archive.namelist()
            if Path(name).name.lower() in _ZIP_MANIFEST_NAMES and not name.endswith("/")
        ]
        if not candidates:
            raise ValueError("ZIP 中缺少 manifest.json")
        name = sorted(candidates, key=lambda value: (Path(value).name.lower() != "manifest.json", value))[0]
        return json.loads(archive.read(name).decode("utf-8-sig"))


def _read_manifest(path):
    if path.suffix.lower() == ".zip":
        return _manifest_from_zip(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_manifest(manifest, source_format):
    if not isinstance(manifest, dict):
        raise ValueError("manifest 必须是 JSON 对象")
    for field in ("id", "name", "version", "format"):
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} 必须是非空字符串")
    if not _ID_RE.fullmatch(manifest["id"]):
        raise ValueError("id 只能包含字母、数字、下划线、冒号和连字符，且必须以字母开头")
    try:
        Version(manifest["version"])
    except InvalidVersion as exc:
        raise ValueError("version 不是有效版本字符串") from exc
    priority = manifest.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, (int, float)):
        raise ValueError("priority 必须是数字")
    metadata = dict(manifest)
    metadata["priority"] = priority
    metadata["source_format"] = source_format
    return metadata


def scan_content_packs(root=None):
    """扫描内容包目录，返回 ``{"packs": [...], "warnings": [...]}``。

    JSON 文件和 ZIP 文件都被视为候选包。重复 id 按 priority 降序选择，优先级相同则按
    文件名排序，以保证结果可复现。
    """

    configured = root or os.environ.get(CONTENT_PACKS_ENV)
    directory = Path(configured) if configured else DEFAULT_CONTENT_PACKS_DIR
    result = {"packs": [], "warnings": []}
    if not directory.exists():
        return result
    if not directory.is_dir():
        result["warnings"].append(f"内容包目录不是目录：{directory}")
        return result

    try:
        candidates = sorted(
            (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in {".json", ".zip"}),
            key=lambda path: path.name,
        )
    except OSError as exc:
        result["warnings"].append(f"无法扫描内容包目录：{exc}")
        return result
    by_id = {}
    for path in candidates:
        source_format = path.suffix.lower().lstrip(".")
        try:
            metadata = _validate_manifest(_read_manifest(path), source_format)
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            metadata.update({"path": str(path), "hash": digest, "sha256": digest})
        except Exception as exc:
            result["warnings"].append(f"{path.name}: {exc}")
            continue
        pack_id = metadata["id"]
        previous = by_id.get(pack_id)
        if previous is None:
            by_id[pack_id] = metadata
            continue
        ordered = sorted((previous, metadata), key=lambda item: (-item["priority"], Path(item["path"]).name))
        winner, loser = ordered
        by_id[pack_id] = winner
        result["warnings"].append(
            f"重复内容包 id {pack_id}：选择 {Path(winner['path']).name}，忽略 {Path(loser['path']).name}"
        )
    result["packs"] = sorted(by_id.values(), key=lambda item: item["id"])
    return result


def discover_content_packs(root=None):
    """兼容调用方的扫描别名。"""

    return scan_content_packs(root)


class ContentPackCatalog:
    def __init__(self, root=None):
        self.root = root

    def scan(self):
        return scan_content_packs(self.root)
