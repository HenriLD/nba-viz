-- Cheap enrichment tables (item 2): small per-player-per-season aggregates from
-- the NBA's own pre-computed endpoints, plus a free derived team-season view.
-- Each table is ~500 rows/season (~2.5k total) — well under the free-tier budget.
-- Run after schema.sql:  psql $DATABASE_URL -f db/enrich.sql

-- Clutch performance (NBA "clutch" = last 5 min, score within 5).
CREATE TABLE IF NOT EXISTS clutch_stats (
    season       TEXT    NOT NULL,
    player_id    INTEGER NOT NULL,
    player_name  TEXT,
    team_abbreviation TEXT,
    gp INTEGER, w INTEGER, l INTEGER, min NUMERIC,
    fgm NUMERIC, fga NUMERIC, fg_pct NUMERIC,
    fg3m NUMERIC, fg3a NUMERIC, fg3_pct NUMERIC,
    ftm NUMERIC, fta NUMERIC, ft_pct NUMERIC,
    reb NUMERIC, ast NUMERIC, tov NUMERIC, stl NUMERIC, blk NUMERIC,
    pts NUMERIC, plus_minus NUMERIC,
    dd2 INTEGER, td3 INTEGER,            -- double-doubles / triple-doubles in clutch
    PRIMARY KEY (season, player_id)
);

-- Clutch *efficiency* view — the insightful answer to "best clutch scorer/shooter"
-- without the raw-points trap. Pure arithmetic over the tiny clutch_stats table
-- (no game-log scan), so it adds no query cost. ts_pct/efg_pct/pts_per_min make
-- an efficiency leaderboard a one-liner; passthrough columns (gp, min, fga) carry
-- the volume guard so a 2-for-2 night can't top the board.
CREATE OR REPLACE VIEW v_clutch AS
SELECT
    season, player_id, player_name, team_abbreviation,
    gp, w, l, min,
    fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct,
    reb, ast, tov, stl, blk, pts, plus_minus, dd2, td3,
    round(pts / nullif(2 * (fga + 0.44 * fta), 0), 3) AS ts_pct,        -- true shooting
    round((fgm + 0.5 * fg3m) / nullif(fga, 0), 3)     AS efg_pct,       -- effective FG%
    round(pts / nullif(min, 0), 2)                    AS pts_per_min    -- scoring rate
FROM clutch_stats;

-- Hustle: effort metrics not visible in the box score.
CREATE TABLE IF NOT EXISTS hustle_stats (
    season       TEXT    NOT NULL,
    player_id    INTEGER NOT NULL,
    player_name  TEXT,
    team_abbreviation TEXT,
    g INTEGER, min NUMERIC,
    contested_shots NUMERIC,
    contested_shots_2pt NUMERIC,
    contested_shots_3pt NUMERIC,
    deflections NUMERIC,
    charges_drawn NUMERIC,
    screen_assists NUMERIC,
    screen_ast_pts NUMERIC,
    loose_balls_recovered NUMERIC,
    box_outs NUMERIC,
    PRIMARY KEY (season, player_id)
);

-- Tracking defense: how the player they guard shoots (overall defended FG%).
CREATE TABLE IF NOT EXISTS defense_tracking (
    season       TEXT    NOT NULL,
    player_id    INTEGER NOT NULL,
    player_name  TEXT,
    player_position TEXT,
    gp INTEGER,
    freq NUMERIC,                -- share of opp shots this player defended
    d_fgm NUMERIC, d_fga NUMERIC, d_fg_pct NUMERIC,
    normal_fg_pct NUMERIC,       -- those shooters' normal FG%
    pct_plusminus NUMERIC,       -- d_fg_pct - normal_fg_pct (negative = good defense)
    PRIMARY KEY (season, player_id)
);

-- Derived (free) team-season summary: offense, defense, net, record. Lets the
-- model rank teams and join opponent-strength tiers ("vs a top-10 defense").
CREATE OR REPLACE VIEW v_team_season AS
SELECT
    tm.abbreviation                                   AS team,
    t.season,
    count(*)                                          AS gp,
    sum((t.wl = 'W')::int)                            AS wins,
    sum((t.wl = 'L')::int)                            AS losses,
    round(avg(t.pts), 1)                              AS pts_pg,        -- offense
    round(avg(opp.pts), 1)                            AS opp_pts_pg,    -- defense
    round(avg(t.pts) - avg(opp.pts), 1)               AS net_pg,
    round(avg(t.fg3a), 1)                             AS fg3a_pg,
    round(sum(t.fg3m)::numeric / nullif(sum(t.fg3a), 0), 3) AS fg3_pct
FROM team_game_logs t
JOIN teams tm ON tm.team_id = t.team_id
LEFT JOIN team_game_logs opp
       ON opp.game_id = t.game_id AND opp.team_id <> t.team_id
WHERE t.season_type = 'Regular Season'
GROUP BY tm.abbreviation, t.season;
