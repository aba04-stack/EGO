"""Dataset library page: catalogue, scan and preview training data."""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .datasets import DatasetEntry, DatasetError, DatasetLibrary, preview_rows
from .ui_common import C, F_MONO, F_SMALL, card, page_header, set_text


class DatasetsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._entries: dict[str, DatasetEntry] = {}
        self._build()

    def _build(self):
        header = page_header(
            self,
            "Датасеты",
            "Библиотека данных: JSONL/CSV/TXT с подсчётом строк и предпросмотром. "
            "Хранится в общей папке библиотеки — можно синхронизировать облаком.",
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        toolbar_card = card(self)
        toolbar_card.pack(fill="x", padx=24, pady=(0, 12))
        bar = tk.Frame(toolbar_card, bg=C["panel"])
        bar.pack(fill="x")
        ttk.Button(bar, text="Обновить", command=self.refresh).pack(side="left")
        ttk.Button(bar, text="Сканировать папку…", style="Accent.TButton",
                   command=self.scan_folder).pack(side="left", padx=8)
        ttk.Button(bar, text="Добавить вручную",
                   command=self.add_manual).pack(side="left", padx=8)
        ttk.Button(bar, text="Предпросмотр", command=self.show_preview).pack(
            side="left", padx=8)
        ttk.Button(bar, text="Удалить", style="Danger.TButton",
                   command=self.remove_selected).pack(side="left", padx=8)
        self.library_var = tk.StringVar()
        tk.Label(bar, textvariable=self.library_var, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="right")

        table_card = card(self)
        table_card.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        columns = ("name", "format", "rows", "size", "location", "updated")
        self.tree = ttk.Treeview(table_card, columns=columns, show="headings",
                                 height=10)
        for col, title, width in [
            ("name", "Название", 180), ("format", "Формат", 80),
            ("rows", "Строк", 80), ("size", "Размер", 100),
            ("location", "Путь / URI", 320), ("updated", "Обновлено", 120),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_preview())

        preview_card = card(self, "Предпросмотр")
        preview_card.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        self.preview_text = tk.Text(preview_card, height=8, wrap="word",
                                    state="disabled", bd=1, relief="solid",
                                    font=F_MONO)
        self.preview_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------- helpers
    def _library(self) -> DatasetLibrary:
        return DatasetLibrary(self.app.model_registry().library_dir)

    def on_show(self):
        self.refresh()

    def refresh(self):
        try:
            entries = self._library().load()
        except Exception as exc:
            messagebox.showerror("Датасеты", str(exc), parent=self)
            return
        self.tree.delete(*self.tree.get_children())
        self._entries.clear()
        for entry in entries:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.updated_at))
            size = f"{entry.size_bytes / 1024:.1f} KB" if entry.size_bytes else "—"
            iid = self.tree.insert("", "end", values=(
                entry.name, entry.format, entry.rows, size, entry.location, stamp,
            ))
            self._entries[iid] = entry
        library_dir = self.app.model_registry().library_dir
        self.library_var.set(f"Библиотека: {library_dir}")

    def _selected(self) -> DatasetEntry | None:
        selection = self.tree.selection()
        return self._entries.get(selection[0]) if selection else None

    def scan_folder(self):
        folder = filedialog.askdirectory(title="Папка с датасетами")
        if not folder:
            return

        def work():
            library = self._library()
            found = library.scan_folder(folder)
            existing = {entry.location for entry in library.load()}
            added = 0
            for entry in found:
                if entry.location not in existing:
                    library.add(entry)
                    added += 1
            return added

        self.app.start_async("Сканирование датасетов", work,
                             lambda added: self._after_scan(added, folder))

    def _after_scan(self, added: int, folder: str):
        self.refresh()
        self.app.activity.log("system", f"Сканированы датасеты: добавлено {added}")
        messagebox.showinfo("Датасеты",
                            f"Добавлено датасетов: {added}\nПапка: {folder}",
                            parent=self)

    def add_manual(self):
        entry = DatasetEntry(name=f"dataset-{len(self._entries) + 1}",
                             format="jsonl", location="data/train.jsonl")
        try:
            self._library().add(entry)
        except DatasetError as exc:
            messagebox.showerror("Датасеты", str(exc), parent=self)
            return
        self.refresh()

    def remove_selected(self):
        entry = self._selected()
        if entry is None:
            return
        if not messagebox.askyesno("Удалить",
                                   f"Удалить «{entry.name}» из библиотеки?",
                                   parent=self):
            return
        try:
            self._library().remove(entry.id)
        except DatasetError as exc:
            messagebox.showerror("Датасеты", str(exc), parent=self)
            return
        self.refresh()

    def show_preview(self):
        entry = self._selected()
        if entry is None:
            set_text(self.preview_text, "Выберите датасет в таблице.")
            return
        root = self.app.workspace_root()
        if root is None or not entry.location:
            set_text(self.preview_text,
                     "Предпросмотр доступен для локальных файлов в рабочей папке.")
            return
        path = Path(entry.location)
        if not path.is_absolute():
            path = root / entry.location
        if not path.is_file():
            set_text(self.preview_text, f"Файл не найден: {entry.location}")
            return
        rows = preview_rows(path, entry.format)
        import json as _json
        set_text(self.preview_text,
                 "\n".join(_json.dumps(row, ensure_ascii=False)[:240] for row in rows)
                 or "Файл пуст.")
