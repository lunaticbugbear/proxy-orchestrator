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


# ─── Dashboard HTML (9router design language) ─────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTML_PAGE


HTML_PAGE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Proxy Orchestrator</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/icon?family=Material+Symbols+Outlined" rel="stylesheet">
<style>
  :root {
    --brand-500: #E56A4A;
    --brand-600: #cc5236;
    --brand-700: #a64027;
    --brand-300: #ee8d6a;
    --brand-400: #ea7855;

    --bg: #1a1a1a;
    --bg-alt: #1F1F1E;
    --surface: #262626;
    --surface-2: #303030;
    --surface-3: #3a3a3a;
    --sidebar: rgba(30, 30, 30, 0.85);

    --border: #333333;
    --border-subtle: #2a2a2a;

    --text-main: #ededed;
    --text-muted: #9ca3af;
    --text-subtle: #6b7280;

    --danger: #ef4444;
    --success: #22c55e;
    --warning: #fbbf24;
    --info: #60a5fa;

    --radius: 10px;
    --radius-lg: 14px;

    --shadow-soft: 0 1px 2px 0 rgba(0,0,0,0.3);
    --shadow-warm: 0 2px 12px -2px rgba(229, 106, 74, 0.25);
    --shadow-elev:
      inset 0 1px 0 0 rgba(255,255,255,0.06),
      0 1px 2px rgba(0,0,0,0.4),
      0 16px 48px -8px rgba(0,0,0,0.55);

    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background-color: var(--bg);
    color: var(--text-main);
    font-family: var(--font-sans);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
  }

  ::selection { background: rgba(229,106,74,0.3); color: var(--brand-300); }

  .material-symbols-outlined {
    font-family: 'Material Symbols Outlined', sans-serif;
    font-weight: normal; font-style: normal;
    font-size: 20px; line-height: 1;
    display: inline-block;
    -webkit-font-smoothing: antialiased;
  }

  /* Layout: sidebar + main */
  .app-layout { display: flex; min-height: 100vh; }

  /* Sidebar */
  .sidebar {
    width: 260px; flex-shrink: 0;
    border-right: 1px solid var(--border-subtle);
    background: var(--sidebar);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    display: flex; flex-direction: column;
  }
  .traffic-lights { display: flex; gap: 8px; padding: 18px 24px 4px; }
  .traffic-lights span { width: 12px; height: 12px; border-radius: 50%; }
  .traffic-lights .red { background: #FF5F56; }
  .traffic-lights .yellow { background: #FFBD2E; }
  .traffic-lights .green { background: #27C93F; }

  .logo-section { padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
  .logo-icon {
    width: 36px; height: 36px;
    border-radius: var(--radius);
    background: linear-gradient(135deg, var(--brand-500), var(--brand-700));
    box-shadow: var(--shadow-warm);
    display: flex; align-items: center; justify-content: center;
  }
  .logo-icon .material-symbols-outlined { color: white; font-size: 20px; }
  .logo-text h1 { font-size: 16px; font-weight: 600; letter-spacing: -0.3px; }
  .logo-text span { font-size: 11px; color: var(--text-muted); }

  .nav-section { flex: 1; padding: 8px 16px; overflow-y: auto; }
  .nav-section::-webkit-scrollbar { width: 4px; }
  .nav-section::-webkit-scrollbar-thumb { background: rgba(156,163,175,0.2); border-radius: 20px; }
  .nav-label {
    font-size: 11px; font-weight: 600;
    color: var(--text-subtle);
    text-transform: uppercase; letter-spacing: 0.5px;
    padding: 12px 12px 6px;
  }
  .nav-item {
    display: flex; align-items: center; gap: 12px;
    padding: 7px 12px; border-radius: 8px;
    color: var(--text-muted);
    transition: all 0.15s;
    cursor: pointer; font-size: 13px; font-weight: 500;
    margin-bottom: 2px;
  }
  .nav-item:hover { background: var(--surface-2); color: var(--text-main); }
  .nav-item.active { background: rgba(229,106,74,0.1); color: var(--brand-500); }
  .nav-item.active .material-symbols-outlined { font-variation-settings: 'FILL' 1; }
  .nav-item .material-symbols-outlined { font-size: 18px; }

  .sidebar-footer { padding: 12px 16px; border-top: 1px solid var(--border-subtle); }
  .sidebar-footer .badge {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 11px; color: var(--text-subtle);
  }
  .sidebar-footer .badge .dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--success); animation: pulse 2s infinite;
  }

  /* Main content */
  .main-content { flex: 1; overflow-x: hidden; }

  .topbar {
    display: flex; justify-content: space-between; align-items: center;
    padding: 16px 32px;
    border-bottom: 1px solid var(--border-subtle);
    background: var(--sidebar);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
  }
  .topbar h2 { font-size: 18px; font-weight: 600; letter-spacing: -0.5px; }
  .topbar .meta { display: flex; align-items: center; gap: 16px; }
  .topbar .meta-item {
    display: flex; align-items: center; gap: 6px;
    font-size: 12px; color: var(--text-muted);
  }
  .topbar .meta-item .dot {
    width: 8px; height: 8px; border-radius: 50%;
  }
  .topbar .meta-item .dot.live { background: var(--success); animation: pulse 2s infinite; }
  .topbar .meta-item .dot.dead { background: var(--danger); }

  .content-area { padding: 24px 32px; }

  /* Dot grid bg */
  .dot-grid {
    background-color: var(--bg);
    background-image:
      radial-gradient(circle at 15% 20%, rgba(229,106,74,0.12) 0%, transparent 40%),
      radial-gradient(circle at 85% 80%, rgba(229,106,74,0.06) 0%, transparent 40%);
  }

  /* Stat cards */
  .cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px; margin-bottom: 24px;
  }
  .stat-card {
    background: var(--surface);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-elev);
    padding: 20px;
    transition: transform 0.2s, box-shadow 0.2s;
    position: relative; overflow: hidden;
  }
  .stat-card::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(229,106,74,0.3), transparent);
  }
  .stat-card:hover { transform: translateY(-2px); }
  .stat-card .stat-header {
    display: flex; align-items: center; gap: 8px; margin-bottom: 12px;
  }
  .stat-card .stat-icon {
    width: 32px; height: 32px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
  }
  .stat-card .stat-icon .material-symbols-outlined { font-size: 18px; }
  .stat-card .stat-label {
    font-size: 12px; font-weight: 500;
    color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.3px;
  }
  .stat-card .stat-value {
    font-size: 28px; font-weight: 700; letter-spacing: -1px;
    line-height: 1.2;
  }
  .stat-card .stat-sub {
    font-size: 11px; color: var(--text-subtle); margin-top: 4px;
  }

  .stat-card.green .stat-icon { background: rgba(34,197,94,0.12); }
  .stat-card.green .stat-icon .material-symbols-outlined { color: var(--success); }
  .stat-card.green .stat-value { color: var(--success); }
  .stat-card.red .stat-icon { background: rgba(239,68,68,0.12); }
  .stat-card.red .stat-icon .material-symbols-outlined { color: var(--danger); }
  .stat-card.red .stat-value { color: var(--danger); }
  .stat-card.blue .stat-icon { background: rgba(96,165,250,0.12); }
  .stat-card.blue .stat-icon .material-symbols-outlined { color: var(--info); }
  .stat-card.blue .stat-value { color: var(--info); }
  .stat-card.brand .stat-icon { background: rgba(229,106,74,0.12); }
  .stat-card.brand .stat-icon .material-symbols-outlined { color: var(--brand-500); }
  .stat-card.brand .stat-value { color: var(--brand-500); }
  .stat-card.yellow .stat-icon { background: rgba(251,191,36,0.12); }
  .stat-card.yellow .stat-icon .material-symbols-outlined { color: var(--warning); }
  .stat-card.yellow .stat-value { color: var(--warning); }

  /* Table card */
  .table-card {
    background: var(--surface);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-elev);
    overflow: hidden;
  }
  .table-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-subtle);
  }
  .table-header h3 {
    font-size: 14px; font-weight: 600;
    display: flex; align-items: center; gap: 8px;
  }
  .table-header h3 .material-symbols-outlined { font-size: 18px; color: var(--brand-500); }
  .table-header .count {
    font-size: 11px; color: var(--text-muted);
    background: var(--surface-2); padding: 3px 10px; border-radius: 12px;
  }

  table { width: 100%; border-collapse: collapse; }
  thead th {
    text-align: left; padding: 10px 20px;
    font-size: 11px; font-weight: 600;
    color: var(--text-subtle);
    text-transform: uppercase; letter-spacing: 0.5px;
    border-bottom: 1px solid var(--border-subtle);
    white-space: nowrap;
  }
  tbody td {
    padding: 12px 20px;
    border-bottom: 1px solid var(--border-subtle);
    font-size: 13px; white-space: nowrap;
  }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr { transition: background 0.15s; }
  tbody tr:hover { background: var(--surface-2); }

  .status-pill {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 600;
  }
  .status-pill.up { background: rgba(34,197,94,0.12); color: var(--success); }
  .status-pill.down { background: rgba(239,68,68,0.12); color: var(--danger); }
  .status-pill .dot { width: 6px; height: 6px; border-radius: 50%; }
  .status-pill.up .dot { background: var(--success); }
  .status-pill.down .dot { background: var(--danger); }

  .tag {
    display: inline-block; padding: 2px 8px;
    border-radius: 6px; font-size: 11px; font-weight: 500;
  }
  .tag.region { background: rgba(96,165,250,0.12); color: var(--info); }
  .tag.protocol { background: var(--surface-3); color: var(--text-muted); }

  .health-bar {
    display: inline-flex; align-items: center; gap: 8px;
  }
  .health-bar .bar {
    width: 50px; height: 5px;
    background: var(--surface-3); border-radius: 3px; overflow: hidden;
  }
  .health-bar .fill { height: 100%; border-radius: 3px; transition: width 0.5s; }
  .health-bar .fill.green { background: var(--success); }
  .health-bar .fill.yellow { background: var(--warning); }
  .health-bar .fill.red { background: var(--danger); }
  .health-bar .pct { font-size: 11px; color: var(--text-muted); }

  .latency { font-size: 12px; color: var(--text-muted); }
  .latency.fast { color: var(--success); }
  .latency.moderate { color: var(--warning); }
  .latency.slow { color: var(--danger); }

  .empty-state {
    text-align: center; padding: 48px 20px;
    color: var(--text-subtle);
  }
  .empty-state .material-symbols-outlined {
    font-size: 48px; color: var(--surface-3); margin-bottom: 12px;
  }

  /* Animations */
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
  @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
  @keyframes slideInTop { from { transform: translateY(-8px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
  .fade-in { animation: fadeIn 0.3s ease-out forwards; }
  .slide-in-top { animation: slideInTop 0.2s cubic-bezier(0.22,1,0.36,1) forwards; }

  /* Footer */
  .footer {
    padding: 16px 32px;
    text-align: center; font-size: 12px; color: var(--text-subtle);
  }
  .footer a { color: var(--brand-400); text-decoration: none; }
  .footer a:hover { color: var(--brand-300); }
</style>
</head>
<body>

<div class="app-layout">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="traffic-lights">
      <span class="red"></span><span class="yellow"></span><span class="green"></span>
    </div>
    <div class="logo-section">
      <div class="logo-icon"><span class="material-symbols-outlined">hub</span></div>
      <div class="logo-text">
        <h1>Proxy Orchestrator</h1>
        <span>v1.0.0</span>
      </div>
    </div>
    <nav class="nav-section">
      <div class="nav-label">Monitoring</div>
      <div class="nav-item active">
        <span class="material-symbols-outlined">dashboard</span>
        <span>Overview</span>
      </div>
      <div class="nav-item">
        <span class="material-symbols-outlined">dns</span>
        <span>Proxies</span>
      </div>
      <div class="nav-item">
        <span class="material-symbols-outlined">health_and_safety</span>
        <span>Health Checks</span>
      </div>
      <div class="nav-item">
        <span class="material-symbols-outlined">bar_chart</span>
        <span>Analytics</span>
      </div>
      <div class="nav-label">System</div>
      <div class="nav-item">
        <span class="material-symbols-outlined">settings</span>
        <span>Settings</span>
      </div>
      <div class="nav-item">
        <span class="material-symbols-outlined">terminal</span>
        <span>API Docs</span>
      </div>
    </nav>
    <div class="sidebar-footer">
      <div class="badge">
        <span class="dot"></span>
        <span id="sidebarStatus">Connected</span>
      </div>
    </div>
  </aside>

  <!-- Main -->
  <div class="main-content dot-grid">
    <div class="topbar">
      <h2>Overview</h2>
      <div class="meta">
        <div class="meta-item">
          <span class="dot live" id="liveDot"></span>
          <span id="lastUpdate">Connecting…</span>
        </div>
      </div>
    </div>

    <div class="content-area">
      <!-- Stat Cards -->
      <div class="cards-grid" id="cards">
        <div class="stat-card green fade-in">
          <div class="stat-header">
            <div class="stat-icon"><span class="material-symbols-outlined">check_circle</span></div>
            <span class="stat-label">Active</span>
          </div>
          <div class="stat-value" id="activeCount">—</div>
          <div class="stat-sub" id="activeSub">of — total</div>
        </div>
        <div class="stat-card red fade-in">
          <div class="stat-header">
            <div class="stat-icon"><span class="material-symbols-outlined">cancel</span></div>
            <span class="stat-label">Inactive</span>
          </div>
          <div class="stat-value" id="inactiveCount">—</div>
          <div class="stat-sub" id="inactiveSub">—</div>
        </div>
        <div class="stat-card blue fade-in">
          <div class="stat-header">
            <div class="stat-icon"><span class="material-symbols-outlined">swap_horiz</span></div>
            <span class="stat-label">Requests</span>
          </div>
          <div class="stat-value" id="totalReqs">—</div>
          <div class="stat-sub" id="totalReqsSub">— ok / — fail</div>
        </div>
        <div class="stat-card brand fade-in">
          <div class="stat-header">
            <div class="stat-icon"><span class="material-symbols-outlined">trending_up</span></div>
            <span class="stat-label">Success Rate</span>
          </div>
          <div class="stat-value" id="successRate">—</div>
          <div class="stat-sub" id="successRateSub">—</div>
        </div>
        <div class="stat-card yellow fade-in">
          <div class="stat-header">
            <div class="stat-icon"><span class="material-symbols-outlined">speed</span></div>
            <span class="stat-label">Avg Latency</span>
          </div>
          <div class="stat-value" id="avgLatency">—</div>
          <div class="stat-sub" id="avgLatencySub">—</div>
        </div>
      </div>

      <!-- Proxy Table -->
      <div class="table-card slide-in-top">
        <div class="table-header">
          <h3><span class="material-symbols-outlined">dns</span> Proxy Pool</h3>
          <span class="count" id="poolCount">— proxies</span>
        </div>
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
              <th>Latency</th>
            </tr>
          </thead>
          <tbody id="proxyTable">
            <tr><td colspan="10"><div class="empty-state"><span class="material-symbols-outlined">hourglass_empty</span><div>Loading…</div></div></td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="footer">
      Proxy Orchestrator · <a href="https://github.com/lunaticbugbear/proxy-orchestrator" target="_blank">GitHub</a> · Auto-refresh 3s
    </div>
  </div>
</div>

<script>
const REFRESH_MS = 3000;

function fmt(n) {
  if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
  if (n >= 1e3) return (n/1e3).toFixed(1)+'k';
  return String(n);
}
function rateCls(r) { return r >= 90 ? 'green' : r >= 60 ? 'yellow' : 'red'; }
function latCls(ms) { return ms < 500 ? 'fast' : ms < 1500 ? 'moderate' : 'slow'; }

async function fetchData() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    updateUI(data);
  } catch(e) {
    document.getElementById('liveDot').className = 'dot dead';
    document.getElementById('lastUpdate').textContent = 'Connection error';
    document.getElementById('sidebarStatus').textContent = 'Disconnected';
  }
}

function updateUI(data) {
  const pool = data.pool;
  const proxies = data.proxies || [];

  document.getElementById('activeCount').textContent = pool.active;
  document.getElementById('activeSub').textContent = 'of ' + pool.total + ' total';
  document.getElementById('inactiveCount').textContent = pool.inactive;
  document.getElementById('inactiveSub').textContent = pool.inactive === 0 ? 'all healthy' : 'needs attention';
  document.getElementById('totalReqs').textContent = fmt(pool.total_requests);
  document.getElementById('totalReqsSub').textContent = fmt(pool.total_success)+' ok / '+fmt(pool.total_fail)+' fail';
  document.getElementById('successRate').textContent = pool.overall_success_rate + '%';
  document.getElementById('successRateSub').textContent = pool.overall_success_rate >= 90 ? 'healthy' : 'degraded';
  document.getElementById('avgLatency').textContent = pool.avg_latency_ms + 'ms';
  document.getElementById('avgLatencySub').textContent = pool.avg_latency_ms < 500 ? 'fast' : pool.avg_latency_ms < 1500 ? 'moderate' : 'slow';
  document.getElementById('poolCount').textContent = pool.total + ' proxies';

  const tbody = document.getElementById('proxyTable');
  if (proxies.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10"><div class="empty-state"><span class="material-symbols-outlined">inbox</span><div>No proxies registered. Add via config.yaml or add_proxy().</div></div></td></tr>';
  } else {
    tbody.innerHTML = proxies.map(p => {
      const total = p.success_count + p.fail_count;
      const rate = total > 0 ? (p.success_count / total * 100).toFixed(1) : '100.0';
      const rc = rateCls(parseFloat(rate));
      const statusPill = p.active
        ? '<span class="status-pill up"><span class="dot"></span>UP</span>'
        : '<span class="status-pill down"><span class="dot"></span>DOWN</span>';
      const healthBar = '<span class="health-bar"><span class="bar"><span class="fill '+rc+'" style="width:'+rate+'%"></span></span><span class="pct">'+rate+'%</span></span>';
      const lat = p.avg_latency_ms > 0
        ? '<span class="latency '+latCls(p.avg_latency_ms)+'">'+p.avg_latency_ms.toFixed(0)+'ms</span>'
        : '<span class="latency">—</span>';
      return '<tr>'
        + '<td>'+statusPill+'</td>'
        + '<td style="font-weight:600">'+p.host+':'+p.port+'</td>'
        + '<td><span class="tag region">'+p.region+'</span></td>'
        + '<td><span class="tag protocol">'+p.protocol+'</span></td>'
        + '<td style="color:var(--text-muted)">'+p.weight.toFixed(3)+'</td>'
        + '<td style="color:var(--success)">'+p.success_count+'</td>'
        + '<td style="color:var(--danger)">'+p.fail_count+'</td>'
        + '<td>'+rate+'%</td>'
        + '<td>'+healthBar+'</td>'
        + '<td>'+lat+'</td>'
        + '</tr>';
    }).join('');
  }

  const now = new Date();
  document.getElementById('lastUpdate').textContent = 'Updated ' + now.toLocaleTimeString('en-US',{hour12:false});
  document.getElementById('liveDot').className = 'dot live';
  document.getElementById('sidebarStatus').textContent = 'Connected';
}

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

