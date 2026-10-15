"""Check the public ZIP and checksum before publishing a game-free release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile


PREFIX = "A2-Racers-Revival/"
FORBIDDEN_SUFFIXES = {".exe", ".iso", ".cue", ".bin", ".zip"}


def check(archive_path: Path, version: str) -> dict[str, object]:
    if not archive_path.is_file():
        raise ValueError("De openbare release-ZIP ontbreekt.")
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    expected_checksum = f"{digest}  {archive_path.name}\n"
    if checksum_path.read_text(encoding="ascii") != expected_checksum:
        raise ValueError("De SHA-256-controlesom komt niet overeen met de release-ZIP.")

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read(PREFIX + "release-manifest.json"))
        if manifest.get("audience") != "launcher-public" or manifest.get("game_archive_included") is not False:
            raise ValueError("De release is geen openbare launcher zonder game.")
        release = json.loads(archive.read(PREFIX + "public-release.json"))
        packaged_version = archive.read(PREFIX + "VERSION.txt").decode("ascii").strip()
        if release.get("games_bundled") is not False or release.get("version") != version or packaged_version != version:
            raise ValueError("De ingepakte versie of gamevermelding klopt niet.")
        forbidden = []
        for name in names:
            path = PurePosixPath(name)
            parts = tuple(part.casefold() for part in path.parts[1:])
            if (not name.startswith(PREFIX) or not parts
                    or parts[0] in {"payload", "game-media"}
                    or parts[:2] == ("local", "games")
                    or path.suffix.casefold() in FORBIDDEN_SUFFIXES):
                forbidden.append(name)
        if forbidden:
            raise ValueError("De release bevat mogelijk spel- of payloadbestanden: " + ", ".join(forbidden[:5]))
    return {"version": version, "files_checked": len(names), "sha256": digest, "games_bundled": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes-template", type=Path)
    parser.add_argument("--notes-output", type=Path)
    args = parser.parse_args()
    result = check(args.archive, args.version)
    if (args.notes_template is None) != (args.notes_output is None):
        raise ValueError("Geef zowel --notes-template als --notes-output op.")
    if args.notes_template is not None:
        notes = args.notes_template.read_text(encoding="utf-8").rstrip()
        if args.version not in notes:
            raise ValueError("De releasetekst noemt een andere versie.")
        args.notes_output.write_text(
            notes + f"\n\n**SHA-256 van de ZIP:**\n\n```text\n{result['sha256']}\n```\n",
            encoding="utf-8",
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
