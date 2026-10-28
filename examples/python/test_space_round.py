import unittest

from space_round import Enemy, PLAYER_Y, SpaceRound


class SpaceRoundTest(unittest.TestCase):
    def test_hits_count_one_enemy_per_shot(self):
        game = SpaceRound()
        game.enemies = [Enemy(380, 450), Enemy(380, 450)]
        game.fire()
        game.update(0.1)
        self.assertEqual(game.hits, 1)
        self.assertEqual(len(game.enemies), 1)
        self.assertEqual(game.shots, [])

    def test_shots_leaving_screen_are_misses(self):
        game = SpaceRound()
        game.player_x = 25
        game.fire()
        game.update(1)
        self.assertEqual(game.hits, 0)
        self.assertEqual(game.misses, 1)

    def test_pause_excludes_time_movement_and_shots(self):
        game = SpaceRound()
        game.paused = True
        game.fire()
        game.update(20, movement=1, firing=True)
        self.assertEqual(game.elapsed, 0)
        self.assertEqual(game.player_x, 400)
        self.assertEqual(game.shots_fired, 0)
        game.paused = False
        game.update(0.1, movement=1, firing=True)
        self.assertAlmostEqual(game.elapsed, 0.1)
        self.assertGreater(game.player_x, 400)
        self.assertEqual(game.shots_fired, 1)

    def test_result_is_frozen_and_repeated_finish_is_idempotent(self):
        game = SpaceRound("demo-board")
        game.update(1.5)
        game.fire()
        result = game.finish("Finished")
        self.assertEqual(result.play_time_seconds, 1)
        self.assertEqual(result.misses, 1)
        self.assertEqual(result.hits + result.misses, game.shots_fired)
        game.update(10, firing=True)
        self.assertIs(game.finish("Again"), result)
        self.assertEqual(result.api_arguments()["leaderboard_id"], "demo-board")
        self.assertNotEqual(SpaceRound().run_id, result.run_id)

    def test_wave_advances_and_score_matches_kills(self):
        game = SpaceRound()
        game.enemies = [Enemy(380, 450)]
        game.fire()
        game.update(0.1)
        self.assertEqual(game.wave, 2)
        self.assertEqual(len(game.enemies), 24)
        result = game.finish("Finished")
        self.assertEqual(result.enemies_killed, 1)
        self.assertEqual(result.score, 100)

    def test_time_limit_and_invasion_finish_round(self):
        game = SpaceRound()
        game.elapsed = 59.9
        game.update(0.5)
        self.assertEqual(game.result.play_time_seconds, 60)
        self.assertEqual(game.end_reason, "Time is up")
        game = SpaceRound()
        game.enemies = [Enemy(300, PLAYER_Y)]
        game.update(0.1)
        self.assertIsNotNone(game.result)
        self.assertEqual(game.end_reason, "The invaders reached your ship")

    def test_movement_and_rate_of_fire_are_bounded(self):
        game = SpaceRound()
        game.update(2, movement=-1, firing=True)
        self.assertEqual(game.player_x, 25)
        self.assertLessEqual(game.shots_fired, 9)
        result = game.finish("Finished")
        self.assertEqual(result.hits + result.misses, game.shots_fired)
        with self.assertRaises(ValueError):
            SpaceRound().update(-1)


if __name__ == "__main__":
    unittest.main()
