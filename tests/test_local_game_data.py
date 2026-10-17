"""Synthetic local-resource fixtures; never use real game files or mount media."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import local_game_data as data

ROOT = Path(__file__).resolve().parents[1]


def synthetic_profile(source, essential_names):
    records = [{"path": path.relative_to(source).as_posix(), "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in sorted(source.rglob("*"), key=lambda p: p.relative_to(source).as_posix())
               if path.is_file()]
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return {"files": len(records), "bytes": sum(item["size"] for item in records),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "essential": {name: (item["size"], item["sha256"])
                          for item in records if (name := item["path"]) in essential_names}}


class LocalGameDataTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "local/test-fixtures"
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="local-data-", dir=parent)
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / "game"
        self.source.mkdir()
        for name, value in {"resource.img": b"synthetic essential data", "intro.smk": b"synthetic film",
                            "tracks/route.txt": b"synthetic nonessential track", "A2.EXE": b"not executable"}.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        self.profile = synthetic_profile(self.source, {"resource.img", "intro.smk"})
        patcher = patch.object(data, "SOURCE_PROFILE", self.profile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def state(self):
        return {p.relative_to(self.source).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.source.rglob("*") if p.is_file()}

    def test_quick_and_complete_checks_are_read_only_and_need_no_image(self):
        before = self.state()
        quick = data.check_local_source(self.source)
        full = data.check_local_source(self.source, full=True)
        self.assertEqual(quick["validation"], "essential-resources")
        self.assertEqual(full["validation"], "complete-original-tree")
        self.assertFalse(full["disc_image_used"])
        self.assertEqual(full["source_tree_sha256"], self.profile["sha256"])
        self.assertEqual(full["source_files"], 4)
        self.assertEqual(before, self.state())
        self.assertEqual(list(self.source.parent.iterdir()), [self.source])

    def test_missing_or_same_size_changed_essential_resource_is_rejected(self):
        resource = self.source / "resource.img"
        resource.write_bytes(b"X" * resource.stat().st_size)
        with self.assertRaisesRegex(ValueError, "resource.img"):
            data.check_local_source(self.source)
        resource.unlink()
        with self.assertRaisesRegex(ValueError, "resource.img"):
            data.check_local_source(self.source, full=True)

    def test_missing_nonessential_track_cannot_pass_complete_check(self):
        (self.source / "tracks/route.txt").unlink()
        data.check_local_source(self.source)
        with self.assertRaisesRegex(ValueError, "volledige lokale gamebestanden"):
            data.check_local_source(self.source, full=True)

    def test_extra_file_and_renamed_file_are_rejected(self):
        extra = self.source / "unexpected.txt"
        extra.write_bytes(b"synthetic extra")
        with self.assertRaises(ValueError):
            data.check_local_source(self.source, full=True)
        extra.unlink()
        (self.source / "tracks/route.txt").rename(self.source / "tracks/renamed.txt")
        with self.assertRaisesRegex(ValueError, "onbekende versie"):
            data.check_local_source(self.source, full=True)

    def test_same_size_nonessential_bytes_are_version_bound(self):
        path = self.source / "tracks/route.txt"
        path.write_bytes(b"X" * path.stat().st_size)
        with self.assertRaisesRegex(ValueError, "onbekende versie"):
            data.check_local_source(self.source, full=True)

    def test_nonessential_size_mismatch_and_budgets_are_rejected(self):
        with patch.object(data, "MAX_FILES", 3), self.assertRaises(ValueError):
            data.check_local_source(self.source, full=True)
        with patch.object(data, "MAX_BYTES", 1), self.assertRaises(ValueError):
            data.check_local_source(self.source, full=True)
        (self.source / "tracks/route.txt").write_bytes(b"too small")
        with self.assertRaisesRegex(ValueError, "totale grootte"):
            data.check_local_source(self.source, full=True)

    def test_full_flag_rejects_truthy_nonbooleans_before_file_reads(self):
        for flag in (1, "true", None, []):
            with self.subTest(flag=flag), patch.object(data, "_file_hash", side_effect=AssertionError("read")):
                with self.assertRaises(ValueError):
                    data.check_local_source(self.source, full=flag)

    def test_ancestor_guard_precedes_resources(self):
        with patch.object(data, "validate_ancestors", side_effect=ValueError("reparse")), \
                patch.object(data, "_file_hash", side_effect=AssertionError("read")):
            with self.assertRaisesRegex(ValueError, "reparse"):
                data.check_local_source(self.source, full=True)

    def test_game_environment_uses_own_drive_and_preserves_callers_environment(self):
        with patch.dict(os.environ, {"NOCD": "existing-parent-value"}):
            self.assertEqual(data.launch_environment(Path(r"c:\synthetic\game")), {"NOCD": "C"})
            self.assertEqual(data.launch_environment(Path("D:/synthetic/game")), {"NOCD": "D"})
            self.assertEqual(os.environ["NOCD"], "existing-parent-value")

    def test_relative_unc_device_and_nondrive_paths_are_rejected(self):
        for value in ("relative/game", "C:relative", "/game", r"\\server\share\game",
                      r"\\?\C:\game", "1:/game", "é:/game"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                data.launch_environment(Path(value))
