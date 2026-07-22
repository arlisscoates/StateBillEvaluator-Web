"""SQLite persistence — the Windows stand-in for the app's SwiftData store."""
import os
import sqlite3
from datetime import datetime, timezone

DB_DIR = os.path.join(os.path.expanduser("~"), ".state_bill_evaluator")
DB_PATH = os.path.join(DB_DIR, "bills.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS bills (
                bill_id          INTEGER PRIMARY KEY,
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
        )


def upsert_summary(summary: dict) -> int:
    """Insert or update a bill from a LegiScan search summary. Returns bill_id.

    Mirrors SyncService.syncBills upsert: refresh title/last_action on existing
    rows, leave category/impact untouched.
    """
    bid = int(summary["bill_id"])
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        row = c.execute("SELECT bill_id FROM bills WHERE bill_id=?", (bid,)).fetchone()
        if row:
            c.execute(
                """UPDATE bills SET title=COALESCE(?,title), last_action=?,
                   last_action_date=?, url=CASE WHEN ?<>'' THEN ? ELSE url END,
                   last_updated=? WHERE bill_id=?""",
                (
                    summary.get("title"),
                    summary.get("last_action"),
                    summary.get("last_action_date"),
                    summary.get("url") or "",
                    summary.get("url") or "",
                    now,
                    bid,
                ),
            )
        else:
            c.execute(
                """INSERT INTO bills (bill_id,title,description,state,status,session,url,
                   last_action,last_action_date,last_updated)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    bid,
                    summary.get("title") or "Untitled",
                    summary.get("title") or "",
                    summary.get("state") or "US",
                    summary.get("last_action") or "Unknown",
                    "",
                    summary.get("url") or "",
                    summary.get("last_action"),
                    summary.get("last_action_date"),
                    now,
                ),
            )
    return bid


def insert_sample_bill(b: dict) -> None:
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO bills
               (bill_id,title,description,state,status,session,url,category_name,
                last_action,last_action_date,last_updated)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                b["bill_id"], b["title"], b["description"], b["state"], b["status"],
                b["session"], b["url"], b["category_name"], b["last_action"],
                b["last_action_date"], datetime.now(timezone.utc).isoformat(),
            ),
        )


def set_category(bill_id: int, category: str) -> None:
    with _conn() as c:
        c.execute("UPDATE bills SET category_name=? WHERE bill_id=?", (category, bill_id))


def set_impact(bill_id: int, impact_json: str) -> None:
    with _conn() as c:
        c.execute("UPDATE bills SET impact_json=? WHERE bill_id=?", (impact_json, bill_id))


def set_detail(bill_id: int, description=None, status=None, url=None, session=None, sponsors=None) -> None:
    with _conn() as c:
        c.execute(
            """UPDATE bills SET
               description=COALESCE(?,description), status=COALESCE(?,status),
               url=COALESCE(?,url), session=COALESCE(?,session),
               sponsors=COALESCE(?,sponsors) WHERE bill_id=?""",
            (description, status, url, session, sponsors, bill_id),
        )


def all_bills() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM bills ORDER BY state, title")]


def uncategorized_bills() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM bills WHERE category_name IS NULL OR category_name=''")]


def clear_all() -> None:
    with _conn() as c:
        c.execute("DELETE FROM bills")
