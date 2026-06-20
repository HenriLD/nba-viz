"""Shared database access: engine, query helper, idempotent upserts, and a
sandboxed read-only executor for model-authored SQL."""
import os
import re
from functools import lru_cache

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

load_dotenv()


@lru_cache(maxsize=1)
def get_engine():
    url = os.environ["DATABASE_URL"]
    return create_engine(url, pool_pre_ping=True)


def query_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def execute(sql: str, params: dict | None = None) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(sql), params or {})


# --------------------------------------------------------------- safe SELECT

class UnsafeQuery(ValueError):
    pass


# Whole-word statement keywords that must never appear in model-authored SQL.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|"
    r"vacuum|reindex|cluster|lock|call|do|merge|set|reset|prepare|execute|"
    r"into|nextval|setval|pg_sleep|dblink|pg_read_file|lo_import|lo_export)\b",
    re.IGNORECASE)


def _validate_select(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise UnsafeQuery("Empty query.")
    if ";" in s:
        raise UnsafeQuery("Only a single statement is allowed (no ';').")
    if "--" in s or "/*" in s:
        raise UnsafeQuery("SQL comments are not allowed.")
    if not re.match(r"(?is)^\s*(select|with)\b", s):
        raise UnsafeQuery("Only SELECT / WITH queries are allowed.")
    if _FORBIDDEN.search(s):
        raise UnsafeQuery("Query contains a disallowed keyword "
                          "(only read-only SELECTs are permitted).")
    return s


# Postgres SQLSTATE -> a concise, model-actionable hint. The raw psycopg/
# SQLAlchemy error is verbose (echoes the wrapped query, links to sqlalche.me);
# the model recovers far better from one clear sentence about what to fix.
_SQLSTATE_HELP = {
    "57014": "The query timed out (>{secs}s). Narrow it — filter to one "
             "player/team/season, aggregate, or add LIMIT; don't scan every season.",
    "42703": "That column doesn't exist on the view you queried. Check the "
             "schema for the exact column names.",
    "42P01": "No such table/view. Query only the documented views (v_player_games, "
             "v_team_games, v_shots, player_advanced, team_advanced, "
             "player_improvement, v_clutch, v_team_season, standings, clutch_stats, "
             "hustle_stats, defense_tracking, defender_shooting).",
    "42601": "SQL syntax error — re-check the statement around the position noted.",
    "42803": "Grouping error: every non-aggregated SELECT column must appear in "
             "GROUP BY (use GROUP BY 1, 2 …) or be wrapped in sum()/avg()/count().",
    "42883": "No such function/operator — usually a type mismatch. Cast with "
             "::numeric or ::int.",
    "42804": "Type mismatch. Cast the column with ::numeric / ::int / ::text.",
    "22P02": "Invalid value for a type (e.g. text where a number is expected). "
             "Check casts and quoting.",
    "42702": "Ambiguous column — qualify it with its table/view alias.",
}


def _find_db_error(exc: Exception):
    """Walk the exception chain (pandas DatabaseError → SQLAlchemy → psycopg) for
    the node that actually carries a Postgres SQLSTATE."""
    seen, node = set(), exc
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if getattr(node, "sqlstate", None):
            return node
        orig = getattr(node, "orig", None)
        if orig is not None and getattr(orig, "sqlstate", None):
            return orig
        node = node.__cause__ or node.__context__
    return None


def _friendly_sql_error(exc: Exception, sql: str, timeout_ms: int) -> str:
    """Translate a DB execution error into one actionable line + the model's own
    SQL, stripped of the wrapped-subquery echo and the sqlalche.me URL."""
    psy = _find_db_error(exc)
    sqlstate = getattr(psy, "sqlstate", None)
    diag = getattr(psy, "diag", None)
    core = (getattr(diag, "message_primary", None)
            or (str(psy).split("\n")[0].strip() if psy else "")
            or str(exc).split("\n")[0].strip())
    hint = _SQLSTATE_HELP.get(sqlstate, "")
    if sqlstate == "57014":
        hint = hint.format(secs=int(timeout_ms) // 1000)
    parts = [p for p in (core, hint) if p]
    return f"SQL error: {' — '.join(parts)}  Your query was: {sql}"


def safe_select(sql: str, max_rows: int = 1000, timeout_ms: int = 6000) -> pd.DataFrame:
    """Run model-authored SQL with several independent guardrails:

    1. Keyword/structure validation (single read-only SELECT, no comments).
    2. The statement is wrapped as a subquery with a hard LIMIT — a non-SELECT
       or multi-statement payload fails to parse here, and the row count is
       capped regardless of what the model wrote.
    3. The transaction is READ ONLY, so even a novel bypass cannot mutate data.
    4. statement_timeout aborts a runaway query.

    Execution errors are re-raised as a concise ValueError (see
    _friendly_sql_error) so the model can fix its SQL instead of parsing a raw
    psycopg traceback.
    """
    cleaned = _validate_select(sql)
    wrapped = f"SELECT * FROM (\n{cleaned}\n) AS _q LIMIT {int(max_rows)}"
    try:
        with get_engine().connect() as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
                return pd.read_sql(text(wrapped), conn)
    except Exception as e:  # noqa: BLE001 — translate any DB error for the model
        raise ValueError(_friendly_sql_error(e, cleaned, timeout_ms)) from None


@lru_cache(maxsize=32)
def _reflect(table_name: str) -> Table:
    meta = MetaData()
    return Table(table_name, meta, autoload_with=get_engine())


def upsert_df(table_name: str, df: pd.DataFrame, conflict_cols: list[str],
              chunk_size: int = 1000) -> int:
    """INSERT ... ON CONFLICT DO UPDATE for every row of df.

    Only columns that exist on the target table are written; extra df columns
    are dropped silently so nba_api response shape changes don't break sync.
    """
    if df.empty:
        return 0
    table = _reflect(table_name)
    cols = [c.name for c in table.columns if c.name in df.columns]
    # Drop duplicate conflict keys within the batch — Postgres rejects an
    # ON CONFLICT upsert that would touch the same row twice (e.g. a traded
    # player appearing once per team in a season-aggregate endpoint).
    if all(c in df.columns for c in conflict_cols):
        df = df.drop_duplicates(subset=conflict_cols, keep="last")
    # astype(object) first: on a float column, .where(..., None) coerces None
    # back to NaN, and a NaN sent to an INTEGER column raises "integer out of
    # range" (e.g. old box scores with missing stat values). object dtype lets
    # the None survive so it inserts as SQL NULL.
    records = df[cols].astype(object).where(pd.notnull(df[cols]), None).to_dict("records")

    written = 0
    with get_engine().begin() as conn:
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            stmt = pg_insert(table).values(chunk)
            update_cols = {c: stmt.excluded[c] for c in cols if c not in conflict_cols}
            if update_cols:
                stmt = stmt.on_conflict_do_update(index_elements=conflict_cols,
                                                  set_=update_cols)
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
            conn.execute(stmt)
            written += len(chunk)
    return written
