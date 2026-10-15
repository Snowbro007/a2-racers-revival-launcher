"""Read-only preflight for the supplied A2 Racer II v1.01 playtests.

Only known local paths are read. This module never prepares a copy, mounts a
disc, inspects live processes or executes game code. A successful preflight
means that a start trial can be attempted, not that the game is playable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import trial_manifest

GAME = "a2racer2"
EXPECTED_SOURCE_FILES = 1259
MAX_SOURCE_FILES = 5000
MAX_SOURCE_ENTRIES = 10000
SOURCE_PINS = {
    "DATA/A2_II.EXE": {"size": 28672, "sha256": "42348e50ad5e5551fc09477a26dc0651ff7f27869f38f151de741d1f583a780c"},
    "DATA/MENU.DAT": {"size": 253440, "sha256": "ca55597bf957b17e893c1a887b8965e94c62ab59298709c66c26233369fdbe83"},
    "DATA/SPEL.DAT": {"size": 669696, "sha256": "551484bcf472407fd67ee8933c6f26b5a937d428e9e0cdf0cd72988dd003c2f9"},
    "DATA/RASER.INI": {"size": 7466, "sha256": "d0928a9785dde4ea4d2fa2da3c90effa0020aab10d769277ac346fe803dc689f"},
    "DATA/INTRO.SMK": {"size": 16078036, "sha256": "8bec0a45c0b740f4440d89762832a25db5ffe6def6edceeffee0b49180c53818"},
}
ISO_PIN = {"size": 459978752, "sha256": "8a0755bdbde7b526763157e8034403f9d2a732d36db1fad93c2fdc9eb67f1d7d"}
GRAPHICS_WRAPPERS = ("native", "dgvoodoo-windowed")


def _fingerprint(path: Path, expected: dict) -> dict:
    """Stream one fixed-size file, rejecting links and changes during the read."""
    result = {"path": str(path), "expected_size": expected["size"],
              "expected_sha256": expected["sha256"], "verified": False}
    try:
        trial_manifest.validate_ancestors(path)
        if not path.is_file():
            raise ValueError("Bestand ontbreekt of is geen gewone file.")
        before = path.stat()
        result["size"] = before.st_size
        if before.st_size != expected["size"]:
            raise ValueError("Bestand heeft een onverwachte grootte.")
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            while block := handle.read(min(1024 * 1024, expected["size"] + 1 - total)):
                digest.update(block)
                total += len(block)
                if total > expected["size"]:
                    raise ValueError("Bestand veranderde tijdens de hashcontrole.")
        trial_manifest.validate_ancestors(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ino) or total != expected["size"]:
            raise ValueError("Bestand veranderde tijdens de hashcontrole.")
        result["sha256"] = digest.hexdigest()
        if result["sha256"] != expected["sha256"]:
            raise ValueError("Bestand wijkt af van de bekende bronversie.")
        result["verified"] = True
    except (OSError, ValueError) as exc:
        result["error"] = str(exc)
    return result


def _source_count(source: Path) -> int:
    # Explicit walk checks each entry before descending into it; no reparse
    # point or symlink in a source tree is allowed, including unpinned assets.
    trial_manifest.validate_ancestors(source)
    if not source.is_dir():
        raise ValueError("De lokale deel-II-bronmap ontbreekt.")
    count = 0
    entries = 0
    stack = [source]
    while stack:
        current = stack.pop()
        trial_manifest.validate_ancestors(current)
        for entry in current.iterdir():
            entries += 1
            if entries > MAX_SOURCE_ENTRIES:
                raise ValueError("De bron bevat onverwacht veel bestanden of mappen.")
            if trial_manifest._is_link(entry):
                raise ValueError("De bron bevat een link/reparse point.")
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file():
                count += 1
                if count > MAX_SOURCE_FILES:
                    raise ValueError("De bron bevat onverwacht veel bestanden.")
            else:
                raise ValueError("De bron bevat een niet-regulier bestand.")
    return count


def check_workspace(root: Path, graphics_wrapper: str = "native",
                    disable_movies: bool = False) -> dict:
    """Return the static prerequisites for one fixed II launcher trial."""
    if graphics_wrapper not in GRAPHICS_WRAPPERS or type(disable_movies) is not bool:
        raise ValueError("Onbekend deel-II-proefprofiel.")
    trial_manifest.validate_graphics_profile(GAME, graphics_wrapper, "none")
    trial_manifest.validate_disable_movies(GAME, "launcher", disable_movies)
    source = root / "local/games/a2racer2"
    image = root / "local/media/a2racer2/iso2048/disc.iso"
    ready_image = root / "local/media/a2racer2/ready/disc.iso"
    result = {
        "schema": 1, "game": GAME, "mode": "static_only", "ready_for_trial": False,
        "graphics_wrapper": graphics_wrapper, "disable_movies": disable_movies,
        "source_path": str(source), "source_files": None,
        "expected_source_files": EXPECTED_SOURCE_FILES, "source_pins": [],
        "disc": {"mount_state": "not_checked", "mount_required_before_start": True,
                 "mount_script": str(root / "tools/Mount-A2Disc.ps1"),
                 "source_image": None, "ready_image": None},
        "launch_contract": {"script": "Invoke-A2Trial.ps1", "game": GAME,
                            "stage": "launcher", "executable_relative": "DATA/A2_II.EXE",
                            "working_directory_relative": "DATA", "game_arguments": [],
                            "graphics_wrapper": graphics_wrapper, "disable_movies": disable_movies,
                            "enable_game_debug": True, "race_fps_limit": 0,
                            "display_profile": "original", "binary_fixes": [],
                            "fresh_run_name_required": True, "stop_at_end": False},
        "graphics_dependencies": [], "errors": [],
        "limitations": [
            "Vijf vaste bronbestanden worden gehasht; de overige bestanden worden alleen geteld.",
            "Geen huidige mountstatus, zichtbaar menu, bediening, geluid of speelbaarheid getest.",
            "Deel-I-patches, 20 FPS, HD, zichtafstand en focusherstel zijn niet naar deel II overgezet.",
        ],
    }
    source_tree_valid = False
    try:
        count = _source_count(source)
        result["source_files"] = count
        if count != EXPECTED_SOURCE_FILES:
            result["errors"].append("Het aantal bronbestanden wijkt af van de bekende extractie.")
        source_tree_valid = True
    except (OSError, ValueError) as exc:
        result["errors"].append(str(exc))
    if source_tree_valid:
        for name, expected in SOURCE_PINS.items():
            check = _fingerprint(source / name, expected)
            check["relative_path"] = name
            result["source_pins"].append(check)
            if not check["verified"]:
                result["errors"].append(f"Broncontrole mislukt: {name}: {check['error']}")
    source_image = _fingerprint(image, ISO_PIN)
    result["disc"]["source_image"] = source_image
    if not source_image["verified"]:
        result["errors"].append("De bekende deel-II-cd-image ontbreekt of wijkt af.")
    try:
        trial_manifest.validate_ancestors(ready_image)
        if ready_image.exists():
            ready = _fingerprint(ready_image, ISO_PIN)
            result["disc"]["ready_image"] = ready
            if not ready["verified"]:
                result["errors"].append("De bestaande ready-cd-image wijkt af; overschrijven is niet toegestaan.")
        else:
            result["disc"]["ready_image"] = {"path": str(ready_image), "exists": False,
                                                "preparation_required": True}
    except (OSError, ValueError) as exc:
        result["errors"].append(str(exc))
    if source_tree_valid:
        try:
            planned = trial_manifest.plan_graphics_wrapper(root, GAME, source, graphics_wrapper)
            # Do not return external config contents; names and hashes identify
            # the known components that would be copied by the trial runner.
            result["graphics_dependencies"] = [
                {**{key: item[key] for key in ("source_path", "relative_path", "sha256")},
                 "size": len(item["data"])}
                for item in planned
            ]
        except (OSError, ValueError) as exc:
            result["errors"].append(f"Wrappervoorbereiding geblokkeerd: {exc}")
    result["ready_for_trial"] = not result["errors"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphics-wrapper", choices=GRAPHICS_WRAPPERS, default="native")
    parser.add_argument("--disable-movies", action="store_true")
    args = parser.parse_args()
    try:
        result = check_workspace(ROOT, args.graphics_wrapper, args.disable_movies)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result["ready_for_trial"] else 1
    except (OSError, ValueError) as exc:
        print(json.dumps({"game": GAME, "mode": "static_only", "ready_for_trial": False,
                          "errors": [str(exc)]}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
