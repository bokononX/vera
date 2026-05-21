import unittest
from pathlib import Path

from vera_harness.models import AssistantIdentity, OwnerProfile, TelegramTask
from vera_harness.prompt import build_prompt_policy
from vera_harness.user_memory import UserMemoryRetrievalOptions, retrieve_user_memory_for_task


MEMORY_FIXTURE = Path(__file__).parent / "fixtures" / "user_memory"


class PromptPolicyTests(unittest.TestCase):
    def test_policy_prompt_includes_herald_place_vera_and_cat_131_constraints(self):
        task = TelegramTask.from_message(
            chat_id=1,
            user_id=2,
            message_id=3,
            text="Help coordinate a careful project decision.",
        )

        prompt = build_prompt_policy(task).render_prompt()

        required_fragments = [
            "You are Vera",
            "Assistant identity:",
            "User-facing assistant name: Vera",
            "personal assistant/minime",
            "Self-identification rule",
            "Codex/OpenAI tooling is the runtime layer",
            "Herald",
            "faithful representative",
            "The Place",
            "Vera",
            "semantic",
            "empirical",
            "modeling",
            "values/priors",
            "irreducible",
            "Interest surfacing",
            "Face-saving",
            "Minimal disclosure",
            "No sycophancy drift",
            "Reversibility",
            "VERA_TASK_STATUS",
        ]
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, prompt)
        self.assertNotEqual(prompt.splitlines()[0], "You are Herald, a faithful representative of the Telegram user.")

    def test_configured_assistant_identity_override_renders_before_task(self):
        task = TelegramTask.from_message(
            chat_id=1,
            user_id=2,
            message_id=3,
            text="who are you?",
        )
        identity = AssistantIdentity(
            name="Mira",
            short_description="a focused thinking partner",
            mission="Help Victor reason clearly.",
            core_values=("truth",),
            communication_principles=("brief and candid",),
            transparency_rules=("say Codex/OpenAI is runtime when asked",),
            relationship_to_owner="Help the owner as a configured assistant.",
        )

        prompt = build_prompt_policy(task, assistant_identity=identity).render_prompt()

        self.assertLess(prompt.index("User-facing assistant name: Mira"), prompt.index("Task:"))
        self.assertIn("Mission: Help Victor reason clearly.", prompt)
        self.assertIn("Communication principles: brief and candid", prompt)
        self.assertIn("do not default to `I am Codex`", prompt)
        self.assertNotIn("Human identity label:", prompt)

    def test_owner_profile_renders_only_for_matching_telegram_user(self):
        owner = OwnerProfile(
            user_id=200,
            display_name="Vera Owner",
            username="owner_handle",
            role="Vera protects the owner's long-term agency.",
            values=("truth over comfort",),
            priorities=("name tradeoffs early",),
            communication_style=("direct and concrete",),
            escalation_boundaries=("require approval before irreversible actions",),
            wiki_profile_excerpt="The owner prefers concise correction over reassurance.",
        )
        owner_task = TelegramTask.from_message(
            chat_id=100,
            user_id=200,
            message_id=1,
            text="Help me decide.",
        )
        other_task = TelegramTask.from_message(
            chat_id=100,
            user_id=201,
            message_id=2,
            text="Help me decide.",
        )

        owner_prompt = build_prompt_policy(owner_task, owner_profile=owner).render_prompt()
        owner_policy = build_prompt_policy(owner_task, owner_profile=owner)
        other_prompt = build_prompt_policy(other_task, owner_profile=owner).render_prompt()

        self.assertIn("Assistant identity:", owner_prompt)
        self.assertIn("Owner relationship:", owner_prompt)
        self.assertIn("Primary owner Telegram user_id: 200", owner_prompt)
        self.assertIn("direct and concrete", owner_prompt)
        self.assertIn("require approval before irreversible actions", owner_prompt)
        self.assertIn("not an authorization override", owner_prompt)
        self.assertIn("concise correction", owner_prompt)
        self.assertIn("<redacted owner profile>", "\n".join(owner_policy.summary_lines))
        self.assertNotIn("concise correction", "\n".join(owner_policy.summary_lines))
        self.assertNotIn("Owner relationship:", other_prompt)
        self.assertNotIn("direct and concrete", other_prompt)

    def test_user_memory_context_renders_with_provenance_and_caveats(self):
        task = TelegramTask.from_message(
            chat_id=100,
            user_id=200,
            message_id=300,
            text="Implement Herald user memory retrieval with concise engineering status.",
        )
        memory_context = retrieve_user_memory_for_task(
            task,
            UserMemoryRetrievalOptions(
                root=MEMORY_FIXTURE,
                max_pages=5,
                allow_private=True,
            ),
        )

        policy = build_prompt_policy(task, user_memory_context=memory_context)
        prompt = policy.render_prompt()

        self.assertLess(prompt.index("## User Memory Context"), prompt.index("Identity constraints:"))
        self.assertIn("Direct Engineering Updates", prompt)
        self.assertIn("source: src-pref-direct-updates", prompt)
        self.assertIn("confidence: high", prompt)
        self.assertIn("Correction: Status Tone Scope", prompt)
        self.assertIn("User corrected that concise status preferences", prompt)
        self.assertIn("User memory retrieval applied", "\n".join(policy.summary_lines))


if __name__ == "__main__":
    unittest.main()
