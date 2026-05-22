import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from vera_harness.user_memory import (
    IngestOptions,
    MemoryState,
    PageType,
    SourceRetention,
    WikiLintOptions,
    UserMemoryRetrievalOptions,
    UserMemoryControlController,
    ingest_user_memory,
    lint_user_memory,
    load_user_memory_page,
    load_messages_from_file,
    messages_from_json_payload,
    parse_conversation_text,
    retrieve_user_memory_for_task,
)
from vera_harness.models import TelegramTask


CAPTURED_AT = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)
MEMORY_FIXTURE = Path(__file__).parent / "fixtures" / "user_memory"


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


class UserMemoryRetrievalTests(unittest.TestCase):
    def test_retrieves_bounded_relevant_pages_with_guardrail_caveats(self):
        task = TelegramTask.from_message(
            chat_id=100,
            user_id=200,
            message_id=300,
            text="Implement Herald user memory retrieval and give concise engineering status.",
        )

        context = retrieve_user_memory_for_task(
            task,
            UserMemoryRetrievalOptions(
                root=MEMORY_FIXTURE,
                max_pages=5,
                allow_private=True,
            ),
        )

        used_paths = {page.relative_path for page in context.selected_pages}
        self.assertLessEqual(len(context.selected_pages), 5)
        self.assertIn("wiki/projects/herald-user-memory.md", used_paths)
        self.assertIn("wiki/preferences/direct-engineering-updates.md", used_paths)
        self.assertIn("wiki/corrections/status-tone-scope.md", used_paths)
        self.assertTrue(any("engineering updates" in fact for fact in context.facts))
        self.assertTrue(any("Status Tone Scope" in caveat for caveat in context.caveats))

    def test_default_privacy_filter_excludes_private_and_restricted_memory(self):
        task = TelegramTask.from_message(
            chat_id=100,
            user_id=200,
            message_id=301,
            text="Use concise engineering status and medical memory.",
        )

        context = retrieve_user_memory_for_task(
            task,
            UserMemoryRetrievalOptions(root=MEMORY_FIXTURE, max_pages=5),
        )
        block = context.render_prompt_block()

        self.assertNotIn("Direct Engineering Updates", block)
        self.assertNotIn("Private Medical Detail", block)
        self.assertNotIn("Secret Token Handling", block)
        self.assertGreaterEqual(context.omitted_private_count, 1)
        self.assertGreaterEqual(context.omitted_sensitive_count, 1)

    def test_prompt_block_marks_provenance_confidence_and_open_questions(self):
        task = TelegramTask.from_message(
            chat_id=100,
            user_id=200,
            message_id=302,
            text="Plan Herald memory review cadence for prompt retrieval.",
        )

        context = retrieve_user_memory_for_task(
            task,
            UserMemoryRetrievalOptions(
                root=MEMORY_FIXTURE,
                max_pages=5,
                allow_private=True,
            ),
        )
        block = context.render_prompt_block()

        self.assertIn("## User Memory Context", block)
        self.assertIn("page: wiki/questions/memory-review-cadence.md", block)
        self.assertIn("source: src-question-review-cadence", block)
        self.assertIn("confidence: low", block)
        self.assertIn("Open question:", block)
        self.assertIn("Confirmation constraints:", block)
        self.assertIn("confirm_first", block)


class UserMemoryControlTests(unittest.TestCase):
    def test_lists_memory_with_source_confidence_and_sensitivity_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _copy_memory_fixture(temp_dir)
            controller = UserMemoryControlController()

            response = controller.handle(
                _telegram_task("what do you remember about engineering updates?"),
                root,
            )

            self.assertIn("Direct Engineering Updates", response)
            self.assertIn("confidence: high", response)
            self.assertIn("sensitivity: private", response)
            self.assertIn("source: src-pref-direct-updates", response)

    def test_correction_updates_active_claim_and_keeps_correction_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _copy_memory_fixture(temp_dir)
            controller = UserMemoryControlController()

            response = controller.handle(
                _telegram_task(
                    "correct engineering updates to User prefers narrative engineering updates for planning."
                ),
                root,
            )

            self.assertIn("Updated Direct Engineering Updates", response)
            page = load_user_memory_page(root, "wiki/preferences/direct-engineering-updates.md")
            self.assertIsNotNone(page)
            assert page is not None
            self.assertIn("narrative engineering updates", page.summary)
            self.assertTrue(page.corrections)
            correction_page = root / page.corrections[0]
            self.assertTrue(correction_page.exists())
            context = retrieve_user_memory_for_task(
                _telegram_task("Use engineering updates for planning."),
                UserMemoryRetrievalOptions(root=root, allow_private=True),
            )
            prompt_block = context.render_prompt_block()
            self.assertIn("narrative engineering updates", prompt_block)
            self.assertNotIn("concrete validation evidence", prompt_block)

    def test_forget_tombstones_page_updates_index_log_and_retrieval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _copy_memory_fixture(temp_dir)
            controller = UserMemoryControlController()

            response = controller.handle(_telegram_task("forget medical detail"), root)

            self.assertIn("Forgot 1 memory page", response)
            page_text = (root / "wiki" / "preferences" / "private-medical-detail.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("status: deleted", page_text)
            self.assertIn("memory_state: retracted", page_text)
            self.assertNotIn("Restricted health-related preference exists", page_text)
            self.assertNotIn("Private Medical Detail", (root / "index.md").read_text(encoding="utf-8"))
            self.assertIn("memory-control forget", (root / "log.md").read_text(encoding="utf-8"))
            context = retrieve_user_memory_for_task(
                _telegram_task("Use medical memory."),
                UserMemoryRetrievalOptions(root=root, allow_private=True, allow_restricted=True),
            )
            self.assertFalse(
                any(page.relative_path == "wiki/preferences/private-medical-detail.md" for page in context.selected_pages)
            )

    def test_mark_this_as_sensitive_uses_last_listed_memory_and_excludes_retrieval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _copy_memory_fixture(temp_dir)
            controller = UserMemoryControlController()

            controller.handle(_telegram_task("what do you remember about engineering updates?"), root)
            response = controller.handle(_telegram_task("mark this as sensitive"), root)

            self.assertIn("Marked Direct Engineering Updates as `restricted`", response)
            page = load_user_memory_page(root, "wiki/preferences/direct-engineering-updates.md")
            self.assertIsNotNone(page)
            assert page is not None
            self.assertEqual(page.sensitivity, "restricted")
            self.assertEqual(page.prompt_visibility, "confirm_first")
            context = retrieve_user_memory_for_task(
                _telegram_task("Use concise engineering updates."),
                UserMemoryRetrievalOptions(root=root, allow_private=True, allow_restricted=False),
            )
            self.assertGreaterEqual(context.omitted_sensitive_count, 1)
            self.assertFalse(
                any(page.relative_path == "wiki/preferences/direct-engineering-updates.md" for page in context.selected_pages)
            )

    def test_high_sensitivity_inferred_memory_requires_confirmation_before_storage(self):
        messages = parse_conversation_text("User: I might prefer medical triage reminders.")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "memory")
            plan = ingest_user_memory(
                messages=messages,
                source_text=messages[0].text,
                options=_options(root),
                apply=True,
            )

            self.assertEqual(len(plan.confirmation_required_candidates), 1)
            self.assertFalse((root / "wiki" / "preferences").exists() and list((root / "wiki" / "preferences").glob("*.md")))
            pending = (root / "review" / "pending.md").read_text(encoding="utf-8")
            self.assertIn("high-sensitivity inferred claim withheld", pending)
            self.assertNotIn("triage reminders", pending)
            self.assertIn("confirmation_required: 1", (root / "log.md").read_text(encoding="utf-8"))


class UserMemoryLintTests(unittest.TestCase):
    def test_lint_reports_known_consolidation_findings_and_review_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "memory")
            _write_manifest(root, "src-one", "src-two", "src-three", "src-four", "src-five")
            _write_lint_page(
                root,
                "wiki/preferences/direct-updates.md",
                "Direct Engineering Updates",
                source_id="src-one",
                related=("wiki/preferences/direct-engineering-updates.md",),
                last_observed_at="2026-01-01T00:00:00Z",
                stale_after="P30D",
                body="User prefers concise engineering status updates.",
            )
            _write_lint_page(
                root,
                "wiki/preferences/direct-engineering-updates.md",
                "Direct Engineering Updates",
                source_id="src-two",
                body="User prefers concise engineering updates with validation evidence.",
            )
            _write_lint_page(
                root,
                "wiki/preferences/orphan-status-format.md",
                "Orphan Status Format",
                source_id="src-three",
                body="User prefers terse status formatting.",
            )
            _write_lint_page(
                root,
                "wiki/values/status-format.md",
                "Status Format",
                page_type="value",
                source_id="src-four",
                body="User values concise status format for this task.",
            )
            _write_lint_page(
                root,
                "wiki/preferences/missing-metadata.md",
                "Missing Metadata",
                source_id="src-five",
                include_confidence=False,
                include_source_refs=False,
                body="User prefers reviewable memory reports.",
            )
            _write_lint_page(
                root,
                "wiki/preferences/contested-status.md",
                "Contested Status",
                source_id="src-five",
                status="contested",
                review_status="disputed",
                contradictions=("wiki/preferences/direct-updates.md",),
                body="User preference conflicts with an older status style claim.",
            )
            (root / "index.md").write_text(
                "# User Memory Index\n\n"
                "## Preferences\n\n"
                "- [Direct Updates](wiki/preferences/direct-updates.md) - confirmed; confidence: high\n",
                encoding="utf-8",
            )

            report = lint_user_memory(
                WikiLintOptions(
                    root=root,
                    as_of=datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc),
                )
            )

        self.assertTrue(report.duplicate_candidates)
        self.assertIn("wiki/preferences/orphan-status-format.md", report.orphan_pages)
        self.assertIn("wiki/preferences/direct-updates.md", report.stale_pages)
        self.assertTrue(
            any(item.path == "wiki/preferences/missing-metadata.md" for item in report.missing_metadata)
        )
        self.assertTrue(
            any(item.path == "wiki/preferences/contested-status.md" for item in report.unresolved_contradictions)
        )
        self.assertTrue(report.relationship_type_suggestions)
        self.assertTrue(
            any(item.suggested_type.value != "related" for item in report.relationship_type_suggestions)
        )
        review_categories = {item.category for item in report.review_items}
        self.assertIn("duplicate", review_categories)
        self.assertIn("relationship", review_categories)
        self.assertIn("concept-level", review_categories)
        self.assertIn("contradiction", review_categories)

    def test_lint_apply_performs_safe_fixes_and_appends_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "memory")
            _write_manifest(root, "src-one", "src-two")
            _write_lint_page(
                root,
                "wiki/preferences/direct-updates.md",
                "Direct Updates",
                source_id="src-one",
                related=("wiki/preferences/validation-updates.md",),
                last_observed_at="2026-01-01T00:00:00Z",
                stale_after="P30D",
            )
            _write_lint_page(
                root,
                "wiki/preferences/validation-updates.md",
                "Validation Updates",
                source_id="src-two",
            )
            (root / "index.md").write_text(
                "# User Memory Index\n\n"
                "## Preferences\n\n"
                "- [Direct Updates](wiki/preferences/direct-updates.md) - confirmed; confidence: high\n",
                encoding="utf-8",
            )

            report = lint_user_memory(
                WikiLintOptions(
                    root=root,
                    owner_user="user-test",
                    as_of=datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc),
                    apply=True,
                )
            )

            direct_page = (root / "wiki" / "preferences" / "direct-updates.md").read_text()
            validation_page = (root / "wiki" / "preferences" / "validation-updates.md").read_text()
            index = (root / "index.md").read_text()
            log = (root / "log.md").read_text()

        self.assertIn("status: stale", direct_page)
        self.assertIn("review_status: needs_user_review", direct_page)
        self.assertIn("- wiki/preferences/direct-updates.md", validation_page)
        self.assertIn("Validation Updates", index)
        self.assertIn("lint/consolidation pass", log)
        applied_actions = {fix.action for fix in report.safe_fixes if fix.applied}
        self.assertIn("rebuild_index", applied_actions)
        self.assertIn("add_backlink", applied_actions)
        self.assertIn("mark_stale", applied_actions)
        self.assertIn("append_log", applied_actions)


def _options(root: Path, channel: str = "codex") -> IngestOptions:
    return IngestOptions(
        root=root,
        owner_user="user-test",
        channel=channel,
        source_id="src-test",
        captured_at=CAPTURED_AT,
        source_retention=SourceRetention.HASH_ONLY,
    )


def _copy_memory_fixture(temp_dir: str) -> Path:
    root = Path(temp_dir, "memory")
    shutil.copytree(MEMORY_FIXTURE, root)
    return root


def _telegram_task(text: str) -> TelegramTask:
    return TelegramTask.from_message(chat_id=100, user_id=200, message_id=300, text=text)


def _write_manifest(root: Path, *source_ids: str) -> None:
    manifest = root / "raw" / "manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for source_id in source_ids:
        lines.append(
            '{"path": "raw/redactions/%s.json", "sensitivity": "private", "source_id": "%s"}'
            % (source_id, source_id)
        )
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_lint_page(
    root: Path,
    relative_path: str,
    title: str,
    page_type: str = "preference",
    source_id: str = "src-one",
    status: str = "active",
    memory_state: str = "confirmed",
    review_status: str = "user_confirmed",
    related: tuple = (),
    contradictions: tuple = (),
    corrections: tuple = (),
    include_confidence: bool = True,
    include_source_refs: bool = True,
    last_observed_at: str = "2026-05-01T00:00:00Z",
    stale_after: str = "P90D",
    body: str = "User prefers direct updates.",
) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        "id: mem-{}".format(relative_path.replace("/", "-").replace(".md", "")),
        "title: {}".format(title),
        "page_type: {}".format(page_type),
        "owner_user: user-test",
        "status: {}".format(status),
        "memory_state: {}".format(memory_state),
    ]
    if include_confidence:
        lines.extend(["confidence:", "  level: high", "  score: 0.90"])
    lines.extend(
        [
            "sensitivity: private",
            "prompt_visibility: task_only",
            "review_status: {}".format(review_status),
            "created_at: 2026-05-01T00:00:00Z",
            "updated_at: 2026-05-01T00:00:00Z",
            "last_observed_at: {}".format(last_observed_at),
            "last_confirmed_at: 2026-05-01T00:00:00Z",
            "stale_after: {}".format(stale_after),
        ]
    )
    if include_source_refs:
        lines.extend(
            [
                "source_refs:",
                "  - source_id: {}".format(source_id),
                "    path: raw/redactions/{}.json".format(source_id),
                "    locator: message:1",
                "    claim: {}".format(body),
                "    support: explicit",
                "    excerpt_hash: sha256:test",
            ]
        )
    lines.extend(_test_yaml_list("related", related))
    lines.extend(_test_yaml_list("supersedes", ()))
    lines.extend(_test_yaml_list("superseded_by", ()))
    lines.extend(_test_yaml_list("contradictions", contradictions))
    lines.extend(_test_yaml_list("corrections", corrections))
    lines.extend(["tags: [test]", "---", "", "# {}".format(title), "", body, ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _test_yaml_list(key: str, values: tuple) -> list:
    if not values:
        return ["{}: []".format(key)]
    return ["{}:".format(key)] + ["  - {}".format(value) for value in values]


if __name__ == "__main__":
    unittest.main()
