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


@app.get("/api/request-log")
async def api_request_log(limit: int = 50):
    """Recent requests across all proxies (activity feed)."""
    orch = get_orch()
    return JSONResponse(orch.db.get_recent_requests(limit))


@app.get("/api/request-log/{proxy_id}")
async def api_proxy_request_log(proxy_id: int, limit: int = 100):
    """Recent requests for a specific proxy (detail panel)."""
    orch = get_orch()
    return JSONResponse(orch.db.get_proxy_requests(proxy_id, limit))


@app.get("/api/trends")
async def api_trends(hours: int = 24):
    """Aggregated trends: hourly buckets + region distribution."""
    orch = get_orch()
    return JSONResponse(orch.db.get_trends(hours))


# ─── Dashboard HTML (9router design language) ─────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTML_PAGE


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Proxy Orchestrator</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/icon?family=Material+Symbols+Outlined" rel="stylesheet">
<style>
:root{--brand-500:#E56A4A;--brand-600:#cc5236;--brand-700:#a64027;--brand-300:#ee8d6a;--brand-400:#ea7855;--bg:#1a1a1a;--bg-alt:#1F1F1E;--surface:#262626;--surface-2:#303030;--surface-3:#3a3a3a;--sidebar:rgba(30,30,30,0.85);--border:#333;--border-subtle:#2a2a2a;--text-main:#ededed;--text-muted:#9ca3af;--text-subtle:#6b7280;--danger:#ef4444;--success:#22c55e;--warning:#fbbf24;--info:#60a5fa;--radius:10px;--radius-lg:14px;--shadow-soft:0 1px 2px 0 rgba(0,0,0,0.3);--shadow-warm:0 2px 12px -2px rgba(229,106,74,0.25);--shadow-elev:inset 0 1px 0 0 rgba(255,255,255,0.06),0 1px 2px rgba(0,0,0,0.4),0 16px 48px -8px rgba(0,0,0,0.55);--font-sans:'Inter',-apple-system,BlinkMacSystemFont,system-ui,sans-serif}
.light{--bg:#FDFAF6;--bg-alt:#F7F3EE;--surface:#fff;--surface-2:#f4f4f5;--surface-3:#e7e7e9;--sidebar:rgba(244,241,236,0.85);--border:#e5e7eb;--border-subtle:#f1f1f3;--text-main:#0a0a0a;--text-muted:#6B7280;--text-subtle:#9CA3AF;--danger:#cf222e;--success:#10B981;--warning:#F59E0B;--info:#3B82F6;--shadow-elev:inset 0 1px 0 0 rgba(255,255,255,0.8),0 1px 2px rgba(15,23,42,0.04),0 12px 36px -8px rgba(15,23,42,0.10)}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text-main);font-family:var(--font-sans);-webkit-font-smoothing:antialiased;font-size:14px;line-height:1.5;min-height:100vh}
::selection{background:rgba(229,106,74,0.3);color:var(--brand-300)}
.material-symbols-outlined{font-family:'Material Symbols Outlined',sans-serif;font-weight:400;font-style:normal;font-size:20px;line-height:1;display:inline-block;-webkit-font-smoothing:antialiased}
.app-layout{display:flex;min-height:100vh}
.sidebar{width:260px;flex-shrink:0;border-right:1px solid var(--border-subtle);background:var(--sidebar);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);display:flex;flex-direction:column}
.traffic-lights{display:flex;gap:8px;padding:18px 24px 4px}
.traffic-lights span{width:12px;height:12px;border-radius:50%}
.traffic-lights .red{background:#FF5F56}.traffic-lights .yellow{background:#FFBD2E}.traffic-lights .green{background:#27C93F}
.logo-section{padding:16px 24px;display:flex;align-items:center;gap:12px}
.logo-icon{width:36px;height:36px;border-radius:var(--radius);background:linear-gradient(135deg,var(--brand-500),var(--brand-700));box-shadow:var(--shadow-warm);display:flex;align-items:center;justify-content:center}
.logo-icon .material-symbols-outlined{color:#fff;font-size:20px}
.logo-text h1{font-size:16px;font-weight:600;letter-spacing:-0.3px}
.logo-text span{font-size:11px;color:var(--text-muted)}
.nav-section{flex:1;padding:8px 16px;overflow-y:auto}
.nav-section::-webkit-scrollbar{width:4px}.nav-section::-webkit-scrollbar-thumb{background:rgba(156,163,175,0.2);border-radius:20px}
.nav-label{font-size:11px;font-weight:600;color:var(--text-subtle);text-transform:uppercase;letter-spacing:0.5px;padding:12px 12px 6px}
.nav-item{display:flex;align-items:center;gap:12px;padding:7px 12px;border-radius:8px;color:var(--text-muted);transition:all .15s;cursor:pointer;font-size:13px;font-weight:500;margin-bottom:2px}
.nav-item:hover{background:var(--surface-2);color:var(--text-main)}
.nav-item.active{background:rgba(229,106,74,0.1);color:var(--brand-500)}
.nav-item.active .material-symbols-outlined{font-variation-settings:'FILL' 1}
.nav-item .material-symbols-outlined{font-size:18px}
.sidebar-footer{padding:12px 16px;border-top:1px solid var(--border-subtle);display:flex;justify-content:space-between;align-items:center}
.sidebar-footer .badge{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--text-subtle)}
.sidebar-footer .badge .dot{width:6px;height:6px;border-radius:50%;background:var(--success);animation:pulse 2s infinite}
.theme-toggle{background:none;border:none;cursor:pointer;color:var(--text-muted);padding:4px;border-radius:6px;transition:all .15s}
.theme-toggle:hover{background:var(--surface-2);color:var(--text-main)}
.main-content{flex:1;overflow-x:hidden}
.topbar{display:flex;justify-content:space-between;align-items:center;padding:16px 32px;border-bottom:1px solid var(--border-subtle);background:var(--sidebar);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
.topbar h2{font-size:18px;font-weight:600;letter-spacing:-0.5px}
.topbar .meta{display:flex;align-items:center;gap:16px}
.topbar .meta-item{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-muted)}
.topbar .meta-item .dot{width:8px;height:8px;border-radius:50%}
.topbar .meta-item .dot.live{background:var(--success);animation:pulse 2s infinite}
.topbar .meta-item .dot.dead{background:var(--danger)}
.content-area{padding:24px 32px}
.dot-grid{background-color:var(--bg);background-image:radial-gradient(circle at 15% 20%,rgba(229,106,74,0.12) 0%,transparent 40%),radial-gradient(circle at 85% 80%,rgba(229,106,74,0.06) 0%,transparent 40%)}
.light .dot-grid{background-image:radial-gradient(circle at 15% 20%,rgba(229,106,74,0.10) 0%,transparent 40%),radial-gradient(circle at 85% 80%,rgba(229,106,74,0.06) 0%,transparent 40%)}
.cards-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px}
.stat-card{background:var(--surface);border-radius:var(--radius-lg);box-shadow:var(--shadow-elev);padding:20px;transition:transform .2s,box-shadow .2s;position:relative;overflow:hidden;cursor:pointer}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(229,106,74,0.3),transparent)}
.stat-card:hover{transform:translateY(-2px)}
.stat-card .stat-header{display:flex;align-items:center;gap:8px;margin-bottom:12px}
.stat-card .stat-icon{width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center}
.stat-card .stat-icon .material-symbols-outlined{font-size:18px}
.stat-card .stat-label{font-size:12px;font-weight:500;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.3px}
.stat-card .stat-value{font-size:28px;font-weight:700;letter-spacing:-1px;line-height:1.2}
.stat-card .stat-sub{font-size:11px;color:var(--text-subtle);margin-top:4px}
.stat-card .spark{margin-top:8px;height:24px}
.stat-card.green .stat-icon{background:rgba(34,197,94,0.12)}.stat-card.green .stat-icon .material-symbols-outlined{color:var(--success)}.stat-card.green .stat-value{color:var(--success)}
.stat-card.red .stat-icon{background:rgba(239,68,68,0.12)}.stat-card.red .stat-icon .material-symbols-outlined{color:var(--danger)}.stat-card.red .stat-value{color:var(--danger)}
.stat-card.blue .stat-icon{background:rgba(96,165,250,0.12)}.stat-card.blue .stat-icon .material-symbols-outlined{color:var(--info)}.stat-card.blue .stat-value{color:var(--info)}
.stat-card.brand .stat-icon{background:rgba(229,106,74,0.12)}.stat-card.brand .stat-icon .material-symbols-outlined{color:var(--brand-500)}.stat-card.brand .stat-value{color:var(--brand-500)}
.stat-card.yellow .stat-icon{background:rgba(251,191,36,0.12)}.stat-card.yellow .stat-icon .material-symbols-outlined{color:var(--warning)}.stat-card.yellow .stat-value{color:var(--warning)}
.table-card{background:var(--surface);border-radius:var(--radius-lg);box-shadow:var(--shadow-elev);overflow:hidden;margin-bottom:24px}
.table-header{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid var(--border-subtle)}
.table-header h3{font-size:14px;font-weight:600;display:flex;align-items:center;gap:8px}
.table-header h3 .material-symbols-outlined{font-size:18px;color:var(--brand-500)}
.table-header .tools{display:flex;align-items:center;gap:12px}
.table-header .count{font-size:11px;color:var(--text-muted);background:var(--surface-2);padding:3px 10px;border-radius:12px}
.search-box{position:relative}
.search-box input{background:var(--surface-2);border:1px solid var(--border-subtle);border-radius:8px;padding:6px 12px 6px 32px;font-size:12px;color:var(--text-main);width:160px;outline:none;transition:border-color .15s}
.search-box input:focus{border-color:var(--brand-500)}
.search-box .material-symbols-outlined{position:absolute;left:8px;top:50%;transform:translateY(-50%);font-size:16px;color:var(--text-subtle)}
.region-filter{background:var(--surface-2);border:1px solid var(--border-subtle);border-radius:8px;padding:6px 10px;font-size:12px;color:var(--text-main);outline:none;cursor:pointer}
table{width:100%;border-collapse:collapse}
thead th{text-align:left;padding:10px 20px;font-size:11px;font-weight:600;color:var(--text-subtle);text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid var(--border-subtle);white-space:nowrap}
tbody td{padding:12px 20px;border-bottom:1px solid var(--border-subtle);font-size:13px;white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
tbody tr{transition:background .15s;cursor:pointer}
tbody tr:hover{background:var(--surface-2)}
.status-pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600}
.status-pill.up{background:rgba(34,197,94,0.12);color:var(--success)}
.status-pill.down{background:rgba(239,68,68,0.12);color:var(--danger)}
.status-pill .dot{width:6px;height:6px;border-radius:50%}
.status-pill.up .dot{background:var(--success)}.status-pill.down .dot{background:var(--danger)}
.tag{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:500}
.tag.region{background:rgba(96,165,250,0.12);color:var(--info)}
.tag.protocol{background:var(--surface-3);color:var(--text-muted)}
.health-bar{display:inline-flex;align-items:center;gap:8px}
.health-bar .bar{width:50px;height:5px;background:var(--surface-3);border-radius:3px;overflow:hidden}
.health-bar .fill{height:100%;border-radius:3px;transition:width .5s}
.health-bar .fill.green{background:var(--success)}.health-bar .fill.yellow{background:var(--warning)}.health-bar .fill.red{background:var(--danger)}
.health-bar .pct{font-size:11px;color:var(--text-muted)}
.latency{font-size:12px;color:var(--text-muted)}
.latency.fast{color:var(--success)}.latency.moderate{color:var(--warning)}.latency.slow{color:var(--danger)}
.empty-state{text-align:center;padding:48px 20px;color:var(--text-subtle)}
.empty-state .material-symbols-outlined{font-size:48px;color:var(--surface-3);margin-bottom:12px}
/* Detail panel */
.detail-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);backdrop-filter:blur(4px);z-index:40;opacity:0;pointer-events:none;transition:opacity .2s}
.detail-overlay.open{opacity:1;pointer-events:auto}
.detail-panel{position:fixed;top:0;right:0;width:480px;max-width:90vw;height:100vh;background:var(--bg);border-left:1px solid var(--border);box-shadow:var(--shadow-elev);z-index:50;transform:translateX(100%);transition:transform .3s cubic-bezier(0.22,1,0.36,1);overflow-y:auto}
.detail-panel.open{transform:translateX(0)}
.detail-header{display:flex;justify-content:space-between;align-items:center;padding:20px 24px;border-bottom:1px solid var(--border-subtle)}
.detail-header h3{font-size:16px;font-weight:600;display:flex;align-items:center;gap:8px}
.detail-header .close-btn{background:none;border:none;cursor:pointer;color:var(--text-muted);padding:4px;border-radius:6px}
.detail-header .close-btn:hover{background:var(--surface-2);color:var(--text-main)}
.detail-body{padding:20px 24px}
.detail-section{margin-bottom:24px}
.detail-section h4{font-size:12px;font-weight:600;color:var(--text-subtle);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px}
.detail-stats{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.detail-stat{background:var(--surface);border-radius:var(--radius);padding:12px}
.detail-stat .label{font-size:11px;color:var(--text-muted);margin-bottom:4px}
.detail-stat .value{font-size:16px;font-weight:600}
.log-table{width:100%;border-collapse:collapse}
.log-table th{text-align:left;padding:6px 8px;font-size:10px;font-weight:600;color:var(--text-subtle);text-transform:uppercase;border-bottom:1px solid var(--border-subtle)}
.log-table td{padding:6px 8px;font-size:12px;border-bottom:1px solid var(--border-subtle);font-family:monospace}
.log-table .ok{color:var(--success)}.log-table .err{color:var(--danger)}
/* Activity feed */
.feed-card{background:var(--surface);border-radius:var(--radius-lg);box-shadow:var(--shadow-elev);overflow:hidden}
.feed-list{max-height:300px;overflow-y:auto}
.feed-list::-webkit-scrollbar{width:4px}.feed-list::-webkit-scrollbar-thumb{background:rgba(156,163,175,0.2);border-radius:20px}
.feed-item{display:flex;align-items:center;gap:12px;padding:10px 20px;border-bottom:1px solid var(--border-subtle);font-size:13px;animation:fadeIn .3s ease-out}
.feed-item:last-child{border-bottom:none}
.feed-item .feed-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.feed-item .feed-dot.ok{background:var(--success)}.feed-item .feed-dot.fail{background:var(--danger)}
.feed-item .feed-host{flex:1;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.feed-item .feed-status{font-size:11px;color:var(--text-muted);font-family:monospace}
.feed-item .feed-time{font-size:11px;color:var(--text-subtle);flex-shrink:0}
/* Charts */
.chart-card{background:var(--surface);border-radius:var(--radius-lg);box-shadow:var(--shadow-elev);padding:20px;margin-bottom:24px}
.chart-card h3{font-size:14px;font-weight:600;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.chart-card h3 .material-symbols-outlined{font-size:18px;color:var(--brand-500)}
.chart-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px}
.bar-chart{display:flex;align-items:flex-end;gap:4px;height:120px;padding-top:8px}
.bar-chart .bar-col{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;height:100%;justify-content:flex-end}
.bar-chart .bar{width:100%;border-radius:3px 3px 0 0;transition:height .5s;min-height:2px}
.bar-chart .bar.ok{background:var(--success);opacity:0.8}
.bar-chart .bar.fail{background:var(--danger);opacity:0.8}
.bar-chart .bar-label{font-size:9px;color:var(--text-subtle)}
.donut-container{display:flex;align-items:center;gap:24px}
.donut-legend{display:flex;flex-direction:column;gap:8px}
.donut-legend-item{display:flex;align-items:center;gap:8px;font-size:12px}
.donut-legend-item .swatch{width:12px;height:12px;border-radius:3px}
/* Toast */
.toast-container{position:fixed;bottom:24px;right:24px;z-index:100;display:flex;flex-direction:column;gap:8px}
.toast{background:var(--surface);border-radius:var(--radius);box-shadow:var(--shadow-elev);padding:12px 16px;display:flex;align-items:center;gap:10px;font-size:13px;animation:slideInRight .3s cubic-bezier(0.22,1,0.36,1);max-width:360px}
.toast.success{border-left:3px solid var(--success)}
.toast.error{border-left:3px solid var(--danger)}
.toast.info{border-left:3px solid var(--info)}
.toast .material-symbols-outlined{font-size:18px}
.toast.success .material-symbols-outlined{color:var(--success)}
.toast.error .material-symbols-outlined{color:var(--danger)}
.toast.info .material-symbols-outlined{color:var(--info)}
/* Views */
.view{display:none}.view.active{display:block}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes slideInRight{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
@keyframes slideInTop{from{transform:translateY(-8px);opacity:0}to{transform:translateY(0);opacity:1}}
.fade-in{animation:fadeIn .3s ease-out forwards}
.slide-in-top{animation:slideInTop .2s cubic-bezier(0.22,1,0.36,1) forwards}
.footer{padding:16px 32px;text-align:center;font-size:12px;color:var(--text-subtle)}
.footer a{color:var(--brand-400);text-decoration:none}
.footer a:hover{color:var(--brand-300)}
</style>
</head>
<body>
<div class="app-layout">
  <aside class="sidebar">
    <div class="traffic-lights"><span class="red"></span><span class="yellow"></span><span class="green"></span></div>
    <div class="logo-section">
      <div class="logo-icon"><span class="material-symbols-outlined">hub</span></div>
      <div class="logo-text"><h1>Proxy Orchestrator</h1><span>v1.0.0</span></div>
    </div>
    <nav class="nav-section">
      <div class="nav-label">Monitoring</div>
      <div class="nav-item active" data-view="overview"><span class="material-symbols-outlined">dashboard</span><span>Overview</span></div>
      <div class="nav-item" data-view="proxies"><span class="material-symbols-outlined">dns</span><span>Proxies</span></div>
      <div class="nav-item" data-view="analytics"><span class="material-symbols-outlined">bar_chart</span><span>Analytics</span></div>
      <div class="nav-item" data-view="activity"><span class="material-symbols-outlined">stream</span><span>Activity Feed</span></div>
      <div class="nav-label">System</div>
      <div class="nav-item" data-view="settings"><span class="material-symbols-outlined">settings</span><span>Settings</span></div>
      <div class="nav-item" data-view="api"><span class="material-symbols-outlined">terminal</span><span>API Docs</span></div>
    </nav>
    <div class="sidebar-footer">
      <div class="badge"><span class="dot"></span><span id="sidebarStatus">Connected</span></div>
      <button class="theme-toggle" id="themeToggle" title="Toggle theme"><span class="material-symbols-outlined" id="themeIcon">light_mode</span></button>
    </div>
  </aside>

  <div class="main-content dot-grid">
    <div class="topbar">
      <h2 id="pageTitle">Overview</h2>
      <div class="meta">
        <div class="meta-item"><span class="dot live" id="liveDot"></span><span id="lastUpdate">Connecting...</span></div>
      </div>
    </div>
    <div class="content-area">

      <!-- OVERVIEW VIEW -->
      <div class="view active" id="view-overview">
        <div class="cards-grid" id="cards">
          <div class="stat-card green fade-in" onclick="navigate('proxies')">
            <div class="stat-header"><div class="stat-icon"><span class="material-symbols-outlined">check_circle</span></div><span class="stat-label">Active</span></div>
            <div class="stat-value" id="activeCount">-</div><div class="stat-sub" id="activeSub">of - total</div>
          </div>
          <div class="stat-card red fade-in" onclick="navigate('proxies')">
            <div class="stat-header"><div class="stat-icon"><span class="material-symbols-outlined">cancel</span></div><span class="stat-label">Inactive</span></div>
            <div class="stat-value" id="inactiveCount">-</div><div class="stat-sub" id="inactiveSub">-</div>
          </div>
          <div class="stat-card blue fade-in" onclick="navigate('analytics')">
            <div class="stat-header"><div class="stat-icon"><span class="material-symbols-outlined">swap_horiz</span></div><span class="stat-label">Requests</span></div>
            <div class="stat-value" id="totalReqs">-</div><div class="stat-sub" id="totalReqsSub">- ok / - fail</div>
          </div>
          <div class="stat-card brand fade-in" onclick="navigate('analytics')">
            <div class="stat-header"><div class="stat-icon"><span class="material-symbols-outlined">trending_up</span></div><span class="stat-label">Success Rate</span></div>
            <div class="stat-value" id="successRate">-</div><div class="stat-sub" id="successRateSub">-</div>
          </div>
          <div class="stat-card yellow fade-in" onclick="navigate('analytics')">
            <div class="stat-header"><div class="stat-icon"><span class="material-symbols-outlined">speed</span></div><span class="stat-label">Avg Latency</span></div>
            <div class="stat-value" id="avgLatency">-</div><div class="stat-sub" id="avgLatencySub">-</div>
          </div>
        </div>
        <div class="table-card slide-in-top">
          <div class="table-header">
            <h3><span class="material-symbols-outlined">dns</span> Proxy Pool</h3>
            <div class="tools"><span class="count" id="poolCount">- proxies</span></div>
          </div>
          <div id="overviewTable"></div>
        </div>
        <div class="chart-row">
          <div class="chart-card">
            <h3><span class="material-symbols-outlined">bar_chart</span> Request Volume (24h)</h3>
            <div id="trendChart"></div>
          </div>
          <div class="chart-card">
            <h3><span class="material-symbols-outlined">donut_large</span> Region Distribution</h3>
            <div id="regionChart"></div>
          </div>
        </div>
      </div>

      <!-- PROXIES VIEW -->
      <div class="view" id="view-proxies">
        <div class="table-card">
          <div class="table-header">
            <h3><span class="material-symbols-outlined">dns</span> All Proxies</h3>
            <div class="tools">
              <div class="search-box"><span class="material-symbols-outlined">search</span><input type="text" id="searchInput" placeholder="Search host..." oninput="filterTable()"></div>
              <select class="region-filter" id="regionFilter" onchange="filterTable()"><option value="">All Regions</option></select>
              <span class="count" id="poolCount2">- proxies</span>
            </div>
          </div>
          <table>
            <thead><tr><th>Status</th><th>Host:Port</th><th>Region</th><th>Protocol</th><th>Weight</th><th>Success</th><th>Fail</th><th>Rate</th><th>Health</th><th>Latency</th></tr></thead>
            <tbody id="proxyTable"></tbody>
          </table>
        </div>
      </div>

      <!-- ANALYTICS VIEW -->
      <div class="view" id="view-analytics">
        <div class="cards-grid" id="analyticsCards">
          <div class="stat-card brand"><div class="stat-header"><div class="stat-icon"><span class="material-symbols-outlined">trending_up</span></div><span class="stat-label">Total Success</span></div><div class="stat-value" id="aTotalSuccess">-</div></div>
          <div class="stat-card red"><div class="stat-header"><div class="stat-icon"><span class="material-symbols-outlined">trending_down</span></div><span class="stat-label">Total Failures</span></div><div class="stat-value" id="aTotalFail">-</div></div>
          <div class="stat-card green"><div class="stat-header"><div class="stat-icon"><span class="material-symbols-outlined">percent</span></div><span class="stat-label">Overall Rate</span></div><div class="stat-value" id="aRate">-</div></div>
          <div class="stat-card yellow"><div class="stat-header"><div class="stat-icon"><span class="material-symbols-outlined">timer</span></div><span class="stat-label">Avg Latency</span></div><div class="stat-value" id="aLatency">-</div></div>
        </div>
        <div class="chart-card">
          <h3><span class="material-symbols-outlined">bar_chart</span> Hourly Request Trends (24h)</h3>
          <div id="trendChart2"></div>
        </div>
        <div class="chart-card">
          <h3><span class="material-symbols-outlined">donut_large</span> Region Distribution</h3>
          <div id="regionChart2"></div>
        </div>
      </div>

      <!-- ACTIVITY VIEW -->
      <div class="view" id="view-activity">
        <div class="feed-card">
          <div class="table-header"><h3><span class="material-symbols-outlined">stream</span> Live Request Feed</h3><span class="count" id="feedCount">- events</span></div>
          <div class="feed-list" id="feedList"><div class="empty-state"><span class="material-symbols-outlined">hourglass_empty</span><div>Loading...</div></div></div>
        </div>
      </div>

      <!-- SETTINGS VIEW -->
      <div class="view" id="view-settings">
        <div class="chart-card">
          <h3><span class="material-symbols-outlined">settings</span> Orchestrator Settings</h3>
          <div id="settingsBody" style="color:var(--text-muted);font-size:13px;line-height:2">Loading...</div>
        </div>
      </div>

      <!-- API VIEW -->
      <div class="view" id="view-api">
        <div class="chart-card">
          <h3><span class="material-symbols-outlined">terminal</span> API Endpoints</h3>
          <div style="font-family:monospace;font-size:12px;line-height:2;color:var(--text-muted)">
            <div><span style="color:var(--success)">GET</span> /api/stats - Pool summary + per-proxy runtime stats</div>
            <div><span style="color:var(--success)">GET</span> /api/db-stats - Historical stats from SQLite (24h)</div>
            <div><span style="color:var(--success)">GET</span> /api/request-log?limit=50 - Recent requests (activity feed)</div>
            <div><span style="color:var(--success)">GET</span> /api/request-log/{proxy_id} - Per-proxy request history</div>
            <div><span style="color:var(--success)">GET</span> /api/health-log/{proxy_id} - Health check history</div>
            <div><span style="color:var(--success)">GET</span> /api/trends?hours=24 - Hourly trends + region distribution</div>
          </div>
        </div>
      </div>

    </div>
    <div class="footer">Proxy Orchestrator - <a href="https://github.com/lunaticbugbear/proxy-orchestrator" target="_blank">GitHub</a> - Auto-refresh 3s</div>
  </div>
</div>

<!-- Detail Panel -->
<div class="detail-overlay" id="detailOverlay" onclick="closeDetail()"></div>
<div class="detail-panel" id="detailPanel">
  <div class="detail-header">
    <h3><span class="material-symbols-outlined">dns</span> <span id="detailTitle">Proxy Detail</span></h3>
    <button class="close-btn" onclick="closeDetail()"><span class="material-symbols-outlined">close</span></button>
  </div>
  <div class="detail-body" id="detailBody"></div>
</div>

<!-- Toast Container -->
<div class="toast-container" id="toastContainer"></div>

<script>
const REFRESH=3000;let allProxies=[];let lastReqCount=0;let regions=[];let currentTrends=null;
function fmt(n){if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'k';return String(n)}
function rateCls(r){return r>=90?'green':r>=60?'yellow':'red'}
function latCls(ms){return ms<500?'fast':ms<1500?'moderate':'slow'}
function toast(msg,type){const c=document.getElementById('toastContainer');const t=document.createElement('div');t.className='toast '+type;t.innerHTML='<span class="material-symbols-outlined">'+(type==='success'?'check_circle':type==='error'?'error':'info')+'</span><span>'+msg+'</span>';c.appendChild(t);setTimeout(()=>{t.style.opacity='0';t.style.transition='opacity .3s';setTimeout(()=>t.remove(),300)},4000)}
function navigate(view){document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));document.getElementById('view-'+view).classList.add('active');document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));document.querySelector('[data-view="'+view+'"]').classList.add('active');const titles={overview:'Overview',proxies:'Proxies',analytics:'Analytics',activity:'Activity Feed',settings:'Settings',api:'API Docs'};document.getElementById('pageTitle').textContent=titles[view];if(view==='analytics')fetchTrends();if(view==='activity')fetchFeed()}
function buildTable(proxies,tbodyId){
  const tb=document.getElementById(tbodyId)||document.getElementById('proxyTable');
  if(!proxies||proxies.length===0){tb.innerHTML='<tr><td colspan="10"><div class="empty-state"><span class="material-symbols-outlined">inbox</span><div>No proxies registered</div></div></td></tr>';return}
  tb.innerHTML=proxies.map(p=>{
    const total=p.success_count+p.fail_count;const rate=total>0?(p.success_count/total*100).toFixed(1):'100.0';const rc=rateCls(parseFloat(rate));
    const sp=p.active?'<span class="status-pill up"><span class="dot"></span>UP</span>':'<span class="status-pill down"><span class="dot"></span>DOWN</span>';
    const hb='<span class="health-bar"><span class="bar"><span class="fill '+rc+'" style="width:'+rate+'%"></span></span><span class="pct">'+rate+'%</span></span>';
    const lat=p.avg_latency_ms>0?'<span class="latency '+latCls(p.avg_latency_ms)+'">'+p.avg_latency_ms.toFixed(0)+'ms</span>':'<span class="latency">-</span>';
    return '<tr onclick="openDetail('+p.id+')">'+'<td>'+sp+'</td>'+'<td style="font-weight:600">'+p.host+':'+p.port+'</td>'+'<td><span class="tag region">'+p.region+'</span></td>'+'<td><span class="tag protocol">'+p.protocol+'</span></td>'+'<td style="color:var(--text-muted)">'+p.weight.toFixed(3)+'</td>'+'<td style="color:var(--success)">'+p.success_count+'</td>'+'<td style="color:var(--danger)">'+p.fail_count+'</td>'+'<td>'+rate+'%</td>'+'<td>'+hb+'</td>'+'<td>'+lat+'</td>'+'</tr>'
  }).join('')
}
function renderOverviewTable(){const tb=document.getElementById('overviewTable');tb.innerHTML='<table><thead><tr><th>Status</th><th>Host:Port</th><th>Region</th><th>Protocol</th><th>Weight</th><th>Success</th><th>Fail</th><th>Rate</th><th>Health</th><th>Latency</th></tr></thead><tbody id="ovTb"></tbody></table>';buildTable(allProxies.slice(0,5),'ovTb')}
function filterTable(){const q=document.getElementById('searchInput').value.toLowerCase();const r=document.getElementById('regionFilter').value;const filtered=allProxies.filter(p=>(!q||p.host.includes(q)||String(p.port).includes(q))&&(!r||p.region===r));buildTable(filtered,'proxyTable')}
function updateRegionFilter(){const rs=[...new Set(allProxies.map(p=>p.region))];const sel=document.getElementById('regionFilter');const cur=sel.value;sel.innerHTML='<option value="">All Regions</option>'+rs.map(r=>'<option value="'+r+'"'+(r===cur?' selected':'')+'>'+r+'</option>').join('')}
async function openDetail(id){
  const p=allProxies.find(x=>x.id===id);if(!p)return;
  document.getElementById('detailTitle').textContent=p.host+':'+p.port;
  document.getElementById('detailOverlay').classList.add('open');
  document.getElementById('detailPanel').classList.add('open');
  let html='<div class="detail-section"><div class="detail-stats">'+
    '<div class="detail-stat"><div class="label">Status</div><div class="value" style="color:'+(p.active?'var(--success)':'var(--danger)')+'">'+(p.active?'UP':'DOWN')+'</div></div>'+
    '<div class="detail-stat"><div class="label">Region</div><div class="value">'+p.region+'</div></div>'+
    '<div class="detail-stat"><div class="label">Protocol</div><div class="value">'+p.protocol+'</div></div>'+
    '<div class="detail-stat"><div class="label">Weight</div><div class="value">'+p.weight.toFixed(3)+'</div></div>'+
    '<div class="detail-stat"><div class="label">Success</div><div class="value" style="color:var(--success)">'+p.success_count+'</div></div>'+
    '<div class="detail-stat"><div class="label">Failures</div><div class="value" style="color:var(--danger)">'+p.fail_count+'</div></div>'+
    '<div class="detail-stat"><div class="label">Avg Latency</div><div class="value">'+(p.avg_latency_ms>0?p.avg_latency_ms.toFixed(0)+'ms':'-')+'</div></div>'+
    '<div class="detail-stat"><div class="label">Success Rate</div><div class="value">'+((p.success_count+p.fail_count>0)?(p.success_count/(p.success_count+p.fail_count)*100).toFixed(1):'100.0')+'%</div></div>'+
    '</div></div>';
  document.getElementById('detailBody').innerHTML=html;
  // Fetch request log + health log
  try{
    const[rl,hl]=await Promise.all([fetch('/api/request-log/'+id).then(r=>r.json()),fetch('/api/health-log/'+id).then(r=>r.json())]);
    let h2='<div class="detail-section"><h4>Recent Requests ('+rl.length+')</h4><table class="log-table"><thead><tr><th>Time</th><th>Status</th><th>Latency</th><th>URL</th></tr></thead><tbody>';
    h2+=rl.slice(0,20).map(r=>'<tr><td>'+(r.timestamp||'').slice(11,19)+'</td><td class="'+(r.success?'ok':'err')+'">'+(r.status_code||'ERR')+'</td><td>'+(r.latency_ms?r.latency_ms.toFixed(0)+'ms':'-')+'</td><td style="max-width:180px;overflow:hidden;text-overflow:ellipsis">'+(r.url||'-')+'</td></tr>').join('');
    h2+='</tbody></table></div>';
    h2+='<div class="detail-section"><h4>Health History ('+hl.length+')</h4><table class="log-table"><thead><tr><th>Time</th><th>Status</th><th>Latency</th></tr></thead><tbody>';
    h2+=hl.slice(0,15).map(r=>'<tr><td>'+(r.checked_at||'').slice(11,19)+'</td><td class="'+(r.status==='up'?'ok':'err')+'">'+r.status+'</td><td>'+(r.latency_ms?r.latency_ms.toFixed(0)+'ms':'-')+'</td></tr>').join('');
    h2+='</tbody></table></div>';
    document.getElementById('detailBody').innerHTML+=h2;
  }catch(e){toast('Failed to load detail data','error')}
}
function closeDetail(){document.getElementById('detailOverlay').classList.remove('open');document.getElementById('detailPanel').classList.remove('open')}
async function fetchFeed(){
  try{
    const r=await fetch('/api/request-log?limit=50');const data=await r.json();
    document.getElementById('feedCount').textContent=data.length+' events';
    document.getElementById('feedList').innerHTML=data.length===0?'<div class="empty-state"><span class="material-symbols-outlined">inbox</span><div>No requests yet</div></div>':data.map(r=>
      '<div class="feed-item"><span class="feed-dot '+(r.success?'ok':'fail')+'"></span><span class="feed-host">'+r.host+':'+r.port+' - '+(r.url||'').slice(0,40)+'</span><span class="feed-status">'+(r.status_code||'ERR')+' '+(r.latency_ms?r.latency_ms.toFixed(0)+'ms':'')+'</span><span class="feed-time">'+(r.timestamp||'').slice(11,19)+'</span></div>'
    ).join('')
  }catch(e){}
}
function renderTrendChart(data,containerId){
  const el=document.getElementById(containerId);if(!el)return;
  if(!data||!data.hourly||data.hourly.length===0){el.innerHTML='<div class="empty-state"><span class="material-symbols-outlined">bar_chart</span><div>No trend data yet</div></div>';return}
  const maxVal=Math.max(...data.hourly.map(h=>h.total),1);
  el.innerHTML='<div class="bar-chart">'+data.hourly.map(h=>{
    const okH=(h.successes/h.total*100);const failH=((h.total-h.successes)/h.total*100);
    return '<div class="bar-col"><div class="bar fail" style="height:'+(failH)+'%" title="Fail: '+(h.total-h.successes)+'"></div><div class="bar ok" style="height:'+(okH)+'%" title="OK: '+h.successes+'"></div><div class="bar-label">'+(h.hour||'').slice(11,13)+'</div></div>'
  }).join('')+'</div>'
}
function renderRegionChart(data,containerId){
  const el=document.getElementById(containerId);if(!el)return;
  if(!data||!data.regions||data.regions.length===0){el.innerHTML='<div class="empty-state"><span class="material-symbols-outlined">donut_large</span><div>No region data yet</div></div>';return}
  const colors=['#E56A4A','#60a5fa','#22c55e','#fbbf24','#a855f7','#ec4899','#14b8a6','#f97316'];
  const total=data.regions.reduce((s,r)=>s+r.count,0)||1;
  let acc=0;const segs=[];
  data.regions.forEach((r,i)=>{
    const pct=r.count/total*100;segs.push({pct,color:colors[i%colors.length],region:r.region,count:r.count});acc+=pct
  });
  // SVG donut
  let svg='<svg width="120" height="120" viewBox="0 0 36 36"><circle cx="18" cy="18" r="15.915" fill="none" stroke="var(--surface-3)" stroke-width="3"/>';
  acc=0;
  segs.forEach(s=>{const dash=s.pct;const off=100-acc;svg+='<circle cx="18" cy="18" r="15.915" fill="none" stroke="'+s.color+'" stroke-width="3" stroke-dasharray="'+dash+' '+off+'" stroke-dashoffset="'+(25-off)+'" transform="rotate(-90 18 18)"/>';acc+=dash});
  svg+='</svg>';
  el.innerHTML='<div class="donut-container">'+svg+'<div class="donut-legend">'+segs.map(s=>'<div class="donut-legend-item"><span class="swatch" style="background:'+s.color+'"></span><span>'+s.region+': '+s.count+' ('+s.pct.toFixed(0)+'%)</span></div>').join('')+'</div></div>'
}
async function fetchTrends(){
  try{const r=await fetch('/api/trends?hours=24');const data=await r.json();currentTrends=data;
    renderTrendChart(data,'trendChart');renderTrendChart(data,'trendChart2');
    renderRegionChart(data,'regionChart');renderRegionChart(data,'regionChart2');
  }catch(e){}
}
function updateSettings(){
  document.getElementById('settingsBody').innerHTML=
    '<div><strong>Max Retries:</strong> <span id="setMax">-</span></div>'+
    '<div><strong>Request Timeout:</strong> <span id="setTimeout">-</span>s</div>'+
    '<div><strong>Failure Threshold:</strong> <span id="setThreshold">-</span></div>'+
    '<div><strong>Connector Limit:</strong> <span id="setConn">-</span></div>'+
    '<div><strong>Retry Backoff Base:</strong> <span id="setBackoff">-</span>s</div>'+
    '<div><strong>Total Proxies:</strong> <span id="setProxies">-</span></div>'+
    '<div><strong>Database:</strong> SQLite (WAL mode)</div>'
}
async function fetchData(){
  try{
    const res=await fetch('/api/stats');const data=await res.json();const pool=data.pool;allProxies=data.proxies||[];
    document.getElementById('activeCount').textContent=pool.active;
    document.getElementById('activeSub').textContent='of '+pool.total+' total';
    document.getElementById('inactiveCount').textContent=pool.inactive;
    document.getElementById('inactiveSub').textContent=pool.inactive===0?'all healthy':'needs attention';
    document.getElementById('totalReqs').textContent=fmt(pool.total_requests);
    document.getElementById('totalReqsSub').textContent=fmt(pool.total_success)+' ok / '+fmt(pool.total_fail)+' fail';
    document.getElementById('successRate').textContent=pool.overall_success_rate+'%';
    document.getElementById('successRateSub').textContent=pool.overall_success_rate>=90?'healthy':'degraded';
    document.getElementById('avgLatency').textContent=pool.avg_latency_ms+'ms';
    document.getElementById('avgLatencySub').textContent=pool.avg_latency_ms<500?'fast':pool.avg_latency_ms<1500?'moderate':'slow';
    document.getElementById('poolCount').textContent=pool.total+' proxies';
    document.getElementById('poolCount2').textContent=pool.total+' proxies';
    // Analytics view
    document.getElementById('aTotalSuccess').textContent=fmt(pool.total_success);
    document.getElementById('aTotalFail').textContent=fmt(pool.total_fail);
    document.getElementById('aRate').textContent=pool.overall_success_rate+'%';
    document.getElementById('aLatency').textContent=pool.avg_latency_ms+'ms';
    // Settings
    document.getElementById('setMax')&&((document.getElementById('setMax').textContent='-'),(document.getElementById('setTimeout').textContent='-'),(document.getElementById('setThreshold').textContent='-'),(document.getElementById('setConn').textContent='-'),(document.getElementById('setBackoff').textContent='-'),(document.getElementById('setProxies').textContent=pool.total));
    // Tables
    renderOverviewTable();buildTable(allProxies,'proxyTable');updateRegionFilter();
    // Toast on new requests
    if(lastReqCount>0&&pool.total_requests>lastReqCount){toast(pool.total_requests-lastReqCount+' new request(s)','info')}
    lastReqCount=pool.total_requests;
    // Status
    const now=new Date();document.getElementById('lastUpdate').textContent='Updated '+now.toLocaleTimeString('en-US',{hour12:false});
    document.getElementById('liveDot').className='dot live';document.getElementById('sidebarStatus').textContent='Connected';
  }catch(e){document.getElementById('liveDot').className='dot dead';document.getElementById('lastUpdate').textContent='Connection error';document.getElementById('sidebarStatus').textContent='Disconnected';toast('Connection lost','error')}
}
// Theme toggle
document.getElementById('themeToggle').addEventListener('click',()=>{
  const isDark=!document.documentElement.classList.contains('light');
  if(isDark){document.documentElement.classList.add('light');document.getElementById('themeIcon').textContent='dark_mode'}
  else{document.documentElement.classList.remove('light');document.getElementById('themeIcon').textContent='light_mode'}
});
// Nav clicks
document.querySelectorAll('.nav-item').forEach(n=>n.addEventListener('click',()=>navigate(n.dataset.view)));
// Keyboard: Escape closes detail
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDetail()});
// Init
updateSettings();fetchData();fetchTrends();fetchFeed();
setInterval(fetchData,REFRESH);setInterval(fetchFeed,5000);setInterval(fetchTrends,30000);
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

