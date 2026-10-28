"""Original arcade demo of the game API. Launch with run_example.sh game."""

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from getpass import getpass
import math
import os
import sys
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import httpx
import pygame
import requests
from supabase_auth.errors import AuthError

from game_client import GameClient, LoginRequiredError
from round_summary import summary_lines
from space_round import (
    ENEMY_HEIGHT, ENEMY_WIDTH, HEIGHT, PLAYER_Y, ROUND_SECONDS, WIDTH,
    RoundResult, SpaceRound,
)


BACKGROUND = (10, 15, 30)
WHITE = (230, 238, 255)
CYAN = (90, 225, 235)
GREEN = (120, 245, 160)
YELLOW = (255, 213, 110)
RED = (255, 125, 135)
MUTED = (150, 165, 190)
API_ERRORS = (requests.RequestException, httpx.HTTPError, AuthError, LoginRequiredError)


class DemoApi:
    """All network calls run serially off the drawing thread."""

    def __init__(self, client: GameClient, leaderboard_id: str):
        self.client = client
        self.leaderboard_id = leaderboard_id
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="game-api")
        self.future: Future | None = None
        self.operation = ""
        self.pending: RoundResult | None = None
        self.stats: dict | None = None
        self.entries: list[dict] = []
        self.rank: int | None = None
        self.saved_id = None
        self.summary: dict | None = None
        self.status = "Ready"
        self.error = False

    @property
    def busy(self) -> bool:
        return self.future is not None

    def refresh(self) -> None:
        if self.busy:
            raise RuntimeError("Wait for the current API request")
        self.operation = "refresh"
        self.status = "Loading stats and leaderboard (Render may need to wake up)..."
        self.error = False
        self.future = self.executor.submit(self._load_stats)

    def _load_stats(self):
        return (
            self.client.my_stats(),
            self.client.leaderboard(self.leaderboard_id, limit=7),
            self.client.my_standing(self.leaderboard_id),
            self.client.round_summary(self.saved_id) if self.saved_id is not None else None,
        )

    def submit(self, result: RoundResult) -> None:
        if self.busy:
            raise RuntimeError("Wait for the current API request")
        if self.pending is not None and self.pending != result:
            raise RuntimeError("Retry or explicitly discard the unsaved round first")
        self.pending = result
        self.operation = "submit"
        self.status = "Saving round... Do not close the game."
        self.error = False
        self.future = self.executor.submit(self.client.submit_run, **result.api_arguments())

    def poll(self) -> None:
        if self.future is None or not self.future.done():
            return
        future, operation = self.future, self.operation
        self.future = None
        try:
            value = future.result()
        except API_ERRORS as error:
            self.error = True
            if isinstance(error, requests.HTTPError) and error.response is not None:
                detail = f"HTTP {error.response.status_code}"
            else:
                detail = type(error).__name__
            if operation == "submit":
                self.status = f"Save not confirmed ({detail}). Press R to retry the SAME round."
            else:
                self.status = f"Stats unavailable ({detail}). Press R to refresh."
            return
        if operation == "submit":
            self.saved_id = self.pending.run_id
            self.summary = None
            self.pending = None
            self.refresh()
        else:
            self.stats, board, standing, self.summary = value
            self.entries = board["entries"]
            player = standing["player"]
            self.rank = player["rank"] if player is not None else None
            self.status = "Round saved; statistics updated." if self.saved_id else "Statistics updated."
            self.error = False

    def discard(self) -> None:
        if self.busy:
            raise RuntimeError("Cannot discard while a request is running")
        self.pending = None
        self.status = "Local retry discarded. A timed-out request may still have been saved."

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=True)


class SpaceDemo:
    def __init__(self, api: DemoApi):
        self.api = api
        self.screen = pygame.display.set_mode((1160, 710))
        pygame.display.set_caption("Orbit Defenders - Game API Demo")
        self.font = pygame.font.Font(None, 25)
        self.small = pygame.font.Font(None, 21)
        self.large = pygame.font.Font(None, 42)
        self.round: SpaceRound | None = None
        self.quit_confirm = False
        self.running = True
        self.last_tick = time.monotonic()
        self.notice = ""

    def text(self, value, x, y, color=WHITE, font=None):
        self.screen.blit((font or self.font).render(str(value), True, color), (x, y))

    def start_round(self):
        if self.api.busy or self.api.pending is not None:
            self.notice = "Wait for the API, or retry/discard the unsaved round first."
            return
        self.round = SpaceRound(self.api.leaderboard_id)
        self.quit_confirm = False
        self.notice = ""
        self.last_tick = time.monotonic()

    def finish_round(self, reason):
        if self.round is not None and self.round.result is None:
            result = self.round.finish(reason)
            self.api.submit(result)

    def request_quit(self):
        if self.api.busy:
            self.notice = "API request in progress. Wait for it to finish before closing."
            return
        if self.api.pending is not None or (self.round and self.round.result is None):
            self.quit_confirm = True
            if self.round:
                self.round.paused = True
            self.notice = "Unsaved progress! Y: exit without retry/saving. N: stay (paused)."
        else:
            self.running = False

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.request_quit()
        elif event.type == pygame.WINDOWFOCUSLOST:
            if self.round and self.round.result is None:
                self.round.paused = True
        elif event.type == pygame.KEYDOWN:
            if self.quit_confirm:
                if event.key == pygame.K_y:
                    self.running = False
                elif event.key == pygame.K_n:
                    self.quit_confirm = False
                    self.notice = ""
                return
            active = self.round is not None and self.round.result is None
            if event.key == pygame.K_q:
                self.request_quit()
            elif event.key == pygame.K_RETURN and not active:
                self.start_round()
            elif event.key == pygame.K_p and active:
                self.round.paused = not self.round.paused
            elif event.key == pygame.K_ESCAPE and active:
                self.finish_round("Round ended by player")
            elif event.key == pygame.K_r and not active and not self.api.busy:
                if self.api.pending:
                    self.api.submit(self.api.pending)
                else:
                    self.api.refresh()
            elif event.key == pygame.K_d and not active and not self.api.busy and self.api.pending:
                self.api.discard()
                self.notice = "Retry discarded. Press ENTER for a new round."

    def tick(self):
        now = time.monotonic()
        elapsed = now - self.last_tick
        self.last_tick = now
        self.api.poll()
        if self.round and self.round.result is None:
            # Treat a long OS stall as a pause, not an unfair leap in the simulation.
            if elapsed > 0.25:
                self.round.paused = True
            keys = pygame.key.get_pressed()
            direction = int(keys[pygame.K_RIGHT] or keys[pygame.K_d]) - int(
                keys[pygame.K_LEFT] or keys[pygame.K_a])
            self.round.update(min(elapsed, 0.25), direction, bool(keys[pygame.K_SPACE]))
            if self.round.result is not None:
                self.api.submit(self.round.result)

    def draw(self):
        self.screen.fill(BACKGROUND)
        self.text("ORBIT DEFENDERS", 24, 16, CYAN, self.large)
        self.text("A small arcade game demonstrating Supabase + the Java API", 25, 55, MUTED)
        field = pygame.Rect(15, 90, WIDTH, HEIGHT)
        pygame.draw.rect(self.screen, (16, 24, 43), field, border_radius=8)
        for i in range(55):
            pygame.draw.circle(self.screen, (65, 82, 110),
                               (25 + (i * 137) % 775, 102 + (i * 89) % 530), 1)
        if self.round:
            for enemy in self.round.enemies:
                x, y = int(enemy.x) + 15, int(enemy.y) + 90
                pygame.draw.rect(self.screen, GREEN, (x, y + 5, ENEMY_WIDTH, ENEMY_HEIGHT - 5))
                pygame.draw.rect(self.screen, GREEN, (x + 5, y, ENEMY_WIDTH - 10, 8))
                for eye in (8, 23):
                    pygame.draw.rect(self.screen, BACKGROUND, (x + eye, y + 9, 4, 5))
            for shot in self.round.shots:
                pygame.draw.rect(self.screen, YELLOW, (int(shot.x) + 12, int(shot.y) + 90, 6, 12))
            x, y = int(self.round.player_x) + 15, PLAYER_Y + 90
            pygame.draw.polygon(self.screen, CYAN, [(x, y - 18), (x - 20, y + 12), (x + 20, y + 12)])
            self.text(f"Score {self.round.hits * 100}   Hits {self.round.hits}   "
                      f"Misses {self.round.misses}   Wave {self.round.wave}", 30, 103)
            self.text(f"{max(0, math.ceil(ROUND_SECONDS - self.round.elapsed))}s", 745, 103, YELLOW)
        if self.round is None:
            self.text("Press ENTER to start", 220, 280, WHITE, self.large)
            self.text("Clear the invaders before they reach your ship.", 190, 335)
            self.text("60 seconds per round. Each hit earns 100 points.", 185, 365)
        elif self.round.result:
            self.draw_round_summary()
        elif self.round.paused:
            self.text("PAUSED - P to resume", 220, 325, YELLOW, self.large)
        self.draw_sidebar()
        self.text("Move: arrows / A D    Shoot: SPACE    Pause: P    End round: ESC    Quit: Q",
                  24, 660, MUTED, self.small)
        self.text(self.notice or self.api.status, 24, 686,
                  RED if self.notice or self.api.error else GREEN, self.small)
        pygame.display.flip()

    def draw_round_summary(self):
        pygame.draw.rect(self.screen, BACKGROUND, (35, 185, 760, 455), border_radius=10)
        self.text(self.round.end_reason, 55, 202, YELLOW)
        result = self.round.result
        shots = result.hits + result.misses
        accuracy = f"{100 * result.hits / shots:.1f}%" if shots else "-"
        self.text(f"Score: {result.score}   Kills: {result.enemies_killed}   Accuracy: {accuracy}", 55, 240)
        self.text(f"Hits: {result.hits}   Misses: {result.misses}   Active time: {result.play_time_seconds}s",
                  55, 268)
        saved = self.api.saved_id == result.run_id
        self.text("Saved to API" if saved else "Not yet confirmed by API", 55, 300, GREEN if saved else YELLOW)
        if saved and self.api.summary is not None:
            lines = summary_lines(result, self.api.summary)
        elif saved:
            lines = ["Loading round comparison..." if self.api.busy
                     else "Comparison unavailable. Press R to retry (the round is saved)."]
        else:
            lines = ["The comparison will appear once this round is saved."]
        y = 340
        for line in lines:
            words = line.split()
            wrapped = ""
            for word in words:
                candidate = f"{wrapped} {word}".strip()
                if wrapped and self.small.size(candidate)[0] > 715:
                    self.text(wrapped, 55, y, WHITE, self.small)
                    y += 24
                    wrapped = word
                else:
                    wrapped = candidate
            self.text(wrapped, 55, y, WHITE, self.small)
            y += 27
        self.text("ENTER: next round   R: retry/refresh   D: discard retry", 55, 610, MUTED, self.small)

    def draw_sidebar(self):
        x = 840
        self.text("YOUR API STATISTICS", x, 100, CYAN)
        stats = self.api.stats
        if stats is not None:
            accuracy = stats["accuracyPercent"]
            rows = [
                f"Rounds: {stats['runsPlayed']}",
                f"Best score: {stats['bestScore']}",
                f"Hits / misses: {stats['hits']} / {stats['misses']}",
                f"Enemies killed: {stats['enemiesKilled']}",
                f"Active time: {stats['playTimeSeconds']}s",
                f"Accuracy: {accuracy}%" if accuracy is not None else "Accuracy: -",
                f"Board rank: {self.api.rank or '-'}",
            ]
            for index, row in enumerate(rows):
                self.text(row, x, 140 + index * 27)
        else:
            self.text("Not loaded yet - R to retry", x, 145, MUTED)
        self.text("LEADERBOARD", x, 365, CYAN)
        self.text(self.api.leaderboard_id[:32], x, 395, MUTED, self.small)
        player_id = stats["playerId"] if stats else None
        for index, entry in enumerate(self.api.entries):
            name = entry["displayName"][:16]
            row = f"{entry['rank']}. {name}  {entry['score']}"
            self.text(row, x, 427 + index * 27,
                      GREEN if entry["playerId"] == player_id else WHITE, self.small)
        self.text("R: refresh when not playing", x, 635, MUTED, self.small)

    def run(self):
        clock = pygame.time.Clock()
        self.api.refresh()
        while self.running:
            for event in pygame.event.get():
                self.handle_event(event)
            if not self.running:
                break
            self.tick()
            self.draw()
            clock.tick(60)


def main():
    parser = argparse.ArgumentParser(description="Orbit Defenders: play and submit API statistics")
    parser.add_argument("--leaderboard-id", default=os.environ.get("GAME_LEADERBOARD_ID", "default"))
    args = parser.parse_args()
    client = GameClient(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_PUBLISHABLE_KEY"],
        os.environ["GAME_API_URL"],
    )
    print("Orbit Defenders - sign in to play. No database credentials are needed.")
    action = input("[L]ogin or [S]ign up? ").strip().lower()
    if action not in {"l", "login", "s", "signup"}:
        parser.error("Choose L for login or S to create an account")
    email = input("Email: ").strip()
    password = getpass("Password: ")
    try:
        if action in {"s", "signup"}:
            client.sign_up(email, password)
            print("Check your email to confirm the account, then launch the game again and choose L.")
            return
        client.sign_in(email, password)
    except API_ERRORS as error:
        print(f"Authentication failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    finally:
        del password

    pygame.init()
    api = DemoApi(client, args.leaderboard_id)
    try:
        SpaceDemo(api).run()
    finally:
        api.close()
        pygame.quit()
        try:
            client.sign_out()
        except API_ERRORS as error:
            print(f"Logout could not be confirmed: {type(error).__name__}", file=sys.stderr)


if __name__ == "__main__":
    main()
