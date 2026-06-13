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


def safe_select(sql: str, max_rows: int = 1000, timeout_ms: int = 6000) -> pd.DataFrame:
    """Run model-authored SQL with several independent guardrails:

    1. Keyword/structure validation (single read-only SELECT, no comments).
    2. The statement is wrapped as a subquery with a hard LIMIT — a non-SELECT
       or multi-statement payload fails to parse here, and the row count is
       capped regardless of what the model wrote.
    3. The transaction is READ ONLY, so even a novel bypass cannot mutate data.
    4. statement_timeout aborts a runaway query.
    """
    cleaned = _validate_select(sql)
    wrapped = f"SELECT * FROM (\n{cleaned}\n) AS _q LIMIT {int(max_rows)}"
    with get_engine().connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
            return pd.read_sql(text(wrapped), conn)


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
    records = df[cols].where(pd.notnull(df[cols]), None).to_dict("records")

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
