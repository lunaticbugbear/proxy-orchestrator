"""
Test suite for Proxy Orchestrator.
Covers the bugs found in review + core behavior. Run: pytest -v
"""

import asyncio
import os
import tempfile
import pytest

from core import Proxy, ProxyOrchestrator, ProxyResponse
from db import Database


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    for ext in ("", "-wal", "-shm"):
        try:
            os.remove(path + ext)
        except OSError:
            pass


# ---------------- Proxy unit tests ----------------

def test_consecutive_failure_deactivation():
    """Bug #1: proxy with a past success must still deactivate on consecutive failures."""
    p = Proxy(1, "h", 80, failure_threshold=5)
    p.record_success(100)
    for _ in range(5):
        p.record_failure()
    assert p.active is False
    assert p.consecutive_failures == 5


def test_success_resets_failure_streak():
    p = Proxy(1, "h", 80, failure_threshold=5)
    for _ in range(4):
        p.record_failure()
    assert p.consecutive_failures == 4
    p.record_success(50)
    assert p.consecutive_failures == 0
    assert p.active is True


def test_url_credentials_are_encoded():
    """Bug #4: special chars in credentials must be percent-encoded."""
    p = Proxy(1, "gw.proxy.com", 8080, username="user@corp", password="p:ss/w@rd")
    assert p.url == "http://user%40corp:p%3Ass%2Fw%40rd@gw.proxy.com:8080"


def test_url_no_auth():
    p = Proxy(1, "h", 80)
    assert p.url == "http://h:80"


def test_success_rate_optimistic_default():
    p = Proxy(1, "h", 80)
    assert p.success_rate == 1.0  # new proxy
    p.record_failure()
    assert p.success_rate == 0.0


# ---------------- Orchestrator selection tests ----------------

def test_sticky_session_same_proxy(tmp_db):
    o = ProxyOrchestrator(db_path=tmp_db)
    o.add_proxy("a", 80)
    o.add_proxy("b", 80)
    p1 = o.get_proxy(session_id="s1")
    p2 = o.get_proxy(session_id="s1")
    assert p1.id == p2.id


def test_sticky_respects_region(tmp_db):
    """Bug #2: sticky pin must not override an explicit region request."""
    o = ProxyOrchestrator(db_path=tmp_db)
    o.add_proxy("us1", 80, region="US")
    o.add_proxy("id1", 80, region="ID")
    p_us = o.get_proxy(session_id="s1", region="US")
    assert p_us.region == "US"
    p_id = o.get_proxy(session_id="s1", region="ID")
    assert p_id.region == "ID"


def test_round_robin_per_region(tmp_db):
    """Bug #3: round-robin cursor must be per-region and deterministic."""
    o = ProxyOrchestrator(db_path=tmp_db)
    o.add_proxy("us1", 80, region="US")
    o.add_proxy("us2", 80, region="US")
    seq = [o.get_proxy(region="US", strategy="round_robin").host for _ in range(4)]
    assert seq == ["us1", "us2", "us1", "us2"]


def test_region_filter(tmp_db):
    o = ProxyOrchestrator(db_path=tmp_db)
    o.add_proxy("us1", 80, region="US")
    o.add_proxy("id1", 80, region="ID")
    for _ in range(10):
        assert o.get_proxy(region="ID").region == "ID"


def test_no_active_proxies_returns_none(tmp_db):
    o = ProxyOrchestrator(db_path=tmp_db)
    p = o.add_proxy("a", 80)
    p.active = False
    assert o.get_proxy() is None


def test_sticky_repin_after_death(tmp_db):
    o = ProxyOrchestrator(db_path=tmp_db)
    o.add_proxy("a", 80)
    o.add_proxy("b", 80)
    o.get_proxy(session_id="s1")
    pinned = o._sticky_map["s1"]
    o.proxies[pinned].active = False
    p = o.get_proxy(session_id="s1")
    assert p is not None and p.active is True
    assert p.id != pinned


# ---------------- Config loading tests ----------------

@pytest.mark.asyncio
async def test_placeholder_config_skipped(tmp_db):
    """Bug #5: template/placeholder proxies must not be loaded."""
    import yaml
    cfg = {
        "proxies": [
            {"host": "geo.iproyal.com", "port": 12321, "username": "your_user", "password": "your_pass"},
            {"host": "real.proxy.net", "port": 8080, "username": "u", "password": "p"},
            {"host": "<PLACEHOLDER>", "port": 80},
            {"host": "noport.com"},  # missing port
        ]
    }
    fd, cfg_path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    with open(cfg_path, "w") as f:
        yaml.safe_dump(cfg, f)

    o = ProxyOrchestrator(db_path=tmp_db)
    await o.load_from_config(cfg_path)
    os.remove(cfg_path)

    hosts = [p.host for p in o.proxies.values()]
    assert hosts == ["real.proxy.net"]


# ---------------- DB tests ----------------

def test_real_p95(tmp_db):
    """Bug #7: p95 must be a real percentile, not avg."""
    db = Database(tmp_db)
    pid = db.upsert_proxy("h", 80)
    for i in range(1, 101):
        db.log_request(pid, None, "u", 200, True, float(i))
    stats = db.get_proxy_stats(pid, hours=24)
    assert stats["avg_latency"] == 50.5
    assert stats["p95_latency"] == 95.0
    db.close()


def test_prune_removes_old_only(tmp_db):
    db = Database(tmp_db)
    pid = db.upsert_proxy("h", 80)
    for i in range(5):
        db._conn.execute(
            "INSERT INTO request_log (proxy_id,url,success,latency_ms,timestamp) "
            "VALUES (?,?,?,?,datetime('now','-10 days'))",
            (pid, "u", 1, float(i)),
        )
    db._conn.commit()
    for i in range(3):
        db.log_request(pid, None, "u", 200, True, float(i))
    res = db.prune(retention_days=7)
    assert res["request_log_deleted"] == 5
    remaining = db._conn.execute("SELECT COUNT(*) FROM request_log").fetchone()[0]
    assert remaining == 3
    db.close()


def test_upsert_idempotent(tmp_db):
    db = Database(tmp_db)
    id1 = db.upsert_proxy("h", 80, region="US")
    id2 = db.upsert_proxy("h", 80, region="ID")  # same host:port
    assert id1 == id2
    p = db.get_proxy_by_id(id1)
    assert p["region"] == "ID"  # updated
    db.close()


# ---------------- Async request / failover tests ----------------

@pytest.mark.asyncio
async def test_request_no_proxy_returns_none(tmp_db):
    o = ProxyOrchestrator(db_path=tmp_db, max_retries=2)
    p = o.add_proxy("127.0.0.1", 1)
    p.active = False
    r = await o.request("GET", "https://httpbin.org/ip")
    assert r is None
    await o.close()


@pytest.mark.asyncio
async def test_response_wrapper():
    body = b'{"key": "value"}'
    p = Proxy(1, "h", 80)
    r = ProxyResponse(200, {"Content-Type": "application/json"}, body, p)
    assert r.ok is True
    assert await r.text() == '{"key": "value"}'
    assert (await r.json())["key"] == "value"
    assert r.content == body


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
