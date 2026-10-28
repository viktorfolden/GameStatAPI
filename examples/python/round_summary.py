"""Human-readable comparisons using a saved round's server-side baseline."""

from decimal import Decimal

from space_round import RoundResult


def _number(value: Decimal) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _difference(value, baseline, higher: str, lower: str, equal: str) -> str:
    current, previous = Decimal(str(value)), Decimal(str(baseline))
    if current == previous:
        return equal
    if previous == 0:
        return f"{higher} (baseline was 0; percentage unavailable)"
    delta = (current - previous) / previous * 100
    amount = abs(delta)
    percent = "<0.1" if amount < Decimal("0.1") else _number(amount)
    return f"{percent}% {higher if delta > 0 else lower}"


def summary_lines(result: RoundResult, summary: dict) -> list[str]:
    if summary["runId"] != str(result.run_id) or summary["leaderboardId"] != result.leaderboard_id:
        raise ValueError("Summary does not belong to this round")
    previous = summary["previous"]
    lines = []
    if previous["roundsPlayed"] == 0:
        lines.append("Your first round on this board - no previous average yet.")
    else:
        lines.append(f"Compared with your {previous['roundsPlayed']} previous rounds on this board:")
        shots = result.hits + result.misses
        accuracy = Decimal(result.hits) * 100 / shots if shots else None
        baseline = previous["accuracyPercent"]
        if accuracy is None:
            lines.append("Accuracy: no shots fired this round.")
        elif baseline is None:
            lines.append(f"Accuracy: {_number(accuracy)}% (no previous shots to compare).")
        else:
            difference = _difference(accuracy, baseline, "more accurate", "less accurate", "same accuracy")
            lines.append(f"Accuracy: {_number(accuracy)}% vs {_number(Decimal(str(baseline)))}% - {difference}.")
        kills = _difference(result.enemies_killed, previous["averageKills"],
                            "more kills", "fewer kills", "same kills as your average")
        score = _difference(result.score, previous["averageScore"],
                            "more points", "fewer points", "same points as your average")
        lines.extend([f"Kills: {kills}.", f"Score: {score}."])

    opponent = summary["bestOtherPlayer"]
    if opponent is None:
        lines.append("No other players have a score on this board yet.")
    else:
        lines.append(f"Best other player: {opponent['displayName']} - {opponent['score']} points.")
        difference = _difference(result.score, opponent["score"],
                                 "above their best score", "below their best score", "tied with their best score")
        lines.append(f"Your round: {difference}.")
    return lines
