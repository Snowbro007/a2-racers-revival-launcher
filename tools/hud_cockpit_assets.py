"""Code-native vector cockpit art and pure HD atlas contracts for pinned A2-I.

No artwork is resized and no game files are read, written or executed here.
Native animation frame selection remains authoritative. Renderers receive
logical vector primitives and return their already-rendered RGBA bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import struct

from tools.hud_hd_assets import COCKPIT_BY_NAME, COLOR_KEY_RGB565, SOURCE_SHA256

SCHEMA = 1
ASSET_ROOT = "local/mods/a2racer1/hud-cockpit-v1"
MAX_EDGE = 2048
MAX_TOTAL_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class FrameSpec:
    animation_frame: int
    pixel_rect: tuple[int, int, int, int]


@dataclass(frozen=True)
class AtlasSpec:
    name: str
    cached_role: str
    scale: int
    texture_size: tuple[int, int]
    frames: tuple[FrameSpec, ...]

    @property
    def logical_size(self) -> tuple[int, int]:
        return COCKPIT_BY_NAME[self.cached_role].logical_rect[2:]

    @property
    def active_size(self) -> tuple[int, int]:
        return (max(f.pixel_rect[0] + f.pixel_rect[2] for f in self.frames),
                max(f.pixel_rect[1] + f.pixel_rect[3] for f in self.frames))

    @property
    def animation_group(self) -> int:
        return COCKPIT_BY_NAME[self.cached_role].group_index

    @property
    def callers(self) -> tuple[int, ...]:
        return COCKPIT_BY_NAME[self.cached_role].caller_return_vas

    @property
    def byte_count(self) -> int:
        return self.texture_size[0] * self.texture_size[1] * 2


def _grid(name: str, role: str, scale: int, texture_size: tuple[int, int],
          indices: tuple[int, ...], columns: int) -> AtlasSpec:
    width, height = COCKPIT_BY_NAME[role].logical_rect[2:]
    w, h = width * scale, height * scale
    return AtlasSpec(name, role, scale, texture_size,
                     tuple(FrameSpec(index, ((i % columns) * w, (i // columns) * h, w, h))
                           for i, index in enumerate(indices)))


ATLASES = (
    _grid("strip-vector-v1", "dashboard_strip", 3, (2048, 128), (0,), 1),
    *(_grid(f"wheel-vector-v1-{part}", "steering_wheel", 3, (1024, 2048),
            tuple(range(part * 5, part * 5 + 5)), 1) for part in range(3)),
    _grid("right-vector-v1", "right_gauge", 4, (2048, 512), tuple(range(20)), 10),
    _grid("speed-vector-v1", "speedometer", 4, (2048, 2048), tuple(range(40)), 7),
    _grid("tach-vector-v1", "tachometer", 4, (2048, 1024), tuple(range(20)), 7),
)
ATLAS_BY_NAME = {a.name: a for a in ATLASES}


@dataclass(frozen=True)
class PatchSpec:
    name: str
    logical_rect: tuple[int, int, int, int]
    scale: int
    texture_size: tuple[int, int]

    @property
    def logical_size(self) -> tuple[int, int]:
        return self.logical_rect[2:]

    @property
    def active_size(self) -> tuple[int, int]:
        return tuple(v * self.scale for v in self.logical_size)

    @property
    def byte_count(self) -> int:
        return self.texture_size[0] * self.texture_size[1] * 2


FIXED_PATCHES = (PatchSpec("rim-bridge-vector-v1", (0, 303, 640, 177), 3, (2048, 1024)),)

# These angles are measured from the original changing needle pixels, not from
# guessed RPM/speed formulas. Native live frame selection remains unchanged.
NEEDLE_ANGLES = {
    "speedometer": (141.777,149.139,156.324,163.784,170.140,178.168,-174.152,-168.108,
                    -161.567,-154.327,-145.983,-138.373,-131.552,-123.966,-116.745,-109.235,
                    -104.104,-98.219,-91.000,-85.597,-79.653,-74.105,-68.211,-60.798,-53.838,
                    -47.371,-42.289,-36.690,-30.457,-23.759,-19.841,-15.330,-10.093,-4.342,
                    1.389,6.714,11.173,16.300,22.342,28.943),
    "tachometer": (152.853,160.554,175.661,-175.783,-163.382,-148.740,-138.206,-125.598,
                   -111.493,-99.883,-88.173,-75.848,-58.921,-46.132,-35.290,-19.711,
                   -5.250,6.798,20.550,35.899),
    "right_gauge": (146.909,152.142,158.328,164.836,168.650,180.000,-179.183,-170.378,
                    -164.895,-159.232,-153.694,-146.542,-140.383,-133.681,-125.231,
                    -117.410,-110.296,-103.554,-96.594,-90.884),
}
# Native black-hole component centroids, including joined fragments where a
# baked spoke boundary splits a hole. Frame 7/resource 82 is the neutral pose.
WHEEL_HOLE_CENTERS = (
    (260.31,59.27),(262.98,64.79),(265.26,69.91),(271.02,81.41),
    (273.88,92.11),(273.74,98.65),(274.73,107.62),(275.01,116.70),
    (55.95,107.81),(56.85,98.91),(58.64,90.67),(61.10,80.58),
    (64.24,72.80),(68.04,64.71),(71.27,58.56),
)


def _wheel_angle(frame: int) -> float:
    cx, cy = 162.0, 127.0
    x, y = WHEEL_HOLE_CENTERS[frame]
    ref_x, ref_y = (275.01,116.70) if frame <= 7 else (55.59,116.76)
    a = math.degrees(math.atan2(y-cy,x-cx)-math.atan2(ref_y-cy,ref_x-cx))
    return (a + 180.0) % 360.0 - 180.0


WHEEL_ANGLES = tuple(round(_wheel_angle(i), 3) for i in range(15))


def measure_needle_angles(frames: tuple[bytes, ...], size: tuple[int, int], palette: bytes,
                          center: tuple[int, int], *, variation_threshold: int = 40,
                          radius_min: float = 7.0, radius_max: float | None = None) -> tuple[float, ...]:
    """Read-only angular measurement from indexed synthetic or original bytes.

    A changing neutral pixel is measured above its minimum luminance across
    frames. Static labels and the hub/outer border are excluded. This is an
    artwork measurement, not a replacement native simulation/frame selector.
    """
    if (not isinstance(size, tuple) or len(size) != 2 or
            any(type(v) is not int or not 1 <= v <= 512 for v in size)
            or type(palette) is not bytes or len(palette) != 768
            or not isinstance(frames, tuple) or not 2 <= len(frames) <= 64
            or any(type(f) is not bytes or len(f) != size[0]*size[1] for f in frames)
            or not isinstance(center, tuple) or len(center) != 2
            or any(type(v) is not int for v in center)
            or not (0 <= center[0] < size[0] and 0 <= center[1] < size[1])
            or type(variation_threshold) is not int or not 0 <= variation_threshold <= 255):
        raise ValueError("Ongeldig read-only wijzermeetcontract.")
    if radius_max is None:
        radius_max = min(size) * .36
    if (type(radius_min) not in (int,float) or type(radius_max) not in (int,float)
            or not math.isfinite(radius_min) or not math.isfinite(radius_max)
            or not 0 <= radius_min < radius_max <= max(size)):
        raise ValueError("Ongeldige wijzermeet-annulus.")
    colors = tuple(tuple(palette[i*3:i*3+3]) for i in range(256))
    brightness = tuple(sum(c)/3.0 for c in colors)
    minima = tuple(min(brightness[f[p]] for f in frames) for p in range(size[0]*size[1]))
    maxima = tuple(max(brightness[f[p]] for f in frames) for p in range(size[0]*size[1]))
    result = []
    for frame in frames:
        vx = vy = weight = 0.0
        for pos, index in enumerate(frame):
            dx, dy = pos % size[0]-center[0], pos // size[0]-center[1]
            radius = math.hypot(dx,dy)
            delta = brightness[index]-minima[pos]
            color = colors[index]
            if (radius_min < radius < radius_max and max(color)-min(color) <= 8
                    and maxima[pos]-minima[pos] > variation_threshold and delta > 20):
                vx += dx/radius*delta
                vy += dy/radius*delta
                weight += delta
        if weight <= 0 or math.hypot(vx,vy) < weight*.5:
            raise ValueError("Geen eenduidige oorspronkelijke wijzerrichting gemeten.")
        result.append(round(math.degrees(math.atan2(vy,vx)),3))
    return tuple(result)


def validate_atlases(atlases: tuple[AtlasSpec, ...]) -> None:
    if not isinstance(atlases, tuple) or not atlases or len(atlases) > 20:
        raise ValueError("Cockpitatlassen ontbreken of overschrijden de limiet.")
    names: set[str] = set()
    roles: dict[str, set[int]] = {}
    for atlas in atlases:
        if (not isinstance(atlas, AtlasSpec) or type(atlas.cached_role) is not str
                or atlas.cached_role not in COCKPIT_BY_NAME):
            raise ValueError("Onbekend cockpit-atlascontract.")
        if type(atlas.name) is not str or not atlas.name or atlas.name in names:
            raise ValueError("Cockpitatlasnaam ontbreekt of is dubbel.")
        names.add(atlas.name)
        if type(atlas.scale) is not int or not 1 <= atlas.scale <= 4:
            raise ValueError("Ongeldige cockpit-vectorschaal.")
        if (not isinstance(atlas.texture_size, tuple) or len(atlas.texture_size) != 2
                or any(type(v) is not int or not 1 <= v <= MAX_EDGE or v & (v - 1)
                       for v in atlas.texture_size)):
            raise ValueError("Cockpitatlas vereist begrensde pow2-afmetingen.")
        if not isinstance(atlas.frames, tuple) or not atlas.frames:
            raise ValueError("Cockpitatlas heeft geen framecontract.")
        covered = roles.setdefault(atlas.cached_role, set())
        rects = []
        w, h = (v * atlas.scale for v in atlas.logical_size)
        for frame in atlas.frames:
            if (not isinstance(frame, FrameSpec) or type(frame.animation_frame) is not int
                    or not 0 <= frame.animation_frame < len(COCKPIT_BY_NAME[atlas.cached_role].resource_indices)
                    or frame.animation_frame in covered):
                raise ValueError("Dubbele of ongeldige native cockpitframekeuze.")
            rect = frame.pixel_rect
            if (not isinstance(rect, tuple) or len(rect) != 4
                    or any(type(v) is not int for v in rect) or rect[2:] != (w, h)
                    or min(rect[:2]) < 0 or rect[0] + w > atlas.texture_size[0]
                    or rect[1] + h > atlas.texture_size[1]):
                raise ValueError("Cockpitframecrop valt buiten de atlas.")
            if any(rect[0] < x + rw and x < rect[0] + w and rect[1] < y + rh and y < rect[1] + h
                   for x, y, rw, rh in rects):
                raise ValueError("Cockpitframecrops overlappen.")
            rects.append(rect)
            covered.add(frame.animation_frame)
    if sum(a.byte_count for a in atlases) > MAX_TOTAL_BYTES:
        raise ValueError("Cockpitatlassen overschrijden het pixelbudget.")
    for role, covered in roles.items():
        if covered != set(range(len(COCKPIT_BY_NAME[role].resource_indices))):
            raise ValueError("Cockpitrol mist oorspronkelijke native frames.")


def encode_atlas(atlas: AtlasSpec, rgba_frames: tuple[bytes, ...]) -> bytes:
    """Pack already-rendered straight RGBA tiles; no resampling or image edits.

    Alpha zero is the explicit colorkey. Intermediate alpha is blended onto
    the scene's own opaque base by the vector renderer, so only 0/255 is valid
    here. Frames must include opaque erasure coverage, except native apertures.
    """
    if atlas not in ATLASES or not isinstance(rgba_frames, tuple) or len(rgba_frames) != len(atlas.frames):
        raise ValueError("RGBA-frames passen niet bij het vaste atlascontract.")
    tw, th = atlas.texture_size
    out = bytearray(struct.pack("<H", COLOR_KEY_RGB565) * (tw * th))
    for spec, rgba in zip(atlas.frames, rgba_frames):
        x, y, w, h = spec.pixel_rect
        if type(rgba) is not bytes or len(rgba) != w * h * 4:
            raise ValueError("Cockpitframe heeft geen exacte RGBA-lengte.")
        for row in range(h):
            for col in range(w):
                r, g, b, alpha = rgba[(row * w + col) * 4:(row * w + col) * 4 + 4]
                if alpha not in (0, 255):
                    raise ValueError("Vectorframe moet vooraf op eigen basis zijn gecompositeerd.")
                if alpha:
                    value = (r >> 3) << 11 | (g >> 2) << 5 | b >> 3
                    if value == COLOR_KEY_RGB565:
                        value ^= 1
                    struct.pack_into("<H", out, ((y + row) * tw + x + col) * 2, value)
    return bytes(out)


def encode_fixed(patch: PatchSpec, rgba: bytes) -> bytes:
    """Encode an already-rendered fixed vector patch with exact native rect."""
    if patch not in FIXED_PATCHES:
        raise ValueError("Onbekende vaste cockpitpatch.")
    w, h = patch.active_size
    if type(rgba) is not bytes or len(rgba) != w*h*4:
        raise ValueError("Vaste cockpitpatch heeft geen exacte RGBA-lengte.")
    tw, th = patch.texture_size
    out = bytearray(struct.pack("<H",COLOR_KEY_RGB565)*(tw*th))
    for y in range(h):
        for x in range(w):
            r,g,b,alpha = rgba[(y*w+x)*4:(y*w+x)*4+4]
            if alpha not in (0,255):
                raise ValueError("Vaste vectorpatch vereist gecompositeerde alfa.")
            if alpha:
                value = (r>>3)<<11 | (g>>2)<<5 | b>>3
                if value == COLOR_KEY_RGB565:
                    value ^= 1
                struct.pack_into("<H",out,(y*tw+x)*2,value)
    return bytes(out)


def export_plan() -> dict:
    """Stable JSON plan; commands use logical coords and #AARRGGBB colors.

    WPF renders each frame into its exact physical crop with ScaleTransform.
    Renderer contract: opaque base; clip to logical rect; clear explicit holes
    after drawing; convert Pbgra32 to straight RGBA only for fully opaque pixels.
    """
    validate_atlases(ATLASES)
    return {"schema": SCHEMA, "source_binary_sha256": SOURCE_SHA256,
            "asset_root": ASSET_ROOT, "game_executed": False,
            "command_coordinates": "logical", "color_format": "#AARRGGBB",
            "assets": [{"name": p.name,"cached_role":None,"fixed_rect":list(p.logical_rect),
                        "scale":p.scale,"logical_size":list(p.logical_size),
                        "texture_size":list(p.texture_size),"active_size":list(p.active_size),
                        "bytes":p.byte_count,"frames":[{"animation_frame":None,
                          "pixel_rect":[0,0,*p.active_size],"scene":fixed_scene(p)}]}
                       for p in FIXED_PATCHES] + [{"name": a.name, "cached_role": a.cached_role, "scale": a.scale,
                        "logical_size": list(a.logical_size), "texture_size": list(a.texture_size),
                        "active_size": list(a.active_size), "animation_group": a.animation_group,
                        "callers": list(a.callers), "bytes": a.byte_count,
                        "frames": [{"animation_frame": f.animation_frame, "pixel_rect": list(f.pixel_rect),
                                    "scene": frame_scene(a.cached_role, f.animation_frame)} for f in a.frames]}
                       for a in ATLASES]}


def frame_scene(role: str, frame: int) -> dict:
    """Vector artwork generator; body follows below the measured geometry pins."""
    if type(role) is not str or role not in COCKPIT_BY_NAME or type(frame) is not int:
        raise ValueError("Onbekende cockpitrol/frame.")
    group = COCKPIT_BY_NAME[role]
    if not 0 <= frame < len(group.resource_indices):
        raise ValueError("Cockpitframe valt buiten de oorspronkelijke animatie.")
    return _scene(role, frame)


def _scene(role: str, frame: int) -> dict:
    group = COCKPIT_BY_NAME[role]
    width,height = group.logical_rect[2:]
    commands=[]
    holes=[]
    if role == "dashboard_strip":
        commands.append(_rect((0,0,width,height),"#FF41454A"))
        commands.append(_path("M 0 24 C 130 13 385 10 640 28 L 640 36 L 0 36 Z","#FF24272B"))
        commands.extend(rim_commands(0,-267))
        # Native red detector LEDs occupy the original strip. Retain actual
        # selected native pixels instead of guessing detector on/off values.
        holes.append((400,14,240,22))
    elif role == "steering_wheel":
        commands.append(_rect((0,0,width,height),"#FF080A0C"))
        commands.append(_path("M 0 0 L 330 0 L 306 16 L 292 29 L 250 35 L 246 59 L 89 59 L 83 40 L 26 29 Z","#FFB81512"))
        commands.append(_path("M 0 1 L 330 1 L 306 16 L 292 29 L 250 35","#00000000","#FFE43B30",1.5))
        angle=WHEEL_ANGLES[frame]
        spokes=((12,107),(40,88),(96,96),(162,100),(225,95),(290,82),(321,102),
                (310,130),(238,140),(182,147),(174,186),(144,186),(139,145),(65,143),(18,130))
        commands.append(_path(_polygon(tuple(_rotate(p,angle) for p in spokes)),"#FF555B61","#FF858C92",1.5))
        highlight=((30,105),(85,102),(161,110),(242,104),(301,99))
        commands.append(_path(_polyline(tuple(_rotate(p,angle) for p in highlight)),"#00000000","#FF9EA5AC",1.5))
        for cx,cy,r in ((55.59,116.76,12),(102.8,122,20),(227,122,21),(275.01,116.7,13)):
            xx,yy=_rotate((cx,cy),angle)
            commands.append(_ellipse((xx-r,yy-r,r*2,r*2),"#FF090B0D","#FFB3BAC0",2))
            commands.append(_ellipse((xx-r+2,yy-r+2,r*2-4,r*2-4),"#FF080A0C","#FF30363C",.8))
        commands.append(_ellipse((135,99,55,56),"#FFB5BABF","#FF767D83",2.4))
        commands.append(_ellipse((141,105,43,44),"#FFCDD1D4","#FFE1E5E7",1.2))
        commands.append(_text("A2",(143,109,40,30),18,"#FF535A60",family="Arial",weight="Bold"))
        commands.extend(rim_commands(-44,-348))
        # LED state stays native. At high wheel angles native spokes can
        # occlude LEDs; retaining this complete zone preserves that behavior.
        holes.extend(((45,0,40,26),(89,41,157,18)))
    else:
        commands.append(_rect((0,0,width,height),"#FFB81512"))
        commands.extend(rim_commands(-group.logical_rect[0],-group.logical_rect[1]))
        cx,cy = {"speedometer":(35,34),"tachometer":(35,35),"right_gauge":(23,24)}[role]
        radius=min(width,height)*.475
        commands.append(_ellipse((cx-radius,cy-radius,radius*2,radius*2),"#FF252A2F","#FF07090B",1.3))
        commands.append(_ellipse((cx-radius+1.6,cy-radius+1.6,(radius-1.6)*2,(radius-1.6)*2),"#FF101316","#FF7A8187",.65))
        if role=="right_gauge":
            _ticks(commands,cx,cy,radius-3,150,270,12,"#FF71877B",.7)
            for i in range(14):
                a=155+i*8.0
                col="#FF3F9A56" if i>4 else "#FFA76D36"
                commands.append(_path(_polyline((_polar(cx,cy,radius-3,a),_polar(cx,cy,radius-6,a))),"#00000000",col,1.5))
            # The original tiny symbol depicts the fuel pump. Draw its shape
            # as geometry; the letter P would falsely resemble a parking icon.
            commands.append(_path(f"M {cx-3} {cy+8} L {cx+2} {cy+8} L {cx+2} {cy+16} L {cx-3} {cy+16} Z M {cx-2} {cy+9} L {cx+1} {cy+9} L {cx+1} {cy+12} L {cx-2} {cy+12} Z M {cx+2} {cy+10} L {cx+4} {cy+12} L {cx+4} {cy+15} L {cx+2} {cy+15}","#00000000","#FFBDC5C9",.9))
        elif role=="tachometer":
            for i in range(30):
                a=146+i*8.0
                col="#FF37964F" if i<18 else ("#FFB27B36" if i<23 else "#FFAE3731")
                commands.append(_path(_polyline((_polar(cx,cy,radius-3,a),_polar(cx,cy,radius-7,a))),"#00000000",col,2))
            _ticks(commands,cx,cy,radius-8,145,385,24,"#FFAAB3B9",.7)
            for number in range(9):
                x,y=_polar(cx,cy,radius-12,145+number*30)
                commands.append(_text(str(number),(x-3,y-3,6,6),5,"#FFCED5D9"))
            commands.append(_text("rpm ×1000",(cx-17,cy+17,34,7),4.2,"#FFADB6BE"))
        else:
            _ticks(commands,cx,cy,radius-3,140,388,40,"#FFD9DFE3",.8)
            # Artistically reconstructed scale with the observed original
            # final mark 250. Needle choice/calibration follows native IDs.
            for i,number in enumerate((*range(20,241,20),250)):
                x,y=_polar(cx,cy,radius-10,164+i*18.7)
                commands.append(_text(str(number),(x-5,y-2.8,10,5.6),4.05,"#FFE4E8EB"))
            commands.append(_text("km/h",(cx-10,cy+17,20,6),4.5,"#FFAFBAC2"))
            commands.append(_ellipse((cx-3.5,cy+13,7,7),"#FF57332A","#FF876348",.7))
            commands.append(_ellipse((cx-1.6,cy+14.9,3.2,3.2),"#FFDA4D25"))
        angle=NEEDLE_ANGLES[role][frame]
        tip=_polar(cx,cy,radius*.78,angle)
        back=_polar(cx,cy,3.0,angle+180)
        left=_polar(cx,cy,1.45,angle+90)
        right=_polar(cx,cy,1.45,angle-90)
        commands.append(_path(_polygon((back,left,tip,right)),"#FFE8ECEF","#FF929DA5",.35))
        commands.append(_ellipse((cx-2.5,cy-2.5,5,5),"#FF8B959E","#FFC9D0D5",.5))
    return {"size":[width,height],"commands":commands,"transparent_rects":[list(r) for r in holes]}


def _rect(rect,fill,stroke=None,stroke_width=0):
    return {"kind":"rect","rect":list(rect),"fill":fill,"stroke":stroke,"stroke_width":stroke_width}


def _ellipse(rect,fill,stroke=None,stroke_width=0):
    return {"kind":"ellipse","rect":list(rect),"fill":fill,"stroke":stroke,"stroke_width":stroke_width}


def _path(d,fill,stroke=None,stroke_width=0):
    return {"kind":"path","d":d,"fill":fill,"stroke":stroke,"stroke_width":stroke_width}


def _text(text,rect,size,fill,family="Arial",weight="Normal"):
    return {"kind":"text","text":text,"rect":list(rect),"font_family":family,
            "font_size":size,"font_weight":weight,"fill":fill,"align":"center"}


def _polar(cx,cy,r,angle):
    angle=math.radians(angle)
    return cx+r*math.cos(angle),cy+r*math.sin(angle)


def _rotate(point,angle):
    a=math.radians(angle);dx,dy=point[0]-162,point[1]-127
    return 162+dx*math.cos(a)-dy*math.sin(a),127+dx*math.sin(a)+dy*math.cos(a)


def _polyline(points):
    return "M "+" L ".join(f"{x:.4f},{y:.4f}" for x,y in points)


def _polygon(points):
    return _polyline(points)+" Z"


def _ticks(commands,cx,cy,r,start,end,count,color,width):
    for i in range(count+1):
        angle=start+(end-start)*i/count
        inner=r-(3.6 if i%2==0 else 1.9)
        commands.append(_path(_polyline((_polar(cx,cy,inner,angle),_polar(cx,cy,r,angle))),
                              "#00000000",color,width))


def rim_commands(origin_x: float = 0, origin_y: float = 0) -> list[dict]:
    """One shared global-coordinate rim for strip, bridge and native wheel rect.

    Fixed outer circle global center (210,452), radius185. Only wheel spokes
    rotate. Each caller clips these exact same vectors to its own native rect.
    This fitted code-native geometry is artwork, not inferred game physics.
    """
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (origin_x,origin_y)):
        raise ValueError("Ongeldige gezamenlijke stuurboog-origin.")
    return [
        _ellipse((25+origin_x,267+origin_y,370,370),"#00000000","#FF0B0D0F",24),
        _ellipse((28+origin_x,270+origin_y,364,364),"#00000000","#FF252A2E",19),
        _ellipse((28+origin_x,270+origin_y,364,364),"#00000000","#FF626970",2.3),
        _ellipse((44+origin_x,286+origin_y,332,332),"#00000000","#FF171C20",3),
        _ellipse((45+origin_x,287+origin_y,330,330),"#00000000","#FF838B92",.65),
    ]


def fixed_scene(patch: PatchSpec) -> dict:
    if patch not in FIXED_PATCHES:
        raise ValueError("Onbekende vaste cockpitvectorpatch.")
    x,y,w,h=patch.logical_rect
    commands=[_rect((0,0,w,h),"#FF080A0C"),
              _rect((0,0,w,45),"#FF41454A"),
              _path("M 44 0 L 350 0 L 384 45 L 62 45 Z","#FFB81512")]
    commands.extend(rim_commands(-x,-y))
    return {"size":[w,h],"commands":commands,
            "transparent_rects":[[89,26,40,19],[400,0,240,45],
                                 [44,45,330,132],[430,45,210,132]]}


def scene_svg(scene: dict) -> str:
    """Standalone vector review; no raster artwork or native pixels embedded."""
    from xml.sax.saxutils import escape
    w,h=scene["size"]
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    out.append('<defs><mask id="holes"><rect width="100%" height="100%" fill="white"/>')
    for x,y,rw,rh in scene["transparent_rects"]:
        out.append(f'<rect x="{x}" y="{y}" width="{rw}" height="{rh}" fill="black"/>')
    out.append('</mask></defs><g mask="url(#holes)">')
    def color(value):
        if value is None or value[:3]=="#00":return "none"
        return "#"+value[3:]
    for cmd in scene["commands"]:
        attrs=f'fill="{color(cmd["fill"])}" stroke="{color(cmd.get("stroke"))}" stroke-width="{cmd.get("stroke_width",0)}"'
        if cmd["kind"]=="path":
            out.append(f'<path d="{escape(cmd["d"])}" {attrs}/>')
        elif cmd["kind"]=="text":
            x,y,tw,th=cmd["rect"]
            out.append(f'<text x="{x+tw/2}" y="{y+th/2}" text-anchor="middle" dominant-baseline="central" font-family="{escape(cmd["font_family"])}" font-size="{cmd["font_size"]}" font-weight="{cmd["font_weight"]}" {attrs}>{escape(cmd["text"])}</text>')
        else:
            x,y,rw,rh=cmd["rect"]
            if cmd["kind"]=="rect":out.append(f'<rect x="{x}" y="{y}" width="{rw}" height="{rh}" {attrs}/>')
            else:out.append(f'<ellipse cx="{x+rw/2}" cy="{y+rh/2}" rx="{rw/2}" ry="{rh/2}" {attrs}/>')
    return "".join(out)+"</g></svg>"


validate_atlases(ATLASES)
