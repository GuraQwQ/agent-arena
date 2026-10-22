"""设置与运行模块必须一起提交或回滚。"""
import json
from pathlib import Path
from fastapi import FastAPI
from test_engine import EngineCase
from mods import ModManager, ModConflict
from gameplay import ACTIVE_MODULES, _load_unmanaged

class ModSettingsTest(EngineCase):
    def test_failed_reload_and_archive_restore_use_consistent_settings(self):
        previous = dict(ACTIVE_MODULES)
        self.addCleanup(lambda: (ACTIVE_MODULES.clear(), ACTIVE_MODULES.update(previous), _load_unmanaged.cache_clear()))
        root = Path(self.directory.name) / "mods"
        directory = root / "example"
        directory.mkdir(parents=True)
        manifest = {"id":"example", "type":"extension", "version":"1", "settings": {
            "speed": {"type":"integer", "label":"速度", "default":1}}}
        (directory / "mod.json").write_text(json.dumps(manifest), encoding="utf-8")
        (directory / "mod.py").write_text('API_VERSION=1\ndef configure(settings, context):\n    if settings["speed"] == 2: raise ValueError("重载失败")\n    context.engine.mod_value=lambda: settings["speed"]\n', encoding="utf-8")
        manager = ModManager(root, self.room, FastAPI())
        manager.apply(["example"])
        before = self.path.read_bytes()
        with self.assertRaises(ModConflict): manager.update_settings("example", {"speed":2})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.room.mod_settings["example"]["speed"], 1)
        self.assertEqual(self.room.mod_value(), 1)
        archived = self.room.snapshot().model_dump(mode="json")
        manager.update_settings("example", {"speed":3})
        manager.apply(["example"], restore_snapshot=archived)
        self.assertEqual(self.room.mod_value(), 1)
        self.assertEqual(self.room.mod_settings["example"]["speed"], 1)
