"""Deterministic, read-only directory inventory. No third-party dependencies."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from .executables import inspect_executable

GAMES = ("a2racer1", "a2racer2", "a2racer3")
REPORT_NAMES = ("manifest.json", "diagnosis.md", "diagnosis.json")


def _reparse(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def validate_output_path(output: Path) -> None:
    """Do not write reports through an existing link or junction."""
    output = Path(output).absolute()
    for candidate in (output, *output.parents):
        try:
            if _reparse(candidate):
                raise ValueError("Rapportpad bevat een symlink/reparse point; kies een echte rapportmap.")
        except FileNotFoundError:
            pass
    if output.exists() and not output.is_dir():
        raise ValueError("Rapportpad is geen map.")


def _validate_source_ancestors(source: Path) -> None:
    for candidate in (source.absolute(), *source.absolute().parents):
        if _reparse(candidate):
            raise ValueError("Bronpad bevat een symlink/reparse point; kies de echte bronmap.")


def _kind(path: Path, prefix: bytes) -> str:
    if prefix.startswith(b"MZ") or path.suffix.lower() in (".exe", ".dll", ".ocx", ".drv", ".scr"):
        return "executable"
    signatures = ((b"RIFF", "riff"), (b"BM", "bitmap"), (b"\x89PNG\r\n\x1a\n", "png"),
                  (b"OggS", "ogg"), (b"PK\x03\x04", "zip"), (b"\xff\xd8\xff", "jpeg"))
    for signature, kind in signatures:
        if prefix.startswith(signature):
            return kind
    extension = path.suffix.lower()
    if extension in (".ini", ".cfg", ".conf", ".reg"):
        return "configuration-candidate"
    if extension in (".txt", ".nfo", ".htm", ".html"):
        return "text-candidate"
    if extension in (".dat", ".pak", ".wad", ".res", ".tex", ".mdl", ".map", ".sav"):
        return "asset-candidate"
    return "unknown"


def scan_directory(game: str, source: Path, output: Path) -> dict:
    """Scan only regular files; omit links and the chosen report subtree."""
    if game not in GAMES:
        raise ValueError("Onbekende game; kies " + ", ".join(GAMES) + ".")
    source, output = Path(source), Path(output)
    if not source.exists():
        raise ValueError(f"Bronmap bestaat niet: {source}")
    if _reparse(source):
        raise ValueError("Bronmap is een symlink of reparse point; kies de echte map.")
    _validate_source_ancestors(source)
    if not source.is_dir():
        raise ValueError(f"Bronpad is geen map: {source}")
    validate_output_path(output)
    source, output = source.resolve(), output.resolve()
    if source == output:
        raise ValueError("Gebruik een andere rapportmap dan de bronmap, bijvoorbeeld een submap reports.")
    if output in source.parents:
        raise ValueError("Rapportmap mag geen bovenliggende map van de bronmap zijn.")
    files, issues = [], []

    def issue(path: str, code: str, message: str) -> None:
        issues.append({"path": path, "code": code, "message": message})

    def walk(directory: Path, depth: int = 0) -> None:
        if depth > 128:
            issue(directory.relative_to(source).as_posix(), "depth_limit", "Mapdiepte groter dan 128; overgeslagen.")
            return
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            issue(directory.relative_to(source).as_posix(), "unreadable_directory", f"Map niet leesbaar ({type(exc).__name__}).")
            return
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(source).as_posix()
            try:
                if _reparse(path):
                    issue(relative, "link_skipped", "Symlink/reparse point overgeslagen; doel niet gevolgd.")
                    continue
                if path.resolve() == output:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    walk(path, depth + 1)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    issue(relative, "special_file_skipped", "Geen regulier bestand; overgeslagen.")
                    continue
                before = path.stat(follow_symlinks=False)
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    prefix = handle.read(16)
                    digest.update(prefix)
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
                after = path.stat(follow_symlinks=False)
                if _reparse(path) or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                    issue(relative, "changed_during_scan", "Bestand veranderde tijdens de scan; resultaat weggelaten.")
                    continue
                record = {"path": relative, "size": before.st_size, "sha256": digest.hexdigest(), "type": _kind(path, prefix)}
                if record["type"] == "executable":
                    record["executable"] = inspect_executable(path)
                    final = path.stat(follow_symlinks=False)
                    if _reparse(path) or (after.st_size, after.st_mtime_ns, after.st_ino) != (final.st_size, final.st_mtime_ns, final.st_ino):
                        issue(relative, "changed_during_scan", "Bestand veranderde tijdens headerinspectie; resultaat weggelaten.")
                        continue
                    for problem in record["executable"]["issues"]:
                        issue(relative, "executable_header", problem)
                files.append(record)
            except OSError as exc:
                issue(relative, "unreadable_file", f"Bestand niet leesbaar ({type(exc).__name__}).")

    walk(source)
    files.sort(key=lambda record: record["path"])
    issues.sort(key=lambda record: (record["path"], record["code"], record["message"]))
    return {
        "schema_version": 1, "game": game, "files": files, "issues": issues,
        "summary": {"file_count": len(files), "total_size": sum(record["size"] for record in files),
                    "executable_count": sum(record["type"] == "executable" for record in files),
                    "unknown_type_count": sum(record["type"] == "unknown" for record in files)},
    }


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def write_reports(manifest: dict, output: Path) -> None:
    from .diagnosis import diagnose, render_report, validate_manifest

    diagnosis = diagnose(manifest)
    report = render_report(manifest, diagnosis)
    output = Path(output)
    validate_output_path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name in REPORT_NAMES:
        try:
            if _reparse(output / name):
                raise ValueError("Rapportbestand is een link/reparse point; kies een andere rapportmap.")
        except FileNotFoundError:
            pass
    # A selected report directory may contain only our own report filenames.
    # Do not overwrite an unrelated JSON/document supplied as game input.
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_manifest(old)
        except (ValueError, AttributeError, OSError):
            raise ValueError("Rapportmap bevat een onbekend manifest.json; kies een lege rapportmap.") from None
    elif any((output / name).exists() for name in REPORT_NAMES):
        raise ValueError("Rapportmap bevat bestaande rapportnamen; kies een lege rapportmap.")
    write_json(manifest_path, manifest)
    (output / "diagnosis.md").write_text(report, encoding="utf-8", newline="\n")
