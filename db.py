"""
Proxy Orchestrator - SQLite Database Layer
Handles all persistence: proxy registry, health history, request analytics.
"""

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

_lock = threading.Lock()


def _get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


class Database:
    def __init__(self, db_path: str = "proxies.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = _get_conn(db_path)
        self._init_tables()

    def _init_tables(self):
        with self._lock, self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS proxies (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    host        TEXT NOT NULL,
                    port        INTEGER NOT NULL,
                    username    TEXT,
                    password    TEXT,
                    region      TEXT DEFAULT 'unknown',
                    protocol    TEXT DEFAULT 'http',
                    active      INTEGER DEFAULT 1,
                    created_at  TEXT DEFAULT (datetime('now')),
                    UNIQUE(host, port)
                );

                CREATE TABLE IF NOT EXISTS health_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    proxy_id    INTEGER NOT NULL,
                    status      TEXT NOT NULL,    -- 'up' | 'down'
                    latency_ms  REAL,
                    checked_at  TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (proxy_id) REFERENCES proxies(id)
                );

                CREATE TABLE IF NOT EXISTS request_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    proxy_id    INTEGER,
                    session_id  TEXT,
                    url         TEXT,
                    status_code INTEGER,
                    success     INTEGER NOT NULL,  -- 1 or 0
                    latency_ms  REAL,
                    error       TEXT,
                    timestamp   TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (proxy_id) REFERENCES proxies(id)
                );

                CREATE INDEX IF NOT EXISTS idx_health_proxy ON health_log(proxy_id, checked_at);
                CREATE INDEX IF NOT EXISTS idx_req_proxy ON request_log(proxy_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_req_session ON request_log(session_id);
            """)

    # ---- Proxy CRUD ----

    def upsert_proxy(self, host: str, port: int, username=None, password=None,
                     region="unknown", protocol="http") -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                """INSERT INTO proxies (host, port, username, password, region, protocol)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(host, port) DO UPDATE SET
                     username=excluded.username,
                     password=excluded.password,
                     region=excluded.region,
                     protocol=excluded.protocol
                   RETURNING id""",
                (host, port, username, password, region, protocol)
            )
            row = cur.fetchone()
            return row["id"]

    def get_proxy_by_id(self, proxy_id: int) -> dict | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_all_proxies(self, active_only: bool = False) -> list[dict]:
        with self._lock:
            if active_only:
                cur = self._conn.execute("SELECT * FROM proxies WHERE active = 1")
            else:
                cur = self._conn.execute("SELECT * FROM proxies")
            return [dict(r) for r in cur.fetchall()]

    def set_proxy_active(self, proxy_id: int, active: bool):
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE proxies SET active = ? WHERE id = ?",
                (1 if active else 0, proxy_id)
            )

    # ---- Health Log ----

    def log_health(self, proxy_id: int, status: str, latency_ms: float | None = None):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO health_log (proxy_id, status, latency_ms) VALUES (?, ?, ?)",
                (proxy_id, status, latency_ms)
            )

    def get_recent_health(self, proxy_id: int, limit: int = 10) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM health_log WHERE proxy_id = ? ORDER BY checked_at DESC LIMIT ?",
                (proxy_id, limit)
            )
            return [dict(r) for r in cur.fetchall()]

    # ---- Request Log ----

    def log_request(self, proxy_id: int | None, session_id: str | None, url: str,
                    status_code: int | None, success: bool, latency_ms: float,
                    error: str | None = None):
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO request_log
                   (proxy_id, session_id, url, status_code, success, latency_ms, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (proxy_id, session_id, url, status_code, 1 if success else 0,
                 latency_ms, error)
            )

    def get_proxy_stats(self, proxy_id: int, hours: int = 24) -> dict:
        """Return success rate, avg latency, p95 latency, request count for a proxy in last N hours."""
        with self._lock:
            cur = self._conn.execute(
                """SELECT
                     COUNT(*) as total,
                     SUM(success) as successes,
                     AVG(CASE WHEN success = 1 THEN latency_ms END) as avg_latency
                   FROM request_log
                   WHERE proxy_id = ?
                     AND timestamp >= datetime('now', ?)""",
                (proxy_id, f"-{hours} hours")
            )
            row = cur.fetchone()
            if not row or row["total"] == 0:
                return {"total": 0, "success_rate": 0.0, "avg_latency": 0.0, "p95_latency": 0.0}

            total = row["total"]
            successes = row["successes"] or 0

            # Real p95: fetch successful latencies sorted, take the 95th-percentile index.
            lat_cur = self._conn.execute(
                """SELECT latency_ms FROM request_log
                   WHERE proxy_id = ? AND success = 1 AND latency_ms IS NOT NULL
                     AND timestamp >= datetime('now', ?)
                   ORDER BY latency_ms""",
                (proxy_id, f"-{hours} hours")
            )
            latencies = [r["latency_ms"] for r in lat_cur.fetchall()]
            p95 = 0.0
            if latencies:
                import math
                idx = max(0, math.ceil(0.95 * len(latencies)) - 1)
                p95 = latencies[idx]

            return {
                "total": total,
                "success_rate": round(successes / total * 100, 2),
                "avg_latency": round(row["avg_latency"] or 0, 2),
                "p95_latency": round(p95, 2),
            }

    def prune(self, retention_days: int = 7, vacuum: bool = False) -> dict:
        """Delete request_log and health_log rows older than retention_days.
        Returns counts deleted. Set vacuum=True to reclaim disk (locks DB briefly)."""
        with self._lock, self._conn:
            cutoff = f"-{retention_days} days"
            req = self._conn.execute(
                "DELETE FROM request_log WHERE timestamp < datetime('now', ?)", (cutoff,)
            ).rowcount
            health = self._conn.execute(
                "DELETE FROM health_log WHERE checked_at < datetime('now', ?)", (cutoff,)
            ).rowcount
        if vacuum:
            with self._lock:
                self._conn.execute("VACUUM")
        return {"request_log_deleted": req, "health_log_deleted": health}

    def get_all_stats(self, hours: int = 24) -> list[dict]:
        proxies = self.get_all_proxies()
        results = []
        for p in proxies:
            stats = self.get_proxy_stats(p["id"], hours)
            health = self.get_recent_health(p["id"], 1)
            results.append({
                **p,
                **stats,
                "last_health": health[0]["status"] if health else "unknown",
                "last_check": health[0]["checked_at"] if health else None,
            })
        return results

    def get_recent_requests(self, limit: int = 50) -> list[dict]:
        """Recent requests across all proxies (for activity feed)."""
        with self._lock:
            cur = self._conn.execute(
                """SELECT r.*, p.host, p.port, p.region
                   FROM request_log r
                   JOIN proxies p ON r.proxy_id = p.id
                   ORDER BY r.timestamp DESC
                   LIMIT ?""",
                (limit,)
            )
            return [dict(r) for r in cur.fetchall()]

    def get_proxy_requests(self, proxy_id: int, limit: int = 100) -> list[dict]:
        """Recent requests for a specific proxy."""
        with self._lock:
            cur = self._conn.execute(
                """SELECT * FROM request_log
                   WHERE proxy_id = ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (proxy_id, limit)
            )
            return [dict(r) for r in cur.fetchall()]

    def get_trends(self, hours: int = 24) -> dict:
        """Aggregated trends for charts: hourly buckets of success/fail + avg latency."""
        with self._lock:
            cur = self._conn.execute(
                """SELECT
                     strftime('%Y-%m-%d %H:00', timestamp) as hour,
                     COUNT(*) as total,
                     SUM(success) as successes,
                     AVG(CASE WHEN success = 1 THEN latency_ms END) as avg_lat
                   FROM request_log
                   WHERE timestamp >= datetime('now', ?)
                   GROUP BY hour
                   ORDER BY hour""",
                (f"-{hours} hours",)
            )
            rows = [dict(r) for r in cur.fetchall()]

            # Region distribution
            cur2 = self._conn.execute(
                """SELECT p.region, COUNT(*) as count, SUM(r.success) as successes
                   FROM request_log r
                   JOIN proxies p ON r.proxy_id = p.id
                   WHERE r.timestamp >= datetime('now', ?)
                   GROUP BY p.region
                   ORDER BY count DESC""",
                (f"-{hours} hours",)
            )
            regions = [dict(r) for r in cur2.fetchall()]

            return {"hourly": rows, "regions": regions}

    def close(self):
        self._conn.close()
