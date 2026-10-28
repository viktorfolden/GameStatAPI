"""Deterministic game rules, independent of graphics and the network."""

from dataclasses import dataclass
from uuid import UUID, uuid4


WIDTH = 800
HEIGHT = 560
PLAYER_Y = 505
ENEMY_WIDTH = 32
ENEMY_HEIGHT = 24
ROUND_SECONDS = 60


@dataclass
class Enemy:
    x: float
    y: float


@dataclass
class Shot:
    x: float
    y: float


@dataclass(frozen=True)
class RoundResult:
    run_id: UUID
    leaderboard_id: str
    score: int
    hits: int
    misses: int
    enemies_killed: int
    play_time_seconds: int

    def api_arguments(self) -> dict:
        return {
            "run_id": self.run_id,
            "leaderboard_id": self.leaderboard_id,
            "score": self.score,
            "hits": self.hits,
            "misses": self.misses,
            "enemies_killed": self.enemies_killed,
            "play_time_seconds": self.play_time_seconds,
        }


class SpaceRound:
    def __init__(self, leaderboard_id: str = "default"):
        self.run_id = uuid4()
        self.leaderboard_id = leaderboard_id
        self.player_x = WIDTH / 2
        self.shots: list[Shot] = []
        self.enemies: list[Enemy] = []
        self.elapsed = 0.0
        self.cooldown = 0.0
        self.hits = 0
        self.misses = 0
        self.shots_fired = 0
        self.wave = 0
        self.direction = 1
        self.paused = False
        self.result: RoundResult | None = None
        self.end_reason = ""
        self._next_wave()

    def _next_wave(self) -> None:
        self.wave += 1
        self.direction = 1
        self.enemies = [
            Enemy(130 + column * 65, 50 + row * 46)
            for row in range(3) for column in range(8)
        ]

    def fire(self) -> None:
        if self.paused or self.result is not None or self.cooldown > 0:
            return
        self.shots.append(Shot(self.player_x, PLAYER_Y - 15))
        self.shots_fired += 1
        self.cooldown = 0.24

    def update(self, seconds: float, movement: int = 0, firing: bool = False) -> None:
        if seconds < 0:
            raise ValueError("Elapsed time cannot be negative")
        if self.paused or self.result is not None:
            return
        # Small steps prevent fast projectiles passing through enemies between frames.
        remaining = min(seconds, ROUND_SECONDS - self.elapsed)
        while remaining > 0.000001 and self.result is None:
            dt = min(remaining, 1 / 120)
            self._step(dt, movement, firing)
            remaining -= dt
        if self.result is None and self.elapsed >= ROUND_SECONDS - 0.000001:
            self.elapsed = float(ROUND_SECONDS)
            self.finish("Time is up")

    def _step(self, dt: float, movement: int, firing: bool) -> None:
        self.elapsed += dt
        self.cooldown = max(0.0, self.cooldown - dt)
        self.player_x = min(WIDTH - 25, max(25, self.player_x + movement * 340 * dt))
        if firing:
            self.fire()

        speed = 42 + (self.wave - 1) * 14
        for enemy in self.enemies:
            enemy.x += self.direction * speed * dt
        if any(enemy.x < 22 or enemy.x + ENEMY_WIDTH > WIDTH - 22 for enemy in self.enemies):
            self.direction *= -1
            for enemy in self.enemies:
                enemy.x = min(WIDTH - 22 - ENEMY_WIDTH, max(22, enemy.x))
                enemy.y += 22

        for shot in self.shots[:]:
            shot.y -= 570 * dt
            target = next((
                enemy for enemy in self.enemies
                if enemy.x - 3 <= shot.x <= enemy.x + ENEMY_WIDTH + 3
                and enemy.y - 7 <= shot.y <= enemy.y + ENEMY_HEIGHT
            ), None)
            if target is not None:
                self.enemies.remove(target)
                self.shots.remove(shot)
                self.hits += 1
            elif shot.y < 0:
                self.shots.remove(shot)
                self.misses += 1

        if any(enemy.y + ENEMY_HEIGHT >= PLAYER_Y - 18 for enemy in self.enemies):
            self.finish("The invaders reached your ship")
        elif not self.enemies:
            self._next_wave()

    def finish(self, reason: str) -> RoundResult:
        if self.result is None:
            # Unresolved shots count as misses when a round ends.
            self.misses += len(self.shots)
            self.shots.clear()
            self.end_reason = reason
            self.result = RoundResult(
                self.run_id, self.leaderboard_id, self.hits * 100,
                self.hits, self.misses, self.hits, int(self.elapsed),
            )
        return self.result
