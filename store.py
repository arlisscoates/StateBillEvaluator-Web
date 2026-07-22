"""Persistence layer.

Backend is chosen at runtime:
  * If DATABASE_URL (or SUPABASE_DB_URL) is set  -> Postgres (Supabase)  [persistent]
  * Otherwise                                    -> local SQLite         [dev fallback]

The public function interface is identical for both backends, so app.py never
needs to know which one is active. A fresh connection is opened per operation
(cheap, and thread-safe across Streamlit's per-session threads).
"""
import os
from contextlib import contextmanager
from datetime import datetime, timezone

DB_DIR = os.path.join(os.path.expanduser("~"), ".state_bill_evaluator")
DB_PATH = os.path.join(DB_DIR, "bills.db")

# Column order used by the sample-bill upsert.
_SAMPLE_COLS = ["bill_id", "title", "description", "state", "status", "session",
                "url", "category_name", "last_action", "last_action_date", "last_updated"]


def _db_url() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")


def is_postgres() -> bool:
    return bool(_db_url())


@contextmanager
def _cursor():
    """Yield (backend, cursor); commit on success, always close."""
    url = _db_url()
    if url:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(url, cursor_factory=RealDictCursor, connect_timeout=15)
        try:
            yield "postgres", conn.cursor()
            conn.commit()
        finally:
            conn.close()
    else:
        import sqlite3
        os.makedirs(DB_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield "sqlite", conn.cursor()
            conn.commit()
        finally:
            conn.close()


def _q(backend: str, sql: str) -> str:
    """Translate '?' placeholders to '%s' for Postgres. (No literal '?' in our SQL.)"""
    return sql.replace("?", "%s") if backend == "postgres" else sql


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    ddl = """
        CREATE TABLE IF NOT EXISTS bills (
            bill_id          BIGINT PRIMARY KEY,
            title            TEXT NOT NULL,
            description      TEXT DEFAULT '',
            state            TEXT DEFAULT 'US',
            status           TEXT DEFAULT '',
            session          TEXT DEFAULT '',
            url              TEXT DEFAULT '',
            category_name    TEXT,
            sponsors         TEXT,
            last_action      TEXT,
            last_action_date TEXT,
            impact_json      TEXT,
            last_updated     TEXT
        )
    """
    territory_ddl = """
        CREATE TABLE IF NOT EXISTS rep_territory (
            email  TEXT PRIMARY KEY,
            states TEXT DEFAULT ''
        )
    """
    with _cursor() as (backend, cur):
        cur.execute(ddl)
        cur.execute(territory_ddl)


def upsert_summary(summary: dict) -> int:
    """Insert/update a bill from a LegiScan search summary (mirrors SyncService)."""
    bid = int(summary["bill_id"])
    with _cursor() as (backend, cur):
        cur.execute(_q(backend, "SELECT bill_id FROM bills WHERE bill_id=?"), (bid,))
        exists = cur.fetchone() is not None
        if exists:
            cur.execute(_q(backend,
                """UPDATE bills SET title=COALESCE(?,title), last_action=?,
                   last_action_date=?, url=CASE WHEN ?<>'' THEN ? ELSE url END,
                   last_updated=? WHERE bill_id=?"""),
                (summary.get("title"), summary.get("last_action"),
                 summary.get("last_action_date"), summary.get("url") or "",
                 summary.get("url") or "", _now(), bid))
        else:
            cur.execute(_q(backend,
                """INSERT INTO bills (bill_id,title,description,state,status,session,url,
                   last_action,last_action_date,last_updated)
                   VALUES (?,?,?,?,?,?,?,?,?,?)"""),
                (bid, summary.get("title") or "Untitled", summary.get("title") or "",
                 summary.get("state") or "US", summary.get("last_action") or "Unknown",
                 "", summary.get("url") or "", summary.get("last_action"),
                 summary.get("last_action_date"), _now()))
    return bid


def insert_sample_bill(b: dict) -> None:
    values = [b["bill_id"], b["title"], b["description"], b["state"], b["status"],
              b["session"], b["url"], b["category_name"], b["last_action"],
              b["last_action_date"], _now()]
    cols = ",".join(_SAMPLE_COLS)
    with _cursor() as (backend, cur):
        if backend == "postgres":
            ph = ",".join(["%s"] * len(_SAMPLE_COLS))
            updates = ",".join(f"{c}=EXCLUDED.{c}" for c in _SAMPLE_COLS if c != "bill_id")
            cur.execute(
                f"INSERT INTO bills ({cols}) VALUES ({ph}) "
                f"ON CONFLICT (bill_id) DO UPDATE SET {updates}", values)
        else:
            ph = ",".join(["?"] * len(_SAMPLE_COLS))
            cur.execute(f"INSERT OR REPLACE INTO bills ({cols}) VALUES ({ph})", values)


def set_category(bill_id: int, category: str) -> None:
    with _cursor() as (backend, cur):
        cur.execute(_q(backend, "UPDATE bills SET category_name=? WHERE bill_id=?"),
                    (category, bill_id))


def set_impact(bill_id: int, impact_json: str) -> None:
    with _cursor() as (backend, cur):
        cur.execute(_q(backend, "UPDATE bills SET impact_json=? WHERE bill_id=?"),
                    (impact_json, bill_id))


def set_detail(bill_id: int, description=None, status=None, url=None, session=None, sponsors=None) -> None:
    with _cursor() as (backend, cur):
        cur.execute(_q(backend,
            """UPDATE bills SET
               description=COALESCE(?,description), status=COALESCE(?,status),
               url=COALESCE(?,url), session=COALESCE(?,session),
               sponsors=COALESCE(?,sponsors) WHERE bill_id=?"""),
            (description, status, url, session, sponsors, bill_id))


def all_bills() -> list[dict]:
    with _cursor() as (backend, cur):
        cur.execute("SELECT * FROM bills ORDER BY state, title")
        return [dict(r) for r in cur.fetchall()]


def uncategorized_bills() -> list[dict]:
    with _cursor() as (backend, cur):
        cur.execute("SELECT * FROM bills WHERE category_name IS NULL OR category_name=''")
        return [dict(r) for r in cur.fetchall()]


def clear_all() -> None:
    with _cursor() as (backend, cur):
        cur.execute("DELETE FROM bills")


# --- per-rep territory ------------------------------------------------------

def get_territory(email: str) -> list[str]:
    with _cursor() as (backend, cur):
        cur.execute(_q(backend, "SELECT states FROM rep_territory WHERE email=?"), (email,))
        row = cur.fetchone()
    if not row:
        return []
    states = dict(row)["states"] or ""
    return [s for s in states.split(",") if s]


def set_territory(email: str, states: list[str]) -> None:
    joined = ",".join(states)
    with _cursor() as (backend, cur):
        if backend == "postgres":
            cur.execute(
                "INSERT INTO rep_territory (email, states) VALUES (%s, %s) "
                "ON CONFLICT (email) DO UPDATE SET states=EXCLUDED.states",
                (email, joined))
        else:
            cur.execute("INSERT OR REPLACE INTO rep_territory (email, states) VALUES (?, ?)",
                        (email, joined))
