CREATE TABLE game.players (
    id UUID PRIMARY KEY,
    display_name VARCHAR(32) NOT NULL DEFAULT 'Player',
    share_stats BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE game.leaderboards (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    game_version VARCHAR(40) NOT NULL,
    game_mode VARCHAR(40) NOT NULL,
    difficulty VARCHAR(40) NOT NULL,
    season VARCHAR(40) NOT NULL,
    accepting_runs BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE game.runs (
    id UUID PRIMARY KEY,
    player_id UUID NOT NULL REFERENCES game.players(id),
    leaderboard_id VARCHAR(64) NOT NULL REFERENCES game.leaderboards(id),
    score BIGINT NOT NULL CHECK (score >= 0),
    hits INTEGER NOT NULL CHECK (hits >= 0),
    misses INTEGER NOT NULL CHECK (misses >= 0),
    enemies_killed INTEGER NOT NULL CHECK (enemies_killed >= 0),
    play_time_seconds INTEGER NOT NULL CHECK (play_time_seconds >= 0),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX runs_player_idx ON game.runs (player_id);
CREATE INDEX runs_leaderboard_player_score_idx
    ON game.runs (leaderboard_id, player_id, score DESC);

INSERT INTO game.leaderboards (id, name, game_version, game_mode, difficulty, season)
VALUES ('default', 'All-time scores', '1', 'standard', 'normal', 'all-time');

-- Only the server-side database owner accesses these tables. Clients get no RLS policies.
ALTER TABLE game.players ENABLE ROW LEVEL SECURITY;
ALTER TABLE game.leaderboards ENABLE ROW LEVEL SECURITY;
ALTER TABLE game.runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON SCHEMA game FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA game FROM PUBLIC;
