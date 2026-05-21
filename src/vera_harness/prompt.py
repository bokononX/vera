"""Prompt and policy synthesis for Herald/The Place/Vera aligned Codex runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .models import OwnerProfile, TelegramTask


@dataclass(frozen=True)
class PromptPolicy:
    """Policy summary and prompt text for a Codex run."""

    task: TelegramTask
    identity_constraints: Tuple[str, ...]
    cat_131_principles: Tuple[str, ...]
    operating_limits: Tuple[str, ...]
    status_contract: Tuple[str, ...]
    owner_profile: Optional[OwnerProfile]
    owner_profile_facts: Tuple[str, ...] = ()

    @property
    def summary_lines(self) -> Tuple[str, ...]:
        return (
            self.identity_constraints
            + self.owner_profile_summary_lines
            + self.cat_131_principles
            + self.operating_limits
            + self.status_contract
        )

    @property
    def owner_profile_summary_lines(self) -> Tuple[str, ...]:
        lines = []
        if self.owner_profile is not None:
            owner = self.owner_profile
            lines.extend(
                [
                    "Owner profile applies to primary owner Telegram user_id {}.".format(
                        owner.user_id
                    ),
                    "Owner identity label: {}.".format(owner.display_label(self.task.username)),
                ]
            )
            if owner.communication_style:
                lines.append(
                    "Owner communication style preferences configured: {}.".format(
                        len(owner.communication_style)
                    )
                )
            if owner.wiki_profile_path is not None:
                lines.append("Refreshable owner profile source: {}".format(owner.wiki_profile_path))
            if owner.wiki_profile_excerpt:
                lines.append("Refreshable owner profile facts: <redacted owner profile>.")
        if self.owner_profile_facts:
            lines.append(
                "Confirmed owner profile guidance configured: {} redacted entries.".format(
                    len(self.owner_profile_facts)
                )
            )
        return tuple(lines)

    @property
    def owner_profile_lines(self) -> Tuple[str, ...]:
        if self.owner_profile is None:
            return ()
        owner = self.owner_profile
        lines = [
            "Primary owner Telegram user_id: {}".format(owner.user_id),
            "Human identity label: {}".format(owner.display_label(self.task.username)),
            "Vera's role for the owner: {}".format(
                owner.role
                or "act as a faithful, careful representative and coordination aide for the owner"
            ),
            "Owner identity is relationship context, not an authorization override; safety, truthfulness, governance, and explicit approval boundaries still apply.",
        ]
        lines.extend(_prefixed_lines("Values to respect", owner.values))
        lines.extend(_prefixed_lines("Current priorities", owner.priorities))
        lines.extend(_prefixed_lines("Communication style preferences", owner.communication_style))
        lines.extend(_prefixed_lines("Escalation/refusal boundaries", owner.escalation_boundaries))
        if owner.wiki_profile_path is not None:
            lines.append("Refreshable profile source: {}".format(owner.wiki_profile_path))
        if owner.wiki_profile_excerpt:
            lines.append("Refreshable owner profile facts:")
            lines.extend(
                "  {}".format(line)
                for line in owner.wiki_profile_excerpt.splitlines()
                if line.strip()
            )
        return tuple(lines)

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
        if self.owner_profile_lines:
            sections.extend(["", "Owner relationship:"])
            sections.extend("- {}".format(item) for item in self.owner_profile_lines)
        if self.owner_profile_facts:
            sections.extend(["", "Confirmed owner profile guidance:"])
            sections.extend("- {}".format(item) for item in self.owner_profile_facts)
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
    owner_profile: Optional[OwnerProfile] = None,
    owner_profile_facts: Tuple[str, ...] = (),
) -> PromptPolicy:
    session_owner_profile = owner_profile if owner_profile and owner_profile.matches(task) else None
    session_owner_profile_facts = (
        owner_profile_facts
        if session_owner_profile is not None or owner_profile is None
        else ()
    )
    return PromptPolicy(
        task=task,
        identity_constraints=(
            "Herald advocates for the user without pretending to be the user or making final human value judgments.",
            "The Place is the coordination environment: reduce avoidable confusion, social friction, and unnecessary blame before humans engage.",
            "Vera is the protocol state underneath the work: preserve trust, verification discipline, governance boundaries, and context-specific disclosure.",
        ),
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
        owner_profile=session_owner_profile,
        owner_profile_facts=session_owner_profile_facts,
    )


def _prefixed_lines(prefix: str, values: Tuple[str, ...]) -> Tuple[str, ...]:
    return tuple("{}: {}".format(prefix, value) for value in values)
