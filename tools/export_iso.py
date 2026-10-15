"""Export an existing local CD data volume as an unchanged ISO2048 image.

Raw MODE2/2352 Form1 headers are removed; every logical ISO9660 sector,
including its primary volume descriptor, is preserved byte for byte. This
does not reproduce audio tracks or data beyond the declared ISO9660 volume.
The tool does not mount images or execute game code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))
from tools.extract_disc import (  # noqa: E402
    BLOCK_SIZE, GAMES, MAX_IMAGE_BYTES, DiscError, DiscImage,
    publish_stage, reject_symlink_parents, remove_stage,
)


def _hash_image(path: Path) -> str:
    reject_symlink_parents(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise DiscError("Source must be an ordinary image file")
    if not 0 < info.st_size <= MAX_IMAGE_BYTES:
        raise DiscError("Image byte limit exceeded")
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            if count > MAX_IMAGE_BYTES:
                raise DiscError("Image grew beyond byte limit")
            digest.update(chunk)
    if count != info.st_size:
        raise DiscError("Image size changed during hashing")
    return digest.hexdigest()


def export_iso(workspace: Path, game: str) -> dict:
    """Publish a new ISO and report inside workspace/local/media/<game>/.

    Only fixed source/destination names are accepted. Existing destinations,
    symlink/reparse-point ancestors and changing sources are refused.
    """
    if game not in GAMES:
        raise DiscError("Unknown game id")
    workspace = Path(workspace).absolute()
    parent = workspace / "local" / "media" / game
    source = parent / "disc.img"
    target = parent / "iso2048"
    for path in (source, target):
        reject_symlink_parents(path)
    if not parent.is_dir():
        raise DiscError("Extracted local media directory does not exist")
    if target.exists():
        raise DiscError("ISO destination already exists; refusing overwrite")
    source_info = source.stat()
    source_hash = _hash_image(source)
    stage = Path(tempfile.mkdtemp(prefix=".iso2048-", dir=parent))
    published = False
    try:
        output = stage / "disc.iso"
        digest = hashlib.sha256()
        written = 0
        with DiscImage(source) as disc:
            pvd = disc.read_extent(16, BLOCK_SIZE)
            volume_label = pvd[40:72]
            expected_bytes = disc.volume_blocks * BLOCK_SIZE
            if expected_bytes > MAX_IMAGE_BYTES:
                raise DiscError("ISO volume byte limit exceeded")
            with output.open("xb") as outgoing:
                for chunk in disc.chunks(0, expected_bytes):
                    outgoing.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if written != expected_bytes:
                raise DiscError("Logical volume length changed during export")
            metadata = {
                "game": game,
                "source_path": str(source),
                "source_bytes": source_info.st_size,
                "source_sha256": source_hash,
                "source_sector_format": "MODE2/2352 Form1" if disc.payload_offset else "ISO2048",
                "source_sector_bytes": disc.sector_size,
                "source_payload_offset": disc.payload_offset,
                "volume_blocks": disc.volume_blocks,
                "volume_label": volume_label.decode("ascii", errors="replace").rstrip(" "),
                "volume_label_bytes_hex": volume_label.hex(),
                "iso_path": str(target / "disc.iso"),
                "iso_bytes": written,
                "iso_sha256": digest.hexdigest(),
                "iso_sector_bytes": BLOCK_SIZE,
                "source_verified_unchanged": True,
                "method": "Unmodified ISO9660 logical sectors; no mount or game execution",
                "limitations": "Data volume only; no audio tracks, raw headers or trailing sectors; no EDC/ECC validation",
            }
        # Verify the actual saved bytes and descriptor before publishing them.
        if _hash_image(output) != metadata["iso_sha256"]:
            raise DiscError("Saved ISO hash does not match exported sectors")
        with DiscImage(output) as check:
            if (check.sector_size != BLOCK_SIZE
                    or check.volume_blocks != metadata["volume_blocks"]
                    or check.read_extent(16, BLOCK_SIZE) != pvd):
                raise DiscError("Saved ISO volume descriptor differs from source")
        current_info = source.stat()
        if (current_info.st_size != source_info.st_size
                or current_info.st_mtime_ns != source_info.st_mtime_ns
                or current_info.st_ino != source_info.st_ino
                or current_info.st_dev != source_info.st_dev
                or _hash_image(source) != source_hash):
            raise DiscError("Source image changed during export; refusing publication")
        (stage / "export.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        publish_stage(stage, target, parent)
        published = True
        return metadata
    finally:
        if not published:
            remove_stage(stage, parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, choices=GAMES)
    args = parser.parse_args()
    try:
        metadata = export_iso(WORKSPACE, args.game)
    except (DiscError, OSError) as exc:
        parser.exit(1, f"ISO export refused: {exc}\n")
    print(json.dumps(metadata, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
