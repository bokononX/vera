import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vera_harness.models import TelegramTask
from vera_harness.owner_questions import (
    JsonOwnerQuestionQueueStore,
    OwnerQuestionQueue,
    OwnerQuestionQueueError,
    OwnerQuestionStatus,
    OwnerQuestionSubjectRef,
)
from vera_harness.user_memory import UserMemoryRetrievalOptions, retrieve_user_memory_for_task


NOW = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)


class OwnerQuestionQueueTests(unittest.TestCase):
    def test_enqueue_dedupes_near_identical_subject_question_and_persists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = _queue(Path(temp_dir, "questions.json"))
            subject = OwnerQuestionSubjectRef(
                kind="imessage_contact",
                subject_id="imessage:+15550100",
                label="Alice Example",
            )

            first = queue.enqueue_question(
                "Who is Alice Example, and how should I understand your relationship with them?",
                source="imessage_contact_discovery",
                subject_ref=subject,
                priority=2,
                now=NOW,
            )
            second = queue.enqueue_question(
                "Who is Alice Example and what is your relationship to them?",
                source="imessage_contact_discovery",
                subject_ref=subject,
                priority=7,
                metadata={"producer": "contacts"},
                now=NOW + timedelta(minutes=1),
            )

            self.assertEqual(first.question_id, second.question_id)
            self.assertEqual(second.priority, 7)
            self.assertEqual(second.metadata["producer"], "contacts")
            self.assertEqual(len(queue.list_questions()), 1)

            reopened = _queue(Path(temp_dir, "questions.json"))
            persisted = reopened.get_question(first.question_id)
            self.assertEqual(persisted.question_text, first.question_text)
            self.assertEqual(persisted.status, OwnerQuestionStatus.PENDING)
            self.assertEqual(persisted.subject_ref, subject)

    def test_select_next_respects_priority_cooldown_asked_and_deferred_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = _queue(Path(temp_dir, "questions.json"))
            low = queue.enqueue_question(
                "What project is Foxtrot?",
                source="memory_gap",
                priority=1,
                now=NOW,
            )
            high = queue.enqueue_question(
                "What is your relationship to Bob?",
                source="relationship_context",
                subject_ref=OwnerQuestionSubjectRef(
                    kind="person",
                    subject_id="person:bob",
                    label="Bob",
                ),
                priority=10,
                do_not_ask_before=NOW + timedelta(hours=1),
                now=NOW,
            )
            mid = queue.enqueue_question(
                "Are there boundaries I should remember for work messages?",
                source="preference_gap",
                priority=5,
                now=NOW,
            )

            self.assertEqual(queue.select_next_pending_question(now=NOW), mid)
            self.assertEqual(queue.select_next_pending_question(now=NOW + timedelta(hours=2)), high)

            asked = queue.mark_asked(high.question_id, now=NOW + timedelta(hours=2))
            self.assertEqual(asked.status, OwnerQuestionStatus.ASKED)
            self.assertEqual(asked.ask_count, 1)
            self.assertEqual(queue.select_next_pending_question(now=NOW + timedelta(hours=2)), mid)

            deferred = queue.defer_question(
                high.question_id,
                do_not_ask_before=NOW + timedelta(hours=4),
                now=NOW + timedelta(hours=2, minutes=5),
            )
            self.assertEqual(deferred.status, OwnerQuestionStatus.PENDING)
            self.assertEqual(queue.select_next_pending_question(now=NOW + timedelta(hours=3)), mid)
            selected_after_cooldown = queue.select_next_pending_question(now=NOW + timedelta(hours=5))
            self.assertIsNotNone(selected_after_cooldown)
            if selected_after_cooldown is not None:
                self.assertEqual(selected_after_cooldown.question_id, high.question_id)

            queue.dismiss_question(mid.question_id, reason="owner_declined", now=NOW + timedelta(hours=5))
            selected_after_dismiss = queue.select_next_pending_question(now=NOW + timedelta(hours=5))
            self.assertIsNotNone(selected_after_dismiss)
            if selected_after_dismiss is not None:
                self.assertEqual(selected_after_dismiss.question_id, high.question_id)
            queue.dismiss_question(high.question_id, reason="owner_declined", now=NOW + timedelta(hours=5))
            self.assertEqual(queue.select_next_pending_question(now=NOW + timedelta(hours=5)), low)

    def test_mark_answered_writes_explicit_user_memory_with_question_provenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue_path = temp / "questions.json"
            memory_root = temp / "memory"
            queue = _queue(queue_path)
            question = queue.enqueue_question(
                "Who is Alice Example, and how should I understand your relationship with them?",
                source="relationship_context",
                subject_ref=OwnerQuestionSubjectRef(
                    kind="person",
                    subject_id="person:alice",
                    label="Alice Example",
                ),
                priority=9,
                now=NOW,
            )

            answered = queue.mark_answered(
                question.question_id,
                "Alice Example is my sister and a close collaborator on home projects.",
                memory_root=memory_root,
                owner_user="owner-test",
                now=NOW + timedelta(minutes=3),
            )

            self.assertEqual(answered.status, OwnerQuestionStatus.ANSWERED)
            self.assertTrue(answered.answer_hash.startswith("sha256:"))
            self.assertEqual(len(answered.answer_memory_refs), 1)
            memory_ref = answered.answer_memory_refs[0]
            self.assertEqual(memory_ref.path, "wiki/people/alice-example.md")
            self.assertEqual(memory_ref.locator, "owner_question:{}".format(question.question_id))

            page_text = (memory_root / memory_ref.path).read_text(encoding="utf-8")
            self.assertIn("page_type: person", page_text)
            self.assertIn("memory_state: confirmed", page_text)
            self.assertIn("review_status: user_confirmed", page_text)
            self.assertIn("Owner-provided context about Alice Example", page_text)
            self.assertIn("owner_question:{}".format(question.question_id), page_text)
            self.assertIn(memory_ref.source_id, (memory_root / "log.md").read_text(encoding="utf-8"))

            raw_state = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertNotIn("sister", json.dumps(raw_state))
            redaction_path = memory_root / "raw" / "redactions" / "{}.json".format(
                memory_ref.source_id
            )
            redaction = redaction_path.read_text(encoding="utf-8")
            self.assertIn('"raw_content": "not retained"', redaction)
            self.assertNotIn("sister", redaction)

            context = retrieve_user_memory_for_task(
                TelegramTask.from_message(
                    chat_id=100,
                    user_id=200,
                    message_id=300,
                    text="Coordinate with Alice Example.",
                    received_at=NOW,
                ),
                UserMemoryRetrievalOptions(root=memory_root, allow_private=True),
            )
            prompt_block = context.render_prompt_block()
            self.assertIn("Alice Example", prompt_block)
            self.assertIn(memory_ref.source_id, prompt_block)

            reopened = _queue(queue_path)
            persisted = reopened.get_question(question.question_id)
            self.assertEqual(persisted.status, OwnerQuestionStatus.ANSWERED)
            self.assertEqual(persisted.answer_memory_refs[0].path, memory_ref.path)

    def test_secret_like_answer_is_not_written_to_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = _queue(Path(temp_dir, "questions.json"))
            question = queue.enqueue_question(
                "What credential should I remember?",
                source="memory_gap",
                now=NOW,
            )

            with self.assertRaises(OwnerQuestionQueueError):
                queue.mark_answered(
                    question.question_id,
                    "The API key is abc123.",
                    memory_root=Path(temp_dir, "memory"),
                    owner_user="owner-test",
                    now=NOW,
                )

            persisted = queue.get_question(question.question_id)
            self.assertEqual(persisted.status, OwnerQuestionStatus.PENDING)


def _queue(path: Path) -> OwnerQuestionQueue:
    return OwnerQuestionQueue(JsonOwnerQuestionQueueStore(path))
