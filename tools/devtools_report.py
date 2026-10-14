"""Read-only, bounded viewer for existing A2 runtime reports.

No executable, process, game tree or path named inside a report is opened.
Timestamps and source line numbers are observations, not a combined clock.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from itertools import islice
import json
import os
from pathlib import Path
import re
import stat
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))
from tools.trial_manifest import validate_ancestors  # noqa: E402

GAMES = ("a2racer1", "a2racer2")
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_LOG_BYTES = 256 * 1024
MAX_RECORDS = 2000
MAX_FILES = 64
MAX_OUTPUT_BYTES = 1536 * 1024
MAX_JSON_DEPTH = 64
CONFIG_FIELDS = (
    "stage", "profile", "graphics_wrapper", "graphics_wrapper_version",
    "graphics_diagnostic", "display_profile", "race_fps_limit", "map_mode",
    "render_distance_profile", "race_focus_recovery", "native_graphics",
    "camera_profile", "texture_profile", "object_distance_profile", "widescreen_complete",
    "requested_native_graphics", "native_dashboard", "native_horizon",
    "keep_native_options", "native_options", "hide_watermark",
    "movie_display_mode", "skip_intro", "disable_movies", "omit_native_intro",
    "any_key_welcome", "pump_launcher_messages", "config_changes",
)
SUMMARY_FIELDS = (
    "stage", "duration_seconds", "started_utc", "stop_at_end", "stop_reason",
    "fatal_error", "gameplay_status", "remaining_processes", "crash_events",
    "diagnostics", "limitations", "debug_requested", "intro_skipped",
)
FIX_FIELDS = ("path", "purpose", "purposes", "before_sha256", "after_sha256",
              "runtime_verified", "render_distance_profile", "limitation",
              "camera_profile", "camera_patch", "profile", "texture_evidence",
              "object_distance_profile", "object_distance_patch")
DEFAULT_LIMITATIONS = [
    "Alleen opgeslagen rapporten; geen actuele proces- of gamecontrole.",
    "Geladen modules bewijzen geen API-gebruik, zichtbaar beeld of speelbaarheid.",
    "Bronnen hebben hun eigen volgorde; ontbrekende timestamps worden niet ingevuld.",
]


def validate_run_name(name: str) -> None:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,90}", name):
        raise ValueError("Ongeldige proefnaam: gebruik 1-90 letters, cijfers, _ of -.")
    if name.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)],
                        *[f"LPT{i}" for i in range(10)]}:
        raise ValueError("Gereserveerde Windows-proefnaam.")


def report_root(root: Path | str) -> Path:
    workspace = Path(root).absolute()
    validate_ancestors(workspace)
    if not workspace.is_dir():
        raise ValueError("Workspace bestaat niet als echte map.")
    reports = workspace / "reports" / "runtime"
    validate_ancestors(reports)
    return reports


def run_path(root: Path | str, game: str, run: str) -> Path:
    if game not in GAMES:
        raise ValueError("Onbekende game.")
    validate_run_name(run)
    path = report_root(root) / game / run
    validate_ancestors(path)
    if not path.is_dir():
        raise ValueError("Proefrapport bestaat niet als echte map.")
    return path


def _warn(warnings: list[str], message: str) -> None:
    if message not in warnings and len(warnings) < MAX_RECORDS:
        warnings.append(message)


def _safe_file(path: Path, warnings: list[str], source: str) -> bool:
    try:
        validate_ancestors(path)
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("Geen regulier bestand met precies één bestandslink.")
        return True
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as exc:
        _warn(warnings, f"{source}: niet gelezen ({exc}).")
        return False


def _read(path: Path, maximum: int, warnings: list[str], source: str,
          tail: bool = False) -> tuple[bytes | None, int]:
    if not _safe_file(path, warnings, source):
        return None, 0
    try:
        # Recheck after opening, before reading: no links or non-regular inputs.
        with path.open("rb") as handle:
            validate_ancestors(path)
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("Geen regulier bestand met precies één bestandslink.")
            start = max(0, metadata.st_size - maximum) if tail else 0
            marker = handle.read(2) if tail else b""
            if marker in (b"\xff\xfe", b"\xfe\xff") and start:
                start -= start % 2
            handle.seek(start)
            if start:
                handle.seek(start)
            data = handle.read(maximum + 1)
            if metadata.st_size > maximum or len(data) > maximum:
                _warn(warnings, f"{source}: afgekapt bij {maximum} bytes.")
                if not tail:
                    return None, 0
                data = data[:maximum]
            if start and marker in (b"\xff\xfe", b"\xfe\xff"):
                data = marker + data
            after = os.fstat(handle.fileno())
            if (metadata.st_size, metadata.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                _warn(warnings, f"{source}: veranderde tijdens lezen; momentopname kan onvolledig zijn.")
            return data, start
    except (OSError, ValueError) as exc:
        _warn(warnings, f"{source}: niet gelezen ({exc}).")
        return None, 0


def _decode(data: bytes, warnings: list[str], source: str) -> str:
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16")
        return data.decode("utf-8-sig")
    except UnicodeError:
        _warn(warnings, f"{source}: tekstcodering onbekend/beschadigd; vervangtekens gebruikt.")
        return data.decode("utf-8", errors="replace")


def _reject_constant(value: str) -> None:
    raise ValueError(f"Niet-eindig JSON-getal: {value}")


def _loads(text: str) -> object:
    # Reject excessive nesting before entering the JSON decoder (its recursion
    # limit can be changed by unrelated host code). Quoted braces do not count.
    depth = 0
    quoted = escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError(f"JSON dieper dan {MAX_JSON_DEPTH} niveaus")
        elif character in "]}":
            depth -= 1
    return json.loads(text, parse_constant=_reject_constant)


def _json(path: Path, warnings: list[str], source: str) -> object | None:
    data, _ = _read(path, MAX_JSON_BYTES, warnings, source)
    if data is None:
        return None
    try:
        return _loads(_decode(data, warnings, source))
    except (ValueError, RecursionError) as exc:
        _warn(warnings, f"{source}: ongeldig/onvolledig JSON ({exc}).")
        return None


def _object(path: Path, warnings: list[str], source: str) -> dict:
    value = _json(path, warnings, source)
    if value is None:
        return {}
    if not isinstance(value, dict):
        _warn(warnings, f"{source}: JSON-object verwacht.")
        return {}
    return value


def _compact(value: object, warnings: list[str], source: str) -> object:
    """Keep hostile report data from inflating the UI; mark every truncation."""
    budget = [512]
    cut = [False]

    def visit(item: object, depth: int) -> object:
        budget[0] -= 1
        if budget[0] < 0 or depth > 6:
            cut[0] = True
            return "[afgekapt]"
        if isinstance(item, str):
            if len(item) > 4096:
                cut[0] = True
                return item[:4096] + "[afgekapt]"
            return item
        if isinstance(item, list):
            if len(item) > MAX_RECORDS:
                cut[0] = True
            result = []
            for val in item[:MAX_RECORDS]:
                if budget[0] <= 0:
                    cut[0] = True
                    break
                result.append(visit(val, depth + 1))
            return result
        if isinstance(item, dict):
            result = {}
            for key, val in item.items():
                if budget[0] <= 0 or len(result) >= 64:
                    cut[0] = True
                    break
                safe_key = key[:256]
                if safe_key != key:
                    cut[0] = True
                result[safe_key] = visit(val, depth + 1)
            return result
        return item

    result = visit(value, 0)
    if cut[0]:
        _warn(warnings, f"{source}: gegevens voor weergave afgekapt; geen volledig rapport.")
    return result


def _base(path: Path, game: str, run: str, warnings: list[str],
          include_integrity: bool = True) -> tuple[dict, dict, dict]:
    summary = _object(path / "summary.json", warnings, "summary.json")
    if not summary:
        legacy = _object(path / "run-summary.json", warnings, "run-summary.json")
        if legacy:
            summary = {"started_utc": legacy.get("StartUTC"),
                       "stop_reason": legacy.get("StopReason"),
                       "gameplay_status": legacy.get("GameSuccess"), "legacy_report": True}
            _warn(warnings, "run-summary.json: oudere indeling; configuratie en binary-identiteit kunnen ontbreken.")
    prepared = _object(path / "prepared.json", warnings, "prepared.json")
    embedded = summary.get("preparation")
    if not prepared and isinstance(embedded, dict):
        prepared = embedded
    for source, data in (("summary.json", summary), ("prepared.json", prepared)):
        if "game" in data and data["game"] != game:
            _warn(warnings, f"{source}: game-identiteit wijkt af van rapportmap.")
        if "run_name" in data and data["run_name"] != run:
            _warn(warnings, f"{source}: proefnaam wijkt af van rapportmap.")
    integrity = _object(path / "integrity.json", warnings, "integrity.json") if include_integrity else {}
    if not integrity and isinstance(summary.get("integrity"), dict):
        integrity = summary["integrity"]
    return summary, prepared, integrity


def _summary(summary: dict, prepared: dict, warnings: list[str]) -> dict:
    identity = {
        "executable_path": prepared.get("executable_path"),
        "executable_sha256": prepared.get("executable_sha256"),
        "binary_fixes": [{key: fix[key] for key in FIX_FIELDS if key in fix}
                         for fix in prepared.get("binary_fixes", [])[:MAX_RECORDS]
                         if isinstance(fix, dict)] if isinstance(prepared.get("binary_fixes", []), list) else [],
    }
    result = {"binary_identity": identity,
              **{key: summary[key] for key in SUMMARY_FIELDS if key in summary}}
    if "started_utc" in result:
        result["started_utc"] = _timestamp(result["started_utc"], warnings, "summary.started_utc")
    return _compact(result, warnings, "summary")


def _configuration(summary: dict, prepared: dict, warnings: list[str]) -> dict:
    return _compact({key: prepared[key] if key in prepared else summary[key]
                     for key in CONFIG_FIELDS if key in prepared or key in summary},
                    warnings, "configuration")


def _profile(summary: dict, prepared: dict) -> str | None:
    values = [prepared.get("graphics_wrapper", summary.get("graphics_wrapper")),
              prepared.get("display_profile"), prepared.get("render_distance_profile")]
    if prepared.get("race_fps_limit") is not None:
        values.append(f"{prepared['race_fps_limit']} FPS")
    text = " / ".join(str(v)[:256] for v in values if isinstance(v, (str, int, float, bool)))
    stage = prepared.get("stage", summary.get("stage"))
    return text or (stage[:256] if isinstance(stage, str) else None)


def _timestamp(value: object, warnings: list[str], source: str) -> object:
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value) > 128:
            raise ValueError("Tijdwaarde is geen korte ISO-tijdtekst")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Tijdzone ontbreekt")
    except ValueError:
        _warn(warnings, f"{source}: ongeldige of onvolledige timestamp; ruwe waarde behouden.")
    return _compact(value, warnings, source)


def list_runs(root: Path | str, game: str | None = None) -> dict:
    if game is not None and game not in GAMES:
        raise ValueError("Onbekende game.")
    reports = report_root(root)
    warnings: list[str] = []
    runs = []
    for selected in (game,) if game else GAMES:
        directory = reports / selected
        try:
            validate_ancestors(directory)
            if not directory.exists():
                continue
            if not directory.is_dir():
                raise ValueError("Rapportlocatie is geen map.")
            entries = list(islice(directory.iterdir(), MAX_RECORDS + 1))
            if len(entries) > MAX_RECORDS:
                _warn(warnings, f"{selected}: mapinventaris afgekapt bij {MAX_RECORDS} vermeldingen.")
            entries = sorted(entries[:MAX_RECORDS], key=lambda p: p.name.casefold())
        except (OSError, ValueError) as exc:
            _warn(warnings, f"{selected}: niet gelezen ({exc}).")
            continue
        for path in entries:
            if len(runs) >= MAX_RECORDS:
                _warn(warnings, f"Proeflijst afgekapt bij {MAX_RECORDS} proeven.")
                break
            try:
                validate_run_name(path.name)
                validate_ancestors(path)
                if not path.is_dir():
                    continue
            except (ValueError, OSError) as exc:
                _warn(warnings, f"{selected}/{path.name}: overgeslagen ({exc}).")
                continue
            local_warnings: list[str] = []
            summary, prepared, _ = _base(path, selected, path.name, local_warnings, include_integrity=False)
            limitations = summary.get("limitations", [])
            if not isinstance(limitations, list):
                limitations = []
            runs.append(_compact({"game": selected, "run": path.name, "profile": _profile(summary, prepared),
                                  "created_at": _timestamp(summary.get("started_utc"), local_warnings, "started_utc"),
                                  "stop_reason": summary.get("stop_reason"),
                                  "limitations": [*DEFAULT_LIMITATIONS, *limitations, *local_warnings]},
                                 warnings, f"{selected}/{path.name}"))
    runs.sort(key=lambda r: (str(r.get("created_at") or ""), r["game"], r["run"]), reverse=True)
    if not reports.exists():
        _warn(warnings, "reports/runtime ontbreekt; er zijn nog geen opgeslagen runtimeproeven.")
    return _output_bound({"schema": 1, "runs": runs, "warnings": warnings})


def _timeline(path: Path, warnings: list[str]) -> list[dict]:
    records = []
    try:
        entries = list(islice(path.iterdir(), MAX_RECORDS + 1))
        if len(entries) > MAX_RECORDS:
            _warn(warnings, f"Rapportmapinventaris afgekapt bij {MAX_RECORDS} vermeldingen.")
        files = [p for p in entries[:MAX_RECORDS] if p.name in ("events.jsonl", "processes.jsonl")
                 or re.fullmatch(r"(?:focus|visibility)-[A-Za-z0-9_-]+\.jsonl", p.name)]
    except OSError as exc:
        _warn(warnings, f"Tijdlijn niet gelezen ({exc}).")
        return records
    for candidate in sorted(files, key=lambda p: p.name)[:MAX_FILES]:
        data, _ = _read(candidate, MAX_JSON_BYTES, warnings, candidate.name)
        if data is None:
            continue
        for number, text in enumerate(_decode(data, warnings, candidate.name).splitlines(), 1):
            if not text.strip():
                continue
            if len(records) >= MAX_RECORDS:
                _warn(warnings, f"Tijdlijn afgekapt bij {MAX_RECORDS} regels.")
                return records
            try:
                event = _loads(text)
                if not isinstance(event, dict):
                    raise ValueError("JSON-object verwacht")
            except (ValueError, RecursionError) as exc:
                _warn(warnings, f"{candidate.name}:{number}: ongeldig/onvolledig JSONL ({exc}).")
                continue
            timestamp = next((event[key] for key in ("timestamp_utc", "utc", "UTC", "time")
                              if key in event), None)
            records.append({"source": candidate.name, "line": number,
                            "time": _timestamp(timestamp, warnings, f"{candidate.name}:{number}"),
                            "event": _compact(event, warnings, f"{candidate.name}:{number}")})
    if len(files) > MAX_FILES:
        _warn(warnings, f"Tijdlijnbronnen afgekapt bij {MAX_FILES} bestanden.")
    return records


def _logs(path: Path, warnings: list[str]) -> list[dict]:
    files = []
    directory = path / "game-logs"
    stack = [(directory, 0)]
    visited = 0
    while stack and visited < MAX_FILES and len(files) <= MAX_FILES:
        current, depth = stack.pop()
        visited += 1
        try:
            validate_ancestors(current)
            if not current.is_dir():
                continue
            entries = list(islice(current.iterdir(), MAX_RECORDS + 1))
            if len(entries) > MAX_RECORDS:
                _warn(warnings, f"game-logs: mapinventaris afgekapt bij {MAX_RECORDS} vermeldingen.")
            for candidate in sorted(entries[:MAX_RECORDS], key=lambda p: p.name):
                validate_ancestors(candidate)
                if candidate.is_dir():
                    if depth < 3:
                        stack.append((candidate, depth + 1))
                    else:
                        _warn(warnings, "game-logs: logmappen dieper dan 3 niveaus overgeslagen.")
                elif candidate.suffix.lower() in (".txt", ".log"):
                    files.append((candidate, candidate.relative_to(path).as_posix()))
                    if len(files) > MAX_FILES:
                        break
        except (OSError, ValueError) as exc:
            _warn(warnings, f"game-logs: niet gelezen ({exc}).")
    if stack:
        _warn(warnings, f"game-logs: mapinventaris afgekapt bij {MAX_FILES} mappen/bestanden.")
    files.extend((path / name, name) for name in (
        "stderr.txt", "ffplay-stderr.txt", "stdout.txt", "ffplay-stdout.txt", "config.diff", "transcript.txt"))
    result = []
    quota = max(1, MAX_RECORDS // max(1, min(len(files), MAX_FILES)))
    for candidate, source in files[:MAX_FILES]:
        data, offset = _read(candidate, MAX_LOG_BYTES, warnings, source, tail=True)
        if data is None:
            continue
        # A tail does not know the original line count. Never pretend it does.
        if offset:
            _warn(warnings, f"{source}: regelnummers zijn relatief aan het gelezen einde; byte-offset {offset}.")
            marker = data[:2] if data[:2] in (b"\xff\xfe", b"\xfe\xff") else b""
            body = data[len(marker):]
            newline = b"\n\x00" if marker == b"\xff\xfe" else (b"\x00\n" if marker else b"\n")
            split = body.find(newline)
            data = marker + body[split + len(newline):] if split >= 0 else b""
        lines = _decode(data, warnings, source).splitlines()
        first = max(0, len(lines) - quota)
        if first:
            _warn(warnings, f"{source}: alleen de laatste {quota} gelezen regels getoond.")
        for number, text in enumerate(lines[first:], first + 1):
            if len(result) >= MAX_RECORDS:
                _warn(warnings, f"Logweergave afgekapt bij {MAX_RECORDS} regels.")
                return result
            result.append({"source": source, "line": number,
                           "text": _compact(text, warnings, f"{source}:{number}")})
    if len(files) > MAX_FILES:
        _warn(warnings, f"Logbronnen afgekapt bij {MAX_FILES} bestanden.")
    return result


def _modules(summary: dict, path: Path, warnings: list[str]) -> list:
    values = summary.get("modules")
    if not isinstance(values, list):
        values = _json(path / "modules.json", warnings, "modules.json")
    if not isinstance(values, list):
        return []
    result = []
    for item in values[:MAX_RECORDS]:
        if not isinstance(item, dict):
            _warn(warnings, "modules: ongeldige modulevermelding overgeslagen.")
            continue
        if isinstance(item.get("Modules"), list):
            for module in item["Modules"][:MAX_RECORDS]:
                if isinstance(module, dict):
                    result.append({"name": module.get("ModuleName"), "path": module.get("FileName"),
                                   "time": _timestamp(item.get("UTC"), warnings, "modules.UTC"),
                                   "pid": item.get("PID")})
        else:
            result.append(_compact(item, warnings, "module"))
        if len(result) >= MAX_RECORDS:
            _warn(warnings, f"Modulelijst afgekapt bij {MAX_RECORDS} vermeldingen.")
            return result[:MAX_RECORDS]
    return result


def show_run(root: Path | str, game: str, run: str, query: str | None = None) -> dict:
    path = run_path(root, game, run)
    warnings: list[str] = []
    summary, prepared, integrity = _base(path, game, run, warnings)
    if not summary:
        _warn(warnings, "Geen leesbare summary.json; proef kan nog lopen of alleen voorbereid zijn.")
    result = {"schema": 1, "game": game, "run": run,
              "summary": _summary(summary, prepared, warnings),
              "configuration": _configuration(summary, prepared, warnings),
              "integrity": _compact(integrity, warnings, "integrity"),
              "modules": _modules(summary, path, warnings),
              "timeline": _timeline(path, warnings), "logs": _logs(path, warnings),
              "warnings": warnings,
              "limits": {"json_bytes": MAX_JSON_BYTES, "log_tail_bytes": MAX_LOG_BYTES,
                         "records_per_collection": MAX_RECORDS, "files_per_collection": MAX_FILES,
                         "output_bytes": MAX_OUTPUT_BYTES, "json_depth": MAX_JSON_DEPTH, "snapshot_only": True,
                         "timestamps_inferred": False, "query": query}}
    if query is not None:
        if len(query) > 512:
            raise ValueError("Zoektekst maximaal 512 tekens.")
        needle = query.casefold()
        for key in ("timeline", "logs"):
            result[key] = [item for item in result[key]
                           if needle in json.dumps(item, ensure_ascii=False).casefold()]
    for limitation in DEFAULT_LIMITATIONS:
        _warn(warnings, limitation)
    return _output_bound(result)


def compare_runs(root: Path | str, game: str, run: str, other_run: str) -> dict:
    sides = []
    warnings: list[str] = []
    for name in (run, other_run):
        path = run_path(root, game, name)
        local: list[str] = []
        summary, prepared, _ = _base(path, game, name, local, include_integrity=False)
        sides.append({"summary": _summary(summary, prepared, local),
                      "configuration": _configuration(summary, prepared, local),
                      "modules": _modules(summary, path, local)})
        for message in local:
            _warn(warnings, f"{name}: {message}")
    left, right = sides
    changes = []
    for field in sorted(set(left["configuration"]) | set(right["configuration"])):
        old, new = left["configuration"].get(field), right["configuration"].get(field)
        if old != new:
            changes.append({"field": f"configuration.{field}", "left": old, "right": new})
    if left["summary"].get("binary_identity") != right["summary"].get("binary_identity"):
        changes.append({"field": "binary_identity", "left": left["summary"].get("binary_identity"),
                        "right": right["summary"].get("binary_identity")})
    # Compare factual module sets independent of sampling order and absolute trial path.
    def identities(modules: list) -> list:
        unique = {json.dumps({key: module.get(key) for key in ("name", "path", "sha256", "file_version")},
                             sort_keys=True, ensure_ascii=True)
                  for module in modules if isinstance(module, dict)}
        return [json.loads(value) for value in sorted(unique)]
    lm, rm = identities(left["modules"]), identities(right["modules"])
    if lm != rm:
        changes.append({"field": "modules", "left": lm, "right": rm})
    _warn(warnings, "Vergelijking toont alleen opgeslagen verschillen; bewijst geen oorzaak, FPS of geslaagde race.")
    _warn(warnings, "Modulepaden kunnen alleen door de eigen proefmap verschillen; geen oorzaak afgeleid.")
    return _output_bound({"schema": 1, "game": game, "run": run, "other_run": other_run,
                          "left_summary": left["summary"], "right_summary": right["summary"],
                          "changes": changes, "warnings": warnings})


def _serialized(value: dict) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _output_bound(value: dict) -> dict:
    if len(_serialized(value)) <= MAX_OUTPUT_BYTES:
        return value
    _warn(value["warnings"], f"Totale weergave afgekapt bij {MAX_OUTPUT_BYTES} bytes.")
    for key in ("logs", "timeline", "modules", "runs", "changes"):
        while value.get(key) and len(_serialized(value)) > MAX_OUTPUT_BYTES:
            value[key] = value[key][:len(value[key]) // 2]
    for key in ("configuration", "integrity", "summary", "left_summary", "right_summary"):
        if len(_serialized(value)) > MAX_OUTPUT_BYTES and key in value:
            value[key] = {"truncated": True}
    if len(_serialized(value)) > MAX_OUTPUT_BYTES:
        value["warnings"] = ["Rapportgegevens te groot; weergave onvolledig."]
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "show", "compare"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, default=WORKSPACE)
        command.add_argument("--game", choices=GAMES, required=name != "list")
        if name != "list":
            command.add_argument("--run", required=True)
        if name == "show":
            command.add_argument("--query")
        if name == "compare":
            command.add_argument("--other-run", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            result = list_runs(args.root, args.game)
        elif args.command == "show":
            result = show_run(args.root, args.game, args.run, args.query)
        else:
            result = compare_runs(args.root, args.game, args.run, args.other_run)
        print(_serialized(result))
        return 0
    except (OSError, ValueError, RecursionError) as exc:
        print(_serialized({"schema": 1, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
