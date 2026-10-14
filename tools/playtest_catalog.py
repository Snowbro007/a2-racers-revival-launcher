"""Fixed, reviewable local playtest plans. Planning never starts a game."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROFILES = {
    "i-base": {"game": "a2racer1", "label": "I - Werkende basis", "display": "hd-1280x960", "camera": "original", "texture": "original", "note": "1280x960-verzoek, 20 FPS, 20x20, Horizon Uit, dashboard en focusherstel. Referentie voor de nieuwe proeven."},
    "i-1080-control": {"game": "a2racer1", "label": "I - 1080 hoog - 4-3", "display": "hd-1440x1080", "camera": "original", "texture": "original", "note": "1440x1080-verzoek met 4:3-verhouding en zijbalken; vergelijk scherpte met de basis."},
    "i-4k-control": {"game": "a2racer1", "label": "I - 4K hoog - 4-3", "display": "hd-2880x2160", "camera": "original", "texture": "original", "note": "2880x2160-verzoek met 4:3-verhouding. Hoge GPU-belasting; echte renderresolutie nog niet gemeten."},
    "i-wide-1080": {"game": "a2racer1", "label": "I - 1080p - 16-9 camera", "display": "hd-1920x1080-camera", "camera": "camera-16-9", "texture": "original", "note": "Experimentele bredere camera. HUD/dashboard kunnen uitrekken en objecten aan de zijkant kunnen verdwijnen; nog geen volledige widescreenfix."},
    "i-wide-4k": {"game": "a2racer1", "label": "I - 4K - 16-9 camera", "display": "hd-3840x2160-camera", "camera": "camera-16-9", "texture": "original", "note": "Dezelfde experimentele camera met 3840x2160-verzoek. Test eerst de 1080p-camera; HUD en zijculling blijven open."},
    "i-texture-road": {"game": "a2racer1", "label": "I - HD wegtexture", "display": "hd-1280x960", "camera": "original", "texture": "hd-road-256", "note": "Eén nieuwe optionele wegtexture, 256x256 in het oorspronkelijke palet. Vergelijk met Werkende basis op dezelfde etappe."},
    "ii-native-movies": {"game": "a2racer2", "label": "II - Native - films aan", "wrapper": "native", "movies_off": False, "note": "Oorspronkelijke startketen en films, met diagnostische logs. Geen deel-I-camera-, FPS-, zicht- of focuspatch."},
    "ii-native-no-movies": {"game": "a2racer2", "label": "II - Native - films uit", "wrapper": "native", "movies_off": True, "note": "Vergelijk met films aan: uitsluitend de MOVIES-optie verandert naast diagnostische logging."},
    "ii-wrapper-no-movies": {"game": "a2racer2", "label": "II - dgVoodoo - films uit", "wrapper": "dgvoodoo-windowed", "movies_off": True, "note": "Afzonderlijke wrappervergelijking voor de volledige startketen. Menu, audio en race zijn nog niet speelbaar bevestigd."},
    # Append new profiles so the nine existing desktop button numbers stay fixed.
    "i-object-max": {"game": "a2racer1", "label": "I - Alle geladen objecten (optioneel)", "display": "hd-1280x960", "camera": "original", "texture": "original", "objects": "loaded-all", "note": "Optionele objectafstand: alle geladen actieve objecten voor rendering selecteren, met dezelfde 1280x960/20 FPS/20x20/Horizon Uit. Wegselectie blijft gelijk. Kan de ronde rand van de map zichtbaar maken en extra tekenwerk vragen."},
    "i-wide-4k-hd-256": {"game": "a2racer1", "label": "I - 4K - HD weg 256", "display": "hd-3840x2160-camera", "camera": "camera-16-9", "texture": "hd-road-256", "note": "4K-speelvoorkeur met de eerdere optionele 256x256-wegtexture. Vergelijk op hetzelfde wegpunt met 4K zonder texturemod."},
    "i-wide-4k-hd-512": {"game": "a2racer1", "label": "I - 4K - HD weg 512 (proef)", "display": "hd-3840x2160-camera", "camera": "camera-16-9", "texture": "hd-road-512", "note": "Optionele scherpere 512x512-wegtexture met fijner asfalt. Nog te spelen; vergelijk op hetzelfde wegpunt met 4K zonder mod en de 256-versie. Objectafstand blijft origineel."},
    "i-wide-1080-hd-scenery": {"game": "a2racer1", "label": "I - 1080p - HD omgeving extra scherp", "display": "hd-1920x1080-camera", "camera": "camera-16-9", "texture": "hd-scenery-1024", "note": "Nieuwe optionele proef met 1024x1024-asfalt en een 512x512-texture voor berm en vangrail. Vergelijk op hetzelfde wegpunt met 1080p zonder mod en de eerdere 512-wegtexture. Objectafstand blijft origineel; beeld en speelstabiliteit nog testen."},
    "i-wide-1080-cockpit": {"game": "a2racer1", "label": "I - 1080p - Nieuw dashboard en boetekaartje", "display": "hd-1920x1080-camera", "camera": "camera-16-9", "texture": "hd-scenery-cockpit", "note": "Optionele vormgevingsproef met de HD-omgeving, vernieuwde instrumentplaat, minimapbehuizing en boetekaart op de oorspronkelijke 640x480/320x194-afmetingen. Bewegend stuur en meters blijven origineel. Controleer wijzers, lampjes, minimap, wisselende boetebedragen en Enter=Terug. Objectafstand blijft origineel; geen bewezen HD-renderpad voor de 2D-interface."},
    "i-wide-1080-expanded": {"game": "a2racer1", "label": "I - 1080p - HD uitgebreid", "display": "hd-1920x1080-camera", "camera": "camera-16-9", "texture": "hd-expanded-v1", "note": "Bijgewerkte optionele textureproef: scherper wegdek, borden, poster en tankstation; alle racers, verkeersauto's en politie, inclusief bus, bestelwagen en vrachtwagen. Roze meterrand hersteld. Vast dashboard en boetekaart vernieuwd op native afmetingen; bewegend stuur, metercijfers en wijzers blijven origineel. Vergelijk voertuigen dichtbij van voren, achteren en opzij. HD blijft standaard uit. Objectafstand blijft origineel. Nieuwe voertuigen, finish/herstart en focuswissels nog beoordelen."},
    "i-wide-1080-hud-hd": {"game": "a2racer1", "label": "I - 1080p - HD interface (proef)", "display": "hd-1920x1080-camera", "camera": "camera-16-9", "texture": "hd-expanded-v1", "hud": "hd-overlay-v1", "note": "Kaart en vaste dashboarddelen zijn door de gebruiker als scherper bevestigd. Bewegend stuur, meters en minimap blijven native. Vergelijking voor de afzonderlijke HD-cockpitproef; Alt+Tab, herstart en andere boetebedragen zijn nog open."},
    "i-wide-1080-cockpit-hd": {"game": "a2racer1", "label": "I - 1080p - HD stuur en meters (proef)", "display": "hd-1920x1080-camera", "camera": "camera-16-9", "texture": "hd-expanded-v1", "hud": "hd-cockpit-v1", "note": "Afzonderlijke proef bovenop de geslaagde HD-interface: groter getekend stuur met bovenboog, snelheidsmeter, toerenteller en kleine rechtermeter. Volgt de oorspronkelijke animatieframekeuze en onthoudt ongewijzigde frames. Minimap en kleine linkermeter blijven native. Vergelijk met proef17 en controleer links/rechts sturen, accelereren, remmen, dashboard aan/uit, kaart sluiten, herstart en Alt+Tab."},
    "i-wide-1080-cockpit-refined": {"game": "a2racer1", "label": "I - 1080p - HD cockpit en bedrag (correctie)", "display": "hd-1920x1080-camera", "camera": "camera-16-9", "texture": "hd-expanded-v1", "hud": "hd-cockpit-v2", "note": "Correctie op proef18: behoud van de leren dashboardmaterialen uit proef17, metalen stuurspaken en meters op passende ondergrond. Boetebedrag met aansluitende letters en doorlopend kaartpapier. Native animatie en dynamische bedragen blijven leidend. HD blijft optioneel. Controleer aansluiting, sturen, meters, verschillende boetes en Alt+Tab; deze versie is nog niet speelbaar bevestigd."},
    "i-menu-classic-fullscreen": {"game": "a2racer1", "label": "I - Classic menu fullscreen (proef)", "display": "hd-1920x1080-camera", "camera": "camera-16-9", "texture": "original", "menu": "classic-fullscreen", "note": "Afzonderlijke menuproef: originele achtergronden in een randloos volledig scherm met 4:3-verhouding. Race gebruikt 1080p,20FPS,verder wegzicht en focusherstel; HD racetextures blijven uit. Controleer naam invoeren, alle tabbladen, muisklikken, menu/race/menu en Alt+Tab. Native invoervelden kunnen tijdelijk de opschaling veranderen; werking nog te testen."},
    "i-menu-refreshed-fullscreen": {"game": "a2racer1", "label": "I - Opgefrist menu fullscreen (proef)", "display": "hd-1920x1080-camera", "camera": "camera-16-9", "texture": "original", "menu": "refreshed-fullscreen", "note": "Optionele nieuwe menuachtergronden, oorspronkelijke indeling en native knoppen/letters, fullscreen in4:3. Vergelijk met Classic fullscreen. Menu blijft native640x480, geen nieuwe HD-menu-engine. HD racetextures blijven uit. Controleer naam invoeren, tabbladen, muisklikken, menu/race/menu en Alt+Tab. Originelen en eerdere proeven blijven behouden."},
    "i-wide-1080-cockpit-layered": {"game": "a2racer1", "label": "I - 1080p - Meters achter stuur (correctie)", "display": "hd-1920x1080-camera", "camera": "camera-16-9", "texture": "hd-expanded-v1", "hud": "hd-cockpit-v3", "note": "Vergelijk met proef19: dezelfde cockpit en scherpe meters, maar hun vlakken vallen nu achter de bestaande leren stuurrand. Meterposities, stuurframes, boetekaart en native animatie blijven gelijk. Fanprojectmelding verschijnt vóór de start. Controleer kleine meters langs de stuurrand, links/rechts sturen, accelereren, remmen en Alt+Tab. HD blijft optioneel en standaard uit; deze correctie is nog niet in-game bevestigd."},
}


for _profile_id, _render, _label, _note in (
    ("i-menu-30", "gdi-30", "I - Menu 30 FPS (vergelijking)",
     "Opgefrist fullscreenmenu met 30 FPS-presentatielimiet. Controleer knipperen bij stilstaand menu, muis en naam invoeren. Race blijft 1080p/20FPS; HD textures uit."),
    ("i-menu-30-direct", "gdi-30-direct", "I - Menu 30 FPS zonder child-clear (vergelijking)",
     "Vergelijk met Menu 30 FPS: alleen wrapper-childdetectie uit. Native knoppen en naamveld blijven bestaan. Controleer knipperen, zichtbaarheid, typen, klikken en menu/race/menu. Geen bewezen reparatie."),
):
    PROFILES[_profile_id] = deepcopy(PROFILES["i-menu-refreshed-fullscreen"])
    PROFILES[_profile_id].update(menu_render=_render, label=_label, note=_note)


def plan(profile_id: str, run_name: str, root: Path = ROOT) -> dict:
    from tools.trial_manifest import validate_slug, validate_ancestors
    validate_slug(run_name)
    if profile_id not in PROFILES:
        raise ValueError("Onbekende speelproef; kies een vaste proef uit de catalogus.")
    profile = deepcopy(PROFILES[profile_id])
    args = ["-Game", profile["game"], "-Stage", "launcher", "-RunName", run_name,
            "-DurationSeconds", "20"]
    if profile["game"] == "a2racer1":
        args += ["-GraphicsWrapper", "hybrid-dgvoodoo", "-OmitNativeIntro", "-AnyKeyWelcome",
                 "-PumpLauncherMessages", "-RaceFPSLimit", "20", "-HideWatermark",
                 "-LocalGameData", "-KeepNativeOptions", "-NativeGraphics", "accelerated-640",
                 "-NativeDashboard", "1", "-NativeHorizon", "0", "-RenderDistanceProfile", "extended-20",
                 "-RaceFocusRecovery", "-DisplayProfile", profile["display"],
                 "-CameraProfile", profile["camera"], "-TextureProfile", profile["texture"]]
        args += ["-ObjectDistanceProfile", profile.get("objects", "original")]
        if profile.get("hud"):
            args += ["-HudProfile", profile["hud"]]
        if profile.get("menu"):
            args += ["-MenuProfile", profile["menu"]]
        if profile.get("menu_render"):
            args += ["-MenuRenderProfile", profile["menu_render"]]
    else:
        args += ["-GraphicsWrapper", profile["wrapper"]]
        if profile["movies_off"]:
            args += ["-DisableMovies"]
    script = root / "tools/Invoke-A2Trial.ps1"
    report = root / "reports/runtime" / profile["game"] / run_name
    for path in (script, report):
        validate_ancestors(path)
    return {"schema": 1, "id": profile_id, **profile, "run_name": run_name,
            "script": str(script), "arguments": args, "report_path": str(report),
            "stops_game": False, "runtime_verified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "plan"))
    parser.add_argument("--profile", choices=tuple(PROFILES))
    parser.add_argument("--run-name", default="check-only")
    args = parser.parse_args()
    try:
        if args.action == "list":
            result = [{"id": key, **value} for key, value in PROFILES.items()]
        else:
            if not args.profile:
                raise ValueError("Een profiel is vereist.")
            result = plan(args.profile, args.run_name)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
