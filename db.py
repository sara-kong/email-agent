import os
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector

load_dotenv()

SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        if not SUPABASE_DB_URL:
            raise RuntimeError(
                "SUPABASE_DB_URL is not set. Add it to .env "
                "(Supabase project settings -> Database -> Connection string)."
            )
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, SUPABASE_DB_URL)
    return _pool


def get_conn():
    """Get a pooled connection. Caller must return it via put_conn()."""
    conn = _get_pool().getconn()
    register_vector(conn)
    return conn


def put_conn(conn):
    _get_pool().putconn(conn)


@contextmanager
def db_cursor(commit=False, dict_rows=False):
    """
    Usage:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM emails WHERE user_id = %s", (user_id,))
            rows = cur.fetchall()

        with db_cursor(commit=True) as cur:
            cur.execute("INSERT INTO emails (...) VALUES (...)", (...))

        with db_cursor(dict_rows=True) as cur:
            cur.execute("SELECT * FROM emails WHERE user_id = %s", (user_id,))
            rows = [dict(r) for r in cur.fetchall()]
    """
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor) if dict_rows else conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        finally:
            cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


if __name__ == "__main__":
    with db_cursor() as cur:
        cur.execute("select extname from pg_extension where extname = 'vector'")
        print("pgvector extension installed:", cur.fetchone() is not None)

        cur.execute("""
            select table_name from information_schema.tables
            where table_schema = 'public'
            order by table_name
        """)
        tables = [r[0] for r in cur.fetchall()]
        print(f"Tables in public schema ({len(tables)}):")
        for t in tables:
            print(f"  - {t}")
