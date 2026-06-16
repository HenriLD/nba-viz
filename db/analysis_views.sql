-- Analysis views for the flexible query tool (query_chart).
-- Run after schema.sql:  psql $DATABASE_URL -f db/analysis_views.sql
--
-- These denormalize the raw tables and precompute the derived columns the
-- model would otherwise have to express in fragile string/window SQL:
-- home/away, opponent, win flag, days of rest, game number, opponent points.
--
-- name_key = lower(unaccent(player_name)) lets model SQL match players by an
-- unaccented substring (e.g. name_key LIKE '%jokic%' matches 'Nikola Jokić'),
-- preserving the diacritic-folding the curated path gets from entity resolution.

CREATE EXTENSION IF NOT EXISTS unaccent;

-- Drop first: CREATE OR REPLACE VIEW cannot insert/reorder columns.
DROP VIEW IF EXISTS v_player_games;
DROP VIEW IF EXISTS v_team_games;
DROP VIEW IF EXISTS v_shots;

-- One row per player per game, analysis-friendly.
CREATE OR REPLACE VIEW v_player_games AS
SELECT
    pgl.player_id,
    pgl.player_name,
    lower(unaccent(pgl.player_name))            AS name_key,
    pgl.team_id,
    pgl.team_abbreviation                       AS team,
    pgl.game_id,
    pgl.season,
    pgl.season_type,
    pgl.game_date,
    pgl.matchup,
    (pgl.matchup LIKE '%vs.%')                  AS is_home,
    trim(right(pgl.matchup, 3))                 AS opponent,   -- 3-letter abbr
    (pgl.wl = 'W')                              AS won,
    (pgl.game_date - lag(pgl.game_date) OVER (
        PARTITION BY pgl.player_id, pgl.season, pgl.season_type
        ORDER BY pgl.game_date))                AS days_rest,  -- NULL on 1st game
    row_number() OVER (
        PARTITION BY pgl.player_id, pgl.season, pgl.season_type
        ORDER BY pgl.game_date)                 AS game_no,
    pgl.min, pgl.pts, pgl.reb, pgl.ast, pgl.stl, pgl.blk, pgl.tov, pgl.pf,
    pgl.oreb, pgl.dreb,
    pgl.fgm, pgl.fga, pgl.fg_pct,
    pgl.fg3m, pgl.fg3a, pgl.fg3_pct,
    pgl.ftm, pgl.fta, pgl.ft_pct,
    pgl.plus_minus,
    -- Derived per-game advanced metrics (free — arithmetic on the same row):
    -- prefer these over raw splits for "efficiency" / "impact" / "best game".
    round(pgl.pts / nullif(2 * (pgl.fga + 0.44 * pgl.fta), 0)::numeric, 3) AS ts_pct,
    round((pgl.fgm + 0.5 * pgl.fg3m) / nullif(pgl.fga, 0)::numeric, 3)     AS efg_pct,
    round((pgl.pts + 0.4 * pgl.fgm - 0.7 * pgl.fga - 0.4 * (pgl.fta - pgl.ftm)
           + 0.7 * pgl.oreb + 0.3 * pgl.dreb + pgl.stl + 0.7 * pgl.ast
           + 0.7 * pgl.blk - 0.4 * pgl.pf - pgl.tov)::numeric, 1)         AS game_score
FROM player_game_logs pgl;

-- One row per team per game, with opponent points and margin via self-join.
CREATE OR REPLACE VIEW v_team_games AS
SELECT
    t.team_id,
    tm.abbreviation                             AS team,
    t.game_id,
    t.season,
    t.season_type,
    t.game_date,
    t.matchup,
    (t.matchup LIKE '%vs.%')                    AS is_home,
    trim(right(t.matchup, 3))                   AS opponent,
    (t.wl = 'W')                                AS won,
    (t.game_date - lag(t.game_date) OVER (
        PARTITION BY t.team_id, t.season, t.season_type
        ORDER BY t.game_date))                  AS days_rest,
    t.pts,
    opp.pts                                     AS opp_pts,
    (t.pts - opp.pts)                           AS margin,
    t.reb, t.ast, t.stl, t.blk, t.tov, t.pf,
    t.oreb, t.dreb,
    t.fgm, t.fga, t.fg_pct,
    t.fg3m, t.fg3a, t.fg3_pct,
    t.ftm, t.fta, t.ft_pct,
    t.plus_minus,
    round((t.fgm + 0.5 * t.fg3m) / nullif(t.fga, 0)::numeric, 3)  AS efg_pct,
    -- Possession estimate (Oliver) and points per 100 — a pace-fair scoring rate.
    (t.fga + 0.44 * t.fta + t.tov - t.oreb)                       AS poss,
    round(100 * t.pts / nullif(t.fga + 0.44 * t.fta + t.tov - t.oreb, 0)::numeric, 1) AS off_rtg
FROM team_game_logs t
JOIN teams tm ON tm.team_id = t.team_id
LEFT JOIN team_game_logs opp
       ON opp.game_id = t.game_id AND opp.team_id <> t.team_id;

-- One row per shot, with boolean flags for easy filtering/aggregation.
CREATE OR REPLACE VIEW v_shots AS
SELECT
    s.game_id, s.game_event_id,
    s.player_id, s.player_name,
    lower(unaccent(s.player_name))              AS name_key,
    s.team_id,
    s.season, s.season_type, s.game_date, s.period,
    s.minutes_remaining, s.seconds_remaining,
    (s.minutes_remaining * 60 + s.seconds_remaining)  AS secs_left_period,
    -- Time-based "clutch"/late-game flag: 4th quarter or OT, <= 5:00 left. (The
    -- official clutch definition also needs score-within-5, which we have no
    -- per-shot score for — so this is the time half of clutch, not the margin.)
    (s.period >= 4 AND s.minutes_remaining * 60 + s.seconds_remaining <= 300) AS late_game,
    s.action_type, s.shot_type,
    (s.shot_type = '3PT Field Goal')            AS is_three,
    s.shot_zone_basic, s.shot_zone_area, s.shot_zone_range,
    s.shot_distance, s.loc_x, s.loc_y,
    (s.shot_made_flag = 1)                      AS made,
    -- Game context joined from the shooter's team box score (1:1 on game+team),
    -- so shots can be filtered/colored by opponent or by win/loss — "shots vs
    -- the Lakers", "shots in wins". opponent is the 3-letter abbreviation.
    trim(right(tgl.matchup, 3))                 AS opponent,
    (tgl.wl = 'W')                              AS won
FROM shots s
LEFT JOIN team_game_logs tgl
       ON tgl.game_id = s.game_id AND tgl.team_id = s.team_id;
