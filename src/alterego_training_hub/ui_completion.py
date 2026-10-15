"""Editor autocomplete: word completion popup driven by the buffer vocabulary."""
from __future__ import annotations

import tkinter as tk

from .completion import _count_chars, collect_candidates, current_word
from .ui_common import F_MONO, C


class CompletionPopup:
    """Small listbox under the editor cursor; Tab/Enter accepts, Esc closes."""

    def __init__(self, editor_page):
        self.page = editor_page
        self.visible = False
        self._window: tk.Toplevel | None = None
        self._listbox: tk.Listbox | None = None
        self._replace_start = 0
        self._replace_end = 0

    def hide(self):
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
        self._window = None
        self._listbox = None
        self.visible = False

    def update(self):
        """Recompute suggestions for the caret; show or hide the popup."""
        editor = self.page.editor
        try:
            cursor_index = editor.index("insert")
            text = editor.get("1.0", "end-1c")
            line_start = int(str(cursor_index).split(".", 1)[0])
        except Exception:
            self.hide()
            return
        cursor_offset = _count_chars(editor, cursor_index)
        prefix, word_start = current_word(text, cursor_offset)
        candidates = collect_candidates(text, prefix)
        if not candidates:
            self.hide()
            return
        self._replace_start = word_start
        self._replace_end = cursor_offset
        self._show(candidates, line_start)

    def _show(self, candidates: list[str], line: int):
        if self._window is None:
            try:
                self._window = tk.Toplevel(self.page)
                self._window.wm_overrideredirect(True)
                self._listbox = tk.Listbox(
                    self._window, bd=1, relief="solid", font=F_MONO,
                    activestyle="none", bg=C["panel"], fg=C["text"],
                    selectbackground=C["accent"], selectforeground="#ffffff",
                    exportselection=False)
                self._listbox.pack(fill="both", expand=True)
                self._listbox.bind("<ButtonRelease-1>", lambda _e: self.accept())
            except Exception:
                self.hide()
                return
        assert self._listbox is not None
        try:
            self._listbox.delete(0, "end")
            for candidate in candidates:
                self._listbox.insert("end", candidate)
            self._listbox.selection_set(0)
            # Position near the cursor line inside the editor.
            editor = self.page.editor
            bbox = editor.bbox(f"{line}.0")
            x = self.page.winfo_rootx() + 220
            y = self.page.winfo_rooty() + 160
            if bbox:
                x += int(bbox[0])
                y += int(bbox[1]) + int(bbox[3]) + 2
            self._window.geometry(f"+{x}+{y}")
            self._window.lift()
        except Exception:
            self.hide()
            return
        self.visible = True

    def _selected(self) -> str | None:
        if self._listbox is None:
            return None
        try:
            selection = self._listbox.curselection()
            if not selection:
                return None
            return str(self._listbox.get(selection[0]))
        except Exception:
            return None

    def move(self, step: int):
        if self._listbox is None:
            return
        try:
            size = self._listbox.size()
            current = (self._listbox.curselection() or (0,))[0]
            target = (current + step) % max(1, size)
            self._listbox.selection_clear(0, "end")
            self._listbox.selection_set(target)
            self._listbox.activate(target)
        except Exception:
            pass

    def accept(self) -> bool:
        word = self._selected()
        if word is None:
            return False
        editor = self.page.editor
        try:
            editor.delete(f"1.0+{self._replace_start}c", f"1.0+{self._replace_end}c")
            editor.insert(f"1.0+{self._replace_start}c", word)
        except Exception:
            return False
        self.hide()
        return True
