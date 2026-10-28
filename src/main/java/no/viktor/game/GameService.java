package no.viktor.game;

import java.util.List;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.annotation.Isolation;

import static no.viktor.game.ApiModels.*;

@Service
class GameService {
    private final GameRepository repository;

    GameService(GameRepository repository) {
        this.repository = repository;
    }

    @Transactional
    public Submission submit(UUID playerId, RunRequest request) {
        var existing = repository.run(playerId, request.runId());
        if (existing.isPresent()) {
            return sameSubmission(request, existing.get());
        }
        Leaderboard board = leaderboard(request.leaderboardId());
        if (!board.acceptingRuns()) {
            throw new ApiException(HttpStatus.CONFLICT, "This leaderboard is closed");
        }
        repository.ensurePlayer(playerId);
        boolean created = repository.insertRun(playerId, request);
        RunResponse stored = repository.run(playerId, request.runId())
                .orElseThrow(() -> new ApiException(HttpStatus.CONFLICT, "Run ID is already in use"));
        // ON CONFLICT also handles concurrent retries without counting a round twice.
        return created ? new Submission(stored, true) : sameSubmission(request, stored);
    }

    private Submission sameSubmission(RunRequest request, RunResponse stored) {
        if (!stored.leaderboardId().equals(request.leaderboardId())
                || stored.score() != request.score() || stored.hits() != request.hits()
                || stored.misses() != request.misses() || stored.enemiesKilled() != request.enemiesKilled()
                || stored.playTimeSeconds() != request.playTimeSeconds()) {
            throw new ApiException(HttpStatus.CONFLICT, "Run ID is already in use with different data");
        }
        return new Submission(stored, false);
    }

    @Transactional
    public Profile myProfile(UUID playerId) {
        repository.ensurePlayer(playerId);
        return repository.profile(playerId).orElseThrow();
    }

    @Transactional
    public Profile updateProfile(UUID playerId, ProfileRequest request) {
        repository.ensurePlayer(playerId);
        repository.updateProfile(playerId, request);
        return repository.profile(playerId).orElseThrow();
    }

    public Stats stats(UUID requesterId, UUID playerId) {
        if (!requesterId.equals(playerId)) {
            Profile profile = repository.profile(playerId)
                    .filter(Profile::shareStats)
                    .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Player statistics not found"));
            return repository.stats(profile.playerId());
        }
        return repository.stats(playerId);
    }

    public List<Leaderboard> leaderboards() {
        return repository.leaderboards();
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public RoundSummary roundSummary(UUID playerId, UUID runId) {
        RunResponse run = repository.run(playerId, runId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Round not found"));
        return new RoundSummary(run.runId(), run.leaderboardId(),
                repository.previousRounds(playerId, run),
                repository.bestOtherPlayer(run.leaderboardId(), playerId).orElse(null));
    }

    public LeaderboardPage scores(String id, int limit, int offset) {
        return new LeaderboardPage(leaderboard(id), repository.scores(id, limit, offset), limit, offset);
    }

    public PlayerStanding standing(String id, UUID playerId) {
        Leaderboard board = leaderboard(id);
        List<LeaderboardEntry> neighbors = repository.neighbors(id, playerId);
        LeaderboardEntry player = neighbors.stream()
                .filter(entry -> entry.playerId().equals(playerId)).findFirst().orElse(null);
        return new PlayerStanding(board, player, neighbors);
    }

    private Leaderboard leaderboard(String id) {
        return repository.leaderboard(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Leaderboard not found"));
    }
}
