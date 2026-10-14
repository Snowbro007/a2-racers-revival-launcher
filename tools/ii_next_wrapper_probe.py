"""Prepare independent II wrapper probes; never execute games or mount media.

Only new local/ii-parallel copies and reports/a2racer2-next reports are written.
The shared trial runner and all game binaries remain unchanged.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from a2revival.inventory import scan_directory, write_json
from tools import ii_playtest_check, trial_manifest

FPS_CHOICES = (0, 30, 60)

LAUNCH_SCRIPT = r'''#Requires -Version 7.4
[CmdletBinding()]
param([switch]$CheckOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try {
    $iiBase = $PSScriptRoot
    $iiWorkspace = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $iiBase))
    . (Join-Path $iiWorkspace 'tools/launcher_common.ps1')
    $iiRunName = Split-Path -Leaf $iiBase
    if ($iiRunName -notmatch '^[a-z0-9][a-z0-9-]{0,47}$') { throw 'Ongeldige proefnaam.' }
    $iiReport = Join-Path $iiWorkspace ('reports/a2racer2-next/' + $iiRunName)
    $iiGame = Join-Path $iiBase 'game'
    foreach ($path in @($iiBase, $iiReport, $iiGame)) { Assert-LauncherPath $path }
    $iiPrepared = Get-Content -LiteralPath (Join-Path $iiReport 'prepared.json') -Raw | ConvertFrom-Json
    $iiManifest = Get-Content -LiteralPath (Join-Path $iiReport 'copy-prepared.json') -Raw | ConvertFrom-Json
    if ($iiPrepared.game -ne 'a2racer2' -or -not $iiPrepared.disable_movies -or -not $iiPrepared.hide_watermark -or $iiPrepared.no_cd_mode -ne 'builtin-NOCD-local-files') { throw 'Onverwacht deel-II-profiel.' }
    $iiDrive = [System.IO.Path]::GetPathRoot($iiGame).Substring(0, 1).ToUpperInvariant()
    if ($iiDrive -notmatch '^[A-Z]$') { throw 'Deze proef vereist een lokale schijfletter.' }
    $iiGamePrefix = [System.IO.Path]::GetFullPath($iiGame).TrimEnd('\') + '\'
    $iiCheckedDirs = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in $iiManifest.files) {
        $path = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($iiGame, $file.path))
        if (-not $path.StartsWith($iiGamePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Manifestpad valt buiten de proefkopie.' }
        $directory = [System.IO.Path]::GetDirectoryName($path)
        if ($iiCheckedDirs.Add($directory)) { Assert-LauncherPath $directory }
        $info = [System.IO.FileInfo]::new($path)
        if (-not $info.Exists -or $info.Length -ne $file.size -or ($info.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { throw ('Lokaal gamebestand ontbreekt of is onvolledig: ' + $file.path) }
    }
    foreach ($name in @('DATA/A2_II.EXE', 'DATA/MENU.DAT', 'DATA/SPEL.DAT', 'DATA/RASER.INI', 'DATA/dgVoodoo.conf', 'DATA/DDraw.dll', 'DATA/D3DImm.dll')) {
        $expected = @($iiManifest.files | Where-Object { $_.path -eq $name })
        $path = Join-Path $iiGame $name
        Assert-LauncherPath $path
        if ($expected.Count -ne 1 -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected[0].sha256) { throw ('Proefbestand veranderde: ' + $name) }
    }
    if ($CheckOnly) {
        @{ game='a2racer2'; game_started=$false; disc_image_used=$false; fps=$iiPrepared.wrapper_fps_requested; no_cd_mode='builtin-NOCD-local-files'; child_NOCD=$iiDrive } | ConvertTo-Json
        exit 0
    }
    $iiRunning = @()
    foreach ($root in @('local/experiments', 'local/ii-parallel')) {
        $iiRunning += @(Get-LauncherProcesses (Join-Path $iiWorkspace $root))
    }
    if ($iiRunning.Count) { throw 'Sluit de eerdere game eerst normaal af voordat je een nieuwe proef start.' }
    # The verified MENU/SPEL versions already implement NOCD through getenv.
    # Scope this override to the new child. Parent/system environment stays intact.
    Start-Process -FilePath (Join-Path $iiGame 'DATA/A2_II.EXE') -WorkingDirectory (Join-Path $iiGame 'DATA') -Environment @{ NOCD = $iiDrive }
} catch {
    Write-Host ('Deel-II-proef kon niet starten: ' + $_.Exception.Message) -ForegroundColor Red
    if (-not $CheckOnly -and -not $env:II_PROBE_NONINTERACTIVE) { $null = Read-Host 'Druk op Enter om te sluiten' }
    exit 1
}
'''


def write_launch_files(base: Path, powershell_path: str) -> None:
    """Emit user-invoked start files; preparation never invokes this script."""
    if not powershell_path or any(c in powershell_path for c in '\r\n"'):
        raise ValueError("Geen bruikbare PowerShell 7 gevonden.")
    (base / "Start-Probe.ps1").write_text(LAUNCH_SCRIPT, encoding="utf-8-sig")
    command = ('@echo off\r\n"' + powershell_path.replace('%', '%%') +
               '" -NoLogo -NoProfile -File "%~dp0Start-Probe.ps1"\r\n')
    (base / "Start.cmd").write_text(command, encoding="utf-8", newline="")


def replace_setting(data: bytes, section: bytes, key: bytes,
                    before: bytes, after: bytes) -> bytes:
    """Preserve all bytes except one value; reject ambiguous INI input."""
    lines = data.splitlines(keepends=True)
    active = b""
    sections = 0
    matches = []
    for index, line in enumerate(lines):
        heading = re.fullmatch(rb"[ \t]*\[([^\]]+)\][ \t]*", line.rstrip(b"\r\n"))
        if heading:
            active = heading[1].strip().lower()
            sections += active == section.lower()
        if active == section.lower():
            match = re.fullmatch(rb"([ \t]*" + re.escape(key) +
                                 rb"[ \t]*=[ \t]*)([^\r\n]*)(\r?\n)?", line, re.I)
            if match:
                matches.append((index, match))
    if sections != 1 or len(matches) != 1 or matches[0][1][2].strip() != before:
        raise ValueError("Onverwachte of dubbele configuratiesectie/sleutel.")
    index, match = matches[0]
    value = match[2]
    trailing = value[len(value.rstrip(b" \t")):]
    lines[index] = match[1] + after + trailing + (match[3] or b"")
    return b"".join(lines)


def wrapper_config(data: bytes, fps_limit: int) -> bytes:
    if type(fps_limit) is not int or fps_limit not in FPS_CHOICES:
        raise ValueError("Kies de deel-II-proef 0, 30 of 60 FPS.")
    data = replace_setting(data, b"DirectX", b"dgVoodooWatermark", b"true", b"false")
    return replace_setting(data, b"GeneralExt", b"FPSLimit", b"0",
                           str(fps_limit).encode("ascii"))


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_manifest(source: Path, report: Path) -> dict:
    result = scan_directory("a2racer2", source, report)
    bad = [item for item in result["issues"] if item["code"] != "executable_header"]
    if bad:
        raise ValueError(f"Onvolledige/onstabiele scan: {bad[0]['code']}")
    return result


def check_local_source(workspace: Path) -> dict:
    """Pin the existing complete extraction without reading or requiring an ISO."""
    source = workspace / 'local/games/a2racer2'
    errors = []
    count = ii_playtest_check._source_count(source)
    if count != ii_playtest_check.EXPECTED_SOURCE_FILES:
        errors.append('Onverwacht aantal bronbestanden.')
    pins = []
    for name, expected in ii_playtest_check.SOURCE_PINS.items():
        item = ii_playtest_check._fingerprint(source / name, expected)
        item['relative_path'] = name
        pins.append(item)
        if not item['verified']:
            errors.append('Onbekend/onvolledig bronbestand: ' + name)
    return {'game': 'a2racer2', 'ready_for_trial': not errors, 'errors': errors,
            'source_files': count, 'source_pins': pins, 'disc_image_used': False,
            'no_cd_mode': 'builtin-NOCD-local-files', 'runtime_tested': False}


def prepare_probe(workspace: Path, run_name: str, fps_limit: int) -> dict:
    trial_manifest.validate_slug(run_name)
    # Validate before creating output, including bool-as-int and unsupported caps.
    wrapper_config(b"[GeneralExt]\nFPSLimit=0\n[DirectX]\ndgVoodooWatermark=true\n", fps_limit)
    powershell_path = shutil.which("pwsh")
    if not powershell_path:
        raise ValueError("Geen PowerShell 7 gevonden; geen proef voorbereid.")
    workspace = workspace.absolute()
    source = workspace / "local/games/a2racer2"
    base = workspace / "local/ii-parallel" / run_name
    report = workspace / "reports/a2racer2-next" / run_name
    for path in (base, report):
        trial_manifest.validate_ancestors(path)
        if path.exists():
            raise ValueError("Proef of rapport bestaat al; overschrijven geweigerd.")
    check = check_local_source(workspace)
    if not check["ready_for_trial"]:
        raise ValueError("Deel-II-preflight mislukt: " + "; ".join(check["errors"]))
    planned = trial_manifest.plan_graphics_wrapper(workspace, "a2racer2", source,
                                                  "dgvoodoo-windowed")
    config_items = [item for item in planned if item["relative_path"] == "DATA/dgVoodoo.conf"]
    if len(config_items) != 1:
        raise ValueError("Verwachte deel-II-wrapperconfig ontbreekt.")
    original_config = config_items[0]["data"]
    config = wrapper_config(original_config, fps_limit)
    movie_source = (source / "DATA/RASER.INI").read_bytes()
    movies_off = replace_setting(movie_source, b"MOVIES", b"ON", b"1", b"0")
    before = stable_manifest(source, report)
    reference_path = workspace / "reports/a2racer2/manifest.json"
    trial_manifest.validate_ancestors(reference_path)
    reference = json.loads(reference_path.read_text(encoding="utf-8-sig"))
    if any(trial_manifest.manifest_diff(reference, before).values()):
        raise ValueError("Bron wijkt af van de volledige bestaande deel-II-inventarisatie.")
    planned = copy.deepcopy(planned)
    config_item = next(item for item in planned if item["relative_path"] == "DATA/dgVoodoo.conf")
    config_item["data"] = config
    config_item["sha256"] = fingerprint(config)
    base.parent.mkdir(parents=True, exist_ok=True)
    base.mkdir()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.mkdir()
    game = base / "game"
    # Full copy, no hardlinks; scans/preflight reject source reparse points.
    shutil.copytree(source, game)
    copied = stable_manifest(game, report)
    if any(trial_manifest.manifest_diff(before, copied).values()):
        raise ValueError("Kopie verschilt van de bron; geen startbestand gemaakt.")
    config_path = game / "DATA/RASER.INI"
    if config_path.read_bytes() != movie_source:
        raise ValueError("Filmconfig veranderde; geen startbestand gemaakt.")
    config_path.write_bytes(movies_off)
    dependencies = trial_manifest.apply_graphics_wrapper(game, planned)
    after = stable_manifest(source, report)
    if any(trial_manifest.manifest_diff(before, after).values()):
        raise ValueError("Bron veranderde tijdens voorbereiding; geen startbestand gemaakt.")
    prepared = stable_manifest(game, report)
    diff = trial_manifest.manifest_diff(copied, prepared)
    if diff != {"changed": ["DATA/RASER.INI"], "removed": [],
                "added": sorted(item["relative_path"] for item in planned)}:
        raise ValueError("Onverwachte wijziging in proefkopie; geen startbestand gemaakt.")
    if fingerprint((game / "DATA/dgVoodoo.conf").read_bytes()) != fingerprint(config):
        raise ValueError("Wrapperconfigcontrole mislukt; geen startbestand gemaakt.")
    for name, manifest in (("source-before.json", before), ("source-after.json", after),
                           ("copy-before.json", copied), ("copy-prepared.json", prepared)):
        write_json(report / name, manifest)
    write_json(report / "preflight.json", check)
    (report / "wrapper-before.conf").write_bytes(original_config)
    (report / "wrapper-prepared.conf").write_bytes(config)
    result = {"schema": 1, "game": "a2racer2", "run_name": run_name,
              "mode": "static-preparation-only", "runtime_tested": False,
              "source_unchanged": True, "copy_diff": diff,
              "wrapper_version": trial_manifest.DGVOODOO_VERSION,
              "wrapper_fps_requested": fps_limit, "hide_watermark": True,
              "disable_movies": True, "binary_fixes": [],
              "wrapper_config_sha256": fingerprint(config),
              "graphics_dependencies": dependencies,
              "game_path": str(game), "report_path": str(report),
              "start_file": str(base / "Start.cmd"),
              "no_cd_mode": "builtin-NOCD-local-files", "disc_image_used": False,
              "limitations": ["Geen game gestart, cd gemount of live proces geïnspecteerd.",
                              "FPS-limiet geldt voor menu en race; werkelijk FPS niet gemeten.",
                              "30/60 zijn diagnosekandidaten, geen bewezen oorspronkelijk speltempo.",
                              "Nieuwe schone speler/opties; bestaande saves niet overgenomen."]}
    write_json(report / "prepared.json", result)
    instructions = ("A2 Racer II - lokale wrapperproef\n"
                    f"Gevraagde FPS-limiet: {fps_limit} (0 = onbeperkt). Logo uit, films uit.\n"
                    "Sluit eerdere games normaal af voordat je Start.cmd opent.\n"
                    "Deze proef gebruikt de ingebouwde NOCD-optie en alle lokale gamebestanden.\n"
                    "Geen cd of image nodig; de start mount/dismount niets.\n"
                    "Deze start sluit geen andere processen af.\n"
                    "Geen runtime-monitor of automatische stop; afsluiten via het gamemenu.\n"
                    "Test dezelfde etappe, auto en botsing; noteer raceklok/echte tijd en geluid.\n")
    (base / "Lees-eerst.txt").write_text(instructions, encoding="utf-8")
    write_launch_files(base, powershell_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--fps", type=int, choices=FPS_CHOICES, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare_probe(ROOT, args.run_name, args.fps), ensure_ascii=True, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "runtime_tested": False}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
