"""Dataset library page: catalogue, scan and preview training data."""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .datasets import DatasetEntry, DatasetError, DatasetLibrary, preview_rows
from .i18n import t
from .ui_common import F_BASE, F_MONO, F_SMALL, C, card, page_header, set_text


class DatasetsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._entries: dict[str, DatasetEntry] = {}
        self._build()

    def _build(self):
        header = page_header(
            self,
            t('Датасеты'),
            t('Библиотека данных: JSONL/CSV/TXT с подсчётом строк и предпросмотром. Хранится в общей папке библиотеки — можно синхронизировать облаком.'),
            actions=[(t('Сканировать папку…'), self.scan_folder, "Accent.TButton")],
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        toolbar_card = card(self)
        toolbar_card.pack(fill="x", padx=24, pady=(0, 12))
        bar = tk.Frame(toolbar_card, bg=C["panel"])
        bar.pack(fill="x")
        ttk.Button(bar, text=t('Обновить'), command=self.refresh).pack(side="left")
        ttk.Button(bar, text=t('Сканировать папку…'), style="Accent.TButton",
                   command=self.scan_folder).pack(side="left", padx=8)
        ttk.Button(bar, text=t('Добавить вручную'),
                   command=self.add_manual).pack(side="left", padx=8)
        ttk.Button(bar, text=t('Предпросмотр'), command=self.show_preview).pack(
            side="left", padx=8)
        ttk.Button(bar, text=t('Удалить'), style="Danger.TButton",
                   command=self.remove_selected).pack(side="left", padx=8)
        self.library_var = tk.StringVar()
        tk.Label(bar, textvariable=self.library_var, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="right")

        # Hugging Face download + filter/split tools
        tools_row = tk.Frame(toolbar_card, bg=C["panel"])
        tools_row.pack(fill="x", pady=(6, 0))
        tk.Label(tools_row, text="Hugging Face", bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        self.hf_var = tk.StringVar()
        tk.Entry(tools_row, textvariable=self.hf_var, width=32, bd=1,
                 relief="solid", font=F_MONO).pack(side="left", padx=(0, 6))
        tk.Label(tools_row, text=t('(организация/имя)'), bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(side="left", padx=(0, 12))
        ttk.Button(tools_row, text=t('Скачать с HF'),
                   command=self.download_hf).pack(side="left", padx=(0, 12))
        tk.Label(tools_row, text=t('Фильтр (содержит)'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        self.filter_var = tk.StringVar()
        tk.Entry(tools_row, textvariable=self.filter_var, width=18, bd=1,
                 relief="solid", font=F_BASE).pack(side="left", padx=(0, 6))
        ttk.Button(tools_row, text=t('Фильтр и разбиение train/val/test'),
                   command=self.filter_split).pack(side="left")
        sft_row = tk.Frame(toolbar_card, bg=C["panel"])
        sft_row.pack(fill="x", pady=(6, 0))
        tk.Label(sft_row, text="SFT", bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        ttk.Button(sft_row, text=t('Валидация формата'),
                   command=self.sft_validate).pack(side="left", padx=(0, 6))
        ttk.Button(sft_row, text=t('Near-dup дедупликация'),
                   command=self.dedupe_near).pack(side="left", padx=(0, 6))
        ttk.Button(sft_row, text=t('Деконтаминация от eval…'),
                   command=self.decontaminate).pack(side="left")

        table_card = card(self)
        table_card.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        columns = ("name", "format", "rows", "size", "location", "updated")
        self.tree = ttk.Treeview(table_card, columns=columns, show="headings",
                                 height=10)
        for col, title, width in [
            ("name", t('Название'), 180), ("format", t('Формат'), 80),
            ("rows", t('Строк'), 80), ("size", t('Размер'), 100),
            ("location", t('Путь / URI'), 320), ("updated", t('Обновлено'), 120),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_preview())

        preview_card = card(self, t('Предпросмотр'))
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
            messagebox.showerror(t('Датасеты'), str(exc), parent=self)
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
        self.library_var.set(t('Библиотека: {library_dir}').format(library_dir=library_dir))

    def _selected(self) -> DatasetEntry | None:
        selection = self.tree.selection()
        return self._entries.get(selection[0]) if selection else None

    def download_hf(self):
        from .datasets import fetch_hf_rows, write_rows

        repo_id = self.hf_var.get().strip()
        if not repo_id:
            messagebox.showinfo("Hugging Face",
                                t('Укажите идентификатор датасета, например squad или imdb.'), parent=self)
            return
        if not messagebox.askyesno(
            "Hugging Face",
            t('Скачать до 100 строк датасета «{repo_id}» (split=train)?\nЗапрос пойдёт к datasets-server.huggingface.co.').format(repo_id=repo_id), parent=self):
            return
        library_dir = self.app.model_registry().library_dir

        def work():
            rows = fetch_hf_rows(repo_id, limit=100)
            target = library_dir / "hf" / (repo_id.replace("/", "__") + ".jsonl")
            write_rows(target, rows, "jsonl")
            entry = DatasetEntry(
                name=repo_id.replace("/", "__"), format="jsonl",
                location=str(target), rows=len(rows),
                size_bytes=target.stat().st_size, notes=f"hf:{repo_id}")
            self._library().add(entry)
            return len(rows)

        def done(count):
            self.refresh()
            self.app.activity.log("system", t('Скачан датасет с HF: {repo_id} ({count} строк)').format(repo_id=repo_id, count=count))
            messagebox.showinfo("Hugging Face", t('Готово: строк — {count}').format(count=count), parent=self)

        def failed(error):
            messagebox.showerror("Hugging Face", str(error), parent=self)

        self.app.start_async(t('Скачать с Hugging Face'), work, done, failed)

    def filter_split(self):
        from .datasets import filter_rows, read_rows, split_rows, write_rows

        entry = self._selected()
        if entry is None:
            messagebox.showinfo(t('Датасеты'), t('Выберите датасет в таблице.'),
                                parent=self)
            return
        source = Path(entry.location)
        if not source.is_file():
            messagebox.showerror(t('Датасеты'), t('Файл не найден: {v1}').format(v1=entry.location),
                                 parent=self)
            return
        fmt = entry.format
        try:
            rows = read_rows(source, fmt)
            rows = filter_rows(rows, contains=self.filter_var.get().strip())
            parts = split_rows(rows, seed=42)
        except Exception as exc:
            messagebox.showerror(t('Датасеты'), str(exc), parent=self)
            return
        written = []
        for part, part_rows in parts.items():
            target = source.with_name(f"{source.stem}.{part}.{fmt}")
            write_rows(target, part_rows, fmt)
            self._library().add(DatasetEntry(
                name=f"{entry.name}-{part}", format=fmt, location=str(target),
                rows=len(part_rows), size_bytes=target.stat().st_size))
            written.append(f"{part}: {len(part_rows)}")
        self.refresh()
        self.app.activity.log("system", t('Разбиение датасета: ') + ", ".join(written))
        messagebox.showinfo(t('Датасеты'),
                            t('Готово — ') + ", ".join(written), parent=self)

    def scan_folder(self):
        folder = filedialog.askdirectory(title=t('Папка с датасетами'))
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

        self.app.start_async(t('Сканирование датасетов'), work,
                             lambda added: self._after_scan(added, folder))

    def _after_scan(self, added: int, folder: str):
        self.refresh()
        self.app.activity.log("system", t('Сканированы датасеты: добавлено {added}').format(added=added))
        messagebox.showinfo(t('Датасеты'),
                            t('Добавлено датасетов: {added}\nПапка: {folder}').format(added=added, folder=folder),
                            parent=self)

    def add_manual(self):
        entry = DatasetEntry(name=f"dataset-{len(self._entries) + 1}",
                             format="jsonl", location="data/train.jsonl")
        try:
            self._library().add(entry)
        except DatasetError as exc:
            messagebox.showerror(t('Датасеты'), str(exc), parent=self)
            return
        self.refresh()

    def remove_selected(self):
        entry = self._selected()
        if entry is None:
            return
        if not messagebox.askyesno(t('Удалить'),
                                   t('Удалить «{v1}» из библиотеки?').format(v1=entry.name),
                                   parent=self):
            return
        try:
            self._library().remove(entry.id)
        except DatasetError as exc:
            messagebox.showerror(t('Датасеты'), str(exc), parent=self)
            return
        self.refresh()

    def show_preview(self):
        entry = self._selected()
        if entry is None:
            set_text(self.preview_text, t('Выберите датасет в таблице.'))
            return
        root = self.app.workspace_root()
        if root is None or not entry.location:
            set_text(self.preview_text,
                     t('Предпросмотр доступен для локальных файлов в рабочей папке.'))
            return
        path = Path(entry.location)
        if not path.is_absolute():
            path = root / entry.location
        if not path.is_file():
            set_text(self.preview_text, t('Файл не найден: {v1}').format(v1=entry.location))
            return
        rows = preview_rows(path, entry.format)
        import json as _json
        set_text(self.preview_text,
                 "\n".join(_json.dumps(row, ensure_ascii=False)[:240] for row in rows)
                 or t('Файл пуст.'))


    # ------------------------------------------------------------- SFT tools
    def _selected_rows(self):
        from .datasets import read_rows

        entry = self._selected()
        if entry is None:
            messagebox.showinfo(t('Датасеты'),
                                t('Выберите датасет в таблице.'),
                                parent=self)
            return None, None
        source = Path(entry.location)
        if not source.is_file():
            messagebox.showerror(t('Датасеты'),
                                 t('Файл не найден: {v1}').format(
                                     v1=entry.location),
                                 parent=self)
            return None, None
        return entry, read_rows(source, entry.format)

    def _write_derived(self, entry, rows, suffix, label):
        from .datasets import write_rows

        source = Path(entry.location)
        target = source.with_name(f"{source.stem}.{suffix}.{entry.format}")
        write_rows(target, rows, entry.format)
        self._library().add(DatasetEntry(
            name=f"{entry.name}-{suffix}", format=entry.format,
            location=str(target), rows=len(rows),
            size_bytes=target.stat().st_size))
        self.refresh()
        self.app.activity.log(
            "system", label + f": {target.name} ({len(rows)})")
        return target

    def sft_validate(self):
        from .datasets import read_rows  # noqa: F401 - symmetry/readability
        from .sft_data import validate_sft

        entry, rows = self._selected_rows()
        if entry is None:
            return

        def work():
            return validate_sft(rows)

        def done(report):
            messagebox.showinfo(t('SFT-валидация'), report.render(),
                                parent=self)

        self.app.start_async(t('SFT-валидация'), work, done)

    def dedupe_near(self):
        from .sft_data import dedupe_near as _dedupe

        entry, rows = self._selected_rows()
        if entry is None:
            return

        def work():
            return _dedupe(rows)

        def done(result):
            kept, removed = result
            target = self._write_derived(entry, kept, "dedup",
                                         t('Near-dup дедупликация'))
            messagebox.showinfo(
                t('Near-dup дедупликация'),
                t('Удалено почти-дублей: {v1}; осталось {v2}').format(
                    v1=removed, v2=len(kept)) + f"\n{target}",
                parent=self)

        self.app.start_async(t('Near-dup дедупликация'), work, done)

    def decontaminate(self):
        from tkinter import filedialog

        from .datasets import read_rows
        from .sft_data import decontaminate as _decontaminate

        entry, rows = self._selected_rows()
        if entry is None:
            return
        eval_path = filedialog.askopenfilename(
            parent=self, title=t('Eval-датасет для деконтаминации'))
        if not eval_path:
            return
        eval_rows = read_rows(Path(eval_path), entry.format)

        def work():
            return _decontaminate(rows, eval_rows)

        def done(result):
            target = self._write_derived(entry, result.cleaned, "clean",
                                         t('Деконтаминация'))
            messagebox.showinfo(
                t('Деконтаминация'),
                result.render() + f"\n{target}", parent=self)

        self.app.start_async(t('Деконтаминация'), work, done)
