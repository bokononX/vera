import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from vera_harness.user_memory import (
    IngestOptions,
    MemoryState,
    PageType,
    SourceRetention,
    ingest_user_memory,
    load_messages_from_file,
    messages_from_json_payload,
    parse_conversation_text,
)


CAPTURED_AT = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)


class UserMemoryExtractionTests(unittest.TestCase):
    def test_extracts_required_candidate_types_and_classifications(self):
        fixture_path = Path(__file__).parent / "fixtures" / "sample_conversation.txt"
        messages, source_text = load_messages_from_file(fixture_path)

        with tempfile.TemporaryDirectory() as temp_dir:
            plan = ingest_user_memory(
                messages=messages,
                source_text=source_text,
                options=_options(Path(temp_dir)),
            )

        by_type = {candidate.page_type for candidate in plan.candidates}
        self.assertIn(PageType.CONCEPT, by_type)
        self.assertIn(PageType.VALUE, by_type)
        self.assertIn(PageType.PREFERENCE, by_type)
        self.assertIn(PageType.PROJECT, by_type)
        self.assertIn(PageType.PERSON, by_type)
        self.assertIn(PageType.ORG, by_type)
        self.assertIn(PageType.DECISION, by_type)
        self.assertIn(PageType.OPEN_QUESTION, by_type)
        self.assertIn(PageType.OBSERVATION, by_type)

        states = {candidate.memory_state for candidate in plan.candidates}
        self.assertIn(MemoryState.CONFIRMED, states)
        self.assertIn(MemoryState.INFERRED, states)
        self.assertIn(MemoryState.OBSERVED_PATTERN, states)
        self.assertIn(MemoryState.OPEN_QUESTION, states)
        self.assertFalse(any("remember everything" in candidate.claim for candidate in plan.candidates))

    def test_normalized_telegram_json_ingest_path(self):
        messages = messages_from_json_payload(
            [
                {
                    "message_id": 42,
                    "text": "I value minimal disclosure.",
                    "received_at": "2026-05-20T12:00:00Z",
                }
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            plan = ingest_user_memory(
                messages=messages,
                source_text="telegram-json",
                options=_options(Path(temp_dir), channel="telegram"),
            )

        self.assertEqual(len(plan.candidates), 1)
        candidate = plan.candidates[0]
        self.assertEqual(candidate.page_type, PageType.VALUE)
        self.assertEqual(candidate.memory_state, MemoryState.CONFIRMED)
        self.assertEqual(candidate.source_refs[0].locator, "message:42")


class UserMemoryApplyTests(unittest.TestCase):
    def test_dry_run_does_not_mutate_files_and_renders_plan(self):
        messages = parse_conversation_text("User: I prefer concise updates.")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "memory")
            plan = ingest_user_memory(
                messages=messages,
                source_text="User: I prefer concise updates.",
                options=_options(root),
            )

            self.assertFalse(root.exists())
            rendered = plan.format_human_readable()
            self.assertIn("User memory ingest plan (dry-run)", rendered)
            self.assertIn("wiki/preferences/concise-updates.md", rendered)
            self.assertIn("Dry-run only: no files were mutated.", rendered)

    def test_apply_creates_pages_index_log_and_hash_only_source_metadata(self):
        messages = parse_conversation_text(
            "User: I prefer concise engineering updates.\n"
            "User: Open question: what review cadence should Vera use?"
        )
        source_text = "\n".join(message.text for message in messages)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "memory")
            plan = ingest_user_memory(
                messages=messages,
                source_text=source_text,
                options=_options(root),
                apply=True,
            )

            preference_page = root / "wiki" / "preferences" / "concise-engineering-updates.md"
            question_page = root / "wiki" / "questions" / "question-what-review-cadence-should-vera-use.md"
            self.assertTrue(preference_page.exists())
            self.assertTrue(question_page.exists())
            self.assertIn("User prefers concise engineering updates.", preference_page.read_text())
            self.assertIn("Concise Engineering Updates", (root / "index.md").read_text())
            self.assertIn(plan.source_record.source_id, (root / "log.md").read_text())
            manifest = (root / "raw" / "manifest.jsonl").read_text()
            self.assertIn('"retention": "hash_only"', manifest)
            redaction = (root / plan.source_record.path).read_text()
            self.assertIn('"raw_content": "not retained"', redaction)
            self.assertNotIn("I prefer concise engineering updates", redaction)

    def test_existing_page_is_updated_instead_of_duplicated(self):
        messages = parse_conversation_text("User: I prefer concise updates.")
        source_text = "User: I prefer concise updates."

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "memory")
            options = _options(root)
            ingest_user_memory(messages, source_text, options, apply=True)
            second_plan = ingest_user_memory(messages, source_text, options, apply=True)

            pages = list((root / "wiki" / "preferences").glob("*.md"))
            self.assertEqual([page.name for page in pages], ["concise-updates.md"])
            self.assertTrue(all(edit.action == "unchanged" for edit in second_plan.edits))
            log_lines = [
                line
                for line in (root / "log.md").read_text().splitlines()
                if "src-test" in line
            ]
            self.assertEqual(len(log_lines), 1)

    def test_correction_records_contradiction_without_overwriting_old_claim(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "memory")
            existing = root / "wiki" / "preferences" / "concise-status-updates.md"
            existing.parent.mkdir(parents=True)
            existing.write_text(
                "\n".join(
                    [
                        "---",
                        "id: mem-preference-concise-status-updates",
                        "title: Concise Status Updates",
                        "page_type: preference",
                        "owner_user: user-test",
                        "status: active",
                        "memory_state: confirmed",
                        "confidence:",
                        "  level: high",
                        "  score: 0.90",
                        "sensitivity: private",
                        "prompt_visibility: task_only",
                        "review_status: user_confirmed",
                        "created_at: 2026-05-20T00:00:00Z",
                        "updated_at: 2026-05-20T00:00:00Z",
                        "last_observed_at: 2026-05-20T00:00:00Z",
                        "last_confirmed_at: 2026-05-20T00:00:00Z",
                        "stale_after: P90D",
                        "source_refs: []",
                        "related: []",
                        "supersedes: []",
                        "superseded_by: []",
                        "contradictions: []",
                        "corrections: []",
                        "tags: [preference]",
                        "---",
                        "",
                        "# Concise Status Updates",
                        "",
                        "User prefers long narrative updates.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            messages = parse_conversation_text(
                "User: Actually, I prefer concise status updates, not long narrative updates."
            )

            plan = ingest_user_memory(
                messages=messages,
                source_text=messages[0].text,
                options=_options(root),
                apply=True,
            )

            updated = existing.read_text()
            self.assertIn("status: contested", updated)
            self.assertIn("User prefers long narrative updates.", updated)
            self.assertIn("User prefers concise status updates.", updated)
            self.assertTrue((root / "wiki" / "corrections" / "correction-concise-status-updates.md").exists())
            contradictions = (root / "review" / "contradictions.md").read_text()
            self.assertIn("concise-status-updates.md", contradictions)
            self.assertIn(plan.source_record.source_id, contradictions)

    def test_secret_like_claims_are_withheld(self):
        messages = parse_conversation_text(
            "User: My API key is abc123.\nUser: I value privacy."
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            plan = ingest_user_memory(
                messages=messages,
                source_text="secret source",
                options=_options(Path(temp_dir)),
            )

        self.assertEqual(plan.withheld_secret_count, 1)
        self.assertEqual(len(plan.candidates), 1)
        self.assertNotIn("abc123", plan.format_human_readable())


def _options(root: Path, channel: str = "codex") -> IngestOptions:
    return IngestOptions(
        root=root,
        owner_user="user-test",
        channel=channel,
        source_id="src-test",
        captured_at=CAPTURED_AT,
        source_retention=SourceRetention.HASH_ONLY,
    )


if __name__ == "__main__":
    unittest.main()
