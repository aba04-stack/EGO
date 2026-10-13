"""Tests for chart math (scales, ticks) — no tkinter required."""
from __future__ import annotations

from alterego_training_hub.chart import (
    SeriesView,
    chart_points,
    format_tick,
    nice_ticks,
    value_range,
)


def test_chart_points_maps_range_to_canvas():
    points = chart_points([0.0, 1.0], width=200, height=100, vmin=0.0, vmax=1.0,
                          pad=10)
    assert points == [(10.0, 90.0), (190.0, 10.0)]  # y grows downward


def test_chart_points_handles_degenerate_data():
    assert chart_points([], 200, 100) == []
    # nan/inf are filtered out; the one surviving value sits mid-chart.
    filtered = chart_points([float("nan"), 1.0, float("inf")], 200, 100, pad=10)
    assert len(filtered) == 1 and filtered[0][1] == 50.0
    single = chart_points([5.0], 200, 100, pad=10)
    assert len(single) == 1 and 10 <= single[0][1] <= 90
    assert chart_points([1.0, 2.0], width=5, height=5) == []  # too small


def test_value_range_shared_and_constant():
    low, high = value_range([SeriesView("a", [1.0, 3.0]), SeriesView("b", [2.0, 5.0])])
    assert low <= 1.0 and high >= 5.0
    low, high = value_range([SeriesView("a", [2.0, 2.0])])
    assert low < 2.0 < high
    assert value_range([]) == (0.0, 1.0)


def test_nice_ticks_are_readable():
    ticks = nice_ticks(0.0, 1.0, 5)
    assert ticks[0] >= 0.0 and ticks[-1] <= 1.0 + 1e-9
    assert len(ticks) >= 3
    ticks = nice_ticks(0.02, 0.031, 4)
    assert all(0.02 - 1e-9 <= value <= 0.031 + 1e-9 for value in ticks)
    assert nice_ticks(1.0, 1.0) == [1.0, 1.0]


def test_format_tick():
    assert format_tick(100) == "100"
    assert format_tick(2.0) == "2"
    assert format_tick(0.125) == "0.125"
