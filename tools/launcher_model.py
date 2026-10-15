"""Launcher settings and fixed launch plans; never execute game code.

All writes belong to local/launcher. A session is a frozen set of preferences,
not a user-supplied executable, script, command or destination.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.trial_manifest import EXPECTED_BINARIES, HD_DISPLAY_PROFILES, validate_ancestors, validate_slug
from tools import ii_frontend_launcher, ii_original_launcher
from tools import ii_launcher_graphics

# Version-1 presets are migration data only; new choices are independent.
LEGACY_GRAPHICS = {
    "software-640": {"native": "software-640", "display": "original"},
    "software-4-3": {"native": "software-640", "display": "borderless-4-3"},
    "accelerated-640": {"native": "accelerated-640", "display": "original"},
    "accelerated-hd": {"native": "accelerated-640", "display": "hd-1280x960"},
    "accelerated-hd-startfix": {"native": "accelerated-640", "display": "hd-1280x960"},
    "accelerated-hd-alt-tab": {"native": "accelerated-640", "display": "hd-1280x960-fake"},
    "accelerated-hd-distance": {"native": "accelerated-640", "display": "hd-1280x960", "render_distance_profile": "extended-8"},
    "accelerated-hd-distance-10": {"native": "accelerated-640", "display": "hd-1280x960", "render_distance_profile": "extended-10"},
    "accelerated-hd-distance-20": {"native": "accelerated-640", "display": "hd-1280x960", "render_distance_profile": "extended-20"},
    "accelerated-hd-1920": {"native": "accelerated-640", "display": "hd-1920x1440"},
}

GRAPHICS = {
    "software-640": {"label": "Software · 640 × 480", "description": "Oorspronkelijke softwareweergave; opschalen voegt geen renderdetail toe."},
    "accelerated-640": {"label": "3D Accelerator · aanbevolen", "description": "3D-weergave met hogere resoluties en extra zichtafstand. In de game heet deze stand 3D Accelerator."},
}
DISPLAY_PROFILES = {
    "original": {"label": "Originele resolutie · 4:3", "description": "Behoudt de oorspronkelijke beeldinstellingen.", "native_graphics": None, "camera_profile": "original"},
    "borderless-4-3": {"label": "640 × 480 · 4:3 opschalen", "description": "Softwarebeeld in 4:3, met zijbalken op een breed scherm; geen extra renderdetail.", "native_graphics": "software-640", "camera_profile": "original"},
    "hd-1280x960": {"label": "1280 × 960 · 4:3", "description": "Onze bevestigde speelbasis. De wrapper vraagt 1280 × 960 aan; de interne renderresolutie is nog niet gemeten.", "native_graphics": "accelerated-640", "camera_profile": "original"},
    "hd-1440x1080": {"label": "1440 × 1080 · 4:3", "description": "1080 pixels hoog met oorspronkelijke 4:3-verhouding. Interne renderresolutie nog niet gemeten.", "native_graphics": "accelerated-640", "camera_profile": "original"},
    "hd-1920x1440": {"label": "1920 × 1440 · 4:3", "description": "Racebeeld eerder bereikt; interne renderresolutie nog niet gemeten.", "native_graphics": "accelerated-640", "camera_profile": "original"},
    "hd-2880x2160": {"label": "2880 × 2160 · 4:3", "description": "2160 pixels hoog met oorspronkelijke 4:3-verhouding. Interne renderresolutie nog niet gemeten.", "native_graphics": "accelerated-640", "camera_profile": "original"},
    "hd-1920x1080-camera": {"label": "1080p · 1920 × 1080 · 16:9 (aanbevolen)", "description": "Aanbevolen Full HD-breedbeeld, door de speler bevestigd werkend.", "native_graphics": "accelerated-640", "camera_profile": "camera-16-9"},
    "hd-3840x2160-camera": {"label": "4K · 3840 × 2160 · 16:9", "description": "4K-breedbeeld, door de speler bevestigd werkend. Vraagt meer van je pc.", "native_graphics": "accelerated-640", "camera_profile": "camera-16-9"},
    "hd-1280x960-fake": {"label": "1280 × 960 · oude Alt+Tab-proef", "description": "Deze mislukte schermproef is vervallen. Kies een andere resolutie om te spelen; de eerder opgeslagen keuze blijft bewaard tot je zelf kiest.", "native_graphics": "accelerated-640", "camera_profile": "original", "launcher_visible": False},
}
CAMERA_PROFILES = {
    "original": {"label": "Oorspronkelijke 4:3-camera", "description": "Oorspronkelijke projectie; geen camera-aanpassing."},
    "camera-16-9": {"label": "Breedbeeldcamera · 16:9", "description": "Breedbeeldcamera voor de bevestigde 1080p- en 4K-speelstanden."},
}
RENDER_DISTANCES = {
    "original": {"label": "Origineel", "description": "Je ziet de weg vooruit zoals in de oorspronkelijke game."},
    "extended-8": {"label": "Iets verder", "description": "Je ziet de weg en omgeving iets verder vooruit; wegdelen verschijnen eerder."},
    "extended-10": {"label": "Verder", "description": "Je ziet meer van de weg en omgeving verder vooruit; wegdelen verschijnen eerder."},
    "extended-20": {"label": "Ver vooruit · aanbevolen", "description": "Je ziet veel meer van de weg en omgeving verder vooruit; wegdelen verschijnen eerder. Onze aanbevolen speelstand."},
}
OBJECT_DISTANCES = {
    "original": {"label": "Origineel", "description": "Auto's, gebouwen en andere objecten verschijnen op de oorspronkelijke afstand."},
    "loaded-all": {"label": "Alle geladen objecten · optioneel", "description": "Toont ook verder weg geladen auto's en gebouwen. Kan de ronde rand van de map zichtbaar maken en meer rekenkracht vragen."},
}
TEXTURE_PROFILES = {
    "original": {"label": "Origineel", "description": "Standaard: HD uit. Alle oorspronkelijke textures blijven behouden: weg, omgeving, auto's en cockpit."},
    "hd-road-256": {"label": "HD-weg · 256 × 256", "description": "Oude wegtextureproef. Kies Origineel of HD textures om te spelen; deze eerdere keuze blijft bewaard tot je zelf kiest.", "launcher_visible": False},
    "hd-road-512": {"label": "HD-weg · 512 × 512", "description": "Oude wegtextureproef. Kies Origineel of HD textures om te spelen; deze eerdere keuze blijft bewaard tot je zelf kiest.", "launcher_visible": False},
    "hd-scenery-1024": {"label": "HD-omgeving", "description": "Oude omgevingsproef. Kies Origineel of HD textures om te spelen; deze eerdere keuze blijft bewaard tot je zelf kiest.", "launcher_visible": False},
    "hd-scenery-cockpit": {"label": "HD-omgeving + cockpit", "description": "Oude cockpitproef. Kies Origineel of HD textures om te spelen; deze eerdere keuze blijft bewaard tot je zelf kiest.", "launcher_visible": False},
    "hd-expanded-v1": {"label": "HD textures · eerdere versie", "description": "Eerdere HD-textureversie. Kies Origineel of HD textures · aanbevolen voor de nieuwste keuze; deze opgeslagen versie blijft bewaard tot je zelf kiest.", "launcher_visible": False},
    "hd-revival-v1": {"label": "HD textures · aanbevolen", "description": "Optionele visuele upgrade: scherpere weg, omgeving, borden, tankstation en voertuigen, plus HD-dashboard, stuur, meters en boetekaart. HD staat standaard uit. Alt+Tab in deze nieuwste versie is nog niet bevestigd.",
                      "native_texture_profile": "hd-expanded-v1", "hud_profile": "hd-cockpit-v3",
                      "hud_displays": list(HD_DISPLAY_PROFILES)},
}
LEGACY_PREFERENCE_KEYS = {"graphics", "dashboard", "fps", "intro", "debug"}
MENU_PROFILES = {
    "original": {"label": "Origineel · venster", "description": "Standaard: het oorspronkelijke spelmenu in een venster."},
    "classic-fullscreen": {"label": "Classic · fullscreen (proef)", "description": "Klassiek menu in echte 640 × 480-fullscreen, met originele bediening en herstel voor het naamveld. Vereist ondersteuning van deze schermmodus. HD tijdens racen staat hier los van."},
    "refreshed-fullscreen": {"label": "Refreshed · fullscreen (proef)", "description": "Optioneel: opgefriste achtergronden en klassieke indeling in echte 640 × 480-fullscreen. De bediening blijft origineel, met herstel voor het naamveld. Vereist ondersteuning van deze schermmodus; dit is geen HD-menu. HD tijdens racen staat hier los van."},
    "hd-fullscreen": {"label": "HD menu · fullscreen", "description": "Bevestigd werkend, schermvullend menu met scherpe knoppen en naamvelden. Eigen HD-spelers; grafische opties kies je in de launcher."},
}
DEFAULT_SETTINGS = {
    "schema": 4, "selected_game": "a2racer1", "games": {
        "a2racer1": {"graphics": "accelerated-640", "display_profile": "hd-1920x1080-camera",
                     "camera_profile": "camera-16-9", "render_distance_profile": "extended-20",
                     "object_distance_profile": "original", "texture_profile": "original", "native_horizon": 0, "race_focus_recovery": True,
                     "menu_profile": "original", "dashboard": True, "fps": 20, "intro": True, "debug": False},
        "a2racer2": {"graphics": "native", "dashboard": None, "fps": 0, "intro": False, "debug": False, "menu_profile": "revival", "race_display": "widescreen", **ii_launcher_graphics.DEFAULTS, "race_resolution": "1080p"},
    },
}
SCHEMA_THREE_PREFERENCE_KEYS = set(DEFAULT_SETTINGS["games"]["a2racer1"]) - {"menu_profile"}
SCHEMA_TWO_PREFERENCE_KEYS = SCHEMA_THREE_PREFERENCE_KEYS - {"texture_profile"}

# Presets are explicit choices, not migrations or new saved defaults.
I_PROFILES = {
    'original': {'label': 'Origineel', 'preferences': {
        **DEFAULT_SETTINGS['games']['a2racer1'], 'display_profile': 'original',
        'camera_profile': 'original', 'render_distance_profile': 'original',
        'native_horizon': 1, 'race_focus_recovery': False}},
    'recommended': {'label': 'Aanbevolen', 'preferences': deepcopy(DEFAULT_SETTINGS['games']['a2racer1'])},
    'max': {'label': 'MAX', 'preferences': {
        **DEFAULT_SETTINGS['games']['a2racer1'], 'display_profile': 'hd-3840x2160-camera',
        'fps': 30, 'object_distance_profile': 'loaded-all', 'texture_profile': 'hd-revival-v1',
        'menu_profile': 'hd-fullscreen'}},
}

II_PROFILES = {
    'original': {'label': 'Origineel', 'preferences': {
        **DEFAULT_SETTINGS['games']['a2racer2'], 'race_display': 'classic',
        'sky_mode': 'original', 'race_distance': 'auto'}},
    'recommended': {'label': 'Aanbevolen', 'preferences': deepcopy(DEFAULT_SETTINGS['games']['a2racer2'])},
    'max': {'label': 'MAX', 'preferences': {
        **DEFAULT_SETTINGS['games']['a2racer2'], 'race_resolution': '4k', 'race_hud': 'hd'}},
}


def validate_preferences(game: str, value: dict, *, legacy: bool = False, schema: int | None = None) -> dict:
    if not isinstance(game, str) or game not in DEFAULT_SETTINGS["games"] or not isinstance(value, dict):
        raise ValueError("Onbekende game of instellingen.")
    if schema is not None and (type(schema) is not int or schema not in (1, 2, 3, 4)):
        raise ValueError("Onbekende voorkeurenschemaversie.")
    legacy = legacy or schema == 1
    schema_two = game == "a2racer1" and not legacy and (schema == 2 or schema is None and set(value) == SCHEMA_TWO_PREFERENCE_KEYS)
    schema_three = game == "a2racer1" and not legacy and (schema == 3 or schema is None and set(value) == SCHEMA_THREE_PREFERENCE_KEYS)
    old_ii = game == 'a2racer2' and set(value) == LEGACY_PREFERENCE_KEYS
    previous_ii = game == 'a2racer2' and set(value) == LEGACY_PREFERENCE_KEYS | {'menu_profile'}
    display_ii = game == 'a2racer2' and set(value) == LEGACY_PREFERENCE_KEYS | {'menu_profile','race_display'}
    expected = (LEGACY_PREFERENCE_KEYS if old_ii or legacy and game != 'a2racer2' else
                LEGACY_PREFERENCE_KEYS | {'menu_profile'} if previous_ii else
                LEGACY_PREFERENCE_KEYS | {'menu_profile','race_display'} if display_ii else
                SCHEMA_TWO_PREFERENCE_KEYS if schema_two else SCHEMA_THREE_PREFERENCE_KEYS if schema_three else set(DEFAULT_SETTINGS["games"][game]))
    if set(value) != expected:
        raise ValueError("Onbekende of ontbrekende launcheropties.")
    if (type(value["intro"]) is not bool or type(value["debug"]) is not bool
            or type(value["fps"]) is not int or not isinstance(value["graphics"], str)):
        raise ValueError("Ongeldige instellingstypen.")
    if game == "a2racer2":
        if value["graphics"] != "native" or value["dashboard"] is not None or value["fps"] != 0:
            raise ValueError("Deel II gebruikt voorlopig uitsluitend de native beeld- en tempo-opties.")
        result = deepcopy(value)
        # Frozen five-field sessions keep their original native route.
        if old_ii:
            result['menu_profile'] = 'original'
        if old_ii or previous_ii:
            result['race_display'] = 'classic' if result['menu_profile'] == 'original' else 'widescreen'
        if not isinstance(result['menu_profile'],str) or result['menu_profile'] not in ii_frontend_launcher.MENU_PROFILES:
            raise ValueError('Onbekend deel-II-menuprofiel.')
        if not isinstance(result['race_display'], str) or result['race_display'] not in ('classic','widescreen'):
            raise ValueError('Onbekende deel-II-raceweergave.')
        if old_ii or previous_ii or display_ii:
            result.update(ii_launcher_graphics.DEFAULTS)
        ii_launcher_graphics.validate_options({key:result[key] for key in ii_launcher_graphics.CHOICES})
        return result
    if type(value["dashboard"]) is not bool or value["fps"] not in (20, 30):
        raise ValueError("Ongeldige deel-I-opties.")
    if legacy:
        if value["graphics"] not in LEGACY_GRAPHICS:
            raise ValueError("Onbekende oorspronkelijke beeldkeuze.")
        old = LEGACY_GRAPHICS[value["graphics"]]
        result = deepcopy(value)
        result.update(graphics=old["native"], display_profile=old["display"], camera_profile="original",
                      render_distance_profile=old.get("render_distance_profile", "original"),
                      object_distance_profile="original", texture_profile="original", menu_profile="original", native_horizon=-1, race_focus_recovery=False)
        return validate_preferences(game, result)
    if schema_two:
        value = deepcopy(value)
        value["texture_profile"] = "original"
    if schema_two or schema_three:
        value = deepcopy(value)
        value["menu_profile"] = "original"
    for field, catalog in (("graphics", GRAPHICS), ("display_profile", DISPLAY_PROFILES),
                           ("camera_profile", CAMERA_PROFILES), ("render_distance_profile", RENDER_DISTANCES),
                           ("object_distance_profile", OBJECT_DISTANCES), ("texture_profile", TEXTURE_PROFILES),
                           ("menu_profile", MENU_PROFILES)):
        if not isinstance(value[field], str) or value[field] not in catalog:
            raise ValueError("Onbekende deel-I-beeldoptie: " + field)
    if type(value["race_focus_recovery"]) is not bool or type(value["native_horizon"]) is not int or value["native_horizon"] not in (-1, 0, 1):
        raise ValueError("Ongeldige focus- of horizonkeuze.")
    display = DISPLAY_PROFILES[value["display_profile"]]
    if display["native_graphics"] is not None and display["native_graphics"] != value["graphics"]:
        raise ValueError("Resolutiekeuze past niet bij de renderer.")
    if display["camera_profile"] != value["camera_profile"]:
        raise ValueError("Resolutie en cameraprofiel moeten samen passen.")
    if value["graphics"] == "software-640" and (value["render_distance_profile"] != "original"
            or value["object_distance_profile"] != "original" or value["texture_profile"] != "original" or value["race_focus_recovery"]):
        raise ValueError("Extra zicht, objectselectie, HD-textures en focusherstel vereisen native 3D.")
    return deepcopy(value)


def validate_settings(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != set(DEFAULT_SETTINGS)
            or type(value["schema"]) is not int or value["schema"] not in (1, 2, 3, 4)
            or not isinstance(value["selected_game"], str) or value["selected_game"] not in DEFAULT_SETTINGS["games"]
            or not isinstance(value["games"], dict) or set(value["games"]) != set(DEFAULT_SETTINGS["games"])):
        raise ValueError("Onbekende launcherinstellingen; het bestand wordt niet overschreven.")
    result = deepcopy(value)
    for game, preferences in value["games"].items():
        result["games"][game] = validate_preferences(game, preferences, schema=value["schema"])
    result["schema"] = 4
    return result


def read_json(path: Path) -> dict:
    validate_ancestors(path)
    if not path.is_file() or path.stat().st_size > 16384:
        raise ValueError("Launcherbestand ontbreekt of is te groot.")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_settings(root: Path) -> dict:
    path = root / "local/launcher/settings.json"
    validate_ancestors(path)
    return validate_settings(read_json(path)) if path.exists() else deepcopy(DEFAULT_SETTINGS)


def write_atomic(path: Path, value: dict) -> None:
    validate_ancestors(path)
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError("Launcherbestand is geen zelfstandige gewone file.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "-" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        for attempt, delay in enumerate((0, 0.05, 0.1, 0.15)):
            if delay:
                time.sleep(delay)
            validate_ancestors(path)
            validate_ancestors(temporary)
            if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
                raise ValueError("Launcherbestand is geen zelfstandige gewone file.")
            if not temporary.is_file() or temporary.stat().st_nlink != 1:
                raise ValueError("Tijdelijk launcherbestand is niet zelfstandig.")
            try:
                os.replace(temporary, path)
                break
            except OSError as error:
                if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 3:
                    raise
    finally:
        temporary.unlink(missing_ok=True)


def save_preferences(root: Path, game: str, preferences: dict) -> dict:
    preferences = validate_preferences(game, preferences)
    settings = load_settings(root)
    settings["games"][game] = preferences
    settings["selected_game"] = game
    write_atomic(root / "local/launcher/settings.json", settings)
    return settings


def game_availability(root: Path, game: str) -> dict:
    source = root / "local/games" / game
    result = {"ready": False, "reason": "Gamebestanden ontbreken.", "experimental": game == "a2racer2"}
    if game == 'a2racer2':
        result['source_ready'] = False
    try:
        for name, expected in EXPECTED_BINARIES[game].items():
            path = source / name
            validate_ancestors(path)
            if not path.is_file():
                return result
            if path.stat().st_size > 2 * 1024**2 or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("Andere binaryversie gevonden; start geblokkeerd.")
        if game == "a2racer1":
            from tools.local_game_data import check_local_source
            check_local_source(source)
            result.update(ready=True, reason="Lokale gamebestanden gecontroleerd.")
        else:
            result['source_ready'] = True
            native = ii_original_launcher.availability(root)
            result.update(ready=native['available'], reason=native['reason'])
    except (OSError, ValueError) as exc:
        result["reason"] = str(exc)
    return result


def texture_availability(root: Path, profile: str) -> dict:
    """Check every fixed, pinned local asset; never load game resources or write."""
    if not isinstance(profile, str) or profile not in TEXTURE_PROFILES:
        raise ValueError("Onbekend launchertextureprofiel.")
    if profile == "original":
        return {"available": True, "reason": ""}
    metadata = TEXTURE_PROFILES[profile]
    native_profile = metadata.get("native_texture_profile", profile)
    result = {"available": False, "reason": "Een gekozen HD-texture ontbreekt in deze kopie."}
    try:
        from tools.resource_archive import MAX_RESOURCE_BYTES, texture_asset_specs
        from tools.pcx_codec import decode_pcx
        specs = texture_asset_specs(native_profile)
        if not specs:
            raise ValueError("HD-profiel mist zijn vaste texturecontracten.")
        for spec in specs:
            if not spec["sha256"]:
                result["reason"] = "Een HD-texture is nog niet gecontroleerd en voorbereid."
                return result
            relative = Path(spec["path"])
            if relative.is_absolute() or any(part in ("..", ".") for part in relative.parts):
                raise ValueError("Onveilig vast texturepad.")
            path = root / relative
            validate_ancestors(path)
            if not path.is_file():
                return result
            if not 1 <= path.stat().st_size <= MAX_RESOURCE_BYTES:
                raise ValueError("HD-texture heeft een ongecontroleerde grootte.")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != spec["sha256"]:
                raise ValueError("HD-texture wijkt af van het gecontroleerde bestand.")
            image = decode_pcx(data)
            if (image.width, image.height) != tuple(spec["dimensions"]):
                raise ValueError("HD-texture heeft afwijkende afmetingen.")
            if "atlas_anchor_guards" in spec:
                from tools.vehicle_mesh import validate_atlas_anchors
                validate_atlas_anchors(image, spec["atlas_anchor_guards"])
        if native_profile in ("hd-scenery-cockpit", "hd-expanded-v1"):
            from tools.sprite_archive import MAX_RESOURCE_BYTES as MAX_SPRITE_BYTES, sprite_asset_specs, validate_asset
            sprite_specs = sprite_asset_specs(native_profile)
            if not sprite_specs:
                raise ValueError("Cockpitprofiel mist zijn vaste spritecontracten.")
            for spec in sprite_specs:
                if not spec["sha256"]:
                    result["reason"] = "Een cockpit- of metertexture is nog niet gecontroleerd en voorbereid."
                    return result
                relative = Path(spec["path"])
                if relative.is_absolute() or any(part in ("..", ".") for part in relative.parts):
                    raise ValueError("Onveilig vast cockpittexturepad.")
                path = root / relative
                validate_ancestors(path)
                if not path.is_file():
                    result["reason"] = ("Het nieuwe boetekaartje ontbreekt in deze kopie." if native_profile == "hd-scenery-cockpit"
                                        else "Een cockpit- of metertexture ontbreekt in deze kopie.")
                    return result
                if not 1 <= path.stat().st_size <= MAX_SPRITE_BYTES:
                    raise ValueError("Cockpittexture heeft een ongecontroleerde grootte.")
                validate_asset(path.read_bytes(), spec)
        if "hud_profile" in metadata:
            from tools.hud_hd_fix import load_profile_assets
            load_profile_assets(root, metadata["hud_profile"])
        result.update(available=True, reason="")
    except (OSError, ValueError) as exc:
        result["reason"] = str(exc)
    return result


def require_texture(root: Path, game: str, preferences: dict) -> None:
    if game == "a2racer1":
        metadata = TEXTURE_PROFILES[preferences["texture_profile"]]
        if "hud_profile" in metadata and (preferences["display_profile"] not in metadata["hud_displays"]
                                         or not preferences["race_focus_recovery"]):
            raise ValueError("HD textures vereist een HD-resolutie en Alt+Tab-herstel.")
        available = texture_availability(root, preferences["texture_profile"])
        if not available["available"]:
            raise ValueError(available["reason"])


def menu_availability(root: Path, profile: str) -> dict:
    result = {"available": True, "reason": "", "runtime_verified": False}
    if profile not in MENU_PROFILES:
        raise ValueError("Onbekend menuprofiel.")
    if profile == "refreshed-fullscreen":
        from tools.menu_art_fix import validate_pack
        try:
            validate_pack(root / "local/mods/a2racer1/menu-refresh-v1")
        except (OSError, ValueError) as exc:
            result.update(available=False, reason=str(exc))
    if profile == "hd-fullscreen":
        from tools.i_frontend_prepare import validate_art
        try:
            validate_art(root)
        except (OSError, ValueError) as exc:
            result.update(available=False, reason=str(exc))
    return result


def require_menu(root: Path, game: str, preferences: dict) -> None:
    if game == "a2racer1":
        available = menu_availability(root, preferences["menu_profile"])
        if not available["available"]:
            raise ValueError(available["reason"])


def iii_preparation(root: Path) -> dict:
    """Read-only source status; deliberately outside playable games/settings."""
    tours = {}
    for number, digest in ((1, '4754e7d6374563103ff56ead0eeb685f8e90bcd8e211c9cd30bf37f92eb00f8d'),
                           (2, '17e8da1b6a8f69c998ad6eb239efa9465665729d837b779c8a39ffa9379e883e')):
        folder = root / 'local/iii-prepared/baseline-20261013' / f'tour{number}'
        play = root / f'local/iii-play/tour{number}'
        if play.exists():
            folder = play
        present = False
        try:
            for name in ('spel.dat', f'A2 Racer III Tour {number}.exe', 'raser.ini'):
                path = folder / name
                validate_ancestors(path)
                if not path.is_file():
                    raise ValueError('Bron ontbreekt.')
            with (folder / 'spel.dat').open('rb') as stream:
                present = hashlib.file_digest(stream, 'sha256').hexdigest() == digest
        except (OSError, ValueError):
            pass
        launch_ready = False
        if present:
            try:
                from tools.iii_local_launcher import check as check_iii
                launch_ready = check_iii(root, number)['launch_ready']
            except (OSError, ValueError, KeyError):
                pass
        from tools.iii_compat_launcher import PROFILES, available
        profiles = {name: {**entry, **(available(root, number, name) if launch_ready else
                     {'available': False, 'reason': 'Koppel eerst de volledige gamemap van deze tour.'})}
                    for name,entry in PROFILES.items()}
        profiles['original'] = {'available': launch_ready, 'label': 'Origineel',
                                'reason': 'Originele schermmodus; de racecrash is gemeld bij Tour 1.'}
        tours[str(number)] = {'label': f'Tour {number}', 'source_present': present,
                             'launch_ready': launch_ready,
                             'profiles': profiles,
                             'ready': False, 'runtime_verified': False,
                             'reason': ('Start zonder cd gereed · speelbaarheid nog niet bevestigd.' if launch_ready else
                                        'Bron beschikbaar · voorbereid, nog niet speelgetest.' if present
                                        else 'Lokale proefbron ontbreekt of wijkt af.')}
    return {'tours': tours, 'ready': False}


def ii_graphics_support(root: Path) -> dict:
    result = {}
    for resolution in ii_launcher_graphics.CHOICES['race_resolution']:
        result[resolution] = {}
        for hud in ii_launcher_graphics.CHOICES['race_hud']:
            try:
                options = dict(ii_launcher_graphics.DEFAULTS, race_resolution=resolution, race_hud=hud)
                ii_launcher_graphics.check_options(root, options)
                entry = {'available': True, 'reason': ''}
            except (OSError, ValueError, KeyError, TypeError) as exc:
                entry = {'available': False, 'reason': str(exc)}
            result[resolution][hud] = entry
    return result


def snapshot(root: Path) -> dict:
    return {"settings": load_settings(root), "default_settings": deepcopy(DEFAULT_SETTINGS),
            "graphics": GRAPHICS, "displays": DISPLAY_PROFILES, "cameras": CAMERA_PROFILES,
            "render_distances": RENDER_DISTANCES, "object_distances": OBJECT_DISTANCES,
            "textures": {profile: {**entry, **texture_availability(root, profile)}
                         for profile, entry in TEXTURE_PROFILES.items()},
            "menus": {profile: {**entry, **menu_availability(root, profile)}
                      for profile, entry in MENU_PROFILES.items()},
            "ii_menus": {profile: {**entry, **(ii_frontend_launcher.availability(root) if profile == 'revival'
                         else {'available': game_availability(root,'a2racer2')['ready'], 'reason': ''})}
                         for profile, entry in ii_frontend_launcher.MENU_PROFILES.items()},
            "games": {game: game_availability(root, game) for game in DEFAULT_SETTINGS["games"]},
            "i_profiles": deepcopy(I_PROFILES), "ii_profiles": deepcopy(II_PROFILES), "ii_graphics": deepcopy(ii_launcher_graphics.CHOICES), "ii_graphics_support": ii_graphics_support(root), "iii_preparation": iii_preparation(root), "latest_session": latest_session(root)}


def latest_session(root: Path) -> str | None:
    parent = root / "local/launcher/sessions"
    validate_ancestors(parent)
    if not parent.is_dir():
        return None
    # Only names are returned; never follow paths supplied by a log or request.
    for path in sorted(parent.iterdir(), key=lambda p: p.name, reverse=True)[:100]:
        try:
            validate_ancestors(path / "status.json")
            if session_directory(root, path.name).is_dir() and (path / "status.json").is_file():
                status = read_json(path / "status.json")
                if isinstance(status, dict) and status.get("run_name") == path.name:
                    return path.name
        except (OSError, ValueError):
            continue
    return None


def session_directory(root: Path, name: str) -> Path:
    validate_slug(name)
    if not name.startswith("launcher-"):
        raise ValueError("Onbekende launchersessie.")
    path = root / "local/launcher/sessions" / name
    validate_ancestors(path)
    return path


def create_session(root: Path, game: str, preferences: dict) -> dict:
    preferences = validate_preferences(game, preferences)
    if game == 'a2racer2' and preferences['menu_profile'] == 'revival':
        frontend = ii_frontend_launcher.availability(root)
        availability = dict(ready=frontend['available'], reason=frontend['reason'])
        if availability['ready'] and preferences['race_display'] == 'widescreen':
            ii_launcher_graphics.check_options(root,{key:preferences[key] for key in ii_launcher_graphics.CHOICES})
    else:
        availability = game_availability(root, game)
    if not availability["ready"]:
        raise ValueError(availability["reason"])
    require_texture(root, game, preferences)
    require_menu(root, game, preferences)
    # Refuse invalid persisted settings before writing a session or changing them.
    load_settings(root)
    name = "launcher-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    folder = session_directory(root, name)
    folder.mkdir(parents=True, exist_ok=False)
    request = {"schema": 4, "run_name": name, "game": game, "preferences": preferences,
               "created_utc": datetime.now(timezone.utc).isoformat()}
    with (folder / "request.json").open("x", encoding="utf-8") as handle:
        json.dump(request, handle, ensure_ascii=False, indent=2)
    save_preferences(root, game, preferences)
    return {"run_name": name, "session_path": str(folder)}


def launch_plan(root: Path, name: str) -> dict:
    folder = session_directory(root, name)
    request = read_json(folder / "request.json")
    if (not isinstance(request, dict) or set(request) != {"schema", "run_name", "game", "preferences", "created_utc"}
            or type(request["schema"]) is not int or request["schema"] not in (1, 2, 3, 4) or request["run_name"] != name):
        raise ValueError("Ongeldig startverzoek.")
    game = request["game"]
    preferences = validate_preferences(game, request["preferences"], schema=request["schema"])
    if game == 'a2racer2' and preferences['menu_profile'] == 'revival':
        frontend = ii_frontend_launcher.registered_menu(root)
        arguments = ['-RaceDisplay', preferences['race_display']]
        trial = Path(frontend['base'])/'game'
        report = frontend['report_path']
        if set(ii_launcher_graphics.CHOICES).issubset(request['preferences']):
            if preferences['race_display'] == 'widescreen':
                ii_launcher_graphics.check_options(root,{key:preferences[key] for key in ii_launcher_graphics.CHOICES})
            arguments += ['-RunName',name]
            for key,flag in (('race_resolution','-RaceResolution'),('race_hud','-RaceHud'),('sky_mode','-SkyMode'),('race_distance','-RenderDistance')):
                arguments += [flag,preferences[key]]
            trial = ii_launcher_graphics.target_folder(root,name)/'game'
            report = str(root/'reports/a2racer2-next'/trial.parent.name)
        return {'run_name': name, 'game': game, 'script': 'Invoke-IIFrontend.ps1', 'arguments': arguments,
                'session_path': str(folder), 'trial_path': str(trial),
                'report_path': report, 'debug': False, 'preferences': preferences,
                'menu_profile': 'revival', 'requires_disc': False}
    if game == 'a2racer2':
        native = ii_original_launcher.registered_menu(root)
        return {'run_name': name, 'game': game, 'script': 'Invoke-IIOriginalMenu.ps1', 'arguments': [],
                'session_path': str(folder), 'trial_path': str(Path(native['base'])/'game'),
                'report_path': native['report_path'], 'debug': False, 'preferences': preferences,
                'menu_profile': 'original', 'requires_disc': False}
    available = game_availability(root, game)
    if not available["ready"]:
        raise ValueError(available["reason"])
    require_texture(root, game, preferences)
    require_menu(root, game, preferences)
    arguments = ["-RunName", name, "-DurationSeconds", "180" if preferences["debug"] else "20"]
    if game == "a2racer1" and preferences["menu_profile"] == "hd-fullscreen":
        texture = TEXTURE_PROFILES[preferences["texture_profile"]]
        arguments += ["-RaceFPSLimit", str(preferences["fps"]),
                      "-DisplayProfile", preferences["display_profile"], "-CameraProfile", preferences["camera_profile"],
                      "-NativeGraphics", preferences["graphics"], "-NativeDashboard", str(int(preferences["dashboard"])),
                      "-NativeHorizon", str(preferences["native_horizon"]),
                      "-RenderDistanceProfile", preferences["render_distance_profile"],
                      "-ObjectDistanceProfile", preferences["object_distance_profile"],
                      "-TextureProfile", texture.get("native_texture_profile", preferences["texture_profile"]),
                      "-HudProfile", texture.get("hud_profile", "original")]
        if preferences["intro"]:
            arguments += ["-Intro"]
        if preferences["race_focus_recovery"]:
            arguments += ["-RaceFocusRecovery"]
        if preferences["debug"]:
            arguments += ["-EnableGameDebug", "-StopAtEnd"]
        trial_root = root / "local/experiments/a2racer1" / name / "game"
        validate_ancestors(trial_root)
        return {"run_name": name, "game": game, "script": "Start-IHDMenu.ps1", "arguments": arguments,
                "session_path": str(folder), "trial_path": str(trial_root),
                "report_path": str(root / "reports/runtime/a2racer1" / name),
                "debug": preferences["debug"], "preferences": preferences}
    script = "Invoke-A2Trial.ps1"
    if game == "a2racer1":
        arguments += ["-RaceFPSLimit", str(preferences["fps"]), "-DisplayProfile", preferences["display_profile"],
                      "-NativeGraphics", preferences["graphics"], "-NativeDashboard", "1" if preferences["dashboard"] else "0",
                      "-NativeHorizon", str(preferences["native_horizon"])]
        # The player approved this start repair for every part-I play route.
        # Low-level preparation retains an explicit unpatched research baseline.
        arguments += ["-PumpLauncherMessages", "-LocalGameData"]
        for field, flag in (("render_distance_profile", "-RenderDistanceProfile"),
                            ("camera_profile", "-CameraProfile"), ("object_distance_profile", "-ObjectDistanceProfile"),
                            ("texture_profile", "-TextureProfile"), ("menu_profile", "-MenuProfile")):
            if preferences[field] != "original":
                choice = preferences[field]
                if field == "texture_profile":
                    choice = TEXTURE_PROFILES[choice].get("native_texture_profile", choice)
                arguments += [flag, choice]
        texture = TEXTURE_PROFILES[preferences["texture_profile"]]
        if "hud_profile" in texture:
            arguments += ["-HudProfile", texture["hud_profile"]]
        if preferences["race_focus_recovery"]:
            arguments += ["-RaceFocusRecovery"]
        if preferences["intro"]:
            script = "Invoke-A2WithIntro.ps1"
        else:
            arguments += ["-Game", game, "-Stage", "launcher", "-GraphicsWrapper", "hybrid-dgvoodoo",
                          "-OmitNativeIntro", "-AnyKeyWelcome", "-KeepNativeOptions", "-HideWatermark"]
    else:
        arguments += ["-Game", game, "-Stage", "launcher"]
        if not preferences["intro"]:
            arguments += ["-DisableMovies"]
    if preferences["debug"]:
        arguments += ["-EnableGameDebug", "-StopAtEnd"]
    trial_root = root / "local/experiments" / game / name / "game"
    validate_ancestors(trial_root)
    return {"run_name": name, "game": game, "script": script, "arguments": arguments,
            "session_path": str(folder), "trial_path": str(trial_root),
            "report_path": str(root / "reports/runtime" / game / name), "debug": preferences["debug"],
            "preferences": preferences}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("snapshot")
    sub.add_parser('ii-menu-plan')
    sub.add_parser('ii-original-menu-plan')
    for action in ("save", "create-session"):
        item = sub.add_parser(action)
        item.add_argument("--game", choices=tuple(DEFAULT_SETTINGS["games"]), required=True)
        item.add_argument("--graphics", required=True)
        item.add_argument("--display-profile", choices=tuple(DISPLAY_PROFILES))
        item.add_argument("--camera-profile", choices=tuple(CAMERA_PROFILES))
        item.add_argument("--render-distance-profile", choices=tuple(RENDER_DISTANCES))
        item.add_argument("--object-distance-profile", choices=tuple(OBJECT_DISTANCES))
        item.add_argument("--texture-profile", choices=tuple(TEXTURE_PROFILES))
        item.add_argument("--menu-profile", choices=tuple(dict.fromkeys((*MENU_PROFILES,*ii_frontend_launcher.MENU_PROFILES))))
        item.add_argument('--race-display', choices=('classic','widescreen'))
        for key,choices in ii_launcher_graphics.CHOICES.items():
            item.add_argument('--'+key.replace('_','-'),choices=tuple(choices))
        item.add_argument("--native-horizon", type=int, choices=(-1, 0, 1))
        item.add_argument("--race-focus-recovery", type=int, choices=(0, 1))
        item.add_argument("--fps", type=int, required=True)
        item.add_argument("--dashboard", type=int, choices=(-1, 0, 1), required=True)
        item.add_argument("--intro", type=int, choices=(0, 1), required=True)
        item.add_argument("--debug", type=int, choices=(0, 1), required=True)
    item = sub.add_parser("plan")
    item.add_argument("--session", required=True)
    item = sub.add_parser("import-game")
    item.add_argument("--archive", type=Path, required=True)
    item.add_argument('--game', choices=('a2racer1','a2racer2'), default='a2racer1')
    sub.add_parser('detect-installations')
    item = sub.add_parser('import-installation')
    item.add_argument('--folder', type=Path, required=True)
    item.add_argument('--game', choices=('a2racer1','a2racer2'), default='a2racer1')
    sub.add_parser('prepare-ii')
    item = sub.add_parser('import-iii-installation')
    item.add_argument('--folder', type=Path, required=True)
    item.add_argument('--tour', type=int, choices=(1,2), required=True)
    args = parser.parse_args()
    try:
        if args.action == "snapshot":
            result = snapshot(ROOT)
        elif args.action == 'ii-original-menu-plan':
            result = ii_original_launcher.registered_menu(ROOT)
        elif args.action == 'ii-menu-plan':
            result = ii_frontend_launcher.registered_menu(ROOT)
        elif args.action == "plan":
            result = launch_plan(ROOT, args.session)
        elif args.action == "import-game":
            from tools.portable_test import import_game
            result = import_game(ROOT, args.archive, args.game)
            if args.game == 'a2racer2':
                from tools.ii_portable_prepare import prepare
                result.update(prepare(ROOT, sys.executable))
        elif args.action == 'detect-installations':
            from tools.game_installation import discover
            result = discover(ROOT)
        elif args.action == 'import-installation':
            from tools.game_installation import import_installation
            result = import_installation(ROOT, args.folder, args.game)
            if args.game == 'a2racer2':
                from tools.ii_portable_prepare import prepare
                result.update(prepare(ROOT, sys.executable))
        elif args.action == 'prepare-ii':
            from tools.ii_portable_prepare import prepare
            result = prepare(ROOT, sys.executable)
        elif args.action == 'import-iii-installation':
            from tools.iii_installation import import_folder
            result = import_folder(ROOT, args.folder, args.tour)
        else:
            preferences = {"graphics": args.graphics, "fps": args.fps,
                           "dashboard": None if args.dashboard == -1 else bool(args.dashboard),
                           "intro": bool(args.intro), "debug": bool(args.debug)}
            if args.race_display is not None and args.game != 'a2racer2':
                raise ValueError('Deze raceweergavekeuze hoort bij deel II.')
            extra = {"display_profile": args.display_profile, "camera_profile": args.camera_profile,
                     "render_distance_profile": args.render_distance_profile,
                     "object_distance_profile": args.object_distance_profile,
                     "native_horizon": args.native_horizon, "race_focus_recovery": args.race_focus_recovery}
            supplied = [value is not None for value in extra.values()]
            if any(supplied):
                if args.game != "a2racer1" or not all(supplied):
                    raise ValueError("Nieuwe beeldopties moeten volledig en uitsluitend voor deel I worden aangeleverd.")
                extra["race_focus_recovery"] = bool(extra["race_focus_recovery"])
                # Version-2 CLI callers have no texture flag; retain their exact
                # choices while opting into the original texture by default.
                extra["texture_profile"] = args.texture_profile or "original"
                extra["menu_profile"] = args.menu_profile or "original"
                preferences.update(extra)
            elif args.game == "a2racer1":
                if args.texture_profile is not None or args.menu_profile is not None:
                    raise ValueError("Een texturekeuze vereist de volledige deel-I-beeldopties.")
                # Older callers send only the five known version-1 keys.
                preferences = validate_preferences(args.game, preferences, legacy=True)
            elif args.texture_profile is not None:
                raise ValueError("HD-texturekeuzes zijn uitsluitend beschikbaar voor deel I.")
            elif args.game == 'a2racer2':
                preferences['menu_profile'] = args.menu_profile or 'original'
                preferences['race_display'] = args.race_display or ('widescreen' if preferences['menu_profile']=='revival' else 'classic')
                for key in ii_launcher_graphics.CHOICES:
                    preferences[key] = getattr(args,key) or DEFAULT_SETTINGS['games']['a2racer2'][key]
            if args.game != 'a2racer2' and any(getattr(args,key) is not None for key in ii_launcher_graphics.CHOICES):
                raise ValueError('Deze beeldopties horen uitsluitend bij deel II.')
            result = (save_preferences if args.action == "save" else create_session)(ROOT, args.game, preferences)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
