"""Local display recovery for an explicitly started, owned native-menu probe.

Import and snapshot are read-only. Call restore only after owned-job cleanup.
No registry updates, hooks, driver installs or game processes are involved.
"""
from __future__ import annotations

import copy
import ctypes
from dataclasses import dataclass
import os
import struct

DEVMODEW_SIZE = 220
KNOWN_PUBLIC_SIZES = (188, 220)
DISPLAY_DEVICEW_SIZE = 840
ATTACHED_TO_DESKTOP = 1
ENUM_CURRENT_SETTINGS = 0xFFFFFFFF
CDS_TEST = 2
MAX_DEVICES = 32


@dataclass(frozen=True)
class DisplayDevice:
    name: str
    state_flags: int


def mode_summary(raw: bytes) -> dict:
    """Inspect the documented fixed Windows UTF-16 DEVMODEW layout."""
    if not isinstance(raw, bytes) or len(raw) != DEVMODEW_SIZE:
        raise ValueError("De huidige displaymodus ontbreekt of heeft geen DEVMODEW220-layout.")
    public_size, driver_extra = struct.unpack_from("<HH", raw, 68)
    if public_size not in KNOWN_PUBLIC_SIZES or driver_extra != 0:
        raise ValueError("Afwijkende DEVMODEW-grootte of private drivergegevens.")
    bits, width, height, flags, frequency = struct.unpack_from("<5I", raw, 168)
    if not (1 <= width <= 131072 and 1 <= height <= 131072 and 1 <= bits <= 128
            and 0 <= frequency <= 10000):
        raise ValueError("Ongeldige huidige displaymodus.")
    x, y, orientation, fixed_output = struct.unpack_from("<iiII", raw, 76)
    # Some current Windows drivers return the older public layout ending just
    # after dmDisplayFrequency. Bytes past its declared dmSize are not fields.
    panning_width, panning_height = struct.unpack_from("<II", raw, 212) if public_size == 220 else (0, 0)
    return {"width": width, "height": height, "bits_per_pixel": bits,
            "frequency": frequency, "position_x": x, "position_y": y,
            "orientation": orientation, "fixed_output": fixed_output,
            "display_flags": flags, "panning_width": panning_width,
            "panning_height": panning_height}


class WindowsDisplayAPI:
    """Small injectable Win32 adapter; fixed-width buffers avoid wchar ABI drift."""

    def __init__(self, user32=None):
        if user32 is None:
            if os.name != "nt":
                raise OSError("Displayherstel vereist Windows.")
            user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32 = user32
        signatures = {
            "EnumDisplayDevicesW": (ctypes.c_int32, (ctypes.c_wchar_p, ctypes.c_uint32,
                                                    ctypes.c_void_p, ctypes.c_uint32)),
            "EnumDisplaySettingsW": (ctypes.c_int32, (ctypes.c_wchar_p, ctypes.c_uint32,
                                                     ctypes.c_void_p)),
            "ChangeDisplaySettingsExW": (ctypes.c_int32, (ctypes.c_wchar_p, ctypes.c_void_p,
                                                         ctypes.c_void_p, ctypes.c_uint32,
                                                         ctypes.c_void_p)),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(user32, name)
            function.restype, function.argtypes = result, arguments

    def enum_devices(self):
        result = []
        for index in range(MAX_DEVICES + 1):
            data = ctypes.create_string_buffer(DISPLAY_DEVICEW_SIZE)
            struct.pack_into("<I", data, 0, DISPLAY_DEVICEW_SIZE)
            if not self.user32.EnumDisplayDevicesW(None, index, data, 0):
                return result
            if index == MAX_DEVICES:
                raise ValueError("De displaylijst overschrijdt de proefgrens.")
            # WCHAR is always two bytes in this Windows wire layout.
            name = data.raw[4:68].decode("utf-16-le").split("\0", 1)[0]
            flags = struct.unpack_from("<I", data, 324)[0]
            result.append(DisplayDevice(name, flags))
        raise AssertionError("Onbereikbare display-enumeratie.")

    def current_mode(self, device_name):
        data = ctypes.create_string_buffer(DEVMODEW_SIZE)
        struct.pack_into("<HH", data, 68, DEVMODEW_SIZE, 0)
        if not self.user32.EnumDisplaySettingsW(device_name, ENUM_CURRENT_SETTINGS, data):
            raise OSError("De huidige displaymodus kon niet worden gelezen: " + device_name)
        return data.raw

    def change_mode(self, device_name, raw, flags):
        mode_summary(raw)
        if flags not in (CDS_TEST, 0):
            raise ValueError("Alleen tijdelijk testen/herstellen is toegestaan.")
        public_size = struct.unpack_from("<H", raw, 68)[0]
        # Keep the driver's known public version/header. Never submit unknown
        # bytes outside an older declared layout as private restore information.
        public = raw[:public_size] + bytes(DEVMODEW_SIZE - public_size)
        data = ctypes.create_string_buffer(public, DEVMODEW_SIZE)
        return int(self.user32.ChangeDisplaySettingsExW(device_name, data, None, flags, None))


class WindowsDisplaySession:
    """Snapshot once; best-effort restore of only those same attached adapters.

The caller owns the process lifecycle. A successful restore does not prove that
the native game or its own cleanup succeeded. Check/prepare paths need no object.
"""

    def __init__(self, api=None):
        self.api = api if api is not None else WindowsDisplayAPI()
        self._captured = None
        self._public = None
        self._restore_result = None

    def _devices(self):
        devices, names = [], set()
        for device in self.api.enum_devices():
            if (not isinstance(device, DisplayDevice) or not isinstance(device.name, str)
                    or not 1 <= len(device.name) <= 32 or "\0" in device.name
                    or type(device.state_flags) is not int or not 0 <= device.state_flags <= 0xFFFFFFFF
                    or device.name.casefold() in names or len(devices) >= MAX_DEVICES):
                raise ValueError("Ongeldige of dubbele display-inventarisatie.")
            names.add(device.name.casefold())
            devices.append(device)
        return devices

    def snapshot(self):
        if self._captured is not None:
            raise ValueError("Deze displaysessie heeft al een voorstartmeting.")
        captured, public = [], []
        for device in self._devices():
            if not device.state_flags & ATTACHED_TO_DESKTOP:
                continue
            raw = self.api.current_mode(device.name)
            summary = mode_summary(raw)
            captured.append((device, raw, summary))
            public.append({"device": device.name, "state_flags": device.state_flags,
                           "mode": summary, "devmodew_public_size": struct.unpack_from("<H", raw, 68)[0],
                           "devmodew_hex": raw.hex()})
        if not captured:
            raise ValueError("Geen aangesloten displaymodus vastgelegd; proefstart geblokkeerd.")
        self._captured = tuple(captured)
        self._public = {"schema": 1, "read_only": True, "devices": public}
        return copy.deepcopy(self._public)

    def restore(self, before):
        if self._captured is None or before != self._public:
            raise ValueError("Displayherstel vereist de ongewijzigde eigen voorstartmeting.")
        if self._restore_result is not None:
            return copy.deepcopy(self._restore_result)
        result = {"schema": 1, "registry_updated": False, "attempted": False,
                  "verified": False, "all_connected_restored": False,
                  "devices": [], "errors": [], "skipped_detached": [],
                  "untracked_devices": [], "flags": {"test": CDS_TEST, "apply": 0}}
        try:
            connected = {device.name.casefold(): device for device in self._devices()
                         if device.state_flags & ATTACHED_TO_DESKTOP}
        except (OSError, ValueError, TypeError, AttributeError) as error:
            result["errors"].append("Display-inventarisatie na de proef mislukt: " + str(error))
            self._restore_result = copy.deepcopy(result)
            return result
        original_names = {device.name.casefold() for device, _, _ in self._captured}
        result["untracked_devices"] = [device.name for name, device in connected.items()
                                       if name not in original_names]
        for device, raw, expected in self._captured:
            entry = {"device": device.name, "before": expected}
            result["devices"].append(entry)
            if device.name.casefold() not in connected:
                entry["status"] = "detached_skipped"
                result["skipped_detached"].append(device.name)
                continue
            try:
                current = mode_summary(self.api.current_mode(device.name))
                entry["after_job_cleanup"] = current
                if current == expected:
                    entry.update(status="unchanged", verified=True)
                    continue
                result["attempted"] = True
                tested = self.api.change_mode(device.name, raw, CDS_TEST)
                entry["test_result"] = tested
                if tested != 0:
                    entry["status"] = "test_failed"
                    result["errors"].append(device.name + ": oorspronkelijke modus werd niet geaccepteerd.")
                    continue
                applied = self.api.change_mode(device.name, raw, 0)
                entry["apply_result"] = applied
                if applied != 0:
                    entry["status"] = "apply_failed"
                    result["errors"].append(device.name + ": oorspronkelijke modus kon niet worden hersteld.")
                    continue
                actual = mode_summary(self.api.current_mode(device.name))
                entry["readback"] = actual
                entry["verified"] = actual == expected
                entry["status"] = "restored" if entry["verified"] else "readback_mismatch"
                if not entry["verified"]:
                    result["errors"].append(device.name + ": herstelde modus wijkt af bij teruglezen.")
            except (OSError, ValueError, TypeError, AttributeError) as error:
                entry.update(status="restore_error", error=str(error))
                result["errors"].append(device.name + ": " + str(error))
        # Applying one adapter can also move another adapter in the desktop
        # topology. Verify every surviving captured mode after the last apply.
        if result["attempted"]:
            for entry in result["devices"]:
                if entry.get("status") not in ("unchanged", "restored"):
                    continue
                try:
                    actual = mode_summary(self.api.current_mode(entry["device"]))
                    entry["final_readback"] = actual
                    entry["verified"] = actual == entry["before"]
                    if not entry["verified"]:
                        entry["status"] = "final_readback_mismatch"
                        result["errors"].append(entry["device"] + ": display veranderde tijdens ander displayherstel.")
                except (OSError, ValueError, TypeError, AttributeError) as error:
                    entry.update(status="final_readback_error", verified=False, error=str(error))
                    result["errors"].append(entry["device"] + ": " + str(error))
        result["all_connected_restored"] = not result["errors"]
        result["verified"] = not result["errors"] and not result["skipped_detached"]
        self._restore_result = copy.deepcopy(result)
        return result
