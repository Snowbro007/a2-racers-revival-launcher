"""Read-only RCS planning for opt-in A2-I textures in a fresh trial.

The source index/image pair and selected resource are pinned independently.
Parsing and replacement operate in memory; game_fixes.apply_fixes is responsible
for validating independent trial copies before any files are written.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct

from tools.pcx_codec import decode_pcx

EXPECTED_FILES = {
    "RCS.IND": (5330, "077f36ef320899f354a8d1322edf3ae12e3b727f4ba83171c7e64b09e5384729"),
    "RCS.IMG": (9603035, "028512563a32aa76e020d30b508f8208a6e9d22ebea4127e33b78afe641a4090"),
}
ROAD_NAME = "2baans.pcx"
ROAD_INDEX = 119
ROAD_OFFSET = 1069984
ROAD_BYTES = 20036
ROAD_SHA256 = "aa166c1a981a9cdab6b3b90a06c95de322a33f8794d33f3ca4a02d896cb68f16"
# Set only after the final own asset is converted and statically audited. A
# missing pin refuses preparation; arbitrary user PCX files are never trusted.
EXPECTED_HD_ROAD_SHA256: str | None = "3171ba0e5ba3baab8491443809913f7c113dfe59e39d6c814974ae62a4a64b4d"
EXPECTED_HD_ROAD_512_SHA256: str | None = "deb5a4503ca6344d41e885ddec3e5ca7dfe42e926b387a0c8e142a3e902772f3"
EXPECTED_HD_ROAD_1024_SHA256: str | None = "225a1b23594602212a1e513d285e3b80a7e2282a7a48b97ba8b45440ff01fa9a"
EXPECTED_HD_GRASS_512_SHA256: str | None = "bb35e026d01e8aff3f28633a8fed4b242a420d2227ab0ea9edf5371028726628"
EXPECTED_DASHBOARD_SHA256: str | None = "1949e4f2aa38bd3f76173caf9da36eb06da70458df1f7f77026d5d476c6922ba"
DASHBOARD_NAME = "SURSCRN.pcx"
DASHBOARD_INDEX = 97
DASHBOARD_OFFSET = 774203
DASHBOARD_BYTES = 40505
DASHBOARD_SHA256 = "8be695e8fd518ed2f4f57250edf4aae0e9a20f55322ee6d76e035ed9493677c8"
# Existing native sprite frames overwrite these exact regions. Retaining their
# backgrounds avoids seams and never changes moving needles or steering frames.
DASHBOARD_PROTECTED_RECTS = ((0, 267, 640, 36), (44, 348, 330, 132),
                             (135, 319, 70, 68), (215, 320, 71, 69),
                             (292, 328, 48, 49), (89, 329, 40, 45))
# Separate resource pins are required even though the whole archive is pinned.
# Unknown fields deliberately refuse the new opt-in profile until static audit.
GRASS_NAME = "grass2.pcx"
GRASS_INDEX = 124
GRASS_OFFSET: int | None = 1143284
GRASS_BYTES: int | None = 61717
GRASS_SHA256: str | None = "57eece7d43399c7985f26f6be820daae6ec6572c7a9017aee765978c0b55075f"
MAX_ENTRIES = 4096
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_RESOURCE_BYTES = 8 * 1024 * 1024
PROFILES = ("original", "hd-road-256", "hd-road-512", "hd-scenery-1024", "hd-scenery-cockpit", "hd-expanded-v1")


def texture_asset_spec(profile: str) -> dict:
    """Return the shared fixed local asset contract; this does not read files.

    Availability checks and trial preparation must use the same profile pin.
    Original has no replacement asset. A missing HD pin refuses planning even
    when a syntactically valid PCX happens to occupy the documented local path.
    """
    if profile == "original":
        return {"path": None, "sha256": None, "dimensions": (128, 128)}
    if profile == "hd-road-256":
        return {"path": "local/mods/a2racer1/road-hd-v1.pcx", "sha256": EXPECTED_HD_ROAD_SHA256,
                "dimensions": (256, 256)}
    if profile == "hd-road-512":
        return {"path": "local/mods/a2racer1/road-hd-v2-512.pcx", "sha256": EXPECTED_HD_ROAD_512_SHA256,
                "dimensions": (512, 512)}
    if profile in ("hd-scenery-1024", "hd-scenery-cockpit", "hd-expanded-v1"):
        return {"path": "local/mods/a2racer1/road-hd-v3-1024.pcx", "sha256": EXPECTED_HD_ROAD_1024_SHA256,
                "dimensions": (1024, 1024)}
    raise ValueError("Onbekend RCS-textureprofiel.")


def texture_asset_specs(profile: str) -> tuple[dict, ...]:
    """Fixed replacement contracts, independently copied for each request.

    The legacy singular contract remains usable for the three original choices.
    This plural contract is required when a profile changes multiple resources.
    Missing asset/resource pins never imply availability or successful planning.
    """
    if profile == "hd-expanded-v1":
        from tools.expanded_texture_specs import expanded_asset_specs
        return (*texture_asset_specs("hd-scenery-cockpit"), *expanded_asset_specs())
    spec = texture_asset_spec(profile)
    if profile == "original":
        return ()
    road = {**spec, "resource": {
        "name": ROAD_NAME, "index": ROAD_INDEX, "offset": ROAD_OFFSET,
        "size": ROAD_BYTES, "sha256": ROAD_SHA256, "dimensions": (128, 128)}}
    if profile not in ("hd-scenery-1024", "hd-scenery-cockpit"):
        return (road,)
    specs = (road, {
        "path": "local/mods/a2racer1/grass2-hd-v1-512.pcx",
        "sha256": EXPECTED_HD_GRASS_512_SHA256, "dimensions": (512, 512),
        "resource": {"name": GRASS_NAME, "index": GRASS_INDEX, "offset": GRASS_OFFSET,
                     "size": GRASS_BYTES, "sha256": GRASS_SHA256, "dimensions": (256, 256)}})
    if profile == "hd-scenery-1024":
        return specs
    return (*specs, {
        "path": "local/mods/a2racer1/dashboard-native-v1.pcx",
        "sha256": EXPECTED_DASHBOARD_SHA256, "dimensions": (640, 480),
        "native_overlay": True, "protected_rectangles": DASHBOARD_PROTECTED_RECTS,
        "resource": {"name": DASHBOARD_NAME, "index": DASHBOARD_INDEX,
                     "offset": DASHBOARD_OFFSET, "size": DASHBOARD_BYTES,
                     "sha256": DASHBOARD_SHA256, "dimensions": (640, 480)}})


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ResourceEntry:
    index: int
    name: str
    raw_name: bytes
    offset: int
    size: int


@dataclass(frozen=True)
class ResourceArchive:
    index_bytes: bytes
    image_bytes: bytes
    entries: tuple[ResourceEntry, ...]


def parse_archive(index_bytes: bytes, image_bytes: bytes) -> ResourceArchive:
    """Parse names/offsets while retaining every original byte, including filler."""
    if not isinstance(index_bytes, bytes) or not isinstance(image_bytes, bytes):
        raise ValueError("RCS vereist twee ongewijzigde bytestrings.")
    if len(index_bytes) < 2 or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("RCS ontbreekt of overschrijdt de bestandsgroottelimiet.")
    count = struct.unpack_from("<H", index_bytes)[0]
    if not 1 <= count <= MAX_ENTRIES or len(index_bytes) != 2 + count * 24:
        raise ValueError("RCS-count past niet exact bij de 24-byte indexrecords.")
    records = []
    seen_names = set()
    for entry_index in range(count):
        raw_name, offset = struct.unpack_from("<20sI", index_bytes, 2 + entry_index * 24)
        name_bytes, separator, _ = raw_name.partition(b"\0")
        if (not separator or not name_bytes or
                any(value < 32 or value >= 127 for value in name_bytes)):
            raise ValueError("RCS-entry mist een begrensde ASCII-naam.")
        name = name_bytes.decode("ascii")
        if any(char in name for char in "/\\:") or name in {".", ".."} or name.casefold() in seen_names:
            raise ValueError("RCS bevat een onveilige of dubbele resourcenaam.")
        seen_names.add(name.casefold())
        if offset >= len(image_bytes) or records and offset <= records[-1][2]:
            raise ValueError("RCS-offsets zijn niet strikt oplopend binnen IMG.")
        records.append((name, raw_name, offset))
    entries = tuple(ResourceEntry(entry_index, name, raw_name, offset,
                                 (records[entry_index + 1][2] if entry_index + 1 < count else len(image_bytes)) - offset)
                    for entry_index, (name, raw_name, offset) in enumerate(records))
    return ResourceArchive(index_bytes, image_bytes, entries)


def serialize_archive(archive: ResourceArchive) -> tuple[bytes, bytes]:
    """An unchanged parsed archive roundtrips byte-exactly; no name normalization."""
    validated = parse_archive(archive.index_bytes, archive.image_bytes)
    if validated.entries != archive.entries:
        raise ValueError("RCS-object komt niet overeen met zijn ongewijzigde indexbytes.")
    return archive.index_bytes, archive.image_bytes


def find_entry(archive: ResourceArchive, name: str) -> ResourceEntry:
    if not isinstance(name, str):
        raise ValueError("RCS-resourcenaam moet tekst zijn.")
    matches = [entry for entry in archive.entries if entry.name.casefold() == name.casefold()]
    if len(matches) != 1:
        raise ValueError("RCS-resourcenaam ontbreekt of is niet uniek.")
    return matches[0]


def entry_bytes(archive: ResourceArchive, name: str) -> bytes:
    entry = find_entry(archive, name)
    return archive.image_bytes[entry.offset:entry.offset + entry.size]


def replace_entry(archive: ResourceArchive, name: str, data: bytes) -> tuple[ResourceArchive, dict]:
    """Replace one payload; update following offsets and prove other bytes equal."""
    serialize_archive(archive)
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_RESOURCE_BYTES:
        raise ValueError("RCS-vervanging ontbreekt of overschrijdt de resourcelimiet.")
    selected = find_entry(archive, name)
    difference = len(data) - selected.size
    if len(archive.image_bytes) + difference > MAX_IMAGE_BYTES:
        raise ValueError("Vervangen RCS.IMG overschrijdt de bestandsgroottelimiet.")
    updated_image = (archive.image_bytes[:selected.offset] + data +
                     archive.image_bytes[selected.offset + selected.size:])
    updated_index = bytearray(archive.index_bytes)
    for entry in archive.entries[selected.index + 1:]:
        struct.pack_into("<I", updated_index, 2 + entry.index * 24 + 20, entry.offset + difference)
    updated = parse_archive(bytes(updated_index), updated_image)
    preserved = []
    for before, after in zip(archive.entries, updated.entries):
        if before.raw_name != after.raw_name:
            raise ValueError("RCS-vervanging heeft naam/filler gewijzigd.")
        if before.index == selected.index:
            continue
        before_data = archive.image_bytes[before.offset:before.offset + before.size]
        after_data = updated.image_bytes[after.offset:after.offset + after.size]
        if before_data != after_data:
            raise ValueError("RCS-vervanging heeft een andere resource gewijzigd.")
        preserved.append({"index": before.index, "name": before.name, "size": before.size,
                          "sha256": _hash(before_data)})
    evidence = {
        "entry_index": selected.index, "name": selected.name, "offset": selected.offset,
        "before_size": selected.size, "after_size": len(data), "offset_delta": difference,
        "before_sha256": _hash(entry_bytes(archive, name)), "after_sha256": _hash(data),
        "other_resources_unchanged": True, "preserved_resources": preserved,
        "name_filler_unchanged": True, "runtime_verified": False,
    }
    return updated, evidence


def read_pinned_archive(source: Path) -> ResourceArchive:
    contents = {}
    for name, (size, expected_hash) in EXPECTED_FILES.items():
        path = source / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise ValueError(f"RCS-bron ontbreekt of heeft afwijkende grootte: {name}.")
        contents[name] = path.read_bytes()
        if _hash(contents[name]) != expected_hash:
            raise ValueError(f"Onbekende RCS-bronversie: {name}.")
    archive = parse_archive(contents["RCS.IND"], contents["RCS.IMG"])
    road = find_entry(archive, ROAD_NAME)
    if (road.index != ROAD_INDEX or road.offset != ROAD_OFFSET or road.size != ROAD_BYTES or
            _hash(entry_bytes(archive, ROAD_NAME)) != ROAD_SHA256):
        raise ValueError("Gepinde RCS-wegtexture wijkt af van de onderzochte versie.")
    return archive


def _plan_multiple_fixes(source: Path, texture_paths: dict[str, Path] | None,
                         profile: str) -> list[dict]:
    """Validate every replacement before composing one atomic archive plan."""
    specs = texture_asset_specs(profile)
    names = {spec["resource"]["name"] for spec in specs}
    if (not isinstance(texture_paths, dict) or set(texture_paths) != names or
            any(not isinstance(path, Path) for path in texture_paths.values())):
        raise ValueError("HD-omgeving vereist exact alle vaste texturebestanden samen.")
    archive = read_pinned_archive(source)
    replacements = []
    for spec in specs:
        resource = spec["resource"]
        name = resource["name"]
        entry = find_entry(archive, name)
        original_data = entry_bytes(archive, name)
        if (resource["sha256"] is None or entry.index != resource["index"] or
                entry.offset != resource["offset"] or entry.size != resource["size"] or
                _hash(original_data) != resource["sha256"]):
            raise ValueError(f"Gepinde RCS-texture wijkt af van de onderzochte versie: {name}.")
        path = texture_paths[name]
        if (path.is_symlink() or not path.is_file() or
                not 1 <= path.stat().st_size <= MAX_RESOURCE_BYTES):
            raise ValueError(f"HD-omgevingtexture ontbreekt of heeft een ongecontroleerde grootte: {name}.")
        data = path.read_bytes()
        if spec["sha256"] is None or _hash(data) != spec["sha256"]:
            raise ValueError(f"HD-omgevingtexture heeft nog geen gecontroleerde assetpin of wijkt daarvan af: {name}.")
        original = decode_pcx(original_data)
        replacement = decode_pcx(data)
        if ((original.width, original.height) != tuple(resource["dimensions"]) or
                (replacement.width, replacement.height) != tuple(spec["dimensions"])):
            width, height = spec["dimensions"]
            raise ValueError(f"Deze HD-proef vereist exact {width}×{height} voor {name}.")
        resized_header_fields = {8, 9, 10, 11, 66, 67}
        if any(before != after for offset, (before, after) in
               enumerate(zip(original.header, replacement.header)) if offset not in resized_header_fields):
            raise ValueError(f"HD-omgevingtexture moet de oorspronkelijke PCX-headermetadata behouden: {name}.")
        if struct.unpack_from("<H", replacement.header, 66)[0] != replacement.width or replacement.row_padding:
            raise ValueError(f"HD-omgevingtexture vereist BytesPerLine gelijk aan de breedte, zonder rijpadding: {name}.")
        if replacement.palette != original.palette:
            raise ValueError(f"HD-omgevingtexture moet het oorspronkelijke 256-kleurenpalet behouden: {name}.")
        original_indices = set(original.pixels)
        replacement_indices = set(replacement.pixels)
        for candidate in (0, 255):
            if candidate not in original_indices and candidate in replacement_indices:
                raise ValueError(f"HD-omgevingtexture introduceert ongecontroleerde paletindex {candidate}: {name}.")
        if spec.get("native_overlay"):
            if replacement.header != original.header:
                raise ValueError("Dashboard moet zijn volledige native PCX-header behouden.")
            if not all((a == 0) == (b == 0) for a, b in zip(original.pixels, replacement.pixels)):
                raise ValueError("Dashboard moet zijn exacte zwarte openingen behouden.")
            for x, y, width, height in spec["protected_rectangles"]:
                if not (0 <= x < original.width and 0 <= y < original.height and
                        0 < width <= original.width - x and 0 < height <= original.height - y):
                    raise ValueError("Dashboardcontract bevat een ongeldige beschermde rechthoek.")
                for row in range(y, y + height):
                    start = row * original.width + x
                    if original.pixels[start:start + width] != replacement.pixels[start:start + width]:
                        raise ValueError("Dashboard wijzigt de aansluiting op oorspronkelijke animatieframes.")
        elif not replacement_indices <= original_indices:
            raise ValueError(f"HD-omgevingtexture introduceert ongecontroleerde paletindices: {name}.")
        if spec.get("protected_scaled_masks"):
            if (replacement.width % original.width or replacement.height % original.height or
                    tuple(spec["protected_scaled_masks"]) != (0, 255)):
                raise ValueError("Atlascontract vereist gehele schaling en beide oorspronkelijke maskers.")
            scale_x = replacement.width // original.width
            scale_y = replacement.height // original.height
            for candidate in (0, 255):
                for row in range(replacement.height):
                    original_row = (row // scale_y) * original.width
                    replacement_row = row * replacement.width
                    if any((replacement.pixels[replacement_row + column] == candidate) !=
                           (original.pixels[original_row + column // scale_x] == candidate)
                           for column in range(replacement.width)):
                        raise ValueError(f"Atlas moet het exact opgeschaalde index-{candidate}-masker behouden: {name}.")
        anchor_checks = []
        if "atlas_anchor_guards" in spec:
            from tools.vehicle_mesh import validate_atlas_anchors
            anchor_checks = validate_atlas_anchors(replacement, spec["atlas_anchor_guards"])
        replacements.append((spec, data, original, anchor_checks))
    updated = archive
    evidence_items = []
    for spec, data, original, anchor_checks in replacements:
        name = spec["resource"]["name"]
        updated, item = replace_entry(updated, name, data)
        # Intermediate offsets can move; expose the pinned source offset too.
        item["source_offset"] = spec["resource"]["offset"]
        item.update(dimensions_before=[original.width, original.height],
                    dimensions_after=list(spec["dimensions"]), asset_sha256=spec["sha256"],
                    header_metadata_preserved=True, bytes_per_line=spec["dimensions"][0],
                    row_padding_absent=True, palette_unchanged=True,
                    palette_indices_subset_of_original=set(decode_pcx(data).pixels) <= set(original.pixels),
                    transparency_policy="No new index 0/255 use; game transparency semantics remain unproven.")
        if spec.get("native_overlay"):
            item.update(zero_mask_unchanged=True, protected_rectangles=list(spec["protected_rectangles"]),
                        native_animation_frames_changed=False, true_hd_2d=False,
                        transparency_policy="Exact native index-0 mask and original animation regions retained; no index 255.")
        if spec.get("protected_scaled_masks"):
            item.update(scaled_index_masks_unchanged=[0, 255], normalized_uv_coordinates_unchanged=True,
                        atlas_internal_alignment_runtime_verified=False,
                        transparency_policy="Both original index masks retained at exact integer texture scale.")
        if anchor_checks:
            item["atlas_anchor_checks"] = anchor_checks
        evidence_items.append(item)
    preserved = []
    for before, after in zip(archive.entries, updated.entries):
        if before.raw_name != after.raw_name:
            raise ValueError("HD-omgeving heeft RCS-naam/filler gewijzigd.")
        if before.name in names:
            continue
        before_data = entry_bytes(archive, before.name)
        if entry_bytes(updated, after.name) != before_data:
            raise ValueError("HD-omgeving heeft een ongekozen resource gewijzigd.")
        preserved.append({"index": before.index, "name": before.name, "size": before.size,
                          "sha256": _hash(before_data)})
    evidence = {"replacements": evidence_items, "other_resources_unchanged": True,
                "preserved_resources": preserved, "name_filler_unchanged": True,
                "runtime_verified": False}
    return [{"path": name, "purpose": "hd-scenery-textures-experimental", "profile": profile,
             "runtime_verified": False, "source_path": str(source / name),
             "before_sha256": _hash(before), "after_sha256": _hash(after), "data": after,
             "texture_evidence": evidence}
            for name, before, after in (("RCS.IND", archive.index_bytes, updated.index_bytes),
                                        ("RCS.IMG", archive.image_bytes, updated.image_bytes))]


def plan_fixes(source: Path, texture_path: Path | None = None,
               profile: str = "original", *, texture_paths: dict[str, Path] | None = None) -> list[dict]:
    """Read-only plans accepted by game_fixes.apply_fixes; originals are never written."""
    if profile in ("hd-scenery-1024", "hd-scenery-cockpit", "hd-expanded-v1"):
        if texture_path is not None:
            raise ValueError("Het omgevingsprofiel vereist alle vaste texturebestanden samen.")
        return _plan_multiple_fixes(source, texture_paths, profile)
    if texture_paths is not None:
        raise ValueError("Dit textureprofiel accepteert geen meervoudige vervanging.")
    spec = texture_asset_spec(profile)
    if profile == "original":
        if texture_path is not None:
            raise ValueError("Het originele textureprofiel accepteert geen vervangbestand.")
        return []
    archive = read_pinned_archive(source)
    if (texture_path is None or texture_path.is_symlink() or not texture_path.is_file() or
            not 1 <= texture_path.stat().st_size <= MAX_RESOURCE_BYTES):
        raise ValueError("HD-wegtexture ontbreekt of heeft een ongecontroleerde grootte.")
    replacement_data = texture_path.read_bytes()
    if spec["sha256"] is None or _hash(replacement_data) != spec["sha256"]:
        raise ValueError("HD-wegtexture heeft nog geen gecontroleerde assetpin of wijkt daarvan af.")
    original = decode_pcx(entry_bytes(archive, ROAD_NAME))
    replacement = decode_pcx(replacement_data)
    if ((original.width, original.height) != (128, 128) or
            (replacement.width, replacement.height) != spec["dimensions"]):
        width, height = spec["dimensions"]
        raise ValueError(f"Deze HD-proef vereist uitsluitend 128×128 naar {width}×{height} voor 2baans.pcx.")
    # The native loader calculates dimensions from signed header coordinates,
    # creates surfaces using them and decodes each row using BytesPerLine.
    # Retain every other header byte and omit padding, so a larger row cannot
    # request more pixels than the surface width. Our decoder has already
    # rejected malformed or row-crossing RLE before the native loader sees it.
    resized_header_fields = {8, 9, 10, 11, 66, 67}
    if any(before != after for offset, (before, after) in
           enumerate(zip(original.header, replacement.header)) if offset not in resized_header_fields):
        raise ValueError("HD-wegtexture moet de oorspronkelijke PCX-headermetadata behouden.")
    if struct.unpack_from("<H", replacement.header, 66)[0] != replacement.width or replacement.row_padding:
        raise ValueError("HD-wegtexture vereist BytesPerLine gelijk aan de breedte, zonder rijpadding.")
    if replacement.palette != original.palette:
        raise ValueError("HD-wegtexture moet het oorspronkelijke 256-kleurenpalet behouden.")
    # No transparent-index semantics have been proven. Neither zero nor 255
    # occurs in the pinned road; its index 255 is magenta. Do not introduce
    # either possible colour-key candidate in this otherwise opaque texture.
    for candidate in (0, 255):
        if candidate not in original.pixels and candidate in replacement.pixels:
            raise ValueError(f"HD-wegtexture introduceert ongecontroleerde paletindex {candidate}.")
    updated, evidence = replace_entry(archive, ROAD_NAME, replacement_data)
    evidence["dimensions_before"] = [128, 128]
    evidence["dimensions_after"] = list(spec["dimensions"])
    evidence["asset_sha256"] = spec["sha256"]
    evidence["header_metadata_preserved"] = True
    evidence["bytes_per_line"] = replacement.width
    evidence["row_padding_absent"] = True
    evidence["palette_unchanged"] = True
    evidence["palette_indices_subset_of_original"] = set(replacement.pixels) <= set(original.pixels)
    evidence["transparency_policy"] = "No new index 0/255 use; game transparency semantics remain unproven."
    plans = []
    for name, before, after in (("RCS.IND", archive.index_bytes, updated.index_bytes),
                                ("RCS.IMG", archive.image_bytes, updated.image_bytes)):
        plans.append({"path": name, "purpose": "hd-road-texture-experimental", "profile": profile,
                      "runtime_verified": False, "source_path": str(source / name),
                      "before_sha256": _hash(before), "after_sha256": _hash(after), "data": after,
                      "texture_evidence": evidence})
    return plans
