# Viktor Game API

Java 21+ / Spring Boot backend for a Python game, with Supabase Auth and PostgreSQL.
Stores immutable rounds, lifetime statistics, and per-leaderboard high scores.
Passwords go directly from the game to Supabase, never through this API.

## 1. Configure Supabase

1. Create a Supabase project. Enable email/password authentication and **Confirm email**.
   Configure a valid Site URL for the page users see after email confirmation.
   Players can then return to the game and log in with their confirmed email and password.
2. Use an **asymmetric JWT signing key**, preferably ES256, under the project's JWT
   signing-key settings. RS256 also works. Legacy HS256 tokens are intentionally not
   accepted; migrate the project's signing key and log in again if necessary.
3. Copy the project URL and **publishable** API key for the Python client.
   Never ship a secret key, `service_role` key, database password, or JWT private key in the game.
4. Obtain the PostgreSQL connection details from the project's Connect panel.
   Use a direct connection or the **session pooler**, not the transaction pooler.
   For IPv4-only hosting, the session pooler is usually the appropriate choice.
5. Configure a custom SMTP provider before inviting real users. Supabase's default
   mail service is restricted. Enable suitable password requirements and Auth rate limits.

The Java server uses the public JWKS endpoint at
`SUPABASE_URL/auth/v1/.well-known/jwks.json`; no Supabase API secret is needed.
It validates signature, issuer, audience, timestamps, UUID subject, and the
`authenticated` role. Supabase owns account creation, email confirmation,
passwords, sessions, and token renewal.

## 2. Run the Java API

Requirements: JDK 21 or newer, Maven 3.9+, and a PostgreSQL database.
Docker is needed only for integration tests or container deployment.

Set these variables in the server's environment or IntelliJ run configuration:

```text
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
DATABASE_URL=jdbc:postgresql://YOUR_DATABASE_HOST:5432/postgres?sslmode=verify-full
DATABASE_USERNAME=YOUR_SERVER_DATABASE_USER
DATABASE_PASSWORD=YOUR_DATABASE_PASSWORD
PORT=8080
```

`.env.example` lists the settings. Neither Java nor the Python example automatically
loads `.env` files. Keep credentials in the hosting provider's secret manager, not
in source code, shell history, or client builds.

Use the hostname and username from Supabase's Connect panel, including the project
suffix when using the pooler. For `sslmode=verify-full`, install the database's trusted
CA certificate as required by the PostgreSQL JDBC driver (for example through the
`sslrootcert` URL parameter). Do not disable certificate verification in production.

The database user must be allowed to create the `game` schema and must own the
tables created by Flyway. Prefer a dedicated, non-superuser server account with
access only to this database/schema; do not use a client/anonymous database role.
Flyway creates and migrates the schema automatically on startup.
The table owner intentionally bypasses RLS; untrusted clients get no policies.
Do not expose the `game` schema through Supabase's Data API.

```sh
mvn spring-boot:run
```

In IntelliJ, import `pom.xml` as a Maven project, then run
`no.viktor.game.GameApiApplication` with the environment variables above.
The original Java starter file has been replaced by this application.

`GET http://localhost:8080/health` is public and reports process liveness only,
not database or Supabase readiness. Every `/v1` request needs:

```http
Authorization: Bearer <Supabase access token>
```

## 3. Connect the Python game

The reusable example is in `examples/python/game_client.py`.
It supports signup, login, logout, token renewal, submitting rounds, profiles,
statistics, top lists, and nearby players. Sessions are held in memory only:
there is no password/token file and no "remember me" feature.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r examples/python/requirements.txt
```

Set `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and `GAME_API_URL` in the
**client's** environment. The client must not receive the database variables.
Use `http://localhost:8080` only for local development; deployed URLs must use HTTPS.

```sh
.venv/bin/python examples/python/game_client.py signup
# Confirm the email before logging in.
.venv/bin/python examples/python/game_client.py login
```

The CLI asks for email and password without echoing the password, then displays
your own statistics. It does not submit fabricated rounds.

To integrate with the game, import `GameClient` from this example module:

```python
import os
from uuid import uuid4
from game_client import GameClient

client = GameClient(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_PUBLISHABLE_KEY"],
    os.environ["GAME_API_URL"],
)
client.sign_in(email_from_login_screen, password_from_login_screen)

# Create this ID once when the round finishes. Keep the same ID AND payload on retries.
run_id = uuid4()
client.submit_run(
    run_id=run_id,
    score=12500,
    hits=85,
    misses=15,
    enemies_killed=32,
    play_time_seconds=420,
)

stats = client.my_stats()
scores = client.leaderboard()
standing = client.my_standing()
client.update_profile("Viktor", share_stats=True)
client.sign_out()
```

Call the synchronous client from a worker, not the game's render loop, and serialize
calls using the same client/session. Present authentication and HTTP errors in the
game UI; do not treat failed submissions as successful. A network timeout can occur
after a round was saved: retry its exact payload and ID. Tokens are refreshed once
on HTTP 401; other failures propagate to the caller. The example does not persist
unsent rounds or integrate with a particular game's event loop.

If adding "remember me", store the refresh token in the OS credential store (for
example `keyring`), never a plaintext file. Password recovery requires an appropriate
Supabase recovery redirect/UI and is not included in this minimal game client.
Logout revokes this session's refresh token; already-issued access tokens can remain
valid until expiry, so use appropriately short access-token lifetimes.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/runs` | Save a completed round; 201 for new, 200 for an identical retry |
| GET | `/v1/me/stats` | Your lifetime totals, best score, and accuracy |
| GET | `/v1/me/profile` | Your display name and statistics-sharing setting |
| PATCH | `/v1/me/profile` | Set both `displayName` and `shareStats` |
| GET | `/v1/players/{uuid}/stats` | Another player's stats, only if they opted in |
| GET | `/v1/leaderboards` | Available boards and their ruleset metadata |
| GET | `/v1/leaderboards/{id}` | Top players; `limit=20` (1-100), `offset=0` (0-10000) |
| GET | `/v1/leaderboards/{id}/me` | Your rank and up to two players on each side |

Round body (all fields required):

```json
{
  "runId": "c1b65cbb-42cb-4b9e-88ba-cbcf53bd7860",
  "leaderboardId": "default",
  "score": 12500,
  "hits": 85,
  "misses": 15,
  "enemiesKilled": 32,
  "playTimeSeconds": 420
}
```

- The verified token determines the player. Sending a `playerId` or any other
  unknown field is rejected, not trusted.
- All counters and scores must be nonnegative integers. Counters fit signed
  32-bit integers; score fits a signed 64-bit integer. Totals use 64-bit values.
- `hits` counts **shots that hit**, not individual enemies hit by one shot.
  `misses` counts shots that hit nothing. Accuracy is
  `totalHits / (totalHits + totalMisses) * 100`, rounded to two decimal places,
  or `null` when no shots have been fired.
- `playTimeSeconds` is active, completed-round playtime excluding pauses.
  The game must measure this. Unsubmitted/crashed/in-progress rounds are not counted.
- Stats include `runsPlayed`, `bestScore`, `hits`, `misses`, `enemiesKilled`,
  `playTimeSeconds`, and `accuracyPercent`. They cover all the player's boards;
  comparable competitive scores belong to individual boards.
- A run UUID is globally unique. An identical retry is safe, including concurrent
  retries. Reusing the ID with different data or another account returns **409**.
  Accepted runs are immutable.
- Stats are private by default. Display name, player UUID, best leaderboard score,
  and rank are visible to other logged-in players regardless of `shareStats`.
  Emails and authentication data are never returned by this API.
- Each board ranks each player's best score. Equal scores share a rank (`1, 1, 3`);
  UUID order makes pagination deterministic for ties. Pages are live, not snapshots.
  A player with no submitted score gets `player: null` and an empty `neighbors` list.
- Invalid input returns **400**, missing/invalid authentication **401**, and missing
  boards or unavailable/private player stats **404**. API validation/business errors
  use Spring's problem-detail responses.

The initial board is `default` (version `1`, standard mode, normal difficulty,
all-time). Add versioned migrations for additional modes, difficulties, versions,
or seasons; the client cannot create boards or alter their metadata.
Setting `accepting_runs = false` closes a board to new rounds but allows identical
retries of already accepted rounds.

## Run automated tests

With Docker running:

```sh
mvn test
.venv/bin/python -m unittest discover -s examples/python -p 'test_*.py'
```

Java integration tests start a disposable real PostgreSQL container and a local
JWKS endpoint. They use signed RSA/EC tokens, not bypassed authentication, and
exercise migrations, input validation, concurrency, privacy, ranking, and totals.
No live Supabase account or cloud credentials are required for these tests.

## Deploy

```sh
mvn -DskipTests package
java -jar target/game-api-0.0.1-SNAPSHOT.jar
```

Or build the non-root container image:

```sh
docker build -t viktor-game-api .
```

Supply the server environment variables through your cloud service's secret
configuration. Expose port `8080` (or `PORT`) behind an HTTPS load balancer.
Keep the database private where supported and use verified TLS connections.
The Docker build context excludes environment files and other local files.

Before exposing this to real players, configure gateway request-size limits
(for example 16 KiB for these small JSON requests), per-user/IP request limits,
and Supabase Auth abuse protection. Apply limits consistently across server replicas.
Add monitoring and PostgreSQL backups, and define account/data deletion and
retention procedures appropriate for your players.

**This is not an anti-cheat system.** The server validates types, nonnegative
values, identity, board selection, and duplicate submissions, but cannot prove
that a client-reported score or playtime is genuine. A modified client can invent
new run IDs and results. Competitive/prize-bearing play needs game-specific
validation, replay verification, or server-authoritative game simulation before
scores should be considered trusted.
