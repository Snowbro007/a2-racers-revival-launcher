"""Bounded read-only decoder for the observed A2-I vehicle D3D resources.

This is a file-format/UV inspection helper, not the game's renderer. The pinned
Panda resource uses counts, 33-byte vertices and 9-byte triangle records. Normals,
UVs and flag bytes are retained verbatim; no game data is modified or executed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct


@dataclass(frozen=True)
class VehicleMesh:
    vertices: tuple[tuple, ...]
    triangles: tuple[tuple, ...]


def decode_vehicle_mesh(data: bytes) -> VehicleMesh:
    if not isinstance(data, bytes) or not 8 <= len(data) <= 8 * 1024 * 1024:
        raise ValueError("Vehicle mesh ontbreekt of is te groot.")
    vertex_count, triangle_count = struct.unpack_from("<II", data)
    if not 3 <= vertex_count <= 65535 or not 1 <= triangle_count <= 65535:
        raise ValueError("Vehicle mesh heeft ongecontroleerde aantallen.")
    triangle_start = 8 + 33 * vertex_count
    if len(data) != triangle_start + 9 * triangle_count:
        raise ValueError("Vehicle mesh heeft geen exacte recordlengte.")
    vertices = tuple(struct.unpack_from("<8fB", data, 8 + 33 * index)
                     for index in range(vertex_count))
    if not all(math.isfinite(value) for row in vertices for value in row[:8]):
        raise ValueError("Vehicle mesh bevat niet-eindige vertexwaarden.")
    triangles = tuple(struct.unpack_from("<3H3B", data, triangle_start + 9 * index)
                      for index in range(triangle_count))
    if any(index >= vertex_count for row in triangles for index in row[:3]):
        raise ValueError("Vehicle mesh verwijst buiten de vertextabel.")
    return VehicleMesh(vertices, triangles)


def uv_anchors(mesh: VehicleMesh, indices: tuple[int, ...]) -> tuple[tuple[float, float], ...]:
    if any(type(index) is not int or not 0 <= index < len(mesh.vertices) for index in indices):
        raise ValueError("UV-anker ligt buiten de vertextabel.")
    return tuple((mesh.vertices[index][6], mesh.vertices[index][7]) for index in indices)


def validate_atlas_anchors(image, guards: list[dict]) -> list[dict]:
    """Check fixed semantic color anchors after PCX conversion, independent of pins.

    This catches a missing/moved rear plate or glass in the inspected Panda
    atlas. Passing these sparse anchors does not prove every UV island matches.
    Only palette RGB is inspected; no pixels are changed and no I/O is done.
    """
    if (type(image.width) is not int or type(image.height) is not int or
            not 1 <= image.width <= 4096 or not 1 <= image.height <= 4096 or
            not isinstance(image.pixels, bytes) or len(image.pixels) != image.width * image.height or
            not isinstance(image.palette, bytes) or len(image.palette) != 768 or
            not isinstance(guards, list) or not 1 <= len(guards) <= 16):
        raise ValueError("Atlasanker heeft ongecontroleerde afbeelding of aantallen.")
    results = []
    names = set()
    predicates = {
        "yellow": lambda r, g, b: r >= 100 and g >= 80 and b <= min(r, g) * 0.55,
        "dark": lambda r, g, b: max(r, g, b) <= 100,
        "red": lambda r, g, b: r >= 100 and r >= g * 1.45 and r >= b * 1.45,
    }
    for guard in guards:
        if (not isinstance(guard, dict) or set(guard) != {"name", "rect", "color", "minimum_fraction"} or
                not isinstance(guard["name"], str) or not 1 <= len(guard["name"]) <= 80 or
                guard["name"] in names or not isinstance(guard["color"], str) or guard["color"] not in predicates):
            raise ValueError("Atlasanker heeft een onbekend contract.")
        names.add(guard["name"])
        rect = guard["rect"]
        fraction = guard["minimum_fraction"]
        if (not isinstance(rect, (tuple, list)) or len(rect) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in rect) or
                not 0 <= rect[0] < rect[2] <= 1 or not 0 <= rect[1] < rect[3] <= 1 or
                type(fraction) not in (int, float) or not math.isfinite(fraction) or not 0 < fraction <= 1):
            raise ValueError("Atlasanker heeft ongeldige UV-grenzen of fractie.")
        left, top = math.ceil(rect[0] * image.width), math.ceil(rect[1] * image.height)
        right, bottom = math.floor(rect[2] * image.width), math.floor(rect[3] * image.height)
        total = (right - left) * (bottom - top)
        if right <= left or bottom <= top:
            raise ValueError("Atlasanker bevat geen volledige texturepixels.")
        predicate = predicates[guard["color"]]
        matching = 0
        for y in range(top, bottom):
            for x in range(left, right):
                index = image.pixels[y * image.width + x] * 3
                if predicate(*image.palette[index:index + 3]):
                    matching += 1
        actual = matching / total
        if actual < fraction:
            raise ValueError(f"Atlasanker {guard['name']} sluit niet aan op het vaste UV-paneel.")
        results.append({"name": guard["name"], "pixels": total, "matching_pixels": matching,
                        "fraction": actual, "minimum_fraction": fraction})
    return results
