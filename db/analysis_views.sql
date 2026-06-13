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
    pgl.plus_minus
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
    t.plus_minus
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
    s.action_type, s.shot_type,
    (s.shot_type = '3PT Field Goal')            AS is_three,
    s.shot_zone_basic, s.shot_zone_area, s.shot_zone_range,
    s.shot_distance, s.loc_x, s.loc_y,
    (s.shot_made_flag = 1)                      AS made
FROM shots s;
