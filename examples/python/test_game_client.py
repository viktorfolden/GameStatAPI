import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import requests

from game_client import GameClient, LoginRequiredError, main


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


if __name__ == "__main__":
    unittest.main()
