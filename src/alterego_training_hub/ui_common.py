"""Shared design system for the desktop UI: colors, fonts, widgets, helpers."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Palette: deep navy chrome, light workspace, blue accent — calm and professional.
# ---------------------------------------------------------------------------
C = {
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
}

F_BASE = ("Segoe UI", 10)
F_BOLD = ("Segoe UI", 10, "bold")
F_TITLE = ("Segoe UI", 15, "bold")
F_SUB = ("Segoe UI", 10)
F_SMALL = ("Segoe UI", 9)
F_MONO = ("Consolas", 9)
F_NAV = ("Segoe UI", 10, "bold")
F_NAV_SMALL = ("Segoe UI", 9)


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
    style.configure("Status.TLabel", background="#e8edf5", foreground=C["muted"], font=F_SMALL,
                     padding=(10, 4))

    style.configure("TButton", font=F_BASE, padding=(12, 6), background=C["panel"])
    style.map("TButton",
              background=[("active", "#e7edf7")],
              foreground=[("disabled", "#9aa7b8")])
    style.configure("Accent.TButton", background=C["accent"], foreground="#ffffff", font=F_BOLD,
                     padding=(14, 7))
    style.map("Accent.TButton",
              background=[("active", C["accent_hover"]), ("disabled", "#9db8e8")],
              foreground=[("disabled", "#eef4ff")])
    style.configure("Danger.TButton", background=C["panel"], foreground=C["danger"],
                     padding=(12, 6))
    style.map("Danger.TButton", background=[("active", "#fde8e8")])

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


def page_header(parent, title: str, subtitle: str = "") -> tk.Frame:
    """Consistent page header: big title + muted subtitle on the light canvas."""
    frame = tk.Frame(parent, bg=C["bg"])
    tk.Label(frame, text=title, bg=C["bg"], fg=C["text"], font=F_TITLE).pack(anchor="w")
    if subtitle:
        tk.Label(frame, text=subtitle, bg=C["bg"], fg=C["muted"], font=F_SUB,
                 wraplength=900, justify="left").pack(anchor="w", pady=(4, 0))
    return frame


def card(parent, title: str | None = None) -> tk.Frame:
    """White card container with optional caption."""
    outer = tk.Frame(parent, bg=C["border"], bd=0)
    inner = tk.Frame(outer, bg=C["panel"], padx=14, pady=12)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    if title:
        tk.Label(inner, text=title, bg=C["panel"], fg=C["text"], font=F_BOLD).pack(anchor="w")
    return inner


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
    """Draw a small multi-line chart on a tk.Canvas (metrics history)."""
    canvas.delete("all")
    valid = {key: values for key, values in series.items() if len(values) >= 2}
    if not valid:
        canvas.create_text(width / 2, height / 2, text="Нет данных для графика",
                           fill=C["muted"], font=F_SMALL)
        return
    all_values = [value for values in valid.values() for value in values]
    vmin, vmax = min(all_values), max(all_values)
    if vmax - vmin < 1e-12:
        vmax = vmin + 1.0
    pad_x, pad_y = 46, 26

    def xy(index: int, count: int, value: float):
        x = pad_x + (width - 2 * pad_x) * index / max(1, count - 1)
        y = height - pad_y - (height - 2 * pad_y) * (value - vmin) / (vmax - vmin)
        return x, y

    canvas.create_line(pad_x, height - pad_y, width - 10, height - pad_y,
                       fill=C["border"])
    canvas.create_line(pad_x, 10, pad_x, height - pad_y, fill=C["border"])
    canvas.create_text(pad_x - 6, 14, text=f"{vmax:.3g}", anchor="e",
                       fill=C["muted"], font=F_SMALL)
    canvas.create_text(pad_x - 6, height - pad_y, text=f"{vmin:.3g}", anchor="e",
                       fill=C["muted"], font=F_SMALL)

    for idx, (key, values) in enumerate(valid.items()):
        color = CHART_COLORS[idx % len(CHART_COLORS)]
        coords: list[float] = []
        for i, value in enumerate(values):
            x, y = xy(i, len(values), value)
            coords.extend((x, y))
        canvas.create_line(*coords, fill=color, width=2, smooth=True)
        last_x, last_y = xy(len(values) - 1, len(values), values[-1])
        canvas.create_oval(last_x - 3, last_y - 3, last_x + 3, last_y + 3,
                           fill=color, outline=color)
        canvas.create_text(width - 12, 14 + idx * 16, text=f"{key}: {values[-1]:.4g}",
                           anchor="e", fill=color, font=F_SMALL)
