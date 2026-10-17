"""Mod 清单、冲突诊断与运行期替换；持久状态仍由引擎原子保存。"""

import hashlib
import importlib.util
import inspect
import json
import re
import sys
import traceback
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from mod_settings import ModSettingsError, defaults_for, normalize_schema, validate_values


def mod_file(root, mod_id, relative):
    directory = (Path(root) / mod_id).resolve()
    path = (directory / relative).resolve()
    if directory.parent != Path(root).resolve() or not path.is_relative_to(directory) or not path.is_file():
        raise ValueError(f"Mod {mod_id} 的文件不存在或路径不正确：{relative}")
    return path


def read_manifest(root, mod_id):
    path = mod_file(root, mod_id, "mod.json")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("id") != mod_id:
        raise ValueError("mod.json 的 id 必须与目录名一致")
    if data.get("type") not in {"game", "extension"}:
        raise ValueError("Mod type 应为 game 或 extension")
    if not isinstance(data.get("version"), str):
        raise ValueError("Mod version 应为版本字符串")
    Version(data["version"])
    data = {"name": mod_id, "description": "", "dependencies": {}, "conflicts": [], "overrides": [], "after": [], "sources": [], "frontend": {}, "api_version": 1, "kind": data.get("type"), "capabilities": [], "settings_schema": data.get("settings", {}), **data}
    data.setdefault("entry", "game.py" if data["type"] == "game" else "mod.py")
    if not all(isinstance(data[key], str) for key in ("name", "description", "entry")):
        raise ValueError("name、description 和 entry 应为字符串")
    if isinstance(data["api_version"], bool) or not isinstance(data["api_version"], (int, str)):
        raise ValueError("api_version 应为整数或版本字符串")
    if not isinstance(data["kind"], str) or not data["kind"]:
        raise ValueError("kind 应为非空字符串")
    if not isinstance(data["capabilities"], list) or not all(isinstance(value, str) for value in data["capabilities"]):
        raise ValueError("capabilities 应为字符串列表")
    for field in ("conflicts", "overrides", "after", "sources"):
        if not isinstance(data[field], list) or not all(isinstance(value, str) for value in data[field]):
            raise ValueError(f"{field} 应为字符串列表")
    if not isinstance(data["dependencies"], dict):
        raise ValueError("dependencies 应为 Mod id 到版本范围的映射")
    for dependency, version in data["dependencies"].items():
        if not isinstance(dependency, str) or not isinstance(version, str):
            raise ValueError("依赖编号和版本范围应为字符串")
        SpecifierSet(version)
    if not isinstance(data["frontend"], dict) or any(key not in {"module", "stylesheet"} or not isinstance(value, str) for key, value in data["frontend"].items()):
        raise ValueError("frontend 仅包含 module 和 stylesheet 文件路径")
    data["settings_schema"] = normalize_schema(data.get("settings_schema", data.get("settings", {})))
    data["settings"] = normalize_schema(data.get("settings", data["settings_schema"]))
    digest = hashlib.sha256()
    rules = {key: data[key] for key in ("id", "version", "type", "entry", "dependencies", "conflicts", "overrides", "sources")}
    digest.update(json.dumps(rules, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for filename in sorted(set([data["entry"], *data["sources"]])):
        source = mod_file(root, mod_id, filename)
        digest.update(filename.encode("utf-8"))
        digest.update(source.read_bytes())
    data["rules_hash"] = digest.hexdigest()
    ui_digest = hashlib.sha256()
    ui_digest.update(json.dumps(data["frontend"], sort_keys=True).encode("utf-8"))
    for filename in data["frontend"].values():
        ui_digest.update(mod_file(root, mod_id, "ui/" + filename).read_bytes())
    data["ui_hash"] = ui_digest.hexdigest()[:16]
    return data


def load_entry(root, metadata):
    entry = mod_file(root, metadata["id"], metadata["entry"])
    for filename in [metadata["entry"], *metadata["sources"]]:
        source = mod_file(root, metadata["id"], filename)
        if source.suffix == ".py":
            cache = Path(importlib.util.cache_from_source(str(source))).resolve()
            if cache.is_relative_to(entry.parent):
                cache.unlink(missing_ok=True)
    name = f"arena_mod_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, entry, submodule_search_locations=[str(entry.parent)])
    module = importlib.util.module_from_spec(spec)
    module.VERSION = metadata["version"]
    module.CLIENT = metadata["frontend"]
    sys.modules[name] = module
    try:
        exec(compile(entry.read_text(encoding="utf-8-sig"), str(entry), "exec"), module.__dict__)
        if getattr(module, "API_VERSION", None) != 1:
            raise ValueError("API_VERSION 必须为 1")
        if metadata["type"] == "game":
            for method in ("create", "observe", "requests", "step"):
                if not callable(getattr(module, method, None)):
                    raise ValueError(f"游戏缺少 {method} 函数")
        return module
    except BaseException:
        unload_entry(module)
        raise


def unload_entry(module):
    for name in list(sys.modules):
        if name == module.__name__ or name.startswith(module.__name__ + "."):
            sys.modules.pop(name, None)


def snapshot_mods(snapshot):
    if snapshot.get("mod_profile"):
        return snapshot["mod_profile"]
    game = snapshot.get("game")
    return [{"id": game["name"], "version": str(game["version"]), "type": "game", "rules_hash": None}] if game else []


class ModConflict(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("；".join(issue["message"] for issue in issues))


class ModContext:
    """Mod 专属运行上下文，隔离设置命名空间并保留扩展点。"""

    def __init__(self, manager, mod_id, app, engine, settings):
        self.manager = manager
        self.mod_id = mod_id
        self.app = app
        self.engine = engine
        self.settings = settings

    def get(self, key, default=None):
        return self.settings.get(key, default)


class ModManager:
    def __init__(self, root, engine, core_app):
        self.root = Path(root)
        self.engine = engine
        self.core_app = core_app
        self.current_app = core_app
        self.generation = 0
        self.enabled = []
        self.modules = {}
        self.loaded = {}
        self.original_attributes = {}
        self.issues = []

    def catalog(self):
        result = {}
        for directory in sorted(self.root.iterdir()) if self.root.exists() else []:
            if not directory.is_dir() or directory.name.startswith(".") or directory.name == "__pycache__":
                continue
            try:
                result[directory.name] = read_manifest(self.root, directory.name)
            except (OSError, ValueError, InvalidVersion, InvalidSpecifier) as exc:
                result[directory.name] = {"id": directory.name, "name": directory.name, "error": str(exc)}
        return result

    def plan(self, enabled, locked=None):
        catalog = self.catalog()
        enabled = list(dict.fromkeys(enabled))
        issues = []
        graph = {}
        claims = {}
        def issue(code, message, mods, **extra):
            issues.append({"code": code, "message": message, "mods": mods, "severity": "error", **extra})
        for mod_id in enabled:
            mod = catalog.get(mod_id)
            if mod is None or mod.get("error"):
                issue("missing", f"{mod_id}：{mod.get('error') if mod else '本机未安装'}", [mod_id])
                continue
            if str(mod.get("api_version", 1)) != "1":
                issue("api_version", f"{mod_id} 需要不兼容的 Mod API 版本 {mod.get('api_version')}，当前服务支持 1", [mod_id])
            graph[mod_id] = set()
            for dependency, requirement in mod["dependencies"].items():
                target = catalog.get(dependency)
                if dependency not in enabled:
                    issue("dependency", f"{mod_id} 需要启用 {dependency} {requirement or '任意版本'}", [mod_id, dependency])
                elif target and not target.get("error") and Version(target["version"]) not in SpecifierSet(requirement):
                    issue("version", f"{mod_id} 需要 {dependency} {requirement}，本机为 {target['version']}", [mod_id, dependency])
                if dependency in enabled:
                    graph[mod_id].add(dependency)
            graph[mod_id].update(other for other in mod["after"] if other in enabled)
            for other in mod["conflicts"]:
                if other in enabled:
                    issue("declared", f"{mod_id} 声明与 {other} 不兼容", [mod_id, other])
            for claim in mod["overrides"]:
                if claim in claims:
                    issue("override", f"{mod_id} 与 {claims[claim]} 同时覆盖 {claim}", [claims[claim], mod_id], resource=claim)
                claims[claim] = mod_id
        game = self.engine.game
        if locked is None and game and game["name"] not in enabled:
            issue("current_game", f"当前牌局需要 {game['name']}；请保留其启用状态", [game["name"]])
        if locked is None and game and game["name"] in enabled:
            current = catalog.get(game["name"], {})
            if current.get("version") and str(current["version"]) != str(game["version"]):
                issue("current_version", f"当前牌局使用 {game['name']} {game['version']}，本机为 {current['version']}；请使用兼容版本或先开启新局", [game["name"]])
        for required in locked or []:
            mod_id = required["id"]
            actual = catalog.get(mod_id)
            if not actual or actual.get("error"):
                issue("archive_missing", f"存档需要 {mod_id} {required['version']}，本机不可用", [mod_id])
            elif str(actual["version"]) != str(required["version"]):
                issue("archive_version", f"存档需要 {mod_id} {required['version']}，本机为 {actual['version']}", [mod_id])
            elif required.get("rules_hash") and required["rules_hash"] != actual["rules_hash"]:
                issue("archive_rules", f"{mod_id} 版本号相同，但规则源码与存档不一致", [mod_id], expected=required["rules_hash"], actual=actual["rules_hash"])
        try:
            order = list(TopologicalSorter(graph).static_order())
        except CycleError as exc:
            order = []
            issue("cycle", "加载顺序存在循环：" + " → ".join(map(str, exc.args[1])), list(exc.args[1]))
        return {"valid": not issues, "issues": issues, "order": order, "catalog": catalog}

    def status(self):
        catalog = self.catalog()
        settings, setting_issues = self.settings_status(catalog)
        return {"mods": list(catalog.values()), "enabled": self.enabled, "order": self.enabled,
                "generation": self.generation, "issues": self.issues + setting_issues, "profile": self.engine.mod_profile,
                "loaded": self.loaded, "settings": settings}

    def settings_status(self, catalog=None):
        catalog = catalog or self.catalog()
        result = []
        issues = []
        for mod_id, metadata in catalog.items():
            schema = metadata.get("settings", {})
            if metadata.get("error") or not schema:
                continue
            stored = self.engine.mod_settings.get(mod_id, {})
            try:
                values = validate_values(schema, stored)
            except ModSettingsError as exc:
                values = stored
                issues.append({"code": "settings", "severity": "error", "mods": [mod_id], "message": f"{mod_id} 的已保存设置无效：{exc}"})
            result.append({"id": mod_id, "name": metadata["name"], "version": metadata["version"],
                           "enabled": mod_id in self.enabled, "schema": schema, "values": values,
                           "defaults": defaults_for(schema)})
        return result, issues

    def update_settings(self, mod_id, values):
        metadata = self.catalog().get(mod_id)
        if not metadata or metadata.get("error"):
            raise ModSettingsError(f"Mod {mod_id} 不存在或清单无效")
        normalized = validate_values(metadata.get("settings", {}), values)
        self.engine.update_mod_settings(mod_id, normalized)
        if mod_id in self.enabled:
            return self.apply(self.enabled)
        return self.status()

    def _new_app(self):
        candidate = FastAPI(title=self.core_app.title, exception_handlers=self.core_app.exception_handlers,
                            middleware=list(self.core_app.user_middleware), docs_url=None, redoc_url=None, openapi_url=None)
        candidate.router.routes = list(self.core_app.router.routes)
        return candidate

    def apply(self, enabled, locked=None, restore_snapshot=None):
        with self.engine._state_lock:
            return self._apply(enabled, locked, restore_snapshot)

    def _apply(self, enabled, locked, restore_snapshot):
        plan = self.plan(enabled, locked)
        if not plan["valid"]:
            self.issues = plan["issues"]
            raise ModConflict(self.issues)
        room = self.engine
        before = room.snapshot().model_copy(deep=True)
        attributes = dict(vars(room))
        modules = {}
        owners = {}
        changes = {}
        patched_by = {}
        pending_settings = dict(room.mod_settings)
        candidate = self._new_app()
        for route in candidate.routes:
            owners[id(route)] = "Arena 核心"
        try:
            for key, original in self.original_attributes.items():
                if original[0]:
                    setattr(room, key, original[1])
                else:
                    vars(room).pop(key, None)
            base_attributes = dict(vars(room))
            for mod_id in plan["order"]:
                mod = plan["catalog"][mod_id]
                module = load_entry(self.root, mod)
                modules[mod_id] = module
                settings = validate_values(mod.get("settings", {}), room.mod_settings.get(mod_id, {}))
                pending_settings[mod_id] = settings
                context = ModContext(self, mod_id, candidate, room, settings)
                hook = getattr(module, "install", None)
                if hook:
                    if inspect.iscoroutinefunction(hook):
                        raise ValueError("install 应同步注册路由与引擎行为")
                    old_attributes = dict(vars(room))
                    if len(inspect.signature(hook).parameters) >= 3:
                        hook(candidate, room, context)
                    else:
                        hook(candidate, room)
                    for key in set(old_attributes) | set(vars(room)):
                        if key not in old_attributes or key not in vars(room) or vars(room)[key] is not old_attributes[key]:
                            if key in patched_by:
                                raise ModConflict([{"severity": "error", "code": "engine_override", "mods": [patched_by[key], mod_id], "message": f"{patched_by[key]} 与 {mod_id} 同时修改引擎属性 {key}", "resource": f"engine:{key}"}])
                            patched_by[key] = mod_id
                    if candidate.router.on_startup or candidate.router.on_shutdown:
                        raise ValueError("可重载 Mod 应在 install 中同步注册接口；后台任务需提供可重载的独立服务")
                configure = getattr(module, "configure", None)
                if configure:
                    configure(settings, context)
                for route in candidate.routes:
                    owners.setdefault(id(route), mod_id)
            routes = [route for route in candidate.routes if getattr(route, "methods", None)]
            collisions = []
            for index, route in enumerate(routes):
                for other in routes[:index]:
                    shared = route.methods & other.methods
                    same = re.sub(r"\{[^}]+\}", "{}", route.path) == re.sub(r"\{[^}]+\}", "{}", other.path)
                    overlaps = same or route.path_regex.fullmatch(other.path) or other.path_regex.fullmatch(route.path)
                    if shared and overlaps:
                        collisions.append({"severity": "error", "code": "route", "mods": [owners[id(other)], owners[id(route)]],
                            "message": f"{owners[id(other)]} 与 {owners[id(route)]} 路由冲突：{','.join(sorted(shared))} {other.path} ↔ {route.path}"})
            if collisions:
                raise ModConflict(collisions)
            if room.snapshot().model_dump() != before.model_dump():
                raise ValueError("install 改变了持久状态；请将状态变更放入规则行动或显式数据迁移")
            for key in set(base_attributes) | set(vars(room)):
                if key not in base_attributes or key not in vars(room) or vars(room)[key] is not base_attributes[key]:
                    changes[key] = (key in base_attributes, base_attributes.get(key))
            room.mod_profile = [{key: plan["catalog"][mod_id][key] for key in ("id", "name", "version", "type", "rules_hash")} for mod_id in plan["order"]]
            room.mod_settings = pending_settings
            if restore_snapshot is not None:
                room.restore_archive(restore_snapshot, archive_current=False, mod_profile=room.mod_profile)
            else:
                from models import VisibilityScope
                room.record_event("MOD_RELOAD", "Mod 组合已重载", " → ".join(plan["order"]) or "核心规则", scope=VisibilityScope.HOST_ONLY, data={"mod_profile": room.mod_profile})
        except BaseException as exc:
            vars(room).clear()
            vars(room).update(attributes)
            room._apply_snapshot(before)
            for module in modules.values():
                unload_entry(module)
            if isinstance(exc, ModConflict):
                self.issues = exc.issues
            else:
                frames = traceback.extract_tb(exc.__traceback__)
                frame = frames[-1]
                self.issues = [{"severity": "error", "code": "load", "mods": [mod_id] if 'mod_id' in locals() else [],
                    "message": f"Mod 重载失败：{exc}", "location": f"{frame.filename}:{frame.lineno}"}]
            raise ModConflict(self.issues) from exc
        from gameplay import ACTIVE_MODULES, _load_unmanaged
        ACTIVE_MODULES.clear()
        ACTIVE_MODULES.update(modules)
        _load_unmanaged.cache_clear()
        for module in self.modules.values():
            unload_entry(module)
        self.modules = modules
        self.loaded = {mod_id: {key: plan["catalog"][mod_id][key] for key in ("rules_hash", "ui_hash")} for mod_id in plan["order"]}
        self.original_attributes = changes
        self.current_app = candidate
        self.enabled = plan["order"]
        self.generation += 1
        self.issues = []
        for queue in room.sse_queues:
            queue.put_nowait({"type": "MOD_RELOAD", "data": {"generation": self.generation}})
        room.broadcast_host_update()
        return self.status()


class ModRuntime:
    def __init__(self, manager):
        self.manager = manager

    async def __call__(self, scope, receive, send):
        target = self.manager.core_app if scope["type"] == "lifespan" else self.manager.current_app
        await target(scope, receive, send)
