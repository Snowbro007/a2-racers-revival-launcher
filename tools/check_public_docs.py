"""Check the explicit public documentation boundary; never modify repository files."""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = frozenset({
    'docs/launcher-start-help.md',
    'docs/public-gitignore.txt',
    'docs/public-readme.md',
    'docs/public-release-notes.md',
    'docs/public-release.json',
    'docs/release-acceptance.example.json',
    'docs/release-third-party-notices.md',
    'docs/releasing.md',
    'docs/updates.md',
})
PUBLIC_NARRATIVE_FILES = PUBLIC_DOCS | frozenset({
    'README.md', 'LEESMIJ.txt', 'RELEASE-NOTES.md', 'THIRD-PARTY-NOTICES.md',
    'VERSION.txt', 'LICENSE', 'tools/windows/msi/README.md',
})
NARRATIVE_SUFFIXES = frozenset({'.md', '.txt', '.rst', '.adoc'})


def check_paths(paths) -> int:
    """Reject internal docs even when a caller adds them to a package file list.

    Names are repository-relative POSIX paths and intentionally case-sensitive.
    Ordinary source, tests and workflow files remain governed by their separate
    source/package checks; this boundary does not claim to scan file contents.
    """
    checked = 0
    for name in paths:
        if (not isinstance(name, str) or not name or '\\' in name or ':' in name
                or '\x00' in name or name.startswith('/')
                or any(part in ('', '.', '..') or part.endswith((' ', '.'))
                       or any(ord(char) < 32 for char in part) for part in name.split('/'))):
            raise ValueError('Ongeldige openbare bestandsnaam.')
        path = PurePosixPath(name)
        in_docs = path.parts[0].casefold() == 'docs'
        narrative = path.suffix.casefold() in NARRATIVE_SUFFIXES
        if (in_docs or narrative) and name not in PUBLIC_NARRATIVE_FILES:
            raise ValueError('Niet-toegestane openbare documentatie: ' + name)
        checked += 1
    return checked


def tracked_paths(repository: Path) -> list[str]:
    """Read only the Git index; never walk local caches or private game folders."""
    output = subprocess.check_output(['git', 'ls-files', '-z'], cwd=repository)
    return [name for name in output.decode('utf-8').split('\x00') if name]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=ROOT,
                        help='Openbare broncheckout die moet worden gecontroleerd.')
    args = parser.parse_args(argv)
    try:
        count = check_paths(tracked_paths(args.repository))
    except (OSError, ValueError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f'Openbare documentatie gecontroleerd: {count} getrackte bestanden.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
