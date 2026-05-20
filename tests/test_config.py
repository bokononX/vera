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
                    "VERA_WORKSPACE_ROOT": temp_dir,
                    "VERA_CODEX_APP_SERVER_COMMAND": "codex app-server --port 0",
                    "VERA_MAX_TURNS": "7",
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
        self.assertEqual(config.workspace_root, Path(temp_dir).resolve())
        self.assertEqual(config.codex_app_server_command.argv, ("codex", "app-server", "--port", "0"))
        self.assertEqual(config.max_turns, 7)
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
        self.assertEqual(config.codex_app_server_command.argv, ("codex", "app-server"))
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

    def test_invalid_values_raise_config_error(self):
        invalid_cases = [
            {"VERA_ALLOWED_CHAT_IDS": "abc"},
            {"VERA_MAX_TURNS": "0"},
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


if __name__ == "__main__":
    unittest.main()
