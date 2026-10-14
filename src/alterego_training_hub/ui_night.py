"""Night-watch behaviour of the app shell (extracted from ui.py, этап 36).

Free functions taking the app instance; TrainingHubApp keeps thin wrapper
methods so existing call sites and tests are untouched.
"""
from __future__ import annotations

import time

from .config import app_data_dir
from .i18n import t


def night_watch_log(app):
    from .night_watch import NightWatchLog

    return NightWatchLog(app_data_dir() / "night-watch.json")

def night_watch_maybe(app) -> None:
    """Throttled tick: run a night check when the window/interval allow."""
    if not getattr(app.settings, "night_watch_enabled", False):
        return
    now = time.time()
    if now - float(getattr(app, "_night_tick_at", 0.0)) < 60.0:
        return
    app._night_tick_at = now
    try:
        from .night_watch import WatchConfig, due

        config = WatchConfig(
            enabled=True,
            interval_minutes=int(
                getattr(app.settings, "night_watch_interval", 30) or 30))
        if not config.in_window(now):
            return
        log = app.night_watch_log()
        entries = log.entries()
        last = entries[-1].at if entries else 0.0
        if not due(last, now=now,
                   interval_minutes=config.interval_minutes):
            return
    except Exception:
        return
    if getattr(app, "_night_running", False):
        return
    app._night_running = True

    def work():
        try:
            return app.run_night_check()
        finally:
            app._night_running = False

    app.start_async(t('Ночная проверка'), work)

def run_night_check(app):
    """Collect one snapshot and ask the mentor to analyse it."""
    from .dashboard import build_dashboard
    from .metrics import parse_log
    from .night_watch import run_check
    from .watchdog import detect_issues

    tail = app.training.tail()
    summary = parse_log(tail)
    issues = [issue.line() for issue in detect_issues(
        summary, running=app.training.status().running)]
    # Верификатор (этап 38): сравнение с прошлым снимком — деградация
    # генераций/val_loss попадает в замечания и утренний итог.
    try:
        from .config import app_data_dir as _data_dir
        from .night_watch import (
            degradation_issues,
            load_state,
            save_state,
            state_from_tail,
        )

        _state_path = _data_dir() / "night-watch-state.json"
        _current = state_from_tail(tail)
        issues.extend(degradation_issues(load_state(_state_path), _current))
        save_state(_state_path, _current)
    except Exception:
        pass
    dashboard = build_dashboard(summary, title=t('Ночной снимок'))
    entry = run_check(app.mentor_client(), tail=tail, dashboard=dashboard,
                      issues=issues)
    app.night_watch_log().add(entry)
    app.activity.log("night", entry.line())
    app.set_status(t('Ночная проверка: ') + entry.summary)
    return entry

def morning_report_text(app) -> str:
    from .night_watch import morning_report

    actions = []
    chat = app.pages.get("chat")
    session = getattr(chat, "session", None)
    if session is not None:
        try:
            from .action_trace import action_entries_from_messages

            actions = action_entries_from_messages(session.messages)
        except Exception:
            actions = []
    return morning_report(app.night_watch_log().entries(), actions=actions)

