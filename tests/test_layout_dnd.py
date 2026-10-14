"""Tests for panel docking helpers and extended layout state."""
from __future__ import annotations

import pytest

from alterego_training_hub.layouts import (LayoutError, LayoutState, docked,
                                           edge_drop, load_layout, save_layout)


def test_edge_drop_zones():
    assert edge_drop(10, 1000) == "left"
    assert edge_drop(980, 1000) == "right"
    assert edge_drop(500, 1000) is None
    assert edge_drop(220, 1000) is None      # outside 22% margin
    assert edge_drop(-5, 1000) is None
    assert edge_drop(1200, 1000) is None
    assert edge_drop(10, 0) is None
    assert edge_drop(10, -1) is None
    assert edge_drop("x", 1000) is None


def test_layout_state_validates_sides_and_height():
    state = LayoutState()
    state.validate()
    with pytest.raises(LayoutError):
        LayoutState(sidebar_side="top").validate()
    with pytest.raises(LayoutError):
        LayoutState(chat_side="up").validate()
    with pytest.raises(LayoutError):
        LayoutState(bottom_height=10).validate()
    with pytest.raises(LayoutError):
        LayoutState(bottom_height="abc").validate()
    LayoutState(bottom_height=80).validate()
    LayoutState(bottom_height=800).validate()


def test_docked_returns_new_state():
    state = LayoutState()
    moved = docked(state, "chat", "left")
    assert moved.chat_side == "left"
    assert state.chat_side == "right"      # original untouched
    moved = docked(state, "sidebar", "right")
    assert moved.sidebar_side == "right"
    with pytest.raises(LayoutError):
        docked(state, "bottom", "left")
    with pytest.raises(LayoutError):
        docked(state, "chat", "middle")


def test_save_load_round_trip_with_dock_fields(tmp_path):
    state = LayoutState(page="model", sidebar_side="right", chat_side="left",
                        bottom_height=320)
    file = save_layout(tmp_path / "layouts" / "mine.json", state)
    loaded = load_layout(file)
    assert loaded == state


def test_load_old_layout_gains_defaults(tmp_path):
    file = tmp_path / "old.json"
    file.write_text('{"page": "editor", "bottom_visible": true, '
                    '"bottom_view": "git", "geometry": "800x600"}',
                    encoding="utf-8")
    loaded = load_layout(file)
    assert loaded.bottom_view == "git"
    assert loaded.sidebar_side == "left"   # defaults for new fields
    assert loaded.chat_side == "right"
    assert loaded.bottom_height == 210
