"""Search page: regex search across the workspace with jump-to-line results."""
from __future__ import annotations

import hashlib
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .config import app_data_dir
from .i18n import t
from .semantic_search import SemanticIndex
from .tools import WorkspaceTools
from .ui_common import F_BASE, F_MONO, F_SMALL, C, Collapsible, card, page_header

MAX_RESULTS = 300


class SearchPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._results: list[tuple[Path, int]] = []
        self._build()

    def _build(self):
        header = page_header(
            self,
            t('Поиск по проекту'),
            t('Поиск по содержимому файлов рабочей папки (регулярные выражения). Двойной клик по результату открывает файл в редакторе на нужной строке; Ctrl+Shift+F — сюда.'),
        )
        header.pack(fill="x", padx=24, pady=(20, 10))

        params = Collapsible(self, t('Параметры поиска'))
        params.pack(fill="x", padx=24, pady=(0, 10))
        params.set_hint(t('свернуть/развернуть'))
        row = tk.Frame(params.body, bg=C["panel"])
        row.pack(fill="x")
        tk.Label(row, text=t('Шаблон (regex)'), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 8))
        self.query_var = tk.StringVar()
        self.query_entry = tk.Entry(row, textvariable=self.query_var, bd=1,
                                    relief="solid", font=F_MONO, width=36)
        self.query_entry.pack(side="left", padx=(0, 8))
        self.query_entry.bind("<Return>", lambda _e: self.run_search())
        tk.Label(row, text=t('Файлы (glob)'), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(8, 8))
        self.glob_var = tk.StringVar(value="**/*")
        tk.Entry(row, textvariable=self.glob_var, bd=1, relief="solid",
                 font=F_MONO, width=18).pack(side="left", padx=(0, 8))
        ttk.Button(row, text=t('Найти'), style="Accent.TButton",
                   command=self.run_search).pack(side="left")
        ttk.Button(row, text=t('🧠 По смыслу'),
                   command=self.run_semantic).pack(side="left", padx=(8, 0))
        ttk.Button(row, text=t('Очистить'),
                   command=self.clear_results).pack(side="left", padx=8)
        self.status_var = tk.StringVar(value=t('Введите шаблон и нажмите «Найти».'))
        tk.Label(row, textvariable=self.status_var, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="left", padx=10)

        results_card = card(self, t('Результаты'))
        results_card.pack(fill="both", expand=True, padx=24, pady=(0, 14))
        columns = ("file", "line", "text")
        self.tree = ttk.Treeview(results_card, columns=columns, show="headings",
                                 height=14)
        for col, title, width in [
            ("file", t('Файл'), 220), ("line", t('Строка'), 70),
            ("text", t('Совпадение'), 560),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.tree.bind("<Return>", lambda _e: self.open_selected())

    # ------------------------------------------------------------- handlers
    def clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._results = []
        self.status_var.set(t('Результаты очищены.'))

    def run_search(self):
        root = self.app.workspace_root()
        if root is None:
            messagebox.showinfo(t('Поиск'), t('Сначала выберите рабочую папку.'),
                                parent=self)
            return
        pattern = self.query_var.get()
        if not pattern.strip():
            return
        glob = self.glob_var.get().strip() or "**/*"

        def done(result):
            matches = result.get("matches", [])
            self.clear_results()
            for index, match in enumerate(matches[:MAX_RESULTS]):
                text = match if isinstance(match, str) else str(match)
                # tools.search_files returns "relpath:line: text"
                rel, line_no, snippet = self._parse_match(text)
                item_id = self.tree.insert("", "end", values=(
                    rel, line_no, snippet))
                self._results.append((item_id, root / rel, line_no))
            self.status_var.set(t('Совпадений: {v1}').format(v1=len(matches))
                                + (t(' (показаны первые {v1})').format(v1=min(len(matches), MAX_RESULTS))
                                   if len(matches) > MAX_RESULTS else ""))

        self.app.start_async(
            t('Поиск: {pattern}').format(pattern=pattern),
            lambda: WorkspaceTools(root).search_files(pattern, glob),
            done,
        )

    def run_semantic(self):
        """Semantic search: local hash embeddings, cosine over chunks."""
        root = self.app.workspace_root()
        if root is None:
            messagebox.showinfo(t('Поиск'), t('Сначала выберите рабочую папку.'),
                                parent=self)
            return
        query = self.query_var.get()
        if not query.strip():
            return
        cache_name = hashlib.sha256(
            str(root.resolve()).encode("utf-8")).hexdigest()[:16]
        cache_path = app_data_dir() / "semantic-index" / f"{cache_name}.json"

        def work():
            index = SemanticIndex(root)
            stats = index.build(SemanticIndex.load_cache(cache_path))
            try:
                index.save(cache_path)
            except OSError:
                pass
            return {"hits": index.search(query), "stats": stats}

        def done(result):
            hits = result["hits"]
            self.clear_results()
            for hit in hits:
                item_id = self.tree.insert("", "end", values=(
                    hit.path, hit.line,
                    f"{hit.score:.2f} · {hit.snippet}"))
                self._results.append((item_id, root / hit.path, hit.line))
            stats = result["stats"]
            self.status_var.set(
                t('По смыслу: {v1} результатов · индекс: {v2} файлов, {v3} новых чанков').format(
                    v1=len(hits), v2=stats["files"], v3=stats["embedded"]))

        self.app.start_async(t('Смысловой поиск: {pattern}').format(pattern=query),
                             work, done)

    @staticmethod
    def _parse_match(text: str) -> tuple[str, int, str]:
        first, sep, rest = text.partition(":")
        second, sep2, snippet = rest.partition(":")
        if sep and sep2 and second.isdigit():
            return first, int(second), snippet.strip()
        return text, 0, ""

    def open_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        item_id = selection[0]
        record = next((r for r in self._results if r[0] == item_id), None)
        if record is None:
            return
        _iid, path, line_no = record
        self.app.show_page("editor")
        editor = self.app.pages["editor"]
        editor.open_file(path, line=line_no or None)
