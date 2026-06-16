"""
Proxy Orchestrator — Web Dashboard (9router-style)
FastAPI + embedded HTML/JS. Single file, no build step, auto-refresh.

Run:
    python dashboard.py
    # or
    uvicorn dashboard:app --reload
"""

import time
import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from core import ProxyOrchestrator
from analytics import Analytics

app = FastAPI(title="Proxy Orchestrator")

# Global orchestrator instance (set by main() or imported externally)
_orch: ProxyOrchestrator | None = None


def set_orchestrator(orch: ProxyOrchestrator):
    global _orch
    _orch = orch


def get_orch() -> ProxyOrchestrator:
    if _orch is None:
        raise RuntimeError("Orchestrator not initialized. Call set_orchestrator() first.")
    return _orch


# ─── API Endpoints ────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats():
    """Pool-level summary + per-proxy runtime stats."""
    orch = get_orch()
    proxies = orch.stats()
    active = sum(1 for p in proxies if p["active"])
    total = len(proxies)
    total_success = sum(p["success_count"] for p in proxies)
    total_fail = sum(p["fail_count"] for p in proxies)
    total_reqs = total_success + total_fail
    overall_rate = round(total_success / total_reqs * 100, 1) if total_reqs > 0 else 0.0

    avg_lat = 0.0
    lat_count = 0
    for p in proxies:
        if p["avg_latency_ms"] > 0:
            avg_lat += p["avg_latency_ms"]
            lat_count += 1
    avg_lat = round(avg_lat / lat_count, 1) if lat_count > 0 else 0.0

    return JSONResponse({
        "pool": {
            "total": total,
            "active": active,
            "inactive": total - active,
            "total_requests": total_reqs,
            "total_success": total_success,
            "total_fail": total_fail,
            "overall_success_rate": overall_rate,
            "avg_latency_ms": avg_lat,
        },
        "proxies": proxies,
        "timestamp": time.time(),
    })


@app.get("/api/db-stats")
async def api_db_stats():
    """Historical stats from SQLite (last 24h)."""
    orch = get_orch()
    return JSONResponse(orch.db.get_all_stats(24))


@app.get("/api/health-log/{proxy_id}")
async def api_health_log(proxy_id: int, limit: int = 20):
    """Recent health check history for a proxy."""
    orch = get_orch()
    return JSONResponse(orch.db.get_recent_health(proxy_id, limit))


# ─── Dashboard HTML ───────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTML_PAGE


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Proxy Orchestrator</title>
<style>
  :root {
    --bg: #0a0a0f;
    --bg-card: #12121a;
    --bg-card-hover: #1a1a25;
    --border: #1e1e2e;
    --border-active: #2a2a3e;
    --text: #e0e0e8;
    --text-dim: #6b6b80;
    --text-muted: #48485a;
    --green: #00d68f;
    --green-dim: #007a51;
    --red: #ff3b5c;
    --red-dim: #7a1c2c;
    --yellow: #ffb800;
    --yellow-dim: #7a5800;
    --blue: #4d8dff;
    --blue-dim: #1c3a7a;
    --purple: #9d6dff;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 13px;
    min-height: 100vh;
    padding: 20px;
  }

  /* Header */
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }
  .header h1 {
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.5px;
  }
  .header h1 .accent { color: var(--green); }
  .header .live {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11px;
    color: var(--text-dim);
  }
  .live-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  /* Stat Cards */
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
  }
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    transition: border-color 0.2s;
  }
  .card:hover { border-color: var(--border-active); }
  .card .label {
    font-size: 11px;
    color: var(--text-dim);
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .card .value {
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -1px;
  }
  .card .sub {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 4px;
  }
  .card.green .value { color: var(--green); }
  .card.red .value { color: var(--red); }
  .card.blue .value { color: var(--blue); }
  .card.yellow .value { color: var(--yellow); }

  /* Table */
  .table-wrap {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  thead th {
    text-align: left;
    padding: 12px 16px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  tbody td {
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr { transition: background 0.15s; }
  tbody tr:hover { background: var(--bg-card-hover); }

  /* Status dot */
  .status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 8px;
    vertical-align: middle;
  }
  .status-dot.up { background: var(--green); box-shadow: 0 0 6px var(--green-dim); }
  .status-dot.down { background: var(--red); box-shadow: 0 0 6px var(--red-dim); }

  /* Health bar */
  .health-bar {
    display: inline-block;
    width: 60px;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
    vertical-align: middle;
    margin-right: 6px;
  }
  .health-bar .fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
  }
  .health-bar .fill.green { background: var(--green); }
  .health-bar .fill.yellow { background: var(--yellow); }
  .health-bar .fill.red { background: var(--red); }

  .tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.3px;
  }
  .tag.region {
    background: var(--blue-dim);
    color: var(--blue);
  }
  .tag.protocol {
    background: var(--border-active);
    color: var(--text-dim);
  }

  /* Footer */
  .footer {
    margin-top: 20px;
    text-align: center;
    font-size: 11px;
    color: var(--text-muted);
  }
  .footer a { color: var(--text-dim); text-decoration: none; }
  .footer a:hover { color: var(--text); }

  /* Empty state */
  .empty {
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
  }
</style>
</head>
<body>

<div class="header">
  <h1>Proxy <span class="accent">Orchestrator</span></h1>
  <div class="live">
    <span class="live-dot" id="liveDot"></span>
    <span id="lastUpdate">—</span>
  </div>
</div>

<!-- Stat Cards -->
<div class="cards" id="cards">
  <div class="card green">
    <div class="label">Active Proxies</div>
    <div class="value" id="activeCount">—</div>
    <div class="sub" id="activeSub"></div>
  </div>
  <div class="card red">
    <div class="label">Inactive</div>
    <div class="value" id="inactiveCount">—</div>
    <div class="sub" id="inactiveSub"></div>
  </div>
  <div class="card blue">
    <div class="label">Total Requests</div>
    <div class="value" id="totalReqs">—</div>
    <div class="sub" id="totalReqsSub"></div>
  </div>
  <div class="card">
    <div class="label">Success Rate</div>
    <div class="value" id="successRate">—</div>
    <div class="sub" id="successRateSub"></div>
  </div>
  <div class="card yellow">
    <div class="label">Avg Latency</div>
    <div class="value" id="avgLatency">—</div>
    <div class="sub" id="avgLatencySub"></div>
  </div>
</div>

<!-- Proxy Table -->
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Status</th>
        <th>Host:Port</th>
        <th>Region</th>
        <th>Protocol</th>
        <th>Weight</th>
        <th>Success</th>
        <th>Fail</th>
        <th>Rate</th>
        <th>Health</th>
        <th>Avg Latency</th>
      </tr>
    </thead>
    <tbody id="proxyTable">
      <tr><td colspan="10" class="empty">Loading…</td></tr>
    </tbody>
  </table>
</div>

<div class="footer">
  Proxy Orchestrator · <a href="https://github.com/lunaticbugbear/proxy-orchestrator" target="_blank">GitHub</a>
  · Auto-refresh 3s
</div>

<script>
const REFRESH_MS = 3000;

function formatNum(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n);
}

function rateColor(rate) {
  if (rate >= 90) return 'green';
  if (rate >= 60) return 'yellow';
  return 'red';
}

async function fetchData() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    updateUI(data);
  } catch (e) {
    document.getElementById('liveDot').style.background = 'var(--red)';
    document.getElementById('lastUpdate').textContent = 'Connection error';
  }
}

function updateUI(data) {
  const pool = data.pool;
  const proxies = data.proxies;

  // Cards
  document.getElementById('activeCount').textContent = pool.active;
  document.getElementById('activeSub').textContent = `of ${pool.total} total`;
  document.getElementById('inactiveCount').textContent = pool.inactive;
  document.getElementById('inactiveSub').textContent = pool.inactive === 0 ? 'all healthy' : 'needs attention';

  document.getElementById('totalReqs').textContent = formatNum(pool.total_requests);
  document.getElementById('totalReqsSub').textContent = `${formatNum(pool.total_success)} ok / ${formatNum(pool.total_fail)} fail`;

  document.getElementById('successRate').textContent = pool.overall_success_rate + '%';
  document.getElementById('successRateSub').textContent = pool.overall_success_rate >= 90 ? 'healthy' : 'degraded';

  document.getElementById('avgLatency').textContent = pool.avg_latency_ms + 'ms';
  document.getElementById('avgLatencySub').textContent = pool.avg_latency_ms < 500 ? 'fast' : pool.avg_latency_ms < 1500 ? 'moderate' : 'slow';

  // Table
  const tbody = document.getElementById('proxyTable');
  if (!proxies || proxies.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty">No proxies registered. Add proxies via config.yaml or add_proxy().</td></tr>';
  } else {
    tbody.innerHTML = proxies.map(p => {
      const total = p.success_count + p.fail_count;
      const rate = total > 0 ? (p.success_count / total * 100).toFixed(1) : '100.0';
      const rateCls = rateColor(parseFloat(rate));
      const statusDot = p.active
        ? '<span class="status-dot up"></span>UP'
        : '<span class="status-dot down"></span>DOWN';
      const healthBar = `<span class="health-bar"><span class="fill ${rateCls}" style="width:${rate}%"></span></span>${rate}%`;

      return `<tr>
        <td>${statusDot}</td>
        <td style="font-weight:600">${p.host}:${p.port}</td>
        <td><span class="tag region">${p.region}</span></td>
        <td><span class="tag protocol">${p.protocol}</span></td>
        <td style="color:var(--text-dim)">${p.weight.toFixed(3)}</td>
        <td style="color:var(--green)">${p.success_count}</td>
        <td style="color:var(--red)">${p.fail_count}</td>
        <td>${rate}%</td>
        <td>${healthBar}</td>
        <td style="color:var(--text-dim)">${p.avg_latency_ms > 0 ? p.avg_latency_ms.toFixed(0) + 'ms' : '—'}</td>
      </tr>`;
    }).join('');
  }

  // Timestamp
  const now = new Date();
  const timeStr = now.toLocaleTimeString('en-US', { hour12: false });
  document.getElementById('lastUpdate').textContent = `Updated ${timeStr}`;
  document.getElementById('liveDot').style.background = 'var(--green)';
}

// Initial fetch + interval
fetchData();
setInterval(fetchData, REFRESH_MS);
</script>

</body>
</html>
"""


# ─── Standalone launcher ──────────────────────────────────────────

if __name__ == "__main__":
    import yaml
    import uvicorn
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("dashboard")

    async def _init():
        orch = ProxyOrchestrator(db_path="proxies.db")
        try:
            await orch.load_from_config("config.yaml")
        except FileNotFoundError:
            logger.warning("config.yaml not found — starting with empty pool")
        set_orchestrator(orch)
        logger.info(f"Dashboard ready: {len(orch.proxies)} proxies loaded")

    # Run init synchronously before uvicorn steals the loop
    asyncio.run(_init())

    logger.info("Starting dashboard on http://localhost:8643")
    uvicorn.run(app, host="0.0.0.0", port=8643, log_level="warning")

