import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
import requests

from space_demo import DemoApi, SpaceDemo, main
from space_round import SpaceRound


STATS = {
    "playerId": "example-player",
    "runsPlayed": 1,
    "bestScore": 100,
    "hits": 1,
    "misses": 1,
    "enemiesKilled": 1,
    "playTimeSeconds": 10,
    "accuracyPercent": 50,
}


class DemoApiTest(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.my_stats.return_value = STATS
        self.client.leaderboard.return_value = {"entries": []}
        self.client.my_standing.return_value = {"player": {"rank": 3}}
        self.client.round_summary.return_value = {"previous": {"roundsPlayed": 0}}
        self.api = DemoApi(self.client, "default")
        self.addCleanup(self.api.close)

    def complete(self):
        # Waiting here is test-only; the actual UI polls without blocking.
        from concurrent.futures import wait
        done, pending = wait([self.api.future], timeout=3)
        self.assertFalse(pending)
        self.assertEqual(len(done), 1)
        self.api.poll()

    def test_save_then_refresh_uses_existing_client(self):
        result = SpaceRound().finish("Finished")
        self.api.submit(result)
        self.complete()
        self.assertIsNone(self.api.pending)
        self.assertEqual(self.api.saved_id, result.run_id)
        self.complete()
        self.assertEqual(self.api.stats, STATS)
        self.assertEqual(self.api.rank, 3)
        self.client.submit_run.assert_called_once_with(**result.api_arguments())
        self.client.leaderboard.assert_called_once_with("default", limit=7)
        self.client.round_summary.assert_called_once_with(result.run_id)
        self.assertEqual(self.api.summary, self.client.round_summary.return_value)

    def test_failed_submission_retains_exact_payload_for_retry(self):
        result = SpaceRound().finish("Finished")
        self.client.submit_run.side_effect = [requests.Timeout("Wake-up timeout"), {"score": 0}]
        self.api.submit(result)
        self.complete()
        self.assertIs(self.api.pending, result)
        self.assertTrue(self.api.error)
        self.assertIsNone(self.api.saved_id)
        self.assertIn("SAME round", self.api.status)
        with self.assertRaises(RuntimeError):
            self.api.submit(SpaceRound().finish("New"))
        self.api.submit(self.api.pending)
        self.complete()
        self.complete()
        calls = self.client.submit_run.call_args_list
        self.assertEqual(calls[0], calls[1])
        self.assertIsNone(self.api.pending)

    def test_stats_failure_does_not_mark_saved_round_unsaved(self):
        result = SpaceRound().finish("Finished")
        self.client.my_stats.side_effect = requests.ConnectionError("Offline")
        self.api.submit(result)
        self.complete()
        self.complete()
        self.assertEqual(self.api.saved_id, result.run_id)
        self.assertIsNone(self.api.pending)
        self.assertIn("Stats unavailable", self.api.status)
        self.api.refresh()
        self.complete()
        self.client.submit_run.assert_called_once()

    def test_http_failure_is_visible_and_retry_can_be_discarded(self):
        response = requests.Response()
        response.status_code = 404
        self.client.submit_run.side_effect = requests.HTTPError(response=response)
        self.api.submit(SpaceRound("missing").finish("Finished"))
        self.complete()
        self.assertIn("HTTP 404", self.api.status)
        self.api.discard()
        self.assertIsNone(self.api.pending)

    def test_summary_failure_can_be_retried_without_resubmitting(self):
        result = SpaceRound().finish("Finished")
        self.client.round_summary.side_effect = [
            requests.Timeout("Unavailable"), {"previous": {"roundsPlayed": 2}},
        ]
        self.api.submit(result)
        self.complete()
        self.complete()
        self.assertIsNone(self.api.summary)
        self.assertEqual(self.api.saved_id, result.run_id)
        self.assertTrue(self.api.error)
        self.api.refresh()
        self.complete()
        self.assertEqual(self.api.summary["previous"]["roundsPlayed"], 2)
        self.client.submit_run.assert_called_once()


class DemoWindowTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"})
        self.env.start()
        self.addCleanup(self.env.stop)
        pygame.init()
        self.addCleanup(pygame.quit)
        self.client = Mock()
        self.api = DemoApi(self.client, "default")
        self.addCleanup(self.api.close)
        self.api.stats = STATS
        self.api.entries = [{"rank": 1, "playerId": "example-player", "displayName": "Pilot", "score": 100}]
        self.demo = SpaceDemo(self.api)

    def key(self, key):
        self.demo.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))

    def test_menu_game_pause_results_and_quit_confirmation_render(self):
        self.demo.draw()
        self.key(pygame.K_RETURN)
        self.assertIsNotNone(self.demo.round)
        self.demo.tick()
        self.demo.draw()
        self.key(pygame.K_p)
        self.assertTrue(self.demo.round.paused)
        self.demo.draw()
        self.key(pygame.K_q)
        self.assertTrue(self.demo.quit_confirm)
        self.assertTrue(self.demo.running)
        self.key(pygame.K_n)
        self.key(pygame.K_p)
        self.demo.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        self.assertTrue(self.demo.round.paused)
        with patch.object(self.api, "submit") as submit:
            self.key(pygame.K_ESCAPE)
            submit.assert_called_once_with(self.demo.round.result)
        self.demo.draw()

    def test_unsaved_round_prevents_new_game_and_requires_explicit_discard(self):
        self.api.pending = SpaceRound().finish("Finished")
        self.key(pygame.K_RETURN)
        self.assertIsNone(self.demo.round)
        self.key(pygame.K_q)
        self.assertTrue(self.demo.quit_confirm)
        self.key(pygame.K_n)
        self.key(pygame.K_d)
        self.key(pygame.K_RETURN)
        self.assertIsNotNone(self.demo.round)

    def test_time_limit_submits_once_without_blocking_the_ui(self):
        self.demo.start_round()
        self.demo.round.elapsed = 59.99
        self.demo.last_tick -= 0.02
        with patch.object(self.api, "submit") as submit:
            self.demo.tick()
            self.demo.tick()
            submit.assert_called_once_with(self.demo.round.result)
            self.assertEqual(self.demo.round.result.play_time_seconds, 60)

    def test_finished_round_displays_personal_and_opponent_comparisons(self):
        self.demo.start_round()
        result = self.demo.round.finish("Finished")
        self.api.saved_id = result.run_id
        self.api.summary = {
            "runId": str(result.run_id), "leaderboardId": "default",
            "previous": {"roundsPlayed": 2, "averageScore": 100,
                         "averageKills": 1, "accuracyPercent": 50},
            "bestOtherPlayer": {"displayName": "Other pilot", "score": 200},
        }
        with patch.object(self.demo, "text", wraps=self.demo.text) as render:
            self.demo.draw()
            text = "\n".join(str(call.args[0]) for call in render.call_args_list)
            self.assertIn("100% fewer points", text)
            self.assertIn("Other pilot", text)
            self.assertIn("100% below their best score", text)


class DemoLoginTest(unittest.TestCase):
    def test_signup_returns_to_terminal_for_email_confirmation(self):
        with patch("sys.argv", ["space_demo.py"]), patch.dict(os.environ, {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "public-key",
            "GAME_API_URL": "http://localhost:8080",
        }), patch("space_demo.GameClient") as factory, \
                patch("builtins.input", side_effect=["s", "pilot@example.com"]), \
                patch("space_demo.getpass", return_value="example-password"), \
                patch("builtins.print"), patch("space_demo.SpaceDemo") as window:
            main()
            factory.return_value.sign_up.assert_called_once_with("pilot@example.com", "example-password")
            factory.return_value.sign_in.assert_not_called()
            window.assert_not_called()

    def test_failed_login_does_not_open_game(self):
        with patch("sys.argv", ["space_demo.py"]), patch.dict(os.environ, {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "public-key",
            "GAME_API_URL": "http://localhost:8080",
        }), patch("space_demo.GameClient") as factory, \
                patch("builtins.input", side_effect=["l", "pilot@example.com"]), \
                patch("space_demo.getpass", return_value="example-password"), \
                patch("builtins.print"), patch("space_demo.SpaceDemo") as window:
            factory.return_value.sign_in.side_effect = requests.ConnectionError("Offline")
            with self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 1)
            window.assert_not_called()


if __name__ == "__main__":
    unittest.main()
