"""Command-line entry points for inventory and diagnosis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .diagnosis import diagnose, render_report
from .inventory import GAMES, scan_directory, validate_output_path, write_json, write_reports


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(prog="a2revival", description="Lokale statische inventarisatie van de originele A2 Racer-games.")
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory", help="Scan een gamemap zonder bestanden uit te voeren of te wijzigen.")
    inventory.add_argument("--game", choices=GAMES, required=True)
    inventory.add_argument("--path", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)
    doctor = commands.add_parser("doctor", help="Beoordeel een bestaand manifest; controleert bronbestanden niet opnieuw.")
    doctor.add_argument("--manifest", type=Path, required=True)
    doctor.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            manifest = scan_directory(args.game, args.path, args.output)
            write_reports(manifest, args.output)
            diagnosis = diagnose(manifest)
            print(f"{args.game}: {manifest['summary']['file_count']} bestanden. Diagnose: {diagnosis['status']}. Windows 11: onbekend.")
            print(f"Rapporten: {args.output.resolve()}")
        else:
            # Refuse unexpectedly huge manifests before allocating JSON structures.
            if args.manifest.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("Manifest is groter dan de limiet van 64 MiB.")
            manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
            diagnosis = diagnose(manifest)
            report = render_report(manifest, diagnosis)
            if args.output:
                validate_output_path(args.output)
                args.output.mkdir(parents=True, exist_ok=True)
                for filename in ("diagnosis.json", "diagnosis.md"):
                    target = args.output / filename
                    try:
                        target.lstat()
                    except FileNotFoundError:
                        pass
                    else:
                        raise ValueError("Doctor-output bestaat al; kies een lege rapportmap.")
                write_json(args.output / "diagnosis.json", diagnosis)
                (args.output / "diagnosis.md").write_text(report, encoding="utf-8", newline="\n")
            print(report)
        return 0
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        print(f"Fout: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
