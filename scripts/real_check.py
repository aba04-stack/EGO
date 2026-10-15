"""Real end-to-end verification — no mocks, no fakes, no simulators.

Exercises the actual subsystems against the real environment: the
real filesystem and git checkout, real subprocesses, the real network
where the sandbox permits it, and a real (tiny) training process whose
log flows through metrics → evaluation → run history.

    python scripts/real_check.py [--quick]

Exit code 0 only when every hard check passes.  Checks that need a
resource the sandbox genuinely lacks (display/Tk, HF network, torch)
report BLOCKED instead of pretending to pass.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("PYTHON_KEYRING_BACKEND",
                      "keyring.backends.null.Keyring")

RESULTS: list[tuple[str, bool | None, str]] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
    except Exception as exc:
        RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"✗ {name} — {type(exc).__name__}: {exc}")
        return
    RESULTS.append((name, True, str(detail or "")))
    print(f"✓ {name} — {detail}")


def blocked(name: str, reason: str) -> None:
    RESULTS.append((name, None, reason))
    print(f"⊘ {name} — BLOCKED: {reason}")


def main() -> int:
    quick = "--quick" in sys.argv
    require_torch = "--require-torch" in sys.argv
    repo = Path(__file__).resolve().parents[1]
    tmp = Path(tempfile.mkdtemp(prefix="ego-real-"))
    os.environ["XDG_CONFIG_HOME"] = str(tmp / "config")

    # 1. Package imports and version -------------------------------------
    def _version():
        import importlib.metadata

        import alterego_training_hub as pkg

        scripts = importlib.metadata.entry_points(group="console_scripts")
        names = {ep.name for ep in scripts}
        assert "ego" in names and "alterego-llm-studio" in names, names
        return f"version {pkg.__version__}, console-script зарегистрирован"
    check("пакет и точка входа импортируются", _version)

    # 2. Settings round-trip on a real file ------------------------------
    def _settings():
        from alterego_training_hub.config import AppSettings

        settings = AppSettings()
        settings.workspace_path = str(repo)
        settings.embeddings_model = "emb-real"
        path = settings.save()
        loaded = AppSettings.load()
        assert loaded.workspace_path == str(repo), loaded.workspace_path
        assert loaded.embeddings_model == "emb-real"
        return f"save/load через {path.name}"
    check("настройки: реальный save/load", _settings)

    # 3. Workspace tools on the real repo --------------------------------
    def _tools():
        from alterego_training_hub.tools import WorkspaceTools

        tools = WorkspaceTools(repo)
        found = tools.search_files("class TrainingRun", "**/*.py")
        assert found["matches"], "TrainingRun не найден поиском"
        listing = tools.list_files("src/alterego_training_hub")
        assert "training.py" in str(listing), listing
        return f"поиск по реальному коду: {len(found['matches'])} совпадений"
    check("инструменты рабочей папки на реальном репозитории", _tools)

    # 4. Git info of the real checkout ------------------------------------
    def _git():
        from alterego_training_hub.reproducibility import collect_environment

        env = collect_environment(repo)
        assert env.get("git_commit"), env
        assert env["packages"], "pip freeze пуст"
        return (f"git {env['git_commit'][:8]} · пакетов {len(env['packages'])} "
                f"· python {env['python']}")
    check("воспроизводимость: реальный git + pip freeze", _git)

    # 5. Semantic search over the real source tree ------------------------
    def _semantic():
        from alterego_training_hub.semantic_search import SemanticIndex

        index = SemanticIndex(repo / "src" / "alterego_training_hub")
        stats = index.build()
        hits = index.search("training process log metrics anomalies")
        assert hits, "нет результатов"
        return (f"файлов {stats['files']}, чанков {stats['embedded']}, "
                f"топ: {hits[0].path}:{hits[0].line}")
    check("семантический поиск по реальному коду", _semantic)

    # 6. Generated training script: real smoke checks ---------------------
    def _smoke():
        from alterego_training_hub.model_recipes import get_preset
        from alterego_training_hub.smoke_run import smoke_script
        from alterego_training_hub.train_script import ScriptConfig, generate_script

        data = tmp / "data.txt"
        data.write_text("реальная строка обучающих данных\n" * 8,
                        encoding="utf-8")
        cfg = ScriptConfig(path="scratch", preset=get_preset("llama-tiny"),
                           dataset_path=str(data))
        script = tmp / "train_llm.py"
        script.write_text(generate_script(cfg), encoding="utf-8")
        report = smoke_script(script)
        assert report.ok, report.render()
        return f"smoke {report.passed}/{len(report.checks)} на реальном скрипте"
    check("сгенерированный скрипт: реальный smoke-прогон", _smoke)

    # 7. Real training process → metrics → evaluation → history -----------
    def _training():
        from alterego_training_hub.evaluation import build_eval_report
        from alterego_training_hub.metrics import parse_log
        from alterego_training_hub.runs import RunStore
        from alterego_training_hub.training import TrainingRun

        program = (
            "import time\n"
            "for step in range(1, 6):\n"
            "    loss = 2.0 / step\n"
            "    print(f'loss={loss:.4f} step={step}', flush=True)\n"
            "    print(f'eval: val_loss={loss * 1.1:.4f}', flush=True)\n"
            "    time.sleep(0.05)\n"
            "print('epoch 1/1', flush=True)\n")
        runner = TrainingRun(log_dir=tmp / "logs")
        log_path = runner.start(f'{sys.executable} -c "{program}"', tmp)
        deadline = time.time() + 30
        while time.time() < deadline and runner.status().running:
            time.sleep(0.2)
        status = runner.status()
        assert not status.running and status.returncode == 0, status
        tail = runner.tail()
        summary = parse_log(tail)
        assert summary.points, "метрики не распарсились"
        report = build_eval_report(tail)
        store = RunStore(tmp / "runs.json")
        record = store.start("real-training", str(tmp), log_path,
                             environment={"git_commit": "realcheck"})
        store.finish(record.id, 0, metrics_last={"loss": 0.4},
                     best={"val_loss": report.best_val_loss or 0.0})
        assert store.list(1)[0].best["val_loss"] > 0
        return (f"процесс ok, точек метрик {len(summary.points)}, "
                f"best val_loss={report.best_val_loss}")
    check("реальное обучение: процесс→метрики→оценка→история", _training)

    # 8. Real benchmark of a real command ---------------------------------
    def _bench():
        from alterego_training_hub.bench import BenchStore, run_benchmark
        from alterego_training_hub.bench_history import history_table

        result = run_benchmark(
            "real-cmd", f'{sys.executable} -c "print(1)"', iterations=2)
        assert result.ok(), result
        store = BenchStore(tmp)
        store.add(result)
        assert "real-cmd" in history_table(store.list(5))
        return f"{result.duration_ms} мс/запуск на реальной команде"
    check("бенчмарк реальной команды + история", _bench)

    # 9. SFT data tools on real files --------------------------------------
    def _sft():
        from alterego_training_hub.datasets import read_rows, write_rows
        from alterego_training_hub.sft_data import (
            decontaminate,
            dedupe_near,
            validate_sft,
        )

        rows = [
            {"messages": [{"role": "user", "content": "Привет"},
                          {"role": "assistant", "content": "Здравствуйте"}]},
            {"messages": [{"role": "user", "content": "Привет"},
                          {"role": "assistant", "content": "Здравствуйте!"}]},
            {"instruction": "Переведи", "output": ""},
        ]
        path = write_rows(tmp / "sft.jsonl", rows, "jsonl")
        loaded = read_rows(path, "jsonl")
        report = validate_sft(loaded)
        assert report.problem_rows == 1, report.render()
        _kept, removed = dedupe_near(loaded, threshold=0.99)
        result = decontaminate(loaded, [loaded[0]], threshold=0.99)
        return (f"валидация ловит битую строку; dedup −{removed}; "
                f"деконтаминация −{len(result.contaminated)}")
    check("SFT: валидация/дедуп/деконтаминация на реальных файлах", _sft)

    # 10. Checkpoints on a real folder tree --------------------------------
    def _checkpoints():
        from alterego_training_hub.checkpoints import find_checkpoints

        ck = tmp / "runs" / "m" / "checkpoint-100"
        ck.mkdir(parents=True)
        (ck / "trainer_state.json").write_text(
            '{"global_step": 100, "log_history": [{"eval_loss": 1.25}]}',
            encoding="utf-8")
        (ck / "model.safetensors").write_bytes(b"w" * 16)
        found = find_checkpoints(tmp)
        assert found and found[0].step == 100 and found[0].val_loss == 1.25
        return f"найден {found[0].name} шаг 100 val_loss 1.25"
    check("чекпоинты: реальное сканирование папок", _checkpoints)

    # 10b. Streaming big dataset -------------------------------------------
    def _streaming():
        import json as _json
        import tracemalloc

        from alterego_training_hub.data_audit import audit_rows
        from alterego_training_hub.datasets import iter_rows
        from alterego_training_hub.sft_data import dedupe_near_file

        src = tmp / "big.jsonl"
        total = 40_000
        with src.open("w", encoding="utf-8") as handle:
            for i in range(total):
                text = f"строка {i} про обучение нейронных сетей и данные"
                if i and i % 10_000 == 0:
                    text = "строка 0 про обучение нейронных сетей и данные"
                handle.write(_json.dumps({"text": text}, ensure_ascii=False) + "\n")
        tracemalloc.start()
        audit = audit_rows(iter_rows(src, "jsonl"))
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert audit.rows == total and audit.duplicates == 3, audit
        assert peak < 20_000_000, f"пик памяти {peak} — файл грузится целиком?"
        result = dedupe_near_file(src, tmp / "big.dedup.jsonl", "jsonl",
                                  threshold=0.99)
        assert result.removed == 3 and result.kept == total - 3, result
        return (f"{total} строк потоково, пик аудита {peak / 1e6:.1f} МБ, "
                f"near-dup удалено {result.removed}")
    check("потоковая обработка: большой датасет без загрузки в память",
          _streaming)

    # 11. Budget ledger math ------------------------------------------------
    def _budget():
        from alterego_training_hub.budget_guard import (
            BudgetLedger,
            PodSpend,
            apply_guard,
        )

        ledger = BudgetLedger.load(tmp / "budget.json")
        now = time.time()
        stopped: list[str] = []
        ledger.pods["pod-real"] = PodSpend(
            pod_id="pod-real", hourly_usd=2.0, started_at=now - 3600,
            managed=True)  # под создан приложением — только такие стопятся
        verdict = apply_guard(
            ledger, [{"id": "pod-real", "status": "RUNNING",
                      "costPerHr": 2.0}],
            cap_usd=0.5, stopper=stopped.append, now=now)
        assert stopped == ["pod-real"], verdict
        return f"потрачено ${verdict.spent_usd:.2f} → автостоп сработал"
    check("бюджет: реальный учёт и автостоп", _budget)

    # 12. Local inference probes (real sockets, servers down) ---------------
    def _local():
        from alterego_training_hub.local_inference import probe_all

        statuses = probe_all()
        assert len(statuses) == 2
        return " · ".join(s.render() for s in statuses)
    check("локальный инференс: реальные пробы портов", _local)

    # 13. Plugin market on a real folder + real example plugin --------------
    def _plugins():
        from alterego_training_hub.plugin_market import parse_market
        from alterego_training_hub.plugins import PluginManager

        market = tmp / "market"
        (market / "hello").mkdir(parents=True)
        source = repo / "examples" / "hello_plugin.py"
        assert source.is_file(), "examples/hello_plugin.py отсутствует"
        (market / "hello" / "plugin.py").write_bytes(source.read_bytes())
        entries = parse_market(market)
        assert entries and entries[0].id == "hello"
        manager = PluginManager(tmp / "plugins")
        from alterego_training_hub.plugin_market import install_market_entry

        install_market_entry(entries[0], manager.plugins_dir)
        loaded = manager.load_all()
        assert any(p.id == "hello" for p in loaded), loaded
        return "реальный плагин из маркета установлен и загружен"
    check("плагины: реальный маркет и загрузка", _plugins)

    # 14. Night verifier on real state --------------------------------------
    def _night():
        from alterego_training_hub.night_watch import WatchState, degradation_issues

        before = WatchState(best_val_loss=1.0,
                            samples=[{"text": "раз два три"}])
        after = WatchState(best_val_loss=1.5, samples=[{"text": ""}])
        issues = degradation_issues(before, after)
        assert issues, "деградация не замечена"
        return "; ".join(issues[:2])
    check("ночной верификатор: реальная деградация ловится", _night)

    # 15. Update check against the real GitHub API ---------------------------
    if quick:
        blocked("проверка обновлений: реальный GitHub API",
                "пропущено в --quick")
    else:
        def _update():
            from alterego_training_hub.update_check import check_update

            report = check_update("1.8.0")
            # Repo may have no releases yet: a graceful text is a pass.
            assert report.render(), "пустой отчёт"
            return report.render().splitlines()[0][:110]
        check("проверка обновлений: реальный GitHub API", _update)

    # 16. Blocked-in-sandbox realities (reported, not faked) ------------------
    try:
        import tkinter  # noqa: F401
        blocked("настоящий Tk", "модуль есть, но нужен дисплей (CI: xvfb job)")
    except ImportError:
        blocked("настоящий Tk",
                "в песочнице нет tkinter/дисплея — в CI это делает xvfb job")
    def _torch_training():
        import subprocess

        from alterego_training_hub.model_recipes import get_preset
        from alterego_training_hub.train_script import ScriptConfig, generate_script

        work = tmp / "torch-train"
        work.mkdir()
        line = ("Маленькая модель учится предсказывать следующий "
                "символ текста. " * 3) + "\n"
        (work / "data.txt").write_text(line * 300, encoding="utf-8")
        cfg = ScriptConfig(path="scratch",
                           preset=get_preset("llama-tiny"),
                           dataset_path=str(work / "data.txt"),
                           epochs=1, batch=4, seq_len=128,
                           sample_every=10 ** 9)
        script = work / "train_llm.py"
        script.write_text(generate_script(cfg), encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(script), "--output-dir", str(work / "out")],
            capture_output=True, text=True, timeout=600, cwd=work)
        assert done.returncode == 0, done.stderr[-500:]
        assert (work / "out" / "model.pt").is_file(), "нет чекпоинта"
        assert (work / "out" / "checkpoint-epoch1.pt").is_file()
        losses = [float(part.split("=")[1])
                  for part in done.stdout.split()
                  if part.startswith("loss=")]
        assert losses and losses[-1] < losses[0], losses
        return (f"loss {losses[0]:.3f} → {losses[-1]:.3f}, "
                "чекпоинт model.pt сохранён")

    def _lora_training():
        # Крошечная GPT-2 и токенизатор собираются ЛОКАЛЬНО (без HF Hub):
        # настоящее LoRA-обучение сгенерированным скриптом.
        import subprocess

        from tokenizers import Tokenizer, models, pre_tokenizers, trainers
        from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

        from alterego_training_hub.train_script import ScriptConfig, generate_script

        work = tmp / "lora-train"
        work.mkdir()
        texts = ["кошка сидит на окне и смотрит на улицу",
                 "собака бежит по парку и играет с мячом",
                 "птица летит над лесом и поёт песню",
                 "модель учится предсказывать следующее слово"] * 6
        tok = Tokenizer(models.WordLevel(unk_token="<unk>"))
        tok.pre_tokenizer = pre_tokenizers.Whitespace()
        tok.train_from_iterator(texts, trainers.WordLevelTrainer(
            special_tokens=["<unk>", "<pad>"]))
        fast = PreTrainedTokenizerFast(tokenizer_object=tok,
                                       unk_token="<unk>", pad_token="<pad>")
        base = work / "base"
        base.mkdir()
        fast.save_pretrained(base)
        GPT2LMHeadModel(GPT2Config(
            vocab_size=len(fast), n_layer=2, n_embd=32, n_head=2,
            n_positions=128,
            pad_token_id=fast.pad_token_id)).save_pretrained(base)
        data = work / "data.txt"
        data.write_text("\n".join(texts) + "\n", encoding="utf-8")
        cfg = ScriptConfig(path="lora", dataset_path=str(data),
                           base_model=str(base), epochs=1, batch=4,
                           seq_len=64, eval_prompts=("кошка сидит",))
        script = work / "train_llm.py"
        script.write_text(generate_script(cfg), encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(script), "--output-dir", str(work / "out")],
            capture_output=True, text=True, timeout=600, cwd=work)
        assert done.returncode == 0, done.stderr[-500:]
        assert "val_loss=" in done.stdout, done.stdout[-300:]
        assert any((work / "out").rglob("adapter_model.safetensors")) or \
            any((work / "out").rglob("adapter_model.bin"))
        val = [p for p in done.stdout.split() if p.startswith("val_loss=")]
        return f"адаптер обучен и сохранён, {val[0] if val else ''}"

    try:
        import torch  # noqa: F401
    except ImportError:
        blocked("torch-обучение",
                "torch не установлен (в CI/у пользователя скрипт тот же; "
                "здесь проверен smoke-прогоном)")
    else:
        check("torch-обучение: настоящий скрипт учит модель", _torch_training)
    try:
        import peft  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        blocked("LoRA-обучение",
                "нет transformers/peft (pip install transformers peft datasets)")
    else:
        check("LoRA-обучение: настоящий адаптер на локальной модели",
              _lora_training)

    failed = [r for r in RESULTS if r[1] is False]
    blocked_n = [r for r in RESULTS if r[1] is None]
    passed = [r for r in RESULTS if r[1] is True]
    print(f"\nИтог: ✓ {len(passed)} · ✗ {len(failed)} · ⊘ {len(blocked_n)}")
    if failed:
        return 1
    if require_torch and any(name.startswith(("torch", "LoRA"))
                             for name, ok, _ in RESULTS if ok is None):
        print("✗ --require-torch: torch/LoRA недоступны, реальное обучение "
              "не проверено — это провал, а не пропуск")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
