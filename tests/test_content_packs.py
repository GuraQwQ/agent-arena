"""内容包清单扫描的最小行为覆盖。"""

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from content_packs import scan_content_packs


class ContentPackTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def write_json(self, filename, **manifest):
        (self.root / filename).write_text(json.dumps(manifest), encoding="utf-8")

    def test_scans_json_and_zip_and_returns_hash(self):
        self.write_json("one.json", id="one", name="One", version="1.0", format="json")
        with zipfile.ZipFile(self.root / "two.zip", "w") as archive:
            archive.writestr("manifest.json", json.dumps({"id": "two", "name": "Two", "version": "2", "format": "zip"}))
        result = scan_content_packs(self.root)
        self.assertEqual([pack["id"] for pack in result["packs"]], ["one", "two"])
        self.assertEqual(len(result["packs"][0]["hash"]), 64)
        self.assertFalse(result["warnings"])

    def test_bad_package_does_not_block_and_duplicate_uses_priority(self):
        self.write_json("bad.json", id="bad", name="Bad", version="broken", format="json")
        self.write_json("low.json", id="same", name="Low", version="1", format="json", priority=1)
        self.write_json("high.json", id="same", name="High", version="1", format="json", priority=2)
        result = scan_content_packs(self.root)
        self.assertEqual(result["packs"][0]["name"], "High")
        self.assertEqual(len(result["packs"]), 1)
        self.assertTrue(any("bad.json" in warning for warning in result["warnings"]))
        self.assertTrue(any("重复内容包" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
