"""Native option changes on synthetic bytes; no game execution."""
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import game_options as go

ROOT = Path(__file__).resolve().parents[1]


class GameOptionsTests(unittest.TestCase):
    def test_horizon_only_changes_its_two_bytes_and_preserves_default_call(self):
        original = bytes(range(20))
        for horizon in (0, 1):
            with self.subTest(horizon=horizon):
                result = go.derive_options(original, "preserve", -1, horizon)
                self.assertEqual(result[:8], original[:8])
                self.assertEqual(result[8:10], struct.pack("<H", horizon))
                self.assertEqual(result[10:], original[10:])
        self.assertEqual(original, bytes(range(20)))
        self.assertEqual(go.derive_options(original, "preserve", -1, -1), original)
        self.assertEqual(go.derive_options(original, "preserve", -1), original)

    def test_horizon_rejects_bool_and_invalid_values_even_if_other_options_preserve(self):
        for horizon in (True, False, 2, -2, 1.0, "1", None):
            with self.subTest(horizon=horizon):
                with self.assertRaisesRegex(ValueError, "Horizon"):
                    go.derive_options(go.DEFAULT_OPTIONS, "preserve", -1, horizon)
                with self.assertRaisesRegex(ValueError, "Horizon"):
                    go.plan_options(ROOT / "local/test-fixtures/nonexistent-options-source",
                                    None, "preserve", -1, horizon)

    def test_preserving_every_field_returns_previous_plan_unchanged(self):
        previous = {"data": bytes(range(20)), "source_path": "synthetic previous"}
        source = ROOT / "local/test-fixtures/nonexistent-options-source"
        self.assertIs(go.plan_options(source, previous, "preserve", -1, -1), previous)
        self.assertIsNone(go.plan_options(source, None, "preserve", -1))

    def test_horizon_override_requires_pins_uses_all_seeds_and_preserves_sources(self):
        parent = ROOT / "local/test-fixtures"; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            source = Path(temporary)
            pins = {}
            for name in go.VERSION_HASHES:
                data = b"non-executable synthetic horizon " + name.encode()
                (source / name).write_bytes(data)
                pins[name] = hashlib.sha256(data).hexdigest()
            options = bytes(range(20))
            (source / "OPTIE.A2R").write_bytes(options)
            before = {p.name: p.read_bytes() for p in source.iterdir()}
            with self.assertRaisesRegex(ValueError, "bekende deel-I-versie"):
                go.plan_options(source, None, "preserve", -1, 1)
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, before)
            with patch.object(go, "VERSION_HASHES", pins):
                result = go.plan_options(source, None, "preserve", -1, 1)
                self.assertEqual(result["data"], options[:8] + b"\x01\x00" + options[10:])
                self.assertEqual(result["origin"], "source-options")
                self.assertEqual(result["overrides"],
                                 {"graphics": "preserve", "dashboard": -1, "horizon": 1})
                previous = {"data": options, "source_path": "synthetic previous"}
                updated = go.plan_options(source, previous, "preserve", -1, 0)
                self.assertEqual(updated["data"], options[:8] + b"\x00\x00" + options[10:])
                self.assertEqual(updated["origin"], "previous-options")
                self.assertEqual(updated["source_path"], previous["source_path"])
                self.assertEqual(previous["data"], options)
                self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, before)
                (source / "OPTIE.A2R").unlink()
                seeded = go.plan_options(source, None, "preserve", -1, 1)
                self.assertEqual(seeded["data"], go.DEFAULT_OPTIONS[:8] + b"\x01\x00"
                                 + go.DEFAULT_OPTIONS[10:])
                self.assertEqual(seeded["origin"], "native-defaults")
                (source / "A2SPEL.DAT").write_bytes(b"wrong synthetic version")
                with self.assertRaisesRegex(ValueError, "A2SPEL.DAT"):
                    go.plan_options(source, previous, "preserve", -1, 0)
                self.assertEqual((source / "A2SPEL.DAT").read_bytes(), b"wrong synthetic version")
            self.assertEqual(go.DEFAULT_OPTIONS,
                             struct.pack("<10H", 1, 1, 0, 1, 0, 0, 1, 0, 3, 4))

    def test_only_proven_fields_change_and_other_choices_survive(self):
        original = struct.pack("<10H", *range(100, 110))
        result = go.derive_options(original, "software-640", 1)
        expected = list(range(100, 110)); expected[3] = 2; expected[5] = 1
        self.assertEqual(struct.unpack("<10H", result), tuple(expected))
        self.assertEqual(original, struct.pack("<10H", *range(100, 110)))
        self.assertEqual(go.derive_options(original, "preserve", -1), original)
        self.assertEqual(struct.unpack("<H", go.derive_options(original, "accelerated-640", 0)[6:8])[0], 0)

    def test_bad_length_value_and_bool_are_rejected(self):
        for data, graphics, dashboard in ((b"x", "preserve", -1), (b"x" * 20, "other", 1),
                                           (b"x" * 20, "preserve", True), (b"x" * 20, "preserve", 2)):
            with self.subTest(graphics=graphics, dashboard=dashboard), self.assertRaises(ValueError):
                go.derive_options(data, graphics, dashboard)

    def test_override_requires_pinned_menu_and_race_preserves_inputs(self):
        parent = ROOT / "local/test-fixtures"; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            source = Path(temporary)
            pins = {}
            for name in go.VERSION_HASHES:
                data = b"non-executable synthetic " + name.encode()
                (source / name).write_bytes(data); pins[name] = hashlib.sha256(data).hexdigest()
            options = bytes(range(20)); (source / "OPTIE.A2R").write_bytes(options)
            before = {p.name: p.read_bytes() for p in source.iterdir()}
            with self.assertRaisesRegex(ValueError, "bekende deel-I-versie"):
                go.plan_options(source, None, "software-640", 1)
            with patch.object(go, "VERSION_HASHES", pins):
                result = go.plan_options(source, None, "software-640", 1)
                self.assertEqual(result["data"], go.derive_options(options, "software-640", 1))
                (source / "OPTIE.A2R").unlink()
                previous = {"data": options, "source_path": "synthetic previous options"}
                result = go.plan_options(source, previous, "software-640", 1)
                self.assertEqual(result["source_path"], previous["source_path"])
                same = {"data": result["data"], "source_path": "previous", "source_mtime_ns": 1234}
                unchanged = go.plan_options(source, same, "software-640", 1)
                self.assertEqual(unchanged["source_mtime_ns"], 1234)
                seeded = go.plan_options(source, None, "software-640", 1)
                self.assertEqual(seeded["data"], go.derive_options(go.DEFAULT_OPTIONS, "software-640", 1))
                self.assertEqual(seeded["origin"], "native-defaults")
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, {n: d for n, d in before.items() if n != "OPTIE.A2R"})


if __name__ == "__main__":
    unittest.main()
