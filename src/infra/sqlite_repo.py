import sqlite3
from typing import Optional, Any, Dict, List, Tuple
from datetime import datetime
import json
import uuid


class SQLiteRepo:
    def __init__(self, db_path, logger):
        self.db_path = str(db_path)
        self.logger = logger

    def _conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def init_schema(self):
        with self._conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS workorders (
                wo_id TEXT PRIMARY KEY,
                item TEXT,
                lot TEXT,
                qty REAL,
                move_card TEXT,
                status TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS ledger (
                led_id TEXT PRIMARY KEY,
                wo_id TEXT,
                action TEXT,
                note TEXT,
                ts TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT,
                payload_json TEXT,
                created_at TEXT,
                pushed_at TEXT,
                push_error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_workorders_status ON workorders(status);
            CREATE INDEX IF NOT EXISTS idx_workorders_move_card ON workorders(move_card);
            CREATE INDEX IF NOT EXISTS idx_ledger_wo_id ON ledger(wo_id);
            """)
        self.logger.info("SQLite schema initialized")

    # ---------------- WorkOrders ----------------
    def upsert_workorders(self, rows: List[Dict[str, Any]]):
        with self._conn() as c:
            c.executemany("""
                INSERT INTO workorders(wo_id,item,lot,qty,move_card,status,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(wo_id) DO UPDATE SET
                    item=excluded.item,
                    lot=excluded.lot,
                    qty=excluded.qty,
                    move_card=excluded.move_card,
                    status=excluded.status,
                    updated_at=excluded.updated_at
            """, [
                (r["wo_id"], r["item"], r["lot"], float(r["qty"]), r["move_card"], r["status"], r["updated_at"])
                for r in rows
            ])

    def list_workorders(self,
                        include_done: bool,
                        include_canceled: bool,
                        search_move_card: str = "",
                        search_text: str = "") -> List[Dict[str, Any]]:
        where = []
        params = []

        if not include_done:
            where.append("status != 'DONE'")
        if not include_canceled:
            where.append("status != 'CANCELED'")

        if search_move_card.strip():
            where.append("move_card LIKE ?")
            params.append(f"%{search_move_card.strip()}%")

        if search_text.strip():
            where.append("(wo_id LIKE ? OR item LIKE ? OR lot LIKE ?)")
            t = f"%{search_text.strip()}%"
            params.extend([t, t, t])

        sql = "SELECT * FROM workorders"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC"

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_workorder(self, wo_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM workorders WHERE wo_id=?", (wo_id,)).fetchone()
            return dict(r) if r else None

    def update_workorder_status(self, wo_id: str, new_status: str):
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            c.execute("""
                UPDATE workorders SET status=?, updated_at=? WHERE wo_id=?
            """, (new_status, now, wo_id))

    # ---------------- Ledger ----------------
    def append_ledger(self, wo_id: str, action: str, note: str = "") -> str:
        led_id = str(uuid.uuid4())
        ts = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            c.execute("""
                INSERT INTO ledger(led_id, wo_id, action, note, ts)
                VALUES(?,?,?,?,?)
            """, (led_id, wo_id, action, note, ts))
        return led_id

    def list_ledger(self, wo_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._conn() as c:
            if wo_id:
                rows = c.execute("SELECT * FROM ledger WHERE wo_id=? ORDER BY ts DESC", (wo_id,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM ledger ORDER BY ts DESC LIMIT 500").fetchall()
            return [dict(r) for r in rows]

    # ---------------- Events (Queue) ----------------
    def enqueue_event(self, event_type: str, payload: Dict[str, Any]) -> str:
        event_id = str(uuid.uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            c.execute("""
                INSERT INTO events(event_id,event_type,payload_json,created_at,pushed_at,push_error)
                VALUES(?,?,?,?,NULL,NULL)
            """, (event_id, event_type, json.dumps(payload, ensure_ascii=False), now))
        return event_id

    def list_pending_events(self, limit: int) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT * FROM events
                WHERE pushed_at IS NULL
                ORDER BY created_at ASC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def mark_event_pushed(self, event_id: str):
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            c.execute("UPDATE events SET pushed_at=?, push_error=NULL WHERE event_id=?", (now, event_id))

    def mark_event_failed(self, event_id: str, error: str):
        with self._conn() as c:
            c.execute("UPDATE events SET push_error=? WHERE event_id=?", (error, event_id))