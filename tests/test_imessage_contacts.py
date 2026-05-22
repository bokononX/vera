import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from vera_harness.imessage_contacts import (
    IMessageContactIngestionError,
    discover_imessage_contacts,
    ingest_imessage_contacts,
    normalize_imessage_address,
)


CAPTURED_AT = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)
PRIVATE_BODY = "PRIVATE MESSAGE BODY SHOULD NEVER APPEAR"


class IMessageContactDiscoveryTests(unittest.TestCase):
    def test_discovers_metadata_only_contacts_and_display_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir, "chat.db")
            _write_messages_metadata_db(db_path)

            candidates = discover_imessage_contacts(db_path)

        by_address = {candidate.normalized_address: candidate for candidate in candidates}
        self.assertIn("+15551234567", by_address)
        self.assertIn("friend@example.com", by_address)
        self.assertEqual(by_address["+15551234567"].display_names, ("Alice Example",))
        self.assertEqual(by_address["friend@example.com"].display_names, ())
        self.assertIn("iMessage", by_address["+15551234567"].services)
        self.assertIn("iMessage;-;+15551234567", by_address["+15551234567"].chat_guids)

    def test_ingest_applies_person_open_question_without_message_bodies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            db_path = temp_path / "chat.db"
            memory_root = temp_path / "memory"
            _write_messages_metadata_db(db_path)

            result = ingest_imessage_contacts(
                enabled=True,
                chat_db_path=db_path,
                memory_root=memory_root,
                owner_user="user-test",
                apply=True,
                captured_at=CAPTURED_AT,
            )
            second_result = ingest_imessage_contacts(
                enabled=True,
                chat_db_path=db_path,
                memory_root=memory_root,
                owner_user="user-test",
                apply=True,
                captured_at=CAPTURED_AT,
            )

            rendered = result.format_human_readable()
            phone_page = memory_root / "wiki" / "people" / "imessage-contact-15551234567.md"
            email_page = memory_root / "wiki" / "people" / "imessage-contact-friend-example-com.md"
            phone_page_exists = phone_page.exists()
            email_page_exists = email_page.exists()
            all_persisted_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in sorted(memory_root.rglob("*"))
                if path.is_file()
            )
            second_actions = tuple(edit.action for edit in second_result.plan.edits)

        self.assertTrue(phone_page_exists)
        self.assertTrue(email_page_exists)
        self.assertIn("I noticed you text with Alice Example (+15551234567). Who is this", rendered)
        self.assertNotIn("conversation", rendered.lower())
        self.assertIn("memory_state: open_question", all_persisted_text)
        self.assertIn("review_status: needs_user_review", all_persisted_text)
        self.assertIn("prompt_visibility: confirm_first", all_persisted_text)
        self.assertIn("needs-owner-context", all_persisted_text)
        self.assertIn("message_count\": 0", all_persisted_text)
        self.assertNotIn(PRIVATE_BODY, rendered)
        self.assertNotIn(PRIVATE_BODY, all_persisted_text)
        self.assertTrue(all(action == "unchanged" for action in second_actions))

    def test_disabled_ingest_does_not_open_messages_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir, "missing-chat.db")
            with patch("vera_harness.imessage_contacts.discover_imessage_contacts") as discover:
                result = ingest_imessage_contacts(
                    enabled=False,
                    chat_db_path=missing_path,
                    memory_root=Path(temp_dir, "memory"),
                    owner_user="user-test",
                    apply=True,
                    captured_at=CAPTURED_AT,
                )

        discover.assert_not_called()
        self.assertFalse(result.enabled)
        self.assertIn("No Messages database was opened", result.format_human_readable())

    def test_missing_chat_db_reports_full_disk_access_hint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(IMessageContactIngestionError, "Full Disk Access"):
                discover_imessage_contacts(Path(temp_dir, "missing-chat.db"))

    def test_normalizes_phone_and_email_handles_for_dedupe(self):
        self.assertEqual(normalize_imessage_address("+1 (555) 123-4567"), "+15551234567")
        self.assertEqual(normalize_imessage_address("Friend@Example.COM"), "friend@example.com")


def _write_messages_metadata_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE handle (
              ROWID INTEGER PRIMARY KEY,
              id TEXT,
              uncanonicalized_id TEXT,
              service TEXT
            );
            CREATE TABLE chat (
              ROWID INTEGER PRIMARY KEY,
              guid TEXT,
              chat_identifier TEXT,
              display_name TEXT,
              service_name TEXT
            );
            CREATE TABLE chat_handle_join (
              chat_id INTEGER,
              handle_id INTEGER
            );
            CREATE TABLE message (
              ROWID INTEGER PRIMARY KEY,
              text TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO handle (ROWID, id, uncanonicalized_id, service) VALUES (?, ?, ?, ?)",
            (1, "+1 (555) 123-4567", "+1 (555) 123-4567", "iMessage"),
        )
        connection.execute(
            "INSERT INTO handle (ROWID, id, uncanonicalized_id, service) VALUES (?, ?, ?, ?)",
            (2, "Friend@Example.COM", "Friend@Example.COM", "iMessage"),
        )
        connection.execute(
            "INSERT INTO handle (ROWID, id, uncanonicalized_id, service) VALUES (?, ?, ?, ?)",
            (3, "Other@Example.COM", "Other@Example.COM", "iMessage"),
        )
        connection.execute(
            "INSERT INTO chat (ROWID, guid, chat_identifier, display_name, service_name) VALUES (?, ?, ?, ?, ?)",
            (10, "iMessage;-;+15551234567", "+15551234567", "Alice Example", "iMessage"),
        )
        connection.execute(
            "INSERT INTO chat (ROWID, guid, chat_identifier, display_name, service_name) VALUES (?, ?, ?, ?, ?)",
            (11, "iMessage;+;group-guid", "group-guid", "Project Group", "iMessage"),
        )
        connection.execute("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)", (10, 1))
        connection.execute("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)", (11, 2))
        connection.execute("INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)", (11, 3))
        connection.execute("INSERT INTO message (ROWID, text) VALUES (?, ?)", (100, PRIVATE_BODY))
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
