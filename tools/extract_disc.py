"""Extract one supplied CD image and its ISO9660 files without executing them.

Only ordinary data files/directories are created. The input archive stays read-only.
The CLI confines all generated files to this project's local/ directory.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tempfile
import time
import zipfile


MAX_IMAGE_BYTES = 2 * 1024**3
MAX_EXTRACTED_BYTES = 2 * 1024**3
MAX_ENTRIES = 20_000
MAX_DEPTH = 16
MAX_DIRECTORY_BYTES = 8 * 1024**2
MAX_TOTAL_DIRECTORY_BYTES = 32 * 1024**2
BLOCK_SIZE = 2048
RAW_SECTOR_SIZE = 2352
SYNC = b"\x00" + b"\xff" * 10 + b"\x00"
GAMES = ("a2racer1", "a2racer2")


class DiscError(ValueError):
    """The disc or destination cannot be handled safely by this extractor."""


def both_endian(data: bytes, offset: int, width: int) -> int:
    if len(data) < offset + width * 2:
        raise DiscError("Truncated ISO9660 number")
    little = int.from_bytes(data[offset : offset + width], "little")
    big = int.from_bytes(data[offset + width : offset + width * 2], "big")
    if little != big:
        raise DiscError("Mismatched ISO9660 byte-order copies")
    return little


def safe_name(identifier: bytes, directory: bool) -> str:
    try:
        name = identifier.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DiscError("Only ASCII primary-volume names are supported") from exc
    if not directory and name.endswith(";1"):
        name = name[:-2]
        # ISO9660 permits an empty extension, represented by NAME.;1.
        # Remove only that single separator, never arbitrary dots or whitespace.
        if name.endswith(".") and name.count(".") == 1 and name != ".":
            name = name[:-1]
    if not name or name in (".", "..") or name.endswith((" ", ".")):
        raise DiscError(f"Unsafe or ambiguous file name: {identifier!r}")
    if any(ord(char) < 32 or char in '/\\:<>"|?*;' for char in name):
        raise DiscError(f"Unsafe character in file name: {identifier!r}")
    stem = name.split(".")[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    if stem in reserved:
        raise DiscError("Windows device name in disc")
    return name


@dataclass(frozen=True)
class Entry:
    parts: tuple[str, ...]
    extent: int
    size: int
    directory: bool
    original_identifier: str = ""


class DiscImage:
    """Bounded read-only access to ISO2048 or raw MODE2/2352 Form1 sectors."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.stream = self.path.open("rb")
        self.image_size = self.path.stat().st_size
        self.sector_size = 0
        self.payload_offset = 0
        self.volume_blocks = 0
        try:
            self._detect()
        except BaseException:
            self.stream.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stream.close()

    def _detect(self):
        candidates = []
        for sector_size, payload_offset in ((2048, 0), (2352, 24)):
            if self.image_size % sector_size:
                continue
            self.stream.seek(16 * sector_size + payload_offset)
            marker = self.stream.read(7)
            if marker == b"\x01CD001\x01":
                candidates.append((sector_size, payload_offset))
        if len(candidates) != 1:
            raise DiscError("Unsupported or ambiguous CD sector format")
        self.sector_size, self.payload_offset = candidates[0]
        self.volume_blocks = self.image_size // self.sector_size
        pvd = self.read_extent(16, BLOCK_SIZE)
        blocks = both_endian(pvd, 80, 4)
        if not blocks or blocks > self.volume_blocks:
            raise DiscError("ISO9660 volume extends beyond image")
        if both_endian(pvd, 128, 2) != BLOCK_SIZE:
            raise DiscError("Unsupported ISO9660 logical block size")
        self.volume_blocks = blocks
        self.root_record = pvd[156:190]
        root = self._record(self.root_record, ())
        if root is None or not root.directory:
            raise DiscError("Missing ISO9660 root directory")
        self.root = root

    def _bounds(self, extent: int, size: int):
        if extent < 0 or size < 0:
            raise DiscError("Negative extent or size")
        blocks = (size + BLOCK_SIZE - 1) // BLOCK_SIZE
        if extent > self.volume_blocks or extent + blocks > self.volume_blocks:
            raise DiscError("Extent lies outside ISO9660 volume")

    def chunks(self, extent: int, size: int):
        self._bounds(extent, size)
        remaining = size
        current = extent
        while remaining:
            count = min(64, (remaining + BLOCK_SIZE - 1) // BLOCK_SIZE)
            self.stream.seek(current * self.sector_size)
            raw = self.stream.read(count * self.sector_size)
            if len(raw) != count * self.sector_size:
                raise DiscError("Truncated sector data")
            if self.payload_offset:
                payloads = []
                for position in range(0, len(raw), self.sector_size):
                    sector = raw[position : position + self.sector_size]
                    if sector[:12] != SYNC or sector[15] != 2:
                        raise DiscError("Expected raw MODE2 sector")
                    if sector[16:20] != sector[20:24] or sector[18] & 0x20:
                        raise DiscError("Unsupported MODE2 Form2 or malformed subheader")
                    payloads.append(sector[24 : 24 + BLOCK_SIZE])
                data = b"".join(payloads)
            else:
                data = raw
            chunk = data[:remaining]
            yield chunk
            remaining -= len(chunk)
            current += count

    def read_extent(self, extent: int, size: int) -> bytes:
        if size > MAX_DIRECTORY_BYTES:
            raise DiscError("Read exceeds bounded directory buffer")
        return b"".join(self.chunks(extent, size))

    def _record(self, record: bytes, parent: tuple[str, ...]) -> Entry | None:
        if len(record) < 34 or record[0] != len(record):
            raise DiscError("Truncated directory record")
        name_length = record[32]
        if not name_length or 33 + name_length > len(record):
            raise DiscError("Truncated directory identifier")
        if record[1] or record[26] or record[27] or record[25] & 0x80:
            raise DiscError("Extended attributes, interleaving or multi-extent files are unsupported")
        if both_endian(record, 28, 2) != 1:
            raise DiscError("Multi-volume files are unsupported")
        extent = both_endian(record, 2, 4)
        size = both_endian(record, 10, 4)
        self._bounds(extent, size)
        identifier = record[33 : 33 + name_length]
        directory = bool(record[25] & 2)
        if identifier in (b"\x00", b"\x01"):
            if not directory:
                raise DiscError("Special directory identifier on file")
            return Entry(parent, extent, size, True)
        name = safe_name(identifier, directory)
        return Entry(parent + (name,), extent, size, directory, identifier.decode("ascii"))

    def inventory(self) -> list[Entry]:
        result = []
        pending = [(self.root, 0)]
        visited = set()
        total_size = 0
        total_directory_size = 0
        while pending:
            directory, depth = pending.pop()
            if depth > MAX_DEPTH or directory.extent in visited:
                raise DiscError("Directory depth limit or cycle detected")
            visited.add(directory.extent)
            if not directory.size or directory.size > MAX_DIRECTORY_BYTES:
                raise DiscError("Invalid or excessive directory size")
            total_directory_size += directory.size
            if total_directory_size > MAX_TOTAL_DIRECTORY_BYTES:
                raise DiscError("Total directory byte limit exceeded")
            data = self.read_extent(directory.extent, directory.size)
            position = 0
            names = set()
            while position < len(data):
                length = data[position]
                if not length:
                    position = (position // BLOCK_SIZE + 1) * BLOCK_SIZE
                    continue
                if position + length > len(data) or position % BLOCK_SIZE + length > BLOCK_SIZE:
                    raise DiscError("Directory record crosses a sector boundary")
                record = data[position : position + length]
                entry = self._record(record, directory.parts)
                position += length
                if record[33 : 33 + record[32]] in (b"\x00", b"\x01"):
                    continue
                if entry is None:
                    continue
                key = entry.parts[-1].casefold()
                if key in names:
                    raise DiscError("Case-insensitive destination collision")
                names.add(key)
                result.append(entry)
                if len(result) > MAX_ENTRIES:
                    raise DiscError("Entry count limit exceeded")
                if entry.directory:
                    pending.append((entry, depth + 1))
                else:
                    total_size += entry.size
                    if total_size > MAX_EXTRACTED_BYTES:
                        raise DiscError("Extracted byte limit exceeded")
        return result


def child_path(root: Path, *parts: str) -> Path:
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise DiscError("Destination escapes output directory")
    return target


def reject_symlink_parents(path: Path):
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise DiscError("Symlink or reparse point in output path")


def remove_stage(stage: Path, expected_parent: Path):
    # Only newly created staging trees may be removed; check absolute bounds first.
    reject_symlink_parents(stage)
    if stage.resolve().parent != expected_parent.resolve() or stage.is_symlink():
        raise DiscError("Refusing unsafe staging cleanup")
    shutil.rmtree(stage)


def publish_stage(stage: Path, target: Path, expected_parent: Path):
    """Publish a new owned tree, tolerating bounded Windows file-lock failures."""
    for attempt, delay in enumerate((0.0, 0.05, 0.1, 0.2)):
        if delay:
            time.sleep(delay)
        reject_symlink_parents(stage)
        reject_symlink_parents(target)
        if (stage.resolve().parent != expected_parent.resolve()
                or target.resolve().parent != expected_parent.resolve()):
            raise DiscError("Refusing unsafe staging publication")
        if target.exists():
            raise DiscError("Destination appeared during extraction; refusing overwrite")
        try:
            stage.rename(target)
            return
        except PermissionError as exc:
            # Sharing/lock errors (32/33) and access denied (5) may occur while
            # Windows scans a newly written tree. Recheck bounds and absence
            # before each retry; persistent ACL failures remain failures.
            if (getattr(exc, "winerror", None) not in (5, 32, 33)
                    or attempt == 3):
                raise


def extract_archive(archive: Path, output_root: Path, game: str, *, expected_image: dict | None = None) -> dict:
    if game not in GAMES:
        raise DiscError("Unknown game id")
    output_root = Path(output_root).absolute()
    reject_symlink_parents(output_root)
    media_parent = output_root / "media"
    games_parent = output_root / "games"
    for parent in (media_parent, games_parent):
        reject_symlink_parents(parent)
        parent.mkdir(parents=True, exist_ok=True)
    media_target = child_path(media_parent, game)
    game_target = child_path(games_parent, game)
    if media_target.exists() or game_target.exists():
        raise DiscError("Game destination already exists; refusing overwrite")
    media_stage = Path(tempfile.mkdtemp(prefix=f".{game}-", dir=media_parent))
    game_stage = Path(tempfile.mkdtemp(prefix=f".{game}-", dir=games_parent))
    published_media = False
    published_game = False
    try:
        with zipfile.ZipFile(archive) as source:
            images = [entry for entry in source.infolist()
                      if not entry.is_dir() and Path(entry.filename).suffix.lower() in (".bin", ".iso")]
            if len(images) != 1:
                raise DiscError("Archive must contain exactly one BIN or ISO image")
            selected = images[0]
            if expected_image is not None:
                if (set(expected_image) != {'member', 'size', 'sha256'}
                        or selected.filename != expected_image['member']
                        or selected.file_size != expected_image['size']):
                    raise DiscError('Het gecontroleerde cd-image veranderde; import gestopt.')
            if selected.flag_bits & 1 or stat.S_ISLNK(selected.external_attr >> 16):
                raise DiscError("Encrypted image or ZIP symlink is unsupported")
            if selected.file_size <= 0 or selected.file_size > MAX_IMAGE_BYTES:
                raise DiscError("Image byte limit exceeded")
            image_path = media_stage / "disc.img"
            count = 0
            digest = hashlib.sha256()
            with source.open(selected) as incoming, image_path.open("xb") as outgoing:
                while chunk := incoming.read(1024 * 1024):
                    count += len(chunk)
                    if count > selected.file_size or count > MAX_IMAGE_BYTES:
                        raise DiscError("Image exceeds advertised or permitted length")
                    outgoing.write(chunk)
                    digest.update(chunk)
            if count != selected.file_size:
                raise DiscError("Truncated archive member")
            if expected_image is not None and digest.hexdigest() != expected_image['sha256']:
                raise DiscError('Het gecontroleerde cd-image veranderde; import gestopt.')
            with DiscImage(image_path) as disc:
                entries = disc.inventory()
                for entry in entries:
                    target = child_path(game_stage, *entry.parts)
                    if entry.directory:
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("xb") as outgoing:
                            for chunk in disc.chunks(entry.extent, entry.size):
                                outgoing.write(chunk)
                metadata = {
                    "game": game,
                    "archive": str(Path(archive).absolute()),
                    "archive_member": selected.filename,
                    "image_bytes": count,
                    "sector_format": "MODE2/2352 Form1" if disc.payload_offset else "ISO2048",
                    "sector_bytes": disc.sector_size,
                    "payload_offset": disc.payload_offset,
                    "volume_blocks": disc.volume_blocks,
                    "files": sum(not entry.directory for entry in entries),
                    "directories": sum(entry.directory for entry in entries),
                    "extracted_bytes": sum(entry.size for entry in entries if not entry.directory),
                    "media_path": str(media_target / "disc.img"),
                    "game_path": str(game_target),
                    "method": "Static ZIP and primary ISO9660 reads; no game code executed",
                    "filename_translations": [
                        {"path": "/".join(entry.parts), "original_identifier": entry.original_identifier}
                        for entry in entries
                        if entry.original_identifier != entry.parts[-1]
                    ],
                }
            (media_stage / "extraction.json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        publish_stage(media_stage, media_target, media_parent)
        published_media = True
        publish_stage(game_stage, game_target, games_parent)
        published_game = True
        return metadata
    finally:
        if not published_media:
            remove_stage(media_stage, media_parent)
        if not published_game:
            remove_stage(game_stage, games_parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--game", required=True, choices=GAMES)
    parser.add_argument("--output", type=Path, default=Path("local"))
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = args.output if args.output.is_absolute() else project / args.output
    try:
        reject_symlink_parents(output)
        if not output.resolve().is_relative_to((project / "local").resolve()):
            raise DiscError("--output must be inside this project's local/ directory")
        metadata = extract_archive(args.archive, output, args.game)
    except (DiscError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
        parser.exit(1, f"Extraction refused: {exc}\n")
    summary = {key: value for key, value in metadata.items() if key != "filename_translations"}
    summary["filename_translation_count"] = len(metadata["filename_translations"])
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
