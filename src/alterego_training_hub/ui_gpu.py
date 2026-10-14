"""Cloud GPU page: RunPod catalog, budget gate, pod lifecycle with confirmations."""
from __future__ import annotations
from .i18n import t

import json
import tkinter as tk
from tkinter import messagebox, ttk

from .cloud_gpu import CloudGpuError
from .ui_common import C, F_BASE, F_MONO, F_SMALL, Collapsible, card, page_header


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
            t('Внешние GPU'),
            t('Каталог RunPod с живыми ценами, лимит тарифа GPU и явные подтверждения перед любыми платными или разрушительными действиями.'),
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        auth_section = Collapsible(self, "RunPod API")
        auth_section.pack(fill="x", padx=24, pady=(0, 12))
        auth = auth_section.body
        row = tk.Frame(auth, bg=C["panel"])
        row.pack(fill="x")
        tk.Label(row, text=t('API-ключ'), bg=C["panel"], font=F_BASE).pack(side="left",
                                                                        padx=(0, 8))
        self.runpod_key_var = tk.StringVar()
        tk.Entry(row, textvariable=self.runpod_key_var, show="•", bd=1, relief="solid",
                 font=F_BASE).pack(side="left", fill="x", expand=True)
        self.runpod_secret_status = tk.StringVar(value=self._secret_status("runpod_api_key"))
        tk.Label(row, textvariable=self.runpod_secret_status, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="left", padx=10)
        ttk.Button(row, text=t('Сохранить ключ'), style="Accent.TButton",
                   command=self.save_runpod_key).pack(side="left")

        catalog = card(self, t('Каталог GPU — цены из API'))
        catalog.pack(fill="x", padx=24, pady=(0, 12))
        bar = tk.Frame(catalog, bg=C["panel"])
        bar.pack(fill="x", pady=(0, 8))
        tk.Label(bar, text=t('Облако'), bg=C["panel"], font=F_BASE).pack(side="left",
                                                                     padx=(0, 6))
        self.cloud_var = tk.StringVar(value=self.app.settings.runpod_cloud)
        ttk.Combobox(bar, textvariable=self.cloud_var, values=("SECURE", "COMMUNITY"),
                     state="readonly", width=12).pack(side="left")
        ttk.Button(bar, text=t('Обновить каталог'), style="Accent.TButton",
                   command=self.refresh_gpu_catalog).pack(side="left", padx=10)
        ttk.Button(bar, text=t('Мои ресурсы'), command=self.refresh_pods).pack(side="left")

        gpu_columns = ("name", "id", "memory", "hourly", "availability")
        self.gpu_tree = ttk.Treeview(catalog, columns=gpu_columns, show="headings",
                                     height=6)
        for col, title, width in [
            ("name", t('Модель GPU'), 250), ("id", "ID", 190), ("memory", t('Память'), 90),
            ("hourly", t('Цена/час'), 170), ("availability", t('Доступность'), 130),
        ]:
            self.gpu_tree.heading(col, text=title)
            self.gpu_tree.column(col, width=width, anchor="w")
        self.gpu_tree.pack(side="left", fill="x", expand=True)
        scroll = ttk.Scrollbar(catalog, orient="vertical", command=self.gpu_tree.yview)
        scroll.pack(side="right", fill="y")
        self.gpu_tree.configure(yscrollcommand=scroll.set)

        create = card(self, t('Запуск GPU — оплата начнётся после создания'))
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

        entry(0, 0, t('Лимит цены GPU ($/час)'), self.gpu_budget_var, 12)
        entry(0, 2, t('Контейнерный диск (GB)'), self.gpu_disk_var, 10)
        entry(1, 0, t('Имя ресурса'), self.gpu_name_var)
        entry(1, 2, t('Образ контейнера'), self.gpu_image_var, 38)
        ttk.Button(create, text=t('Проверить цену и создать…'),
                   command=self.create_gpu_pod).grid(
            row=2, column=0, columnspan=4, sticky="ew", padx=4, pady=(8, 2))
        tk.Label(
            create,
            text=t('Лимит действует только на цену GPU и не является общим потолком расходов. Контейнерный диск временный: сохраняйте чекпойнты отдельно.'),
            bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=900, justify="left",
        ).grid(row=3, column=0, columnspan=4, sticky="w", padx=4, pady=(5, 0))

        pods = card(self, t('Мои GPU-ресурсы'))
        pods.pack(fill="x", padx=24, pady=(0, 12))
        pods_columns = ("id", "name", "status", "gpu", "cost")
        self.pod_tree = ttk.Treeview(pods, columns=pods_columns, show="headings",
                                     height=5)
        for col, title, width in [
            ("id", "ID", 180), ("name", t('Имя'), 220), ("status", t('Статус'), 110),
            ("gpu", "GPU", 170), ("cost", t('Расходы'), 150),
        ]:
            self.pod_tree.heading(col, text=title)
            self.pod_tree.column(col, width=width, anchor="w")
        self.pod_tree.pack(side="left", fill="x", expand=True)
        pod_scroll = ttk.Scrollbar(pods, orient="vertical", command=self.pod_tree.yview)
        pod_scroll.pack(side="right", fill="y")
        self.pod_tree.configure(yscrollcommand=pod_scroll.set)
        pod_buttons = tk.Frame(pods, bg=C["panel"])
        pod_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(pod_buttons, text=t('Остановить'),
                   command=lambda: self.pod_action("stop")).pack(side="left")
        ttk.Button(pod_buttons, text=t('Возобновить'),
                   command=lambda: self.pod_action("start")).pack(side="left", padx=8)
        ttk.Button(pod_buttons, text=t('Удалить ресурс…'), style="Danger.TButton",
                   command=self.terminate_pod).pack(side="left", padx=8)

        # Cloud training job queue
        jobs = card(self, t('Очередь облачных заданий обучения'))
        jobs.pack(fill="x", padx=24, pady=(0, 12))
        job_form = tk.Frame(jobs, bg=C["panel"])
        job_form.pack(fill="x")
        tk.Label(job_form, text=t('Название'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        self.job_name_var = tk.StringVar(value="train-run")
        tk.Entry(job_form, textvariable=self.job_name_var, width=18, bd=1,
                 relief="solid", font=F_BASE).pack(side="left", padx=(0, 10))
        tk.Label(job_form, text=t('Команда'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        self.job_cmd_var = tk.StringVar(value="python train.py")
        tk.Entry(job_form, textvariable=self.job_cmd_var, width=36, bd=1,
                 relief="solid", font=F_MONO).pack(side="left", padx=(0, 10),
                                                   fill="x", expand=True)
        ttk.Button(job_form, text=t('В очередь'),
                   command=self.add_cloud_job).pack(side="left")

        job_columns = ("status", "name", "command", "pod")
        self.job_tree = ttk.Treeview(jobs, columns=job_columns, show="headings",
                                     height=4)
        for col, title, width in [
            ("status", t('Статус'), 110), ("name", t('Название'), 180),
            ("command", t('Команда'), 320), ("pod", "Pod", 160),
        ]:
            self.job_tree.heading(col, text=title)
            self.job_tree.column(col, width=width, anchor="w")
        self.job_tree.pack(side="left", fill="x", expand=True, pady=(6, 0))
        job_scroll = ttk.Scrollbar(jobs, orient="vertical",
                                   command=self.job_tree.yview)
        job_scroll.pack(side="right", fill="y", pady=(6, 0))
        self.job_tree.configure(yscrollcommand=job_scroll.set)
        job_buttons = tk.Frame(jobs, bg=C["panel"])
        job_buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(job_buttons, text=t('Обновить очередь'),
                   command=self.refresh_jobs).pack(side="left")
        ttk.Button(job_buttons, text=t('Отправить в RunPod…'),
                   command=self.submit_selected_job).pack(side="left", padx=8)
        ttk.Button(job_buttons, text=t('Отменить'), style="Danger.TButton",
                   command=self.cancel_selected_job).pack(side="left")
        ttk.Button(job_buttons, text=t('Colab'),
                   command=self.export_selected_job_to_colab).pack(
            side="left", padx=8)
        self.refresh_jobs()

        self.gpu_notes_var = tk.StringVar(
            value=t('Подключите ключ RunPod и обновите каталог. Внешнее обучение моделей запускается отдельно на странице «Обучение».'))
        tk.Label(self, textvariable=self.gpu_notes_var, bg=C["bg"], fg=C["muted"],
                 font=F_SMALL, wraplength=900, justify="left").pack(
            anchor="w", padx=24, pady=(0, 14))

    # -------------------------------------------------------------- helpers
    def _secret_status(self, name: str) -> str:
        try:
            return t('Ключ сохранён') if self.app.secrets.get(name) else t('Ключ не сохранён')
        except Exception:
            return t('Хранилище ключей недоступно')

    # ------------------------------------------------------- cloud job queue
    def refresh_jobs(self):
        from .cloud_queue import CloudJobQueue

        queue = CloudJobQueue(self.app.model_registry().library_dir)
        self.job_tree.delete(*self.job_tree.get_children())
        self._jobs = {}
        for job in queue.list():
            iid = self.job_tree.insert("", "end", values=(
                job.status, job.name, job.command[:60], job.pod_id or "—"))
            self._jobs[iid] = job

    def add_cloud_job(self):
        from .cloud_queue import CloudJob, CloudJobQueue

        try:
            job = CloudJob(name=self.job_name_var.get().strip(),
                           command=self.job_cmd_var.get().strip())
            CloudJobQueue(self.app.model_registry().library_dir).add(job)
        except Exception as exc:
            messagebox.showerror(t('Облачные задания'), str(exc), parent=self)
            return
        self.refresh_jobs()
        self.app.activity.log("cloud", t('Задание добавлено в очередь: {v1}').format(v1=job.name))

    def _selected_job(self):
        selection = self.job_tree.selection()
        return self._jobs.get(selection[0]) if selection else None

    def submit_selected_job(self):
        from .cloud_queue import CloudJobQueue

        job = self._selected_job()
        if job is None:
            messagebox.showinfo(t('Облачные задания'), t('Выберите задание.'),
                                parent=self)
            return
        if not messagebox.askyesno(
            "RunPod",
            t('Отправить «{v1}» в RunPod? Будет создан платный GPU-ресурс.\nЛимит цены и ключ задаются в секции RunPod API.').format(v1=job.name), parent=self):
            return
        try:
            key = self.app.secrets.get("runpod_api_key")
        except RuntimeError as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)
            return
        from .cloud_gpu import RunPodClient

        queue = CloudJobQueue(self.app.model_registry().library_dir)
        updated = queue.submit(job.id, RunPodClient(key))
        self.refresh_jobs()
        self.app.activity.log("cloud", t('Отправка задания: {v1}').format(v1=updated.line()))
        if updated.error:
            messagebox.showerror(t('Облачные задания'), updated.error, parent=self)
        else:
            messagebox.showinfo(t('Облачные задания'),
                                t('Создан pod: {v1}').format(v1=updated.pod_id), parent=self)

    def cancel_selected_job(self):
        from .cloud_queue import CloudJobQueue

        job = self._selected_job()
        if job is None:
            messagebox.showinfo(t('Облачные задания'), t('Выберите задание.'),
                                parent=self)
            return
        try:
            CloudJobQueue(self.app.model_registry().library_dir).cancel(job.id)
        except Exception as exc:
            messagebox.showerror(t('Облачные задания'), str(exc), parent=self)
            return
        self.refresh_jobs()

    def export_selected_job_to_colab(self):
        from .colab_export import (ColabExportError, default_notebook_name,
                                   save_notebook)

        job = self._selected_job()
        if job is None:
            messagebox.showinfo(t('Облачные задания'), t('Выберите задание.'),
                                parent=self)
            return
        out_dir = self.app.model_registry().library_dir / "exports"
        try:
            file = save_notebook(job, out_dir / default_notebook_name(job))
        except ColabExportError as exc:
            messagebox.showerror(t('Облачные задания'), str(exc), parent=self)
            return
        self.app.set_status(t('Ноутбук сохранён: ') + str(file))

    def _persist_gpu_settings(self):
        try:
            budget = float(self.gpu_budget_var.get())
            disk = int(self.gpu_disk_var.get())
            if budget != budget or budget in (float("inf"), float("-inf")) or budget <= 0:
                raise ValueError(t('Цена в час должна быть положительной.'))
            if not 10 <= disk <= 1000:
                raise ValueError(t('Контейнерный диск должен быть 10–1000 GB.'))
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
            messagebox.showinfo("RunPod", t('Введите API-ключ для сохранения.'), parent=self)
            return
        try:
            self.app.secrets.set("runpod_api_key", key)
            self.runpod_key_var.set("")
            self.runpod_secret_status.set(self._secret_status("runpod_api_key"))
            messagebox.showinfo("RunPod", t('Ключ сохранён в системном хранилище.'),
                                parent=self)
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)

    def refresh_gpu_catalog(self):
        try:
            client = self.app.runpod_client()
            self._persist_gpu_settings()
            cloud = self.cloud_var.get().upper()
        except Exception as exc:
            messagebox.showerror(t('Внешние GPU'), str(exc), parent=self)
            return
        self.app.start_async(t('Загрузка каталога GPU'),
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
                values.append(t('{cloud_name}: ${v2:.3f}/ч').format(cloud_name=cloud_name, v2=float(value)))
        return " · ".join(values) or t('цена не получена')

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
        self.gpu_notes_var.set(t('GPU в каталоге: {v1}. Выберите GPU для расчёта.').format(v1=len(items)))

    def refresh_pods(self):
        try:
            client = self.app.runpod_client()
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)
            return
        self.app.start_async(t('Загрузка ресурсов RunPod'),
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
        self.gpu_notes_var.set(t('Ресурсов в аккаунте: {v1}.').format(v1=len(items)))

    def create_gpu_pod(self):
        selected = self.gpu_tree.selection()
        if not selected:
            messagebox.showinfo(t('Внешние GPU'), t('Сначала выберите GPU в каталоге.'),
                                parent=self)
            return
        gpu = self._gpu_rows.get(selected[0])
        if not gpu or not gpu.get("id"):
            messagebox.showerror(t('Внешние GPU'), t('У выбранной записи нет GPU ID.'),
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
            messagebox.showerror(t('Проверка цены'), str(exc), parent=self)
            return

        confirmation = (
            t('GPU: {v1}\nТариф GPU: ${v3:.4f} в час\nЛимит тарифа GPU: ${v5:.4f} в час\nКонтейнерный диск: {v7} GB\n\nЭто не общий лимит расходов: хранилище и другие услуги тарифицируются отдельно. Данные на контейнерном диске могут исчезнуть.\n\nСоздать платный ресурс сейчас?').format(v1=plan['gpu_name'], v3=plan['gpu_hourly_usd'], v5=plan['gpu_only_budget_usd'], v7=plan['container_disk_gb'])
        )
        if not messagebox.askyesno(t('Подтверждение расходов'), confirmation, parent=self):
            return
        self.app.start_async(t('Создание платного GPU-ресурса'),
                             lambda: client.create_pod(plan, confirmed=True),
                             self._after_gpu_created)

    def _after_gpu_created(self, pod):
        self.gpu_notes_var.set(
            t('Создан ресурс {v1}. Проверьте статус и расходы.').format(v1=pod.get('id', '')))
        self.refresh_pods()
        messagebox.showinfo(
            t('GPU создан'),
            t('ID: {v1}\nСоздание ресурса не запускает обучение автоматически.').format(v1=pod.get('id', t('не указан'))),
            parent=self,
        )

    def _selected_pod(self):
        selected = self.pod_tree.selection()
        if not selected:
            messagebox.showinfo("GPU", t('Сначала выберите ресурс из списка.'), parent=self)
            return None
        pod = self._pod_rows.get(selected[0])
        if not pod or not pod.get("id"):
            messagebox.showerror("GPU", t('У выбранного ресурса нет ID.'), parent=self)
            return None
        return pod

    def pod_action(self, action: str):
        pod = self._selected_pod()
        if not pod:
            return
        title = t('остановить') if action == "stop" else t('возобновить')
        if not messagebox.askyesno(t('Управление GPU'),
                                   t('Подтвердить действие «{title}» для {v3}?').format(title=title, v3=pod['id']),
                                   parent=self):
            return
        try:
            client = self.app.runpod_client()
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)
            return
        self.app.start_async(t('Действие RunPod: {action}').format(action=action),
                             lambda: client.pod_action(str(pod["id"]), action,
                                                       confirmed=True),
                             lambda _: self.refresh_pods())

    def terminate_pod(self):
        pod = self._selected_pod()
        if not pod:
            return
        if not messagebox.askyesno(
            t('Безвозвратное удаление'),
            t('Удалить GPU-ресурс {v1}? Данные на контейнерном диске могут быть потеряны.').format(v1=pod['id']),
            parent=self,
        ):
            return
        try:
            client = self.app.runpod_client()
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)
            return
        self.app.start_async(t('Удаление GPU-ресурса'),
                             lambda: client.terminate_pod(str(pod["id"]),
                                                          confirmed=True),
                             lambda _: self.refresh_pods())
