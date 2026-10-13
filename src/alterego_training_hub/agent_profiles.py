"""Agent behaviour profiles: one-click presets for common jobs.

Profiles only set pure preferences (steps, reasoning, verification, extra
prompt); they never carry credentials and never touch the network.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    id: str
    label: str
    max_steps: int
    reasoning: str  # off | low | medium | high
    verify: bool
    subagents: bool
    extra: str


AGENT_PROFILES: dict[str, AgentProfile] = {
    "mentor": AgentProfile(
        id="mentor",
        label="Наставник",
        max_steps=8,
        reasoning="medium",
        verify=True,
        subagents=False,
        extra="Объясняй действия и предлагай улучшения; веди обучающий тон.",
    ),
    "reviewer": AgentProfile(
        id="reviewer",
        label="Ревьюер кода",
        max_steps=12,
        reasoning="high",
        verify=True,
        subagents=False,
        extra="Фокус: точное ревью изменений, диффы, риски и соответствие стилю. "
              "Не выполняй мутации без явного запроса.",
    ),
    "trainer": AgentProfile(
        id="trainer",
        label="Оптимизатор обучения",
        max_steps=16,
        reasoning="medium",
        verify=True,
        subagents=True,
        extra="Фокус: метрики обучения, корректировка lr/эпох через "
              "set_training_control, отслеживание аномалий и плато.",
    ),
    "full": AgentProfile(
        id="full",
        label="Полный агент",
        max_steps=25,
        reasoning="high",
        verify=True,
        subagents=True,
        extra="Действуй автономно, планируй шаги (update_plan), проверяй результат "
              "самопроверкой и докладывай вердиктом.",
    ),
}

DEFAULT_PROFILE_ID = "mentor"


def profile_ids() -> list[str]:
    return list(AGENT_PROFILES)


def profile_labels() -> list[str]:
    return [AGENT_PROFILES[pid].label for pid in AGENT_PROFILES]


def profile_info(profile_id: str) -> AgentProfile:
    return AGENT_PROFILES.get(str(profile_id), AGENT_PROFILES[DEFAULT_PROFILE_ID])


def profile_id_by_label(label: str) -> str:
    for profile in AGENT_PROFILES.values():
        if profile.label == label:
            return profile.id
    return DEFAULT_PROFILE_ID


def apply_profile(settings, profile_id: str) -> AgentProfile:
    """Write a profile's preferences into an AppSettings-like object."""
    profile = profile_info(profile_id)
    settings.agent_profile = profile.id
    settings.agent_max_steps = profile.max_steps
    settings.agent_reasoning = profile.reasoning
    settings.agent_verify = profile.verify
    settings.agent_subagents = profile.subagents
    settings.agent_system_extra = profile.extra
    return profile
