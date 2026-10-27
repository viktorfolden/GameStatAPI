package no.viktor.game;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import static no.viktor.game.ApiModels.*;

@Repository
class GameRepository {
    private static final String RANKED_SCORES = """
            WITH best AS (
                SELECT player_id, MAX(score) AS score
                FROM game.runs WHERE leaderboard_id = ?
                GROUP BY player_id
            ), ranked AS (
                SELECT b.player_id, p.display_name, b.score,
                       RANK() OVER (ORDER BY b.score DESC) AS rank,
                       ROW_NUMBER() OVER (ORDER BY b.score DESC, b.player_id) AS position
                FROM best b JOIN game.players p ON p.id = b.player_id
            )
            """;

    private final JdbcTemplate jdbc;

    GameRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    void ensurePlayer(UUID playerId) {
        jdbc.update("INSERT INTO game.players (id) VALUES (?) ON CONFLICT (id) DO NOTHING", playerId);
    }

    Optional<Profile> profile(UUID playerId) {
        return jdbc.query("SELECT id, display_name, share_stats FROM game.players WHERE id = ?",
                (rs, row) -> new Profile(rs.getObject("id", UUID.class),
                        rs.getString("display_name"), rs.getBoolean("share_stats")), playerId)
                .stream().findFirst();
    }

    void updateProfile(UUID playerId, ProfileRequest request) {
        jdbc.update("UPDATE game.players SET display_name = ?, share_stats = ? WHERE id = ?",
                request.displayName(), request.shareStats(), playerId);
    }

    List<Leaderboard> leaderboards() {
        return jdbc.query("SELECT * FROM game.leaderboards ORDER BY id", this::mapLeaderboard);
    }

    Optional<Leaderboard> leaderboard(String id) {
        return jdbc.query("SELECT * FROM game.leaderboards WHERE id = ?", this::mapLeaderboard, id)
                .stream().findFirst();
    }

    boolean insertRun(UUID playerId, RunRequest run) {
        return jdbc.update("""
                INSERT INTO game.runs
                    (id, player_id, leaderboard_id, score, hits, misses, enemies_killed, play_time_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING
                """, run.runId(), playerId, run.leaderboardId(), run.score(), run.hits(),
                run.misses(), run.enemiesKilled(), run.playTimeSeconds()) == 1;
    }

    Optional<RunResponse> run(UUID playerId, UUID runId) {
        return jdbc.query("SELECT * FROM game.runs WHERE id = ? AND player_id = ?",
                (rs, row) -> new RunResponse(rs.getObject("id", UUID.class),
                        rs.getString("leaderboard_id"), rs.getLong("score"), rs.getInt("hits"),
                        rs.getInt("misses"), rs.getInt("enemies_killed"), rs.getInt("play_time_seconds"),
                        rs.getObject("submitted_at", OffsetDateTime.class)), runId, playerId)
                .stream().findFirst();
    }

    Stats stats(UUID playerId) {
        return jdbc.queryForObject("""
                SELECT COUNT(*) AS runs_played, COALESCE(MAX(score), 0) AS best_score,
                       COALESCE(SUM(hits), 0) AS hits, COALESCE(SUM(misses), 0) AS misses,
                       COALESCE(SUM(enemies_killed), 0) AS enemies_killed,
                       COALESCE(SUM(play_time_seconds), 0) AS play_time_seconds
                FROM game.runs WHERE player_id = ?
                """, (rs, row) -> {
            long hits = rs.getLong("hits");
            long misses = rs.getLong("misses");
            BigDecimal shots = BigDecimal.valueOf(hits).add(BigDecimal.valueOf(misses));
            BigDecimal accuracy = shots.signum() == 0 ? null
                    : BigDecimal.valueOf(hits).multiply(BigDecimal.valueOf(100))
                    .divide(shots, 2, RoundingMode.HALF_UP);
            return new Stats(playerId, rs.getLong("runs_played"), rs.getLong("best_score"),
                    hits, misses, rs.getLong("enemies_killed"), rs.getLong("play_time_seconds"), accuracy);
        }, playerId);
    }

    List<LeaderboardEntry> scores(String leaderboardId, int limit, int offset) {
        return jdbc.query(RANKED_SCORES + "SELECT * FROM ranked ORDER BY position LIMIT ? OFFSET ?",
                this::mapEntry, leaderboardId, limit, offset);
    }

    List<LeaderboardEntry> neighbors(String leaderboardId, UUID playerId) {
        return jdbc.query(RANKED_SCORES + """
                SELECT * FROM ranked
                WHERE position BETWEEN
                    (SELECT position FROM ranked WHERE player_id = ?) - 2
                    AND (SELECT position FROM ranked WHERE player_id = ?) + 2
                ORDER BY position
                """, this::mapEntry, leaderboardId, playerId, playerId);
    }

    private Leaderboard mapLeaderboard(ResultSet rs, int row) throws SQLException {
        return new Leaderboard(rs.getString("id"), rs.getString("name"), rs.getString("game_version"),
                rs.getString("game_mode"), rs.getString("difficulty"), rs.getString("season"),
                rs.getBoolean("accepting_runs"));
    }

    private LeaderboardEntry mapEntry(ResultSet rs, int row) throws SQLException {
        return new LeaderboardEntry(rs.getObject("player_id", UUID.class),
                rs.getString("display_name"), rs.getLong("score"), rs.getLong("rank"));
    }
}
