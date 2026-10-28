import unittest
from uuid import uuid4

from round_summary import summary_lines
from space_round import RoundResult


class RoundSummaryTest(unittest.TestCase):
    def setUp(self):
        self.result = RoundResult(uuid4(), "default", 190, 9, 1, 9, 60)
        self.summary = {
            "runId": str(self.result.run_id), "leaderboardId": "default",
            "previous": {"roundsPlayed": 2, "averageScore": 200,
                         "averageKills": 10, "accuracyPercent": 75},
            "bestOtherPlayer": {"playerId": "other", "displayName": "Pilot",
                                "score": 250, "rank": 1},
        }

    def test_requested_percentages_and_best_other_score(self):
        text = "\n".join(summary_lines(self.result, self.summary))
        self.assertIn("90% vs 75% - 20% more accurate", text)
        self.assertIn("10% fewer kills", text)
        self.assertIn("5% fewer points", text)
        self.assertIn("Pilot - 250 points", text)
        self.assertIn("24% below their best score", text)

    def test_first_round_and_no_other_players(self):
        self.summary["previous"] = {"roundsPlayed": 0, "averageScore": None,
                                    "averageKills": None, "accuracyPercent": None}
        self.summary["bestOtherPlayer"] = None
        text = "\n".join(summary_lines(self.result, self.summary))
        self.assertIn("first round", text)
        self.assertIn("No other players", text)

    def test_zero_baselines_do_not_divide_by_zero(self):
        self.summary["previous"].update(averageScore=0, averageKills=0, accuracyPercent=0)
        self.summary["bestOtherPlayer"]["score"] = 0
        text = "\n".join(summary_lines(self.result, self.summary))
        self.assertEqual(text.count("baseline was 0"), 4)
        self.assertNotIn("inf", text)

    def test_equal_values_and_absent_accuracy_are_explicit(self):
        self.summary["previous"].update(averageScore=190, averageKills=9, accuracyPercent=None)
        self.summary["bestOtherPlayer"]["score"] = 190
        text = "\n".join(summary_lines(self.result, self.summary))
        self.assertIn("no previous shots", text)
        self.assertIn("same kills as your average", text)
        self.assertIn("same points as your average", text)
        self.assertIn("tied with their best score", text)
        result = RoundResult(self.result.run_id, "default", 0, 0, 0, 0, 60)
        self.assertIn("no shots fired this round", "\n".join(summary_lines(result, self.summary)))

    def test_improvement_and_small_differences(self):
        self.summary["previous"].update(averageScore=100, averageKills=5, accuracyPercent=95)
        self.summary["bestOtherPlayer"]["score"] = 189.99
        text = "\n".join(summary_lines(self.result, self.summary))
        self.assertIn("90% more points", text)
        self.assertIn("80% more kills", text)
        self.assertIn("less accurate", text)
        self.assertIn("<0.1% above their best score", text)

    def test_other_round_or_board_is_rejected(self):
        self.summary["runId"] = str(uuid4())
        with self.assertRaises(ValueError):
            summary_lines(self.result, self.summary)
        self.summary["runId"] = str(self.result.run_id)
        self.summary["leaderboardId"] = "another-board"
        with self.assertRaises(ValueError):
            summary_lines(self.result, self.summary)


if __name__ == "__main__":
    unittest.main()
