"""Read-only mode preflight for the optional native A2-I fullscreen menu.

EnumDisplaySettingsW only inventories modes of the default display. This tool
never changes a display mode, executes a game or loads a wrapper. Enumeration
does not guarantee that Windows will accept the mode at the later game start.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
import sys
from typing import Callable

PROFILES = ("original", "classic-fullscreen", "refreshed-fullscreen")
REQUIRED_MODE = (640, 480, 32)
MAX_MODES = 4096
DEVMODEW_SIZE = 220


def mode_reader(enum_display_settings: Callable) -> Callable:
    """Wrap the W API with a fresh, correctly sized DEVMODEW for every read.

    The injectable callback permits synthetic buffer/ABI contract tests without
    querying a real monitor. Only the documented output fields are inspected.
    """
    def read(index: int) -> tuple[int, int, int] | None:
        data = ctypes.create_string_buffer(DEVMODEW_SIZE)
        struct.pack_into("<HH", data, 68, DEVMODEW_SIZE, 0)  # dmSize, dmDriverExtra
        if not enum_display_settings(None, index, data):
            return None
        bits, width, height = struct.unpack_from("<III", data, 168)
        return width, height, bits
    return read


def windows_mode_reader() -> Callable:
    if sys.platform != "win32":
        raise OSError("Display-inventarisatie vereist Windows.")
    api = ctypes.WinDLL("user32", use_last_error=True).EnumDisplaySettingsW
    api.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p)
    api.restype = ctypes.c_int32
    return mode_reader(api)


def check_profile(profile: str, *, reader: Callable | None = None) -> dict:
    """Fail closed on missing/invalid modes; default menu needs no mode query."""
    if type(profile) is not str or profile not in PROFILES:
        raise ValueError("Onbekend menuprofiel.")
    result = {"profile": profile, "available": profile == "original",
              "read_only": True, "runtime_verified": False,
              "required_mode": None if profile == "original" else list(REQUIRED_MODE),
              "display": "default", "modes_scanned": 0, "reason": ""}
    if profile == "original":
        return result
    try:
        read = reader if reader is not None else windows_mode_reader()
        for index in range(MAX_MODES):
            mode = read(index)
            if mode is None:
                break
            if (type(mode) not in (tuple, list) or len(mode) != 3
                    or any(type(value) is not int for value in mode)
                    or not (1 <= mode[0] <= 131072 and 1 <= mode[1] <= 131072
                            and 1 <= mode[2] <= 128)):
                raise ValueError("Ongeldige displaymodus uit de inventarisatie.")
            result["modes_scanned"] += 1
            if tuple(mode) == REQUIRED_MODE:
                result["available"] = True
                return result
        else:
            raise ValueError("Displaylijst overschrijdt de inventarisatiegrens.")
        result["reason"] = (
            "Fullscreenmenu vereist een beschikbare 640 × 480 × 32-displaymodus. "
            "Kies Origineel · venster op dit scherm."
        )
    except (OSError, ValueError, TypeError, AttributeError) as error:
        result["reason"] = f"Fullscreenmenu kon niet veilig worden gecontroleerd: {error}"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    result = check_profile(parser.parse_args().profile)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["available"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
