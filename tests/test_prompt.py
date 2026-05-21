import unittest

from vera_harness.models import OwnerProfile, TelegramTask
from vera_harness.prompt import build_prompt_policy


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


if __name__ == "__main__":
    unittest.main()
