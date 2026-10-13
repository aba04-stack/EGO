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


F_BASE = ("Segoe UI", 10)
F_BOLD = ("Segoe UI", 10, "bold")
F_TITLE = ("Segoe UI", 15, "bold")
F_SUB = ("Segoe UI", 10)
F_SMALL = ("Segoe UI", 9)
F_MONO = ("Consolas", 9)
F_NAV = ("Segoe UI", 10, "bold")
F_NAV_SMALL = ("Segoe UI", 9)

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
