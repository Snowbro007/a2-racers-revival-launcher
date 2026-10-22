"""Recognize supported II images inside differently packaged player ZIPs.

Only read and hash archive members. Never extract, mount, execute or download.
The ZIP name, member prefix and compression method do not identify a game.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import stat
import zipfile

from tools.trial_manifest import validate_ancestors
from tools.ii_playtest_check import ISO_PIN

MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_ARCHIVE_ENTRIES = 20_000
KNOWN_IMAGES = {
    # Complete supported v1.01 disc: original MODE2 sectors and verified ISO
    # payload export of that same disc. These are content pins, not filenames.
    'ac5ae16ecc358656d154a140437a1cd15ce7649728ae3a06bd60762c8dba20b2': {
        'size': 528967152, 'format': 'MODE2/2352 Form1'},
    ISO_PIN['sha256']: {'size': ISO_PIN['size'], 'format': 'ISO2048'},
}
ERROR_PREFIX = 'Dit deel-II-archief wordt niet herkend. '


def recognize_archive(archive: Path) -> dict:
    """Return an independently pinned image contract before any output exists."""
    validate_ancestors(archive)
    before = archive.stat()
    if not archive.is_file() or not 0 < before.st_size <= MAX_ARCHIVE_BYTES:
        raise ValueError(ERROR_PREFIX+'Kies een volledig ZIP-bestand van maximaal 2 GiB.')
    try:
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise ValueError(ERROR_PREFIX+'Het ZIP-bestand bevat te veel onderdelen.')
            images = [entry for entry in entries if not entry.is_dir()
                      and Path(entry.filename).suffix.casefold() in ('.bin', '.iso')]
            if not images and any(Path(e.filename).suffix.casefold() == '.nrg' for e in entries):
                raise ValueError(ERROR_PREFIX+'Deze download bevat een NRG-image. Kies de ondersteunde BIN/CUE- of ISO-versie.')
            if len(images) != 1:
                raise ValueError(ERROR_PREFIX+'Kies de volledige ZIP met precies één Nederlands v1.01 BIN/CUE- of ISO-image; niet het losse CUE-bestand.')
            image = images[0]
            if image.flag_bits & 1 or stat.S_ISLNK(image.external_attr >> 16):
                raise ValueError(ERROR_PREFIX+'Versleutelde of gekoppelde cd-images worden niet ondersteund.')
            if image.file_size not in {pin['size'] for pin in KNOWN_IMAGES.values()}:
                raise ValueError(ERROR_PREFIX+'Het cd-image heeft een andere of onvolledige grootte dan de ondersteunde Nederlandse v1.01-versie.')
            digest = hashlib.sha256()
            count = 0
            with source.open(image) as incoming:
                while block := incoming.read(1024**2):
                    count += len(block)
                    if count > image.file_size or count > MAX_ARCHIVE_BYTES:
                        raise ValueError(ERROR_PREFIX+'Het cd-image overschrijdt de opgegeven grootte.')
                    digest.update(block)
            image_hash = digest.hexdigest()
            known = KNOWN_IMAGES.get(image_hash)
            if count != image.file_size or known is None or known['size'] != count:
                raise ValueError(ERROR_PREFIX+'De inhoud van het cd-image wijkt af van de ondersteunde Nederlandse v1.01-versie.')
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise ValueError(ERROR_PREFIX+'De ZIP is beschadigd, versleuteld of gebruikt een niet-ondersteunde compressie.') from exc
    validate_ancestors(archive)
    after = archive.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Bronarchief veranderde tijdens de herkenning; kies het bestand opnieuw.')
    return {'member': image.filename, 'size': count, 'sha256': image_hash,
            'format': known['format'], 'game': 'a2racer2', 'native_game_executed': False}
