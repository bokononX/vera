import unittest

from vera_harness.models import TelegramTask
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


if __name__ == "__main__":
    unittest.main()
