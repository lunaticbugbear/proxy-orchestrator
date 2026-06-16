"""
Proxy Orchestrator - Health Checker
Background task that pings all proxies periodically, marks them up/down,
and triggers alerts when the pool drops below threshold.
"""

import asyncio
import time
import logging
import aiohttp

logger = logging.getLogger("proxy_orchestrator.health")


class HealthChecker:
    """
    Background health checker. Runs in an asyncio loop.

    Usage:
        checker = HealthChecker(orchestrator, interval=300, timeout=10,
                                test_url="https://httpbin.org/ip",
                                min_pool_size=3, on_alert=callback)
        asyncio.create_task(checker.run())
    """

    def __init__(self, orchestrator, interval: int = 300, timeout: int = 10,
                 test_url: str = "https://httpbin.org/ip",
                 min_pool_size: int = 3, on_alert=None):
        self.orch = orchestrator
        self.interval = interval
        self.timeout = timeout
        self.test_url = test_url
        self.min_pool_size = min_pool_size
        self.on_alert = on_alert  # callback(message: str)
        self._running = False
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _check_one(self, proxy) -> dict:
        """Check a single proxy. Returns result dict."""
        session = await self._get_session()
        start = time.time()
        try:
            async with session.get(
                self.test_url,
                proxy=proxy.url,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                latency = (time.time() - start) * 1000
                if resp.status == 200:
                    return {"proxy": proxy, "status": "up", "latency_ms": latency}
                else:
                    return {"proxy": proxy, "status": "down", "latency_ms": latency,
                            "error": f"HTTP {resp.status}"}
        except asyncio.TimeoutError:
            latency = (time.time() - start) * 1000
            return {"proxy": proxy, "status": "down", "latency_ms": latency,
                    "error": "timeout"}
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {"proxy": proxy, "status": "down", "latency_ms": latency,
                    "error": str(e)}

    async def check_all(self) -> list[dict]:
        """Check all proxies concurrently."""
        all_proxies = list(self.orch.proxies.values())
        tasks = [self._check_one(p) for p in all_proxies]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        active_count = 0
        down_proxies = []

        for result in results:
            proxy = result["proxy"]
            status = result["status"]

            # Log to DB
            self.orch.db.log_health(proxy.id, status, result.get("latency_ms"))

            if status == "up":
                if not proxy.active:
                    # Proxy recovered!
                    proxy.active = True
                    proxy.fail_count = 0           # reset total fail count on recovery
                    proxy.consecutive_failures = 0  # reset streak so it isn't re-killed instantly
                    logger.info(f"Proxy {proxy.host}:{proxy.port} RECOVERED (latency: {result['latency_ms']:.0f}ms)")
                active_count += 1
            else:
                logger.warning(f"Proxy {proxy.host}:{proxy.port} DOWN: {result.get('error', 'unknown')}")
                down_proxies.append({
                    "host": proxy.host,
                    "port": proxy.port,
                    "error": result.get("error", "unknown"),
                })

                # Mark as inactive in DB
                self.orch.db.set_proxy_active(proxy.id, False)
                proxy.active = False

        logger.info(f"Health check complete: {active_count}/{len(all_proxies)} active")

        # Check threshold
        if active_count < self.min_pool_size and self.on_alert:
            msg = (f"⚠️ Proxy pool alert: only {active_count}/{len(all_proxies)} proxies active "
                   f"(minimum: {self.min_pool_size})\n")
            if down_proxies:
                msg += "Down proxies:\n"
                for dp in down_proxies:
                    msg += f"  - {dp['host']}:{dp['port']} ({dp['error']})\n"
            self.on_alert(msg)

        return results

    async def run(self):
        """Main loop. Runs until stopped."""
        self._running = True
        logger.info(f"Health checker started (interval={self.interval}s, "
                    f"timeout={self.timeout}s, min_pool={self.min_pool_size})")

        while self._running:
            try:
                await self.check_all()
            except Exception as e:
                logger.error(f"Health check error: {e}", exc_info=True)

            await asyncio.sleep(self.interval)

    def stop(self):
        self._running = False

    async def close(self):
        self.stop()
        if self._session and not self._session.closed:
            await self._session.close()
