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
    parser = argparse.ArgumentParser(description="Sign up or sign in and show your game statistics")
    parser.add_argument("action", choices=["signup", "login"])
    args = parser.parse_args()
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
        print(json.dumps(client.my_stats(), indent=2))
        client.sign_out()


if __name__ == "__main__":
    main()
