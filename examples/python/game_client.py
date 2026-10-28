"""Example integration for a Python game. Sessions stay in memory only."""

import argparse
from getpass import getpass
import json
import os
from urllib.parse import urlparse
from uuid import UUID

import requests
from supabase import ClientOptions, create_client


class LoginRequiredError(Exception):
    pass


class GameClient:
    def __init__(self, supabase_url: str, publishable_key: str, api_url: str):
        self._validate_url(supabase_url, allow_local_http=False)
        self._validate_url(api_url, allow_local_http=True)
        self._supabase = create_client(
            supabase_url,
            publishable_key,
            options=ClientOptions(persist_session=False, auto_refresh_token=False),
        )
        self._api_url = api_url.rstrip("/")
        self._http = requests.Session()

    @staticmethod
    def _validate_url(url: str, *, allow_local_http: bool) -> None:
        parsed = urlparse(url)
        local_http = (
            allow_local_http
            and parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "https" and not local_http)
        ):
            raise ValueError("Use an HTTPS URL (HTTP is allowed only for a local game API)")

    def sign_up(self, email: str, password: str) -> None:
        self._supabase.auth.sign_up({"email": email, "password": password})

    def sign_in(self, email: str, password: str) -> None:
        response = self._supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        if response.session is None:
            raise LoginRequiredError("Sign-in did not create a session")

    def sign_out(self) -> None:
        self._supabase.auth.sign_out({"scope": "local"})

    def _request(self, method: str, path: str, *, payload=None, params=None):
        # get_session refreshes an expired session even with background refresh disabled.
        session = self._supabase.auth.get_session()
        if session is None:
            raise LoginRequiredError("Sign in before calling the game API")

        def send(access_token: str):
            return self._http.request(
                method,
                self._api_url + path,
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
                params=params,
                timeout=(5, 15),
                allow_redirects=False,
            )

        response = send(session.access_token)
        if response.status_code == 401:
            refreshed = self._supabase.auth.refresh_session()
            if refreshed.session is None:
                raise LoginRequiredError("Your session expired; sign in again")
            response = send(refreshed.session.access_token)
        if 300 <= response.status_code < 400:
            raise requests.HTTPError("Unexpected API redirect", response=response)
        response.raise_for_status()
        return response.json()

    def submit_run(
        self,
        *,
        run_id: UUID,
        score: int,
        hits: int,
        misses: int,
        enemies_killed: int,
        play_time_seconds: int,
        leaderboard_id: str = "default",
    ):
        return self._request(
            "POST",
            "/v1/runs",
            payload={
                "runId": str(run_id),
                "leaderboardId": leaderboard_id,
                "score": score,
                "hits": hits,
                "misses": misses,
                "enemiesKilled": enemies_killed,
                "playTimeSeconds": play_time_seconds,
            },
        )

    def my_stats(self):
        return self._request("GET", "/v1/me/stats")

    def round_summary(self, run_id: UUID):
        return self._request("GET", f"/v1/runs/{run_id}/summary")

    def player_stats(self, player_id: UUID):
        return self._request("GET", f"/v1/players/{player_id}/stats")

    def my_profile(self):
        return self._request("GET", "/v1/me/profile")

    def update_profile(self, display_name: str, *, share_stats: bool):
        return self._request(
            "PATCH",
            "/v1/me/profile",
            payload={"displayName": display_name, "shareStats": share_stats},
        )

    def leaderboards(self):
        return self._request("GET", "/v1/leaderboards")

    def leaderboard(self, leaderboard_id: str = "default", *, limit: int = 20, offset: int = 0):
        return self._request(
            "GET",
            f"/v1/leaderboards/{leaderboard_id}",
            params={"limit": limit, "offset": offset},
        )

    def my_standing(self, leaderboard_id: str = "default"):
        return self._request("GET", f"/v1/leaderboards/{leaderboard_id}/me")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an account, show statistics, or submit a round")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("signup")
    actions.add_parser("login")
    submit = actions.add_parser("submit", help="Sign in and submit one round")
    submit.add_argument("--run-id", type=UUID, required=True,
                        help="Unique round UUID; reuse with the same data when retrying")
    submit.add_argument("--leaderboard-id", default="default")
    for flag in ["score", "hits", "misses", "enemies-killed", "play-time-seconds"]:
        submit.add_argument(f"--{flag}", type=int, required=True)
    args = parser.parse_args()
    if args.action == "submit":
        for field in ["score", "hits", "misses", "enemies_killed", "play_time_seconds"]:
            value = getattr(args, field)
            maximum = 2**63 - 1 if field == "score" else 2**31 - 1
            if not 0 <= value <= maximum:
                parser.error(f"--{field.replace('_', '-')} must be between 0 and {maximum}")
    client = GameClient(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_PUBLISHABLE_KEY"],
        os.environ["GAME_API_URL"],
    )
    email = input("Email: ").strip()
    password = getpass("Password: ")
    if args.action == "signup":
        client.sign_up(email, password)
        print("Check your email to confirm your account, then run the login command.")
    else:
        client.sign_in(email, password)
        del password
        if args.action == "submit":
            print(f"Submitting round {args.run_id}. Retry with the same ID and data if the request fails.",
                  flush=True)
            saved = client.submit_run(
                run_id=args.run_id,
                leaderboard_id=args.leaderboard_id,
                score=args.score,
                hits=args.hits,
                misses=args.misses,
                enemies_killed=args.enemies_killed,
                play_time_seconds=args.play_time_seconds,
            )
            print("Saved round:")
            print(json.dumps(saved, indent=2))
        print("Player statistics:")
        print(json.dumps(client.my_stats(), indent=2))
        client.sign_out()


if __name__ == "__main__":
    main()
