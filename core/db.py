"""Shared database access: engine, query helper, idempotent upserts."""
import os
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
