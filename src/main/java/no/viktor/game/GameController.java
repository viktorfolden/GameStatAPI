package no.viktor.game;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import static no.viktor.game.ApiModels.*;

@RestController
class GameController {
    private final GameService service;

    GameController(GameService service) {
        this.service = service;
    }

    @GetMapping("/health")
    Map<String, String> health() {
        return Map.of("status", "ok");
    }

    @PostMapping("/v1/runs")
    ResponseEntity<RunResponse> submit(@AuthenticationPrincipal Jwt jwt,
                                       @Valid @RequestBody RunRequest request) {
        Submission submission = service.submit(playerId(jwt), request);
        return ResponseEntity.status(submission.created() ? HttpStatus.CREATED : HttpStatus.OK)
                .body(submission.run());
    }

    @GetMapping("/v1/me/profile")
    Profile myProfile(@AuthenticationPrincipal Jwt jwt) {
        return service.myProfile(playerId(jwt));
    }

    @PatchMapping("/v1/me/profile")
    Profile updateProfile(@AuthenticationPrincipal Jwt jwt, @Valid @RequestBody ProfileRequest request) {
        return service.updateProfile(playerId(jwt), request);
    }

    @GetMapping("/v1/me/stats")
    Stats myStats(@AuthenticationPrincipal Jwt jwt) {
        UUID id = playerId(jwt);
        return service.stats(id, id);
    }

    @GetMapping("/v1/players/{id}/stats")
    Stats playerStats(@AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return service.stats(playerId(jwt), id);
    }

    @GetMapping("/v1/leaderboards")
    List<Leaderboard> leaderboards() {
        return service.leaderboards();
    }

    @GetMapping("/v1/leaderboards/{id}")
    LeaderboardPage scores(@PathVariable String id,
                           @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
                           @RequestParam(defaultValue = "0") @Min(0) @Max(10000) int offset) {
        return service.scores(id, limit, offset);
    }

    @GetMapping("/v1/leaderboards/{id}/me")
    PlayerStanding standing(@AuthenticationPrincipal Jwt jwt, @PathVariable String id) {
        return service.standing(id, playerId(jwt));
    }

    private UUID playerId(Jwt jwt) {
        return UUID.fromString(jwt.getSubject());
    }
}
