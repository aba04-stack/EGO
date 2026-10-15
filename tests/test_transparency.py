"""Этап 26: прозрачность ЛЛМ — мысли, действия, контекст, критик, сэмплы."""
import json

from alterego_training_hub.action_trace import (
    ActionEntry,
    ActionTrace,
    action_entries_from_messages,
    explain_prompt,
)
from alterego_training_hub.chat import ChatMessage
from alterego_training_hub.context_view import (
    build_context_view,
    estimate_cost,
    estimate_tokens,
    format_usage,
    price_for_model,
)
from alterego_training_hub.critique import (
    build_critic_messages,
    parse_critique,
    run_critic,
)
from alterego_training_hub.gen_preview import (
    GenerationSample,
    compare_samples,
    format_sample,
    format_samples,
    parse_samples,
    perplexity_from_loss,
)
from alterego_training_hub.night_watch import WatchEntry, morning_report
from alterego_training_hub.thought_stream import (
    parse_thought_block,
    render_thoughts_or_hint,
)


# ---------------------------------------------------------------- thoughts
def test_parse_thought_block_full():
    record = parse_thought_block(
        "Мысль: смотрю лог\nДействие: читаю файл train.py\n"
        "Мысль: loss растёт\nОтвет: Причина — высокий lr.")
    assert record.has_protocol
    assert [s.kind for s in record.steps] == ["thought", "action", "thought"]
    assert record.answer == "Причина — высокий lr."
    assert "💭 Мысль: смотрю лог" in record.render()


def test_parse_thought_block_plain_text():
    record = parse_thought_block("Просто ответ без протокола.")
    assert not record.has_protocol
    assert record.answer == "Просто ответ без протокола."
    assert render_thoughts_or_hint(record, hint="нет протокола") == "нет протокола"


def test_parse_thought_block_english_and_multiline_answer():
    record = parse_thought_block("Thought: check\nAnswer: line1\nline2")
    assert record.steps[0].kind == "thought"
    assert record.answer == "line1\nline2"


# ------------------------------------------------------------------ actions
def test_action_trace_record_and_render():
    trace = ActionTrace()
    trace.record_tool("read_file", "ok: 10 строк", arguments={"path": "a.py"})
    trace.record_tool("run_tests", "2 failed", ok=False)
    lines = trace.render()
    assert "✓ read_file" in lines and "✗ run_tests" in lines
    entry = trace.entries()[0]
    assert "Зачем" not in entry.detail()
    assert "read_file" in explain_prompt(entry)


def test_action_entries_from_messages():
    messages = [
        ChatMessage(role="user", content="привет"),
        ChatMessage(role="tool", name="read_file",
                    content=json.dumps({"ok": True, "summary": "прочитано"})),
        ChatMessage(role="tool", name="write_file",
                    content=json.dumps({"ok": False, "error": "нет прав"})),
        ChatMessage(role="tool", name="run", content="plain output"),
    ]
    entries = action_entries_from_messages(messages)
    assert [e.tool for e in entries] == ["read_file", "write_file", "run"]
    assert entries[0].ok and entries[0].summary == "прочитано"
    assert not entries[1].ok and "нет прав" in entries[1].summary
    assert entries[2].summary == "plain output"


def test_morning_report_includes_actions():
    entries = [WatchEntry(summary="всё ок", ok=True)]
    actions = [ActionEntry(tool="set_lr", summary="lr=1e-4", ok=True)]
    text = morning_report(entries, actions=actions)
    assert "Действия агента за ночь" in text and "set_lr" in text
    assert "Действия" not in morning_report(entries)


# ------------------------------------------------------------------ context
def test_estimate_tokens_and_cost():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("x" * 400) == 100
    pin, _ = price_for_model("gpt-4o-mini-2024")
    assert pin == 0.15
    assert estimate_cost(1_000_000, 0, "gpt-4o-mini") == 0.15
    assert estimate_cost(0, 0, "whatever") == 0.0


def test_context_view_render():
    view = build_context_view(
        system_prompt="Ты наставник. " * 10,
        messages=[{"role": "user", "content": "Вопрос?"}],
        model="gpt-4o",
        last_usage={"prompt_tokens": 100, "completion_tokens": 50})
    text = view.render()
    assert "Модель: gpt-4o" in text
    assert "Итого контекст" in text
    assert "100 → 50" in format_usage(view.last_usage, model="gpt-4o")


# ------------------------------------------------------------------ critic
class _Mentor:
    def __init__(self, text="", exc=None):
        self.text, self.exc, self.calls = text, exc, []

    def respond(self, messages, *, tools=None, max_tokens=0, temperature=0.0):
        self.calls.append(messages)
        if self.exc:
            raise self.exc
        class R:
            pass
        reply = R()
        reply.text = self.text
        return reply


def test_parse_critique_ok_and_suspect():
    ok = parse_critique("ВЕРДИКТ: ок\nУВЕРЕННОСТЬ: 0.9\nПРОБЛЕМЫ: —")
    assert not ok.suspect and ok.confidence == 0.9 and ok.flag().startswith("✓")
    bad = parse_critique("ВЕРДИКТ: сомнительно\nУВЕРЕННОСТЬ: 0,3\n"
                         "ПРОБЛЕМЫ: выдуман файл; нет метрик")
    assert bad.suspect and bad.confidence == 0.3
    assert bad.issues == ("выдуман файл", "нет метрик")
    assert "⚠ проверить" in bad.render()


def test_run_critic_never_raises():
    report = run_critic(_Mentor(exc=RuntimeError("сеть упала")),
                        answer="ответ")
    assert report.suspect and "сеть упала" in report.issues[0]
    good = run_critic(_Mentor("ВЕРДИКТ: ок\nУВЕРЕННОСТЬ: 1\nПРОБЛЕМЫ: —"),
                      question="q", answer="a", evidence="лог чист")
    assert not good.suspect
    msgs = build_critic_messages(question="q", answer="a")
    assert msgs[0]["role"] == "system" and "Вопрос" in msgs[1]["content"]


# ------------------------------------------------------------------ samples
LOG = """loss=2.3 step=10
{"sample": {"step": 100, "prompt": "Привет", "text": "мир", "checkpoint": "best"}}
### sample @200 [last]
prompt: Столица Франции —
text: Париж.
loss=1.1
"""


def test_parse_samples_json_and_block():
    samples = parse_samples(LOG)
    assert len(samples) == 2
    assert samples[0].step == 100 and samples[0].checkpoint == "best"
    assert samples[1].prompt.startswith("Столица")
    assert "Париж" in samples[1].text
    assert "шаг 100" in samples[0].line()


def test_format_and_compare_samples():
    a = GenerationSample(step=10, prompt="p", text="hello world", checkpoint="a")
    b = GenerationSample(step=20, prompt="p", text="hello there", checkpoint="b")
    card = format_sample(a)
    assert "Шаг: 10" in card and "hello world" in card
    diff = compare_samples(a, b)
    assert "Общее начало" in diff and "vs" in diff
    assert format_samples([]) == ""


def test_perplexity():
    assert perplexity_from_loss(0.0) == 1.0
    assert 2.7 < perplexity_from_loss(1.0) < 2.8
    assert perplexity_from_loss(-1) == float("inf")
    assert perplexity_from_loss("x") == float("inf")
