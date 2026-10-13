"""Tests for the palettes and theme switching helpers (no Tk)."""
from __future__ import annotations

from alterego_training_hub.theme import (
    PALETTES,
    color_map,
    current_theme,
    set_palette,
)


def test_palettes_cover_the_same_roles():
    light, dark = PALETTES["light"], PALETTES["dark"]
    assert set(light) == set(dark)
    assert light["bg"] != dark["bg"]


def test_set_palette_switches_in_place_and_back():
    import alterego_training_hub.theme as theme

    original = dict(theme.C)
    try:
        set_palette("dark")
        assert theme.C["bg"] == PALETTES["dark"]["bg"]
        assert current_theme() == "dark"
        set_palette("light")
        assert theme.C == original
        assert current_theme() == "light"
        set_palette("no-such")  # falls back to light
        assert current_theme() == "light"
    finally:
        set_palette("light")


def test_color_map_maps_only_changed_values():
    mapping = color_map(PALETTES["light"], PALETTES["dark"])
    assert mapping["#f4f6fa".lower()] == PALETTES["dark"]["bg"]
    assert mapping["#3b82f6".lower()] == PALETTES["dark"]["accent"] \
        if "#3b82f6" != PALETTES["dark"]["accent"] else True
    # Unchanged colours produce no mapping entries (accent is shared).
    if PALETTES["light"]["accent"] == PALETTES["dark"]["accent"]:
        assert PALETTES["light"]["accent"].lower() not in mapping
