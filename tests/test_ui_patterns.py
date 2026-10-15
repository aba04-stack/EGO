"""Этап 28: UX-паттерны — иконки, primary-действия, фильтры, статус-бейджи."""
from alterego_training_hub.ui_patterns import (
    NAV_ICONS,
    filter_titles,
    nav_icon,
    nav_label,
    primary_action,
    status_badges,
    tooltip_text,
)


def test_nav_icons_and_labels():
    assert nav_icon("training") == "🏋"
    assert nav_icon("unknown") == "•"
    wide = nav_label("training", "Обучение", compact=False)
    assert "🏋" in wide and "Обучение" in wide
    compact = nav_label("training", "Обучение", compact=True, badge="●")
    assert compact.startswith("🏋") and "Обучение" not in compact
    assert set(NAV_ICONS) >= {"editor", "training", "settings", "chat"}


def test_filter_titles():
    titles = ["Про обучение", "про код", "Другое"]
    assert filter_titles(titles, "про") == ["Про обучение", "про код"]
    assert filter_titles(titles, "") == titles
    assert filter_titles([], "x") == []


def test_primary_actions_map_to_real_methods():
    assert primary_action("training") == ("Запустить", "start_training")
    assert primary_action("nope") is None
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "alterego_training_hub"
    files = {"training": "ui_training.py", "models": "ui_models.py",
             "datasets": "ui_datasets.py", "gpu": "ui_gpu.py",
             "playground": "ui_playground.py", "model": "ui_model.py"}
    for key, filename in files.items():
        action = primary_action(key)
        assert action is not None
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        methods = {node.name for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef)}
        assert action[1] in methods, f"{key}: {action[1]} not in {filename}"


def test_status_badges_and_tooltip():
    badges = status_badges(provider="openai", model="gpt-4o",
                           training="идёт", tokens_today=1200, budget_usd=0.5)
    assert any("gpt-4o" in b for b in badges)
    assert any("🏋" in b for b in badges)
    assert any("1200" in b for b in badges)
    assert status_badges()[0].startswith("🤖")
    assert tooltip_text("Сохранить", "Ctrl+S") == "Сохранить (Ctrl+S)"
    assert tooltip_text("Сохранить") == "Сохранить"
