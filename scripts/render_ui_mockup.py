#!/usr/bin/env python3
"""Render high-fidelity UI mockups from the app's real design tokens.

Real screenshots need a desktop session; this script draws the actual layout,
palette (``theme.C``) and sample content so the design can be reviewed and
attached to documentation. Output: docs/ui-chat.png, docs/ui-dashboard.png.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from alterego_training_hub.theme import C  # noqa: E402

S = 1.5
VW, VH = 1320, 840
W, H = int(VW * S), int(VH * S)
SIDE = 230          # sidebar width — page content lives to the right of it
PX0 = SIDE + 24     # page margin left
PX1 = VW - 24       # page margin right

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
_REG = str(FONT_DIR / "DejaVuSans.ttf")
_BOLD = str(FONT_DIR / "DejaVuSans-Bold.ttf")
_MONO = str(FONT_DIR / "DejaVuSansMono.ttf")
_fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    path = _MONO if mono else (_BOLD if bold else _REG)
    key = (path, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(path, int(size * S * 0.92))
    return _fonts[key]


class Canvas:
    def __init__(self):
        self.image = Image.new("RGB", (W, H), C["bg"])
        self.draw = ImageDraw.Draw(self.image)

    def rect(self, x, y, w, h, fill, outline=None, radius=0, width=1):
        box = [x * S, y * S, (x + w) * S, (y + h) * S]
        if radius:
            self.draw.rounded_rectangle(box, radius=radius * S, fill=fill,
                                        outline=outline, width=int(width * S))
        else:
            self.draw.rectangle(box, fill=fill, outline=outline, width=int(width * S))

    def text(self, x, y, value, size=10, bold=False, mono=False, fill=None, anchor="la"):
        self.draw.text((x * S, y * S), value, font=font(size, bold, mono),
                       fill=fill or C["text"], anchor=anchor)

    def poly(self, points, fill, width=2):
        self.draw.line([(x * S, y * S) for x, y in points], fill=fill,
                       width=int(width * S), joint="curve")

    def save(self, name: str) -> Path:
        docs = ROOT / "docs"
        docs.mkdir(exist_ok=True)
        path = docs / name
        self.image.save(path, "PNG", optimize=True)
        return path


NAV_ITEMS = [
    "Чат с наставником",
    "Рабочая папка",
    "Каталог моделей",
    "Модель и прогресс",
    "Обучение",
    "Внешние GPU",
    "Настройки",
]


def draw_shell(c: Canvas, active: int, status: str, badge: str):
    c.rect(0, 0, VW, VH, C["bg"])
    c.rect(0, 0, SIDE, VH, C["sidebar"])
    c.text(24, 30, "AlterEgo", 17, bold=True, fill="#ffffff")
    c.text(24, 58, "Training Hub", 12, fill=C["sidebar_fg"])
    for idx, label in enumerate(NAV_ITEMS):
        y = 110 + idx * 46
        is_active = idx == active
        if is_active:
            c.rect(0, y, SIDE, 44, C["sidebar_active"])
            c.rect(0, y, 4, 44, C["accent"])
        c.text(30, y + 13, label, 10.5, bold=is_active,
               fill=C["sidebar_fg_active"] if is_active else C["sidebar_fg"])
    c.text(24, VH - 36, "v0.3 · локальный контур", 8.5, fill="#5b6b85")
    c.rect(0, VH - 26, VW, 26, "#e8edf5")
    c.text(12, VH - 19, status, 8.5, fill=C["muted"])
    c.text(VW - 14, VH - 19, badge, 8.5, fill=C["muted"], anchor="ra")


def card(c: Canvas, x, y, w, h, title=None):
    c.rect(x, y, w, h, C["border"], radius=6)
    c.rect(x + 1, y + 1, w - 2, h - 2, C["panel"], radius=6)
    if title:
        c.text(x + 14, y + 10, title, 10.5, bold=True)
    return y + (34 if title else 12)


def render_chat() -> Path:
    c = Canvas()
    draw_shell(c, 0, "Готово: ответ наставника", "папка: alterego-train")
    c.text(PX0, 36, "Чат с наставником", 16, bold=True)
    c.text(PX0, 64, "Диалог, инструменты и правки кода в выбранной рабочей папке. "
                    "Каждое изменение требует вашего подтверждения.", 9.5, fill=C["muted"])

    # Sessions column (page area)
    c.rect(PX0, 100, 190, 540, C["border"], radius=6)
    c.rect(PX0 + 1, 101, 188, 538, C["panel"], radius=6)
    c.text(PX0 + 14, 112, "ДИАЛОГИ", 8.5, bold=True, fill=C["muted"])
    for idx, (name, active) in enumerate([
        ("Почему растёт loss?", True), ("Настройка пайплайна", False),
        ("Экспорт чекпойнтов", False), ("Новый диалог", False),
    ]):
        y = 136 + idx * 34
        if active:
            c.rect(PX0 + 8, y - 4, 174, 30, C["accent"], radius=4)
            c.text(PX0 + 18, y + 3, name, 9.5, bold=True, fill="#ffffff")
        else:
            c.text(PX0 + 18, y + 3, name, 9.5, fill=C["text"])
    c.rect(PX0 + 8, 588, 82, 28, C["panel_alt"], outline=C["border"], radius=4)
    c.text(PX0 + 24, 596, "Новый", 9, fill=C["text"])
    c.rect(PX0 + 98, 588, 82, 28, C["panel_alt"], outline=C["danger"], radius=4)
    c.text(PX0 + 112, 596, "Удалить", 9, fill=C["danger"])

    # Chat column
    cx, cw = 456, 534
    c.rect(cx, 100, cw, 540, C["border"], radius=6)
    c.rect(cx + 1, 101, cw - 2, 538, C["panel"], radius=6)

    c.text(cx + 14, 114, "Вы · 14:02", 8, bold=True, fill=C["muted"])
    c.rect(cx + 90, 128, 420, 52, C["user_bubble"], radius=8)
    c.text(cx + 104, 142, "Почему на 5-й эпохе val_loss начал расти?", 10)
    c.text(cx + 104, 158, "Посмотри лог и код обучения, предложи исправление.", 10)

    c.text(cx + 14, 198, "Наставник · 14:02", 8, bold=True, fill=C["muted"])
    c.rect(cx + 14, 212, 460, 92, C["panel"], outline=C["border"], radius=8)
    c.text(cx + 28, 224, "## Рассуждение", 10, bold=True)
    c.text(cx + 28, 242, "Train loss падает, а val_loss растёт — классическая", 9.8)
    c.text(cx + 28, 258, "картина переобучения. Сначала прочитаю скрипт.", 9.8)
    c.text(cx + 28, 278, "→ read_file: train.py", 9.2, mono=True, fill="#92400e")

    c.rect(cx + 14, 316, 460, 34, C["tool_bubble"], radius=6)
    c.text(cx + 28, 326, '→ read_file: {"ok": true, "path": "train.py"}',
           8.8, mono=True, fill="#78350f")

    c.text(cx + 14, 368, "Наставник · 14:03", 8, bold=True, fill=C["muted"])
    c.rect(cx + 14, 382, 460, 158, C["panel"], outline=C["border"], radius=8)
    c.text(cx + 28, 394, "## Что хорошо", 10, bold=True, fill=C["success"])
    c.text(cx + 28, 412, "• loss на обучении стабильно снижается", 9.8)
    c.text(cx + 28, 428, "• lr-расписание корректно затухает", 9.8)
    c.text(cx + 28, 448, "## Что плохо", 10, bold=True, fill=C["danger"])
    c.text(cx + 28, 466, "• нет dropout/weight decay — переобучение", 9.8)
    c.text(cx + 28, 486, "## Рекомендации", 10, bold=True, fill=C["accent"])
    c.text(cx + 28, 504, "• включить early stopping и аугментации", 9.8)

    c.text(cx + 14, 556, "Быстрые команды:", 8.5, fill=C["muted"])
    for idx, label in enumerate(["Оценка модели", "Прогресс обучения", "Разбор ошибок"]):
        x = cx + 108 + idx * 118
        c.rect(x, 548, 110, 24, C["panel_alt"], outline=C["border"], radius=4)
        c.text(x + 10, 555, label, 8.2, fill=C["text"])
    c.rect(cx + 14, 586, 360, 44, C["panel"], outline=C["border"], radius=4)
    c.text(cx + 26, 600, "Спасибо! А как лучше организовать валидацию?", 9.5,
           fill=C["muted"])
    c.rect(cx + 386, 586, 88, 44, C["accent"], radius=6)
    c.text(cx + 402, 600, "Отправить", 9.5, bold=True, fill="#ffffff")

    # Activity column
    ax = 1002
    c.rect(ax, 100, PX1 - ax, 540, C["border"], radius=6)
    c.rect(ax + 1, 101, PX1 - ax - 2, 538, C["panel"], radius=6)
    c.text(ax + 14, 112, "АКТИВНОСТЬ ИНСТРУМЕНТОВ", 8.2, bold=True, fill=C["muted"])
    rows = [
        ("→ read_file: train.py", C["accent"]),
        ("  [ok] {\"ok\": true, …}", C["success"]),
        ("→ search_files: val_loss", C["accent"]),
        ("  [ok] {\"matches\": 14, …}", C["success"]),
        ("→ run_command: pytest -q", C["accent"]),
        ("  [err] 1 failed, 12 passed", C["danger"]),
        ("наставник формирует ответ", C["muted"]),
    ]
    for idx, (line, color) in enumerate(rows):
        c.text(ax + 14, 138 + idx * 18, line, 8.4, mono=True, fill=color)
    c.text(ax + 14, 300, "Инструменты активны.", 8.4, fill=C["muted"])
    c.text(ax + 14, 316, "Папка: ~/alterego-train", 8.4, fill=C["muted"])
    return c.save("ui-chat.png")


def render_dashboard() -> Path:
    c = Canvas()
    draw_shell(c, 3, "Готово: оценка наставника", "папка: alterego-train")
    c.text(PX0, 36, "Модель и прогресс", 16, bold=True)
    c.text(PX0, 64, "Сводка по выбранной модели: прогресс обучения, оценка "
                    "наставника и журнал действий.", 9.5, fill=C["muted"])

    # Toolbar
    c.text(PX0, 96, "Модель", 10, bold=True)
    c.rect(PX0 + 56, 88, 260, 28, C["panel"], outline=C["border"], radius=4)
    c.text(PX0 + 68, 96, "gpt-mini-v2  ·  local", 9.5, fill=C["text"])
    c.rect(PX0 + 328, 88, 92, 28, C["panel_alt"], outline=C["border"], radius=4)
    c.text(PX0 + 344, 96, "Обновить", 9.2, fill=C["text"])
    c.rect(PX0 + 432, 88, 160, 28, C["accent"], radius=4)
    c.text(PX0 + 448, 96, "Оценка наставника", 9.2, bold=True, fill="#ffffff")
    c.rect(PX0 + 604, 88, 116, 28, C["panel_alt"], outline=C["border"], radius=4)
    c.text(PX0 + 622, 96, "Открыть чат", 9.2, fill=C["text"])

    # Model card
    top = card(c, PX0, 132, 450, 220, "Карточка модели")
    rows = [
        ("Название", "gpt-mini-v2"), ("Тип", "local"),
        ("Путь / URI", "checkpoints/gpt-mini-v2.safetensors"),
        ("API model id", "gpt-mini-v2"),
        ("URL инференса", "https://api.example.test/v1"),
        ("Обновлено", "13.10.2026 14:40"),
        ("Метрики", "val_loss: 1.02, acc: 0.47"),
        ("Заметки", "маленькая LM для экспериментов"),
    ]
    for idx, (label, value) in enumerate(rows):
        y = top + 8 + idx * 20
        c.text(PX0 + 14, y, f"{label}:", 9.2, bold=True, fill=C["muted"])
        c.text(PX0 + 122, y, value, 9.2, fill=C["text"])

    # Progress card
    gx = PX0 + 462
    gw = PX1 - gx
    top = card(c, gx, 132, gw, 220, "Прогресс обучения")
    c.text(gx + 14, top + 6, "Состояние: выполняется", 9.5, bold=True)
    c.text(gx + 14, top + 24, "python scripts/train.py --config base.yaml", 8.6,
           mono=True, fill=C["muted"])
    c.text(gx + 14, top + 42, "эпоха 5/10 · val_loss: 1.02 · acc: 0.47 · "
                              "тренд: val_loss ухудшается", 8.8)
    c.rect(gx + gw - 160, top + 6, 146, 12, C["border"], radius=6)
    c.rect(gx + gw - 160, top + 6, 73, 12, C["accent"], radius=6)
    c.text(gx + gw - 87, top + 22, "эпоха 5 / 10", 8, fill=C["muted"], anchor="ma")
    c.text(gx + 14, top + 62, "⚠ «val_loss» вырос с 1.00 до 1.20 — возможна расходимость.",
           8.6, fill=C["warning"])
    ch_x, ch_y = gx + 14, top + 82
    ch_w, ch_h = gw - 28, 112
    c.rect(ch_x, ch_y, ch_w, ch_h, C["panel_alt"], outline=C["border"], radius=4)
    loss = [2.5, 1.9, 1.5, 1.25, 1.1, 1.02, 1.06, 1.12, 1.18, 1.22]
    acc = [0.10, 0.18, 0.26, 0.32, 0.38, 0.42, 0.44, 0.45, 0.46, 0.47]

    def curve(values, color, vmin, vmax):
        pts = []
        for i, v in enumerate(values):
            x = ch_x + 18 + (ch_w - 60) * i / (len(values) - 1)
            y = ch_y + ch_h - 14 - (ch_h - 30) * (v - vmin) / (vmax - vmin)
            pts.append((x, y))
        c.poly(pts, color, width=2)
        lx, ly = pts[-1]
        c.rect(lx - 3, ly - 3, 6, 6, color, radius=3)

    curve(loss, C["accent"], 0.0, 2.6)
    curve(acc, C["success"], 0.0, 1.0)
    c.text(ch_x + ch_w - 8, ch_y + 8, "val_loss: 1.22", 8.2, fill=C["accent"], anchor="ra")
    c.text(ch_x + ch_w - 8, ch_y + 22, "acc: 0.47", 8.2, fill=C["success"], anchor="ra")

    # Assessment card
    top = card(c, PX0, 364, PX1 - PX0, 268, "Оценка наставника")
    c.text(PX0 + 14, top + 2, "Оценка: 7.5/10", 13, bold=True, fill=C["accent"])
    c.text(PX1 - 14, top + 6, "обновлено 13.10 14:05", 8.5, fill=C["muted"], anchor="ra")
    columns = [
        ("Что хорошо", C["success"],
         ["• loss на обучении падает", "• пайплайн воспроизводим",
          "• lr-расписание корректно"]),
        ("Что плохо", C["danger"],
         ["• val_loss растёт с 5-й эпохи", "• нет early stopping",
          "• датасет мал для архитектуры"]),
        ("Риски", C["warning"],
         ["• переобучение к 8-й эпохе", "• нестабильность при смене seed"]),
        ("Рекомендации", C["accent"],
         ["• включить weight decay 0.01", "• добавить аугментации",
          "• проверить на 3 запусках"]),
    ]
    col_w = (PX1 - PX0 - 28 - 3 * 8) // 4
    for idx, (title, color, items) in enumerate(columns):
        x = PX0 + 14 + idx * (col_w + 8)
        c.text(x, top + 30, title, 9.5, bold=True, fill=color)
        c.rect(x, top + 48, col_w, 86, C["panel"], outline=C["border"], radius=4)
        for j, item in enumerate(items):
            c.text(x + 10, top + 58 + j * 17, item, 8.4, fill=C["text"])
    c.text(PX0 + 14, top + 146, "Рассуждение", 9.5, bold=True)
    c.rect(PX0 + 14, top + 164, PX1 - PX0 - 28, 52, C["panel"], outline=C["border"],
           radius=4)
    c.text(PX0 + 26, top + 174, "Train loss и val_loss расходятся после 5-й эпохи — модель", 9)
    c.text(PX0 + 26, top + 190, "запоминает обучающую выборку. Качество приемлемое, но нужна", 9)
    c.text(PX0 + 26, top + 206, "регуляризация и честная валидация.", 9)

    # Activity card
    top = card(c, PX0, 644, PX1 - PX0, 130, "Действия — журнал активности")
    feed = [
        ("13.10 14:05", "★", "Сохранена оценка наставника (7.5/10)"),
        ("13.10 14:03", "»", "read_file: train.py — ok"),
        ("13.10 14:02", "»", "search_files: val_loss — ok"),
        ("13.10 13:40", "▶", "Обучение запущено: python scripts/train.py --config base.yaml"),
    ]
    for idx, (stamp, icon, text) in enumerate(feed):
        y = top + 8 + idx * 18
        c.text(PX0 + 14, y, stamp, 8.5, mono=True, fill=C["muted"])
        c.text(PX0 + 94, y, icon, 8.5, fill=C["accent"])
        c.text(PX0 + 118, y, text, 8.8, fill=C["text"])
    return c.save("ui-dashboard.png")


if __name__ == "__main__":
    for path in (render_chat(), render_dashboard()):
        print(f"written: {path}")
