"""Этап 34: бенчмарк реальной модели на скриптовом менторе-«актёре»."""
from alterego_training_hub.agent_bench import ScriptedMentor
from alterego_training_hub.live_bench import run_live_benchmark
from alterego_training_hub.mentor import MentorReply, ToolCall


def _tc(name, **args):
    return ToolCall(id="x", name=name, arguments=args)


def _smart_mentor() -> ScriptedMentor:
    """Plays a competent model: fixes, creates, answers — via real tools."""
    return ScriptedMentor([
        # сценарий 1: исправь баг
        MentorReply(text="", model="smart",
                    usage={"prompt_tokens": 100, "completion_tokens": 20},
                    tool_calls=(_tc("replace_in_file", path="calc.py",
                                    find="a - b", replace="a + b"),)),
        MentorReply(text="Исправил.", model="smart",
                    usage={"prompt_tokens": 50, "completion_tokens": 10}),
        # сценарий 2: создай файл
        MentorReply(text="", model="smart",
                    usage={"prompt_tokens": 80, "completion_tokens": 15},
                    tool_calls=(_tc("write_file", path="notes.md",
                                    content="# Заметки проекта\n"),)),
        MentorReply(text="Создал.", model="smart",
                    usage={"prompt_tokens": 40, "completion_tokens": 5}),
        # сценарий 3: ответь по файлу
        MentorReply(text="", model="smart",
                    usage={"prompt_tokens": 60, "completion_tokens": 10},
                    tool_calls=(_tc("read_file", path="config.txt"),)),
        MentorReply(text="mode = nightly", model="smart",
                    usage={"prompt_tokens": 30, "completion_tokens": 5}),
    ])


def test_live_benchmark_smart_model_passes(tmp_path):
    report = run_live_benchmark(
        _smart_mentor(), timeout=30,
        root_factory=lambda: tmp_path / f"s{len(list(tmp_path.iterdir()))}")
    assert report.ok, report.render()
    assert report.passed == 3
    assert report.prompt_tokens == 360
    text = report.render()
    assert "3/3" in text and "стоимости" in text
    assert report.cost_usd >= 0


def test_live_benchmark_lazy_model_fails_fix(tmp_path):
    lazy = ScriptedMentor([
        MentorReply(text="Наверное, всё и так работает.", model="lazy",
                    usage={}),
        MentorReply(text="Готово, наверное.", model="lazy", usage={}),
        MentorReply(text="Не читал, но думаю nightly.", model="lazy",
                    usage={}),
    ])
    counter = {"n": 0}

    def factory():
        counter["n"] += 1
        return tmp_path / f"r{counter['n']}"

    report = run_live_benchmark(lazy, timeout=30, root_factory=factory)
    assert not report.ok
    by_name = {r.name: r.passed for r in report.results}
    assert by_name["исправь баг"] is False
    assert by_name["создай файл"] is False


def test_live_benchmark_timeout_is_a_result(tmp_path):
    import time as _time

    class SlowMentor:
        model = "slow"

        def respond(self, messages, *, tools=None, max_tokens=0,
                    temperature=0.0):
            _time.sleep(2)
            return MentorReply(text="медленно", model=self.model, usage={})

    report = run_live_benchmark(SlowMentor(), timeout=0.2,
                                root_factory=lambda: tmp_path / "t1")
    assert not report.ok
    assert "таймаут" in report.results[0].detail
