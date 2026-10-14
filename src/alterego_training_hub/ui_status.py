"""Status-bar behaviour of the app shell (extracted from ui.py, этап 36)."""
from __future__ import annotations

from .i18n import t


def refresh_status_badges(app) -> None:
    """Right-side status badges: model/provider + training state."""
    try:
        from .ui_patterns import status_badges

        training_text = ""
        try:
            status = app.training.status()
            training_text = t('идёт') if status.running else ""
        except Exception:
            training_text = ""
        badges = status_badges(
            provider=str(getattr(app.settings, "llm_provider", "") or ""),
            model=str(getattr(app.settings, "mentor_model", "") or ""),
            training=training_text,
            tokens_today=int(getattr(app, "_tokens_today", 0) or 0))
        if hasattr(app, "model_badge"):
            app.model_badge.set(badges[0] if badges else "")
        if hasattr(app, "training_badge"):
            app.training_badge.set(badges[1] if len(badges) > 1 else "")
        if hasattr(app, "tokens_badge"):
            app.tokens_badge.set(next(
                (b for b in badges if b.startswith("🎟")), ""))
        app.set_nav_badge("training", "●" if training_text else "")
    except Exception:
        pass
