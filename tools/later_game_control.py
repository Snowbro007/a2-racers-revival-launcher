"""Cooperative local stop requests; never create files or stop a process here."""
from __future__ import annotations

from pathlib import Path
import re
import stat

from tools.trial_manifest import validate_ancestors as _assert_no_links


def validate_token(token: str | None) -> None:
    if token is not None and (type(token) is not str or re.fullmatch('[a-f0-9]{32}', token) is None):
        raise ValueError('Ongeldige spelsessiebesturing.')


def stop_path(root: Path, token: str) -> Path:
    validate_token(token)
    if token is None:
        raise ValueError('Een stopverzoek vereist een sessietoken.')
    path = Path(root) / 'local/launcher/later-controls' / (token + '.stop')
    _assert_no_links(path)
    return path


def stop_requested(root: Path, token: str | None) -> bool:
    validate_token(token)
    if token is None:
        return False
    path = stop_path(root, token)
    try:
        before = path.stat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 6:
        raise ValueError('Ongeldig stopverzoek voor de spelsessie.')
    with path.open('rb') as stream:
        raw = stream.read(6)
    _assert_no_links(path)
    after = path.stat()
    if ((before.st_size, before.st_mtime_ns, before.st_ino) !=
            (after.st_size, after.st_mtime_ns, after.st_ino) or raw != b'stop\n'):
        raise ValueError('Ongeldig of gewijzigd stopverzoek voor de spelsessie.')
    return True
