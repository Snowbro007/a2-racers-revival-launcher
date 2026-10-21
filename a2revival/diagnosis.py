"""Diagnose static evidence, without claiming runtime compatibility."""

from __future__ import annotations

from pathlib import PurePosixPath
import re

from .inventory import GAMES

CATEGORIES = {
    "graphics": {"ddraw.dll", "d3dim.dll", "d3drm.dll", "d3d8.dll", "d3d9.dll", "opengl32.dll", "glide2x.dll", "glide3x.dll"},
    "audio": {"dsound.dll", "winmm.dll", "mss32.dll"},
    "input": {"dinput.dll", "dinput8.dll", "winmm.dll"},
    "network": {"wsock32.dll", "ws2_32.dll", "dplay.dll", "dplayx.dll", "dpnet.dll"},
    "video": {"avifil32.dll", "msvfw32.dll", "binkw32.dll", "smackw32.dll"},
}


def validate_manifest(manifest: dict) -> None:
    def reject(message: str) -> None:
        raise ValueError(f"Ongeldig manifest: {message}")

    if not isinstance(manifest, dict):
        reject("JSON-root moet een object zijn.")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        reject("schema_version moet 1 zijn.")
    if manifest.get("game") not in GAMES:
        reject("game moet een van deze zijn: " + ", ".join(GAMES) + ".")
    if not isinstance(manifest.get("files"), list) or not isinstance(manifest.get("issues"), list) or not isinstance(manifest.get("summary"), dict):
        reject("files, issues en summary ontbreken of hebben een verkeerd type.")
    seen = set()
    for record in manifest["files"]:
        if not isinstance(record, dict):
            reject("elk bestand moet een object zijn.")
        path = record.get("path")
        if not isinstance(path, str) or not path or "\\" in path or ":" in path or path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/")) or PurePosixPath(path).is_absolute():
            reject("bestandspaden moeten veilige relatieve paden zijn.")
        if path in seen:
            reject("dubbel bestandspad.")
        seen.add(path)
        if type(record.get("size")) is not int or record["size"] < 0:
            reject(f"ongeldige bestandsgrootte bij {path}.")
        if not isinstance(record.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", record["sha256"]):
            reject(f"ongeldige SHA-256 bij {path}.")
        if not isinstance(record.get("type"), str):
            reject(f"bestandstype ontbreekt bij {path}.")
        if (record["type"] == "executable") != ("executable" in record):
            reject(f"bestandstype en executable-analyse komen niet overeen bij {path}.")
        if "executable" in record:
            executable = record["executable"]
            if not isinstance(executable, dict) or not isinstance(executable.get("imports"), list) or not isinstance(executable.get("issues"), list):
                reject(f"ongeldige executable-analyse bij {path}.")
            if executable.get("format") not in ("PE", "NE", "LE", "LX", "DOS", "unknown") or executable.get("status") not in ("inspected", "invalid", "unknown"):
                reject(f"ongeldige executable-status bij {path}.")
            if executable.get("architecture") is not None and not isinstance(executable["architecture"], str):
                reject(f"ongeldige architectuur bij {path}.")
            if not all(isinstance(item, str) for item in executable["issues"]):
                reject(f"ongeldige headerproblemen bij {path}.")
            for imported in executable["imports"]:
                if not isinstance(imported, dict) or not isinstance(imported.get("dll"), str) or not isinstance(imported.get("symbols"), list) or not all(isinstance(symbol, str) for symbol in imported["symbols"]):
                    reject(f"ongeldige imports bij {path}.")
    for issue in manifest["issues"]:
        if not isinstance(issue, dict) or not all(isinstance(issue.get(key), str) for key in ("path", "code", "message")):
            reject("ongeldig probleemrecord.")
    expected = {"file_count": len(manifest["files"]), "total_size": sum(item["size"] for item in manifest["files"]),
                "executable_count": sum(item["type"] == "executable" for item in manifest["files"]),
                "unknown_type_count": sum(item["type"] == "unknown" for item in manifest["files"])}
    if any(type(manifest["summary"].get(key)) is not int or manifest["summary"][key] != value for key, value in expected.items()):
        reject("summary komt niet overeen met de bestanden.")


def diagnose(manifest: dict) -> dict:
    validate_manifest(manifest)
    imports = []
    executables = []
    for record in manifest["files"]:
        if "executable" not in record:
            continue
        executable = record["executable"]
        executables.append({"path": record["path"], "format": executable["format"],
                            "architecture": executable.get("architecture"), "status": executable["status"]})
        for imported in executable["imports"]:
            imports.append({"path": record["path"], "dll": imported["dll"], "symbols": imported["symbols"]})
    signals = {category: [item for item in imports if item["dll"].lower() in dlls] for category, dlls in CATEGORIES.items()}
    blockers = []
    if not manifest["files"]:
        blockers.append("De map bevat geen geïnventariseerde bestanden.")
    if not executables:
        blockers.append("Geen executable gevonden; onderzoek schijfimages, installatie of een andere gamemap.")
    if any(item["status"] == "invalid" for item in executables):
        blockers.append("Een of meer headers konden niet volgens de ondersteunde structuren worden geïnspecteerd; onderzoek beschadiging of een afwijkend oud formaat.")
    if any(issue["code"] in ("unreadable_file", "unreadable_directory", "changed_during_scan", "depth_limit") for issue in manifest["issues"]):
        blockers.append("De inventarisatie is onvolledig door leesfouten of veranderende bestanden.")
    return {"game": manifest["game"], "status": "geblokkeerd" if blockers else "onbekend",
            "compatibility": {"windows11": "onbekend", "graphics_wrapper": "kandidaat" if signals["graphics"] else "onbekend",
                              "multiplayer": "onbekend", "browser": "onbekend"},
            "executables": executables, "signals": signals, "blockers": blockers,
            "notes": ["Statische imports zijn aanwijzingen, geen bewijs van gebruik tijdens het spelen.",
                      "Ontbrekende imports sluiten dynamisch geladen API's of netwerkcode niet uit.",
                      "Imports en headerproblemen kunnen uit meegeleverde installers/drivers komen; hun relevantie voor de game is nog niet vastgesteld.",
                      "Geblokkeerd betreft de volledige statische diagnose en bewijst niet dat de game niet kan draaien.",
                      "Windows 11, rendering, audio en input zijn nog niet tijdens een race getest.",
                      "doctor leest alleen het manifest; het controleert de bronbestanden niet opnieuw."]}


def _escape(value: object) -> str:
    text = str(value).replace("\\", "\\\\").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for character in "|`[]*_":
        text = text.replace(character, "\\" + character)
    return "".join(character if ord(character) >= 32 else " " for character in text)


def render_report(manifest: dict, diagnosis: dict) -> str:
    summary = manifest["summary"]
    lines = [f"# Diagnose {manifest['game']}", "", f"Status: **{diagnosis['status']}**. Windows 11: **onbekend**.", "",
             f"{summary['file_count']} bestanden, {summary['total_size']} bytes, {summary['executable_count']} executables, {summary['unknown_type_count']} onbekende bestandstypen.", "",
             "Dit is een lokale statische scan. Er zijn geen gamebestanden gestart, gewijzigd of geüpload.", "", "## Executables", "",
             "| Relatief pad | Formaat | Architectuur | Headerstatus |", "| --- | --- | --- | --- |"]
    for executable in diagnosis["executables"][:80]:
        lines.append("| " + " | ".join(_escape(executable.get(key) or "onbekend") for key in ("path", "format", "architecture", "status")) + " |")
    if not diagnosis["executables"]:
        lines.append("| Geen gevonden | — | — | — |")
    if len(diagnosis["executables"]) > 80:
        lines += ["", f"Eerste 80 van {len(diagnosis['executables'])} executables getoond; alle headers en imports staan in manifest.json."]
    lines += ["", "## Importaanwijzingen", ""]
    for category, evidence in diagnosis["signals"].items():
        lines.append(f"- **{category}**: " + ("; ".join(f"{_escape(item['path'])}: {_escape(item['dll'])} ({', '.join(_escape(s) for s in item['symbols'][:12])})" for item in evidence[:10]) if evidence else "onbekend; geen herkende statische import"))
        if len(evidence) > 10:
            lines.append(f"  Eerste 10 van {len(evidence)} importmodules getoond; overige details staan in manifest.json.")
    lines += ["", "## Blokkades", ""] + ([f"- {item}" for item in diagnosis["blockers"]] or ["Geen statische blokkade vastgesteld. Compatibiliteit blijft onbekend."])
    invalid_paths = {item['path'] for item in diagnosis['executables'] if item['status'] == 'invalid'}
    ordered_issues = sorted(manifest['issues'], key=lambda item: item['path'] not in invalid_paths)
    lines += ["", "## Scanproblemen", ""] + ([f"- {_escape(item['path'])}: {_escape(item['message'])} ({_escape(item['code'])})" for item in ordered_issues[:40]] or ["Geen scanproblemen gemeld."])
    if len(ordered_issues) > 40:
        lines += [f"- Eerste 40 van {len(ordered_issues)} meldingen getoond; alle meldingen staan in manifest.json."]
    lines += ["", "## Grenzen en volgende proef", ""] + [f"- {note}" for note in diagnosis["notes"]]
    lines += ["- Zie README.md en docs/launcher-start-help.md voor hulp bij het toevoegen en starten van je eigen game.",
              "- Onbekende bestandstypen en asset-candidates vereisen formaatonderzoek; deze scan decodeert geen game-assets.", ""]
    return "\n".join(lines)
