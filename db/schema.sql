-- nba-viz schema (Postgres). Run once: psql $DATABASE_URL -f db/schema.sql
-- Sized to fit a free tier (~0.5 GB): 5 seasons of logs + shot detail, no play-by-play.

CREATE TABLE IF NOT EXISTS players (
    player_id   INTEGER PRIMARY KEY,
    full_name   TEXT NOT NULL,
    first_name  TEXT,
    last_name   TEXT,
    is_active   BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS teams (
    team_id      INTEGER PRIMARY KEY,
    abbreviation TEXT NOT NULL,
    nickname     TEXT,
    city         TEXT,
    full_name    TEXT
);

CREATE TABLE IF NOT EXISTS team_game_logs (
    team_id      INTEGER NOT NULL,
    game_id      TEXT    NOT NULL,
    season       TEXT    NOT NULL,            -- '2024-25'
    season_type  TEXT    NOT NULL DEFAULT 'Regular Season',
    game_date    DATE    NOT NULL,
    matchup      TEXT,                        -- 'GSW vs. LAL' / 'GSW @ LAL'
    wl           TEXT,
    min          NUMERIC,
    fgm INTEGER, fga INTEGER, fg_pct NUMERIC,
    fg3m INTEGER, fg3a INTEGER, fg3_pct NUMERIC,
    ftm INTEGER, fta INTEGER, ft_pct NUMERIC,
    oreb INTEGER, dreb INTEGER, reb INTEGER,
    ast INTEGER, stl INTEGER, blk INTEGER, tov NUMERIC, pf INTEGER,
    pts INTEGER, plus_minus NUMERIC,
    PRIMARY KEY (team_id, game_id)
);
CREATE INDEX IF NOT EXISTS idx_tgl_season ON team_game_logs (season, season_type);
CREATE INDEX IF NOT EXISTS idx_tgl_date   ON team_game_logs (game_date);

CREATE TABLE IF NOT EXISTS player_game_logs (
    player_id    INTEGER NOT NULL,
    game_id      TEXT    NOT NULL,
    player_name  TEXT,
    team_id      INTEGER,
    team_abbreviation TEXT,
    season       TEXT    NOT NULL,
    season_type  TEXT    NOT NULL DEFAULT 'Regular Season',
    game_date    DATE    NOT NULL,
    matchup      TEXT,
    wl           TEXT,
    min          NUMERIC,
    fgm INTEGER, fga INTEGER, fg_pct NUMERIC,
    fg3m INTEGER, fg3a INTEGER, fg3_pct NUMERIC,
    ftm INTEGER, fta INTEGER, ft_pct NUMERIC,
    oreb INTEGER, dreb INTEGER, reb INTEGER,
    ast INTEGER, stl INTEGER, blk INTEGER, tov NUMERIC, pf INTEGER,
    pts INTEGER, plus_minus NUMERIC,
    PRIMARY KEY (player_id, game_id)
);
CREATE INDEX IF NOT EXISTS idx_pgl_season ON player_game_logs (season, season_type);
CREATE INDEX IF NOT EXISTS idx_pgl_player ON player_game_logs (player_id, season);
CREATE INDEX IF NOT EXISTS idx_pgl_date   ON player_game_logs (game_date);

-- Shot-level detail (x/y coordinates). ~220k rows per season.
CREATE TABLE IF NOT EXISTS shots (
    game_id         TEXT    NOT NULL,
    game_event_id   INTEGER NOT NULL,
    player_id       INTEGER NOT NULL,
    player_name     TEXT,
    team_id         INTEGER,
    season          TEXT    NOT NULL,
    season_type     TEXT    NOT NULL DEFAULT 'Regular Season',
    game_date       DATE,
    period          INTEGER,
    minutes_remaining INTEGER,
    seconds_remaining INTEGER,
    event_type      TEXT,            -- 'Made Shot' / 'Missed Shot'
    action_type     TEXT,            -- 'Jump Shot', 'Driving Layup Shot', ...
    shot_type       TEXT,            -- '2PT Field Goal' / '3PT Field Goal'
    shot_zone_basic TEXT,
    shot_zone_area  TEXT,
    shot_zone_range TEXT,
    shot_distance   INTEGER,
    loc_x           INTEGER,         -- tenths of feet, -250..250 (court width)
    loc_y           INTEGER,         -- tenths of feet, hoop at y=0
    shot_made_flag  INTEGER,
    PRIMARY KEY (game_id, game_event_id)
);
CREATE INDEX IF NOT EXISTS idx_shots_player ON shots (player_id, season);
CREATE INDEX IF NOT EXISTS idx_shots_team   ON shots (team_id, season);

-- Aggregate tracking: shooting splits by closest-defender distance bucket.
-- This is the public proxy for "conditioning on defenders" — raw positional
-- tracking data is not publicly available.
CREATE TABLE IF NOT EXISTS defender_shooting (
    season         TEXT    NOT NULL,
    player_id      INTEGER NOT NULL,
    player_name    TEXT,
    def_dist_range TEXT    NOT NULL,  -- '0-2 Feet - Very Tight', etc.
    gp  INTEGER,
    fga_frequency NUMERIC,
    fgm NUMERIC, fga NUMERIC, fg_pct NUMERIC, efg_pct NUMERIC,
    fg2m NUMERIC, fg2a NUMERIC, fg2_pct NUMERIC,
    fg3m NUMERIC, fg3a NUMERIC, fg3_pct NUMERIC,
    PRIMARY KEY (season, player_id, def_dist_range)
);

CREATE TABLE IF NOT EXISTS standings (
    season        TEXT    NOT NULL,
    team_id       INTEGER NOT NULL,
    team_city     TEXT,
    team_name     TEXT,
    conference    TEXT,
    playoff_rank  INTEGER,
    wins          INTEGER,
    losses        INTEGER,
    win_pct       NUMERIC,
    updated_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (season, team_id)
);

-- Convenience view: per-player season averages (regular season).
CREATE OR REPLACE VIEW player_season_averages AS
SELECT
    player_id,
    max(player_name) AS player_name,
    season,
    count(*)         AS gp,
    avg(min)         AS min,
    avg(pts)         AS pts,
    avg(reb)         AS reb,
    avg(ast)         AS ast,
    avg(stl)         AS stl,
    avg(blk)         AS blk,
    avg(tov)         AS tov,
    avg(fg3m)        AS fg3m,
    avg(plus_minus)  AS plus_minus,
    sum(fgm)::numeric  / nullif(sum(fga), 0)  AS fg_pct,
    sum(fg3m)::numeric / nullif(sum(fg3a), 0) AS fg3_pct,
    sum(ftm)::numeric  / nullif(sum(fta), 0)  AS ft_pct
FROM player_game_logs
WHERE season_type = 'Regular Season'
GROUP BY player_id, season;
