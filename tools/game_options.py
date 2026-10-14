"""Known A2-I option fields, derived from the supplied menu/race version.

Only prepare bytes for a fresh trial; never write or execute game sources.
See docs/launcher.md for the field evidence and runtime limitations.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

VERSION_HASHES = {
    "A2MENU.DAT": "45b883ec76872622241beb75afb3966723d9bee806d76741c29c6642df6ff6e6",
    "A2SPEL.DAT": "069d39e815fc631ef433550459e8105042cf740dfc311e4f9285d4cca148e726",
}
DEFAULT_OPTIONS = struct.pack("<10H", 1, 1, 0, 1, 0, 0, 1, 0, 3, 4)
GRAPHICS_MODES = {"software-640": 2, "accelerated-640": 0}
DISPLAY_MODE_OFFSET = 6
HORIZON_OFFSET = 8
DASHBOARD_OFFSET = 10


def derive_options(data: bytes, graphics: str, dashboard: int, horizon: int = -1) -> bytes:
    if len(data) != 20:
        raise ValueError("Onbekende OPTIE.A2R-grootte.")
    if graphics not in ("preserve", *GRAPHICS_MODES):
        raise ValueError("Onbekende native graphicskeuze.")
    if type(dashboard) is not int or dashboard not in (-1, 0, 1):
        raise ValueError("Dashboard moet behouden (-1), uit (0) of aan (1) zijn.")
    if type(horizon) is not int or horizon not in (-1, 0, 1):
        raise ValueError("Horizon moet behouden (-1), uit (0) of aan (1) zijn.")
    result = bytearray(data)
    if graphics != "preserve":
        struct.pack_into("<H", result, DISPLAY_MODE_OFFSET, GRAPHICS_MODES[graphics])
    if dashboard != -1:
        struct.pack_into("<H", result, DASHBOARD_OFFSET, dashboard)
    if horizon != -1:
        struct.pack_into("<H", result, HORIZON_OFFSET, horizon)
    return bytes(result)


def plan_options(source: Path, previous: dict | None, graphics: str, dashboard: int,
                 horizon: int = -1) -> dict | None:
    # Validate values even when no override is requested.
    derive_options(DEFAULT_OPTIONS, graphics, dashboard, horizon)
    if graphics == "preserve" and dashboard == -1 and horizon == -1:
        return previous
    for name, expected in VERSION_HASHES.items():
        path = source / name
        if (not path.is_file() or path.stat().st_size > 512 * 1024
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise ValueError(f"Native launcheropties vereisen de bekende deel-I-versie: {name}.")
    if previous:
        original, origin = previous["data"], previous["source_path"]
    elif (source / "OPTIE.A2R").exists():
        path = source / "OPTIE.A2R"
        if path.stat().st_size != 20:
            raise ValueError("Onbekende OPTIE.A2R-grootte in bron.")
        original, origin = path.read_bytes(), str(path)
    else:
        original, origin = DEFAULT_OPTIONS, None
    data = derive_options(original, graphics, dashboard, horizon)
    overrides = {"graphics": graphics, "dashboard": dashboard}
    if horizon != -1:
        overrides["horizon"] = horizon
    result = {"source_path": origin, "source_sha256": hashlib.sha256(original).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "data": data,
            "overrides": overrides,
            "origin": "previous-options" if previous else ("source-options" if origin else "native-defaults")}
    if previous and data == original and "source_mtime_ns" in previous:
        result["source_mtime_ns"] = previous["source_mtime_ns"]
    return result
