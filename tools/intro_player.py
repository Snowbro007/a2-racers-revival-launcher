"""Prepare a local FFplay/Smacker trial; never execute a player or game."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import zipfile

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))
from tools.trial_manifest import validate_ancestors, validate_slug  # noqa: E402

FFMPEG_VERSION = "9.0.2"
ARCHIVE_SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"
INTRO_SIZE = 15760752
INTRO_SHA256 = "39b86263e0e544c9a50bb9e488d9d5829301be53bba3765797394ecc4096bb62"
MAX_ARCHIVE_BYTES = 180 * 1024 * 1024
MAX_PLAYER_BYTES = 200 * 1024 * 1024


def file_hash(path: Path, maximum: int) -> str:
    validate_ancestors(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError(f"Bestand ontbreekt of overschrijdt de limiet: {path.name}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while data := handle.read(1024 * 1024):
            size += len(data)
            if size > maximum:
                raise ValueError("Bestand groeide voorbij de leeslimiet.")
            digest.update(data)
    return digest.hexdigest()


def paths_for(workspace: Path, run_name: str) -> dict[str, Path]:
    validate_slug(run_name)
    validate_slug(run_name + "-intro")
    paths = {
        "source": workspace / "local/games/a2racer1/A2INTRO.SMK",
        "archive": workspace / f"local/components/ffmpeg/{FFMPEG_VERSION}/ffmpeg-{FFMPEG_VERSION}-essentials_build.zip",
        "trial": workspace / "local/experiments/a2racer1" / (run_name + "-intro"),
        "report": workspace / "reports/runtime/a2racer1" / (run_name + "-intro"),
        "game_trial": workspace / "local/experiments/a2racer1" / run_name / "game",
        "game_report": workspace / "reports/runtime/a2racer1" / run_name,
    }
    for path in paths.values():
        validate_ancestors(path)
    return paths


def check_source(paths: dict[str, Path]) -> None:
    if paths["source"].stat().st_size != INTRO_SIZE or file_hash(paths["source"], INTRO_SIZE) != INTRO_SHA256:
        raise ValueError("Onbekende of gewijzigde originele intro.")
    if file_hash(paths["archive"], MAX_ARCHIVE_BYTES) != ARCHIVE_SHA256:
        raise ValueError("FFmpeg-archief komt niet overeen met de gepubliceerde checksum.")


def player_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    candidates = [item for item in archive.infolist()
                  if PurePosixPath(item.filename).name == "ffplay.exe"]
    if len(candidates) != 1:
        raise ValueError("Archief bevat niet precies één FFplay-binary.")
    member = candidates[0]
    path = PurePosixPath(member.filename)
    if (path.is_absolute() or ".." in path.parts or "\\" in member.filename
            or any(":" in part for part in path.parts)
            or stat.S_ISLNK(member.external_attr >> 16)
            or member.flag_bits & 1 or not 0 < member.file_size <= MAX_PLAYER_BYTES):
        raise ValueError("FFplay-archiefmember is onveilig of onbegrensd.")
    return member


def prepare(workspace: Path, run_name: str) -> dict:
    paths = paths_for(workspace, run_name)
    if any(paths[key].exists() for key in ("trial", "report", "game_trial", "game_report")):
        raise ValueError("Proefnaam bestaat al; er wordt niets overschreven.")
    check_source(paths)
    with zipfile.ZipFile(paths["archive"]) as archive:
        member = player_member(archive)
        # Only this one verified member is copied. Archive names never choose
        # an output path; assets and binaries remain in ignored local folders.
        paths["trial"].mkdir(parents=True, exist_ok=False)
        player = paths["trial"] / "ffplay.exe"
        with archive.open(member) as source, player.open("xb") as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
        if player.stat().st_size != member.file_size:
            raise ValueError("FFplay-kopie heeft een afwijkende grootte.")
    video = paths["trial"] / "A2INTRO.SMK"
    with paths["source"].open("rb") as source, video.open("xb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    check_source(paths)
    if file_hash(video, INTRO_SIZE) != INTRO_SHA256:
        raise ValueError("Intro-kopie heeft een afwijkende hash.")
    result = {
        "run_name": run_name, "game": "a2racer1", "player_version": FFMPEG_VERSION,
        "report_path": str(paths["report"]), "trial_path": str(paths["trial"]),
        "player_path": str(player), "player_size": player.stat().st_size,
        "player_sha256": file_hash(player, MAX_PLAYER_BYTES),
        "source_archive_sha256": ARCHIVE_SHA256,
        "video_path": str(video), "video_sha256": INTRO_SHA256,
        "environment": {"SDL_RENDER_DRIVER": "software"},
        "arguments": ["-autoexit", "-exitonkeydown", "-window_title", "Project A2 Revival - originele intro",
                      "-x", "640", "-y", "400", "-nostats", "-loglevel", "info", "-i", str(video)],
        "note": "Originele Smacker-film wordt rechtstreeks afgespeeld; geen conversie of gamepatch.",
    }
    paths["report"].mkdir(parents=True, exist_ok=False)
    (paths["report"] / "prepared.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def finish(workspace: Path, run_name: str) -> dict:
    paths = paths_for(workspace, run_name)
    prepared_path = paths["report"] / "prepared.json"
    validate_ancestors(prepared_path)
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    return {
        "source_video_unchanged": file_hash(paths["source"], INTRO_SIZE) == INTRO_SHA256,
        "trial_video_unchanged": file_hash(paths["trial"] / "A2INTRO.SMK", INTRO_SIZE) == INTRO_SHA256,
        "player_unchanged": file_hash(paths["trial"] / "ffplay.exe", MAX_PLAYER_BYTES) == prepared["player_sha256"],
        "source_archive_unchanged": file_hash(paths["archive"], MAX_ARCHIVE_BYTES) == ARCHIVE_SHA256,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "finish"))
    parser.add_argument("--run-name", required=True)
    args = parser.parse_args()
    try:
        result = prepare(WORKSPACE, args.run_name) if args.action == "prepare" else finish(WORKSPACE, args.run_name)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Introvoorbereiding mislukt: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
