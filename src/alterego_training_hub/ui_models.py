"""Models page: registry of local and cloud-hosted model artifacts."""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .i18n import t
from .models_registry import ModelEntry, ModelRegistryError, default_library_dir
from .ui_common import F_BASE, F_SMALL, C, card, page_header


class ModelsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._entries: dict[str, ModelEntry] = {}
        self._build()

    def _build(self):
        header = page_header(
            self,
            t('Модели'),
            t('Единый каталог моделей: локальные чекпойнты и облачные хранилища (s3://, hf://, runpod://, https://). Манифест можно переносить между машинами.'),
            actions=[(t('Добавить'), self.add_entry, "Accent.TButton")],
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        lib_card = card(self)
        lib_card.pack(fill="x", padx=24, pady=(0, 12))
        row = tk.Frame(lib_card, bg=C["panel"])
        row.pack(fill="x")
        tk.Label(row, text=t('Папка библиотеки моделей:'), bg=C["panel"],
                 font=F_BASE).pack(side="left")
        self.library_var = tk.StringVar()
        tk.Label(row, textvariable=self.library_var, bg=C["panel"], fg=C["muted"],
                 font=F_BASE).pack(side="left", padx=8)
        ttk.Button(row, text=t('Сменить папку…'), command=self.change_library).pack(side="right")
        tk.Label(
            lib_card,
            text=t('Укажите синхронизируемую облаком папку, чтобы каталог моделей был в облаке.'),
            bg=C["panel"], fg=C["muted"], font=F_SMALL,
        ).pack(anchor="w", pady=(6, 0))

        table_card = card(self)
        table_card.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        toolbar = tk.Frame(table_card, bg=C["panel"])
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text=t('Обновить'), command=self.refresh).pack(side="left")
        ttk.Button(toolbar, text=t('Добавить'), style="Accent.TButton",
                   command=self.add_entry).pack(side="left", padx=8)
        ttk.Button(toolbar, text=t('Сохранить изменения'),
                   command=self.save_entry).pack(side="left", padx=8)
        ttk.Button(toolbar, text=t('Удалить'), style="Danger.TButton",
                   command=self.remove_entry).pack(side="left", padx=8)
        ttk.Button(toolbar, text=t('Сканировать папку…'),
                   command=self.scan_folder).pack(side="left", padx=8)
        ttk.Button(toolbar, text=t('Экспорт…'), command=self.export_manifest).pack(side="left",
                                                                               padx=8)
        ttk.Button(toolbar, text=t('Импорт…'), command=self.import_manifest).pack(side="left")
        ttk.Button(toolbar, text=t('Скачать с HF…'),
                   command=self.download_hf).pack(side="left", padx=8)
        ttk.Button(toolbar, text=t('Push на HF…'),
                   command=self.push_hf).pack(side="left")

        columns = ("name", "kind", "location", "model_id", "updated")
        self.tree = ttk.Treeview(table_card, columns=columns, show="headings", height=8)
        for col, title, width in [
            ("name", t('Название'), 200), ("kind", t('Тип'), 80),
            ("location", t('Путь / URI'), 340), ("model_id", "API model id", 160),
            ("updated", t('Обновлено'), 130),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._load_selected())

        # Model tools: export / quantize / benchmark / prompt suite
        tools_card = card(self, t('Инструменты модели'))
        tools_card.pack(fill="x", padx=24, pady=(0, 12))
        tools_row = tk.Frame(tools_card, bg=C["panel"])
        tools_row.pack(fill="x")
        tk.Label(tools_row, text=t('Формат/рецепт'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        self.tool_option_var = tk.StringVar(value="gguf")
        ttk.Combobox(tools_row, textvariable=self.tool_option_var, width=10,
                     values=("gguf", "onnx", "q8_0", "q5_k_m", "q4_k_m",
                             "q4_0", "q3_k_m", "int8"),
                     state="readonly").pack(side="left", padx=(0, 12))
        ttk.Button(tools_row, text=t('Экспорт'),
                   command=self.export_model).pack(side="left", padx=(0, 6))
        ttk.Button(tools_row, text=t('Квантизация'),
                   command=self.quantize_model).pack(side="left", padx=(0, 6))
        ttk.Button(tools_row, text=t('Бенчмарк'),
                   command=self.benchmark_model).pack(side="left", padx=(0, 6))
        ttk.Button(tools_row, text=t('Промпт-набор'),
                   command=self.run_prompt_suite).pack(side="left")
        self.tools_status = tk.StringVar(
            value=t('Выберите модель и инструмент. Экспорт/квантизация требуют внешних конвертеров (см. подсказку в результате).'))
        tk.Label(tools_card, textvariable=self.tools_status, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL, wraplength=900,
                 justify="left").pack(anchor="w", pady=(6, 0))

        # Editor
        edit_card = card(self, t('Карточка модели'))
        edit_card.pack(fill="x", padx=24, pady=(0, 12))
        edit_card.columnconfigure(1, weight=1)
        edit_card.columnconfigure(3, weight=1)

        self.var_name = tk.StringVar()
        self.var_kind = tk.StringVar(value="local")
        self.var_location = tk.StringVar()
        self.var_base_url = tk.StringVar()
        self.var_model_id = tk.StringVar()

        def field(row, col, label, var, widget="entry", width=None):
            tk.Label(edit_card, text=label, bg=C["panel"], font=F_BASE).grid(
                row=row, column=col, sticky="w", padx=(0, 8), pady=4)
            if widget == "combo":
                w = ttk.Combobox(edit_card, textvariable=var, values=("local", "cloud"),
                                 state="readonly", width=10)
            else:
                w = tk.Entry(edit_card, textvariable=var, bd=1, relief="solid",
                             font=F_BASE, width=width)
            w.grid(row=row, column=col + 1, sticky="ew", padx=(0, 16), pady=4)

        field(0, 0, t('Название'), self.var_name)
        field(0, 2, t('Тип'), self.var_kind, widget="combo")
        field(1, 0, t('Путь / URI'), self.var_location)
        field(1, 2, "API model id", self.var_model_id)
        field(2, 0, t('URL инференса'), self.var_base_url)

        tk.Label(edit_card, text=t('Заметки'), bg=C["panel"], font=F_BASE).grid(
            row=3, column=0, sticky="nw", padx=(0, 8), pady=4)
        self.notes = tk.Text(edit_card, height=3, wrap="word", bd=1, relief="solid",
                             font=F_BASE)
        self.notes.grid(row=3, column=1, columnspan=3, sticky="ew", pady=4)

        self.models_status = tk.StringVar(value="")
        tk.Label(self, textvariable=self.models_status, bg=C["bg"], fg=C["muted"],
                 font=F_SMALL).pack(anchor="w", padx=24, pady=(0, 14))

        self._refresh_library_label()

    # ------------------------------------------------------------- handlers
    def _refresh_library_label(self):
        raw = (self.app.settings.model_library_path or "").strip()
        self.library_var.set(str(Path(raw).expanduser()) if raw else str(default_library_dir()))

    def change_library(self):
        path = filedialog.askdirectory(title=t('Папка библиотеки моделей'))
        if not path:
            return
        self.app.settings.model_library_path = path
        self.app.save_settings()
        self._refresh_library_label()
        self.refresh()

    def on_show(self):
        self._refresh_library_label()
        self.refresh()

    def refresh(self):
        try:
            entries = self.app.model_registry().load()
        except Exception as exc:
            messagebox.showerror(t('Модели'), str(exc), parent=self)
            return
        self.tree.delete(*self.tree.get_children())
        self._entries.clear()
        for entry in entries:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.updated_at))
            iid = self.tree.insert("", "end", values=(
                entry.name, entry.kind, entry.location, entry.model_id, stamp,
            ))
            self._entries[iid] = entry
        self.models_status.set(t('Моделей в каталоге: {v1}').format(v1=len(entries)))

    def _load_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        entry = self._entries.get(selection[0])
        if not entry:
            return
        self.var_name.set(entry.name)
        self.var_kind.set(entry.kind)
        self.var_location.set(entry.location)
        self.var_base_url.set(entry.base_url)
        self.var_model_id.set(entry.model_id)
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", entry.notes)

    def _selected_entry(self):
        selection = self.tree.selection()
        return self._entries.get(selection[0]) if selection else None

    def _run_model_tool(self, name: str, args: dict, label: str,
                        confirm_text: str = ""):
        entry = self._selected_entry()
        if entry is None:
            messagebox.showinfo(t('Инструменты модели'),
                                t('Сначала выберите модель в таблице.'),
                                parent=self)
            return
        if confirm_text and not messagebox.askyesno(label, confirm_text,
                                                    parent=self):
            return
        args = dict(args)
        args.setdefault("model_id", entry.id)
        tools, _schemas, _mutations = self.app.agent_extra_tools()
        handler = tools.get(name)

        def work():
            return handler(args)

        def done(result):
            parts = []
            for key in ("checks", "lines", "rank"):
                value = result.get(key)
                if isinstance(value, list) and value:
                    parts.extend(str(item) for item in value)
            for key in ("report", "table", "line", "hint", "error",
                        "output_path"):
                value = result.get(key)
                if value:
                    parts.append(str(value))
            text = "\n".join(parts) or (t('Готово.') if result.get("ok")
                                        else t('Не удалось.'))
            self.tools_status.set(text[:600])
            if result.get("ok"):
                messagebox.showinfo(label, text[:1500], parent=self)
            else:
                messagebox.showerror(label, text[:1500], parent=self)

        def failed(error):
            self.tools_status.set(t('Ошибка: {error}').format(error=error))
            messagebox.showerror(label, str(error), parent=self)

        self.app.start_async(label, work, done, failed)

    def export_model(self):
        option = self.tool_option_var.get().strip().lower()
        fmt = option if option in {"gguf", "onnx"} else "gguf"
        self._run_model_tool(
            "export_model", {"format": fmt}, t('Экспорт модели'),
            t('Конвертировать модель в {v1}? Для этого потребуются внешние инструменты (transformers[onnx] или llama.cpp).').format(v1=fmt.upper()))

    def quantize_model(self):
        option = self.tool_option_var.get().strip().lower()
        quant = option if option in {"q8_0", "q5_k_m", "q4_k_m", "q4_0",
                                     "q3_k_m", "int8"} else "q4_k_m"
        self._run_model_tool(
            "quantize_model", {"quant_type": quant}, t('Квантизация модели'),
            t('Квантизовать модель ({quant})? Файл будет создан в папке библиотеки (exports).').format(quant=quant))

    def benchmark_model(self):
        self._run_model_tool("benchmark_model", {"iterations": 3},
                             t('Бенчмарк модели'),
                             t('Выполнить 3 замера скорости модели?'))

    def run_prompt_suite(self):
        self._run_model_tool(
            "run_prompt_suite", {}, t('Промпт-набор'),
            t('Прогнать набор из 5 промптов? Это отправит запросы к API и может расходовать кредиты провайдера.'))

    def _entry_from_form(self) -> ModelEntry:
        metrics: dict[str, float] = {}
        selection = self.tree.selection()
        if selection and selection[0] in self._entries:
            metrics = dict(self._entries[selection[0]].metrics)
        entry_id = ""
        if selection and selection[0] in self._entries:
            entry_id = self._entries[selection[0]].id
        entry = ModelEntry(
            name=self.var_name.get().strip(),
            kind=self.var_kind.get().strip() or "local",
            location=self.var_location.get().strip(),
            base_url=self.var_base_url.get().strip(),
            model_id=self.var_model_id.get().strip(),
            notes=self.notes.get("1.0", "end").strip(),
            metrics=metrics,
        )
        if entry_id:
            entry.id = entry_id
        return entry

    def add_entry(self):
        try:
            self.app.model_registry().add(self._entry_from_form())
        except ModelRegistryError as exc:
            messagebox.showerror(t('Модели'), str(exc), parent=self)
            return
        self.refresh()
        self.app.set_status(t('Модель добавлена в каталог'))

    def save_entry(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(t('Модели'), t('Выберите модель в списке.'), parent=self)
            return
        try:
            self.app.model_registry().update(self._entry_from_form())
        except ModelRegistryError as exc:
            messagebox.showerror(t('Модели'), str(exc), parent=self)
            return
        self.refresh()
        self.app.set_status(t('Карточка модели сохранена'))

    def remove_entry(self):
        selection = self.tree.selection()
        if not selection:
            return
        entry = self._entries.get(selection[0])
        if not entry:
            return
        if not messagebox.askyesno(t('Удалить модель'),
                                   t('Удалить «{v1}» из каталога?').format(v1=entry.name), parent=self):
            return
        try:
            self.app.model_registry().remove(entry.id)
        except ModelRegistryError as exc:
            messagebox.showerror(t('Модели'), str(exc), parent=self)
            return
        self.refresh()

    def scan_folder(self):
        folder = filedialog.askdirectory(title=t('Папка с чекпойнтами моделей'))
        if not folder:
            return

        def work():
            registry = self.app.model_registry()
            found = registry.scan_folder(folder)
            entries = registry.load()
            existing = {entry.location for entry in entries}
            added = 0
            for entry in found:
                if entry.location not in existing:
                    registry.add(entry)
                    added += 1
            return added

        self.app.start_async(t('Сканирование папки моделей'), work,
                             lambda added: self._after_scan(added, folder))

    def _after_scan(self, added: int, folder: str):
        self.refresh()
        messagebox.showinfo(t('Модели'),
                            t('Найдено и добавлено моделей: {added}\nПапка: {folder}').format(added=added, folder=folder),
                            parent=self)

    def export_manifest(self):
        dest = filedialog.asksaveasfilename(title=t('Экспорт манифеста'),
                                            defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not dest:
            return
        try:
            path = self.app.model_registry().export_manifest(dest)
        except Exception as exc:
            messagebox.showerror(t('Модели'), str(exc), parent=self)
            return
        messagebox.showinfo(t('Модели'), t('Манифест сохранён: {path}').format(path=path), parent=self)

    def import_manifest(self):
        src = filedialog.askopenfilename(title=t('Импорт манифеста'),
                                         filetypes=[("JSON", "*.json")])
        if not src:
            return
        try:
            count = self.app.model_registry().import_manifest(src)
        except ModelRegistryError as exc:
            messagebox.showerror(t('Модели'), str(exc), parent=self)
            return
        self.refresh()
        messagebox.showinfo(t('Модели'), t('Записей в манифесте: {count}').format(count=count), parent=self)


    # ------------------------------------------------------------- HF Hub
    def _hf_token(self) -> str:
        try:
            return self.app.secrets.get("connector.hf_token") or ""
        except Exception:
            return ""

    def download_hf(self):
        """Скачать модель с Hugging Face Hub в библиотеку."""
        from tkinter import simpledialog

        from .hf_hub import download_model

        repo = simpledialog.askstring(
            t('Скачать с Hugging Face'), t('Repo id (owner/name):'),
            parent=self)
        if not repo:
            return
        library = self.app.model_registry().library_dir

        def done(result):
            self.refresh()
            messagebox.showinfo(t('Hugging Face'), result.render(),
                                parent=self)

        def failed(error):
            messagebox.showerror(t('Hugging Face'), str(error), parent=self)

        self.app.start_async(
            t('Скачивание {v1}').format(v1=repo),
            lambda: download_model(repo, library, self._hf_token()),
            done, failed)

    def push_hf(self):
        """Отправить выбранную локальную модель на Hugging Face Hub."""
        from tkinter import simpledialog

        from .hf_hub import push_folder

        entry = self._selected_entry()
        if entry is None or not Path(entry.location).is_dir():
            messagebox.showinfo(
                t('Hugging Face'),
                t('Сначала выберите модель с локальной папкой.'),
                parent=self)
            return
        repo = simpledialog.askstring(
            t('Push на Hugging Face'), t('Repo id (owner/name):'),
            initialvalue=entry.model_id or "", parent=self)
        if not repo:
            return
        token = self._hf_token()
        folder = Path(entry.location)

        def done(url):
            messagebox.showinfo(t('Hugging Face'), str(url), parent=self)

        def failed(error):
            messagebox.showerror(t('Hugging Face'), str(error), parent=self)

        self.app.start_async(
            t('Push {v1}').format(v1=repo),
            lambda: push_folder(repo, folder, token), done, failed)
