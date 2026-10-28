import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch
from uuid import uuid4

import requests
from supabase_auth.errors import AuthApiError

from game_client import GameClient, LoginRequiredError, main, recover_password_interactively


def response(status: int, data: dict) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    return result


class GameClientTest(unittest.TestCase):
    def setUp(self):
        self.sdk_patch = patch("game_client.create_client")
        self.http_patch = patch("game_client.requests.Session")
        self.sdk = self.sdk_patch.start()
        self.http = self.http_patch.start().return_value
        self.addCleanup(self.sdk_patch.stop)
        self.addCleanup(self.http_patch.stop)
        self.auth = self.sdk.return_value.auth
        self.auth.get_session.return_value = SimpleNamespace(access_token="first-token")
        self.client = GameClient(
            "https://example.supabase.co", "sb_publishable_example", "http://localhost:8080"
        )

    def test_sessions_are_not_persisted_and_passwords_go_only_to_supabase(self):
        options = self.sdk.call_args.kwargs["options"]
        self.assertFalse(options.persist_session)
        self.assertFalse(options.auto_refresh_token)
        self.client.sign_up("player@example.com", "example-password")
        self.client.sign_in("player@example.com", "example-password")
        self.auth.sign_in_with_password.assert_called_once_with(
            {"email": "player@example.com", "password": "example-password"}
        )
        self.http.request.assert_not_called()
        self.client.sign_out()
        self.auth.sign_out.assert_called_once_with({"scope": "local"})

    def test_requires_login(self):
        self.auth.get_session.return_value = None
        with self.assertRaises(LoginRequiredError):
            self.client.my_stats()
        self.http.request.assert_not_called()

    def test_password_reset_verifies_recovery_before_updating_password(self):
        self.client.request_password_reset("player@example.com")
        self.client.reset_password("player@example.com", " 012345 ", "new-password")
        self.assertEqual(self.auth.mock_calls, [
            call.reset_password_email("player@example.com"),
            call.verify_otp({"email": "player@example.com", "token": "012345", "type": "recovery"}),
            call.update_user({"password": "new-password"}),
        ])
        self.http.request.assert_not_called()

    def test_invalid_or_expired_recovery_cannot_update_password(self):
        self.auth.verify_otp.side_effect = AuthApiError("Code expired", 403, "otp_expired")
        with self.assertRaises(AuthApiError):
            self.client.reset_password("player@example.com", "012345", "new-password")
        self.auth.update_user.assert_not_called()

    def test_recovery_requires_session_and_confirmed_update(self):
        self.auth.verify_otp.return_value = SimpleNamespace(session=None)
        with self.assertRaises(LoginRequiredError):
            self.client.reset_password("player@example.com", "012345", "new-password")
        self.auth.update_user.assert_not_called()
        self.auth.verify_otp.return_value = SimpleNamespace(session=object())
        self.auth.update_user.return_value = SimpleNamespace(user=None)
        with self.assertRaises(LoginRequiredError):
            self.client.reset_password("player@example.com", "012345", "new-password")

    def test_empty_recovery_inputs_do_not_contact_supabase(self):
        for values in [("", "code", "password"), ("email", " ", "password"), ("email", "code", "")]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.client.reset_password(*values)
        self.auth.verify_otp.assert_not_called()
        self.auth.update_user.assert_not_called()

    def test_refresh_reuses_the_exact_round_payload(self):
        self.http.request.side_effect = [response(401, {}), response(201, {"score": 42})]
        self.auth.refresh_session.return_value = SimpleNamespace(
            session=SimpleNamespace(access_token="refreshed-token")
        )
        run_id = uuid4()
        result = self.client.submit_run(
            run_id=run_id, score=42, hits=8, misses=2, enemies_killed=3, play_time_seconds=60
        )
        self.assertEqual(result["score"], 42)
        first, second = self.http.request.call_args_list
        self.assertEqual(first.kwargs["json"], second.kwargs["json"])
        self.assertEqual(first.kwargs["json"]["runId"], str(run_id))
        self.assertEqual(second.kwargs["headers"]["Authorization"], "Bearer refreshed-token")
        self.assertFalse(second.kwargs["allow_redirects"])
        self.assertEqual(second.kwargs["timeout"], (5, 15))

    def test_errors_are_propagated_without_infinite_retries(self):
        self.auth.refresh_session.return_value = SimpleNamespace(
            session=SimpleNamespace(access_token="refreshed-token")
        )
        for code in [401, 403, 409, 429, 500, 302]:
            with self.subTest(status=code):
                self.http.request.reset_mock()
                self.http.request.return_value = response(code, {})
                with self.assertRaises(requests.HTTPError):
                    self.client.my_stats()
                self.assertEqual(self.http.request.call_count, 2 if code == 401 else 1)

    def test_profile_and_leaderboard_calls(self):
        self.http.request.return_value = response(200, {})
        self.client.update_profile("Viktor", share_stats=True)
        self.assertEqual(
            self.http.request.call_args.kwargs["json"],
            {"displayName": "Viktor", "shareStats": True},
        )
        self.client.leaderboard(limit=10, offset=20)
        self.assertEqual(self.http.request.call_args.kwargs["params"], {"limit": 10, "offset": 20})
        self.client.my_standing()
        self.assertTrue(self.http.request.call_args.args[1].endswith("/v1/leaderboards/default/me"))

    def test_round_summary_uses_authenticated_round_endpoint(self):
        run_id = uuid4()
        self.http.request.return_value = response(200, {"runId": str(run_id)})
        self.assertEqual(self.client.round_summary(run_id), {"runId": str(run_id)})
        self.assertEqual(self.http.request.call_args.args,
                         ("GET", f"http://localhost:8080/v1/runs/{run_id}/summary"))
        self.assertIn("Authorization", self.http.request.call_args.kwargs["headers"])

    def test_rejects_insecure_remote_urls(self):
        for url in [
            "http://api.example.com",
            "ftp://api.example.com",
            "https://user:password@api.example.com",
            "https://api.example.com?key=secret",
            "https://",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                GameClient("https://example.supabase.co", "sb_publishable_example", url)


class CommandLineTest(unittest.TestCase):
    def test_password_reset_command_does_not_require_old_password(self):
        for extra in [[], ["--use-existing-code"]]:
            with self.subTest(extra=extra), patch("sys.argv", ["game_client.py", "reset-password", *extra]), \
                    patch.dict("os.environ", {
                        "SUPABASE_URL": "https://example.supabase.co",
                        "SUPABASE_PUBLISHABLE_KEY": "public-key",
                        "GAME_API_URL": "http://localhost:8080",
                    }), patch("game_client.GameClient") as factory, \
                    patch("builtins.input", return_value="player@example.com"), \
                    patch("game_client.recover_password_interactively") as recover, \
                    patch("game_client.getpass") as old_password:
                main()
                recover.assert_called_once_with(factory.return_value, "player@example.com",
                                                send_email=not bool(extra))
                old_password.assert_not_called()
                factory.return_value.sign_in.assert_not_called()

    def test_submit_logs_in_and_passes_round_fields(self):
        run_id = uuid4()
        args = [
            "game_client.py", "submit", "--run-id", str(run_id), "--score", "12500",
            "--hits", "85", "--misses", "15", "--enemies-killed", "32",
            "--play-time-seconds", "420",
        ]
        with patch("sys.argv", args), patch.dict("os.environ", {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "public-key",
            "GAME_API_URL": "http://localhost:8080",
        }), patch("game_client.GameClient") as factory, \
                patch("builtins.input", return_value="player@example.com"), \
                patch("game_client.getpass", return_value="password"), patch("builtins.print"):
            client = factory.return_value
            client.submit_run.return_value = {"score": 12500}
            client.my_stats.return_value = {"runsPlayed": 1}
            main()
            client.sign_in.assert_called_once_with("player@example.com", "password")
            client.submit_run.assert_called_once_with(
                run_id=run_id, leaderboard_id="default", score=12500, hits=85,
                misses=15, enemies_killed=32, play_time_seconds=420,
            )
            client.my_stats.assert_called_once()
            client.sign_out.assert_called_once()

    def test_invalid_submit_stops_before_login(self):
        base = [
            "game_client.py", "submit", "--run-id", str(uuid4()), "--score", "-1",
            "--hits", "0", "--misses", "0", "--enemies-killed", "0",
            "--play-time-seconds", "0",
        ]
        for args in [base, ["game_client.py", "submit"]]:
            with self.subTest(args=args), patch("sys.argv", args), \
                    patch("sys.stderr"), patch("game_client.GameClient") as factory:
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)
                factory.assert_not_called()


class PasswordRecoveryPromptTest(unittest.TestCase):
    def test_confirmation_mismatch_reprompts_before_consuming_code(self):
        client = Mock()
        with patch("game_client.getpass", side_effect=[
            "012345", "password", "mismatch", "new-password", "new-password",
        ]), patch("builtins.print") as output:
            recover_password_interactively(client, "player@example.com")
        client.request_password_reset.assert_called_once_with("player@example.com")
        client.reset_password.assert_called_once_with("player@example.com", "012345", "new-password")
        client.sign_out.assert_called_once()
        text = "\n".join(str(c.args[0]) for c in output.call_args_list)
        self.assertIn("If this address has an eligible account", text)
        self.assertIn("Password updated", text)
        self.assertNotIn("012345", text)
        self.assertNotIn("new-password", text)

    def test_existing_code_does_not_send_another_email(self):
        client = Mock()
        with patch("game_client.getpass", side_effect=["012345", "new-password", "new-password"]), \
                patch("builtins.print"):
            recover_password_interactively(client, "player@example.com", send_email=False)
        client.request_password_reset.assert_not_called()
        client.reset_password.assert_called_once()

    def test_reset_failure_does_not_report_success(self):
        for failure in [
            AuthApiError("Code expired", 403, "otp_expired"),
            AuthApiError("Password requirements not met", 422, "weak_password"),
            requests.Timeout("Connection timed out"),
        ]:
            with self.subTest(failure=failure):
                client = Mock()
                client.reset_password.side_effect = failure
                with patch("game_client.getpass", side_effect=["012345", "new-password", "new-password"]), \
                        patch("builtins.print") as output, self.assertRaises(SystemExit) as exit_error:
                    recover_password_interactively(client, "player@example.com")
                self.assertEqual(exit_error.exception.code, 1)
                self.assertNotIn("Password updated", "\n".join(str(c.args[0]) for c in output.call_args_list))
                client.sign_out.assert_not_called()

    def test_mail_failure_does_not_prompt_for_code(self):
        client = Mock()
        client.request_password_reset.side_effect = AuthApiError("Too many requests", 429, "over_email_send_rate_limit")
        with patch("game_client.getpass") as prompt, patch("builtins.print"), self.assertRaises(SystemExit):
            recover_password_interactively(client, "player@example.com")
        prompt.assert_not_called()
        client.reset_password.assert_not_called()


if __name__ == "__main__":
    unittest.main()
