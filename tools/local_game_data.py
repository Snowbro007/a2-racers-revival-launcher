"""Version-bound local data checks for A2-I's built-in NOCD environment route.

Read-only: no game execution, binary patch, drive creation or image access.
NOCD takes one drive letter, not a directory. Complete original local resources
and the game root working directory supply the first-choice local file paths.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PureWindowsPath

from tools.trial_manifest import validate_ancestors, validate_tree

SOURCE_PROFILE = {
    "files": 666,
    "bytes": 93431399,
    "sha256": "134f738aeff16eeeb0833eee8250568a336cf7160f374a37479b857a3156cde3",
    "essential": {
        "A2EXIT.SMK": (292708, "ce232c6abfc3a53ed4cb406797236035f4c68ac2e1aa4fd25c1b0fc467dc0a1f"),
        "A2INTRO.SMK": (15760752, "39b86263e0e544c9a50bb9e488d9d5829301be53bba3765797394ecc4096bb62"),
        "A2MRC.IMG": (4042041, "dd837d6a50becd675c3514770ae01102b4b17afcb3b86b281a68cd3552acc2f6"),
        "A2MRC.IND": (1318, "008b848677c486f97311f2023a4d1b3d0a18c815779ecb6ef145ab6fe06d541a"),
        "A2MRCS.IMG": (13321698, "0f0fad9eee81952b8580b1fa4b39d0d4baa8738adcd92a78a894c17744896029"),
        "A2MRCS.IND": (1442, "ce7f22faf099da56c379c695f5265e55a498c9dd09613a991289fe768b00a2e9"),
        "A2WIN.SMK": (6293340, "5ca47d6a40164b4087aab4e0c9aef27da4442900b440761d63e2b1cb22d8bfa1"),
        "RCS.IMG": (9603035, "028512563a32aa76e020d30b508f8208a6e9d22ebea4127e33b78afe641a4090"),
        "RCS.IND": (5330, "077f36ef320899f354a8d1322edf3ae12e3b727f4ba83171c7e64b09e5384729"),
    },
}
MAX_FILES = 4096
MAX_BYTES = 200 * 1024**2


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024**2):
            digest.update(block)
    return digest.hexdigest()


def check_local_source(source: Path, *, full: bool = False) -> dict:
    """Quick startup check, or complete original-tree check before a new copy."""
    if type(full) is not bool:
        raise ValueError("Lokale datacontrole vereist een expliciete boolean.")
    validate_ancestors(source)
    if not source.is_dir():
        raise ValueError("De volledige lokale gamegegevens ontbreken.")
    for name, (size, expected) in SOURCE_PROFILE["essential"].items():
        path = source / name
        validate_ancestors(path)
        if not path.is_file() or path.stat().st_size != size or _file_hash(path) != expected:
            raise ValueError(f"Lokale gamegegevens ontbreken of wijken af: {name}.")
    result = {"mode": "builtin-NOCD-local-files", "validation": "essential-resources",
              "essential_files_checked": len(SOURCE_PROFILE["essential"]), "disc_image_used": False}
    if not full:
        return result
    validate_tree(source)
    paths = sorted((path for path in source.rglob("*") if path.is_file()),
                   key=lambda path: path.relative_to(source).as_posix())
    if len(paths) != SOURCE_PROFILE["files"] or len(paths) > MAX_FILES:
        raise ValueError("De volledige lokale gamebestanden ontbreken of wijken af.")
    sizes = [path.stat().st_size for path in paths]
    if sum(sizes) != SOURCE_PROFILE["bytes"] or sum(sizes) > MAX_BYTES:
        raise ValueError("De lokale gamegegevens hebben een afwijkende totale grootte.")
    records = [{"path": path.relative_to(source).as_posix(), "size": size,
                "sha256": _file_hash(path)} for path, size in zip(paths, sizes)]
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    digest = hashlib.sha256(encoded).hexdigest()
    if digest != SOURCE_PROFILE["sha256"]:
        raise ValueError("De volledige lokale gamegegevens hebben een onbekende versie.")
    result.update(validation="complete-original-tree", source_files=len(records),
                  source_bytes=sum(sizes), source_tree_sha256=digest)
    return result


def launch_environment(working_directory: Path) -> dict[str, str]:
    """Child-only environment contract; never change os.environ or any drive."""
    path = PureWindowsPath(str(working_directory))
    if not path.is_absolute() or len(path.drive) != 2 or path.drive[1] != ":" or not path.drive[0].isascii() or not path.drive[0].isalpha():
        raise ValueError("Cd-loos starten vereist een gamepad met een gewone schijfletter.")
    return {"NOCD": path.drive[0].upper()}
