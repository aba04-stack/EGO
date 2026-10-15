"""Design tokens shared by the Tk UI and the mockup renderer (no Tk import)."""

# Two palettes: deep navy chrome, light workspace (default) and a full dark
# theme. ``C`` is the live palette and is mutated in place on theme switches
# so every module holding a reference sees the new colours.
PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "sidebar": "#141b2d",
        "sidebar_hover": "#1d2941",
        "sidebar_active": "#243656",
        "sidebar_fg": "#9fb0c9",
        "sidebar_fg_active": "#ffffff",
        "accent": "#3b82f6",
        "accent_hover": "#2563eb",
        "bg": "#f4f6fa",
        "panel": "#ffffff",
        "panel_alt": "#f8fafc",
        "border": "#dde3ec",
        "text": "#1b2430",
        "muted": "#64748b",
        "success": "#16a34a",
        "warning": "#d97706",
        "danger": "#dc2626",
        "code_bg": "#0f172a",
        "code_fg": "#e2e8f0",
        "user_bubble": "#dbeafe",
        "tool_bubble": "#fef3c7",
        "assistant_bubble": "#ffffff",
        "statusbar": "#e8edf5",
        "hover": "#e7edf7",
        "danger_soft": "#fde8e8",
    },
    "dark": {
        "sidebar": "#0b1220",
        "sidebar_hover": "#131c2e",
        "sidebar_active": "#1c2a45",
        "sidebar_fg": "#8fa3c0",
        "sidebar_fg_active": "#ffffff",
        "accent": "#3b82f6",
        "accent_hover": "#2563eb",
        "bg": "#111827",
        "panel": "#1f2937",
        "panel_alt": "#172033",
        "border": "#334155",
        "text": "#e5e7eb",
        "muted": "#94a3b8",
        "success": "#22c55e",
        "warning": "#f59e0b",
        "danger": "#ef4444",
        "code_bg": "#0b1220",
        "code_fg": "#e2e8f0",
        "user_bubble": "#1e3a5f",
        "tool_bubble": "#3f3a1e",
        "assistant_bubble": "#1f2937",
        "statusbar": "#0b1220",
        "hover": "#24324a",
        "danger_soft": "#4a1f27",
    },
}

C: dict[str, str] = dict(PALETTES["light"])


def set_palette(name: str) -> dict[str, str]:
    """Activate a palette in-place; returns the live ``C`` mapping."""
    if name not in PALETTES:
        name = "light"
    C.clear()
    C.update(PALETTES[name])
    return C


def current_theme() -> str:
    for name, palette in PALETTES.items():
        if palette.get("bg") == C.get("bg") and palette.get("panel") == C.get("panel"):
            return name
    return "light"


def color_map(old: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Hex-to-hex translation from one palette to another (for recolouring)."""
    mapping: dict[str, str] = {}
    for key, old_val in old.items():
        new_val = new.get(key)
        if isinstance(old_val, str) and isinstance(new_val, str) and old_val != new_val:
            mapping[old_val.lower()] = new_val
    return mapping


from pathlib import Path

# Font stacks “like the modern editors”: Inter/Segoe UI Variable first,
# JetBrains Mono/Cascadia for code.  ``detect_fonts`` picks the first
# family actually installed; tuples are rebuilt by ``set_fonts``.
UI_FONT_CANDIDATES = ("Inter", "Segoe UI Variable Text", "Segoe UI",
                      "SF Pro Text", "Ubuntu", "Noto Sans", "DejaVu Sans")
MONO_FONT_CANDIDATES = ("JetBrains Mono", "Cascadia Code", "Consolas",
                        "SF Mono", "Menlo", "DejaVu Sans Mono")
DEFAULT_UI_FONT = "Segoe UI"
DEFAULT_MONO_FONT = "Consolas"


def bundled_fonts_dir() -> Path:
    return Path(__file__).parent / "assets" / "fonts"


def register_bundled_fonts(fonts_dir=None) -> list[Path]:
    """Make the bundled Inter/JetBrains Mono usable by Tk, per platform.

    Windows: AddFontResourceEx (private, per-process).  macOS/Linux:
    copy into the per-user fonts folder (+ fc-cache on Linux).
    Never raises; returns font files that are in place.
    """
    import shutil
    import sys

    source_dir = Path(fonts_dir) if fonts_dir else bundled_fonts_dir()
    if not source_dir.is_dir():
        return []
    files = sorted(source_dir.glob("*.ttf"))
    done: list[Path] = []
    try:
        if sys.platform.startswith("win"):
            import ctypes

            for file in files:
                added = ctypes.windll.gdi32.AddFontResourceExW(
                    str(file), 0x10, None)  # FR_PRIVATE
                if added:
                    done.append(file)
        elif sys.platform == "darwin":
            target_dir = Path.home() / "Library" / "Fonts"
            target_dir.mkdir(parents=True, exist_ok=True)
            for file in files:
                target = target_dir / file.name
                if not target.exists():
                    shutil.copyfile(file, target)
                done.append(target)
        else:
            target_dir = (Path.home() / ".local" / "share" / "fonts"
                          / "alterego")
            target_dir.mkdir(parents=True, exist_ok=True)
            copied = False
            for file in files:
                target = target_dir / file.name
                if not target.exists():
                    shutil.copyfile(file, target)
                    copied = True
                done.append(target)
            if copied:
                import subprocess

                try:
                    subprocess.run(["fc-cache", "-f", str(target_dir)],
                                   capture_output=True, timeout=30)
                except (OSError, subprocess.SubprocessError):
                    pass
    except Exception:
        return done
    return done


def detect_fonts(families) -> tuple[str, str]:
    """First installed family from each candidate stack."""
    available = {str(f) for f in families or []}
    ui = next((f for f in UI_FONT_CANDIDATES if f in available),
              DEFAULT_UI_FONT)
    mono = next((f for f in MONO_FONT_CANDIDATES if f in available),
                DEFAULT_MONO_FONT)
    return ui, mono


F_BASE = (DEFAULT_UI_FONT, 10)
F_BOLD = (DEFAULT_UI_FONT, 10, "bold")
F_TITLE = (DEFAULT_UI_FONT, 16, "bold")
F_SUB = (DEFAULT_UI_FONT, 10)
F_SMALL = (DEFAULT_UI_FONT, 9)
F_MONO = (DEFAULT_MONO_FONT, 10)
F_NAV = (DEFAULT_UI_FONT, 10, "bold")
F_NAV_SMALL = (DEFAULT_UI_FONT, 9)


def set_fonts(ui_family: str, mono_family: str) -> dict[str, tuple]:
    """Rebuild all F_* tuples for the chosen families; returns them."""
    global F_BASE, F_BOLD, F_TITLE, F_SUB, F_SMALL, F_MONO, F_NAV, F_NAV_SMALL
    F_BASE = (ui_family, 10)
    F_BOLD = (ui_family, 10, "bold")
    F_TITLE = (ui_family, 16, "bold")
    F_SUB = (ui_family, 10)
    F_SMALL = (ui_family, 9)
    F_MONO = (mono_family, 10)
    F_NAV = (ui_family, 10, "bold")
    F_NAV_SMALL = (ui_family, 9)
    return {"F_BASE": F_BASE, "F_BOLD": F_BOLD, "F_TITLE": F_TITLE,
            "F_SUB": F_SUB, "F_SMALL": F_SMALL, "F_MONO": F_MONO,
            "F_NAV": F_NAV, "F_NAV_SMALL": F_NAV_SMALL}

# Syntax-highlighting palette for the dark code area (editor + mockups).
SYNTAX = {
    "keyword": "#7dd3fc",
    "builtin": "#c4b5fd",
    "string": "#86efac",
    "comment": "#6b7f99",
    "number": "#fdba74",
    "defname": "#fde68a",
    "key": "#93c5fd",
}
