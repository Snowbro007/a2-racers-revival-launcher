"""Read only the own HD-HUD counters of one verified existing A2-I trial.

No PID/address input, process enumeration, launch, writes, UI or debugger. The
recorded race identity, current pinned composition, loaded header/helper/hooks
are checked before the bounded counter read. Counters do not prove sharpness.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import hud_hd_fix as fix, hud_hd_native as native, hud_hd_pe as pe
from tools.visibility_monitor import assert_plain_path, same_path

RUN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
MAX_JSON_BYTES = 8 * 1024**2
MAX_EVENTS_BYTES = 16 * 1024**2
DOTNET_FILETIME_DELTA = 504911232000000000
FIELDS = ("ready", "disabled", "queue_count", "viewport_added", "execute_locked",
          "last_hr", "scene_open", "draw_count", "failure_count", "queue_overflow",
          "last_stage", "asset_index", "failure_stage", "failure_asset_index")
FLAG_FIELDS = ("ready", "disabled", "viewport_added", "execute_locked", "scene_open", "queue_overflow")
STATE_READ_BYTES = max(native.STATE[name] + 4 for name in FIELDS)


def _json(raw: bytes) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Dubbele sleutel in HUD-statusdescriptor.")
            value[key] = item
        return value
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)
    if type(value) is not dict:
        raise ValueError("HUD-statusdescriptor moet een JSON-object zijn.")
    return value


def _bounded_read(path: Path, limit: int) -> bytes:
    assert_plain_path(path)
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("HUD-statusbestand overschrijdt de leeslimiet.")
    return raw


def _declared_path(value, expected: Path) -> None:
    if type(value) is not str or not Path(value).is_absolute() or not same_path(value, expected):
        raise ValueError("HUD-statusdescriptor verwijst naar een ander proefpad.")


def derive_composition(workspace: Path, input_sha256: str,
                       profile: str = "hd-overlay-v1") -> tuple[bytes, dict]:
    """Reconstruct only a pinned existing variant plus the current pinned art.

    Reads the fixed original source and own exports; composes in Python memory.
    Does not trust a report-supplied source, output hash, address or byte payload.
    """
    if profile not in fix.PROFILES[1:]:
        raise ValueError("HUD-status vereist een gepind interface- of cockpitprofiel.")
    if type(input_sha256) is not str or input_sha256 not in pe.KNOWN_VARIANTS:
        raise ValueError("HUD-status vereist een bekende inputvariant.")
    variant = pe.KNOWN_VARIANTS[input_sha256]
    source = workspace / "local/games/a2racer1" / fix.NAME
    data = _bounded_read(source, fix.SOURCE_BYTES)
    if len(data) != fix.SOURCE_BYTES or hashlib.sha256(data).hexdigest() != fix.SOURCE_SHA256:
        raise ValueError("De gepinde originele HUD-bron wijkt af.")
    from tools import race_focus_fix, render_distance_fix, widescreen_fix, object_distance_fix
    if variant.focus_recovery:
        data = race_focus_fix.checked_patch(data, variant.render_distance)
    elif variant.render_distance != "original":
        data = render_distance_fix.checked_patch(data, variant.render_distance)
    if variant.camera != "original":
        data = widescreen_fix.checked_patch(data, variant.camera,
                                           render_distance_profile=variant.render_distance,
                                           race_focus_recovery=variant.focus_recovery)
    if variant.object_distance != "original":
        data = object_distance_fix.checked_patch(data, variant.object_distance,
                                                render_distance_profile=variant.render_distance,
                                                race_focus_recovery=variant.focus_recovery,
                                                camera_profile=variant.camera)
    if hashlib.sha256(data).hexdigest() != input_sha256:
        raise ValueError("HUD-status kon de bekende racevariant niet exact afleiden.")
    assets = fix.load_assets(workspace) if profile == "hd-overlay-v1" else fix.load_profile_assets(workspace, profile)
    return (fix.checked_patch(data, assets, profile=profile) if profile in ("hd-cockpit-v2", "hd-cockpit-v3")
            else fix.checked_patch(data, assets))


def _image_contract(data: bytes, hud: dict, *, derived_state_offsets: dict | None = None) -> dict:
    """Read the already independently derived PE; never follow arbitrary RVAs."""
    if (len(data) < 0x400 or data[:2] != b"MZ"):
        raise ValueError("HUD-status mist een PE32-uitvoer.")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if (offset < 0x40 or offset + 248 > 0x400 or data[offset:offset + 4] != b"PE\0\0"
            or struct.unpack_from("<H", data, offset + 4)[0] != 0x14C
            or struct.unpack_from("<H", data, offset + 20)[0] != 224
            or struct.unpack_from("<H", data, offset + 24)[0] != 0x10B
            or struct.unpack_from("<I", data, offset + 52)[0] != pe.IMAGE_BASE):
        raise ValueError("HUD-status kreeg een afwijkende PE32-header.")
    count = struct.unpack_from("<H", data, offset + 6)[0]
    image_size = struct.unpack_from("<I", data, offset + 80)[0]
    headers_size = struct.unpack_from("<I", data, offset + 84)[0]
    table = offset + 248
    if not 1 <= count <= 16 or table + count * 40 > headers_size or headers_size != 0x400:
        raise ValueError("HUD-status kreeg afwijkende sectieheaders.")
    sections = []
    for index in range(count):
        name, virtual_size, rva, raw_size, raw, _, _, _, _, flags = struct.unpack_from(
            "<8s6I2HI", data, table + index * 40)
        if rva + max(raw_size, virtual_size) > image_size or raw + raw_size > len(data):
            raise ValueError("HUD-statussectie valt buiten de afgeleide image.")
        sections.append((name.rstrip(b"\0"), rva, raw_size, raw, virtual_size, flags))
    def mapped(va: int, size: int) -> bytes:
        if type(va) is not int or type(size) is not int or size < 1:
            raise ValueError("Ongeldig afgeleid HUD-codebereik.")
        rva = va - pe.IMAGE_BASE
        matches = [(raw + rva - start) for _, start, length, raw, _, _ in sections
                   if raw and start <= rva and rva + size <= start + length]
        if len(matches) != 1:
            raise ValueError("HUD-codebereik heeft geen unieke afgeleide sectie.")
        return data[matches[0]:matches[0] + size]
    state_va = hud["state_va"]
    # Additional cache fields may only come from independently rebuilt own code.
    # They are never read from the process; the diagnostic DWORDs stay unchanged.
    expected_offsets = native.STATE if derived_state_offsets is None else derived_state_offsets
    if (type(expected_offsets) is not dict or
            any(expected_offsets.get(name) != offset for name, offset in native.STATE.items())):
        raise ValueError("Afgeleid HUD-statecontract mist de vaste diagnostische velden.")
    backend = {"hd-overlay-v1": native.BACKEND, "hd-cockpit-v1": fix.CACHED_BACKEND,
               "hd-cockpit-v2": fix.CACHED_BACKEND, "hd-cockpit-v3": fix.CACHED_BACKEND}.get(hud.get("profile"))
    state_sections = [section for section in sections if section[0] == pe.STATE_NAME]
    code_sections = [section for section in sections if section[0] == pe.CODE_NAME]
    if (len(state_sections) != 1 or len(code_sections) != 1
            or state_va != pe.IMAGE_BASE + state_sections[0][1]
            or hud["code_va"] != pe.IMAGE_BASE + code_sections[0][1]
            or hud["state_bytes"] < STATE_READ_BYTES
            or hud["state_bytes"] > state_sections[0][4]
            or state_sections[0][5] != pe.STATE_FLAGS or code_sections[0][5] != pe.CODE_FLAGS
            or hud["diagnostic_state_offsets"] != expected_offsets
            or backend is None or hud.get("render_backend") != backend
            or hud.get("diagnostic_stages") != native.STAGES):
        raise ValueError("Afgeleid HUD-statecontract wijkt af van de huidige helper.")
    fingerprints = [(hud["code_va"] - pe.IMAGE_BASE, mapped(hud["code_va"], hud["helper_bytes"]))]
    for hook in hud["hooks"]:
        expected = bytes.fromhex(hook["after"])
        if mapped(hook["va"], len(expected)) != expected:
            raise ValueError("Afgeleide HUD-hook komt niet overeen met de uitvoer.")
        fingerprints.append((hook["va"] - pe.IMAGE_BASE, expected))
    return {"header": data[:headers_size], "image_size": image_size,
            "state_rva": state_va - pe.IMAGE_BASE, "fingerprints": tuple(fingerprints)}


def trial_context(workspace: Path, trial: str) -> dict:
    if type(trial) is not str or not RUN_NAME.fullmatch(trial):
        raise ValueError("HUD-status vereist een exacte bestaande deel-I-proefnaam.")
    workspace = Path(workspace).absolute()
    game = workspace / "local/experiments/a2racer1" / trial / "game"
    report = workspace / "reports/runtime/a2racer1" / trial
    prepared_path = report / "prepared.json"
    prepared = _json(_bounded_read(prepared_path, MAX_JSON_BYTES))
    if (prepared.get("game") != "a2racer1" or prepared.get("run_name") != trial
            or prepared.get("hud_profile") not in fix.PROFILES[1:]):
        raise ValueError("HUD-statusdescriptor hoort niet bij een HD-interfaceproef.")
    for key, expected in (("trial_path", game), ("working_directory", game), ("report_path", report),
                          ("source_path", workspace / "local/games/a2racer1")):
        _declared_path(prepared.get(key), expected)
    fixes = prepared.get("binary_fixes")
    if type(fixes) is not list:
        raise ValueError("HUD-status mist de patchbeschrijving.")
    plans = [plan for plan in fixes if type(plan) is dict and plan.get("path") == fix.NAME]
    if len(plans) != 1:
        raise ValueError("HUD-status vereist precies één racepatchbeschrijving.")
    plan = plans[0]
    hud = plan.get("hud_patch")
    profile = prepared["hud_profile"]
    if (plan.get("hud_profile") != profile or type(hud) is not dict
            or plan.get("before_sha256") != fix.SOURCE_SHA256):
        raise ValueError("HUD-status mist de gepinde HUD-patch.")
    _declared_path(plan.get("source_path"), workspace / "local/games/a2racer1" / fix.NAME)
    expected, derived_hud = (derive_composition(workspace, hud.get("input_sha256"))
                             if profile == "hd-overlay-v1" else
                             derive_composition(workspace, hud.get("input_sha256"), profile))
    digest = hashlib.sha256(expected).hexdigest()
    if hud != derived_hud or plan.get("after_sha256") != digest:
        raise ValueError("HUD-statusmetadata wijkt af van de huidige gepinde compositie.")
    race = game / fix.NAME
    data = _bounded_read(race, len(expected))
    if data != expected:
        raise ValueError("HUD-proefbinary wijkt af van de huidige gepinde compositie.")
    contract = _image_contract(expected, derived_hud,
                               derived_state_offsets=derived_hud["diagnostic_state_offsets"])
    return {"trial": trial, "race": race, "report": report, "sha256": digest,
            "hud": derived_hud, "prepared_mtime": prepared_path.stat().st_mtime, **contract}


def _recorded_identity(value, context: dict) -> dict | None:
    if type(value) is not dict or type(value.get("path")) is not str:
        return None
    if not same_path(value["path"], context["race"]):
        return None
    _declared_path(value.get("path"), context["race"])
    pid, ticks = value.get("pid"), value.get("start_ticks")
    if (type(pid) is not int or not 1 <= pid <= 0xFFFFFFFF or type(ticks) is not int
            or not DOTNET_FILETIME_DELTA < ticks < 0x7FFFFFFFFFFFFFFF):
        raise ValueError("Ongeldige opgenomen race-identiteit voor HUD-status.")
    creation = ticks - DOTNET_FILETIME_DELTA
    minimum = int((context["prepared_mtime"] - 1) * 10_000_000) + 116444736000000000
    if creation < minimum:
        raise ValueError("Opgenomen raceproces dateert van vóór deze voorbereiding.")
    return {"pid": pid, "image_path": str(context["race"]),
            "creation_filetime": creation, "exited": False}


def recorded_process(context: dict) -> dict:
    """Only runner-recorded race identities; never discover or accept a PID."""
    candidates = {}
    summary_path = context["report"] / "summary.json"
    if summary_path.exists():
        summary = _json(_bounded_read(summary_path, MAX_JSON_BYTES))
        if summary.get("game") != "a2racer1" or summary.get("run_name") != context["trial"]:
            raise ValueError("HUD-statussamenvatting hoort bij een andere proef.")
        entries = summary.get("processes")
        if type(entries) is not list or len(entries) > 64:
            raise ValueError("HUD-statussamenvatting heeft geen begrensde proceslijst.")
        for entry in entries:
            identity = _recorded_identity(entry.get("identity") if type(entry) is dict else None, context)
            if identity is not None:
                candidates[(identity["pid"], identity["creation_filetime"])] = identity
    events_path = context["report"] / "events.jsonl"
    if events_path.exists():
        raw = _bounded_read(events_path, MAX_EVENTS_BYTES)
        for line in raw.splitlines():
            if not line.strip():
                continue
            if len(line) > MAX_JSON_BYTES:
                raise ValueError("HUD-statusevent overschrijdt de leeslimiet.")
            event = _json(line)
            if event.get("type") != "process_discovered":
                continue
            value = event.get("data")
            identity = _recorded_identity(value.get("identity") if type(value) is dict else None, context)
            if identity is not None:
                candidates[(identity["pid"], identity["creation_filetime"])] = identity
    if len(candidates) != 1:
        raise ValueError("HUD-status vereist precies één opgenomen race-identiteit; start een verse proef.")
    return next(iter(candidates.values()))


def _same_process(observed: dict, expected: dict, *, allow_exit: bool = False) -> None:
    if (type(observed) is not dict or type(observed.get("exited")) is not bool
            or observed["exited"] and not allow_exit
            or type(observed.get("pid")) is not int or observed["pid"] != expected["pid"]
            or type(observed.get("creation_filetime")) is not int
            or observed["creation_filetime"] != expected["creation_filetime"]):
        raise ValueError("Procesidentiteit wijzigde of is afgesloten tijdens HUD-statuscontrole.")
    _declared_path(observed.get("image_path"), Path(expected["image_path"]))


def decode_state(raw: bytes, asset_names: tuple[str, ...] | None = None) -> dict:
    if type(raw) is not bytes or len(raw) != STATE_READ_BYTES:
        raise ValueError("Onvolledige eigen HUD-state.")
    counters = {name: struct.unpack_from("<I", raw, native.STATE[name])[0] for name in FIELDS}
    if any(counters[name] not in (0, 1) for name in FLAG_FIELDS) or counters["queue_count"] > native.MAX_COMMANDS:
        raise ValueError("Eigen HUD-state valt buiten het bewezen tellercontract.")
    if asset_names is None:
        asset_names = tuple(asset.name for asset in fix.ASSETS)
    if (type(asset_names) is not tuple or not 1 <= len(asset_names) <= native.MAX_ASSETS
            or any(type(name) is not str or not 1 <= len(name) <= 128 for name in asset_names)):
        raise ValueError("HUD-status heeft geen begrensde afgeleide assetnamen.")
    stages = {value: name for name, value in native.STAGES.items()}
    if counters["last_stage"] not in stages or counters["failure_stage"] not in stages:
        raise ValueError("Eigen HUD-stage komt niet voor in het huidige gepinde contract.")
    for field in ("asset_index", "failure_asset_index"):
        if counters[field] != native.NO_ASSET and counters[field] >= len(asset_names):
            raise ValueError("Eigen HUD-assetindex valt buiten de huidige gepinde assets.")
    stage_field, asset_field = (("failure_stage", "failure_asset_index") if counters["disabled"]
                                else ("last_stage", "asset_index"))
    asset_index = counters[asset_field]
    diagnostics = {"stage": stages[counters[stage_field]], "stage_id": counters[stage_field],
                   "source": "latched-failure" if counters["disabled"] else "latest-operation",
                   "asset_index": None if asset_index == native.NO_ASSET else asset_index,
                   "asset_name": None if asset_index == native.NO_ASSET else asset_names[asset_index],
                   "last_stage": stages[counters["last_stage"]],
                   "failure_stage": stages[counters["failure_stage"]]}
    hr = counters["last_hr"]
    counters.update(last_hr_hex=f"0x{hr:08X}", last_hr_signed=hr - 0x100000000 if hr & 0x80000000 else hr)
    if counters["disabled"]:
        status = "disabled-after-error"
    elif counters["ready"] and counters["draw_count"]:
        status = "hd-draw-observed"
    elif counters["ready"]:
        status = "ready-without-observed-draw"
    else:
        status = "not-ready"
    return {"status": status, "counters": counters, "diagnostics": diagnostics, "atomic": False,
            "hd_draw_observed": counters["draw_count"] != 0,
            "visual_quality_verified": False, "focus_recovery_verified": False}


def collect_status(workspace: Path, trial: str, *, process_factory=None) -> dict:
    """One bounded read; closes its read-only handle on success or rejection."""
    context = trial_context(workspace, trial)
    expected = recorded_process(context)
    if process_factory is None:
        from tools.process_memory import ReadOnlyProcess
        process_factory = ReadOnlyProcess
    result = {"trial": trial, "race_sha256": context["sha256"], "pid": expected["pid"],
              "creation_filetime": expected["creation_filetime"], "read_only": True,
              "render_backend": context["hud"]["render_backend"],
              "utc": datetime.now(timezone.utc).isoformat()}
    with process_factory(expected["pid"]) as process:
        identity = process.identity()
        _same_process(identity, expected, allow_exit=True)
        if identity["exited"]:
            return {**result, "status": "process-exited", "hd_draw_observed": None,
                    "visual_quality_verified": False, "focus_recovery_verified": False}
        module = process.module(context["race"])
        base, size = module.get("base"), module.get("size")
        if (type(base) is not int or type(size) is not int or base < 0x10000
                or size != context["image_size"] or base + size > 0x100000000):
            raise ValueError("Geladen HUD-racemodule heeft een afwijkend PE32-bereik.")
        if process.read(base, len(context["header"])) != context["header"]:
            raise ValueError("Geladen HUD-header wijkt af van de afgeleide proefbinary.")
        for rva, code in context["fingerprints"]:
            if process.read(base + rva, len(code)) != code:
                raise ValueError("Geladen eigen HUD-helper/hook wijkt af.")
        _same_process(process.identity(), expected)
        raw = process.read(base + context["state_rva"], STATE_READ_BYTES)
        _same_process(process.identity(), expected)
        asset_names = tuple(asset["name"] for asset in context["hud"]["assets"])
        result.update(decode_state(raw, asset_names), module_verified=True, helper_and_hooks_verified=True,
                      current_asset_composition_verified=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", required=True, help="Exacte bestaande proefnaam; geen pad of PID.")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.check_only:
            context = trial_context(ROOT, args.trial)
            result = {"trial": args.trial, "race_sha256": context["sha256"], "process_opened": False,
                      "render_backend": context["hud"]["render_backend"],
                      "current_asset_composition_verified": True, "read_only": True}
        else:
            result = collect_status(ROOT, args.trial)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"HUD-status kon niet worden gelezen: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
