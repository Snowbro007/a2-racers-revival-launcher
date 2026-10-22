"""Synthetic ISO9660 fixtures; no original game content is read by these tests."""

from pathlib import Path
from contextlib import redirect_stderr
import io
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import extract_disc


def dual(value, width):
    return value.to_bytes(width, "little") + value.to_bytes(width, "big")


def record(name, extent, size, directory=False):
    length = 33 + len(name)
    if length % 2:
        length += 1
    data = bytearray(length)
    data[0] = length
    data[2:10] = dual(extent, 4)
    data[10:18] = dual(size, 4)
    data[25] = 2 if directory else 0
    data[28:32] = dual(1, 2)
    data[32] = len(name)
    data[33:33 + len(name)] = name
    return bytes(data)


def iso(entries=None, payload=b"synthetic data\n"):
    blocks = 24
    data = bytearray(blocks * 2048)
    pvd = bytearray(2048)
    pvd[:7] = b"\x01CD001\x01"
    pvd[80:88] = dual(blocks, 4)
    pvd[128:132] = dual(2048, 2)
    pvd[156:190] = record(b"\0", 20, 2048, True)
    data[16 * 2048:17 * 2048] = pvd
    directory = record(b"\0", 20, 2048, True) + record(b"\1", 20, 2048, True)
    if entries is None:
        entries = [record(b"HELLO.TXT;1", 21, len(payload))]
    directory += b"".join(entries)
    data[20 * 2048:20 * 2048 + len(directory)] = directory
    data[21 * 2048:21 * 2048 + len(payload)] = payload
    return bytes(data)


def raw_mode2(source):
    output = bytearray()
    for position in range(0, len(source), 2048):
        sector = bytearray(2352)
        sector[:12] = extract_disc.SYNC
        sector[15] = 2
        sector[24:24 + 2048] = source[position:position + 2048]
        output += sector
    return bytes(output)


class DiscImageTests(unittest.TestCase):
    def setUp(self):
        self.fixture_parent = Path(__file__).resolve().parents[1] / "local" / "test-fixtures"
        self.fixture_parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="disc-tests-", dir=self.fixture_parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.assertEqual(self.root.resolve().parent, self.fixture_parent.resolve())
        self.temp.cleanup()

    def image(self, content):
        path = self.root / "fixture.img"
        path.write_bytes(content)
        return path

    def test_iso2048_preserves_file_bytes(self):
        with extract_disc.DiscImage(self.image(iso())) as disc:
            entries = disc.inventory()
            self.assertEqual(disc.sector_size, 2048)
            self.assertEqual(entries[0].parts, ("HELLO.TXT",))
            self.assertEqual(b"".join(disc.chunks(entries[0].extent, entries[0].size)), b"synthetic data\n")

    def test_raw_mode2_preserves_file_bytes(self):
        with extract_disc.DiscImage(self.image(raw_mode2(iso()))) as disc:
            self.assertEqual((disc.sector_size, disc.payload_offset), (2352, 24))
            entry = disc.inventory()[0]
            self.assertEqual(b"".join(disc.chunks(entry.extent, entry.size)), b"synthetic data\n")

    def test_rejects_path_traversal(self):
        with extract_disc.DiscImage(self.image(iso([record(b"../BAD;1", 21, 1)]))) as disc:
            with self.assertRaises(extract_disc.DiscError):
                disc.inventory()

    def test_rejects_device_name_and_case_collision(self):
        for entries in ([record(b"CON;1", 21, 1)],
                        [record(b"ONE;1", 21, 1), record(b"one;1", 21, 1)]):
            with self.subTest(entries=entries):
                with extract_disc.DiscImage(self.image(iso(entries))) as disc:
                    with self.assertRaises(extract_disc.DiscError):
                        disc.inventory()

    def test_translates_only_standard_empty_extension(self):
        with extract_disc.DiscImage(self.image(iso([record(b"README.;1", 21, 1)]))) as disc:
            entry = disc.inventory()[0]
            self.assertEqual(entry.parts, ("README",))
            self.assertEqual(entry.original_identifier, "README.;1")
        for name in (b".;1", b"..;1", b"NAME..;1", b"NAME.;2"):
            with self.subTest(name=name):
                with self.assertRaises(extract_disc.DiscError):
                    extract_disc.safe_name(name, False)

    def test_reparse_point_parent_is_rejected(self):
        class SyntheticInfo:
            st_mode = stat.S_IFDIR
            st_file_attributes = 0x400
        with patch.object(Path, "lstat", return_value=SyntheticInfo()):
            with self.assertRaises(extract_disc.DiscError):
                extract_disc.reject_symlink_parents(self.root)

    def test_rejects_directory_cycle(self):
        with extract_disc.DiscImage(self.image(iso([record(b"CYCLE", 20, 2048, True)]))) as disc:
            with self.assertRaises(extract_disc.DiscError):
                disc.inventory()

    def test_rejects_out_of_bounds_extent(self):
        with extract_disc.DiscImage(self.image(iso([record(b"BAD;1", 24, 1)]))) as disc:
            with self.assertRaises(extract_disc.DiscError):
                disc.inventory()

    def test_rejects_inconsistent_byte_orders(self):
        malformed = bytearray(iso())
        malformed[16 * 2048 + 84:16 * 2048 + 88] = (25).to_bytes(4, "big")
        with self.assertRaises(extract_disc.DiscError):
            extract_disc.DiscImage(self.image(malformed))

    def test_rejects_form2_and_truncated_image(self):
        malformed = bytearray(raw_mode2(iso()))
        malformed[16 * 2352 + 18] = 0x20
        malformed[16 * 2352 + 22] = 0x20
        for content in (malformed, raw_mode2(iso())[:-1]):
            with self.subTest(length=len(content)):
                with self.assertRaises(extract_disc.DiscError):
                    extract_disc.DiscImage(self.image(content))

    def test_enforces_entry_limit(self):
        with extract_disc.DiscImage(self.image(iso())) as disc:
            with patch.object(extract_disc, "MAX_ENTRIES", 0):
                with self.assertRaises(extract_disc.DiscError):
                    disc.inventory()

    def test_archive_extraction_creates_only_selected_image_and_files(self):
        archive = self.root / "supplied.zip"
        with zipfile.ZipFile(archive, "w") as source:
            source.writestr("nested/disc.iso", iso())
            source.writestr("cover.jpg", b"not selected")
            source.writestr("external.url", b"not selected")
        original = archive.read_bytes()
        output = self.root / "local"
        result = extract_disc.extract_archive(archive, output, "a2racer1")
        self.assertEqual(result["files"], 1)
        self.assertEqual((output / "games/a2racer1/HELLO.TXT").read_bytes(), b"synthetic data\n")
        self.assertEqual(archive.read_bytes(), original)
        self.assertFalse(list(output.rglob("*.jpg")))
        self.assertFalse(list(output.rglob("*.url")))
        with self.assertRaises(extract_disc.DiscError):
            extract_disc.extract_archive(archive, output, "a2racer1")

    def test_rejects_zip_symlink_and_cleans_staging(self):
        archive = self.root / "supplied.zip"
        info = zipfile.ZipInfo("disc.iso")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, "w") as source:
            source.writestr(info, b"target")
        output = self.root / "local"
        with self.assertRaises(extract_disc.DiscError):
            extract_disc.extract_archive(archive, output, "a2racer1")
        self.assertEqual(list((output / "media").iterdir()), [])
        self.assertEqual(list((output / "games").iterdir()), [])

    def test_publish_retries_transient_windows_permission_error(self):
        stage = self.root / "stage"
        stage.mkdir()
        target = self.root / "published"
        original_rename = Path.rename
        calls = []
        transient = PermissionError("synthetic Windows scan lock")
        transient.winerror = 5

        def flaky_rename(path, destination):
            calls.append((path, destination))
            if len(calls) < 3:
                raise transient
            return original_rename(path, destination)

        with patch.object(Path, "rename", flaky_rename), \
                patch.object(extract_disc.time, "sleep") as sleep:
            extract_disc.publish_stage(stage, target, self.root)
        self.assertEqual(len(calls), 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.05, 0.1])
        self.assertTrue(target.is_dir())
        self.assertFalse(stage.exists())

    def test_persistent_publish_failure_removes_staging_trees(self):
        archive = self.root / "supplied.zip"
        with zipfile.ZipFile(archive, "w") as source:
            source.writestr("disc.iso", iso())
        output = self.root / "local"
        persistent = PermissionError("synthetic persistent access denial")
        persistent.winerror = 5
        with patch.object(Path, "rename", side_effect=persistent) as rename, \
                patch.object(extract_disc.time, "sleep") as sleep:
            with self.assertRaises(PermissionError):
                extract_disc.extract_archive(archive, output, "a2racer1")
        self.assertEqual(rename.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.05, 0.1, 0.2])
        self.assertEqual(list((output / "media").iterdir()), [])
        self.assertEqual(list((output / "games").iterdir()), [])

    def test_publish_refuses_destination_that_appears_during_retry(self):
        stage = self.root / "stage"
        stage.mkdir()
        target = self.root / "published"
        transient = PermissionError("synthetic Windows scan lock")
        transient.winerror = 32

        def create_destination(_):
            target.mkdir()
            (target / "existing.txt").write_bytes(b"preserve me")

        with patch.object(Path, "rename", side_effect=transient) as rename, \
                patch.object(extract_disc.time, "sleep", side_effect=create_destination):
            with self.assertRaises(extract_disc.DiscError):
                extract_disc.publish_stage(stage, target, self.root)
        self.assertEqual(rename.call_count, 1)
        self.assertEqual((target / "existing.txt").read_bytes(), b"preserve me")

    def test_publish_does_not_retry_other_permission_failures(self):
        stage = self.root / "stage"
        stage.mkdir()
        target = self.root / "published"
        denied = PermissionError("synthetic non-lock error")
        denied.winerror = 87
        with patch.object(Path, "rename", side_effect=denied) as rename, \
                patch.object(extract_disc.time, "sleep") as sleep:
            with self.assertRaises(PermissionError):
                extract_disc.publish_stage(stage, target, self.root)
        self.assertEqual(rename.call_count, 1)
        sleep.assert_not_called()

    def test_cli_reparse_guard_reports_failure_without_traceback(self):
        errors = io.StringIO()
        argv = ["extract_disc.py", "--archive", "synthetic.zip", "--game", "a2racer1"]
        with patch("sys.argv", argv), \
                patch.object(extract_disc, "reject_symlink_parents",
                             side_effect=extract_disc.DiscError("Synthetic reparse point")), \
                redirect_stderr(errors):
            with self.assertRaises(SystemExit) as result:
                extract_disc.main()
        self.assertEqual(result.exception.code, 1)
        self.assertIn("Extraction refused: Synthetic reparse point", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
