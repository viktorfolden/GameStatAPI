package no.viktor.game;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;

public final class ApiModels {
    private ApiModels() {}

    public record RunRequest(
            @NotNull UUID runId,
            @NotBlank @Pattern(regexp = "[a-z0-9][a-z0-9-]{0,63}") String leaderboardId,
            @NotNull @PositiveOrZero Long score,
            @NotNull @PositiveOrZero Integer hits,
            @NotNull @PositiveOrZero Integer misses,
            @NotNull @PositiveOrZero Integer enemiesKilled,
            @NotNull @PositiveOrZero Integer playTimeSeconds) {}

    public record RunResponse(UUID runId, String leaderboardId, long score, int hits,
                              int misses, int enemiesKilled, int playTimeSeconds,
                              OffsetDateTime submittedAt) {}

    public record Submission(RunResponse run, boolean created) {}

    public record ProfileRequest(
            @NotBlank @Size(max = 32)
            @Pattern(regexp = "[\\p{L}\\p{N} _.-]+") String displayName,
            @NotNull Boolean shareStats) {}

    public record Profile(UUID playerId, String displayName, boolean shareStats) {}

    public record Stats(UUID playerId, long runsPlayed, long bestScore, long hits,
                        long misses, long enemiesKilled, long playTimeSeconds,
                        BigDecimal accuracyPercent) {}

    public record Leaderboard(String id, String name, String gameVersion, String gameMode,
                              String difficulty, String season, boolean acceptingRuns) {}

    public record LeaderboardEntry(UUID playerId, String displayName, long score, long rank) {}

    public record LeaderboardPage(Leaderboard leaderboard, List<LeaderboardEntry> entries,
                                  int limit, int offset) {}

    public record PlayerStanding(Leaderboard leaderboard, LeaderboardEntry player,
                                 List<LeaderboardEntry> neighbors) {}
}
