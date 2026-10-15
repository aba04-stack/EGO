
from alterego_training_hub.activity import ActivityLog
from alterego_training_hub.report import (
    ModelReport,
    ReportStore,
    parse_report,
    report_to_markdown,
)


def test_parse_report_from_fenced_json():
    text = (
        "Модель выглядит неплохо.\n"
        "```report\n"
        '{"score": 7.5, "reasoning": "Loss падает стабильно.",'
        ' "strengths": ["низкий val_loss"], "weaknesses": ["мало данных"],'
        ' "risks": ["переобучение"], "recommendations": ["добавить валидацию"]}\n'
        "```\n"
    )
    report = parse_report(text)
    assert report.score == 7.5
    assert "Loss" in report.reasoning
    assert report.strengths == ["низкий val_loss"]
    assert report.weaknesses == ["мало данных"]
    assert report.risks == ["переобучение"]
    assert report.recommendations == ["добавить валидацию"]


def test_parse_report_from_sections():
    text = (
        "## Рассуждение\n"
        "Обучение идёт ровно, но данных мало.\n"
        "## Что хорошо\n"
        "- loss снижается\n"
        "- метрики стабильны\n"
        "## Что плохо\n"
        "- датасет маленький\n"
        "## Риски\n"
        "- переобучение\n"
        "## Рекомендации\n"
        "- увеличить датасет\n"
    )
    report = parse_report(text)
    assert "данных мало" in report.reasoning
    assert "loss снижается" in report.strengths
    assert "датасет маленький" in report.weaknesses
    assert "переобучение" in report.risks
    assert "увеличить датасет" in report.recommendations


def test_parse_report_fallback_and_score_hint():
    report = parse_report("Свободный текст без структуры. Оценка: 6/10")
    assert report.score == 6.0
    assert "Свободный текст" in report.reasoning

    empty = parse_report("")
    assert empty.is_empty()


def test_header_matching_requires_exact_section_titles():
    text = (
        "Анализ данных завершён: всё готово\n"
        "Просто строка с двоеточием: да\n"
    )
    report = parse_report(text)
    # Neither line is a real section header — the whole text stays reasoning.
    assert "Анализ данных завершён" in report.reasoning
    assert report.strengths == [] and report.weaknesses == []


def test_report_store_and_markdown(tmp_path):
    store = ReportStore(tmp_path / "reports")
    report = ModelReport(score=8, reasoning="всё ок", strengths=["быстро"])
    path = store.save(report)
    assert path.exists()
    loaded = store.latest()
    assert loaded is not None and loaded.score == 8

    md = report_to_markdown(report)
    assert "# Оценка модели" in md
    assert "Что хорошо" in md
    assert "всё ок" in md


def test_activity_log_roundtrip(tmp_path):
    log = ActivityLog(tmp_path / "activity.jsonl")
    log.log("training", "Обучение запущено", command="python train.py")
    log.log("mentor_tool", "Наставник прочитал файл", path="a.py")
    log.log("training", "Обучение завершено", returncode=1)

    events = log.recent()
    assert events[0].summary == "Обучение завершено"
    assert events[0].details["returncode"] == 1
    only_training = log.recent(kind="training")
    assert all(event.kind == "training" for event in only_training)
    assert len(only_training) == 2
    assert ":" in log.recent()[0].stamp()  # "день.месяц часы:минуты"
