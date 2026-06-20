"""The read-only SQL sandbox (core.db._validate_select) — pure, no DB."""
import pytest

from core.db import UnsafeQuery, _friendly_sql_error, _validate_select


def _fake_exc(sqlstate, primary):
    diag = type("Diag", (), {"message_primary": primary})()
    orig = type("Orig", (), {"sqlstate": sqlstate, "diag": diag})()
    return type("Exc", (Exception,), {"orig": orig})()


def test_friendly_error_undefined_column_gives_hint_and_echoes_sql():
    msg = _friendly_sql_error(
        _fake_exc("42703", 'column "ts_pct" does not exist'),
        "SELECT ts_pct FROM v_team_games", 6000)
    assert 'column "ts_pct" does not exist' in msg          # core message kept
    assert "doesn't exist on the view" in msg               # actionable hint
    assert "Your query was: SELECT ts_pct FROM v_team_games" in msg
    assert "sqlalche.me" not in msg and "_q" not in msg     # noise stripped


def test_friendly_error_timeout_mentions_seconds_and_narrowing():
    msg = _friendly_sql_error(
        _fake_exc("57014", "canceling statement due to statement timeout"),
        "SELECT * FROM v_player_games", 6000)
    assert "timed out (>6s)" in msg and "Narrow it" in msg


def test_friendly_error_unknown_sqlstate_still_concise():
    msg = _friendly_sql_error(_fake_exc("XX999", "boom"), "SELECT 1", 6000)
    assert msg.startswith("SQL error: boom") and "Your query was: SELECT 1" in msg


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select pts from v_player_games where name_key like '%curry%'",
    "WITH x AS (SELECT 1 AS a) SELECT * FROM x",
    "  SELECT * FROM v_shots WHERE made  ",
    "SELECT 1;",  # a single trailing semicolon is stripped, still one statement
])
def test_allows_read_only(sql):
    assert _validate_select(sql)


@pytest.mark.parametrize("sql", [
    "INSERT INTO players VALUES (1)",
    "UPDATE players SET full_name = 'x'",
    "DELETE FROM players",
    "DROP TABLE players",
    "ALTER TABLE players ADD COLUMN x int",
    "TRUNCATE players",
    "SELECT 1; SELECT 2",            # multi-statement
    "SELECT 1; DROP TABLE players",  # piggybacked write
    "SELECT 1 -- sneaky",            # line comment
    "SELECT /* c */ 1",              # block comment
    "SELECT * INTO evil FROM players",
    "SELECT pg_sleep(10)",
    "SELECT pg_read_file('/etc/passwd')",
    "",
    "    ",
])
def test_rejects_unsafe(sql):
    with pytest.raises(UnsafeQuery):
        _validate_select(sql)
