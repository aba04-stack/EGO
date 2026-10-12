#!/usr/bin/env python3
"""Render high-fidelity UI mockups from the app's real design tokens.

Real screenshots need a desktop session; this script draws the actual IDE
layout (sidebar + center pages + bottom terminal + docked right chat panel),
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
VW, VH = 1480, 860
W, H = int(VW * S), int(VH * S)
SIDE = 200           # left sidebar (navigation)
CHAT_W = 390         # docked chat panel on the right
CX0 = SIDE + 20      # center page margin left
CX1 = VW - CHAT_W - 20  # center page margin right
TERM_H = 186         # terminal height above the status bar
CH0 = 10             # chat panel margin left (inside the panel)

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


NAV_GROUPS = [
    ("РАЗРАБОТКА", ["Редактор кода", "Рабочая папка"]),
    ("БИБЛИОТЕКА", ["Модели", "Датасеты", "Модель и прогресс"]),
    ("ЭКСПЕРИМЕНТЫ", ["Playground", "Обучение", "Внешние GPU"]),
    ("СИСТЕМА", ["Коннекторы", "Настройки"]),
]


def draw_shell(c: Canvas, active: str, status: str, badge: str):
    c.rect(0, 0, VW, VH, C["bg"])
    # Sidebar
    c.rect(0, 0, SIDE, VH, C["sidebar"])
    c.text(18, 26, "AlterEgo", 16, bold=True, fill="#ffffff")
    c.text(18, 52, "LLM Studio", 11, fill=C["sidebar_fg"])
    y = 88
    for group_title, items in NAV_GROUPS:
        c.text(16, y, group_title, 7.6, bold=True, fill="#5b6b85")
        y += 18
        for label in items:
            is_active = label == active
            if is_active:
                c.rect(0, y, SIDE, 34, C["sidebar_active"])
                c.rect(0, y, 4, 34, C["accent"])
            c.text(28, y + 9, label, 9.6, bold=is_active,
                   fill=C["sidebar_fg_active"] if is_active else C["sidebar_fg"])
            y += 34
        y += 6
    c.text(18, VH - 40, "v0.5 · локальный контур", 8.2, fill="#5b6b85")

    # Right chat panel background
    cxp = VW - CHAT_W
    c.rect(cxp, 0, CHAT_W, VH - 26, C["panel"])
    c.rect(cxp - 1, 0, 1, VH - 26, C["border"])

    # Terminal block in the center column
    term_y = VH - 26 - TERM_H
    c.rect(SIDE, term_y, cxp - SIDE, TERM_H, C["panel"])
    c.rect(SIDE, term_y, cxp - SIDE, 1, C["border"])

    # Status bar
    c.rect(0, VH - 26, VW, 26, "#e8edf5")
    c.text(12, VH - 19, status, 8.5, fill=C["muted"])
    c.text(VW - 14, VH - 19, badge, 8.5, fill=C["muted"], anchor="ra")


def draw_terminal(c: Canvas):
    cxp = VW - CHAT_W
    y0 = VH - 26 - TERM_H
    c.text(SIDE + 12, y0 + 10, "ТЕРМИНАЛ", 8, bold=True, fill=C["muted"])
    c.rect(SIDE + 90, y0 + 8, 240, 20, C["panel_alt"], outline=C["border"], radius=4)
    c.text(SIDE + 98, y0 + 13, "python -m pytest -q", 8.2, mono=True, fill=C["muted"])
    c.rect(SIDE + 338, y0 + 8, 84, 20, C["accent"], radius=4)
    c.text(SIDE + 350, y0 + 13, "▶ Выполнить", 8, bold=True, fill="#ffffff")
    c.rect(SIDE + 430, y0 + 8, 64, 20, C["panel_alt"], outline=C["border"], radius=4)
    c.text(SIDE + 442, y0 + 13, "Очистить", 8, fill=C["text"])

    c.rect(SIDE + 1, y0 + 34, cxp - SIDE - 2, TERM_H - 35, C["code_bg"])
    lines = [
        ("$ python -m pytest -q", C["code_fg"]),
        ("....F..........", C["code_fg"]),
        ("FAILED tests/test_loss.py::test_val_loss_finite", C["danger"]),
        ("1 failed, 93 passed in 4.2s", C["code_fg"]),
        ("[код 1 · 14:41]", C["muted"]),
    ]
    for idx, (line, color) in enumerate(lines):
        c.text(SIDE + 14, y0 + 44 + idx * 17, line, 8.6, mono=True, fill=color)


def draw_chat_panel(c: Canvas, *, agent_mode: bool = True):
    cxp = VW - CHAT_W
    x = cxp + CH0
    w = CHAT_W - 2 * CH0

    c.text(x, 18, "Наставник", 12, bold=True)
    c.rect(x, 40, 210, 22, C["panel_alt"], outline=C["border"], radius=4)
    c.text(x + 8, 46, "Почему растёт loss?", 8.8, fill=C["text"])
    c.rect(x + 216, 40, 22, 22, C["panel_alt"], outline=C["border"], radius=4)
    c.text(x + 223, 45, "+", 10, fill=C["text"])
    c.rect(x + 242, 40, 22, 22, C["panel_alt"], outline=C["danger"], radius=4)
    c.text(x + 249, 45, "✕", 9, fill=C["danger"])

    c.text(x, 74, "Режим", 8, fill=C["muted"])
    if agent_mode:
        c.rect(x + 42, 68, 196, 22, C["success"], radius=4)
        c.text(x + 52, 73, "» Режим агента — действует свободно", 8, bold=True,
               fill="#ffffff")
    else:
        c.rect(x + 42, 68, 196, 22, C["accent"], radius=4)
        c.text(x + 52, 73, "· Ассистент — подтверждает действия", 8, bold=True,
               fill="#ffffff")
    c.text(x, 98, "агент · папка: alterego-train", 8, fill=C["muted"])

    # Conversation bubbles
    c.text(x, 122, "Вы · 14:02", 7.6, bold=True, fill=C["muted"])
    c.rect(x + 46, 134, w - 46, 34, C["user_bubble"], radius=8)
    c.text(x + 56, 142, "Запусти тесты, найди падающий, почини", 8.8)
    c.text(x + 56, 156, "и проверь, что всё зелёное.", 8.8)

    c.text(x, 182, "Наставник · 14:02", 7.6, bold=True, fill=C["muted"])
    for idx, (line, color) in enumerate([
        ("→ run_command: python -m pytest -q", C["accent"]),
        ("  [err] 1 failed, 93 passed", C["danger"]),
        ("→ read_file: tests/test_loss.py", C["accent"]),
        ("  [ok] {\"ok\": true, …}", C["success"]),
        ("→ apply_patch: tests/test_loss.py", C["accent"]),
        ("  [ok] {\"ok\": true, …}", C["success"]),
        ("→ run_command: python -m pytest -q", C["accent"]),
        ("  [ok] 94 passed in 4.0s", C["success"]),
    ]):
        c.rect(x, 194 + idx * 17, w, 16, C["tool_bubble"] if idx % 2 == 0 else C["panel"],
               radius=3)
        c.text(x + 8, 198 + idx * 17, line, 7.6, mono=True, fill=color)

    c.rect(x, 340, w, 92, C["panel"], outline=C["border"], radius=8)
    c.text(x + 12, 350, "Готово: тест починен (assert допускал NaN),", 9)
    c.text(x + 12, 366, "перезапуск — 94 passed. Проверка приложена.", 9)
    c.text(x + 12, 388, "Итог: найдена причина падения, внесена минимальная", 8.6,
           fill=C["muted"])
    c.text(x + 12, 402, "правка, всё проверено повторным прогоном.", 8.6,
           fill=C["muted"])

    # Quick buttons + input
    for idx, label in enumerate(["Оценка", "Прогресс", "Ошибки"]):
        bx = x + idx * 62
        c.rect(bx, 444, 58, 22, C["panel_alt"], outline=C["border"], radius=4)
        c.text(bx + 8, 450, label, 7.8, fill=C["text"])
    c.rect(x, 478, w - 44, 40, C["panel"], outline=C["border"], radius=4)
    c.text(x + 10, 492, "Спасибо! А как добавить early stopping?", 8.6, fill=C["muted"])
    c.rect(x + w - 40, 478, 40, 40, C["accent"], radius=6)
    c.text(x + w - 30, 490, "➤", 11, bold=True, fill="#ffffff")


def card(c: Canvas, x, y, w, h, title=None):
    c.rect(x, y, w, h, C["border"], radius=6)
    c.rect(x + 1, y + 1, w - 2, h - 2, C["panel"], radius=6)
    if title:
        c.text(x + 14, y + 10, title, 10.5, bold=True)
    return y + (34 if title else 12)


def render_chat() -> Path:
    """IDE view: code editor in the center, terminal below, agent chat at right."""
    c = Canvas()
    draw_shell(c, "Редактор кода", "Готово: ответ наставника", "папка: alterego-train")
    c.text(CX0, 32, "Редактор кода", 15, bold=True)
    c.text(CX0, 58, "Сборка проекта, шаблоны обучения и правка файлов в рабочей "
                    "папке.", 9, fill=C["muted"])

    # Scaffolding bar
    c.text(CX0, 86, "Новый проект", 9, bold=True)
    c.rect(CX0 + 90, 80, 120, 22, C["panel"], outline=C["border"], radius=4)
    c.text(CX0 + 98, 86, "demo", 8.8, fill=C["muted"])
    for idx, (label, primary) in enumerate([("Новый проект", False),
                                            ("Шаблон обучения", False),
                                            ("Базовый fine-tune", True)]):
        bx = CX0 + 224 + idx * 116
        c.rect(bx, 80, 108, 22, C["accent"] if primary else C["panel_alt"],
               outline=None if primary else C["border"], radius=4)
        c.text(bx + 10, 86, label, 8, bold=primary,
               fill="#ffffff" if primary else C["text"])

    # File tree
    tw = 180
    c.rect(CX0, 112, tw, 380, C["border"], radius=6)
    c.rect(CX0 + 1, 113, tw - 2, 378, C["panel"], radius=6)
    c.text(CX0 + 12, 122, "ФАЙЛЫ ПРОЕКТА", 7.8, bold=True, fill=C["muted"])
    tree = [
        ("> alterego-train", C["muted"], True),
        ("  v src", C["muted"], True),
        ("    train.py", C["accent"], False),
        ("    data.py", C["text"], False),
        ("    model.py", C["text"], False),
        ("  v tests", C["muted"], True),
        ("    test_loss.py", C["text"], False),
        ("  config.yaml", C["text"], False),
        ("  README.md", C["text"], False),
    ]
    for idx, (label, color, dim) in enumerate(tree):
        y = 142 + idx * 18
        if label.strip() == "train.py":
            c.rect(CX0 + 6, y - 3, tw - 12, 18, C["sidebar_active"], radius=3)
        c.text(CX0 + 12, y, label, 8.4, mono=True, fill=color, bold=not dim)

    # Editor
    ex = CX0 + tw + 12
    ew = CX1 - ex
    c.rect(ex, 112, ew, 380, C["border"], radius=6)
    c.rect(ex + 1, 113, ew - 2, 378, C["code_bg"], radius=6)
    c.rect(ex + 1, 113, ew - 2, 26, C["panel"], radius=6)
    c.text(ex + 12, 120, "src/train.py", 8.6, mono=True, fill=C["text"])
    code = [
        "def train(model, loader, *, epochs=10, lr=3e-4):",
        "    opt = torch.optim.AdamW(model.parameters(), lr=lr)",
        "    for epoch in range(epochs):",
        "        for batch in loader:",
        "            loss = model(batch)",
        "            loss.backward()",
        "            opt.step()",
        "            opt.zero_grad()",
        "        val = evaluate(model, loader.val)",
        "        log(epoch=epoch + 1, val_loss=val)",
        "    return model",
    ]
    for idx, line in enumerate(code):
        y = 150 + idx * 17
        c.text(ex + 12, y, f"{idx + 1:>3}", 7.6, mono=True, fill=C["muted"])
        c.text(ex + 36, y, line, 8.6, mono=True, fill=C["code_fg"])

    draw_terminal(c)
    draw_chat_panel(c, agent_mode=True)
    return c.save("ui-chat.png")


def render_dashboard() -> Path:
    """Model & progress page in the center, terminal below, chat at right."""
    c = Canvas()
    draw_shell(c, "Модель и прогресс", "Готово: оценка наставника", "папка: alterego-train")
    c.text(CX0, 32, "Модель и прогресс", 15, bold=True)
    c.text(CX0, 58, "Сводка по выбранной модели: прогресс обучения, оценка "
                    "наставника и журнал действий.", 9, fill=C["muted"])

    # Toolbar
    c.text(CX0, 88, "Модель", 9.5, bold=True)
    c.rect(CX0 + 52, 80, 220, 24, C["panel"], outline=C["border"], radius=4)
    c.text(CX0 + 62, 87, "gpt-mini-v2  ·  local", 8.8, fill=C["text"])
    c.rect(CX0 + 282, 80, 80, 24, C["panel_alt"], outline=C["border"], radius=4)
    c.text(CX0 + 296, 87, "Обновить", 8.4, fill=C["text"])
    c.rect(CX0 + 372, 80, 136, 24, C["accent"], radius=4)
    c.text(CX0 + 386, 87, "Оценка наставника", 8.4, bold=True, fill="#ffffff")

    # Model card
    top = card(c, CX0, 116, 390, 210, "Карточка модели")
    rows = [
        ("Название", "gpt-mini-v2"), ("Тип", "local"),
        ("Путь / URI", "checkpoints/gpt-mini-v2.safetensors"),
        ("API model id", "gpt-mini-v2"),
        ("URL инференса", "https://api.example.test/v1"),
        ("Обновлено", "13.10.2026 14:40"),
        ("Метрики", "val_loss: 1.22, acc: 0.47"),
        ("Заметки", "маленькая LM для экспериментов"),
    ]
    for idx, (label, value) in enumerate(rows):
        y = top + 6 + idx * 19
        c.text(CX0 + 14, y, f"{label}:", 8.6, bold=True, fill=C["muted"])
        c.text(CX0 + 106, y, value, 8.6, fill=C["text"])

    # Progress card
    gx = CX0 + 402
    gw = CX1 - gx
    top = card(c, gx, 116, gw, 210, "Прогресс обучения")
    c.text(gx + 14, top + 4, "Состояние: выполняется", 9, bold=True)
    c.text(gx + 14, top + 20, "python scripts/train.py --config base.yaml", 7.8,
           mono=True, fill=C["muted"])
    c.text(gx + 14, top + 38, "эпоха 5/10 · val_loss: 1.22 · acc: 0.47 · "
                              "тренд: val_loss ухудшается", 8)
    c.rect(gx + gw - 150, top + 4, 136, 11, C["border"], radius=5)
    c.rect(gx + gw - 150, top + 4, 68, 11, C["accent"], radius=5)
    c.text(gx + gw - 82, top + 18, "эпоха 5 / 10", 7.6, fill=C["muted"], anchor="ma")
    c.text(gx + 14, top + 56, "! «val_loss» вырос с 1.00 до 1.22 — возможна расходимость.",
           7.8, fill=C["warning"])
    ch_x, ch_y = gx + 14, top + 74
    ch_w, ch_h = gw - 28, 108
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
    c.text(ch_x + ch_w - 8, ch_y + 8, "val_loss: 1.22", 7.8, fill=C["accent"], anchor="ra")
    c.text(ch_x + ch_w - 8, ch_y + 22, "acc: 0.47", 7.8, fill=C["success"], anchor="ra")

    # Assessment card
    top = card(c, CX0, 338, CX1 - CX0, 148, "Оценка наставника")
    c.text(CX0 + 14, top + 2, "Оценка: 7.5/10", 12, bold=True, fill=C["accent"])
    c.text(CX1 - 14, top + 6, "обновлено 13.10 14:05", 8, fill=C["muted"], anchor="ra")
    columns = [
        ("Что хорошо", C["success"],
         ["• loss на обучении падает", "• пайплайн воспроизводим"]),
        ("Что плохо", C["danger"],
         ["• val_loss растёт с 5-й эпохи", "• нет early stopping"]),
        ("Риски", C["warning"],
         ["• переобучение к 8-й эпохе", "• нестабильность при смене seed"]),
        ("Рекомендации", C["accent"],
         ["• включить weight decay 0.01", "• проверить на 3 запусках"]),
    ]
    col_w = (CX1 - CX0 - 28 - 3 * 8) // 4
    for idx, (title, color, items) in enumerate(columns):
        x = CX0 + 14 + idx * (col_w + 8)
        c.text(x, top + 28, title, 9, bold=True, fill=color)
        c.rect(x, top + 44, col_w, 56, C["panel"], outline=C["border"], radius=4)
        for j, item in enumerate(items):
            c.text(x + 8, top + 52 + j * 16, item, 7.8, fill=C["text"])

    # Activity card
    top = card(c, CX0, 498, CX1 - CX0, 84, "Действия — журнал активности")
    feed = [
        ("13.10 14:05", "★", "Сохранена оценка наставника (7.5/10)"),
        ("13.10 14:03", "»", "read_file: train.py — ok"),
        ("13.10 13:40", "▶", "Обучение запущено: python scripts/train.py --config base.yaml"),
    ]
    for idx, (stamp, icon, text) in enumerate(feed):
        y = top + 6 + idx * 17
        c.text(CX0 + 14, y, stamp, 8, mono=True, fill=C["muted"])
        c.text(CX0 + 88, y, icon, 8, fill=C["accent"])
        c.text(CX0 + 110, y, text, 8.4, fill=C["text"])

    draw_terminal(c)
    draw_chat_panel(c, agent_mode=False)
    return c.save("ui-dashboard.png")


if __name__ == "__main__":
    for path in (render_chat(), render_dashboard()):
        print(f"written: {path}")
