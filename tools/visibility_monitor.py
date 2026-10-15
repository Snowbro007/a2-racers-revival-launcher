"""Read-only, version-pinned visibility samples from one existing A2 I race.

No game launch, writes, debugger attachment, suspension, input or focus changes.
External samples are not atomic and count flags/handles, not completed drawcalls.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.render_distance_fix import EXPECTED_SHA256, EXPECTED_SIZE, EXPECTED_PATCHED_SHA256_BY_PROFILE

BASE = 0x400000
IMAGE_SIZE = 0x8D000
BINARY_PROFILES = {EXPECTED_SHA256: "original", **{value: key for key, value in EXPECTED_PATCHED_SHA256_BY_PROFILE.items()}}
MAX_ELEMENTS = 16384  # Monitor resource cap, not an engine limit.
MAX_LOG_BYTES = 2 * 1024**2
OBJECT_STRIDE = 75
ROAD_STRIDE = 56
STATIC_CALLBACK_RVA = 0x80BD
SKY_CALLBACK_RVA = 0x8370
RUN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
# VAs/types proved in reports/render-distance/live-layout-evidence.json.
# Fog fields proved by their setters in execute-buffer-followup-findings.md.
FIELDS = {
    "cells_x": (0x4596D8, "i"), "cells_z": (0x4596DC, "i"),
    "extent_x": (0x4596E0, "i"), "extent_z": (0x4596E4, "i"),
    "cell_x": (0x4596E8, "i"), "cell_z": (0x4596EC, "i"),
    "xmin": (0x477014, "i"), "xmax": (0x4596F0, "i"),
    "zmin": (0x477018, "i"), "zmax": (0x4596F4, "i"),
    "camera_choice": (0x457728, "i"),
    "tracked_x": (0x45772C, "f"), "tracked_y": (0x457730, "f"), "tracked_z": (0x457734, "f"),
    "view_translation_x": (0x45B278, "f"), "view_translation_y": (0x45B27C, "f"), "view_translation_z": (0x45B280, "f"),
    "native_3d": (0x458C1C, "i"), "display_option": (0x4759FF, "H"),
    "horizon_enabled": (0x458C2C, "i"), "depth_enabled": (0x47651C, "I"), "zbuffer_present": (0x476504, "I"),
    "object_ptr": (0x476774, "I"), "object_count": (0x476778, "i"), "object_initialized": (0x47677C, "i"),
    "road_ptr": (0x476570, "I"), "road_count": (0x476574, "i"), "road_initialized": (0x476578, "i"),
    "road_index_ptr": (0x476584, "I"), "road_index_count": (0x476588, "i"),
    "road_flags_ptr": (0x47658C, "I"), "road_flags_count": (0x476590, "i"),
    "road_first": (0x476594, "i"), "road_stop": (0x476598, "i"),
    "fog_enabled": (0x476540, "I"), "fog_mode": (0x476548, "b"),
    "fog_start": (0x476549, "f"), "fog_end": (0x47654D, "f"),
}
# Relative CALL bytes are unchanged by PE base relocation.
CODE_FINGERPRINTS = ((0x197B, bytes.fromhex("e813580000")),
                     (0x1980, bytes.fromhex("e8ecbb0100")),
                     (0x7769, bytes.fromhex("e8dab6ffff")),
                     (0x1D618, bytes.fromhex("e88f2d0000")))
TABLE_IDENTITY = ("object_ptr", "object_count", "object_initialized", "road_ptr", "road_count",
                  "road_initialized", "road_flags_ptr", "road_flags_count", "road_index_ptr", "road_index_count",
                  "road_first", "road_stop", "native_3d", "camera_choice", "xmin", "xmax", "zmin", "zmax")
TABLE_IDENTITY += ("cells_x", "cells_z", "extent_x", "extent_z", "cell_x", "cell_z",
                   "horizon_enabled", "depth_enabled", "display_option")


def assert_plain_path(path: Path) -> None:
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Zichtmetingpad bevat een link/reparse point.")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("Zichtmetingpad bevat een hardlink.")


def read_json(path: Path) -> dict:
    assert_plain_path(path)
    with path.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("Zichtmetingdescriptor is te groot.")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Dubbele sleutel in zichtmetingdescriptor.")
            value[key] = item
        return value

    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Zichtmetingdescriptor moet een object zijn.")
    return value


def same_path(first: str | Path, second: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def context(root: Path, run_name: str) -> dict:
    if not isinstance(run_name, str) or not RUN_NAME.fullmatch(run_name):
        raise ValueError("Zichtmeting vereist een exacte bestaande deel-I-proefnaam.")
    root = root.absolute()
    trial = root / "local/experiments/a2racer1" / run_name / "game"
    report = root / "reports/runtime/a2racer1" / run_name
    prepared_path = report / "prepared.json"
    for path in (root, trial, report, prepared_path):
        assert_plain_path(path)
    prepared = read_json(prepared_path)
    if prepared.get("game") != "a2racer1" or prepared.get("run_name") != run_name:
        raise ValueError("Descriptor hoort bij een andere proef.")
    for key, expected in (("trial_path", trial), ("working_directory", trial), ("report_path", report)):
        declared = prepared.get(key)
        if not isinstance(declared, str) or not Path(declared).is_absolute() or not same_path(declared, expected):
            raise ValueError("Descriptor verwijst naar een ander proefpad.")
    race = trial / "A2SPEL.DAT"
    assert_plain_path(race)
    with race.open("rb") as stream:
        data = stream.read(EXPECTED_SIZE + 1)
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != EXPECTED_SIZE or digest not in BINARY_PROFILES:
        raise ValueError("Onbekende racebinary voor zichtmeting.")
    if (data[:2] != b"MZ" or struct.unpack_from("<I", data, 0x3C)[0] + 84 > len(data)):
        raise ValueError("Racebinary heeft geen geldig PE-header.")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if (data[pe:pe + 4] != b"PE\0\0" or struct.unpack_from("<H", data, pe + 4)[0] != 0x14C
            or struct.unpack_from("<H", data, pe + 24)[0] != 0x10B
            or struct.unpack_from("<I", data, pe + 52)[0] != BASE
            or struct.unpack_from("<I", data, pe + 80)[0] != IMAGE_SIZE):
        raise ValueError("Afwijkend PE32-racelayout.")
    started = prepared_path.stat().st_mtime
    summary_path = report / "summary.json"
    if summary_path.exists():
        summary = read_json(summary_path)
        if summary.get("game") != "a2racer1" or summary.get("run_name") != run_name:
            raise ValueError("Samenvatting hoort bij een andere proef.")
        text = summary.get("started_utc")
        if not isinstance(text, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?Z", text):
            raise ValueError("Ongeldige starttijd in proefsamenvatting.")
        started = max(started, datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    return {"run_name": run_name, "race": race, "report": report, "sha256": digest,
            "profile": BINARY_PROFILES[digest], "after_filetime": int((started - 1) * 10_000_000) + 116444736000000000,
            "header": data[:pe + 84]}


def validate_identity(identity: dict, target: dict) -> None:
    if (not isinstance(identity, dict) or identity.get("exited") is not False
            or type(identity.get("pid")) is not int or not 1 <= identity["pid"] <= 0xFFFFFFFF
            or not isinstance(identity.get("image_path"), str) or not Path(identity["image_path"]).is_absolute()
            or not same_path(identity["image_path"], target["race"])
            or type(identity.get("creation_filetime")) is not int
            or identity["creation_filetime"] < target["after_filetime"]):
        raise ValueError("Proces hoort niet bij deze bestaande raceproef.")


def validate_same_process(current: dict, original: dict, target: dict, allow_exit: bool = False) -> bool:
    if not isinstance(current, dict) or type(current.get("exited")) is not bool:
        raise ValueError("Ongeldige processtatus tijdens zichtmeting.")
    validate_identity({**current, "exited": False} if allow_exit else current, target)
    if current["pid"] != original["pid"] or current["creation_filetime"] != original["creation_filetime"]:
        raise ValueError("Procesidentiteit gewijzigd tijdens zichtmeting.")
    return current["exited"]


def validate_memory_image(reader, target: dict, base: int, size: int) -> None:
    if type(base) is not int or base < 0x10000 or base + IMAGE_SIZE > 0x100000000 or size != IMAGE_SIZE:
        raise ValueError("Afwijkend geladen PE32-racemodule.")
    live = reader.read(base, len(target["header"]))
    # ImageBase in the PE header remains the preferred base after relocation.
    if live != target["header"]:
        raise ValueError("Geladen raceheader wijkt af van de gepinde binary.")
    for rva, expected in CODE_FINGERPRINTS:
        if reader.read(base + rva, len(expected)) != expected:
            raise ValueError("Afwijkende codefingerprint voor zichtmeting.")


def read_fields(reader, base: int) -> dict:
    result = {}
    for name, (va, kind) in FIELDS.items():
        size = struct.calcsize("<" + kind)
        result[name] = struct.unpack("<" + kind, reader.read(base + va - BASE, size))[0]
    return result


def table_bytes(reader, pointer: int, count: int, stride: int) -> bytes:
    if type(count) is not int or not 0 <= count <= MAX_ELEMENTS:
        raise ValueError("Aantal overschrijdt de begrensde zichtmeting.")
    if not count:
        return b""
    size = count * stride
    if type(pointer) is not int or pointer < 0x10000 or pointer + size > 0x100000000:
        raise ValueError("Ongeldig PE32-arraybereik voor zichtmeting.")
    return reader.read(pointer, size)


def object_counts(records: bytes, base: int) -> dict:
    if len(records) % OBJECT_STRIDE:
        raise ValueError("Onvolledige objectrecords.")
    counts = {"total": len(records) // OBJECT_STRIDE, "active": 0, "visible_flag": 0,
              "eligible_flags": 0, "static_active": 0, "static_eligible_flags": 0,
              "sky_active": 0, "sky_eligible_flags": 0}
    for offset in range(0, len(records), OBJECT_STRIDE):
        active, visible = records[offset + 52] != 0, records[offset + 53] != 0
        callback = struct.unpack_from("<I", records, offset + 32)[0]
        static_object = callback == base + STATIC_CALLBACK_RVA
        counts["active"] += active
        counts["visible_flag"] += visible
        counts["eligible_flags"] += active and visible
        counts["static_active"] += active and static_object
        counts["static_eligible_flags"] += active and visible and static_object
        sky_object = callback == base + SKY_CALLBACK_RVA
        counts["sky_active"] += active and sky_object
        counts["sky_eligible_flags"] += active and visible and sky_object
        # Execute-handle offset is not assumed here; flag count is sufficient.
    return counts


def road_counts(flags: bytes, records: bytes, first: int, stop: int) -> dict:
    if len(flags) % 4 or len(records) % ROAD_STRIDE:
        raise ValueError("Onvolledige roadarrays.")
    values = [value[0] for value in struct.iter_unpack("<I", flags)]
    count = len(values)
    if len(records) // ROAD_STRIDE != count or not 0 <= first <= stop <= count:
        raise ValueError("Roadcount of Execute-interval wijkt af.")
    selected = [i for i, value in enumerate(values) if value != 0]
    admitted = [i for i in selected if first <= i < stop]
    handles = sum(struct.unpack_from("<I", records, i * ROAD_STRIDE + 52)[0] != 0 for i in admitted)
    return {"total": count, "selected_flags_total": len(selected), "first": first, "stop_exclusive": stop,
            "admitted_flags": len(admitted), "admitted_with_handle": handles,
            "first_selected": min(selected) if selected else None, "last_selected": max(selected) if selected else None}


def sample(reader, base: int) -> dict:
    before = read_fields(reader, base)
    result = {"utc": datetime.now(timezone.utc).isoformat(), "globals": before,
              "atomic": False, "counter_kind": "flags-and-handles-not-drawcalls"}
    if before["native_3d"] != 1:
        result["status"] = "native-3d-not-active"
        return result
    if not before["object_initialized"] or not before["road_initialized"]:
        result["status"] = "tables-not-initialized"
        return result
    if not (before["road_count"] == before["road_flags_count"] == before["road_index_count"]):
        raise ValueError("Roadarraycapaciteiten zijn niet gelijk.")
    objects = table_bytes(reader, before["object_ptr"], before["object_count"], OBJECT_STRIDE)
    flags = table_bytes(reader, before["road_flags_ptr"], before["road_flags_count"], 4)
    roads = table_bytes(reader, before["road_ptr"], before["road_count"], ROAD_STRIDE)
    after = read_fields(reader, base)
    if any(before[key] != after[key] for key in TABLE_IDENTITY):
        result["status"] = "changed-during-read"
        return result
    result.update(status="sampled", objects=object_counts(objects, base),
                  roads=road_counts(flags, roads, before["road_first"], before["road_stop"]))
    return result


def json_line(value: dict) -> str:
    # Bad in-flight float values are explicit nulls, never invalid JSON NaN.
    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):
            return None
        if isinstance(item, dict):
            return {key: finite(value) for key, value in item.items()}
        if isinstance(item, list):
            return [finite(value) for value in item]
        return item
    return json.dumps(finite(value), ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"


def observe(target: dict, pid: int, seconds: int, interval: float, process_factory=None) -> dict:
    if (type(pid) is not int or not 1 <= pid <= 0xFFFFFFFF
            or type(seconds) is not int or not 1 <= seconds <= 300
            or type(interval) not in (int, float) or not 0.5 <= interval <= 5):
        raise ValueError("Zichtmeting vereist PID>0, 1–300 seconden en interval 0,5–5 seconden.")
    if process_factory is None:
        from tools.process_memory import ReadOnlyProcess
        process_factory = ReadOnlyProcess
    samples = 0
    with process_factory(pid) as process:
        identity = process.identity()
        validate_identity(identity, target)
        if identity["pid"] != pid:
            raise ValueError("Procesidentiteit hoort niet bij de gevraagde PID.")
        module = process.module(target["race"])
        validate_memory_image(process, target, module["base"], module["size"])
        validate_same_process(process.identity(), identity, target)
        path = target["report"] / ("visibility-" + uuid.uuid4().hex + ".jsonl")
        assert_plain_path(path)
        with path.open("x", encoding="utf-8") as stream:
            header = {"type": "header", "run_name": target["run_name"], "race_sha256": target["sha256"],
                      "profile": target["profile"], "pid": pid, "creation_filetime": identity["creation_filetime"],
                      "image_base": module["base"], "read_only": True, "memory_code_fingerprints": len(CODE_FINGERPRINTS),
                      "max_elements_policy": MAX_ELEMENTS, "atomic": False, "drawcalls_measured": False}
            line = json_line(header)
            stream.write(line)
            total_bytes = len(line.encode("utf-8"))
            deadline = time.monotonic() + seconds
            stop_reason = "duration-complete"
            while time.monotonic() < deadline:
                current = process.identity()
                exited = validate_same_process(current, identity, target, allow_exit=True)
                if not exited:
                    try:
                        record = sample(process, module["base"])
                    except (OSError, ValueError, RuntimeError) as error:
                        record = {"utc": datetime.now(timezone.utc).isoformat(), "status": "read-failed", "reason": str(error)}
                    after = process.identity()
                    exited = validate_same_process(after, identity, target, allow_exit=True)
                if exited:
                    # A finished process invalidates any concurrent sample.
                    record = {"utc": datetime.now(timezone.utc).isoformat(), "status": "process-exited"}
                    stop_reason = "process-exited"
                line = json_line(record)
                if total_bytes + len(line.encode("utf-8")) > MAX_LOG_BYTES:
                    stop_reason = "log-cap"
                    break
                stream.write(line); stream.flush()
                total_bytes += len(line.encode("utf-8")); samples += 1
                if exited:
                    break
                time.sleep(min(interval, max(0, deadline - time.monotonic())))
    return {"path": str(path), "samples": samples, "read_only": True,
            "drawcalls_measured": False, "stop_reason": stop_reason}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        target = context(ROOT, args.run_name)
        if args.check_only:
            result = {"run_name": target["run_name"], "race_sha256": target["sha256"], "profile": target["profile"],
                      "field_count": len(FIELDS), "process_opened": False}
        else:
            result = observe(target, args.pid, args.seconds, args.interval)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Zichtmeting: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
