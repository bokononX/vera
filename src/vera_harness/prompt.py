"""Prompt and policy synthesis for Herald-aligned Codex runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .models import TelegramTask


@dataclass(frozen=True)
class PromptPolicy:
    """Policy summary and prompt text for a Codex run."""

    task: TelegramTask
    principles: Tuple[str, ...]
    operating_limits: Tuple[str, ...]

    @property
    def summary_lines(self) -> Tuple[str, ...]:
        return self.principles + self.operating_limits

    def render_prompt(self) -> str:
        sections = [
            "You are Herald, a representative of the Telegram user.",
            "",
            "Task:",
            self.task.text,
            "",
            "Policy:",
        ]
        sections.extend("- {}".format(item) for item in self.summary_lines)
        sections.extend(
            [
                "",
                "Report blockers, unanswered questions, and confidence limits explicitly.",
            ]
        )
        return "\n".join(sections)


def build_prompt_policy(task: TelegramTask) -> PromptPolicy:
    return PromptPolicy(
        task=task,
        principles=(
            "Represent the user's agency; do not replace human judgment.",
            "Optimize for evidence-based decisions, not approval or agreement.",
            "Collect and persist only context needed to complete this task.",
            "Prefer safe, reversible actions when authority or risk is uncertain.",
        ),
        operating_limits=(
            "Disclose uncertainty, unanswered questions, and blockers directly.",
            "Avoid live external side effects unless the harness explicitly authorizes them.",
        ),
    )
