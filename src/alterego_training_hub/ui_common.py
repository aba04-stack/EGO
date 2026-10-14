"""Shared design system for the desktop UI: widgets and helpers.

Color/font tokens live in :mod:`alterego_training_hub.theme` so that design
tools (e.g. the mockup renderer) can reuse them without importing Tk.
"""
from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from .i18n import t
from .theme import (  # noqa: F401  (re-exported for page modules)
    F_BASE,
    F_BOLD,
    F_MONO,
    F_NAV,
    F_NAV_SMALL,
    F_SMALL,
    F_SUB,
    F_TITLE,
    C,
)


def apply_theme(root: tk.Tk) -> ttk.Style:
    root.configure(bg=C["bg"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", font=F_BASE, background=C["bg"], foreground=C["text"])
    style.configure("TFrame", background=C["bg"])
    style.configure("Panel.TFrame", background=C["panel"])
    style.configure("TLabel", background=C["bg"], foreground=C["text"])
    style.configure("Panel.TLabel", background=C["panel"], foreground=C["text"])
    style.configure("Title.TLabel", background=C["bg"], foreground=C["text"], font=F_TITLE)
    style.configure("Sub.TLabel", background=C["bg"], foreground=C["muted"], font=F_SUB)
    style.configure("Muted.TLabel", background=C["bg"], foreground=C["muted"], font=F_SMALL)
    style.configure("Muted.Panel.TLabel", background=C["panel"], foreground=C["muted"], font=F_SMALL)
    style.configure("Bold.TLabel", background=C["bg"], foreground=C["text"], font=F_BOLD)
    style.configure("Status.TLabel", background=C["statusbar"], foreground=C["muted"], font=F_SMALL,
                     padding=(10, 4))

    style.configure("TButton", font=F_BASE, padding=(12, 6), background=C["panel"])
    style.map("TButton",
              background=[("active", C["hover"])],
              foreground=[("disabled", "#9aa7b8")])
    style.configure("Accent.TButton", background=C["accent"], foreground="#ffffff", font=F_BOLD,
                     padding=(14, 7))
    style.map("Accent.TButton",
              background=[("active", C["accent_hover"]), ("disabled", "#9db8e8")],
              foreground=[("disabled", "#eef4ff")])
    style.configure("Danger.TButton", background=C["panel"], foreground=C["danger"],
                     padding=(12, 6))
    style.map("Danger.TButton", background=[("active", C["danger_soft"])])

    style.configure("TEntry", padding=5)
    style.configure("TCombobox", padding=4)

    style.configure("Treeview", rowheight=28, background=C["panel"], fieldbackground=C["panel"],
                     borderwidth=0, font=F_BASE)
    style.map("Treeview",
              background=[("selected", C["accent"])],
              foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", font=F_BOLD, background=C["panel_alt"],
                     foreground=C["text"], relief="flat")
    style.map("Treeview.Heading", background=[("active", C["border"])])

    style.configure("Vertical.TScrollbar", background=C["border"], troughcolor=C["bg"],
                     borderwidth=0)
    return style


_RECOLOR_OPTIONS = (
    "bg", "fg", "activebackground", "activeforeground", "selectbackground",
    "selectforeground", "insertbackground", "disabledforeground",
    "highlightbackground", "highlightcolor", "readonlybackground",
    "troughcolor",
)
_TAG_OPTIONS = ("background", "foreground", "selectbackground",
                "selectforeground")


def recolor_widgets(root, old: dict[str, str], new: dict[str, str]) -> None:
    """Rewrite already-built widgets from one palette to another (theme switch).

    Walks every descendant of ``root`` and swaps any colour value that came
    from the old palette, including text-widget tags. Widgets that reject an
    option (ttk ones) are skipped silently.
    """
    from .theme import color_map

    mapping = color_map(old, new)
    if not mapping:
        return

    def swap(value):
        if isinstance(value, str):
            return mapping.get(value.lower(), value)
        return value

    try:
        widgets = list(root.winfo_all() or ())
    except Exception:
        return
    for widget in widgets:
        for option in _RECOLOR_OPTIONS:
            try:
                current = widget.cget(option)
            except Exception:
                continue
            replacement = swap(current)
            if replacement != current:
                try:
                    widget.configure(**{option: replacement})
                except Exception:
                    pass
        try:
            tag_names = widget.tag_names()
        except Exception:
            tag_names = ()
        for tag in tag_names:
            for option in _TAG_OPTIONS:
                try:
                    current = widget.tag_cget(tag, option)
                except Exception:
                    continue
                replacement = swap(current)
                if replacement != current:
                    try:
                        widget.tag_configure(tag, **{option: replacement})
                    except Exception:
                        pass


def page_header(parent, title: str, subtitle: str = "", actions=None) -> tk.Frame:
    """Consistent page header: title + subtitle, primary actions top-right.

    ``actions`` is an optional list of ``(label, command)`` or
    ``(label, command, style)`` tuples rendered as buttons on the right —
    the Cursor/Linear pattern: the one main action always lives here.
    """
    frame = tk.Frame(parent, bg=C["bg"])
    left = tk.Frame(frame, bg=C["bg"])
    left.pack(side="left", fill="x", expand=True)
    tk.Label(left, text=title, bg=C["bg"], fg=C["text"], font=F_TITLE).pack(anchor="w")
    if subtitle:
        tk.Label(left, text=subtitle, bg=C["bg"], fg=C["muted"], font=F_SUB,
                 wraplength=900, justify="left").pack(anchor="w", pady=(4, 0))
    for item in reversed(list(actions or [])):
        label, command = item[0], item[1]
        style = item[2] if len(item) > 2 else "Accent.TButton"
        ttk.Button(frame, text=label, style=style,
                   command=command).pack(side="right", padx=(8, 0), pady=(6, 0))
    return frame


def attach_tooltip(widget, text: str) -> None:
    """Minimal hover tooltip (guarded: never breaks headless/fake widgets)."""
    if not text:
        return

    def show(_event=None):
        try:
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tk.Label(tip, text=text, bg="#1f2733", fg="#ffffff",
                     font=F_SMALL, padx=8, pady=4).pack()
            widget._tooltip_tip = tip
        except Exception:
            pass

    def hide(_event=None):
        tip = getattr(widget, "_tooltip_tip", None)
        if tip is not None:
            try:
                tip.destroy()
            except Exception:
                pass
            widget._tooltip_tip = None

    try:
        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")
    except Exception:
        pass


def card(parent, title: str | None = None) -> tk.Frame:
    """White card container with optional caption."""
    outer = tk.Frame(parent, bg=C["border"], bd=0)
    inner = tk.Frame(outer, bg=C["panel"], padx=14, pady=12)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    if title:
        tk.Label(inner, text=title, bg=C["panel"], fg=C["text"], font=F_BOLD).pack(anchor="w")
    return inner


class Collapsible(tk.Frame):
    """A settings section with a clickable header that hides/shows its body.

    The header shows a chevron (▼ expanded / ▶ collapsed) and the title; the
    body is the white card area where the settings rows are placed.
    """

    def __init__(self, parent, title: str, *, open: bool = True,
                 on_change: Callable[[bool], None] | None = None):
        super().__init__(parent, bg=C["border"], highlightthickness=0)
        self._open = bool(open)
        self._on_change = on_change

        self.header = tk.Frame(self, bg=C["panel"], cursor="hand2")
        self.header.pack(fill="x", padx=1, pady=(1, 0))
        self.arrow = tk.Label(self.header, text="▼" if self._open else "▶",
                              bg=C["panel"], fg=C["muted"], font=F_SMALL,
                              padx=12, pady=7, cursor="hand2")
        self.arrow.pack(side="left")
        self.title_label = tk.Label(self.header, text=title, bg=C["panel"],
                                    fg=C["text"], font=F_BOLD, cursor="hand2",
                                    padx=0, pady=7)
        self.title_label.pack(side="left")
        self.hint_label = tk.Label(self.header, text="", bg=C["panel"],
                                   fg=C["muted"], font=F_SMALL, padx=12, pady=7)
        self.hint_label.pack(side="right")

        self.body = tk.Frame(self, bg=C["panel"], padx=14, pady=10)
        for widget in (self.header, self.arrow, self.title_label):
            widget.bind("<Button-1>", lambda _event: self.toggle())
        if self._open:
            self.body.pack(fill="both", expand=True, padx=1, pady=1)

    def set_hint(self, text: str):
        self.hint_label.configure(text=text)

    @property
    def is_open(self) -> bool:
        return self._open

    def set_open(self, open_: bool) -> None:
        open_ = bool(open_)
        if open_ == self._open:
            return
        self._open = open_
        self.arrow.configure(text="▼" if open_ else "▶")
        if open_:
            self.body.pack(fill="both", expand=True, padx=1, pady=1)
        else:
            self.body.pack_forget()
        if self._on_change:
            self._on_change(open_)

    def toggle(self) -> None:
        self.set_open(not self._open)


def set_text(widget: tk.Text, value: str, *, autoscroll: bool = False) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value)
    widget.configure(state="disabled")
    if autoscroll:
        widget.see("end")


def append_text(widget: tk.Text, value: str) -> None:
    widget.configure(state="normal")
    widget.insert("end", value)
    widget.configure(state="disabled")
    widget.see("end")


def flat_button(parent, text: str, command: Callable[[], None], *,
                bg: str | None = None, fg: str | None = None,
                active_bg: str | None = None, font=F_NAV, padx: int = 16,
                pady: int = 10, anchor: str = "w") -> tk.Label:
    """A flat, hoverable label styled as a button (used in the sidebar and bars)."""
    base_bg = bg or C["panel"]
    hover_bg = active_bg or "#e7edf7"
    label = tk.Label(parent, text=text, bg=base_bg, fg=fg or C["text"], font=font,
                     padx=padx, pady=pady, anchor=anchor, cursor="hand2")

    def on_enter(_event):
        label.configure(bg=hover_bg)

    def on_leave(_event):
        label.configure(bg=base_bg)

    label.bind("<Enter>", on_enter)
    label.bind("<Leave>", on_leave)
    label.bind("<Button-1>", lambda _event: command())
    return label


def confirm_from_worker(app: Any, title: str, message: str, timeout: float = 600.0) -> bool:
    """Ask the user a yes/no question from a worker thread, blocking for the answer."""
    done = threading.Event()
    box: dict[str, Any] = {"ok": False}
    app.post_event("confirm", {"title": title, "message": message, "event": done, "box": box})
    done.wait(timeout)
    return bool(box.get("ok"))


CHART_COLORS = ["#3b82f6", "#16a34a", "#d97706", "#dc2626", "#8b5cf6"]


def draw_line_chart(canvas: tk.Canvas, series: dict[str, list[float]],
                    *, width: int = 520, height: int = 200) -> None:
    """Draw a multi-line metrics chart on a tk.Canvas (history + live update)."""
    from .chart import SeriesView, chart_points, format_tick, nice_ticks, value_range

    canvas.delete("all")
    valid = {key: values for key, values in series.items() if len(values) >= 1}
    if not valid:
        canvas.create_text(width / 2, height / 2, text=t('Нет данных для графика'),
                           fill=C["muted"], font=F_SMALL)
        return
    vmin, vmax = value_range(
        [SeriesView(name=key, values=list(values)) for key, values in valid.items()])
    pad_x, pad_y = 46, 26

    # Grid + ticks from the shared scale.
    for tick in nice_ticks(vmin, vmax, 5):
        points = chart_points([tick, tick], width, height, vmin=vmin, vmax=vmax,
                              pad=pad_y)
        if not points:
            continue
        y = points[0][1]
        if 10 <= y <= height - pad_y:
            canvas.create_line(pad_x, y, width - 10, y, fill=C["border"],
                               dash=(2, 4))
            canvas.create_text(pad_x - 6, y, text=format_tick(tick), anchor="e",
                               fill=C["muted"], font=F_SMALL)

    canvas.create_line(pad_x, height - pad_y, width - 10, height - pad_y,
                       fill=C["border"])
    canvas.create_line(pad_x, 10, pad_x, height - pad_y, fill=C["border"])

    def xy(index: int, count: int, value: float):
        points = chart_points([value], width, height, vmin=vmin, vmax=vmax,
                              pad=pad_y)
        if count <= 1:
            return pad_x + (width - 2 * pad_x) / 2, points[0][1] if points else height / 2
        x = pad_x + (width - 2 * pad_x) * index / max(1, count - 1)
        return x, points[0][1] if points else height / 2

    for idx, (key, values) in enumerate(valid.items()):
        color = CHART_COLORS[idx % len(CHART_COLORS)]
        coords: list[float] = []
        for i, value in enumerate(values):
            x, y = xy(i, len(values), value)
            coords.extend((x, y))
        if len(coords) >= 4:
            canvas.create_line(*coords, fill=color, width=2, smooth=True)
        last_x, last_y = xy(len(values) - 1, len(values), values[-1])
        canvas.create_oval(last_x - 3, last_y - 3, last_x + 3, last_y + 3,
                           fill=color, outline=color)
        canvas.create_text(width - 12, 14 + idx * 16, text=f"{key}: {values[-1]:.4g}",
                           anchor="e", fill=color, font=F_SMALL)
