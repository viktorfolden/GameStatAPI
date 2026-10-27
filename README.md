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

### Encrypted database password for local development

The local Java server can connect to Supabase using a password encrypted on disk.
The master passphrase is entered at a hidden terminal prompt and is never saved.
Render continues to use `DATABASE_PASSWORD` as before; no changes there are needed.
This feature belongs to the backend only. Never distribute database credentials
or this encrypted file with the Python game.

Build the application and create a private local directory:

```sh
mvn -DskipTests package
mkdir -p .local-secrets
chmod 700 .local-secrets
java -jar target/game-stat-api-0.0.1-SNAPSHOT.jar \
  --encrypt-local-password .local-secrets/supabase-password.enc
```

Enter and confirm a strong, unique master passphrase (at least 16 characters),
then enter the Supabase database password. Creation does not contact Supabase
or start the server, and refuses to overwrite an existing file.
The file uses AES-256-GCM authenticated encryption and PBKDF2-HMAC-SHA256 with
600,000 iterations and a random salt. Each encryption also uses a fresh nonce.
On macOS/Linux the file is created with owner-only permissions (`600`).
On other systems, restrict access using the OS file-permission controls.
`.local-secrets/` is excluded from Git, and the Docker build excludes local files.
Do not commit the encrypted file or store its master passphrase beside it.

Set the usual `SUPABASE_URL`, `DATABASE_URL`, and `DATABASE_USERNAME` environment
variables, including verified TLS/CA configuration described above, then start:

```sh
unset DATABASE_PASSWORD
java -jar target/game-stat-api-0.0.1-SNAPSHOT.jar \
  --local-password-file .local-secrets/supabase-password.enc
```

Enter the master passphrase when prompted. A wrong passphrase, corrupt file,
missing file, or non-interactive terminal stops startup instead of falling back.
Run these commands in a real terminal, including IntelliJ's Terminal tab;
the standard IDE Run console and `mvn spring-boot:run` may not provide the
interactive Java console this mode requires.

The decrypted value supplies the default `DATABASE_PASSWORD` property.
Existing environment variables, system properties, or explicit datasource
configuration take precedence; unset password overrides to use this file.
The password necessarily exists in the Java process's memory while JDBC uses it.
This protects storage at rest, not an already-compromised machine or memory dumps.
The master passphrase cannot be recovered; if lost, reset/retrieve the database
credential through your administrator and create a new encrypted file.

## 3. Connect the Python game

To run the example against our Render/Supabase deployment from macOS or Linux:

```sh
./examples/python/run_example.sh signup
./examples/python/run_example.sh login
```

The launcher creates `.venv` if needed, installs the declared dependencies, and
asks for email/password interactively. Confirm your email before logging in.
With no argument it defaults to `login`. It can be invoked from any working
directory. Python 3 with `venv` and pip support is required.

The launcher defaults to `https://viktor-game-api.onrender.com` and the project's
Supabase HTTPS URL and public publishable key. These are client configuration,
not database credentials. Override them using environment variables when needed:

```sh
GAME_API_URL=http://localhost:8080 ./examples/python/run_example.sh login
```

`SUPABASE_URL` must be the project's **HTTPS API URL**, never a JDBC/PostgreSQL
connection string. No database password is needed by the Python client.

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
java -jar target/game-stat-api-0.0.1-SNAPSHOT.jar
```

Or build the non-root container image:

```sh
docker build -t viktor-game-api .
```

Supply the server environment variables through your cloud service's secret
configuration. Expose port `8080` (or `PORT`) behind an HTTPS load balancer.
Keep the database private where supported and use verified TLS connections.
The Docker build context excludes environment files and other local files.

### Render Free with GitHub Actions

The workflow in `.github/workflows/render-deploy.yml` runs Java integration tests,
Python client tests, and a Docker build for pull requests to `master` and pushes to
`master`. Only a successful run on `master` requests a Render deployment. You can also
run it manually from GitHub Actions; deployment is still restricted to `master`.
GitHub-hosted Ubuntu runners provide Docker for the PostgreSQL integration tests.

Initial setup:

1. Push this project to a GitHub repository with a `master` branch.
2. In Render, create a **Blueprint** connected to that repository and use the
   included `render.yaml`. It creates one **Free** Docker web service in Frankfurt,
   with `/health` as its health-check path. It does not create a paid database.
3. Enter `SUPABASE_URL`, `DATABASE_URL`, `DATABASE_USERNAME`, and
   `DATABASE_PASSWORD` in Render when prompted. Use the Supabase session pooler
   if required for IPv4, and configure verified database TLS as described above.
   Render's first deployment starts during service creation; the GitHub workflow
   controls subsequent deployments.
4. Leave Render **Auto-Deploy disabled** (`autoDeployTrigger: "off"` in the
   Blueprint), so Render does not deploy untested commits independently of Actions.
5. Copy the service's **Deploy Hook URL** from Render's Settings. In GitHub, open
   **Settings > Secrets and variables > Actions** and add a repository secret named
   `RENDER_DEPLOY_HOOK_URL`. Treat the entire URL as a password; never commit it.
6. Push a commit to `master`, or run **Test and deploy to Render** manually on `master`.
   Set the Python client's `GAME_API_URL` to the service's HTTPS `onrender.com` URL.

The hook includes the tested commit SHA, not just "latest master". Database credentials
stay in Render; Actions only needs the deploy hook. Protect `master` with required
reviews and the **Test and build** status check before merging.

A green deploy job means **Render accepted the request**, not that the new version
is live. Check Render's deployment logs and health status for rollout success.
The workflow does not retry the deploy hook automatically, avoiding duplicate deploys
after ambiguous network failures. If a request fails, check Render before rerunning.

The Blueprint limits JVM heap to 60% of the container's RAM, leaving room for
non-heap memory; total Java memory consumption is not capped by this setting.
Monitor memory usage on the small free instance.

Render Free sleeps after 15 idle minutes and can take about a minute to wake.
The example client's 15-second read timeout can expire during wake-up. The game
should display a connection state and allow retrying the same round ID and payload.
Free service/build/bandwidth quotas and GitHub Actions allowances still apply;
private repositories may have metered Actions usage beyond their included minutes.
Keep paid upgrades and extra usage billing disabled if zero cost is a requirement.

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
