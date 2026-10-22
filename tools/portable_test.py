"""Build/check an offline personal A2-I test kit; never execute game code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.trial_manifest import validate_ancestors, validate_tree, EXPECTED_BINARIES  # noqa: E402
from tools.intro_player import file_hash, ARCHIVE_SHA256  # noqa: E402

GAME_ARCHIVE_SHA256 = "ba83625fe0db0326028118fa9640fe6e9053ffed1f2c2913ac37fdb08bc8e81c"
GAME_ARCHIVE_NAME = "A2-Racer_Win_NL.zip"
II_ARCHIVE_SHA256 = "a864442903c6e3d87bcca0e1feb9a66c9557235efb72283b9e42ea0b04ce9c6a"
MAX_GAME_ARCHIVE = 2 * 1024**3
PAYLOADS = {
    "python": ("python-3.13.16-embed-amd64.zip", "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297", "local/components/portable-runtimes/python-3.13.16-embed-amd64.zip"),
    "powershell": ("PowerShell-7.6.5-win-x64.zip", "32eb8f6cdce08f86e987d625a2733e54ac3e289ae7e1621b14c0b5bcec2434ea", "local/components/portable-runtimes/PowerShell-7.6.5-win-x64.zip"),
    "cnc": ("cnc-ddraw-v7.0.0.0.zip", "f9640f69c2b8c012b97720ce0a9aac483989563908fc19446b9d1ba16e7239d6", "local/components/cnc-ddraw/v7.0.0.0/cnc-ddraw.zip"),
    "dgvoodoo": ("dgVoodoo2_87_5.zip", "5ffde6927f7355ca3fdd5d785b581256a8e6539fa13e395a891ade6ba1040850", "local/components/dgvoodoo/v2.87.5/dgVoodoo2_87_5.zip"),
    "ffmpeg": ("ffmpeg-9.0.2-essentials_build.zip", ARCHIVE_SHA256, "local/components/ffmpeg/9.0.2/ffmpeg-9.0.2-essentials_build.zip"),
}
APP_FILES = [f"a2revival/{name}.py" for name in ("__init__", "__main__", "cli", "diagnosis", "executables", "inventory")] + [
    "tools/extract_disc.py", "tools/export_iso.py", "tools/trial_manifest.py", "tools/local_game_data.py", "tools/game_fixes.py", "tools/game_options.py", "tools/parent_wait_fix.py", "tools/render_distance_fix.py", "tools/intro_player.py", "tools/portable_test.py",
    "tools/Mount-A2Disc.ps1", "tools/Invoke-A2Trial.ps1", "tools/Invoke-A2WithIntro.ps1",
    "tools/Start-A2Portable.ps1", "tools/Run-A2Portable.ps1", "docs/portable-test.md", "docs/launcher-options.md", "Maak-snelkoppeling.ps1",
    "Launcher.cmd", "tools/Show-A2Launcher.ps1", "tools/Invoke-A2LauncherSession.ps1", "tools/launcher_common.ps1",
    "tools/launcher_window.xaml", "tools/launcher_art/cover-inspired-highway-v1.png", "tools/launcher_model.py", "tools/Watch-A2Focus.ps1", "docs/launcher.md", "docs/render-distance.md",
    "tools/ii_frontend_launcher.py", "tools/ii_frontend_state.py", "tools/Invoke-IIFrontend.ps1",
    "tools/ii_frontend.ps1", "tools/ii_frontend.xaml", "tools/ii_owned_session.ps1",
    "tools/process_memory.py", "tools/visibility_monitor.py",
    "tools/Watch-A2Visibility.ps1",
    "tools/race_focus_fix.py",
    "docs/focus-recovery.md", "docs/cd-local-data.md",
    "docs/modernization-plan.md",
    "tools/devtools_report.py", "tools/Show-A2Devtools.ps1", "tools/devtools_window.xaml", "docs/devtools-plan.md",
    "tools/widescreen_fix.py", "tools/object_distance_fix.py", "tools/resource_archive.py", "tools/pcx_codec.py", "tools/sprite_archive.py",
    "tools/expanded_texture_specs.py", "tools/meter_texture_specs.py", "tools/vehicle_mesh.py",
    "tools/hud_hd_fix.py", "tools/hud_hd_pe.py", "tools/hud_hd_native.py", "tools/hud_hd_assets.py", "tools/hud_hd_status.py",
    "tools/hud_cockpit_fix.py", "tools/hud_cockpit_assets.py",
    "tools/hud_refined_cockpit_fix.py", "tools/hud_refined_cockpit_assets.py", "tools/hud_fine_assets.py",
    "tools/menu_presentation.py", "tools/menu_art_fix.py", "tools/menu_input_fix.py", "tools/menu_display_check.py",
    "tools/Show-A2FanNotice.ps1", "tools/fan_notice_window.xaml", "tools/fan_notice_common.ps1",
    "docs/fan-disclaimer-rights.md",
    "tools/playtest_catalog.py", "tools/Start-A2Playtest.ps1", "tools/Make-A2PlaytestShortcuts.ps1",
    "tools/ii_playtest_check.py", "docs/playtest-batch.md", "docs/widescreen-research.md",
    "docs/texture-playtests.md", "docs/texture-hd-next.md", "docs/a2-racer-ii-playtests.md",
]
MAX_ZIP = 180 * 1024**2
DEFAULT_SETTINGS = {"race_fps_limit": 20, "map_mode": "original"}
COMMANDS = {"Start-A2.cmd": "", "Controleren.cmd": "-CheckOnly", "Diagnose-A2.cmd": "-Diagnostic",
            "Start-A2-20FPS.cmd": "-RaceFPSLimit 20",
            "Minimap-test.cmd": "-MapMode gdi", "Minimap-test-kleuren.cmd": "-MapMode no-dither",
            "Start-A2-30FPS.cmd": "-RaceFPSLimit 30",
            "Beeld-test-4-3.cmd": "-DisplayProfile borderless-4-3 -RaceFPSLimit 20",
            "Beeld-test-1280x960.cmd": "-DisplayProfile hd-1280x960 -RaceFPSLimit 20",
            "Beeld-test-1920x1440.cmd": "-DisplayProfile hd-1920x1440 -RaceFPSLimit 20"}


def load_settings(root: Path) -> dict:
    path = root / "A2-Instellingen.json"
    validate_ancestors(path)
    if not path.exists():
        return DEFAULT_SETTINGS.copy()
    if not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("A2-Instellingen.json is geen klein instellingenbestand.")
    settings = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(settings, dict) or set(settings) != set(DEFAULT_SETTINGS):
        raise ValueError("Instellingen moeten race_fps_limit en map_mode bevatten.")
    from tools.trial_manifest import validate_race_options
    validate_race_options("a2racer1", "hybrid-dgvoodoo", settings["race_fps_limit"], True, settings["map_mode"])
    return settings


def stream_hash(handle) -> str:
    digest = hashlib.sha256()
    while data := handle.read(1024**2):
        digest.update(data)
    return digest.hexdigest()


def checked_zip(path: Path, expected: str) -> zipfile.ZipFile:
    if file_hash(path, MAX_ZIP) != expected:
        raise ValueError(f"Componenthash wijkt af: {path.name}")
    archive = zipfile.ZipFile(path)
    try:
        entries = archive.infolist()
        if len(entries) > 5000 or sum(e.file_size for e in entries) > 600 * 1024**2:
            raise ValueError("Archief overschrijdt de extractielimiet.")
        names = set()
        for entry in entries:
            p = PurePosixPath(entry.filename)
            key = entry.filename.rstrip("/").casefold()
            if (p.is_absolute() or ".." in p.parts or "\\" in entry.orig_filename
                    or any(":" in part for part in p.parts) or key in names
                    or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError("Onveilige of dubbele archiefnaam.")
            names.add(key)
        return archive
    except Exception:
        archive.close()
        raise


def extract_verified(archive_path: Path, expected: str, destination: Path) -> None:
    """Publish only a complete runtime; never repair unknown existing content."""
    validate_ancestors(destination)
    # Provider module paths can exceed MAX_PATH even in a normal kit folder.
    # This affects only runtime extraction/checks, not game/process paths.
    if os.name == "nt":
        absolute = str(destination.absolute())
        if not absolute.startswith("\\\\?\\"):
            absolute = "\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\") else "\\\\?\\" + absolute
        destination = Path(absolute)
    with checked_zip(archive_path, expected) as archive:
        def verify(folder: Path) -> None:
            validate_tree(folder)
            expected_names = {i.filename for i in archive.infolist() if not i.is_dir()}
            actual_names = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
            if actual_names != expected_names:
                raise ValueError("Bestaande runtime bevat afwijkende bestanden. "
                                 "De map blijft behouden; controleer de beveiligingsmelding of gebruik een aparte verse launchermap.")
            for entry in archive.infolist():
                if not entry.is_dir():
                    with archive.open(entry) as handle:
                        digest = stream_hash(handle)
                    if file_hash(folder / entry.filename, 600 * 1024**2) != digest:
                        raise ValueError("Bestaande runtime is gewijzigd.")

        if destination.exists():
            verify(destination)
            return
        parent = destination.parent
        validate_ancestors(parent)
        parent.mkdir(parents=True, exist_ok=True)
        # A unique sibling keeps an interrupted extraction out of the live path.
        # A hard power loss can leave this private staging folder behind, but a
        # subsequent start uses a new one and never trusts that incomplete copy.
        stage = parent / ("." + destination.name + "-extract-" + uuid.uuid4().hex)
        stage.mkdir(exist_ok=False)
        stage_parent = parent.resolve()
        try:
            for entry in archive.infolist():
                target = stage.joinpath(*PurePosixPath(entry.filename).parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open("xb") as out:
                        shutil.copyfileobj(source, out, 1024**2)
            verify(stage)
            validate_ancestors(destination)
            if destination.exists():
                # Another launcher may have completed the same pinned runtime.
                # Inspect it; never overwrite or remove its directory.
                verify(destination)
                return
            # Windows can briefly deny a directory rename while another reader
            # holds a handle. Retry only its access/sharing errors, with at most
            # 750 ms of backoff. Recheck both trees; never repair or overwrite an unknown
            # destination, and never treat this as evidence about an antivirus.
            for attempt, delay in enumerate((0, 0.05, 0.1, 0.2, 0.4)):
                if delay:
                    time.sleep(delay)
                    verify(stage)
                    validate_ancestors(destination)
                    if destination.exists():
                        verify(destination)
                        return
                try:
                    stage.rename(destination)
                    break
                except OSError as error:
                    if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 4:
                        raise
        finally:
            if stage.exists():
                # Only remove the exclusive temporary directory created above.
                # Resolve and reject links before any recursive cleanup.
                if stage.resolve().parent != stage_parent or not stage.name.startswith("." + destination.name + "-extract-"):
                    raise ValueError("Onverwachte runtime-stagingmap; opruimen geweigerd.")
                validate_tree(stage)
                shutil.rmtree(stage)


def payload(root: Path, kind: str) -> Path:
    name, pin, _ = PAYLOADS[kind]
    path = root / "payload" / name
    if file_hash(path, MAX_ZIP) != pin:
        raise ValueError(f"Ontbrekende of gewijzigde component: {kind}")
    return path


def save_exact(path: Path, data: bytes) -> None:
    validate_ancestors(path)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Bestaand componentbestand wijkt af: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def setup_components(root: Path, *, launcher_only: bool = False, skip_media: bool = False) -> dict:
    if launcher_only:
        # This stage never inspects or imports games and cannot imply game readiness.
        archive = payload(root, "python")
        extract_verified(archive, PAYLOADS["python"][1], root / "local/portable-runtime/python")
        return {"launcher_ready": True, "components_ready": False, "game_imported": False,
                "gameplay_status": "niet gecontroleerd", "downloads": False}
    from tools import trial_manifest as tm
    for kind in PAYLOADS:
        if skip_media and kind == 'ffmpeg':
            continue
        payload(root, kind)
    extract_verified(payload(root, "powershell"), PAYLOADS["powershell"][1], root / "local/portable-runtime/powershell")
    cnc = root / "local/components/cnc-ddraw" / tm.CNC_DDRAW_VERSION / "extracted"
    with checked_zip(payload(root, "cnc"), PAYLOADS["cnc"][1]) as archive:
        save_exact(cnc / "ddraw.dll", archive.read("ddraw.dll"))
    dg = root / "local/components/dgvoodoo" / tm.DGVOODOO_VERSION
    with checked_zip(payload(root, "dgvoodoo"), PAYLOADS["dgvoodoo"][1]) as archive:
        for entry in ("MS/x86/DDraw.dll", "MS/x86/D3DImm.dll"):
            save_exact(dg / "extracted" / entry, archive.read(entry))
        config = archive.read("dgVoodoo.conf")
        for key, before, after in ((b"OutputAPI", b"bestavailable", b"d3d11_fl11_0"),
                                   (b"FullScreenMode", b"true", b"false"),
                                   (b"AppControlledScreenMode", b"true", b"false")):
            pattern = rb"(?m)^(" + key + rb"[ \t]*=[ \t]*)" + before + rb"(?=[\r\n])"
            config, count = re.subn(pattern, lambda m: m[1] + after, config)
            if count != 1:
                raise ValueError("Onverwachte dgVoodoo-config.")
        if hashlib.sha256(config).hexdigest() != tm.DGVOODOO_CONFIG_SOURCE["sha256"]:
            raise ValueError("dgVoodoo-profiel wijkt af van de geteste configuratie.")
        save_exact(dg / tm.DGVOODOO_CONFIG_SOURCE["source"], config)
    if not skip_media:
        ff = root / "local/components/ffmpeg/9.0.2/ffmpeg-9.0.2-essentials_build.zip"
        validate_ancestors(ff)
        if ff.exists():
            if file_hash(ff, MAX_ZIP) != ARCHIVE_SHA256:
                raise ValueError("Bestaand FFmpeg-archief wijkt af.")
        else:
            ff.parent.mkdir(parents=True, exist_ok=True)
            with payload(root, "ffmpeg").open("rb") as source, ff.open("xb") as target:
                shutil.copyfileobj(source, target, 1024**2)
    source = root / "local/games/a2racer1"
    if source.exists():
        validate_tree(source)
        for relative, pin in EXPECTED_BINARIES["a2racer1"].items():
            if file_hash(source / relative, 16 * 1024**2) != pin:
                raise ValueError("Onbekende gameversie.")
    else:
        source = root / "local/component-check-empty-source"
        source.mkdir(parents=True, exist_ok=True)
        if any(source.iterdir()):
            raise ValueError("Componentcontrolemap is niet leeg.")
    tm.plan_graphics_wrapper(root, "a2racer1", source, "hybrid-dgvoodoo")
    return {"components_ready": True, "game_imported": (root / "local/games/a2racer1").is_dir(),
            "gameplay_status": "onbekend", "downloads": False}


def import_game(root: Path, archive: Path, game: str = 'a2racer1') -> dict:
    from tools.extract_disc import extract_archive
    pins = {'a2racer1': GAME_ARCHIVE_SHA256, 'a2racer2': II_ARCHIVE_SHA256}
    if game not in pins:
        raise ValueError('Deze game kan nog niet uit een archief worden geïmporteerd.')
    pin = pins[game]
    archive_hash = file_hash(archive, 2 * 1024**3)
    image = None
    if archive_hash != pin:
        if game != 'a2racer2':
            raise ValueError('Dit gamearchief wordt niet herkend; kies de ondersteunde originele Nederlandse versie.')
        from tools.ii_archive_import import recognize_archive
        image = recognize_archive(archive)
    if image is None:
        extract_archive(archive, root / 'local', game)
    else:
        # Bind extraction to the same verified member and bytes; rechecking
        # before parsing/publishing prevents a changed ZIP replacing the image.
        contract = {key: image[key] for key in ('member', 'size', 'sha256')}
        extract_archive(archive, root / 'local', game, expected_image=contract)
    if game == 'a2racer1':
        from tools.local_game_data import check_local_source
        local_data = check_local_source(root / 'local/games' / game, full=True)
    else:
        from tools.ii_portable_prepare import inspect_source
        local_data = inspect_source(root / 'local/games' / game)
    if file_hash(archive, 2 * 1024**3) != archive_hash:
        raise ValueError("Bronarchief veranderde tijdens import.")
    return {"game": game, "game_imported": True, "game_started": False,
            "disc_image_required": False, "local_game_data": local_data, "source_unchanged": True,
            "archive_recognition": 'verified-disc-image' if image else 'known-archive',
            "disc_image_sha256": image['sha256'] if image else None}


def build(root: Path, destination: Path, game_archive: Path | None = None) -> dict:
    validate_ancestors(destination)
    if destination.exists():
        raise ValueError("Testpakket bestaat al; overschrijven geweigerd.")
    if game_archive is not None and file_hash(game_archive, MAX_GAME_ARCHIVE) != GAME_ARCHIVE_SHA256:
        raise ValueError("Persoonlijke game-ZIP heeft een onbekende checksum; niets verpakt.")
    inputs = [(name, root / name) for name in APP_FILES]
    inputs += [("payload/" + name, root / source) for name, _, source in PAYLOADS.values()]
    inputs += [("NOTICES/cnc-ddraw-MIT.txt", root / "local/components/cnc-ddraw/v7.0.0.0/LICENSE-v7.0.0.0.txt"),
               ("NOTICES/dgVoodoo-readme.html", root / "local/components/dgvoodoo/v2.87.5/author-readme-general.html")]
    if game_archive is not None:
        inputs.append((GAME_ARCHIVE_NAME, game_archive))
    for kind, (_, pin, source) in PAYLOADS.items():
        if file_hash(root / source, MAX_ZIP) != pin:
            raise ValueError(f"Onbekende pakketcomponent: {kind}")
    manifest = []
    for name, path in inputs:
        validate_ancestors(path)
        manifest.append({"path": name, "size": path.stat().st_size, "sha256": file_hash(path, MAX_GAME_ARCHIVE if name == GAME_ARCHIVE_NAME else MAX_ZIP)})
    prefix = "A2-Revival-Test-I/"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, path in inputs:
            # Provider ZIPs remain exact bytes; double compression adds no value.
            archive.write(path, prefix + name, compress_type=zipfile.ZIP_STORED if name.startswith("payload/") or name == GAME_ARCHIVE_NAME else zipfile.ZIP_DEFLATED)
        for name, argument in COMMANDS.items():
            text = '@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\\Start-A2Portable.ps1" ' + argument + '\r\npause\r\n'
            archive.writestr(prefix + name, text.encode("ascii"))
        shortcut_button = '@echo off\r\nsetlocal DisableDelayedExpansion\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Maak-snelkoppeling.ps1" -Launcher\r\npause\r\n'
        archive.writestr(prefix + "Maak-snelkoppeling.cmd", shortcut_button.encode("ascii"))
        archive.writestr(prefix + "A2-Instellingen.json", json.dumps(DEFAULT_SETTINGS, indent=2).encode("ascii") + b"\n")
        archive.writestr(prefix + "START-HIER.txt", (root / "docs/portable-test.md").read_bytes())
        archive.writestr(prefix + "package-manifest.json", json.dumps({"purpose": "Personal A2 Racer I test on another PC", "game_archive_included": game_archive is not None, "files": manifest}, indent=2).encode("utf-8"))
    audit_kit(destination, manifest)
    if game_archive is not None and file_hash(game_archive, MAX_GAME_ARCHIVE) != GAME_ARCHIVE_SHA256:
        raise ValueError("Bronarchief veranderde tijdens verpakken.")
    return {"path": str(destination), "size": destination.stat().st_size,
            "sha256": file_hash(destination, 600 * 1024**2), "game_assets_included": game_archive is not None}


def audit_kit(path: Path, manifest: list[dict] | None = None) -> int:
    prefix = "A2-Revival-Test-I/"
    with zipfile.ZipFile(path) as archive:
        stored = json.loads(archive.read(prefix + "package-manifest.json"))
        bundled_game = stored.get("game_archive_included", False)
        if not isinstance(bundled_game, bool):
            raise ValueError("Gamearchiefkeuze in manifest is ongeldig.")
        records = stored["files"]
        if manifest is not None and manifest != records:
            raise ValueError("Pakketmanifest wijkt af.")
        allowed = set(APP_FILES) | {"payload/" + item[0] for item in PAYLOADS.values()} | {"NOTICES/cnc-ddraw-MIT.txt", "NOTICES/dgVoodoo-readme.html"}
        if bundled_game:
            allowed.add(GAME_ARCHIVE_NAME)
        if {r["path"] for r in records} != allowed or len(records) != len(allowed):
            raise ValueError("Onverwachte bestanden in pakketmanifest.")
        pins = {"payload/" + name: pin for name, pin, _ in PAYLOADS.values()}
        if bundled_game:
            pins[GAME_ARCHIVE_NAME] = GAME_ARCHIVE_SHA256
        if any(r["path"] in pins and r["sha256"] != pins[r["path"]] for r in records):
            raise ValueError("Verpakt providerarchief heeft een onbekende checksum.")
        extras = set(COMMANDS) | {"Maak-snelkoppeling.cmd", "START-HIER.txt", "package-manifest.json"}
        if prefix + "A2-Instellingen.json" in archive.namelist():
            extras.add("A2-Instellingen.json")
            if json.loads(archive.read(prefix + "A2-Instellingen.json")) != DEFAULT_SETTINGS:
                raise ValueError("Onverwachte verpakte standaardinstellingen.")
        names = archive.namelist()
        if set(names) != {prefix + n for n in allowed | extras} or len(names) != len(allowed | extras):
            raise ValueError("Onverwachte of dubbele pakketbestanden; game-assets worden geweigerd.")
        for r in records:
            with archive.open(prefix + r["path"]) as handle:
                digest = stream_hash(handle)
            if digest != r["sha256"] or archive.getinfo(prefix + r["path"]).file_size != r["size"]:
                raise ValueError("Verpakt bestand wijkt af van manifest.")
    return len(names)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "import", "build", "audit", "settings"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-game-archive", type=Path,
                        help="Alleen build: voeg de bekende originele ZIP toe aan een persoonlijk pakket.")
    parser.add_argument("--launcher-only", action="store_true",
                        help="Alleen setup: bereid uitsluitend de Python-runtime voor de launcher voor.")
    parser.add_argument("--skip-media", action="store_true",
                        help="Alleen setup: controleer spelonderdelen zonder de introspeler.")
    args = parser.parse_args()
    try:
        if args.include_game_archive is not None and args.action != "build":
            raise ValueError("--include-game-archive is uitsluitend voor build.")
        if args.launcher_only and args.action != "setup":
            raise ValueError("--launcher-only is uitsluitend voor setup.")
        if args.skip_media and args.action != "setup":
            raise ValueError("--skip-media is uitsluitend voor setup.")
        if args.action == "settings":
            result = load_settings(ROOT)
        elif args.action == "setup":
            result = setup_components(ROOT, launcher_only=args.launcher_only, skip_media=args.skip_media)
        elif args.action == "import":
            if not args.archive:
                raise ValueError("Geef --archive.")
            result = import_game(ROOT, args.archive)
        elif args.action == "build":
            if not args.output:
                raise ValueError("Geef --output.")
            result = build(ROOT, args.output, args.include_game_archive)
        else:
            if not args.archive:
                raise ValueError("Geef --archive.")
            result = {"files_checked": audit_kit(args.archive)}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as error:
        parser.exit(1, f"Portable test: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
