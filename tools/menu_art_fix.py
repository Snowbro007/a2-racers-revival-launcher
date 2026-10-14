"""Pinned opt-in refresh of the A2-I native 640x480 menu bitmaps.

This module only reads verified original archives and own PCX exports, and
returns in-memory trial replacement plans. It never starts games, writes source
files, changes sprites, or claims a physically HD menu render target.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct

from tools import resource_archive
from tools.pcx_codec import decode_pcx

PROFILE = "menu-refresh-v1"
ASSET_ROOT = "local/mods/a2racer1/menu-refresh-v1"
NATIVE_DIMENSIONS = (640, 480)
EXPECTED_RESOURCE_COUNT = 60
EXPECTED_FILES = {
    "A2MRC.IND": (1318, "008b848677c486f97311f2023a4d1b3d0a18c815779ecb6ef145ab6fe06d541a"),
    "A2MRC.IMG": (4042041, "dd837d6a50becd675c3514770ae01102b4b17afcb3b86b281a68cd3552acc2f6"),
    "A2MRCS.IND": (1442, "ce7f22faf099da56c379c695f5265e55a498c9dd09613a991289fe768b00a2e9"),
    "A2MRCS.IMG": (13321698, "0f0fad9eee81952b8580b1fa4b39d0d4baa8738adcd92a78a894c17744896029"),
    "A2MENU.DAT": (295936, "45b883ec76872622241beb75afb3966723d9bee806d76741c29c6642df6ff6e6"),
}
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_ASSET_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
# Pinned after technical conversion and native-size visual review. These are
# native bitmap exports, not a verified physical HD renderer or runtime result.
ASSET_PINS: dict[str, tuple[int, str]] = {
    "OPTIES.PCX": (168329, "be1b9816d86f0086e8edc517679f3650aaa437f98946c0543251a9da42494d47"),
    "Nspel_1.pcx": (75921, "3240c628211cc43dc43a5c07b34025fbe73c157b494c3aea28ad12b9c0ead3cc"),
    "Bedien.pcx": (179780, "2a69cbcb2b022916e0cd29c21ec31f759524b8212822f012b9dbbfb9cec4b44c"),
    "Score.pcx": (181403, "c55bda5ee03966ff9a34a98a3ea8a35b8910797bdd0ee30e653a7a4d8055ecea"),
    "Nspel_2.pcx": (78634, "c6ce1152ddca6beced86052e0e9def681e16be9bf761a3333c6099e336424dc0"),
    "hoofd.pcx": (161970, "6eb71b0f7fa132764c0ab92f98391ba1d104e7e0d14a8a80660c732c1b8f3826"),
    "score2.pcx": (179087, "50605b95f9dbf4142c04f0996dce6cbd481ad5cb3e3ffae92b5abb8a6ac31393"),
    "SCORE3.PCX": (179506, "9c7681403987a45872f7822eed1fde0e719625bb4083a13fba6ec9a48412eb24"),
    "Tstand2.pcx": (135251, "4ff95ab6cb33e096e7b845e4783d82367188c89fcf28a195117e2bee1cc051ac"),
    "Etappe3.PCX": (131821, "784ffb6c7ae3b1900287b944a8fd513c89dfcddfafb806523bf78364acd92058"),
    "Tstand.pcx": (136668, "979e6fe5fbf883ea46eee04cf499ae0f257615250a39befbe55959e06435f843"),
    "Etappe1.PCX": (131482, "afdf9d43233ec16f0dc3ba7c95947544e795f22fe79797c826c05677c0dccd27"),
    "Etappe4.PCX": (131920, "2d60e68ea5f18cf0ace27333666d9fa1339bd2e596ac2a7d7260ca55c86cd0ed"),
    "Etappe5.PCX": (132145, "37e48cea08c0abb811636ea3a3f29e683059a44c3fed42a07b4477332f41e937"),
    "Etappe6.PCX": (131983, "129b7e1eb7df342e58acb1aff5e74f926f12ba3eb373564f33682b88642a9ff8"),
    "Etappe2.PCX": (131767, "a9dcf231500655d9b3f7dca0f31d08ddfad527bab582061f319f1d793baaf9ad"),
}
MANIFEST_PIN: tuple[int, str] | None = (17064, "c8eed822f7c349fa354287e55b5456b0fca6dc2ab6dbe85f883c61af2d83e73c")

TOP_BOTTOM = ((0, 0, 640, 96), (0, 457, 640, 23))
# Exact indexed crop matches of original empty animation tiles, not unproven
# control/hitbox positions. Keep these underlays because A2MRC stays unchanged.
BUTTON_UNDERLAYS = tuple((0, y, 218, 45) for y in (124, 176, 228, 279, 331, 382))
FINISH_RECTS = ((0, 0, 640, 96), (53, 121, 87, 31), (490, 121, 94, 31))
PROTECTED_RECTS = {
    "OPTIES.PCX": (*TOP_BOTTOM, (217, 111, 404, 319)),
    "Nspel_1.pcx": (*TOP_BOTTOM, (43, 106, 552, 286), (94, 397, 449, 60)),
    "Bedien.pcx": (*TOP_BOTTOM, *BUTTON_UNDERLAYS, (296, 117, 334, 331)),
    "Score.pcx": (*TOP_BOTTOM, (25, 111, 596, 320)),
    "Nspel_2.pcx": (*TOP_BOTTOM, (43, 106, 552, 286), (94, 397, 449, 60)),
    "hoofd.pcx": (*TOP_BOTTOM, *BUTTON_UNDERLAYS,
                   (331, 133, 87, 91), (419, 132, 193, 110)),
    "score2.pcx": (*TOP_BOTTOM, (25, 107, 596, 324)),
    "SCORE3.PCX": (*TOP_BOTTOM, (25, 107, 596, 324)),
    **{name: FINISH_RECTS for name in (
        "Tstand2.pcx", "Etappe3.PCX", "Tstand.pcx", "Etappe1.PCX",
        "Etappe4.PCX", "Etappe5.PCX", "Etappe6.PCX", "Etappe2.PCX")},
}


@dataclass(frozen=True)
class ArtSpec:
    name: str
    index: int
    offset: int
    size: int
    sha256: str
    palette_sha256: str
    protected_rectangles: tuple[tuple[int, int, int, int], ...]


RESOURCE_SPECS = (
    ArtSpec("OPTIES.PCX", 0, 0, 181299,
            "16aebf02adbf5b89d6c3134f65fa1aa87057b47ad96193040a8bc4cd4faf7f35",
            "6481bf6c135cd860926ba50fe016840e48443048a31017850f19008dce181f19", PROTECTED_RECTS["OPTIES.PCX"]),
    ArtSpec("Nspel_1.pcx", 1, 181299, 78390,
            "b33c87898e266937f95863d0823531a40bde458da751620991398fe22000a694",
            "617adcfb8a662eb000aeac43e8ee9daa8705d3db7c8cb63015e25600916d2359", PROTECTED_RECTS["Nspel_1.pcx"]),
    ArtSpec("Bedien.pcx", 2, 259689, 182246,
            "b2c23131f68da501c825be9d3becc1b5afd3460242ff0a01ddd0b3e537b028e4",
            "1e41c5db58f0d1012563841ff419753828e813b627fefed33418581d782cbe9d", PROTECTED_RECTS["Bedien.pcx"]),
    ArtSpec("Score.pcx", 3, 441935, 183205,
            "762a56b8683903fc108698a5630aab13171c04b5bdc1bf0b10f5ae026c9ce55c",
            "1e41c5db58f0d1012563841ff419753828e813b627fefed33418581d782cbe9d", PROTECTED_RECTS["Score.pcx"]),
    ArtSpec("Nspel_2.pcx", 4, 625140, 81267,
            "a160364454aa025d63b5f2d8fd99ae2dcb4fce1d77d55dd3b226ce116f9aba00",
            "617adcfb8a662eb000aeac43e8ee9daa8705d3db7c8cb63015e25600916d2359", PROTECTED_RECTS["Nspel_2.pcx"]),
    ArtSpec("hoofd.pcx", 5, 706407, 182025,
            "d92ad74cb34faffc9c6b4ecbcf6b9e88ecf1e5c65582887966a93597aea2d7d7",
            "617adcfb8a662eb000aeac43e8ee9daa8705d3db7c8cb63015e25600916d2359", PROTECTED_RECTS["hoofd.pcx"]),
    ArtSpec("score2.pcx", 6, 888432, 180747,
            "7e1f6c6d5ab1432cb9da35060ce413d17697ac1f0656f52bb44d004f4d474237",
            "1e41c5db58f0d1012563841ff419753828e813b627fefed33418581d782cbe9d", PROTECTED_RECTS["score2.pcx"]),
    ArtSpec("SCORE3.PCX", 7, 1069179, 181166,
            "0035c70947559a972e107257d05a5668b0a5ea87483e1ab0185ca9d92aaede77",
            "1e41c5db58f0d1012563841ff419753828e813b627fefed33418581d782cbe9d", PROTECTED_RECTS["SCORE3.PCX"]),
    ArtSpec("Tstand2.pcx", 8, 1250345, 171395,
            "5b0f6c5c213a21334117a608e13ed41b952e7f37e62981d81a1fbff719fe1ed4",
            "6942430d8700bdbaa45c341e31bd573af734c825e562bb6a0e75f81e1136ac13", PROTECTED_RECTS["Tstand2.pcx"]),
    ArtSpec("Etappe3.PCX", 10, 1613872, 170724,
            "7d9bb67d21eb03117fdab4ddee8b85be7b13fa3bf36feb78351770a736efb420",
            "fd3255e5a261246542f28bfd38836904f0702b8f3ff9a3bd3fce463ce7f57d42", PROTECTED_RECTS["Etappe3.PCX"]),
    ArtSpec("Tstand.pcx", 11, 1784596, 172812,
            "c25fc96cb2fe4ade062595ca69969617d7a33e531c7acbd1979eead0edeb6858",
            "6942430d8700bdbaa45c341e31bd573af734c825e562bb6a0e75f81e1136ac13", PROTECTED_RECTS["Tstand.pcx"]),
    ArtSpec("Etappe1.PCX", 12, 1957408, 170385,
            "dcf6082f4bd548b36fd06825d5ce11fb391561aa6bc0e5ed5c25465a43f44a7e",
            "fd3255e5a261246542f28bfd38836904f0702b8f3ff9a3bd3fce463ce7f57d42", PROTECTED_RECTS["Etappe1.PCX"]),
    ArtSpec("Etappe4.PCX", 13, 2127793, 170823,
            "27efbdd5dc02be873c71215c47b234c8a648d21eef08833b8dab4570f63dbc98",
            "fd3255e5a261246542f28bfd38836904f0702b8f3ff9a3bd3fce463ce7f57d42", PROTECTED_RECTS["Etappe4.PCX"]),
    ArtSpec("Etappe5.PCX", 14, 2298616, 171048,
            "afcac6a858b4ae45433a811b2c5aa70e704207bd7aa309f4f88349d2a35ee57b",
            "fd3255e5a261246542f28bfd38836904f0702b8f3ff9a3bd3fce463ce7f57d42", PROTECTED_RECTS["Etappe5.PCX"]),
    ArtSpec("Etappe6.PCX", 15, 2469664, 170886,
            "0a7791520e7d531ae8f4da0a56d4052387a40c84cdb4ac945762ada5d5567ce2",
            "fd3255e5a261246542f28bfd38836904f0702b8f3ff9a3bd3fce463ce7f57d42", PROTECTED_RECTS["Etappe6.PCX"]),
    ArtSpec("Etappe2.PCX", 16, 2640550, 170670,
            "a6a96799101bb3096e56d7ac766a8ba0ad044de2bb6b29039afe5d5c51586098",
            "fd3255e5a261246542f28bfd38836904f0702b8f3ff9a3bd3fce463ce7f57d42", PROTECTED_RECTS["Etappe2.PCX"]),
)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_pinned(path: Path, pin: tuple[int, str] | None, maximum: int) -> bytes:
    from tools.trial_manifest import validate_ancestors
    if (pin is None or type(pin) is not tuple or len(pin) != 2 or
            type(pin[0]) is not int or not 1 <= pin[0] <= maximum or
            type(pin[1]) is not str or len(pin[1]) != 64):
        raise ValueError("Menu-art mist een geldige vaste bestandspin.")
    path = Path(path)
    validate_ancestors(path)
    if not path.is_file() or path.stat().st_size != pin[0]:
        raise ValueError(f"Menu-artbestand ontbreekt of heeft afwijkende grootte: {path.name}.")
    with path.open("rb") as stream:
        data = stream.read(pin[0] + 1)
    if len(data) != pin[0] or _hash(data) != pin[1]:
        raise ValueError(f"Menu-artbestand wijkt af van de gecontroleerde versie: {path.name}.")
    return data


def _object_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Menu-artmanifest heeft dubbele velden.")
        result[key] = value
    return result


def _read_pack(asset_root: Path) -> tuple[dict, dict[str, bytes]]:
    names = tuple(spec.name for spec in RESOURCE_SPECS)
    if not names or len(set(names)) != len(names) or set(ASSET_PINS) != set(names):
        raise ValueError("Menu-art mist de volledige vaste achtergrondset.")
    data = _read_pinned(Path(asset_root) / "manifest.json", MANIFEST_PIN, MAX_MANIFEST_BYTES)
    try:
        manifest = json.loads(data.decode("utf8"), object_pairs_hook=_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Menu-artmanifest is geen geldig JSON-document.") from exc
    if (type(manifest) is not dict or type(manifest.get("schema")) is not int or
            manifest["schema"] != 1 or manifest.get("profile") != PROFILE or
            manifest.get("native_dimensions") != list(NATIVE_DIMENSIONS) or
            manifest.get("true_hd") is not False or
            type(manifest.get("assets")) is not list or len(manifest["assets"]) != len(names)):
        raise ValueError("Menu-artmanifest heeft een afwijkend profiel of assetcontract.")
    assets = {}
    for spec, record in zip(RESOURCE_SPECS, manifest["assets"]):
        pin = ASSET_PINS[spec.name]
        if (type(record) is not dict or record.get("name") != spec.name or
                record.get("file") != spec.name or record.get("bytes") != pin[0] or
                record.get("sha256") != pin[1] or
                record.get("original_sha256") != spec.sha256 or
                record.get("palette_sha256") != spec.palette_sha256 or
                record.get("protected_rectangles") != [list(rect) for rect in spec.protected_rectangles]):
            raise ValueError("Menu-artmanifest wijkt af van de gepinde resourcereeks.")
        payload = _read_pinned(Path(asset_root) / spec.name, pin, MAX_ASSET_BYTES)
        image = decode_pcx(payload)
        if ((image.width, image.height) != NATIVE_DIMENSIONS or
                _hash(image.palette) != spec.palette_sha256):
            raise ValueError(f"Menu-art heeft gewijzigde geometrie of palet: {spec.name}.")
        assets[spec.name] = payload
    return manifest, assets


def validate_pack(asset_root: Path) -> dict:
    """Validate bounded fixed local assets; no original game is needed or run."""
    manifest, _ = _read_pack(asset_root)
    return {"profile": PROFILE, "asset_count": len(RESOURCE_SPECS),
            "manifest_sha256": MANIFEST_PIN[1], "native_dimensions": list(NATIVE_DIMENSIONS),
            "true_hd": False, "runtime_verified": False}


def validate_replacement(original_data: bytes, replacement_data: bytes,
                         protected_rectangles: tuple[tuple[int, int, int, int], ...]) -> dict:
    """Prove palette/layout/masks and every protected pixel, not just counts."""
    original = decode_pcx(original_data)
    replacement = decode_pcx(replacement_data)
    if ((original.width, original.height) != NATIVE_DIMENSIONS or
            (replacement.width, replacement.height) != NATIVE_DIMENSIONS or
            replacement.header != original.header or replacement.palette != original.palette or
            replacement.row_padding != original.row_padding):
        raise ValueError("Menu-art moet oorspronkelijke afmetingen/header/palet/padding behouden.")
    for candidate in (0, 255):
        if any((before == candidate) != (after == candidate)
               for before, after in zip(original.pixels, replacement.pixels)):
            raise ValueError(f"Menu-art moet het exacte index-{candidate}-masker behouden.")
    if type(protected_rectangles) is not tuple or not protected_rectangles:
        raise ValueError("Menu-art vereist vaste beschermde UI-rechthoeken.")
    for rect in protected_rectangles:
        if (type(rect) is not tuple or len(rect) != 4 or any(type(v) is not int for v in rect)):
            raise ValueError("Menu-art heeft een ongeldige beschermde UI-rechthoek.")
        x, y, width, height = rect
        if min(x, y) < 0 or min(width, height) <= 0 or x + width > original.width or y + height > original.height:
            raise ValueError("Menu-art heeft een beschermde UI-rechthoek buiten het beeld.")
        for row in range(y, y + height):
            start = row * original.width + x
            if original.pixels[start:start + width] != replacement.pixels[start:start + width]:
                raise ValueError("Menu-art heeft oorspronkelijke beschermde UI-pixels gewijzigd.")
    return {"dimensions": list(NATIVE_DIMENSIONS), "header_unchanged": True,
            "palette_unchanged": True, "padding_unchanged": True,
            "index0_mask_unchanged": True, "index255_mask_unchanged": True,
            "protected_rectangles": [list(rect) for rect in protected_rectangles],
            "changed_pixels": sum(a != b for a, b in zip(original.pixels, replacement.pixels)),
            "runtime_verified": False}


def _replace_many(archive: resource_archive.ResourceArchive,
                  replacements: dict[str, bytes]) -> resource_archive.ResourceArchive:
    resource_archive.serialize_archive(archive)
    if not replacements or not set(replacements) <= {entry.name for entry in archive.entries}:
        raise ValueError("Menu-artvervanging noemt ontbrekende of lege resources.")
    updated_index = bytearray(archive.index_bytes)
    updated_image = bytearray(archive.image_bytes[:archive.entries[0].offset])
    for entry in archive.entries:
        payload = replacements.get(entry.name, resource_archive.entry_bytes(archive, entry.name))
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= resource_archive.MAX_RESOURCE_BYTES:
            raise ValueError("Menu-artpayload valt buiten de resourcelimiet.")
        struct.pack_into("<I", updated_index, 2 + entry.index * 24 + 20, len(updated_image))
        updated_image.extend(payload)
    updated = resource_archive.parse_archive(bytes(updated_index), bytes(updated_image))
    for old, new in zip(archive.entries, updated.entries):
        if old.raw_name != new.raw_name or (
                old.name not in replacements and
                resource_archive.entry_bytes(archive, old.name) != resource_archive.entry_bytes(updated, new.name)):
            raise ValueError("Menu-artvervanging heeft een niet-geselecteerde resource of naam gewijzigd.")
    return updated


def plan_fixes(source: Path, asset_root: Path) -> list[dict]:
    """Return two in-memory plans after all source/asset checks; never write."""
    originals = {name: _read_pinned(Path(source) / name, pin, MAX_SOURCE_BYTES)
                 for name, pin in EXPECTED_FILES.items()}
    _, replacements = _read_pack(asset_root)
    archive = resource_archive.parse_archive(originals["A2MRCS.IND"], originals["A2MRCS.IMG"])
    if len(archive.entries) != EXPECTED_RESOURCE_COUNT:
        raise ValueError("Menu-artbron heeft een afwijkend resourceaantal.")
    evidence = []
    for spec in RESOURCE_SPECS:
        entry = resource_archive.find_entry(archive, spec.name)
        original = resource_archive.entry_bytes(archive, entry.name)
        if ((entry.index, entry.offset, entry.size, _hash(original)) !=
                (spec.index, spec.offset, spec.size, spec.sha256)):
            raise ValueError(f"Menu-artbronresource wijkt af: {spec.name}.")
        proof = validate_replacement(original, replacements[spec.name], spec.protected_rectangles)
        evidence.append({"name": spec.name, "index": spec.index, "before_sha256": spec.sha256,
                         "after_sha256": _hash(replacements[spec.name]), **proof})
    updated = _replace_many(archive, replacements)
    preserved = [{"name": entry.name, "index": entry.index, "sha256":
                  _hash(resource_archive.entry_bytes(archive, entry.name))}
                 for entry in archive.entries if entry.name not in replacements]
    shared = {"purpose": "menu-art-refresh-native-v1", "menu_art_profile": PROFILE,
              "resources": evidence, "native_dimensions": list(NATIVE_DIMENSIONS),
              "true_hd": False, "runtime_verified": False,
              "preserved_resources": preserved, "other_resources_unchanged": True,
              "sprite_archives_unchanged": True, "menu_binary_unchanged": True}
    return [{**shared, "path": name, "source_path": str(Path(source) / name),
             "before_sha256": _hash(originals[name]), "after_sha256": _hash(data), "data": data}
            for name, data in (("A2MRCS.IND", updated.index_bytes), ("A2MRCS.IMG", updated.image_bytes))]

