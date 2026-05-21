import json
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
                    "VERA_RUN_STATE_PATH": str(Path(temp_dir, "run-state.json")),
                    "VERA_CHAT_SESSION_STATE_PATH": str(Path(temp_dir, "chat-sessions.json")),
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
        self.assertIsNone(config.owner_profile)
        self.assertEqual(config.run_state_path, Path(temp_dir, "run-state.json").resolve())
        self.assertEqual(config.chat_session_state_path, Path(temp_dir, "chat-sessions.json").resolve())
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

    def test_dry_run_config_does_not_require_secrets(self):
        config = HarnessConfig.from_env({}, require_secrets=False)

        self.assertIsNone(config.telegram_bot_token)
        self.assertEqual(config.allowed_chat_ids, ())
        self.assertEqual(config.allowed_user_ids, ())
        self.assertEqual(config.telegram_api_base_url, "https://api.telegram.org")
        self.assertEqual(config.telegram_poll_timeout_seconds, 30)
        self.assertEqual(config.telegram_request_timeout_seconds, 35)
        self.assertEqual(config.telegram_state_path.name, "telegram_state.json")
        self.assertIsNone(config.telegram_unauthorized_response)
        self.assertIsNone(config.owner_profile)
        self.assertEqual(config.run_state_path.name, "run_state.json")
        self.assertEqual(config.chat_session_state_path.name, "chat_sessions.json")
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
            {"VERA_WORKSPACE_BOOTSTRAP_TIMEOUT_SECONDS": "0"},
            {"VERA_WORKSPACE_RETENTION_POLICY": "always-delete"},
            {"VERA_APPROVAL_POLICY": "sometimes"},
            {"VERA_SANDBOX_MODE": "open"},
            {"VERA_CODEX_APPROVAL_DECISION": "approve"},
            {"VERA_CODEX_APP_SERVER_COMMAND": ""},
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
