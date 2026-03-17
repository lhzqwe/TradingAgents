import io
import os
import tempfile
import unittest
from unittest.mock import patch

from rich.console import Console
from typer.testing import CliRunner

try:
    from cli.main import app
except ImportError as exc:  # pragma: no cover - environment-dependent
    raise unittest.SkipTest(f"CLI dependencies are not installed: {exc}") from exc

from cli.auth_commands import auth_app
from cli.openai_codex import ensure_openai_codex_analysis_auth
from tradingagents.auth import (
    OpenAICodexAuthError,
    OpenAICodexProfileNotFound,
    upsert_profile,
)


class CliOpenAICodexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.runner = CliRunner()
        self.env = {"TRADINGAGENTS_STATE_DIR": self.temp_dir.name, **os.environ}

    def test_auth_status_displays_saved_profile(self) -> None:
        upsert_profile(
            "openai-codex:user@example.com",
            {
                "type": "oauth",
                "provider": "openai-codex",
                "access": "access-token",
                "refresh": "refresh-token",
                "expires": 4_102_444_800_000,
                "email": "user@example.com",
            },
            state_dir=self.temp_dir.name,
        )

        result = self.runner.invoke(app, ["auth", "status"], env=self.env)

        self.assertEqual(result.exit_code, 0)
        self.assertIn("openai-codex:user@example", result.stdout)
        self.assertIn(".com", result.stdout)
        self.assertIn("user@example.com", result.stdout)
        self.assertIn("valid", result.stdout)

    def test_auth_login_command_forwards_headless_flag(self) -> None:
        with patch(
            "cli.auth_commands.login_openai_codex",
            return_value=(
                "openai-codex:default",
                {"type": "oauth", "provider": "openai-codex"},
            ),
        ) as mock_login:
            result = self.runner.invoke(
                app,
                ["auth", "login", "--provider", "openai-codex", "--headless"],
                env=self.env,
            )

        self.assertEqual(result.exit_code, 0)
        mock_login.assert_called_once()
        self.assertTrue(mock_login.call_args.kwargs["headless"])

    def test_analysis_helper_reuses_existing_profile(self) -> None:
        with patch(
            "cli.openai_codex.get_active_openai_codex_profile",
            return_value=("openai-codex:user@example.com", {"provider": "openai-codex"}),
        ):
            updated = ensure_openai_codex_analysis_auth(
                {"llm_provider": "openai-codex"},
                interactive=False,
            )

        self.assertEqual(updated["auth_profile_id"], "openai-codex:user@example.com")

    def test_analysis_helper_auto_logs_in_interactive_mode(self) -> None:
        stream = io.StringIO()
        console = Console(file=stream, force_terminal=False)

        with patch(
            "cli.openai_codex.get_active_openai_codex_profile",
            side_effect=OpenAICodexProfileNotFound("missing"),
        ), patch(
            "cli.openai_codex.login_openai_codex",
            return_value=("openai-codex:default", {"provider": "openai-codex"}),
        ) as mock_login:
            updated = ensure_openai_codex_analysis_auth(
                {"llm_provider": "openai-codex"},
                console=console,
                interactive=True,
            )

        self.assertEqual(updated["auth_profile_id"], "openai-codex:default")
        mock_login.assert_called_once()

    def test_analysis_helper_requires_login_when_non_interactive(self) -> None:
        with patch(
            "cli.openai_codex.get_active_openai_codex_profile",
            side_effect=OpenAICodexProfileNotFound("missing"),
        ):
            with self.assertRaises(OpenAICodexAuthError):
                ensure_openai_codex_analysis_auth(
                    {"llm_provider": "openai-codex"},
                    interactive=False,
                )

    def test_analyze_command_accepts_non_interactive_options(self) -> None:
        with patch("cli.main.run_analysis") as mock_run_analysis:
            result = self.runner.invoke(
                app,
                [
                    "analyze",
                    "--ticker",
                    "NVDA",
                    "--analysis-date",
                    "2026-03-16",
                    "--all-analysts",
                    "--research-depth",
                    "1",
                    "--llm-provider",
                    "openai-codex",
                    "--shallow-thinker",
                    "gpt-5.4",
                    "--deep-thinker",
                    "gpt-5.4",
                    "--openai-reasoning-effort",
                    "low",
                    "--auth-profile-id",
                    "openai-codex:user@example.com",
                    "--no-save-report",
                    "--no-display-report",
                ],
                env=self.env,
            )

        self.assertEqual(result.exit_code, 0)
        mock_run_analysis.assert_called_once()
        kwargs = mock_run_analysis.call_args.kwargs
        self.assertFalse(kwargs["save_report"])
        self.assertFalse(kwargs["display_report"])
        selections = kwargs["selections_override"]
        self.assertEqual(selections["ticker"], "NVDA")
        self.assertEqual(selections["analysis_date"], "2026-03-16")
        self.assertEqual(selections["llm_provider"], "openai-codex")
        self.assertEqual(selections["shallow_thinker"], "gpt-5.4")
        self.assertEqual(selections["deep_thinker"], "gpt-5.4")
        self.assertEqual(selections["openai_reasoning_effort"], "low")
        self.assertEqual(selections["auth_profile_id"], "openai-codex:user@example.com")
        self.assertEqual(len(selections["analysts"]), 4)


if __name__ == "__main__":
    unittest.main()
