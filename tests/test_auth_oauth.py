import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tradingagents.auth import (
    auth_store_lock,
    get_active_openai_codex_profile,
    get_profile,
    import_codex_auth_profile,
    is_profile_expired,
    login_openai_codex,
    parse_oauth_callback_input,
    upsert_profile,
)
from tradingagents.auth.paths import resolve_auth_lock_path


def _make_jwt(payload: dict) -> str:
    header = {"alg": "none", "typ": "JWT"}

    def encode(part: dict) -> str:
        raw = json.dumps(part, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    return f"{encode(header)}.{encode(payload)}.signature"


class OpenAICodexAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = self.temp_dir.name

    def test_parse_redirect_url_success(self) -> None:
        parsed = parse_oauth_callback_input(
            "http://127.0.0.1:1455/auth/callback?code=code123&state=state123",
            expected_state="state123",
        )
        self.assertEqual(parsed["code"], "code123")
        self.assertEqual(parsed["state"], "state123")

    def test_parse_redirect_url_rejects_missing_or_mismatched_state(self) -> None:
        with self.assertRaisesRegex(Exception, "state"):
            parse_oauth_callback_input("code=code123", expected_state="state123")

        with self.assertRaisesRegex(Exception, "state"):
            parse_oauth_callback_input(
                "code=code123&state=wrong",
                expected_state="state123",
            )

    def test_auth_store_round_trip_and_locking(self) -> None:
        profile_id = "openai-codex:user@example.com"
        profile = {
            "type": "oauth",
            "provider": "openai-codex",
            "access": "access-token",
            "refresh": "refresh-token",
            "expires": int(time.time() * 1000) + 300_000,
            "email": "user@example.com",
        }
        upsert_profile(profile_id, profile, state_dir=self.state_dir)
        saved = get_profile(profile_id, state_dir=self.state_dir)
        self.assertEqual(saved["email"], "user@example.com")
        self.assertFalse(is_profile_expired(saved))

        lock_path = resolve_auth_lock_path(self.state_dir)
        with auth_store_lock(self.state_dir, timeout_seconds=0.2, poll_seconds=0.01):
            self.assertTrue(lock_path.exists())
            with self.assertRaises(TimeoutError):
                with auth_store_lock(
                    self.state_dir,
                    timeout_seconds=0.05,
                    poll_seconds=0.01,
                ):
                    pass
        self.assertFalse(lock_path.exists())

    def test_import_codex_auth_profile_reads_cli_auth_json(self) -> None:
        codex_auth_path = Path(self.temp_dir.name) / "codex-auth.json"
        token = _make_jwt(
            {
                "email": "user@example.com",
                "exp": int(time.time()) + 3600,
            }
        )
        codex_auth_path.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": token,
                        "refresh_token": "refresh-token",
                        "account_id": "acct_123",
                    },
                }
            ),
            encoding="utf-8",
        )

        profile_id, profile = import_codex_auth_profile(
            state_dir=self.state_dir,
            codex_auth_path=str(codex_auth_path),
        )

        self.assertEqual(profile_id, "openai-codex:user@example.com")
        self.assertEqual(profile["account_id"], "acct_123")
        self.assertEqual(
            get_profile(profile_id, state_dir=self.state_dir)["refresh"],
            "refresh-token",
        )

    @patch("tradingagents.auth.openai_codex_oauth.exchange_authorization_code")
    @patch("tradingagents.auth.openai_codex_oauth.import_codex_auth_profile", return_value=None)
    @patch("tradingagents.auth.openai_codex_oauth.start_local_callback_listener")
    @patch("tradingagents.auth.openai_codex_oauth.webbrowser.open")
    def test_login_uses_local_callback_when_available(
        self,
        mock_browser,
        mock_listener,
        _mock_import,
        mock_exchange,
    ) -> None:
        mock_listener.return_value = (
            "http://127.0.0.1:1455/auth/callback?code=code123&state=test-state"
        )
        mock_exchange.return_value = {
            "type": "oauth",
            "provider": "openai-codex",
            "access": "access-token",
            "refresh": "refresh-token",
            "expires": int(time.time() * 1000) + 300_000,
            "email": "user@example.com",
        }

        with patch(
            "tradingagents.auth.openai_codex_oauth.generate_pkce_pair",
            return_value=("verifier", "challenge"),
        ), patch(
            "tradingagents.auth.openai_codex_oauth.secrets.token_urlsafe",
            return_value="test-state",
        ):
            profile_id, _ = login_openai_codex(
                state_dir=self.state_dir,
                print_func=lambda *args, **kwargs: None,
            )

        self.assertEqual(profile_id, "openai-codex:user@example.com")
        mock_browser.assert_called_once()
        mock_listener.assert_called_once()
        mock_exchange.assert_called_once()

    @patch("tradingagents.auth.openai_codex_oauth.exchange_authorization_code")
    @patch("tradingagents.auth.openai_codex_oauth.import_codex_auth_profile", return_value=None)
    def test_login_headless_accepts_manual_redirect_value(self, _mock_import, mock_exchange) -> None:
        mock_exchange.return_value = {
            "type": "oauth",
            "provider": "openai-codex",
            "access": "access-token",
            "refresh": "refresh-token",
            "expires": int(time.time() * 1000) + 300_000,
        }

        with patch(
            "tradingagents.auth.openai_codex_oauth.generate_pkce_pair",
            return_value=("verifier", "challenge"),
        ), patch(
            "tradingagents.auth.openai_codex_oauth.secrets.token_urlsafe",
            return_value="headless-state",
        ):
            profile_id, profile = login_openai_codex(
                state_dir=self.state_dir,
                headless=True,
                input_func=lambda _: "code=manual-code&state=headless-state",
                print_func=lambda *args, **kwargs: None,
            )

        self.assertEqual(profile_id, "openai-codex:default")
        self.assertEqual(profile["refresh"], "refresh-token")

    @patch("tradingagents.auth.openai_codex_oauth.start_local_callback_listener")
    @patch("tradingagents.auth.openai_codex_oauth.webbrowser.open")
    @patch("tradingagents.auth.openai_codex_oauth.requests.post")
    def test_codex_cli_import_is_preferred_over_browser_login(
        self,
        mock_post,
        mock_browser,
        mock_listener,
    ) -> None:
        codex_auth_path = Path(self.temp_dir.name) / "codex-auth.json"
        token = _make_jwt({"email": "reuse@example.com", "exp": int(time.time()) + 3600})
        codex_auth_path.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": token,
                        "refresh_token": "refresh-token",
                    },
                }
            ),
            encoding="utf-8",
        )

        profile_id, _ = login_openai_codex(
            state_dir=self.state_dir,
            codex_auth_path=str(codex_auth_path),
            print_func=lambda *args, **kwargs: None,
        )

        self.assertEqual(profile_id, "openai-codex:reuse@example.com")
        mock_post.assert_not_called()
        mock_browser.assert_not_called()
        mock_listener.assert_not_called()

    def test_get_active_profile_auto_imports_codex_auth(self) -> None:
        codex_auth_path = Path(self.temp_dir.name) / "codex-auth.json"
        token = _make_jwt({"email": "auto@example.com", "exp": int(time.time()) + 3600})
        codex_auth_path.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": token,
                        "refresh_token": "refresh-token",
                    },
                }
            ),
            encoding="utf-8",
        )

        with patch(
            "tradingagents.auth.openai_codex_oauth.import_codex_auth_profile",
            wraps=lambda state_dir=None, profile_id=None: import_codex_auth_profile(
                state_dir=state_dir,
                profile_id=profile_id,
                codex_auth_path=str(codex_auth_path),
            ),
        ):
            profile_id, profile = get_active_openai_codex_profile(
                state_dir=self.state_dir,
            )

        self.assertEqual(profile_id, "openai-codex:auto@example.com")
        self.assertEqual(profile["provider"], "openai-codex")


if __name__ == "__main__":
    unittest.main()
