"""One naming rule for resolution choices in every game of the launcher.

Rule: ``[Origineel ·] [naam ·] B × H · verhouding [· status]``

- Width and height always use the multiplication sign: ``1920 × 1080``.
- The aspect ratio follows the size: ``4:3`` or ``16:9``.
- A status is always last, lowercase and without brackets.
- The heading above such a choice is always ``Resolutie`` and the overview
  card is always ``RESOLUTIE``.

tools/launcher_common.ps1 (Format-A2Resolution) follows the same rule for
choices that the WPF launcher builds itself.
"""
from __future__ import annotations

STATUSES = ('aanbevolen', 'untested', 'unstable', 'vervallen')
SEPARATOR = ' · '


def resolution_label(width: int | None = None, height: int | None = None, ratio: str | None = None, *,
                     original: bool = False, name: str | None = None, status: str | None = None) -> str:
    if (width is None) != (height is None):
        raise ValueError('Geef breedte en hoogte samen op.')
    if ratio is not None and ratio not in ('4:3', '16:9'):
        raise ValueError('Onbekende beeldverhouding: ' + ratio)
    if status is not None and status not in STATUSES:
        raise ValueError('Onbekende status: ' + status)
    parts = ['Origineel'] if original else []
    if name:
        parts.append(name)
    if width is not None:
        parts.append(str(int(width)) + ' × ' + str(int(height)))
    if ratio:
        parts.append(ratio)
    if status:
        parts.append(status)
    if not parts:
        raise ValueError('Lege resolutienaam.')
    return SEPARATOR.join(parts)
