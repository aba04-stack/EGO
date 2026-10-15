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
    from alterego_training_hub import theme

    original = dict(theme.C)
    try:
        set_palette("dark")
        assert theme.C["bg"] == PALETTES["dark"]["bg"]
        assert current_theme() == "dark"
        set_palette("light")
        assert current_theme() == "light"
        set_palette("no-such")  # falls back to light
        assert current_theme() == "light"
    finally:
        set_palette("dark" if original.get("bg") == PALETTES["dark"]["bg"] else "light")


def test_color_map_maps_only_changed_values():
    mapping = color_map(PALETTES["light"], PALETTES["dark"])
    light_bg = PALETTES["light"]["bg"].lower()
    assert mapping[light_bg] == PALETTES["dark"]["bg"]
    if PALETTES["light"]["accent"] != PALETTES["dark"]["accent"]:
        assert mapping[PALETTES["light"]["accent"].lower()] == PALETTES["dark"]["accent"]
    else:
        assert PALETTES["light"]["accent"].lower() not in mapping
