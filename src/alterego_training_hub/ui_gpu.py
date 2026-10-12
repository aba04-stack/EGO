"""Cloud GPU page: RunPod catalog, budget gate, pod lifecycle with confirmations."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk

from .cloud_gpu import CloudGpuError
from .ui_common import C, F_BASE, F_SMALL, card, page_header


class GpuPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._gpu_rows: dict[str, dict] = {}
        self._pod_rows: dict[str, dict] = {}
        self._build()

    def _build(self):
        header = page_header(
            self,
            "Внешние GPU",
            "Каталог RunPod с живыми ценами, лимит тарифа GPU и явные подтверждения "
            "перед любыми платными или разрушительными действиями.",
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        auth = card(self, "RunPod API")
        auth.pack(fill="x", padx=24, pady=(0, 12))
        row = tk.Frame(auth, bg=C["panel"])
        row.pack(fill="x")
        tk.Label(row, text="API-ключ", bg=C["panel"], font=F_BASE).pack(side="left",
                                                                        padx=(0, 8))
        self.runpod_key_var = tk.StringVar()
        tk.Entry(row, textvariable=self.runpod_key_var, show="•", bd=1, relief="solid",
                 font=F_BASE).pack(side="left", fill="x", expand=True)
        self.runpod_secret_status = tk.StringVar(value=self._secret_status("runpod_api_key"))
        tk.Label(row, textvariable=self.runpod_secret_status, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="left", padx=10)
        ttk.Button(row, text="Сохранить ключ", style="Accent.TButton",
                   command=self.save_runpod_key).pack(side="left")

        catalog = card(self, "Каталог GPU — цены из API")
        catalog.pack(fill="x", padx=24, pady=(0, 12))
        bar = tk.Frame(catalog, bg=C["panel"])
        bar.pack(fill="x", pady=(0, 8))
        tk.Label(bar, text="Облако", bg=C["panel"], font=F_BASE).pack(side="left",
                                                                     padx=(0, 6))
        self.cloud_var = tk.StringVar(value=self.app.settings.runpod_cloud)
        ttk.Combobox(bar, textvariable=self.cloud_var, values=("SECURE", "COMMUNITY"),
                     state="readonly", width=12).pack(side="left")
        ttk.Button(bar, text="Обновить каталог", style="Accent.TButton",
                   command=self.refresh_gpu_catalog).pack(side="left", padx=10)
        ttk.Button(bar, text="Мои ресурсы", command=self.refresh_pods).pack(side="left")

        gpu_columns = ("name", "id", "memory", "hourly", "availability")
        self.gpu_tree = ttk.Treeview(catalog, columns=gpu_columns, show="headings",
                                     height=6)
        for col, title, width in [
            ("name", "Модель GPU", 250), ("id", "ID", 190), ("memory", "Память", 90),
            ("hourly", "Цена/час", 170), ("availability", "Доступность", 130),
        ]:
            self.gpu_tree.heading(col, text=title)
            self.gpu_tree.column(col, width=width, anchor="w")
        self.gpu_tree.pack(side="left", fill="x", expand=True)
        scroll = ttk.Scrollbar(catalog, orient="vertical", command=self.gpu_tree.yview)
        scroll.pack(side="right", fill="y")
        self.gpu_tree.configure(yscrollcommand=scroll.set)

        create = card(self, "Запуск GPU — оплата начнётся после создания")
        create.pack(fill="x", padx=24, pady=(0, 12))
        create.columnconfigure(1, weight=1)
        create.columnconfigure(3, weight=1)
        self.gpu_budget_var = tk.StringVar(
            value=str(self.app.settings.runpod_max_gpu_hourly_usd))
        self.gpu_disk_var = tk.StringVar(value=str(self.app.settings.runpod_container_disk_gb))
        self.gpu_image_var = tk.StringVar(value=self.app.settings.runpod_image)
        self.gpu_name_var = tk.StringVar(value="alterego-training")

        def entry(row, col, label, var, width=None):
            tk.Label(create, text=label, bg=C["panel"], font=F_BASE).grid(
                row=row, column=col, sticky="w", padx=4, pady=3)
            tk.Entry(create, textvariable=var, bd=1, relief="solid", font=F_BASE,
                     width=width).grid(row=row, column=col + 1, sticky="ew", padx=4, pady=3)

        entry(0, 0, "Лимит цены GPU ($/час)", self.gpu_budget_var, 12)
        entry(0, 2, "Контейнерный диск (GB)", self.gpu_disk_var, 10)
        entry(1, 0, "Имя ресурса", self.gpu_name_var)
        entry(1, 2, "Образ контейнера", self.gpu_image_var, 38)
        ttk.Button(create, text="Проверить цену и создать…",
                   command=self.create_gpu_pod).grid(
            row=2, column=0, columnspan=4, sticky="ew", padx=4, pady=(8, 2))
        tk.Label(
            create,
            text="Лимит действует только на цену GPU и не является общим потолком "
                 "расходов. Контейнерный диск временный: сохраняйте чекпойнты отдельно.",
            bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=900, justify="left",
        ).grid(row=3, column=0, columnspan=4, sticky="w", padx=4, pady=(5, 0))

        pods = card(self, "Мои GPU-ресурсы")
        pods.pack(fill="x", padx=24, pady=(0, 12))
        pods_columns = ("id", "name", "status", "gpu", "cost")
        self.pod_tree = ttk.Treeview(pods, columns=pods_columns, show="headings",
                                     height=5)
        for col, title, width in [
            ("id", "ID", 180), ("name", "Имя", 220), ("status", "Статус", 110),
            ("gpu", "GPU", 170), ("cost", "Расходы", 150),
        ]:
            self.pod_tree.heading(col, text=title)
            self.pod_tree.column(col, width=width, anchor="w")
        self.pod_tree.pack(side="left", fill="x", expand=True)
        pod_scroll = ttk.Scrollbar(pods, orient="vertical", command=self.pod_tree.yview)
        pod_scroll.pack(side="right", fill="y")
        self.pod_tree.configure(yscrollcommand=pod_scroll.set)
        pod_buttons = tk.Frame(pods, bg=C["panel"])
        pod_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(pod_buttons, text="Остановить",
                   command=lambda: self.pod_action("stop")).pack(side="left")
        ttk.Button(pod_buttons, text="Возобновить",
                   command=lambda: self.pod_action("start")).pack(side="left", padx=8)
        ttk.Button(pod_buttons, text="Удалить ресурс…", style="Danger.TButton",
                   command=self.terminate_pod).pack(side="left", padx=8)

        self.gpu_notes_var = tk.StringVar(
            value="Подключите ключ RunPod и обновите каталог. Внешнее обучение "
                  "моделей запускается отдельно на странице «Обучение».")
        tk.Label(self, textvariable=self.gpu_notes_var, bg=C["bg"], fg=C["muted"],
                 font=F_SMALL, wraplength=900, justify="left").pack(
            anchor="w", padx=24, pady=(0, 14))

    # -------------------------------------------------------------- helpers
    def _secret_status(self, name: str) -> str:
        try:
            return "Ключ сохранён" if self.app.secrets.get(name) else "Ключ не сохранён"
        except Exception:
            return "Хранилище ключей недоступно"

    def _persist_gpu_settings(self):
        try:
            budget = float(self.gpu_budget_var.get())
            disk = int(self.gpu_disk_var.get())
            if budget != budget or budget in (float("inf"), float("-inf")) or budget <= 0:
                raise ValueError("Цена в час должна быть положительной.")
            if not 10 <= disk <= 1000:
                raise ValueError("Контейнерный диск должен быть 10–1000 GB.")
            self.app.settings.runpod_cloud = self.cloud_var.get().upper()
            self.app.settings.runpod_max_gpu_hourly_usd = budget
            self.app.settings.runpod_container_disk_gb = disk
            self.app.settings.runpod_image = self.gpu_image_var.get().strip()
            self.app.save_settings()
            return budget, disk
        except ValueError as exc:
            raise CloudGpuError(str(exc)) from None

    # ------------------------------------------------------------- handlers
    def save_runpod_key(self):
        key = self.runpod_key_var.get().strip()
        if not key:
            messagebox.showinfo("RunPod", "Введите API-ключ для сохранения.", parent=self)
            return
        try:
            self.app.secrets.set("runpod_api_key", key)
            self.runpod_key_var.set("")
            self.runpod_secret_status.set(self._secret_status("runpod_api_key"))
            messagebox.showinfo("RunPod", "Ключ сохранён в системном хранилище.",
                                parent=self)
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)

    def refresh_gpu_catalog(self):
        try:
            client = self.app.runpod_client()
            self._persist_gpu_settings()
            cloud = self.cloud_var.get().upper()
        except Exception as exc:
            messagebox.showerror("Внешние GPU", str(exc), parent=self)
            return
        self.app.start_async("Загрузка каталога GPU",
                             lambda: client.gpu_catalog(cloud=cloud),
                             self._show_gpu_catalog)

    @staticmethod
    def _price_text(gpu):
        prices = gpu.get("price")
        values = []
        for cloud_name, top_level in (("secure", "securePrice"),
                                      ("community", "communityPrice")):
            value = prices.get(cloud_name) if isinstance(prices, dict) else None
            if value is None:
                value = gpu.get(top_level)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(f"{cloud_name}: ${float(value):.3f}/ч")
        return " · ".join(values) or "цена не получена"

    def _show_gpu_catalog(self, items):
        self._gpu_rows.clear()
        self.gpu_tree.delete(*self.gpu_tree.get_children())
        for index, gpu in enumerate(items):
            iid = f"gpu-{index}"
            self._gpu_rows[iid] = gpu
            memory = gpu.get("memory", gpu.get("memoryInGb", "—"))
            availability = gpu.get("availability", gpu.get("maxGpuCount", "—"))
            if isinstance(availability, dict):
                availability = availability.get("available", availability.get("status", "—"))
            if isinstance(availability, (dict, list)):
                availability = json.dumps(availability, ensure_ascii=False)
            self.gpu_tree.insert("", "end", iid=iid, values=(
                gpu.get("name", gpu.get("displayName", "Unknown GPU")),
                gpu.get("id", ""), memory, self._price_text(gpu), str(availability),
            ))
        self.gpu_notes_var.set(f"GPU в каталоге: {len(items)}. Выберите GPU для расчёта.")

    def refresh_pods(self):
        try:
            client = self.app.runpod_client()
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)
            return
        self.app.start_async("Загрузка ресурсов RunPod",
                             lambda: client.list_pods(), self._show_pods)

    def _show_pods(self, items):
        self._pod_rows.clear()
        self.pod_tree.delete(*self.pod_tree.get_children())
        for index, pod in enumerate(items):
            iid = f"pod-{index}"
            self._pod_rows[iid] = pod
            gpu = pod.get("gpu", pod.get("gpuTypeId", "—"))
            if isinstance(gpu, dict):
                gpu = gpu.get("id", gpu.get("name", "—"))
            cost = pod.get("cost", pod.get("costPerHr", "—"))
            self.pod_tree.insert("", "end", iid=iid, values=(
                pod.get("id", ""), pod.get("name", ""), pod.get("status", ""),
                gpu, str(cost),
            ))
        self.gpu_notes_var.set(f"Ресурсов в аккаунте: {len(items)}.")

    def create_gpu_pod(self):
        selected = self.gpu_tree.selection()
        if not selected:
            messagebox.showinfo("Внешние GPU", "Сначала выберите GPU в каталоге.",
                                parent=self)
            return
        gpu = self._gpu_rows.get(selected[0])
        if not gpu or not gpu.get("id"):
            messagebox.showerror("Внешние GPU", "У выбранной записи нет GPU ID.",
                                 parent=self)
            return
        try:
            client = self.app.runpod_client()
            budget, disk = self._persist_gpu_settings()
            plan = client.plan_pod(
                gpu_id=str(gpu["id"]),
                max_gpu_hourly_usd=budget,
                cloud=self.cloud_var.get().upper(),
                image=self.gpu_image_var.get().strip(),
                container_disk_gb=disk,
                name=self.gpu_name_var.get().strip(),
            )
        except Exception as exc:
            messagebox.showerror("Проверка цены", str(exc), parent=self)
            return

        confirmation = (
            f"GPU: {plan['gpu_name']}\n"
            f"Тариф GPU: ${plan['gpu_hourly_usd']:.4f} в час\n"
            f"Лимит тарифа GPU: ${plan['gpu_only_budget_usd']:.4f} в час\n"
            f"Контейнерный диск: {plan['container_disk_gb']} GB\n\n"
            "Это не общий лимит расходов: хранилище и другие услуги тарифицируются "
            "отдельно. Данные на контейнерном диске могут исчезнуть.\n\n"
            "Создать платный ресурс сейчас?"
        )
        if not messagebox.askyesno("Подтверждение расходов", confirmation, parent=self):
            return
        self.app.start_async("Создание платного GPU-ресурса",
                             lambda: client.create_pod(plan, confirmed=True),
                             self._after_gpu_created)

    def _after_gpu_created(self, pod):
        self.gpu_notes_var.set(
            f"Создан ресурс {pod.get('id', '')}. Проверьте статус и расходы.")
        self.refresh_pods()
        messagebox.showinfo(
            "GPU создан",
            f"ID: {pod.get('id', 'не указан')}\n"
            "Создание ресурса не запускает обучение автоматически.",
            parent=self,
        )

    def _selected_pod(self):
        selected = self.pod_tree.selection()
        if not selected:
            messagebox.showinfo("GPU", "Сначала выберите ресурс из списка.", parent=self)
            return None
        pod = self._pod_rows.get(selected[0])
        if not pod or not pod.get("id"):
            messagebox.showerror("GPU", "У выбранного ресурса нет ID.", parent=self)
            return None
        return pod

    def pod_action(self, action: str):
        pod = self._selected_pod()
        if not pod:
            return
        title = "остановить" if action == "stop" else "возобновить"
        if not messagebox.askyesno("Управление GPU",
                                   f"Подтвердить действие «{title}» для {pod['id']}?",
                                   parent=self):
            return
        try:
            client = self.app.runpod_client()
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)
            return
        self.app.start_async(f"Действие RunPod: {action}",
                             lambda: client.pod_action(str(pod["id"]), action,
                                                       confirmed=True),
                             lambda _: self.refresh_pods())

    def terminate_pod(self):
        pod = self._selected_pod()
        if not pod:
            return
        if not messagebox.askyesno(
            "Безвозвратное удаление",
            f"Удалить GPU-ресурс {pod['id']}? Данные на контейнерном диске "
            "могут быть потеряны.",
            parent=self,
        ):
            return
        try:
            client = self.app.runpod_client()
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)
            return
        self.app.start_async("Удаление GPU-ресурса",
                             lambda: client.terminate_pod(str(pod["id"]),
                                                          confirmed=True),
                             lambda _: self.refresh_pods())
