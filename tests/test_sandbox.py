"""The read-only SQL sandbox (core.db._validate_select) — pure, no DB."""
import pytest

from core.db import UnsafeQuery, _validate_select


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
