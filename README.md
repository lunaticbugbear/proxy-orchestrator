# Proxy Orchestrator

Automation at scale butuh proxy management. Point blank.

You can't hit a target from one IP forever — you get blocked. But managing 10+ proxies manually? Tedious and unscalable.

This is a production-grade proxy orchestrator that handles health checks, smart rotation, geo-targeting, sticky sessions, automatic failover, and analytics — all backed by SQLite for full auditability.

## Features

- **Health Check** — Background pinger checks all proxies every 5 minutes. Auto-disables dead proxies, auto-recovers when they come back.
- **Smart Rotation** — Weighted round-robin based on success rate and latency. Bad proxies get less traffic but aren't fully starved (recovery testing).
- **Geo-Targeting** — Route requests through proxies in specific regions.
- **Sticky Sessions** — Same `session_id` always gets the same proxy. Critical for stateful flows (logins, multi-step processes).
- **Automatic Failover** — Proxy A times out? Request silently retries on Proxy B. Caller never knows.
- **Analytics** — Per-proxy success rate, latency, request count. Historical stats stored in SQLite.
- **Webhook Alerts** — Telegram, Discord, Slack, or any HTTP endpoint. Get notified when pool drops below threshold.

## Architecture

```
proxy-orchestrator/
├── core.py        # Orchestrator: proxy selection, rotation, failover, request execution
├── db.py          # SQLite layer: proxy registry, health log, request log
├── health.py      # Background health checker
├── alerting.py    # Webhook alert delivery (Telegram/Discord/Slack)
├── analytics.py   # Reporting & stats
├── dashboard.py   # Web dashboard (FastAPI + embedded HTML/JS)
├── config.yaml    # Configuration (proxies, health check, webhooks)
├── example.py     # Full usage example
├── test_orchestrator.py  # pytest suite (17 tests)
└── requirements.txt
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Edit config.yaml with your proxies
cp config.yaml config.yaml  # then edit

# Run the example
python example.py
```

## Configuration

Edit `config.yaml`:

```yaml
# SQLite database path
database: proxies.db

# Health check settings
health_check:
  interval: 300          # 5 minutes
  timeout: 10
  test_url: "https://httpbin.org/ip"
  min_pool_size: 3       # alert if active proxies < 3

# Webhook alerts (Telegram example)
webhooks:
  - url: "https://api.telegram.org/bot<TOKEN>/sendMessage"
    method: "POST"
    body_template: '{"text": "{message}"}'
    payload:
      chat_id: "<CHAT_ID>"

# Proxy definitions
proxies:
  - host: "geo.iproyal.com"
    port: 12321
    username: "your_user"
    password: "your_pass"
    region: "US"
    protocol: "http"
```

## Usage

### Basic Request

```python
import asyncio
from core import ProxyOrchestrator

async def main():
    orch = ProxyOrchestrator(db_path="proxies.db")
    await orch.load_from_config("config.yaml")

    # Simple GET through a proxy
    resp = await orch.request("GET", "https://httpbin.org/ip")
    if resp and resp.ok:
        data = await resp.json()
        print(f"IP: {data['origin']}")
        print(f"Via: {resp.proxy.host}:{resp.proxy.port}")

    await orch.close()

asyncio.run(main())
```

### Sticky Session

Same `session_id` → same proxy. Essential for multi-step flows (login → action → logout).

```python
# All 3 requests use the same proxy
for i in range(3):
    resp = await orch.request("GET", "https://example.com", session_id="user_123")
    print(f"Request {i}: via {resp.proxy.host}")
```

### Geo-Targeting

```python
# Route through US proxies only
resp = await orch.request("GET", "https://example.com", region="US")
```

### Failover

Failover is automatic. If a proxy fails, the orchestrator retries with a different proxy — up to `max_retries` times. The caller never sees the failure.

```python
orch = ProxyOrchestrator(db_path="proxies.db", max_retries=5)
# If proxy A fails, auto-retry on B, C, D, E...
```

### Health Monitoring

```python
from health import HealthChecker

checker = HealthChecker(
    orchestrator=orch,
    interval=300,         # check every 5 min
    timeout=10,
    min_pool_size=3,      # alert if < 3 active
    on_alert=my_callback, # called with alert message
)

# Run in background
import asyncio
asyncio.create_task(checker.run())
```

### Analytics

```python
from analytics import Analytics

analytics = Analytics(orch)

# Print formatted report
analytics.print_summary(hours=24)

# Export as JSON
analytics.export_json("report.json")

# Top performing proxies
top = analytics.top_proxies(limit=5)
```

## How Weighted Rotation Works

Each proxy has a `weight` calculated from:

```
weight = success_rate × (1 - 0.5 × latency_factor)
```

Where `latency_factor = min(avg_latency / 2000ms, 1.0)`.

- New proxies start with weight 1.0 (optimistic)
- Failed proxies lose weight but keep a floor of 0.05 (recovery testing)
- After 5 consecutive failures with 0 successes, proxy is auto-deactivated
- Health checker can reactivate recovered proxies

## Database Schema

```sql
-- Proxy registry
proxies(id, host, port, username, password, region, protocol, active, created_at)

-- Health check history
health_log(id, proxy_id, status, latency_ms, checked_at)

-- Request log (every request through the orchestrator)
request_log(id, proxy_id, session_id, url, status_code, success, latency_ms, error, timestamp)
```

## Web Dashboard

A real-time dark-themed dashboard (FastAPI + embedded HTML/JS, no build step).

```bash
python dashboard.py
# → http://localhost:8643
```

Features:
- **Stat cards**: active/inactive count, total requests, success rate, avg latency
- **Proxy table**: live status (UP/DOWN), host:port, region, protocol, weight, success/fail counts, health bar, avg latency
- **Auto-refresh**: every 3 seconds
- **API endpoints**: `/api/stats`, `/api/db-stats`, `/api/health-log/{proxy_id}`

To run the dashboard alongside the orchestrator programmatically:

```python
import dashboard
import uvicorn

dashboard.set_orchestrator(orch)
uvicorn.run(dashboard.app, host="0.0.0.0", port=8643)
```

## Tech Stack

- **Python 3.11+**
- **aiohttp** — async HTTP client with proxy support
- **FastAPI + Uvicorn** — web dashboard and REST API
- **SQLite** — zero-config persistence (WAL mode for concurrent reads)
- **PyYAML** — configuration

## Security & Limitations

This is a portfolio/reference implementation. Be aware of the following before
using it with real credentials in production:

- **Proxy credentials are stored in plaintext** in the SQLite database
  (`proxies` table). Anyone with read access to the `.db` file can read your
  proxy usernames and passwords. The database file should be treated as a
  secret: restrict file permissions, keep it out of version control (see
  `.gitignore`), and never commit it.
- **Credentials in `config.yaml` are also plaintext.** Prefer injecting secrets
  via environment variables rather than committing them.
- **No transport encryption for the alert webhooks beyond what the target URL
  provides.** Use HTTPS webhook endpoints only.

### Hardening roadmap

If you adopt this beyond a portfolio context, these are the next steps:

1. **Encrypt credentials at rest** — store proxy passwords using a symmetric
   key (e.g. `cryptography.fernet`) with the key supplied via an environment
   variable, or delegate to a secrets manager (Vault, AWS Secrets Manager,
   Doppler).
2. **Env-based config** — resolve `${ENV_VAR}` references in `config.yaml` at
   load time so secrets never touch disk in plaintext.
3. **File permissions** — `chmod 600` the database file and config on
   POSIX systems; restrict ACLs on Windows.
4. **Audit logging** — the `request_log` table already records usage; pair it
   with `db.prune(retention_days=...)` to enforce a retention policy so logs
   don't grow unbounded or retain sensitive URLs longer than needed.

## License

MIT
