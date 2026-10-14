"""Bounded presentation choices for the original A2 Racer I menu canvas.

These options keep the native 640x480 menu and its controls. They request an
actual 640x480 display mode, with no wrapper enlargement of child controls.
They only plan cnc-ddraw bytes; they do not render, load a DLL, or query modes.
The refreshed profile selects the same presentation as the classic profile.
Its optional artwork is planned separately by the caller.

The pinned v7.0.0.0 dd_SetDisplayMode code uses windowed=false for display
switching and fullscreen=true for desktop-size enlargement. Both false with
width/height=640/480 requests native-size fullscreen. The caller must check
exact mode support first: the wrapper can otherwise fall back to a larger or
borderless mode. Only [A2MENU] receives overrides. This is static configuration
evidence, not a successful A2 fullscreen or focus-recovery runtime test.
"""

PROFILES = ("original", "classic-fullscreen", "refreshed-fullscreen")
RENDER_PROFILES = ("original", "gdi-30", "gdi-30-direct")
KNOWN_GAMES = ("a2racer1", "a2racer2")
KNOWN_STAGES = ("launcher", "intro", "menu", "race")
KNOWN_WRAPPERS = (
    "native", "dxwrapper-windowed", "cnc-ddraw-gdi", "hybrid-windowed",
    "hybrid-dgvoodoo", "dgvoodoo-windowed",
)
SUPPORTED_WRAPPERS = ("cnc-ddraw-gdi", "hybrid-windowed", "hybrid-dgvoodoo")

# Kept independent from the trial planner to avoid a circular import. The
# caller passes its existing bytes; unknown or changed base configs fail shut.
EXPECTED_BASE_CONFIG = (
    b"[ddraw]\nwindowed=true\nfullscreen=false\n"
    b"renderer=gdi\nborder=true\nsavesettings=0\n"
)
MENU_FULLSCREEN_OVERRIDES = (
    b"\n[A2MENU]\nwindowed=false\nfullscreen=false\nwidth=640\nheight=480\n"
    b"renderer=gdi\nfixchilds=2\nborder=false\nresizable=false\n"
    b"maintas=true\naspect_ratio=4:3\nadjmouse=true\n"
    b"nonexclusive=true\nsavesettings=0\n"
)


def validate_profile(game: str, stage: str, wrapper: str, profile: str) -> None:
    """Reject unsupported presentation requests before any trial writes."""
    for value, choices, label in (
        (game, KNOWN_GAMES, "game"), (stage, KNOWN_STAGES, "startfase"),
        (wrapper, KNOWN_WRAPPERS, "wrapper"), (profile, PROFILES, "menuprofiel"),
    ):
        if type(value) is not str or value not in choices:
            raise ValueError(f"Onbekende {label} voor menupresentatie.")
    if profile != "original" and (
        game != "a2racer1" or stage not in ("launcher", "menu")
        or wrapper not in SUPPORTED_WRAPPERS
    ):
        raise ValueError(
            "Menupresentatie vereist deel I, launcher/menu en de bekende cnc-ddraw-route."
        )


def validate_render_profile(profile: str, render_profile: str) -> None:
    if type(render_profile) is not str or render_profile not in RENDER_PROFILES:
        raise ValueError("Onbekende menu-renderproef.")
    if render_profile != "original" and profile not in PROFILES[1:]:
        raise ValueError("Menu-renderproef vereist een optionele fullscreen-menuvariant.")


def cnc_menu_config(original_config: bytes, profile: str,
                    render_profile: str = "original") -> bytes:
    """Return the exact original config or an explicit opt-in presentation.

    Preserve the complete global section and append only the executable menu
    section. The caller can keep the known root DLL: no new .local redirection
    is required. Global renderer=gdi and savesettings=0 remain the inherited
    defaults; the menu section repeats them to pin GDI and prevent exit-time
    settings overwrite. Hardware-mode support is a caller precondition.
    """
    if type(profile) is not str or profile not in PROFILES:
        raise ValueError("Onbekend menuprofiel.")
    if type(original_config) is not bytes or original_config != EXPECTED_BASE_CONFIG:
        raise ValueError("Onbekende basisconfiguratie voor cnc-ddraw-menupresentatie.")
    validate_render_profile(profile, render_profile)
    if profile == "original":
        return original_config
    overrides = MENU_FULLSCREEN_OVERRIDES
    if render_profile != "original":
        # Pinned v7 supports these keys. Scope only A2MENU; race pacing is separate.
        overrides += b"maxfps=30\nminfps=0\n"
        if render_profile == "gdi-30-direct":
            # Native HWNDs remain; disable wrapper child detection/black clear.
            # Visibility, edit caret and repaint behavior still require runtime QA.
            overrides = overrides.replace(b"fixchilds=2\n", b"fixchilds=0\n")
    return original_config + overrides
