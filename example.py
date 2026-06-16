#!/usr/bin/env python
"""
Proxy Orchestrator - Example Usage
Demonstrates all features: weighted rotation, sticky sessions,
geo-targeting, failover, health checking, and analytics.
"""

import asyncio
import logging
import yaml
from core import ProxyOrchestrator
from health import HealthChecker
from alerting import AlertManager, create_alert_callback
from analytics import Analytics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("example")


async def main():
    # --- 1. Load config ---
    with open("config.yaml", "r") as f:
        cfg = yaml.safe_load(f)

    # --- 2. Initialize orchestrator ---
    orch = ProxyOrchestrator(
        db_path=cfg.get("database", "proxies.db"),
        max_retries=3,
        request_timeout=30,
    )

    # --- 3. Setup alerting ---
    alert_mgr = AlertManager(webhooks=cfg.get("webhooks", []))
    alert_cb = create_alert_callback(alert_mgr)

    # --- 4. Load proxies from config ---
    await orch.load_from_config("config.yaml")

    # Add a couple of test proxies programmatically too
    orch.add_proxy("127.0.0.1", 8888, region="LOCAL", protocol="http")
    orch.add_proxy("127.0.0.1", 9999, region="LOCAL", protocol="http")

    logger.info(f"Total proxies loaded: {len(orch.proxies)}")

    # --- 5. Start health checker in background ---
    hc_cfg = cfg.get("health_check", {})
    checker = HealthChecker(
        orchestrator=orch,
        interval=hc_cfg.get("interval", 300),
        timeout=hc_cfg.get("timeout", 10),
        test_url=hc_cfg.get("test_url", "https://httpbin.org/ip"),
        min_pool_size=hc_cfg.get("min_pool_size", 3),
        on_alert=alert_cb,
    )
    health_task = asyncio.create_task(checker.run())

    # --- 6. Run some test requests ---
    logger.info("=== Sending test requests ===")

    # Simple request with weighted rotation
    resp = await orch.request("GET", "https://httpbin.org/ip")
    if resp and resp.ok:
        data = await resp.json()
        logger.info(f"Response: {data}")
    else:
        logger.warning("Request failed (expected if no real proxies configured)")

    # Sticky session - same proxy for same session_id
    logger.info("=== Sticky session test ===")
    for i in range(3):
        resp = await orch.request("GET", "https://httpbin.org/ip", session_id="user_123")
        if resp:
            logger.info(f"Sticky request {i+1} via {resp.proxy.host}:{resp.proxy.port}")
        else:
            logger.warning(f"Sticky request {i+1} failed")

    # Region targeting
    logger.info("=== Region targeting test ===")
    resp = await orch.request("GET", "https://httpbin.org/ip", region="LOCAL")
    if resp:
        logger.info(f"Region request via {resp.proxy.host}:{resp.proxy.port} (region: {resp.proxy.region})")

    # --- 7. Print analytics ---
    analytics = Analytics(orch)
    analytics.print_summary(hours=1)

    # Show top/worst proxies
    top = analytics.top_proxies(limit=3)
    if top:
        logger.info("Top proxies:")
        for p in top:
            logger.info(f"  {p['host']}:{p['port']} - {p['success_rate']}% success, {p['avg_latency']}ms avg")

    # --- 8. Start dashboard (optional) ---
    # To run the web dashboard alongside the orchestrator:
    #
    #   import dashboard
    #   dashboard.set_orchestrator(orch)
    #   import uvicorn
    #   uvicorn.run(dashboard.app, host="0.0.0.0", port=8643)
    #
    # Or run it standalone:
    #   python dashboard.py  (then add proxies via API or config)

    # --- 9. Cleanup ---
    checker.stop()
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass

    await alert_mgr.close()
    await orch.close()
    await checker.close()

    logger.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())
