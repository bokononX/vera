import json
import os
import tempfile
import unittest
from pathlib import Path

from vera_harness.config import ConfigError, HarnessConfig


class HarnessConfigTests(unittest.TestCase):
    def test_from_env_parses_all_supported_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = HarnessConfig.from_env(
                {
                    "VERA_TELEGRAM_BOT_TOKEN": "token-placeholder",
                    "VERA_ALLOWED_CHAT_IDS": "123, 456",
                    "VERA_ALLOWED_USER_IDS": "789",
                    "VERA_TELEGRAM_API_BASE_URL": "https://telegram.example.test/",
                    "VERA_TELEGRAM_POLL_TIMEOUT_SECONDS": "12",
                    "VERA_TELEGRAM_REQUEST_TIMEOUT_SECONDS": "13",
                    "VERA_TELEGRAM_STATE_PATH": str(Path(temp_dir, "telegram-state.json")),
                    "VERA_TELEGRAM_UNAUTHORIZED_RESPONSE": "This chat is not authorized.",
                    "VERA_ASSISTANT_IDENTITY_PATH": str(Path(temp_dir, "assistant-identity.json")),
                    "VERA_ASSISTANT_IDENTITY_INTERVIEW_STATE_PATH": str(
                        Path(temp_dir, "assistant-identity-interviews.json")
                    ),
                    "VERA_RUN_STATE_PATH": str(Path(temp_dir, "run-state.json")),
                    "VERA_CHAT_SESSION_STATE_PATH": str(Path(temp_dir, "chat-sessions.json")),
                    "VERA_IDENTITY_PROFILE_PATH": str(Path(temp_dir, "identity-profile.json")),
                    "VERA_IDENTITY_INTERVIEW_STATE_PATH": str(Path(temp_dir, "identity-interviews.json")),
                    "VERA_USER_MEMORY_ROOT": str(Path(temp_dir, "memory", "users", "owner")),
                    "VERA_EVENT_LOG_PATH": str(Path(temp_dir, "events.jsonl")),
                    "VERA_HEARTBEAT_ENABLED": "true",
                    "VERA_HEARTBEAT_DRY_RUN": "false",
                    "VERA_HEARTBEAT_INTERVAL_SECONDS": "3600",
                    "VERA_HEARTBEAT_TIMEZONE": "America/Los_Angeles",
                    "VERA_HEARTBEAT_QUIET_HOURS_START": "21:30",
                    "VERA_HEARTBEAT_QUIET_HOURS_END": "07:15",
                    "VERA_HEARTBEAT_MAX_DAILY_INITIATIONS": "3",
                    "VERA_HEARTBEAT_OWNER_CHAT_ID": "123",
                    "VERA_HEARTBEAT_STATE_PATH": str(Path(temp_dir, "heartbeat-state.json")),
                    "VERA_HEARTBEAT_REPEAT_COOLDOWN_SECONDS": "7200",
                    "VERA_HEARTBEAT_MAX_RECENT_TOPICS": "9",
                    "VERA_WORKSPACE_ROOT": temp_dir,
                    "VERA_CODEX_APP_SERVER_COMMAND": "codex app-server --port 0",
                    "VERA_MAX_TURNS": "7",
                    "VERA_MAX_RETRIES": "2",
                    "VERA_TURN_TIMEOUT_SECONDS": "11",
                    "VERA_RUN_TIMEOUT_SECONDS": "22",
                    "VERA_WORKSPACE_BOOTSTRAP_TIMEOUT_SECONDS": "33",
                    "VERA_WORKSPACE_RETENTION_POLICY": "cleanup_on_completion",
                    "VERA_APPROVAL_POLICY": "never",
                    "VERA_SANDBOX_MODE": "read-only",
                    "VERA_CODEX_APPROVAL_DECISION": "decline",
                    "VERA_CODEX_AUTO_INPUT_RESPONSE": "Use the default option.",
                    "VERA_REPO_CLONE_COMMAND": "git clone git@example.test:repo.git .",
                    "VERA_REPO_BOOTSTRAP_COMMAND": "python3 -m unittest",
                    "VERA_IMESSAGE_CONTACT_INGESTION_ENABLED": "true",
                    "VERA_IMESSAGE_CHAT_DB_PATH": str(Path(temp_dir, "chat.db")),
                }
            )

        self.assertEqual(config.telegram_bot_token, "token-placeholder")
        self.assertEqual(config.allowed_chat_ids, (123, 456))
        self.assertEqual(config.allowed_user_ids, (789,))
        self.assertEqual(config.telegram_api_base_url, "https://telegram.example.test")
        self.assertEqual(config.telegram_poll_timeout_seconds, 12)
        self.assertEqual(config.telegram_request_timeout_seconds, 13)
        self.assertEqual(config.telegram_state_path, Path(temp_dir, "telegram-state.json").resolve())
        self.assertEqual(config.telegram_unauthorized_response, "This chat is not authorized.")
        self.assertEqual(config.assistant_identity.safe_display_name, "Vera")
        self.assertEqual(
            config.assistant_identity_path,
            Path(temp_dir, "assistant-identity.json").resolve(),
        )
        self.assertEqual(
            config.assistant_identity_interview_state_path,
            Path(temp_dir, "assistant-identity-interviews.json").resolve(),
        )
        self.assertIsNone(config.owner_profile)
        self.assertEqual(config.run_state_path, Path(temp_dir, "run-state.json").resolve())
        self.assertEqual(config.chat_session_state_path, Path(temp_dir, "chat-sessions.json").resolve())
        self.assertEqual(config.identity_profile_path, Path(temp_dir, "identity-profile.json").resolve())
        self.assertEqual(config.identity_interview_state_path, Path(temp_dir, "identity-interviews.json").resolve())
        self.assertEqual(config.user_memory_root, Path(temp_dir, "memory", "users", "owner").resolve())
        self.assertEqual(config.event_log_path, Path(temp_dir, "events.jsonl").resolve())
        self.assertTrue(config.heartbeat.enabled)
        self.assertFalse(config.heartbeat.dry_run)
        self.assertEqual(config.heartbeat.interval_seconds, 3600)
        self.assertEqual(config.heartbeat.timezone, "America/Los_Angeles")
        self.assertEqual(config.heartbeat.quiet_hours_start, "21:30")
        self.assertEqual(config.heartbeat.quiet_hours_end, "07:15")
        self.assertEqual(config.heartbeat.max_daily_initiations, 3)
        self.assertEqual(config.heartbeat.owner_chat_id, 123)
        self.assertEqual(config.heartbeat.state_path, Path(temp_dir, "heartbeat-state.json").resolve())
        self.assertEqual(config.heartbeat.repeat_cooldown_seconds, 7200)
        self.assertEqual(config.heartbeat.max_recent_topics, 9)
        self.assertEqual(config.workspace_root, Path(temp_dir).resolve())
        self.assertEqual(config.codex_app_server_command.argv, ("codex", "app-server", "--port", "0"))
        self.assertEqual(config.max_turns, 7)
        self.assertEqual(config.max_retries, 2)
        self.assertEqual(config.turn_timeout_seconds, 11)
        self.assertEqual(config.run_timeout_seconds, 22)
        self.assertEqual(config.workspace_bootstrap_timeout_seconds, 33)
        self.assertEqual(config.workspace_retention_policy, "cleanup_on_completion")
        self.assertEqual(config.approval_policy, "never")
        self.assertEqual(config.sandbox_mode, "read-only")
        self.assertEqual(config.codex_approval_decision, "decline")
        self.assertEqual(config.codex_auto_input_response, "Use the default option.")
        self.assertIsNotNone(config.repo_clone_command)
        self.assertIsNotNone(config.repo_bootstrap_command)
        self.assertTrue(config.imessage_contact_ingestion_enabled)
        self.assertEqual(config.imessage_chat_db_path, Path(temp_dir, "chat.db").resolve())

    def test_dry_run_config_does_not_require_secrets(self):
        config = HarnessConfig.from_env({}, require_secrets=False)

        self.assertIsNone(config.telegram_bot_token)
        self.assertEqual(config.allowed_chat_ids, ())
        self.assertEqual(config.allowed_user_ids, ())
        self.assertEqual(config.telegram_api_base_url, "https://api.telegram.org")
        self.assertEqual(config.telegram_poll_timeout_seconds, 30)
        self.assertEqual(config.telegram_request_timeout_seconds, 35)
        runtime_root = Path("runtime").resolve()
        self.assertEqual(config.telegram_state_path, runtime_root / "telegram_state.json")
        self.assertIsNone(config.telegram_unauthorized_response)
        self.assertEqual(config.assistant_identity.safe_display_name, "Vera")
        self.assertIn("personal assistant", config.assistant_identity.short_description)
        self.assertEqual(config.assistant_identity_path, runtime_root / "assistant_identity.json")
        self.assertEqual(
            config.assistant_identity_interview_state_path,
            runtime_root / "assistant_identity_interviews.json",
        )
        self.assertIsNone(config.owner_profile)
        self.assertEqual(config.run_state_path, runtime_root / "run_state.json")
        self.assertEqual(config.chat_session_state_path, runtime_root / "chat_sessions.json")
        self.assertEqual(config.identity_profile_path, runtime_root / "identity_profile.json")
        self.assertEqual(config.identity_interview_state_path, runtime_root / "identity_interviews.json")
        self.assertIsNone(config.user_memory_root)
        self.assertEqual(config.event_log_path, runtime_root / "events.jsonl")
        self.assertFalse(config.imessage_contact_ingestion_enabled)
        self.assertEqual(
            config.imessage_chat_db_path,
            Path("~/Library/Messages/chat.db").expanduser().resolve(),
        )
        self.assertFalse(config.heartbeat.enabled)
        self.assertTrue(config.heartbeat.dry_run)
        self.assertEqual(config.heartbeat.interval_seconds, 21600)
        self.assertEqual(config.heartbeat.timezone, "UTC")
        self.assertEqual(config.heartbeat.quiet_hours_start, "22:00")
        self.assertEqual(config.heartbeat.quiet_hours_end, "08:00")
        self.assertEqual(config.heartbeat.max_daily_initiations, 2)
        self.assertIsNone(config.heartbeat.owner_chat_id)
        self.assertEqual(config.heartbeat.state_path, runtime_root / "heartbeat_state.json")
        self.assertEqual(config.workspace_root, runtime_root / "workspaces")
        self.assertEqual(config.codex_app_server_command.argv, ("codex", "app-server"))
        self.assertEqual(config.max_retries, 1)
        self.assertEqual(config.workspace_bootstrap_timeout_seconds, 300)
        self.assertEqual(config.workspace_retention_policy, "retain")
        self.assertEqual(config.sandbox_mode, "read-only")
        self.assertIsNone(config.codex_approval_decision)
        self.assertIsNone(config.codex_auto_input_response)

    def test_live_config_requires_token_and_allow_list(self):
        with self.assertRaises(ConfigError):
            HarnessConfig.from_env({}, require_secrets=True)

        with self.assertRaises(ConfigError):
            HarnessConfig.from_env(
                {"VERA_TELEGRAM_BOT_TOKEN": "token-placeholder"},
                require_secrets=True,
            )

    def test_load_uses_runtime_default_telegram_config_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir, "runtime")
            runtime_dir.mkdir()
            config_path = runtime_dir / "telegram_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {
                            "allowed_chat_ids": [321],
                            "state_path": "./runtime/telegram_state.json",
                        }
                    }
                ),
                encoding="utf-8",
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(temp_dir)
                config = HarnessConfig.load(
                    {"VERA_TELEGRAM_BOT_TOKEN": "token-placeholder"},
                    require_secrets=True,
                )
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(config.allowed_chat_ids, (321,))
        self.assertEqual(config.telegram_state_path, (runtime_dir / "telegram_state.json").resolve())

    def test_load_reads_telegram_settings_from_config_and_token_from_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            state_path = Path(temp_dir, "state.json")
            config_path.write_text(
                """
{
  "telegram": {
    "allowed_chat_ids": [123, 456],
    "allowed_user_ids": [789],
    "api_base_url": "https://telegram.example.test/",
    "poll_timeout_seconds": 12,
    "request_timeout_seconds": 13,
    "state_path": "%s",
    "unauthorized_response": "This chat is not authorized."
  }
}
""".strip()
                % state_path,
                encoding="utf-8",
            )

            config = HarnessConfig.load(
                {
                    "VERA_TELEGRAM_BOT_TOKEN": "token-placeholder",
                    "VERA_ALLOWED_CHAT_IDS": "999",
                    "VERA_WORKSPACE_ROOT": temp_dir,
                },
                telegram_config_path=str(config_path),
                require_secrets=True,
            )

        self.assertEqual(config.telegram_bot_token, "token-placeholder")
        self.assertEqual(config.allowed_chat_ids, (123, 456))
        self.assertEqual(config.allowed_user_ids, (789,))
        self.assertEqual(config.telegram_api_base_url, "https://telegram.example.test")
        self.assertEqual(config.telegram_poll_timeout_seconds, 12)
        self.assertEqual(config.telegram_request_timeout_seconds, 13)
        self.assertEqual(config.telegram_state_path, state_path.resolve())
        self.assertEqual(config.telegram_unauthorized_response, "This chat is not authorized.")

    def test_load_reads_multi_user_telegram_config_with_secret_refs_and_isolated_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            alice_root = Path(temp_dir, "alice")
            bob_root = Path(temp_dir, "bob")
            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {
                            "shared_chat_ids": [-1000],
                            "api_base_url": "https://telegram.example.test",
                            "users": [
                                {
                                    "id": "alice",
                                    "bot_username": "alice_bot",
                                    "bot_token_env": "VERA_TELEGRAM_BOT_TOKEN_ALICE",
                                    "allowed_chat_ids": [101],
                                    "allowed_user_ids": [201],
                                    "command_prefixes": ["/alice"],
                                    "state_path": str(alice_root / "telegram-state.json"),
                                    "run_state_path": str(alice_root / "run-state.json"),
                                    "chat_session_state_path": str(alice_root / "chat-sessions.json"),
                                    "assistant_identity_path": str(alice_root / "assistant.json"),
                                    "assistant": {"name": "Alice Vera"},
                                    "owner": {
                                        "user_id": 201,
                                        "display_name": "Alice Owner",
                                        "user_memory_root": str(alice_root / "memory"),
                                    },
                                    "workspace_root": str(alice_root / "workspaces"),
                                    "event_log_path": str(alice_root / "events.jsonl"),
                                },
                                {
                                    "id": "bob",
                                    "bot_username": "bob_bot",
                                    "bot_token_env": "VERA_TELEGRAM_BOT_TOKEN_BOB",
                                    "allowed_chat_ids": [102],
                                    "allowed_user_ids": [202],
                                    "command_prefixes": ["/bob"],
                                    "state_path": str(bob_root / "telegram-state.json"),
                                    "run_state_path": str(bob_root / "run-state.json"),
                                    "chat_session_state_path": str(bob_root / "chat-sessions.json"),
                                    "assistant_identity_path": str(bob_root / "assistant.json"),
                                    "assistant": {"name": "Bob Vera"},
                                    "owner": {
                                        "user_id": 202,
                                        "display_name": "Bob Owner",
                                        "user_memory_root": str(bob_root / "memory"),
                                    },
                                    "workspace_root": str(bob_root / "workspaces"),
                                    "event_log_path": str(bob_root / "events.jsonl"),
                                },
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = HarnessConfig.load(
                {
                    "VERA_TELEGRAM_BOT_TOKEN_ALICE": "alice-secret-token",
                    "VERA_TELEGRAM_BOT_TOKEN_BOB": "bob-secret-token",
                    "VERA_CODEX_APP_SERVER_COMMAND": "codex app-server",
                },
                telegram_config_path=str(config_path),
                require_secrets=True,
            )

        self.assertEqual(config.telegram_shared_chat_ids, (-1000,))
        self.assertEqual([user.id for user in config.telegram_users], ["alice", "bob"])
        alice = config.telegram_user("alice")
        bob = config.telegram_user("bob")
        self.assertEqual(alice.bot_token_env, "VERA_TELEGRAM_BOT_TOKEN_ALICE")
        self.assertEqual(alice.bot_token, "alice-secret-token")
        self.assertEqual(bob.bot_token_env, "VERA_TELEGRAM_BOT_TOKEN_BOB")
        self.assertEqual(bob.bot_token, "bob-secret-token")
        self.assertEqual(alice.shared_chat_ids, (-1000,))
        self.assertEqual(bob.shared_chat_ids, (-1000,))
        self.assertNotEqual(alice.telegram_state_path, bob.telegram_state_path)
        self.assertNotEqual(alice.run_state_path, bob.run_state_path)
        self.assertNotEqual(alice.chat_session_state_path, bob.chat_session_state_path)
        self.assertNotEqual(alice.workspace_root, bob.workspace_root)
        self.assertNotEqual(alice.event_log_path, bob.event_log_path)
        self.assertEqual(alice.assistant_identity.safe_display_name, "Alice Vera")
        self.assertEqual(bob.assistant_identity.safe_display_name, "Bob Vera")
        self.assertEqual(alice.owner_profile.user_id, 201)
        self.assertEqual(bob.owner_profile.user_id, 202)
        self.assertEqual(alice.user_memory_root, (alice_root / "memory").resolve())
        self.assertEqual(bob.user_memory_root, (bob_root / "memory").resolve())

        alice_config = config.config_for_telegram_user("alice")
        self.assertEqual(alice_config.telegram_runtime_id, "alice")
        self.assertEqual(alice_config.telegram_bot_token, "alice-secret-token")
        self.assertEqual(alice_config.allowed_chat_ids, (101,))
        self.assertEqual(alice_config.allowed_user_ids, (201,))
        self.assertEqual(alice_config.telegram_shared_chat_ids, (-1000,))
        self.assertEqual(alice_config.telegram_bot_username, "alice_bot")
        self.assertEqual(alice_config.telegram_command_prefixes, ("/alice",))
        self.assertEqual(alice_config.telegram_known_bot_usernames, ("alice_bot", "bob_bot"))
        self.assertEqual(alice_config.telegram_known_command_prefixes, ("/alice", "/bob"))
        self.assertEqual(alice_config.telegram_users, ())

    def test_multi_user_config_rejects_raw_tokens_and_missing_token_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {
                            "shared_chat_ids": [-1000],
                            "users": [
                                {
                                    "id": "alice",
                                    "bot_username": "alice_bot",
                                    "bot_token_env": "VERA_TELEGRAM_BOT_TOKEN_ALICE",
                                    "bot_token": "not-allowed",
                                    "allowed_user_ids": [201],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "must not contain secret fields"):
                HarnessConfig.load({}, telegram_config_path=str(config_path), require_secrets=False)

            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {
                            "shared_chat_ids": [-1000],
                            "users": [
                                {
                                    "id": "alice",
                                    "bot_username": "alice_bot",
                                    "bot_token_env": "VERA_TELEGRAM_BOT_TOKEN_ALICE",
                                    "allowed_user_ids": [201],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "environment variables are required"):
                HarnessConfig.load({}, telegram_config_path=str(config_path), require_secrets=True)

    def test_multi_user_config_requires_distinct_token_references(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {
                            "shared_chat_ids": [-1000],
                            "users": [
                                {
                                    "id": "alice",
                                    "bot_username": "alice_bot",
                                    "bot_token_env": "VERA_TELEGRAM_BOT_TOKEN_SHARED",
                                    "allowed_user_ids": [201],
                                },
                                {
                                    "id": "bob",
                                    "bot_username": "bob_bot",
                                    "bot_token_env": "VERA_TELEGRAM_BOT_TOKEN_SHARED",
                                    "allowed_user_ids": [202],
                                },
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "duplicate bot_token_env"):
                HarnessConfig.load(
                    {"VERA_TELEGRAM_BOT_TOKEN_SHARED": "token-placeholder"},
                    telegram_config_path=str(config_path),
                    require_secrets=True,
                )

    def test_load_reads_owner_identity_and_refreshable_profile_from_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            profile_path = Path(temp_dir, "owner-profile.md")
            profile_path.write_text(
                "Owner fact: prefer correction over reassurance.",
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {
                            "allowed_user_ids": [200],
                            "state_path": str(Path(temp_dir, "state.json")),
                        },
                        "owner": {
                            "user_id": 200,
                            "display_name": "Vera Owner",
                            "username": "owner_handle",
                            "role": "Vera is a careful representative.",
                            "values": ["truth over comfort"],
                            "priorities": ["surface tradeoffs"],
                            "communication_style": ["direct and concrete"],
                            "escalation_boundaries": ["require approval before irreversible actions"],
                            "wiki_profile_path": str(profile_path),
                            "user_memory_root": str(Path(temp_dir, "memory", "users", "owner")),
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = HarnessConfig.load(
                {"VERA_TELEGRAM_BOT_TOKEN": "token-placeholder"},
                telegram_config_path=str(config_path),
                require_secrets=True,
            )

        self.assertIsNotNone(config.owner_profile)
        self.assertEqual(config.owner_profile.user_id, 200)
        self.assertEqual(config.owner_profile.display_name, "Vera Owner")
        self.assertEqual(config.owner_profile.username, "owner_handle")
        self.assertEqual(config.owner_profile.communication_style, ("direct and concrete",))
        self.assertEqual(config.owner_profile.wiki_profile_path, profile_path.resolve())
        self.assertIn("prefer correction", config.owner_profile.wiki_profile_excerpt)
        self.assertEqual(config.user_memory_root, Path(temp_dir, "memory", "users", "owner").resolve())

    def test_load_reads_heartbeat_config_section(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            state_path = Path(temp_dir, "heartbeat-state.json")
            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {
                            "allowed_chat_ids": [100],
                            "allowed_user_ids": [200],
                        },
                        "owner": {"user_id": 200},
                        "heartbeat": {
                            "enabled": True,
                            "dry_run": True,
                            "interval_seconds": 1800,
                            "timezone": "America/New_York",
                            "quiet_hours": {"start": "23:00", "end": "06:30"},
                            "max_daily_initiations": 1,
                            "owner_chat_id": 100,
                            "state_path": str(state_path),
                            "repeat_cooldown_seconds": 3600,
                            "max_recent_topics": 5,
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = HarnessConfig.load(
                {"VERA_TELEGRAM_BOT_TOKEN": "token-placeholder"},
                telegram_config_path=str(config_path),
                require_secrets=True,
            )

        self.assertTrue(config.heartbeat.enabled)
        self.assertTrue(config.heartbeat.dry_run)
        self.assertEqual(config.heartbeat.interval_seconds, 1800)
        self.assertEqual(config.heartbeat.timezone, "America/New_York")
        self.assertEqual(config.heartbeat.quiet_hours_start, "23:00")
        self.assertEqual(config.heartbeat.quiet_hours_end, "06:30")
        self.assertEqual(config.heartbeat.max_daily_initiations, 1)
        self.assertEqual(config.heartbeat.owner_chat_id, 100)
        self.assertEqual(config.heartbeat.state_path, state_path.resolve())

    def test_load_reads_assistant_identity_from_config_and_profile_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            assistant_path = Path(temp_dir, "assistant.json")
            assistant_path.write_text(
                json.dumps(
                    {
                        "name": "Mira",
                        "mission": "Help Victor think clearly.",
                        "communication_principles": ["brief, precise, and candid"],
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {"allowed_user_ids": [200]},
                        "assistant": {
                            "identity_path": str(assistant_path),
                            "name": "Inline name is overridden by profile file",
                            "short_description": "a local personal assistant",
                            "core_values": ["truth", "agency"],
                            "relationship_to_owner": "Help the owner as a configured assistant.",
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = HarnessConfig.load(
                {"VERA_TELEGRAM_BOT_TOKEN": "token-placeholder"},
                telegram_config_path=str(config_path),
                require_secrets=True,
            )

        self.assertEqual(config.assistant_identity.safe_display_name, "Mira")
        self.assertEqual(config.assistant_identity_path, assistant_path.resolve())
        self.assertEqual(config.assistant_identity.mission, "Help Victor think clearly.")
        self.assertEqual(config.assistant_identity.short_description, "a local personal assistant")
        self.assertEqual(config.assistant_identity.core_values, ("truth", "agency"))
        self.assertEqual(
            config.assistant_identity.communication_principles,
            ("brief, precise, and candid",),
        )

    def test_load_reads_imessage_contact_ingestion_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            chat_db_path = Path(temp_dir, "Messages", "chat.db")
            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {"allowed_user_ids": [200]},
                        "imessage": {
                            "contact_ingestion_enabled": True,
                            "chat_db_path": str(chat_db_path),
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = HarnessConfig.load(
                {"VERA_TELEGRAM_BOT_TOKEN": "token-placeholder"},
                telegram_config_path=str(config_path),
                require_secrets=True,
            )

        self.assertTrue(config.imessage_contact_ingestion_enabled)
        self.assertEqual(config.imessage_chat_db_path, chat_db_path.resolve())

    def test_explicit_missing_or_malformed_telegram_config_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir, "missing.json")
            with self.assertRaisesRegex(ConfigError, "does not exist"):
                HarnessConfig.load({}, telegram_config_path=str(missing_path), require_secrets=False)

            bad_json_path = Path(temp_dir, "bad.json")
            bad_json_path.write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "not valid JSON"):
                HarnessConfig.load({}, telegram_config_path=str(bad_json_path), require_secrets=False)

    def test_telegram_config_rejects_secret_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            config_path.write_text(
                """
{
  "telegram": {
    "bot_token": "not-allowed-in-config",
    "allowed_chat_ids": [123]
  }
}
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "must not contain secret fields"):
                HarnessConfig.load({}, telegram_config_path=str(config_path), require_secrets=False)

    def test_owner_config_rejects_secret_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {"allowed_chat_ids": [123]},
                        "owner": {"user_id": 200, "token": "not-allowed"},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "Owner config must not contain secret fields"):
                HarnessConfig.load({}, telegram_config_path=str(config_path), require_secrets=False)

    def test_assistant_config_rejects_secret_fields_and_human_overclaims(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir, "telegram.json")
            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {"allowed_chat_ids": [123]},
                        "assistant": {"token": "not-allowed"},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "Assistant config must not contain secret fields"):
                HarnessConfig.load({}, telegram_config_path=str(config_path), require_secrets=False)

            config_path.write_text(
                json.dumps(
                    {
                        "telegram": {"allowed_chat_ids": [123]},
                        "assistant": {"short_description": "I am human."},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "must not configure the assistant"):
                HarnessConfig.load({}, telegram_config_path=str(config_path), require_secrets=False)

    def test_env_allow_list_still_works_when_no_default_config_exists(self):
        config = HarnessConfig.load(
            {
                "VERA_TELEGRAM_BOT_TOKEN": "token-placeholder",
                "VERA_ALLOWED_CHAT_IDS": "123",
            },
            require_secrets=True,
        )

        self.assertEqual(config.telegram_bot_token, "token-placeholder")
        self.assertEqual(config.allowed_chat_ids, (123,))

    def test_invalid_values_raise_config_error(self):
        invalid_cases = [
            {"VERA_ALLOWED_CHAT_IDS": "abc"},
            {"VERA_MAX_TURNS": "0"},
            {"VERA_MAX_RETRIES": "-1"},
            {"VERA_TURN_TIMEOUT_SECONDS": "-1"},
            {"VERA_TELEGRAM_API_BASE_URL": "api.telegram.org"},
            {"VERA_TELEGRAM_POLL_TIMEOUT_SECONDS": "0"},
            {"VERA_TELEGRAM_REQUEST_TIMEOUT_SECONDS": "-1"},
            {"VERA_HEARTBEAT_ENABLED": "maybe"},
            {"VERA_HEARTBEAT_INTERVAL_SECONDS": "0"},
            {"VERA_HEARTBEAT_TIMEZONE": "Not/AZone"},
            {"VERA_HEARTBEAT_QUIET_HOURS_START": "25:00"},
            {
                "VERA_ALLOWED_CHAT_IDS": "100",
                "VERA_HEARTBEAT_OWNER_CHAT_ID": "999",
            },
            {"VERA_HEARTBEAT_MAX_DAILY_INITIATIONS": "-1"},
            {"VERA_HEARTBEAT_REPEAT_COOLDOWN_SECONDS": "0"},
            {"VERA_WORKSPACE_BOOTSTRAP_TIMEOUT_SECONDS": "0"},
            {"VERA_WORKSPACE_RETENTION_POLICY": "always-delete"},
            {"VERA_APPROVAL_POLICY": "sometimes"},
            {"VERA_SANDBOX_MODE": "open"},
            {"VERA_CODEX_APPROVAL_DECISION": "approve"},
            {"VERA_CODEX_APP_SERVER_COMMAND": ""},
            {"VERA_IMESSAGE_CONTACT_INGESTION_ENABLED": "maybe"},
        ]

        for env in invalid_cases:
            with self.subTest(env=env):
                with self.assertRaises(ConfigError):
                    HarnessConfig.from_env(env, require_secrets=False)

    def test_command_resolution_expands_relative_executable_from_monitor_cwd(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir, "bin", "codex")
            executable.parent.mkdir()
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            config = HarnessConfig.from_env(
                {
                    "VERA_CODEX_APP_SERVER_COMMAND": "./bin/codex app-server",
                },
                require_secrets=False,
            )

            resolution = config.codex_app_server_command.resolve_executable(
                "VERA_CODEX_APP_SERVER_COMMAND",
                cwd=Path(temp_dir),
            )

        self.assertEqual(resolution.resolved_executable, executable.resolve())
        self.assertEqual(resolution.argv, (str(executable.resolve()), "app-server"))


if __name__ == "__main__":
    unittest.main()
