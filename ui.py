"""Dashboard UI for the DataMatrix verifier (scene / health / diagnostics)."""
import math
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog

import cv2
import numpy as np
from PIL import Image, ImageTk, ImageDraw, ImageOps

from verifier import (Result, analyze_all, is_good, plain_content,
                      problem_regions, score_of)
from version import VERSION

SEV_COLORS = {
    "critical": "#e53935",
    "warning": "#fb8c00",
    "minor": "#fdd835",
}


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg="#ffffff")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self.win, width=e.width))


class Gauge(tk.Canvas):
    """Classic speedometer-style arc (no center text; score shown above)."""
    def __init__(self, parent, size=210):
        self.size = size
        super().__init__(parent, width=size, height=int(size * 0.62),
                         bg="#ffffff", highlightthickness=0)
        self._value = None
        self._color = None

    def set(self, value, color):
        self._value = value
        self._color = color
        self.delete("all")
        s = self.size
        cx, cy = s / 2, s * 0.82
        r = s * 0.34
        bbox = (cx - r, cy - r, cx + r, cy + r)
        # background arc (bottom open): bottom-left -> top -> bottom-right
        self.create_arc(bbox, start=210, extent=-240, style="arc",
                        outline="#e3e8ee", width=14)
        frac = max(0.0, min(1.0, value / 100.0))
        self.create_arc(bbox, start=210, extent=-240 * frac, style="arc",
                        outline=color, width=14)
        # ticks
        for i in range(0, 11):
            a = math.radians(210 - 240 * i / 10.0)
            x0 = cx + (r - 12) * math.cos(a)
            y0 = cy - (r - 12) * math.sin(a)
            x1 = cx + (r - 4) * math.cos(a)
            y1 = cy - (r - 4) * math.sin(a)
            self.create_line(x0, y0, x1, y1, fill="#cfd8dc", width=2)
        # needle
        a = math.radians(210 - 240 * frac)
        nx = cx + (r - 20) * math.cos(a)
        ny = cy - (r - 20) * math.sin(a)
        self.create_line(cx, cy, nx, ny, fill="#455a64", width=4,
                         capstyle=tk.ROUND)
        self.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill="#455a64", outline="")


class Bar(tk.Canvas):
    def __init__(self, parent, width=170, height=14):
        super().__init__(parent, width=width, height=height,
                         bg="#ffffff", highlightthickness=0)
        self.w, self.h = width, height

    def set(self, fraction, color):
        self.delete("all")
        self.create_rectangle(2, 3, self.w - 2, self.h - 3, fill="#eceff1",
                              outline="#b0bec5")
        frac = max(0.0, min(1.0, fraction))
        self.create_rectangle(2, 3, 2 + (self.w - 4) * frac, self.h - 3,
                              fill=color, outline="")


class VerifierApp:
    def __init__(self, root):
        self.root = root
        root.title(f"DataMatrix Verifier {VERSION}")
        root.geometry("1280x820")
        root.configure(bg="#eef1f5")

        self.result = None
        self.frame_bgr = None
        self.regions = []
        self.capture = None
        self.running = False
        self.busy = False
        self.zoom = 1.0
        self.rotate = 0
        self.channel = "Цвет"
        self.focus_index = None
        self.show_overlay = True
        self.history = []
        self.history_photos = []

        self._style = ttk.Style()
        self._style.theme_use("clam")
        self._style.configure(".", font=("Segoe UI", 10))
        self._style.configure("TFrame", background="#eef1f5")
        self._style.configure("Card.TFrame", background="#ffffff")
        self._style.configure("CardHeader.TLabel", background="#ffffff",
                              foreground="#3f51b5", font=("Segoe UI", 11, "bold"))
        self._style.configure("TNotebook", background="#ffffff",
                              borderwidth=0)
        self._style.configure("TNotebook.Tab", padding=(16, 7),
                              font=("Segoe UI", 10))
        self._style.map("TNotebook.Tab",
                        background=[("selected", "#3f51b5")],
                        foreground=[("selected", "#ffffff")])
        self._style.configure("Accent.TButton", background="#3f51b5",
                              foreground="#ffffff", padding=(14, 6))
        self._style.map("Accent.TButton",
                        background=[("active", "#5c6bc0"), ("pressed", "#303f9f")])
        self._style.configure("Tool.TButton", padding=(10, 5))

        self._build_layout()
        self._set_empty()

    def _card(self, parent, title):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=10)
        header = ttk.Frame(frame, style="Card.TFrame")
        header.pack(fill=tk.X, pady=(0, 8))
        tk.Frame(header, bg="#3f51b5", width=4, height=18).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(header, text=title, style="CardHeader.TLabel").pack(side=tk.LEFT)
        return frame

    # ------------------------------------------------------------- layout

    def _build_layout(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.rowconfigure(2, weight=0)

        toolbar = ttk.Frame(root, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")

        ttk.Button(toolbar, text="Открыть файл...", style="Accent.TButton",
                   command=self.open_file).pack(side=tk.LEFT)
        self.cam_btn = ttk.Button(toolbar, text="Камера: пуск", style="Tool.TButton",
                                  command=self.toggle_camera)
        self.cam_btn.pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Захват кадра", style="Tool.TButton",
                   command=self.capture_now).pack(side=tk.LEFT)
        ttk.Label(toolbar, text="  Калибровка (мкм/px):").pack(side=tk.LEFT)
        self.micron_var = tk.StringVar(value="10")
        ttk.Entry(toolbar, textvariable=self.micron_var, width=6).pack(side=tk.LEFT, padx=(2, 8))

        self.file_var = tk.StringVar(value="—")
        ttk.Label(toolbar, textvariable=self.file_var,
                  foreground="#546e7a").pack(side=tk.LEFT)
        self.valid_var = tk.StringVar(value="Ожидание")
        self.valid_lbl = tk.Label(toolbar, textvariable=self.valid_var,
                                  font=("Segoe UI", 12, "bold"),
                                  fg="#78909c", bg=root.cget("background"))
        self.valid_lbl.pack(side=tk.RIGHT)

        body = ttk.Frame(root, padding=8)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=0)
        body.columnconfigure(2, weight=2)
        body.rowconfigure(0, weight=1)

        self._build_scene(body)
        self._build_health(body)
        self._build_diag(body)
        self._build_bottom(root)

    def _build_scene(self, body):
        scene = self._card(body, "Сцена")
        scene.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.scene_canvas = tk.Canvas(scene, bg="#e8edf2", highlightthickness=0)
        self.scene_canvas.pack(fill=tk.BOTH, expand=True)

        ctrl = ttk.Frame(scene, style="Card.TFrame")
        ctrl.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(ctrl, text="−", width=3, style="Tool.TButton",
                   command=lambda: self._set_zoom(-0.25)).pack(side=tk.LEFT)
        ttk.Button(ctrl, text="+", width=3, style="Tool.TButton",
                   command=lambda: self._set_zoom(0.25)).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="⟳ Повернуть", style="Tool.TButton",
                   command=self._rotate).pack(side=tk.LEFT, padx=4)
        self.channel_var = tk.StringVar(value="Цвет")
        cmb = ttk.Combobox(ctrl, textvariable=self.channel_var, state="readonly", width=8,
                           values=("Цвет", "Серый", "ИК"))
        cmb.pack(side=tk.LEFT, padx=4)
        cmb.bind("<<ComboboxSelected>>", lambda e: self._set_channel())

        self.overlay_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="Подсветка", variable=self.overlay_var,
                        command=self._toggle_overlay).pack(side=tk.LEFT, padx=(8, 0))

    def _set_channel(self):
        self.channel = self.channel_var.get()
        self._refresh_scene()

    def _toggle_overlay(self):
        self.show_overlay = self.overlay_var.get()
        self._refresh_scene()

    def _build_health(self, body):
        health = self._card(body, "Качество и статус")
        health.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        health.columnconfigure(0, weight=1)

        self.score_var = tk.StringVar(value="—")
        self.grade_var = tk.StringVar(value="—")
        score_frame = ttk.Frame(health, style="Card.TFrame")
        score_frame.pack(pady=(2, 0))
        self.score_lbl = tk.Label(score_frame, textvariable=self.score_var,
                                  font=("Segoe UI", 34, "bold"), bg="#ffffff",
                                  fg="#78909c")
        self.score_lbl.pack(side=tk.LEFT)
        tk.Label(score_frame, text=" из 100", font=("Segoe UI", 12),
                 bg="#ffffff", fg="#90a4ae").pack(side=tk.LEFT, anchor="s", pady=(0, 8))
        self.grade_lbl = tk.Label(health, textvariable=self.grade_var,
                                  font=("Segoe UI", 11, "bold"), bg="#ffffff",
                                  fg="#78909c")
        self.grade_lbl.pack(pady=(0, 2))

        self.gauge = Gauge(health)
        self.gauge.pack(pady=(0, 2))

        self.verdict_var = tk.StringVar(value="—")
        self.verdict_lbl = tk.Label(health, textvariable=self.verdict_var,
                                    font=("Segoe UI", 24, "bold"),
                                    bg="#ffffff", fg="#78909c")
        self.verdict_lbl.pack(pady=(4, 0))

        self.reason_var = tk.StringVar(value="Ожидание изображения")
        tk.Label(health, textvariable=self.reason_var, wraplength=230,
                 justify=tk.CENTER, fg="#90a4ae", bg="#ffffff").pack(pady=(2, 6))

        sep = ttk.Separator(health, orient="horizontal")
        sep.pack(fill=tk.X, pady=8)

        tk.Label(health, text="КЛЮЧЕВЫЕ ПАРАМЕТРЫ", font=("Segoe UI", 9, "bold"),
                 fg="#78909c", bg="#ffffff").pack(anchor="w", pady=(0, 4))

        self.param_rows = {}
        for name in ("Контраст символа", "Неоднородность сетки",
                     "Размерность печати", "Тактовые модули"):
            row = ttk.Frame(health, style="Card.TFrame")
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=name, width=20, anchor="w",
                     bg="#ffffff", fg="#455a64", font=("Segoe UI", 9)).pack(side=tk.LEFT)
            bar = Bar(row)
            bar.pack(side=tk.LEFT)
            val = tk.Label(row, text="—", width=4, anchor="e",
                           bg="#ffffff", fg="#455a64")
            val.pack(side=tk.LEFT)
            self.param_rows[name] = (bar, val)

    def _build_diag(self, body):
        diag = self._card(body, "Диагностика и данные")
        diag.grid(row=0, column=2, sticky="nsew")

        self.notebook = ttk.Notebook(diag)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Defects tab
        self.defects_frame = ScrollableFrame(self.notebook)
        self.notebook.add(self.defects_frame, text=" Дефекты ")
        self.defect_cards = []

        # Data tab
        data = ttk.Frame(self.notebook)
        self.notebook.add(data, text=" Данные ")
        self.data_tab = data
        self.results = []
        self.result_index = 0
        self.code_selector = ttk.Combobox(data, state="readonly", width=26)
        self.code_selector.pack(anchor="w", pady=(2, 4))
        self.code_selector.bind("<<ComboboxSelected>>", lambda e: self._on_select_code())
        self.content_var = tk.StringVar(value="—")
        self.content_raw_var = tk.StringVar(value="")
        content_frame = ttk.Frame(data)
        content_frame.pack(fill=tk.X, padx=4, pady=(4, 2))
        tk.Label(content_frame, text="Содержимое:", font=("Segoe UI", 9, "bold"),
                 fg="#455a64", bg="#eef1f5").pack(anchor="w")
        self.content_lbl = tk.Label(content_frame, textvariable=self.content_var,
                                    font=("Consolas", 10), wraplength=350,
                                    justify=tk.LEFT, anchor="nw", bg="#f5f7fa",
                                    relief="solid", bd=1, padx=6, pady=4)
        self.content_lbl.pack(fill=tk.X)
        self.data_cards = []
        self.copy_all_btn = ttk.Button(data, text="Скопировать содержимое",
                                       command=self._copy_all)
        self.copy_all_btn.pack(anchor="w", pady=(4, 6))
        self.chips_frame = ttk.Frame(data)
        self.chips_frame.pack(fill=tk.X, padx=4, pady=4)

        # Report tab
        report = ttk.Frame(self.notebook)
        self.notebook.add(report, text=" Отчет ")
        self.report_lbl = tk.Label(report, text="", justify=tk.LEFT, anchor="nw",
                                   font=("Consolas", 9))
        self.report_lbl.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        ttk.Button(report, text="Сформировать PDF отчёт",
                   command=self._make_pdf).pack(side=tk.BOTTOM, pady=8)

    def _build_bottom(self, root):
        bottom = ttk.Frame(root, padding=(8, 4))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)

        tk.Label(bottom, text="История проверок:", font=("Segoe UI", 9, "bold"),
                 bg="#eef1f5").pack(side=tk.LEFT, padx=(0, 8))

        self.history_frame = ttk.Frame(bottom)
        self.history_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.history_status = tk.StringVar(value="Проанализировано: 0 кодов")
        tk.Label(bottom, textvariable=self.history_status, font=("Segoe UI", 9),
                 fg="#455a64", bg="#eef1f5").pack(side=tk.RIGHT)

    # ------------------------------------------------------------ io

    def open_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff")])
        if path:
            bgr = cv2.imread(path, cv2.IMREAD_COLOR)
            if bgr is None:
                self._set_verdict("Ошибка чтения файла", "#c62828", "Не удалось открыть файл")
                return
            self.file_var.set(os.path.basename(path))
            self.frame_bgr = bgr
            self._start_analysis()

    def toggle_camera(self):
        if self.capture is None:
            self.capture = cv2.VideoCapture(0)
            if not self.capture.isOpened():
                self._set_verdict("Камера недоступна", "#c62828", "Подключите камеру")
                self.capture = None
                return
            self.running = True
            self.cam_btn.configure(text="Камера: стоп")
            self._camera_loop()
        else:
            self.running = False
            self.capture.release()
            self.capture = None
            self.cam_btn.configure(text="Камера: пуск")

    def capture_now(self):
        if self.capture is not None and self.capture.isOpened():
            ok, frame = self.capture.read()
            if ok:
                self.frame_bgr = frame
                self._start_analysis()

    def _camera_loop(self):
        if not self.running:
            return
        ok, frame = self.capture.read()
        if ok:
            self.frame_bgr = frame
            self._start_analysis()
        self.root.after(200, self._camera_loop)

    def close(self):
        self.running = False
        if self.capture is not None:
            self.capture.release()

    # ----------------------------------------------------------- analyze

    def _start_analysis(self):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._analyze, daemon=True).start()

    def _analyze(self):
        try:
            um = float(self.micron_var.get())
        except ValueError:
            um = 10.0
        try:
            results = analyze_all(self.frame_bgr, um_per_px=um)
        finally:
            self.busy = False
        if not results:
            r = Result()
            r.error = "Код не найден"
            results = [r]
        self.results = results
        self.result_index = 0
        self._set_result(0)
        self.root.after(0, self._render)

    def _set_result(self, idx):
        self.result_index = idx
        self.result = self.results[idx]
        self.regions = problem_regions(self.result)
        self.focus_index = None

    def _on_select_code(self):
        idx = self.code_selector.current()
        if 0 <= idx < len(self.results):
            self._set_result(idx)
            self._render(update_history=False)

    def _update_code_selector(self):
        names = []
        for i, r in enumerate(self.results):
            if r.error or r.symbol is None:
                names.append(f"Код {i + 1}: не найден")
            else:
                g = f"{r.min_grade:.1f}".replace(".", ",")
                names.append(f"Код {i + 1}: {g}/4"
                             + (f" ({len(r.elements)} AI)" if r.elements else ""))
        self.code_selector["values"] = names
        if names:
            self.code_selector.current(self.result_index)

    # ----------------------------------------------------------- render

    def _render(self, update_history=True):
        res = self.result
        self._update_code_selector()
        self._refresh_scene()

        if res.error or res.symbol is None:
            self._set_verdict("БРАК", "#c62828", res.error or "Код не найден")
            self._render_health(None)
            self._render_defects([])
            self._render_data([])
            self._render_report(res)
            if update_history:
                self._add_history(res)
            return

        score, color = score_of(res)
        good = is_good(res)
        self.valid_var.set("Валидация: " + ("ОК" if good else "БРАК"))
        self.valid_lbl.configure(fg="#2e7d32" if good else "#c62828")
        verdict = "ГОДЕН" if good else "БРАК"
        reason = self._first_fail_reason(res)
        self._set_verdict(verdict, "#2e7d32" if good else "#c62828", reason)
        self._render_health(res)
        self._render_defects(res)
        self._render_data(res)
        self._render_report(res)
        if update_history:
            self._add_history(res)

    def _set_verdict(self, text, color, reason):
        self.verdict_var.set(text)
        self.verdict_lbl.configure(fg=color)
        self.reason_var.set(reason)

    def _first_fail_reason(self, res):
        for p in res.params:
            if not p.passed:
                return f"{p.name}: {p.value}"
        return "Все параметры в норме"

    def _render_health(self, res):
        if res is None:
            self.score_var.set("0")
            self.grade_var.set("—")
            self.gauge.set(0, "#c62828")
            for name in self.param_rows:
                bar, val = self.param_rows[name]
                bar.set(0, "#eceff1")
                val.configure(text="—")
            return
        score, color = score_of(res)
        grade_str = f"{res.min_grade:.1f}".replace(".", ",")
        self.score_var.set(str(score))
        self.score_lbl.configure(fg=color)
        good = is_good(res)
        txt_color = "#2e7d32" if good else "#c62828"
        self.grade_var.set(f"Грейд {grade_str} / {res.symbol.rows}x{res.symbol.cols}")
        self.grade_lbl.configure(fg=txt_color)
        self.gauge.set(score, color)
        mapping = {"Контраст символа": "Контраст символа",
                   "Неоднородность сетки": "Неоднородность сетки",
                   "Размерность печати": "Размерность печати X",
                   "Тактовые модули": "Последовательность тактовых модулей"}
        for name in self.param_rows:
            key = mapping[name]
            grade = 0
            for p in res.params:
                if p.name == key:
                    grade = p.grade
                    break
            bar, val = self.param_rows[name]
            color = "#2e7d32" if grade >= 4 else ("#f9a825" if grade >= 2 else "#c62828")
            bar.set(grade / 4.0, color)
            val.configure(text=str(grade))

    def _render_defects(self, res):
        for card in self.defect_cards:
            card.destroy()
        self.defect_cards = []
        if not res or res.error:
            tk.Label(self.defects_frame.inner, text="Нет данных",
                     fg="#90a4ae").pack(pady=20)
            return
        cards = 0
        for p in res.params:
            if p.passed:
                continue
            sev = "critical" if p.grade <= 1 else ("warning" if p.grade <= 3 else "minor")
            self._add_defect_card(p, sev)
            cards += 1
        if cards == 0:
            tk.Label(self.defects_frame.inner,
                     text="Все параметры в норме ✅", fg="#2e7d32").pack(pady=20)

    def _add_defect_card(self, p, sev):
        color = SEV_COLORS[sev]
        icon = "🚫" if sev == "critical" else ("⚠️" if sev == "warning" else "🟡")
        card = ttk.Frame(self.defects_frame.inner, padding=4)
        card.pack(fill=tk.X, pady=3)
        tk.Frame(card, bg=color, width=5).pack(side=tk.LEFT, fill=tk.Y)
        body = ttk.Frame(card)
        body.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        lbl = tk.Label(body, text=f"{icon} {p.name}: {p.value}",
                       font=("Segoe UI", 10), bg="#ffffff",
                       anchor="w", justify=tk.LEFT)
        lbl.pack(anchor="w")
        rec = self._recommendation(p)
        if rec:
            tk.Label(body, text=rec, fg="#90a4ae", font=("Segoe UI", 8),
                     bg="#ffffff", anchor="w").pack(anchor="w")
        ttk.Button(card, text="🔍", width=3, style="Tool.TButton",
                   command=lambda: self._focus_on(p.name)).pack(side=tk.RIGHT, padx=4)
        self.defect_cards.append(card)

    def _recommendation(self, p):
        name = p.name
        if "Размерность печати" in name:
            return "Рекомендация: отрегулировать количество чернил / давление печати."
        if "шаблона" in name or "тактовых" in name:
            return "Рекомендация: проверить чистоту формы и материала."
        if "Контраст" in name:
            return "Рекомендация: улучшить контраст краски и подложки."
        if "Неоднородность" in name:
            return "Рекомендация: проверить равномерность освещения и сетки."
        if "Декодирование" in name:
            return "Код не читается — требуется перепечатка."
        if "Запас коррекции" in name:
            return "Рекомендация: снизить повреждения модулей."
        return "Рекомендация: проверить технологический процесс нанесения."

    def _focus_on(self, param_name):
        if self.result is None or self.result.corner_points is None:
            return
        self.focus_index = None
        for i, reg in enumerate(self.regions):
            # map param name -> region label roughly
            label_map = {
                "Размерность печати X": "Размерность печати",
                "Левая часть шаблона \"L\"": "Левая часть шаблона L",
                "Нижняя часть шаблона \"L\"": "Нижняя часть шаблона L",
                "Последовательность тактовых модулей": "Тактовые модули",
                "Контраст символа": "Контраст",
                "Неоднородность освещения": "Неравномерность освещения",
                "Неоднородность сетки": "Неоднородность сетки",
            }
            if label_map.get(param_name) == reg["label"]:
                self.focus_index = i
                break
        self.zoom = 1.6
        self._refresh_scene()

    def _render_data(self, res):
        for card in self.data_cards:
            card.destroy()
        self.data_cards = []
        for w in self.chips_frame.winfo_children():
            w.destroy()
        if not res:
            return
        raw = plain_content(res)
        self.content_raw_var.set(raw)
        self.content_var.set(raw.replace("\x1d", "[GS]") if raw else "—")
        self.copy_all_btn.configure(
            state=tk.NORMAL if res.content else tk.DISABLED,
            text="Скопировать содержимое" + (f" ({len(res.elements)} AI)"
                 if res.elements else ""))
        if res.elements:
            for el in res.elements:
                chip = ttk.Frame(self.chips_frame, relief="solid", padding=4)
                chip.pack(side=tk.LEFT, padx=3, pady=3)
                tk.Label(chip, text=el.display_name(), font=("Segoe UI", 9, "bold"),
                         bg="#ffffff").pack(anchor="w")
                tk.Label(chip, text=el.value, font=("Consolas", 9),
                         bg="#ffffff").pack(anchor="w")
                ttk.Button(chip, text="Копировать",
                           command=lambda v=el.value: self._copy(v)).pack(pady=(2, 0))
                self.data_cards.append(chip)

    def _tab(self, title):
        for t in self.notebook.tabs():
            if title in self.notebook.tab(t, "text"):
                return t
        return self.notebook.tabs()[0]

    def _render_report(self, res):
        if not res or res.error:
            self.report_lbl.configure(text="Нет данных для отчёта.")
            return
        lines = []
        lines.append(f"Класс: {res.overall_class}")
        lines.append(f"Валидация: {res.validation}")
        lines.append(f"Содержимое: {res.content or '(не декодировано)'}")
        lines.append(f"Размер символа: {res.symbol.rows}x{res.symbol.cols}")
        lines.append(f"X-размерность: {res.x_dim_um:.0f} мкм | Y: {res.y_dim_um:.0f} мкм")
        lines.append(f"Апертура: {res.aperture_um} мкм")
        lines.append("")
        lines.append("Параметры ISO 15415:")
        for p in res.params:
            mark = "OK" if p.passed else "FAIL"
            lines.append(f"  [{mark}] {p.name}: {p.display}")
        lines.append("")
        lines.append("Данные GS1:")
        for el in res.elements:
            lines.append(f"  {el.display_name()} = {el.value}")
        self.report_lbl.configure(text="\n".join(lines))

    def _make_pdf(self):
        if self.result is None or self.result.error:
            self._set_verdict("Нет данных", "#c62828", "Сначала проанализируйте код")
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                            filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        from report import build_pdf
        build_pdf(self.result, self.frame_bgr, path)
        self._set_verdict("PDF сохранён", "#2e7d32", os.path.basename(path))

    def _copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _copy_all(self):
        self._copy(self.content_raw_var.get())

    # ---------------------------------------------------------- history

    def _add_history(self, res):
        if self.frame_bgr is None:
            return
        bgr = self.frame_bgr
        if self.history and self.history[-1].get("frame_id") == id(bgr):
            return
        good = is_good(res)
        thumb = self._make_thumbnail(bgr, res, good)
        entry = {"res": res, "frame": bgr, "good": good, "photo": thumb,
                 "frame_id": id(bgr)}
        self.history.append(entry)
        if len(self.history) > 12:
            self.history.pop(0)
        self._render_history()

    def _make_thumbnail(self, bgr, res, good):
        disp = bgr.copy()
        if res.corner_points is not None and res.symbol is not None:
            pts = res.corner_points.astype(np.int32)
            cv2.polylines(disp, [pts], True, (0, 255, 0), 3)
        rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
        im = Image.fromarray(rgb)
        im.thumbnail((110, 70))
        return ImageTk.PhotoImage(im)

    def _render_history(self):
        for w in self.history_frame.winfo_children():
            w.destroy()
        n_ok = sum(1 for e in self.history if e["good"])
        self.history_status.set(
            f"Проанализировано: {len(self.history)} кодов. "
            f"{n_ok} - OK, {len(self.history) - n_ok} - Брак")
        for i, e in enumerate(self.history):
            color = "#2e7d32" if e["good"] else "#c62828"
            lbl = tk.Label(self.history_frame, image=e["photo"], cursor="hand2",
                           highlightbackground=color, highlightthickness=2,
                           bd=0)
            lbl.pack(side=tk.LEFT, padx=3)
            lbl.bind("<Button-1>", lambda ev, idx=i: self._show_history(idx))

    def _show_history(self, idx):
        e = self.history[idx]
        self.frame_bgr = e["frame"]
        self.results = [e["res"]]
        self.result_index = 0
        self.result = e["res"]
        self.regions = problem_regions(e["res"])
        self.zoom = 1.0
        self.focus_index = None
        self._render()

    # ----------------------------------------------------------- scene

    def _set_zoom(self, delta):
        self.zoom = max(0.5, min(4.0, self.zoom + delta))
        self._refresh_scene()

    def _rotate(self):
        self.rotate = (self.rotate + 1) % 4
        self._refresh_scene()

    def _refresh_scene(self):
        if self.frame_bgr is None:
            return
        try:
            base = self._build_base_image()
        except Exception:
            return
        self.scene_canvas.delete("all")
        self._scene_photo = ImageTk.PhotoImage(base)
        self.scene_canvas.create_image(
            self.scene_canvas.winfo_width() // 2 or 300,
            self.scene_canvas.winfo_height() // 2 or 220,
            image=self._scene_photo)

    def _build_base_image(self):
        """Build the display PIL image (channel, rotation, heatmap, zoom)."""
        bgr = self.frame_bgr
        h, w = bgr.shape[:2]

        if self.channel == "Цвет":
            arr = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        elif self.channel == "Серый":
            g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            arr = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
        else:  # ИК: контрастно-растянутый серый
            g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            g = cv2.equalizeHist(g)
            arr = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)

        # rotation
        if self.rotate:
            arr = np.rot90(arr, self.rotate)
        rh, rw = arr.shape[:2]

        cw = max(self.scene_canvas.winfo_width(), 200)
        chh = max(self.scene_canvas.winfo_height(), 150)
        scale = min(cw / rw, chh / rh) * self.zoom
        tw = max(1, int(rw * scale))
        th = max(1, int(rh * scale))
        img = Image.fromarray(arr).resize((tw, th), Image.LANCZOS)

        # crop for zoom > 1
        crop_x = crop_y = 0
        if tw > cw or th > chh:
            cx = int((tw - cw) / 2)
            cy = int((th - chh) / 2)
            crop_x, crop_y = cx, cy
            img = img.crop((cx, cy, min(tw, cx + cw), min(th, cy + chh)))

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)

        def map_poly(poly):
            pts = []
            for x, y in poly:
                px, py = self._map_to_display(x, y, scale, crop_x, crop_y)
                pts.append((px, py))
            return pts

        if self.show_overlay:
            for ri, r in enumerate(self.results):
                if r.corner_points is None:
                    continue
                pts = r.corner_points.astype(np.float32)
                ring = map_poly(pts)
                ring.append(ring[0])
                if ri == self.result_index:
                    d.line(ring, fill=(46, 125, 50, 255), width=3)
                else:
                    d.line(ring, fill=(144, 164, 174, 255), width=2)

            for i, reg in enumerate(self.regions):
                poly = map_poly(reg["poly"])
                color = SEV_COLORS[reg["severity"]]
                rgb = tuple(int(color.lstrip("#")[k:k + 2], 16) for k in (0, 2, 4))
                alpha = 150
                if self.focus_index == i:
                    alpha = 230
                    d.line(poly + [poly[0]], fill=rgb + (255,), width=4)
                d.polygon(poly, fill=rgb + (alpha,))
                d.line(poly + [poly[0]], fill=rgb + (220,), width=2)

        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        return img

    def _map_to_display(self, x, y, scale, crop_x, crop_y):
        """Map an original image point to display coordinates."""
        h, w = self.frame_bgr.shape[:2]
        if self.rotate == 0:
            pass
        elif self.rotate == 1:  # np.rot90 ccw
            x, y = y, w - 1 - x
        elif self.rotate == 2:
            x, y = w - 1 - x, h - 1 - y
        elif self.rotate == 3:
            x, y = h - 1 - y, x
        return x * scale - crop_x, y * scale - crop_y

    def _set_empty(self):
        self._set_verdict("—", "#607d8b", "Откройте файл или включите камеру")


def main():
    root = tk.Tk()
    app = VerifierApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.close(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()