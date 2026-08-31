import sqlite3
import re
import threading
import psycopg

USE_SQLITE = False
_db_lock = threading.Lock()


def _test_postgres():
    try:
        c = psycopg.connect("postgresql://mmd:mmd_pass@localhost:5432/mmd_db", autocommit=True, connect_timeout=3)
        c.close()
        return True
    except Exception as e:
        print(f"Postgres unavailable ({e}) — falling back to embedded SQLite for this session.")
        return False


USE_SQLITE = not _test_postgres()


class SQLiteCursorShim:
    def __init__(self, conn):
        self._conn = conn
        self._cur = conn.cursor()
        self._last_returning = None

    def execute(self, sql, params=None):
        params = params or ()
        sql2 = sql.replace("%s", "?")
        returning_match = re.search(r"RETURNING\s+(\w+)", sql2, re.IGNORECASE)
        if returning_match:
            sql2 = re.sub(r"RETURNING\s+\w+", "", sql2, flags=re.IGNORECASE)
        with _db_lock:
            self._cur.execute(sql2, params)
            self._conn.commit()
            self._last_returning = (self._cur.lastrowid,) if returning_match else None

    def fetchone(self):
        with _db_lock:
            if self._last_returning is not None:
                row = self._last_returning
                self._last_returning = None
                return row
            return self._cur.fetchone()

    def fetchall(self):
        with _db_lock:
            return self._cur.fetchall()

    @property
    def description(self):
        return self._cur.description

    @property
    def rowcount(self):
        return self._cur.rowcount


class SQLiteConnShim:
    def __init__(self, path="fallback.db"):
        self._conn = sqlite3.connect(path, check_same_thread=False)

    def cursor(self):
        return SQLiteCursorShim(self._conn)

    def commit(self):
        with _db_lock:
            self._conn.commit()

    def close(self):
        pass


_sqlite_singleton = None


def get_connection():
    global _sqlite_singleton
    if USE_SQLITE:
        if _sqlite_singleton is None:
            _sqlite_singleton = SQLiteConnShim()
        return _sqlite_singleton
    return psycopg.connect("postgresql://mmd:mmd_pass@localhost:5432/mmd_db", autocommit=True, connect_timeout=3)


def log_audit(conn, alert_id, action, actor, details=""):
    """Append an entry to audit_log. Never lets an audit failure break the caller."""
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO audit_log (alert_id, action, actor, details) VALUES (%s,%s,%s,%s)",
            (alert_id, action, actor, details),
        )
    except Exception as e:
        print(f"[audit_log] failed to record entry: {e}")


def init_schema():
    conn = get_connection()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute("""CREATE TABLE IF NOT EXISTS price_ticks (
            tick_id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, tick_timestamp TEXT, scenario TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT, tick_id INTEGER, ticker TEXT, trader_id TEXT, side TEXT, qty INTEGER)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS alerts (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, alert_type TEXT, risk_level TEXT,
            composite_score REAL, temporal_score REAL, sentiment_score REAL, network_score REAL, lstm_score REAL DEFAULT 0.0,
            alert_timestamp TEXT, status TEXT DEFAULT 'open')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS trader_reputation (
            trader_id TEXT PRIMARY KEY, flag_count INTEGER DEFAULT 0, last_flagged TEXT, reputation_score REAL DEFAULT 0.0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS scenario_commands (
            cmd_id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, scenario TEXT, length_ticks INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, processed INTEGER DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id INTEGER, action TEXT, actor TEXT,
            details TEXT, action_timestamp TEXT DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS trader_reputation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, trader_id TEXT, reputation_score REAL,
            flag_count INTEGER, recorded_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        for col in ("vwap_score", "volume_z_score"):
            try:
                cur.execute(f"ALTER TABLE alerts ADD COLUMN {col} REAL DEFAULT 0")
            except Exception:
                pass  # column already exists from a previous run
        print("SQLite fallback schema initialized (no Docker needed).")
    else:
        cur.execute("""CREATE TABLE IF NOT EXISTS price_ticks (
            tick_id SERIAL PRIMARY KEY, ticker TEXT, open REAL, high REAL, low REAL, close REAL,
            volume BIGINT, tick_timestamp TIMESTAMP, scenario TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS trades (
            trade_id SERIAL PRIMARY KEY, tick_id INTEGER REFERENCES price_ticks(tick_id),
            ticker TEXT, trader_id TEXT, side TEXT, qty INTEGER)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS alerts (
            alert_id SERIAL PRIMARY KEY, ticker TEXT, alert_type TEXT, risk_level TEXT,
            composite_score REAL, temporal_score REAL, sentiment_score REAL, network_score REAL,
            lstm_score REAL DEFAULT 0.0,
            alert_timestamp TIMESTAMP, status TEXT DEFAULT 'open')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS trader_reputation (
            trader_id TEXT PRIMARY KEY, flag_count INTEGER DEFAULT 0,
            last_flagged TIMESTAMP, reputation_score REAL DEFAULT 0.0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS scenario_commands (
            cmd_id SERIAL PRIMARY KEY, ticker TEXT, scenario TEXT, length_ticks INTEGER,
            created_at TIMESTAMP DEFAULT NOW(), processed BOOLEAN DEFAULT FALSE)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            audit_id SERIAL PRIMARY KEY, alert_id INTEGER, action TEXT, actor TEXT,
            details TEXT, action_timestamp TIMESTAMP DEFAULT NOW())""")
        cur.execute("""CREATE TABLE IF NOT EXISTS trader_reputation_history (
            id SERIAL PRIMARY KEY, trader_id TEXT, reputation_score REAL,
            flag_count INTEGER, recorded_at TIMESTAMP DEFAULT NOW())""")
        cur.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS vwap_score REAL DEFAULT 0")
        cur.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS volume_z_score REAL DEFAULT 0")
        print("Postgres schema initialized.")
    conn.close()