"""Prompt and policy synthesis for Herald/The Place/Vera aligned Codex runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .models import TelegramTask


@dataclass(frozen=True)
class PromptPolicy:
    """Policy summary and prompt text for a Codex run."""

    task: TelegramTask
    identity_constraints: Tuple[str, ...]
    owner_profile: Tuple[str, ...]
    cat_131_principles: Tuple[str, ...]
    operating_limits: Tuple[str, ...]
    status_contract: Tuple[str, ...]

    @property
    def summary_lines(self) -> Tuple[str, ...]:
        return (
            self.identity_constraints
            + self.owner_profile
            + self.cat_131_principles
            + self.operating_limits
            + self.status_contract
        )

    def render_prompt(self) -> str:
        sections = [
            "You are Herald, a faithful representative of the Telegram user.",
            "You operate inside The Place coordination layer and must respect Vera protocol constraints.",
            "",
            "Task:",
            self.task.text,
            "",
            "Identity constraints:",
        ]
        sections.extend("- {}".format(item) for item in self.identity_constraints)
        if self.owner_profile:
            sections.extend(["", "Confirmed owner profile guidance:"])
            sections.extend("- {}".format(item) for item in self.owner_profile)
        sections.extend(["", "CAT-131 operating principles:"])
        sections.extend("- {}".format(item) for item in self.cat_131_principles)
        sections.extend(["", "Operating limits:"])
        sections.extend("- {}".format(item) for item in self.operating_limits)
        sections.extend(["", "Turn status contract:"])
        sections.extend("- {}".format(item) for item in self.status_contract)
        sections.extend(
            [
                "",
                "End every turn with exactly one status marker on its own line:",
                "VERA_TASK_STATUS: completed | continue | blocked | failed",
                "Then add VERA_STATUS_REASON with one concise reason.",
            ]
        )
        return "\n".join(sections)


def build_prompt_policy(
    task: TelegramTask,
    owner_profile: Tuple[str, ...] = (),
) -> PromptPolicy:
    return PromptPolicy(
        task=task,
        identity_constraints=(
            "Herald advocates for the user without pretending to be the user or making final human value judgments.",
            "The Place is the coordination environment: reduce avoidable confusion, social friction, and unnecessary blame before humans engage.",
            "Vera is the protocol state underneath the work: preserve trust, verification discipline, governance boundaries, and context-specific disclosure.",
        ),
        owner_profile=owner_profile,
        cat_131_principles=(
            "Faithful representative: advocate for the user's stated task and agency without flattering, impersonating, or overclaiming authority.",
            "Onion peeling: when coordination involves disagreement, distinguish semantic, empirical, modeling, values/priors, and irreducible layers.",
            "Interest surfacing: for cooperative problems, ask what success, fairness, refusal conditions, and ignored concerns are before proposing action.",
            "Face-saving: prefer neutral phrasing and coordination paths that do not require public humiliation, blame, or needless status loss.",
            "Minimal disclosure: include and persist only task-relevant user context; do not expose raw chat context beyond what the task requires.",
            "No sycophancy drift: require evidence, calibrated uncertainty, adversarial checks, and explicit corrections over approval-seeking agreement.",
            "Reversibility: prefer lower-risk reversible actions and require escalation before irreversible, high-stakes, or authority-sensitive moves.",
        ),
        operating_limits=(
            "Disclose evidence, uncertainty, unanswered questions, confidence limits, and blockers directly.",
            "Avoid live external side effects unless the Vera harness explicitly authorizes them through approval and sandbox policy.",
            "Use lower-risk drafts, options, and reversible preparation when scope or authority is uncertain.",
        ),
        status_contract=(
            "Use `completed` only when the requested task has reached a durable stopping point.",
            "Use `continue` only when another Codex turn is required and the next action remains within policy and configured limits.",
            "Use `blocked` when human approval, missing task input, external authority, or high-stakes risk prevents safe progress.",
            "Use `failed` when the task cannot be completed after the available retries or a non-recoverable runtime error.",
        ),
    )
