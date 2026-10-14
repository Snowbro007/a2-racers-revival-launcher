"""Static preparation and integrity checks for explicit Windows runtime trials.

This helper never starts game executables. Runtime execution is owned by the
PowerShell runner; original game trees remain read-only input.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))
from a2revival.inventory import scan_directory, write_json  # noqa: E402
from tools.render_distance_fix import (  # noqa: E402
    EXPECTED_PATCHED_SHA256_BY_PROFILE as RENDER_DISTANCE_RACE_HASHES,
    PROFILES as RENDER_DISTANCE_PROFILES,
)
from tools.race_focus_fix import (  # noqa: E402
    EXPECTED_PATCHED_SHA256_BY_PROFILE as FOCUS_RECOVERY_RACE_HASHES,
)
from tools.widescreen_fix import (  # noqa: E402
    PROFILES as CAMERA_PROFILES,
    EXPECTED_CAMERA_SHA256_BY_PROFILE as CAMERA_RACE_HASHES,
)
from tools.object_distance_fix import (  # noqa: E402
    PROFILES as OBJECT_DISTANCE_PROFILES,
    ALLOWED_PATCHED_SHA256 as OBJECT_DISTANCE_RACE_HASHES,
)

EXPECTED_BINARIES = {
    "a2racer1": {
        "A2.EXE": "bb2ed6f29964628771e48707bf8e938c2d2be3bb19d0745bd3e3f5734cec8f13",
        "A2MOVIE.DAT": "88b2f6f74d14dd883e96d2d78f190834ebce2cbce07a3824881e52d1c66fae4a",
        "A2MENU.DAT": "45b883ec76872622241beb75afb3966723d9bee806d76741c29c6642df6ff6e6",
        "A2SPEL.DAT": "069d39e815fc631ef433550459e8105042cf740dfc311e4f9285d4cca148e726",
    },
    "a2racer2": {
        "DATA/A2_II.EXE": "42348e50ad5e5551fc09477a26dc0651ff7f27869f38f151de741d1f583a780c",
        "DATA/MENU.DAT": "ca55597bf957b17e893c1a887b8965e94c62ab59298709c66c26233369fdbe83",
        "DATA/SPEL.DAT": "551484bcf472407fd67ee8933c6f26b5a937d428e9e0cdf0cd72988dd003c2f9",
    },
}

# Fixed author release, verified against the GitHub release asset digest.
# Components remain local input; no download or execution occurs in this helper.
DXWRAPPER_VERSION = "v1.8.8600.25"
DXWRAPPER_COMPONENTS = {
    "ddraw.dll": {"source": "Stub/ddraw.dll", "size": 485888,
                  "sha256": "7c843006f81983617a37f57d7fb615d23bda99860b71ab745f2b0cea6ab00474"},
    "dxwrapper.dll": {"source": "dxwrapper.dll", "size": 8033280,
                      "sha256": "ec42e51cbb4408518d6348706557b18ef50a87485c8bfa1839c895123fa3295f"},
}
DXWRAPPER_CONFIG = (b"[General]\r\nDisableLogging=0\r\n"
                    b"[Plugins]\r\nLoadPlugins=0\r\n"
                    b"[Compatibility]\r\nDd7to9=1\r\n"
                    b"[d3d9]\r\nEnableWindowMode=1\r\nWindowModeBorder=1\r\n")
# Official v7.0 asset verified against the published, pinned Winetricks checksum.
CNC_DDRAW_VERSION = "v7.0.0.0"
CNC_DDRAW_COMPONENTS = {
    "ddraw.dll": {"source": "ddraw.dll", "size": 396288,
                  "sha256": "c7b25b41c8be1e8c5c46fdf79dd5a06a455cc95bf0d6625436c8170b9bb65133"},
}
CNC_DDRAW_CONFIG = (b"[ddraw]\nwindowed=true\nfullscreen=false\n"
                    b"renderer=gdi\nborder=true\nsavesettings=0\n")
# Fixed author release ZIP matched the GitHub API digest before extraction.
DGVOODOO_VERSION = "v2.87.5"
DGVOODOO_COMPONENTS = {
    "DDraw.dll": {"source": "MS/x86/DDraw.dll", "size": 255488,
                  "sha256": "612a24408a090a3c6f3886557fa18034ee742e94ad0a40ebdf854d2816176c2e"},
    "D3DImm.dll": {"source": "MS/x86/D3DImm.dll", "size": 208384,
                   "sha256": "93c534f2d17419ea78f15551f7e0aac78b3c503733a840914fa063708a5afe8e"},
}
DGVOODOO_CONFIG_SOURCE = {
    "source": "candidate-d3d11-windowed.conf", "size": 21965,
    "sha256": "38f1803e2c954a69873e06c11133f340cc74c818bc133125dfb565bd5c243b7f",
}
MAX_COMPONENT_BYTES = 16 * 1024 * 1024
HD_DISPLAY_RESOLUTIONS = {
    "hd-1280x960": b"1280x960",
    "hd-1280x960-fake": b"1280x960",
    "hd-1920x1440": b"1920x1440",
    "hd-1440x1080": b"h:1440, v:1080",
    "hd-2880x2160": b"h:2880, v:2160",
    "hd-1920x1080-camera": b"h:1920, v:1080",
    "hd-3840x2160-camera": b"h:3840, v:2160",
}
WIDE_DISPLAY_PROFILES = ("hd-1920x1080-camera", "hd-3840x2160-camera")
HD_DISPLAY_PROFILES = tuple(HD_DISPLAY_RESOLUTIONS)
DISPLAY_PROFILES = ("original", "borderless-4-3", *HD_DISPLAY_PROFILES)
NATIVE_OPTIONS_SIZE = 20  # optie.cpp reads/writes 0x14 bytes in this A2-I version.
NATIVE_OPTIONS_MENU_HASHES = {
    EXPECTED_BINARIES["a2racer1"]["A2MENU.DAT"],
    "27a87ce4dd5f16683f4726ec0e38f31ba6a179060be481f359663571d710a372",
}


def validate_slug(run_name: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", run_name):
        raise ValueError("Proefnaam: 1-48 kleine letters/cijfers/koppeltekens; begin met letter of cijfer.")
    if run_name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}:
        raise ValueError("Proefnaam is een gereserveerde Windows-apparaatnaam.")


def _is_link(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def validate_ancestors(path: Path) -> None:
    for candidate in (path.absolute(), *path.absolute().parents):
        try:
            if _is_link(candidate):
                raise ValueError(f"Pad bevat een link/reparse point: {candidate}")
        except FileNotFoundError:
            continue


def validate_tree(path: Path) -> None:
    validate_ancestors(path)
    if not path.is_dir():
        raise ValueError(f"Geen bestaande echte map: {path}")
    # Do not traverse a link before checking it; Path.rglob follows no links on
    # supported Python versions, but an explicit walk makes that policy clear.
    stack = [path]
    while stack:
        current = stack.pop()
        for entry in current.iterdir():
            if _is_link(entry):
                raise ValueError(f"Bron/proef bevat een link/reparse point: {entry}")
            if entry.is_dir():
                stack.append(entry)
            elif not entry.is_file():
                raise ValueError(f"Bron/proef bevat een niet-regulier bestand: {entry}")


def paths_for(workspace: Path, game: str, run_name: str) -> tuple[Path, Path, Path]:
    validate_slug(run_name)
    if game not in EXPECTED_BINARIES:
        raise ValueError("Onbekende game.")
    source = workspace / "local" / "games" / game
    trial = workspace / "local" / "experiments" / game / run_name / "game"
    report = workspace / "reports" / "runtime" / game / run_name
    for path in (source, trial, report):
        validate_ancestors(path)
    return source, trial, report


def snapshot(game: str, source: Path, report: Path, name: str) -> dict:
    validate_tree(source)
    validate_tree(report)
    manifest = scan_directory(game, source, report)
    bad = [issue for issue in manifest["issues"] if issue["code"] != "executable_header"]
    if bad:
        raise ValueError(f"Manifest niet volledig/stabiel: {bad[0]['code']}")
    destination = report / name
    if destination.exists():
        raise ValueError(f"Manifest bestaat al: {name}")
    write_json(destination, manifest)
    return manifest


def manifest_diff(before: dict, after: dict) -> dict:
    old = {item["path"]: item for item in before["files"]}
    new = {item["path"]: item for item in after["files"]}
    changed = [name for name in old.keys() & new.keys()
               if (old[name]["sha256"], old[name]["size"]) != (new[name]["sha256"], new[name]["size"])]
    return {"added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()), "changed": sorted(changed)}


def validate_movie_mode(game: str, stage: str, movie_display_mode: str) -> None:
    if movie_display_mode not in ("original", "640x480"):
        raise ValueError("Onbekende intro-displaymodus.")
    if movie_display_mode != "original" and (game != "a2racer1" or stage not in ("intro", "launcher")):
        raise ValueError("Intro-displaymodus 640x480 is alleen onderzocht voor deel I intro/launcher.")


def validate_skip_intro(game: str, stage: str, skip_intro: bool) -> None:
    if skip_intro and (game != "a2racer1" or stage != "launcher"):
        raise ValueError("Intro overslaan vereist deel I met startfase launcher.")


def validate_graphics_profile(game: str, graphics_wrapper: str, graphics_diagnostic: str) -> None:
    if graphics_wrapper not in ("native", "dxwrapper-windowed", "cnc-ddraw-gdi", "hybrid-windowed", "hybrid-dgvoodoo", "dgvoodoo-windowed"):
        raise ValueError("Onbekende graphics-wrapper.")
    if graphics_diagnostic not in ("none", "fps", "gdi", "emulate-surface", "gdi-origin"):
        raise ValueError("Onbekende graphics-diagnostiek.")
    if graphics_diagnostic != "none" and graphics_wrapper != "dxwrapper-windowed":
        raise ValueError("Graphics-diagnostiek vereist dxwrapper-windowed.")
    if graphics_wrapper in ("hybrid-windowed", "hybrid-dgvoodoo") and game != "a2racer1":
        raise ValueError("Hybrid-wrapper is uitsluitend onderzocht voor deel I.")


def validate_disable_movies(game: str, stage: str, disable_movies: bool) -> None:
    if disable_movies and (game != "a2racer2" or stage != "launcher"):
        raise ValueError("Films uitschakelen is uitsluitend een deel-II-launcherdiagnose.")


def plan_graphics_wrapper(workspace: Path, game: str, source: Path,
                          graphics_wrapper: str, graphics_diagnostic: str = "none",
                          race_fps_limit: int = 0, hide_watermark: bool = False,
                          map_mode: str = "original", display_profile: str = "original",
                          menu_profile: str = "original", menu_render_profile: str = "original") -> list[dict]:
    """Validate every fixed dependency before creating/copying trial files."""
    validate_graphics_profile(game, graphics_wrapper, graphics_diagnostic)
    validate_race_options(game, graphics_wrapper, race_fps_limit, hide_watermark, map_mode)
    validate_display_profile(game, graphics_wrapper, display_profile)
    from tools.menu_presentation import validate_profile, cnc_menu_config, validate_render_profile
    validate_profile(game, "launcher", graphics_wrapper, menu_profile)
    validate_render_profile(menu_profile, menu_render_profile)
    if graphics_wrapper == "native":
        return []
    relative_root = Path() if game == "a2racer1" else Path("DATA")
    profiles = []
    if graphics_wrapper == "dxwrapper-windowed":
        component_root = workspace / "local/components/dxwrapper" / DXWRAPPER_VERSION / "extracted"
        components = DXWRAPPER_COMPONENTS
        config_name = "dxwrapper.ini"
        # Basic probes change one flag; gdi-origin also tests the documented
        # border/initial-position controls while using the same GDI flag.
        extra = {"none": b"", "fps": b"ShowFPSCounter=1\r\n",
                 "gdi": b"[Dd7to9]\r\nDdrawWriteToGDI=1\r\n",
                 "emulate-surface": b"[Dd7to9]\r\nDdrawEmulateSurface=1\r\n",
                 "gdi-origin": b"[Dd7to9]\r\nDdrawWriteToGDI=1\r\n"}[graphics_diagnostic]
        base = DXWRAPPER_CONFIG
        if graphics_diagnostic == "gdi-origin":
            base = base.replace(b"WindowModeBorder=1\r\n",
                                b"WindowModeBorder=0\r\nSetInitialWindowPosition=1\r\n"
                                b"InitialWindowPositionLeft=0\r\nInitialWindowPositionTop=0\r\n")
        config = base + extra
    elif graphics_wrapper == "dgvoodoo-windowed":
        component_root = workspace / "local/components/dgvoodoo" / DGVOODOO_VERSION / "extracted"
        components = DGVOODOO_COMPONENTS
        config_name = "dgVoodoo.conf"
        config = dgvoodoo_windowed_config(component_root, race_fps_limit, hide_watermark, map_mode, display_profile)
    else:
        component_root = workspace / "local/components/cnc-ddraw" / CNC_DDRAW_VERSION / "extracted"
        components = CNC_DDRAW_COMPONENTS
        config_name = "ddraw.ini"
        config = cnc_menu_config(CNC_DDRAW_CONFIG, menu_profile, menu_render_profile)
    profiles.append((component_root, components, relative_root, config_name, config, None))
    if graphics_wrapper in ("hybrid-windowed", "hybrid-dgvoodoo"):
        scoped = Path("A2SPEL.DAT.local")
        if any(item.name.casefold() == scoped.name.casefold() for item in source.iterdir()):
            raise ValueError("SPEL-localmap bestaat al in bron; overschrijven geweigerd.")
        if graphics_wrapper == "hybrid-windowed":
            profiles.append((workspace / "local/components/dxwrapper" / DXWRAPPER_VERSION / "extracted",
                             DXWRAPPER_COMPONENTS, scoped, "dxwrapper.ini", DXWRAPPER_CONFIG, scoped.as_posix()))
        else:
            component_root = workspace / "local/components/dgvoodoo" / DGVOODOO_VERSION / "extracted"
            profiles.append((component_root, DGVOODOO_COMPONENTS, scoped, "dgVoodoo.conf",
                             dgvoodoo_windowed_config(component_root, race_fps_limit, hide_watermark, map_mode, display_profile), scoped.as_posix()))
    planned = []
    for component_root, components, relative_root, config_name, config, new_directory in profiles:
        planned.extend(_plan_component_profile(component_root, components, source, relative_root,
                                               config_name, config, new_directory))
    if graphics_wrapper in ("hybrid-dgvoodoo", "dgvoodoo-windowed"):
        planned[-1]["source_path"] = str(component_root.parent / DGVOODOO_CONFIG_SOURCE["source"])
    return planned


def _read_pinned_component(path: Path, expected: dict, name: str) -> bytes:
    validate_ancestors(path)
    if not path.is_file() or not 0 < expected["size"] <= MAX_COMPONENT_BYTES:
        raise ValueError(f"Wrappercomponent ontbreekt of is onbegrensd: {name}")
    if path.stat().st_size != expected["size"]:
        raise ValueError(f"Onbekende wrappercomponent-grootte: {name}")
    with path.open("rb") as handle:
        data = handle.read(expected["size"] + 1)
    if len(data) != expected["size"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
        raise ValueError(f"Onbekende wrappercomponent-hash: {name}")
    return data


def validate_race_options(game: str, graphics_wrapper: str, race_fps_limit: int,
                          hide_watermark: bool, map_mode: str) -> None:
    if isinstance(race_fps_limit, bool) or not isinstance(race_fps_limit, int) or not 0 <= race_fps_limit <= 120:
        raise ValueError("Race-FPS moet een geheel getal van 0 t/m 120 zijn.")
    if not isinstance(hide_watermark, bool) or map_mode not in ("original", "gdi", "svga", "no-dither"):
        raise ValueError("Ongeldige raceweergaveoptie.")
    if (race_fps_limit or hide_watermark or map_mode != "original") and (
            game != "a2racer1" or graphics_wrapper not in ("hybrid-dgvoodoo", "dgvoodoo-windowed")):
        raise ValueError("Raceweergaveopties vereisen het bekende deel-I-dgVoodoo-profiel.")


def validate_display_profile(game: str, graphics_wrapper: str, display_profile: str) -> None:
    if display_profile not in DISPLAY_PROFILES:
        raise ValueError("Onbekend beeldprofiel.")
    if display_profile != "original" and (
            game != "a2racer1" or graphics_wrapper not in ("hybrid-dgvoodoo", "dgvoodoo-windowed")):
        raise ValueError("Beeldproeven vereisen het bekende deel-I-dgVoodoo-profiel.")


def dgvoodoo_windowed_config(component_root: Path, race_fps_limit: int = 0,
                            hide_watermark: bool = False, map_mode: str = "original",
                            display_profile: str = "original") -> bytes:
    """Derive a race config from locally verified author input and explicit probes.

    The complete external config remains ignored input, never embedded in code.
    """
    config = _read_pinned_component(component_root.parent / DGVOODOO_CONFIG_SOURCE["source"],
                                   DGVOODOO_CONFIG_SOURCE, "dgVoodoo.conf")
    replacements = []
    if race_fps_limit:
        replacements.append((b"GeneralExt", b"FPSLimit", b"0", str(race_fps_limit).encode("ascii")))
    if hide_watermark:
        replacements.append((b"DirectX", b"dgVoodooWatermark", b"true", b"false"))
    if map_mode == "gdi":
        replacements.append((b"GeneralExt", b"SystemHookFlags", b"", b"gdi"))
    elif map_mode == "svga":
        replacements.append((b"DirectX", b"VideoCard", b"internal3D", b"svga"))
    elif map_mode == "no-dither":
        replacements.append((b"DirectXExt", b"Dithering", b"forcealways", b"disabled"))
    validate_display_profile("a2racer1", "dgvoodoo-windowed", display_profile)
    if display_profile != "original":
        scaling = b"stretched" if display_profile in WIDE_DISPLAY_PROFILES else b"stretched_4_3"
        replacements.extend(((b"General", b"ScalingMode", b"unspecified", scaling),
                             (b"General", b"CenterAppWindow", b"false", b"true"),
                             (b"GeneralExt", b"WindowedAttributes", b"", b"borderless, fullscreensize"),
                             (b"GeneralExt", b"Resampling", b"bilinear", b"pointsampled")))
        if display_profile in HD_DISPLAY_PROFILES:
            replacements.append((b"DirectX", b"Resolution", b"unforced",
                                 HD_DISPLAY_RESOLUTIONS[display_profile]))
        if display_profile == "hd-1280x960-fake":
            replacements.extend(((b"General", b"FullScreenMode", b"false", b"true"),
                                 (b"GeneralExt", b"FullscreenAttributes", b"", b"fake")))
    for section, key, before, after in replacements:
        lines = config.splitlines(keepends=True)
        active = b""
        matches = []
        for index, line in enumerate(lines):
            heading = re.fullmatch(rb"[ \t]*\[([^\]]+)\][ \t]*", line.rstrip(b"\r\n"))
            if heading:
                active = heading[1]
            if active == section:
                match = re.fullmatch(rb"(" + key + rb"[ \t]*=[ \t]*)([^\r\n]*)(\r?\n)?", line)
                if match:
                    matches.append((index, match))
        if len(matches) != 1 or matches[0][1][2].strip() != before:
            raise ValueError("Onverwachte dgVoodoo-raceconfig; niets gekopieerd.")
        index, match = matches[0]
        lines[index] = match[1] + after + (match[3] or b"")
        config = b"".join(lines)
    return config


def _plan_component_profile(component_root: Path, components: dict, source: Path, relative_root: Path,
                            config_name: str, config: bytes, new_directory: str | None) -> list[dict]:
    destination_root = source / relative_root
    reserved = {name.casefold() for name in (*components, config_name)}
    if destination_root.exists() and any(item.name.casefold() in reserved for item in destination_root.iterdir()):
        raise ValueError("Wrapperbestand bestaat al in bron; overschrijven geweigerd.")
    planned = []
    for name, expected in components.items():
        path = component_root / expected["source"]
        data = _read_pinned_component(path, expected, name)
        planned.append({"relative_path": (relative_root / name).as_posix(),
                        "source_path": str(path), "sha256": expected["sha256"], "data": data,
                        "new_directory": new_directory})
    planned.append({"relative_path": (relative_root / config_name).as_posix(),
                    "source_path": None, "sha256": hashlib.sha256(config).hexdigest(), "data": config,
                    "new_directory": new_directory})
    return planned


def apply_graphics_wrapper(trial: Path, planned: list[dict]) -> list[dict]:
    # Recheck all destinations before the first write. Exclusive creates also
    # refuse a destination appearing after this check; original files are untouched.
    for item in planned:
        target = trial / item["relative_path"]
        validate_ancestors(target)
        if not target.resolve().is_relative_to(trial.resolve()):
            raise ValueError("Wrapperpad valt buiten de proefmap.")
        if target.exists():
            raise ValueError("Wrapperbestand verscheen in proef; overschrijven geweigerd.")
    new_directories = sorted({item["new_directory"] for item in planned if item.get("new_directory")})
    for relative in new_directories:
        directory = trial / relative
        validate_ancestors(directory)
        if not directory.resolve().is_relative_to(trial.resolve()) or directory.exists():
            raise ValueError("Wrappermap verscheen of valt buiten proef; overschrijven geweigerd.")
    for relative in new_directories:
        (trial / relative).mkdir()  # Exclusive; no pre-existing local directory is merged.
    dependencies = []
    for item in planned:
        target = trial / item["relative_path"]
        with target.open("xb") as handle:
            handle.write(item["data"])
        dependencies.append({"path": str(target), "relative_path": item["relative_path"],
                             "source_path": item["source_path"], "sha256": item["sha256"],
                             "size": len(item["data"])})
    return dependencies


def configure_trial(game: str, game_path: Path, report_path: Path, debug: bool,
                    movie_display_mode: str = "original", disable_movies: bool = False) -> list[dict]:
    """Plan all requested INI changes before any backup or config is written.

    Multiple settings in one file share the original-byte backup and unified
    diff. DISPLAY_MODE=1 and MOVIES/ON=0 are existing game settings;
    no executable is patched. Changes are scoped to the requested section.
    """
    if game not in EXPECTED_BINARIES:
        raise ValueError("Onbekende game.")
    validate_movie_mode(game, "launcher", movie_display_mode)
    validate_disable_movies(game, "launcher", disable_movies)
    validate_tree(game_path)
    validate_tree(report_path)
    choices = []
    if debug:
        choices.extend([(p, "HELPDESK", k, "0", "1") for p, k in
                        ([("A2.INI", "DEBUG"), ("MOVIE.INI", "DEBUG")] if game == "a2racer1"
                         else [("DATA/RASER.INI", "DEBUGON")])])
    if movie_display_mode == "640x480":
        choices.append(("MOVIE.INI", "HELPDESK", "DISPLAY_MODE", "0", "1"))
    if disable_movies:
        choices.append(("DATA/RASER.INI", "MOVIES", "ON", "1", "0"))
    if not choices:
        return []
    grouped = {}
    for relative, section_name, key, before, after in choices:
        grouped.setdefault(relative, []).append((section_name, key, before, after))
    planned = []
    changes = []
    for relative, settings in grouped.items():
        path = game_path / relative
        data = path.read_bytes()
        lines = data.splitlines(keepends=True)
        section = None
        matches = {(s, k): [] for s, k, _, _ in settings}
        section_counts = {s: 0 for s, _, _, _ in settings}
        for index, line in enumerate(lines):
            section_match = re.fullmatch(rb"\s*\[([^\]\r\n]+)\]\s*", line)
            if section_match:
                section = section_match[1].decode("latin-1").strip().upper()
                if section in section_counts:
                    section_counts[section] += 1
                continue
            for section_name, key, _, _ in settings:
                if section == section_name:
                    match = re.fullmatch(rb"([ \t]*" + key.encode("ascii") + rb"[ \t]*=[ \t]*)([^\r\n]*)(\r\n|\n|\r)?", line, re.IGNORECASE)
                    if match:
                        matches[(section_name, key)].append((index, match))
        for section_name, key, before, after in settings:
            if section_counts[section_name] != 1 or len(matches[(section_name, key)]) != 1:
                raise ValueError(f"{relative}: verwacht precies een [{section_name}] {key}.")
            index, match = matches[(section_name, key)][0]
            value = match[2]
            if value.strip() != before.encode("ascii"):
                raise ValueError(f"{relative}: {key} moet oorspronkelijk {before} zijn.")
            new_value = value.replace(before.encode("ascii"), after.encode("ascii"), 1)
            lines[index] = match[1] + new_value + (match[3] or b"")
            changes.append({"path": relative, "section": section_name, "key": key, "before": before, "after": after})
        planned.append((relative, data, b"".join(lines)))
    backup = report_path / "config-before"
    diff_path = report_path / "config.diff"
    if backup.exists() or diff_path.exists():
        raise ValueError("Config-backupmap of diff bestaat al.")
    backup.mkdir()
    diffs = []
    for relative, before, after in planned:
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(before)
        (game_path / relative).write_bytes(after)
        diffs.extend(difflib.unified_diff(before.decode("latin-1").splitlines(True), after.decode("latin-1").splitlines(True), fromfile=relative + " (origineel)", tofile=relative + " (proef)"))
    diff_path.write_text("".join(diffs), encoding="utf-8", newline="")
    return changes


def enable_debug(game: str, game_path: Path, report_path: Path) -> list[dict]:
    """Compatibility entry point for existing debug-only callers."""
    return configure_trial(game, game_path, report_path, True)


def plan_native_options(workspace: Path, game: str, stage: str, keep_native_options: bool) -> dict | None:
    """Carry the latest user-written options forward without interpreting fields.

    Only known A2-I trial binaries qualify. Saved scores/profiles are not copied.
    Callers must have closed their earlier game before starting a new trial.
    """
    if not keep_native_options:
        return None
    if game != "a2racer1" or stage != "launcher":
        raise ValueError("Gameopties meenemen vereist de bekende deel-I-launcher.")
    root = workspace / "local/experiments/a2racer1"
    validate_ancestors(root)
    if not root.exists():
        return None
    candidates = []
    for directory in root.iterdir():
        validate_ancestors(directory)
        if not directory.is_dir():
            continue
        candidate = directory / "game/OPTIE.A2R"
        validate_ancestors(candidate)
        if not candidate.is_file():
            continue
        report = workspace / "reports/runtime/a2racer1" / directory.name / "prepared.json"
        validate_ancestors(report)
        if not report.is_file() or report.stat().st_size > 65536:
            continue
        descriptor = json.loads(report.read_text(encoding="utf-8"))
        if (not isinstance(descriptor, dict) or descriptor.get("game") != game
                or descriptor.get("stage") != "launcher"
                or descriptor.get("run_name") != directory.name):
            continue
        # Old absolute report paths may refer to a relocated portable kit.
        # Read only the recomputed local paths, bound to the recorded run name
        # and verified binaries below; never follow a report-supplied path.
        known = True
        for name, allowed in (("A2MENU.DAT", NATIVE_OPTIONS_MENU_HASHES),
                              ("A2SPEL.DAT", {EXPECTED_BINARIES[game]["A2SPEL.DAT"],
                                              *RENDER_DISTANCE_RACE_HASHES.values(),
                                              *FOCUS_RECOVERY_RACE_HASHES.values(),
                                              *(value for variants in CAMERA_RACE_HASHES.values()
                                                for value in variants.values()),
                                              *OBJECT_DISTANCE_RACE_HASHES})):
            binary = candidate.parent / name
            validate_ancestors(binary)
            if (not binary.is_file() or binary.stat().st_size > 512 * 1024
                    or hashlib.sha256(binary.read_bytes()).hexdigest() not in allowed):
                known = False
                break
        if known:
            candidates.append((candidate.stat().st_mtime_ns, candidate))
    if not candidates:
        return None
    _, path = max(candidates, key=lambda entry: (entry[0], str(entry[1])))
    before = path.stat()
    if before.st_size != NATIVE_OPTIONS_SIZE:
        raise ValueError("Laatste OPTIE.A2R heeft een onbekende grootte; opties niet meegenomen.")
    with path.open("rb") as handle:
        data = handle.read(NATIVE_OPTIONS_SIZE + 1)
    after = path.stat()
    if len(data) != NATIVE_OPTIONS_SIZE or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Gameopties veranderden tijdens lezen; sluit de eerdere game eerst af.")
    return {"source_path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data), "source_mtime_ns": before.st_mtime_ns, "data": data}


def prepare_trial(workspace: Path, game: str, run_name: str, stage: str, debug: bool,
                  movie_display_mode: str = "original", graphics_wrapper: str = "native",
                  graphics_diagnostic: str = "none", skip_intro: bool = False,
                  disable_movies: bool = False, race_fps_limit: int = 0,
                  hide_watermark: bool = False, map_mode: str = "original",
                  omit_native_intro: bool = False, any_key_welcome: bool = False,
                  display_profile: str = "original", keep_native_options: bool = False,
                  native_graphics: str = "preserve", native_dashboard: int = -1,
                  pump_launcher_messages: bool = False,
                  render_distance_profile: str = "original", native_horizon: int = -1,
                  race_focus_recovery: bool = False,
                  camera_profile: str = "original", texture_profile: str = "original",
                  object_distance_profile: str = "original", local_game_data: bool = False,
                  hud_profile: str = "original", menu_profile: str = "original",
                  menu_render_profile: str = "original") -> dict:
    source, trial, report = paths_for(workspace, game, run_name)
    from tools.menu_presentation import validate_profile as validate_menu_profile, validate_render_profile
    validate_render_profile(menu_profile, menu_render_profile)
    if menu_profile != "original":
        validate_graphics_profile(game, graphics_wrapper, graphics_diagnostic)
        validate_menu_profile(game, stage, graphics_wrapper, menu_profile)
    if type(local_game_data) is not bool or local_game_data and game != "a2racer1":
        raise ValueError("Deze lokale-data-start is uitsluitend onderzocht voor deel I.")
    local_data = None
    if local_game_data:
        from tools.local_game_data import check_local_source, launch_environment
        local_data = check_local_source(source, full=True)
        local_data["environment"] = launch_environment(trial)
    if stage not in ("launcher", "intro", "menu", "race"):
        raise ValueError("Onbekende startfase.")
    if stage == "race" and game != "a2racer2":
        raise ValueError("Directe racestart is uitsluitend onderzocht voor deel II.")
    if game == "a2racer2" and stage not in ("launcher", "race"):
        raise ValueError("Deel II ondersteunt hier launcher/race; intro/menu-argumenten zijn nog onbekend.")
    validate_skip_intro(game, stage, skip_intro)
    requested_native_graphics = native_graphics
    # The legacy HD shortcut supplied only a wrapper profile. Preserving its
    # software choice rendered low-resolution pixels despite the HD request.
    if game == "a2racer1" and display_profile in HD_DISPLAY_PROFILES and native_graphics == "preserve":
        native_graphics = "accelerated-640"
    if camera_profile not in CAMERA_PROFILES:
        raise ValueError("Onbekend cameraprofiel.")
    if ((camera_profile != "original") != (display_profile in WIDE_DISPLAY_PROFILES)):
        raise ValueError("Breedbeeldverzoek en experimentele camerapatch moeten samen worden gekozen.")
    if camera_profile != "original" and (game != "a2racer1" or stage != "launcher" or
            graphics_wrapper != "hybrid-dgvoodoo" or native_graphics != "accelerated-640"):
        raise ValueError("Cameraproef vereist de bekende deel-I-launcher met hybride native 3D.")
    from tools.resource_archive import PROFILES as TEXTURE_PROFILES
    if texture_profile not in TEXTURE_PROFILES:
        raise ValueError("Onbekend textureprofiel.")
    if texture_profile != "original" and (game != "a2racer1" or stage != "launcher" or
            graphics_wrapper != "hybrid-dgvoodoo" or native_graphics != "accelerated-640"):
        raise ValueError("Textureproef vereist de bekende deel-I-launcher met hybride native 3D.")
    from tools.hud_hd_fix import PROFILES as HUD_PROFILES
    if hud_profile not in HUD_PROFILES:
        raise ValueError("Onbekend HD-interfaceprofiel.")
    if hud_profile != "original" and (game != "a2racer1" or stage != "launcher" or
            graphics_wrapper != "hybrid-dgvoodoo" or native_graphics != "accelerated-640" or
            display_profile not in HD_DISPLAY_PROFILES or not race_focus_recovery or
            texture_profile != "hd-expanded-v1"):
        raise ValueError("HD-interfaceproef vereist deel I, HD uitgebreid, hybride native 3D, HD-beeld en focusherstel.")
    if object_distance_profile not in OBJECT_DISTANCE_PROFILES:
        raise ValueError("Onbekend objectafstandprofiel.")
    if object_distance_profile != "original" and (game != "a2racer1" or stage != "launcher" or
            graphics_wrapper != "hybrid-dgvoodoo" or native_graphics != "accelerated-640"):
        raise ValueError("Objectafstandproef vereist de bekende deel-I-launcher met hybride native 3D.")
    if render_distance_profile not in RENDER_DISTANCE_PROFILES:
        raise ValueError("Onbekend zichtgebiedprofiel.")
    if render_distance_profile != "original" and (
            game != "a2racer1" or stage != "launcher" or
            graphics_wrapper != "hybrid-dgvoodoo" or native_graphics != "accelerated-640"):
        raise ValueError("Groter zichtgebied vereist de bekende deel-I-launcher met hybride native 3D.")
    if type(race_focus_recovery) is not bool:
        raise ValueError("Focusherstel moet een expliciete boolean zijn.")
    if race_focus_recovery and (game != "a2racer1" or stage != "launcher" or
            graphics_wrapper != "hybrid-dgvoodoo" or native_graphics != "accelerated-640"):
        raise ValueError("Focusherstelproef vereist de bekende deel-I-launcher met hybride native 3D.")
    if (omit_native_intro or any_key_welcome or pump_launcher_messages) and (game != "a2racer1" or stage != "launcher"):
        raise ValueError("Start/toetsfix vereist de bekende deel-I-launcher.")
    if (native_graphics != "preserve" or native_dashboard != -1 or native_horizon != -1) and (game != "a2racer1" or stage != "launcher"):
        raise ValueError("Native launcheropties vereisen deel I en startfase launcher.")
    validate_disable_movies(game, stage, disable_movies)
    validate_movie_mode(game, stage, movie_display_mode)
    validate_graphics_profile(game, graphics_wrapper, graphics_diagnostic)
    validate_menu_profile(game, stage, graphics_wrapper, menu_profile)
    validate_tree(source)
    from tools.game_fixes import plan_fixes, apply_fixes
    binary_arguments = {"race_focus_recovery": True} if race_focus_recovery else {}
    binary_plan = plan_fixes(source, omit_native_intro, any_key_welcome, pump_launcher_messages,
                             render_distance_profile, **binary_arguments)
    from tools.widescreen_fix import compose_fixes
    binary_plan = compose_fixes(source, binary_plan, camera_profile,
                               render_distance_profile=render_distance_profile,
                               race_focus_recovery=race_focus_recovery)
    from tools.object_distance_fix import compose_fixes as compose_object_fixes
    binary_plan = compose_object_fixes(source, binary_plan, object_distance_profile,
                                      render_distance_profile=render_distance_profile,
                                      race_focus_recovery=race_focus_recovery,
                                      camera_profile=camera_profile)
    if texture_profile != "original":
        from tools.resource_archive import plan_fixes as plan_texture_fixes, texture_asset_specs
        specs = texture_asset_specs(texture_profile)
        texture_paths = {spec["resource"]["name"]: workspace / spec["path"] for spec in specs}
        for texture_path in texture_paths.values():
            validate_ancestors(texture_path)
        if len(specs) == 1:
            binary_plan.extend(plan_texture_fixes(source, next(iter(texture_paths.values())), profile=texture_profile))
        else:
            binary_plan.extend(plan_texture_fixes(source, profile=texture_profile, texture_paths=texture_paths))
        if texture_profile in ("hd-scenery-cockpit", "hd-expanded-v1"):
            from tools.sprite_archive import plan_fixes as plan_sprite_fixes, sprite_asset_specs
            sprite_paths = {spec["index"]: workspace / spec["path"]
                            for spec in sprite_asset_specs(texture_profile)}
            for sprite_path in sprite_paths.values():
                validate_ancestors(sprite_path)
            binary_plan.extend(plan_sprite_fixes(source, asset_paths=sprite_paths, profile=texture_profile))
    if hud_profile != "original":
        from tools.hud_hd_fix import compose_fixes as compose_hud_fixes
        binary_plan = compose_hud_fixes(workspace, source, binary_plan, hud_profile)
    if menu_profile == "refreshed-fullscreen":
        from tools.menu_art_fix import plan_fixes as plan_menu_art
        binary_plan.extend(plan_menu_art(source, workspace / "local/mods/a2racer1/menu-refresh-v1"))
    if menu_profile != "original":
        from tools.menu_input_fix import compose_fixes as compose_menu_input
        binary_plan = compose_menu_input(source, binary_plan, menu_profile)
    menu_options = {"menu_profile": menu_profile} if menu_profile != "original" else {}
    if menu_render_profile != "original":
        menu_options["menu_render_profile"] = menu_render_profile
    wrapper_plan = plan_graphics_wrapper(workspace, game, source, graphics_wrapper, graphics_diagnostic,
                                         race_fps_limit, hide_watermark, map_mode, display_profile, **menu_options)
    native_options = plan_native_options(workspace, game, stage, keep_native_options)
    from tools.game_options import plan_options
    native_options = plan_options(source, native_options, native_graphics, native_dashboard,
                                  horizon=native_horizon)
    if trial.parent.exists() or report.exists():
        raise ValueError("Proefmap of rapportmap bestaat al; kies een verse proefnaam.")
    report.mkdir(parents=True)
    before = snapshot(game, source, report, "source-before.json")
    hashes = {item["path"]: item["sha256"] for item in before["files"]}
    for relative, expected in EXPECTED_BINARIES[game].items():
        if hashes.get(relative) != expected:
            raise ValueError(f"Onbekende executable-versie: {relative}; er wordt niets gestart.")
    trial.parent.mkdir(parents=True)
    shutil.copytree(source, trial, copy_function=shutil.copy2)
    copied = snapshot(game, trial, report, "trial-copied.json")
    if any(manifest_diff(before, copied).values()):
        raise ValueError("Proefkopie wijkt af van bron; er wordt niets gestart.")
    if local_game_data:
        # Recheck the actual copy before options/patches, including resources
        # changed between initial validation and copying.
        check_local_source(trial, full=True)
    changes = configure_trial(game, trial, report, debug, movie_display_mode, disable_movies)
    binary_fixes = apply_fixes(trial, binary_plan)
    dependencies = apply_graphics_wrapper(trial, wrapper_plan)
    if native_options:
        destination = trial / "OPTIE.A2R"
        validate_ancestors(destination)
        if destination.exists() and (destination.stat().st_nlink != 1 or destination.samefile(source / "OPTIE.A2R")):
            raise ValueError("Gameopties mogen uitsluitend in een zelfstandige proefkopie worden gezet.")
        destination.write_bytes(native_options["data"])
        # Preparing an unplayed probe must not make its inherited choices newer
        # than the user's own last options change.
        if "source_mtime_ns" in native_options:
            os.utime(destination, ns=(native_options["source_mtime_ns"], native_options["source_mtime_ns"]))
    prepared_manifest = snapshot(game, trial, report, "trial-before.json")
    prepared_hashes = {item["path"]: item["sha256"] for item in prepared_manifest["files"]}
    if game == "a2racer1":
        executable = {"launcher": "A2.EXE", "intro": "A2MOVIE.DAT", "menu": "A2MENU.DAT"}[stage]
        arguments = {"launcher": [], "intro": ["a2intro.smk"], "menu": ["/FIRST"]}[stage]
        working_directory = trial
    else:
        executable = "DATA/SPEL.DAT" if stage == "race" else "DATA/A2_II.EXE"
        arguments, working_directory = [], trial / "DATA"
    descriptor = {"game": game, "run_name": run_name, "stage": stage, "source_path": str(source),
                  "trial_path": str(trial), "report_path": str(report), "executable_path": str(trial / executable),
                  "executable_sha256": prepared_hashes[executable], "arguments": arguments,
                  "working_directory": str(working_directory), "movie_display_mode": movie_display_mode,
                  "skip_intro": bool(skip_intro),
                  "disable_movies": bool(disable_movies),
                  "intro_executable_path": str(trial / "A2MOVIE.DAT") if skip_intro else None,
                  "intro_executable_sha256": hashes.get("A2MOVIE.DAT") if skip_intro else None,
                  "graphics_wrapper": graphics_wrapper, "graphics_dependencies": dependencies,
                  "graphics_diagnostic": graphics_diagnostic,
                  "race_fps_limit": race_fps_limit, "hide_watermark": hide_watermark,
                  "map_mode": map_mode,
                  "display_profile": display_profile,
                  "keep_native_options": bool(keep_native_options),
                  "native_graphics": native_graphics, "native_dashboard": native_dashboard,
                  "native_horizon": native_horizon,
                  "requested_native_graphics": requested_native_graphics,
                  "pump_launcher_messages": bool(pump_launcher_messages),
                  "render_distance_profile": render_distance_profile,
                  "race_focus_recovery": race_focus_recovery,
                  "camera_profile": camera_profile,
                  "texture_profile": texture_profile,
                  "hud_profile": hud_profile,
                  "menu_profile": menu_profile,
                  "menu_render_profile": menu_render_profile,
                  "menu_native_canvas": [640, 480] if game == "a2racer1" else None,
                  "menu_runtime_verified": False,
                  "menu_presentation_route": "native-fullscreen-640x480" if menu_profile != "original" else "original-windowed",
                  "menu_input_fix": "menu-font-measurement-fallback" if menu_profile != "original" else None,
                  "local_game_data": local_data,
                  "object_distance_profile": object_distance_profile,
                  "widescreen_complete": False,
                  "native_options": {key: value for key, value in native_options.items() if key != "data"} if native_options else None,
                  "omit_native_intro": bool(omit_native_intro),
                  "any_key_welcome": bool(any_key_welcome), "binary_fixes": binary_fixes,
                  "graphics_wrapper_version": {"dxwrapper-windowed": DXWRAPPER_VERSION,
                                               "cnc-ddraw-gdi": CNC_DDRAW_VERSION,
                                               "hybrid-windowed": f"cnc-ddraw {CNC_DDRAW_VERSION}; dxwrapper {DXWRAPPER_VERSION}",
                                               "hybrid-dgvoodoo": f"cnc-ddraw {CNC_DDRAW_VERSION}; dgVoodoo {DGVOODOO_VERSION}",
                                               "dgvoodoo-windowed": DGVOODOO_VERSION}.get(graphics_wrapper),
                  "config_changes": changes}
    write_json(report / "prepared.json", descriptor)
    return descriptor


def finish_trial(workspace: Path, game: str, run_name: str) -> dict:
    source, trial, report = paths_for(workspace, game, run_name)
    validate_tree(report)
    before = json.loads((report / "source-before.json").read_text(encoding="utf-8"))
    original_after = snapshot(game, source, report, "source-after.json")
    trial_before = json.loads((report / "trial-before.json").read_text(encoding="utf-8"))
    trial_after = snapshot(game, trial, report, "trial-after.json")
    source_diff = manifest_diff(before, original_after)
    trial_diff = manifest_diff(trial_before, trial_after)
    debug_files = []
    for record in trial_after["files"]:
        name = Path(record["path"]).name.lower()
        if name == "debug.txt" or (name.startswith("dxwrapper-") and name.endswith(".log")):
            data_path = trial / record["path"]
            # Bounded copy: the full file's identity is in the manifest.
            output = report / "game-logs" / record["path"]
            validate_ancestors(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            with data_path.open("rb") as handle:
                data = handle.read(4 * 1024 * 1024)
            if output.exists():
                raise ValueError("Logkopie bestaat al.")
            output.write_bytes(data)
            debug_files.append({"path": record["path"], "size": record["size"], "sha256": record["sha256"], "copied_bytes": len(data), "truncated": record["size"] > len(data)})
    result = {"source_unchanged": not any(source_diff.values()), "source_diff": source_diff,
              "trial_diff": trial_diff, "debug_files": debug_files,
              "note": "Momentopname; lopende processen kunnen later nog proefbestanden wijzigen."}
    write_json(report / "integrity.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "finish"))
    parser.add_argument("--game", required=True, choices=tuple(EXPECTED_BINARIES))
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--stage", default="launcher", choices=("launcher", "intro", "menu", "race"))
    parser.add_argument("--enable-debug", action="store_true")
    parser.add_argument("--skip-intro", action="store_true")
    parser.add_argument("--disable-movies", action="store_true")
    parser.add_argument("--race-fps-limit", type=int, default=0)
    parser.add_argument("--hide-watermark", action="store_true")
    parser.add_argument("--omit-native-intro", action="store_true")
    parser.add_argument("--any-key-welcome", action="store_true")
    parser.add_argument("--pump-launcher-messages", action="store_true")
    parser.add_argument("--render-distance-profile", choices=RENDER_DISTANCE_PROFILES, default="original")
    parser.add_argument("--race-focus-recovery", action="store_true")
    parser.add_argument("--camera-profile", choices=CAMERA_PROFILES, default="original")
    from tools.resource_archive import PROFILES as TEXTURE_PROFILES
    parser.add_argument("--texture-profile", choices=TEXTURE_PROFILES, default="original")
    from tools.hud_hd_fix import PROFILES as HUD_PROFILES
    parser.add_argument("--hud-profile", choices=HUD_PROFILES, default="original")
    from tools.menu_presentation import PROFILES as MENU_PROFILES
    parser.add_argument("--menu-profile", choices=MENU_PROFILES, default="original")
    from tools.menu_presentation import RENDER_PROFILES
    parser.add_argument("--menu-render-profile", choices=RENDER_PROFILES, default="original")
    parser.add_argument("--local-game-data", action="store_true")
    parser.add_argument("--object-distance-profile", choices=OBJECT_DISTANCE_PROFILES, default="original")
    parser.add_argument("--map-mode", choices=("original", "gdi", "svga", "no-dither"), default="original")
    parser.add_argument("--display-profile", choices=DISPLAY_PROFILES, default="original")
    parser.add_argument("--keep-native-options", action="store_true")
    parser.add_argument("--native-graphics", choices=("preserve", "software-640", "accelerated-640"), default="preserve")
    parser.add_argument("--native-dashboard", type=int, choices=(-1, 0, 1), default=-1)
    parser.add_argument("--native-horizon", type=int, choices=(-1, 0, 1), default=-1)
    parser.add_argument("--movie-display-mode", default="original", choices=("original", "640x480"))
    parser.add_argument("--graphics-wrapper", default="native", choices=("native", "dxwrapper-windowed", "cnc-ddraw-gdi", "hybrid-windowed", "hybrid-dgvoodoo", "dgvoodoo-windowed"))
    parser.add_argument("--graphics-diagnostic", default="none", choices=("none", "fps", "gdi", "emulate-surface", "gdi-origin"))
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare_trial(WORKSPACE, args.game, args.run_name, args.stage, args.enable_debug,
                                   args.movie_display_mode, args.graphics_wrapper, args.graphics_diagnostic,
                                   args.skip_intro, args.disable_movies, args.race_fps_limit,
                                   args.hide_watermark, args.map_mode, args.omit_native_intro,
                                   args.any_key_welcome, args.display_profile, args.keep_native_options,
                                   args.native_graphics, args.native_dashboard, args.pump_launcher_messages,
                                   args.render_distance_profile, native_horizon=args.native_horizon,
                                   race_focus_recovery=args.race_focus_recovery,
                                   camera_profile=args.camera_profile, texture_profile=args.texture_profile,
                                   object_distance_profile=args.object_distance_profile,
                                   local_game_data=args.local_game_data,
                                   hud_profile=args.hud_profile, menu_profile=args.menu_profile,
                                   menu_render_profile=args.menu_render_profile)
        else:
            result = finish_trial(WORKSPACE, args.game, args.run_name)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError) as exc:
        print(f"Proefvoorbereiding/integriteitscontrole mislukt: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
