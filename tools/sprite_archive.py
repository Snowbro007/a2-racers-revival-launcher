"""Read-only planning for the pinned A2-I GAMESPR native-size UI sprite.

GAMESPR.IND is a little-endian count and offset table. GAMESPR.IMG repeats
the count and stores eight-byte geometry headers followed by indexed pixels.
There is no embedded palette. Native drawing copies sprite dimensions rather
than scaling them; replacement therefore preserves the entire original header.
Only a separately pinned own asset may enter an independent trial copy.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct

from tools import meter_texture_specs as meters

EXPECTED_FILES = {
    "GAMESPR.IND": (1330, "6a58af781892d12e05b563e370b5fd0f949cb4d3b093fcd7edd251f811866b51"),
    "GAMESPR.IMG": (3470625, "8a83d3abf00a3f99c0ed03f9379e1216a17d9895ef8fff05602a4bb950d333d6"),
}
TICKET_INDEX = 301  # Zero-based archive index; native loader resource ID is 302.
TICKET_OFFSET = 3121479
TICKET_BYTES = 62088
TICKET_SHA256 = "389e3f333a3f456a69b596df93e222987ed83338628b92a254b1c9d6d6031d1f"
TICKET_DIMENSIONS = (320, 194)
TICKET_ANCHOR = (160, 97)
TICKET_HEADER = bytes.fromhex("4001c200a0006100")
NATIVE_PALETTE_SHA256 = "6a42fe69565ef5be1d8ad80b8ebd541a2fc07672739ce2c429b4ddb971fcf325"
# Filled only after the final own raw sprite has been converted and audited.
EXPECTED_HD_TICKET_SHA256: str | None = "206e718b412d00f3606a4929689e8e8d8d421bb632a07e931752b18731db548d"
EXPECTED_AMOUNT_BACKGROUND_INDEX: int | None = 174
AMOUNT_RECT = (230, 130, 48, 13)
ALLOWED_REPLACEMENT_INDICES = (301,) + meters.METER_INDICES
MAX_ENTRIES = 4096
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_DIMENSION = 4096
MAX_RESOURCE_BYTES = 16 * 1024 * 1024
PROFILES = ("original", "hd-scenery-cockpit", "hd-expanded-v1")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SpriteImage:
    width: int
    height: int
    anchor_x: int
    anchor_y: int
    header: bytes
    pixels: bytes


@dataclass(frozen=True)
class SpriteEntry:
    index: int
    offset: int
    size: int
    width: int
    height: int
    anchor_x: int
    anchor_y: int
    header: bytes


@dataclass(frozen=True)
class SpriteArchive:
    index_bytes: bytes
    image_bytes: bytes
    entries: tuple[SpriteEntry, ...]


def decode_sprite(data: bytes) -> SpriteImage:
    """Decode a bounded raw sprite without executing or changing game files."""
    if not isinstance(data, bytes) or not 8 <= len(data) <= MAX_RESOURCE_BYTES:
        raise ValueError("GAMESPR-sprite ontbreekt of overschrijdt de resourcelimiet.")
    width, height, anchor_x, anchor_y = struct.unpack_from("<HHhh", data)
    if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
        raise ValueError("GAMESPR-sprite heeft ongeldige afmetingen.")
    if len(data) != 8 + width * height:
        raise ValueError("GAMESPR-sprite vereist exact acht headerbytes en breedte×hoogte pixels.")
    return SpriteImage(width, height, anchor_x, anchor_y, data[:8], data[8:])


def parse_archive(index_bytes: bytes, image_bytes: bytes) -> SpriteArchive:
    """Parse the exact count/offset format, retaining all source bytes."""
    if not isinstance(index_bytes, bytes) or not isinstance(image_bytes, bytes):
        raise ValueError("GAMESPR vereist twee ongewijzigde bytestrings.")
    if len(index_bytes) < 2 or not 2 <= len(image_bytes) <= MAX_IMAGE_BYTES:
        raise ValueError("GAMESPR ontbreekt of overschrijdt de bestandsgroottelimiet.")
    count = struct.unpack_from("<H", index_bytes)[0]
    if not 1 <= count <= MAX_ENTRIES or len(index_bytes) != 2 + count * 4:
        raise ValueError("GAMESPR-count past niet exact bij de vier-byte indexrecords.")
    if struct.unpack_from("<H", image_bytes)[0] != count:
        raise ValueError("GAMESPR-counts in IND en IMG verschillen.")
    offsets = struct.unpack_from(f"<{count}I", index_bytes, 2)
    if offsets[0] != 2 or any(offset >= len(image_bytes) for offset in offsets):
        raise ValueError("GAMESPR-offsets beginnen niet op byte twee of vallen buiten IMG.")
    if any(current >= following for current, following in zip(offsets, offsets[1:])):
        raise ValueError("GAMESPR-offsets zijn niet strikt oplopend.")
    entries = []
    for index, offset in enumerate(offsets):
        end = offsets[index + 1] if index + 1 < count else len(image_bytes)
        sprite = decode_sprite(image_bytes[offset:end])
        entries.append(SpriteEntry(index, offset, end - offset, sprite.width, sprite.height,
                                   sprite.anchor_x, sprite.anchor_y, sprite.header))
    return SpriteArchive(index_bytes, image_bytes, tuple(entries))


def serialize_archive(archive: SpriteArchive) -> tuple[bytes, bytes]:
    """Reject forged metadata; an unchanged archive roundtrips byte-exactly."""
    if not isinstance(archive, SpriteArchive):
        raise ValueError("GAMESPR-object heeft geen gecontroleerd archiveformaat.")
    validated = parse_archive(archive.index_bytes, archive.image_bytes)
    if validated.entries != archive.entries:
        raise ValueError("GAMESPR-object komt niet overeen met zijn oorspronkelijke indexbytes.")
    return archive.index_bytes, archive.image_bytes


def find_entry(archive: SpriteArchive, index: int) -> SpriteEntry:
    if type(index) is not int or not 0 <= index < len(archive.entries):
        raise ValueError("GAMESPR-spriteindex ontbreekt of is ongeldig.")
    return archive.entries[index]


def entry_bytes(archive: SpriteArchive, index: int) -> bytes:
    entry = find_entry(archive, index)
    return archive.image_bytes[entry.offset:entry.offset + entry.size]


def sprite_asset_specs(profile: str = "hd-scenery-cockpit") -> tuple[dict, ...]:
    """Fixed local asset contracts shared by availability checks and planning."""
    if profile == "original":
        return ()
    if profile not in ("hd-scenery-cockpit", "hd-expanded-v1"):
        raise ValueError("Onbekend GAMESPR-spriteprofiel.")
    ticket = ({
        "path": "local/mods/a2racer1/ticket-hd-v1.spr",
        "sha256": EXPECTED_HD_TICKET_SHA256,
        "dimensions": TICKET_DIMENSIONS,
        "index": TICKET_INDEX,
        "header_hex": TICKET_HEADER.hex(),
        "anchor": TICKET_ANCHOR,
        "native_palette_sha256": NATIVE_PALETTE_SHA256,
        "protected_regions": ({"rect": AMOUNT_RECT,
                               "palette_index": EXPECTED_AMOUNT_BACKGROUND_INDEX},),
        "resource": {"index": TICKET_INDEX, "offset": TICKET_OFFSET,
                     "size": TICKET_BYTES, "sha256": TICKET_SHA256,
                     "dimensions": TICKET_DIMENSIONS, "anchor": TICKET_ANCHOR,
                     "header_hex": TICKET_HEADER.hex()},
    },)
    return ticket + meters.meter_asset_specs() if profile == "hd-expanded-v1" else ticket


def validate_asset(data: bytes, spec: dict) -> SpriteImage:
    """Validate the pinned raw asset and its empty dynamic-number rectangle."""
    sprite = decode_sprite(data)
    if spec.get("sha256") is None or _hash(data) != spec["sha256"]:
        raise ValueError("HD-sprite heeft nog geen gecontroleerde assetpin of wijkt daarvan af.")
    if ((sprite.width, sprite.height) != tuple(spec["dimensions"]) or
            (sprite.anchor_x, sprite.anchor_y) != tuple(spec["anchor"]) or
            sprite.header.hex() != spec["header_hex"]):
        raise ValueError("HD-sprite moet de oorspronkelijke afmetingen, ankers en header behouden.")
    for region in spec.get("protected_regions", ()):
        x, y, width, height = region["rect"]
        index = region["palette_index"]
        if type(index) is not int or not 1 <= index <= 254:
            raise ValueError("HD-sprite mist een gecontroleerde achtergrondindex voor het boetebedrag.")
        if (min(x, y) < 0 or min(width, height) <= 0 or
                x + width > sprite.width or y + height > sprite.height):
            raise ValueError("HD-sprite heeft een ongeldige beschermde bedragzone.")
        if any(sprite.pixels[row * sprite.width + x:row * sprite.width + x + width] !=
               bytes([index]) * width for row in range(y, y + height)):
            raise ValueError("HD-sprite moet de dynamische bedragzone egaal en leeg houden.")
    return sprite


def _validate_replacement(original_data: bytes, data: bytes) -> SpriteImage:
    original = decode_sprite(original_data)
    replacement = decode_sprite(data)
    if replacement.header != original.header:
        raise ValueError("GAMESPR-vervanging moet de volledige oorspronkelijke header behouden.")
    # Index zero and 255 have distinct black/magenta palette colours. Preserve
    # both masks conservatively; no unproven colour-key semantics are assumed.
    for candidate in (0, 255):
        if any((before == candidate) != (after == candidate)
               for before, after in zip(original.pixels, replacement.pixels)):
            raise ValueError(f"GAMESPR-vervanging moet het exacte index-{candidate}-masker behouden.")
    return replacement


def _validate_original_entry(archive: SpriteArchive, spec: dict) -> bytes:
    """Validate independent metadata pins even after the whole archive pin."""
    entry = find_entry(archive, spec["index"])
    resource = spec["resource"]
    original_data = entry_bytes(archive, spec["index"])
    if (entry.index != resource["index"] or entry.offset != resource["offset"] or
            entry.size != resource["size"] or _hash(original_data) != resource["sha256"] or
            (entry.width, entry.height) != tuple(resource["dimensions"]) or
            (entry.anchor_x, entry.anchor_y) != tuple(resource["anchor"]) or
            entry.header.hex() != resource["header_hex"]):
        raise ValueError("Gepinde GAMESPR-sprite wijkt af van de onderzochte versie.")
    return original_data


def _validate_meter_animation(archive: SpriteArchive, replacements: dict[int, bytes]) -> list[dict]:
    """Preserve every animation pixel and require identical static artwork.

    The mask is the union of positions that differ across any original frame,
    including both halves of the 40-frame speedometer. This conservatively
    protects more than only the visible needle and does not infer calibration.
    Changed static pixels are limited to the pinned neutral-grey palette range
    so resampled magenta cutout colours cannot become visible purple rims.
    Every group is validated before any archive bytearray is made or written.
    """
    selected = set(replacements)
    groups = [group for group in meters.METER_GROUPS if selected.intersection(group["indices"])]
    if not groups:
        return []
    specs = {spec["index"]: spec for spec in meters.meter_asset_specs()}
    evidence = []
    for group in groups:
        indices = tuple(group["indices"])
        if not set(indices).issubset(selected):
            raise ValueError("Een metergroep vereist exact alle oorspronkelijke animatieframes samen.")
        originals = [decode_sprite(_validate_original_entry(archive, specs[index])) for index in indices]
        updated = [_validate_replacement(entry_bytes(archive, index), replacements[index])
                   for index in indices]
        if len({frame.header for frame in originals}) != 1:
            raise ValueError("Metergroep heeft afwijkende oorspronkelijke geometrieheaders.")
        changing = 0
        for position, original_values in enumerate(zip(*(frame.pixels for frame in originals))):
            updated_values = tuple(frame.pixels[position] for frame in updated)
            if len(set(original_values)) > 1:
                changing += 1
                if updated_values != original_values:
                    raise ValueError("HD-meter moet iedere oorspronkelijke wijzer- en animatiepixel exact behouden.")
            elif len(set(updated_values)) != 1:
                raise ValueError("HD-meter moet statische pixels in alle frames identiek houden.")
            elif (updated_values[0] != original_values[0] and
                  updated_values[0] not in meters.RIM_PALETTE_INDICES):
                raise ValueError("HD-meterrand mag uitsluitend de gecontroleerde neutrale grijstinten gebruiken.")
        evidence.append({"group": group["name"], "indices": list(indices),
                         "dimensions": list(group["dimensions"]), "anchor": list(group["anchor"]),
                         "protected_animation_pixels": changing,
                         "animation_pixels_unchanged": True,
                         "shared_static_pixels_consistent": True,
                         "native_geometry_unchanged": True, "true_hd_ui_scaling": False})
    return evidence


def replace_sprites(archive: SpriteArchive, replacements: dict[int, bytes]) -> tuple[SpriteArchive, dict]:
    """Bounded in-memory replacements, preserving offsets and other records."""
    serialize_archive(archive)
    if (not isinstance(replacements, dict) or not replacements or
            any(type(index) is not int or index not in ALLOWED_REPLACEMENT_INDICES
                for index in replacements)):
        raise ValueError("GAMESPR accepteert uitsluitend de onderzochte spriteindices.")
    validated = []
    for index, data in replacements.items():
        entry = find_entry(archive, index)
        replacement = _validate_replacement(entry_bytes(archive, index), data)
        validated.append((entry, data, replacement))
    meter_evidence = _validate_meter_animation(archive, replacements)
    updated_image = bytearray(archive.image_bytes)
    for entry, data, _ in validated:
        updated_image[entry.offset:entry.offset + entry.size] = data
    updated = parse_archive(archive.index_bytes, bytes(updated_image))
    preserved = []
    for entry in archive.entries:
        if entry.index in replacements:
            continue
        original_data = entry_bytes(archive, entry.index)
        if entry_bytes(updated, entry.index) != original_data:
            raise ValueError("GAMESPR-vervanging heeft een ongekozen sprite gewijzigd.")
        preserved.append({"index": entry.index, "offset": entry.offset,
                          "size": entry.size, "sha256": _hash(original_data)})
    evidence = {
        "replacements": [{"index": entry.index, "offset": entry.offset, "size": entry.size,
                          "before_sha256": _hash(entry_bytes(archive, entry.index)),
                          "after_sha256": _hash(data), "dimensions": [sprite.width, sprite.height],
                          "anchor": [sprite.anchor_x, sprite.anchor_y],
                          "header_unchanged": True, "index_0_mask_unchanged": True,
                          "index_255_mask_unchanged": True}
                         for entry, data, sprite in validated],
        "index_bytes_unchanged": updated.index_bytes == archive.index_bytes,
        "other_resources_unchanged": True,
        "preserved_resources": preserved,
        "palette_embedded": False,
        "native_palette_sha256": NATIVE_PALETTE_SHA256,
        "runtime_verified": False,
    }
    if meter_evidence:
        evidence["meter_animation_groups"] = meter_evidence
        evidence["true_hd_ui_scaling"] = False
    return updated, evidence


def read_pinned_archive(source: Path) -> SpriteArchive:
    contents = {}
    for name, (size, expected_hash) in EXPECTED_FILES.items():
        path = source / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise ValueError(f"GAMESPR-bron ontbreekt of heeft afwijkende grootte: {name}.")
        data = path.read_bytes()
        if _hash(data) != expected_hash:
            raise ValueError(f"Onbekende GAMESPR-bronversie: {name}.")
        contents[name] = data
    return parse_archive(contents["GAMESPR.IND"], contents["GAMESPR.IMG"])


def plan_fixes(source: Path, asset_paths: dict[int, Path] | None = None,
               profile: str = "hd-scenery-cockpit") -> list[dict]:
    """Read-only plans for game_fixes.apply_fixes on an independent trial."""
    specs = sprite_asset_specs(profile)
    if profile == "original":
        if asset_paths is not None:
            raise ValueError("Het originele spriteprofiel accepteert geen vervangbestanden.")
        return []
    indices = {spec["index"] for spec in specs}
    if (not isinstance(asset_paths, dict) or set(asset_paths) != indices or
            any(type(index) is not int for index in asset_paths) or
            any(not isinstance(path, Path) for path in asset_paths.values())):
        raise ValueError("HD-spriteprofiel vereist exact alle vaste spritebestanden samen.")
    archive = read_pinned_archive(source)
    replacements = {}
    for spec in specs:
        index = spec["index"]
        _validate_original_entry(archive, spec)
        path = asset_paths[index]
        if (path.is_symlink() or not path.is_file() or
                not 8 <= path.stat().st_size <= MAX_RESOURCE_BYTES):
            raise ValueError("HD-sprite ontbreekt of heeft een ongecontroleerde grootte.")
        data = path.read_bytes()
        validate_asset(data, spec)
        replacements[index] = data
    updated, evidence = replace_sprites(archive, replacements)
    for item, spec in zip(evidence["replacements"], specs):
        item["asset_sha256"] = spec["sha256"]
        item["protected_regions"] = [{"rect": list(region["rect"]),
                                      "palette_index": region["palette_index"]}
                                     for region in spec["protected_regions"]]
    return [{"path": name, "purpose": "hd-native-ui-sprites-experimental", "profile": profile,
             "runtime_verified": False, "source_path": str(source / name),
             "before_sha256": _hash(before), "after_sha256": _hash(after), "data": after,
             "sprite_evidence": evidence}
            for name, before, after in (("GAMESPR.IND", archive.index_bytes, updated.index_bytes),
                                        ("GAMESPR.IMG", archive.image_bytes, updated.image_bytes))]
