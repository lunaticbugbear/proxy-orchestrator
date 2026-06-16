"""
Proxy Orchestrator - Core Engine
Handles proxy selection, rotation, failover, sticky sessions, and request execution.
"""

import asyncio
import aiohttp
import time
import logging
import random
from typing import Optional
from urllib.parse import quote

from db import Database

logger = logging.getLogger("proxy_orchestrator")

# Number of consecutive failures before a proxy is auto-deactivated.
DEFAULT_FAILURE_THRESHOLD = 5


class ProxyResponse:
    """
    Lightweight response wrapper. Body is already read (bytes) so the caller
    can access it after the underlying aiohttp context has closed.
    """

    __slots__ = ("status", "headers", "_body", "proxy")

    def __init__(self, status: int, headers: dict, body: bytes, proxy: "Proxy"):
        self.status = status
        self.headers = headers
        self._body = body
        self.proxy = proxy

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400

    @property
    def content(self) -> bytes:
        return self._body

    async def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    async def json(self):
        import json as _json
        return _json.loads(self._body)

    def __repr__(self):
        return f"<ProxyResponse [{self.status}] via {self.proxy.host}:{self.proxy.port}>"


class Proxy:
    """Represents a single proxy with runtime stats."""

    def __init__(self, proxy_id: int, host: str, port: int, username: str = None,
                 password: str = None, region: str = "unknown", protocol: str = "http",
                 failure_threshold: int = DEFAULT_FAILURE_THRESHOLD):
        self.id = proxy_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.region = region
        self.protocol = protocol
        self.failure_threshold = failure_threshold

        # Runtime state
        self.active = True
        self.success_count = 0
        self.fail_count = 0
        self.consecutive_failures = 0  # reset on every success
        self.weight = 1.0  # higher = more likely to be selected
        self.last_used = 0.0
        self.avg_latency = 0.0
        self._latency_samples = []

    @property
    def url(self) -> str:
        """Build proxy URL for aiohttp. Credentials are percent-encoded so
        special chars (@ : / etc.) in user/pass don't corrupt the URL."""
        auth = ""
        if self.username and self.password:
            user = quote(str(self.username), safe="")
            pwd = quote(str(self.password), safe="")
            auth = f"{user}:{pwd}@"
        return f"{self.protocol}://{auth}{self.host}:{self.port}"

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        if total == 0:
            return 1.0  # optimistic default for new proxies
        return self.success_count / total

    def update_weight(self):
        """Recalculate weight based on success rate and latency."""
        # Weight = success_rate * (1 / (1 + avg_latency_factor))
        latency_factor = min(self.avg_latency / 2000.0, 1.0) if self.avg_latency > 0 else 0
        self.weight = self.success_rate * (1.0 - 0.5 * latency_factor)
        # Floor weight so bad proxies still get occasional traffic for recovery testing
        self.weight = max(self.weight, 0.05)

    def record_success(self, latency_ms: float):
        self.success_count += 1
        self.consecutive_failures = 0  # reset failure streak
        self._latency_samples.append(latency_ms)
        if len(self._latency_samples) > 50:
            self._latency_samples.pop(0)
        self.avg_latency = sum(self._latency_samples) / len(self._latency_samples)
        self.last_used = time.time()
        self.update_weight()

    def record_failure(self):
        self.fail_count += 1
        self.consecutive_failures += 1
        self.last_used = time.time()
        self.update_weight()
        # Auto-deactivate after N CONSECUTIVE failures, regardless of past successes.
        if self.consecutive_failures >= self.failure_threshold:
            if self.active:
                logger.warning(
                    f"Proxy {self.host}:{self.port} auto-deactivated after "
                    f"{self.consecutive_failures} consecutive failures"
                )
            self.active = False

    def __repr__(self):
        return f"<Proxy {self.host}:{self.port} region={self.region} active={self.active} weight={self.weight:.2f}>"


class ProxyOrchestrator:
    """
    Main orchestrator. Manages proxy pool, selection, failover, and request execution.

    Usage:
        orch = ProxyOrchestrator(db_path="proxies.db")
        await orch.load_from_config("config.yaml")

        # Simple request
        resp = await orch.request("GET", "https://httpbin.org/ip")

        # Sticky session (same proxy for same session_id)
        resp = await orch.request("GET", "https://example.com", session_id="user_123")

        # With region targeting
        resp = await orch.request("GET", "https://example.com", region="US")
    """

    def __init__(self, db_path: str = "proxies.db", max_retries: int = 3,
                 request_timeout: int = 30, failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
                 connector_limit: int = 100, retry_backoff_base: float = 0.5):
        self.db = Database(db_path)
        self.proxies: dict[int, Proxy] = {}
        self.max_retries = max_retries
        self.request_timeout = request_timeout
        self.failure_threshold = failure_threshold
        self.connector_limit = connector_limit
        self.retry_backoff_base = retry_backoff_base  # seconds; exponential w/ jitter
        self._sticky_map: dict[str, int] = {}  # session_id -> proxy_id
        self._rr_cursors: dict[str, int] = {}  # per-region round-robin cursor
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=self.connector_limit)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    @staticmethod
    def _is_placeholder(value) -> bool:
        """Detect template/placeholder values that should not be loaded as real config."""
        if value is None:
            return False
        s = str(value)
        markers = ("<", ">", "your_", "example.com", "changeme", "xxxx", "TODO")
        return any(m in s for m in markers)

    async def load_from_config(self, config_path: str):
        """Load proxies from YAML config file. Placeholder/template entries are skipped."""
        import yaml
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)

        proxies_cfg = cfg.get("proxies", []) or []
        loaded, skipped = 0, 0
        for p in proxies_cfg:
            host = p.get("host")
            port = p.get("port")
            # Validate required fields
            if not host or not port:
                logger.warning(f"Skipping proxy with missing host/port: {p}")
                skipped += 1
                continue
            # Skip placeholder/template entries
            if (self._is_placeholder(host) or self._is_placeholder(p.get("username"))
                    or self._is_placeholder(p.get("password"))):
                logger.warning(f"Skipping placeholder proxy entry: {host}:{port}")
                skipped += 1
                continue
            try:
                port = int(port)
            except (ValueError, TypeError):
                logger.warning(f"Skipping proxy with invalid port: {host}:{port}")
                skipped += 1
                continue

            self.add_proxy(
                host=host,
                port=port,
                username=p.get("username"),
                password=p.get("password"),
                region=p.get("region", "unknown"),
                protocol=p.get("protocol", "http"),
            )
            loaded += 1

        logger.info(f"Loaded {loaded} proxies from {config_path} ({skipped} skipped)")

    def add_proxy(self, host: str, port: int, username=None, password=None,
                  region="unknown", protocol="http") -> Proxy:
        """Add a proxy programmatically."""
        proxy_id = self.db.upsert_proxy(host, port, username, password, region, protocol)
        proxy = Proxy(proxy_id, host, port, username, password, region, protocol,
                      failure_threshold=self.failure_threshold)
        self.proxies[proxy_id] = proxy
        return proxy

    def _get_active_proxies(self, region: str = None) -> list[Proxy]:
        """Get all active proxies, optionally filtered by region."""
        active = [p for p in self.proxies.values() if p.active]
        if region:
            active = [p for p in active if p.region == region]
        return active

    def _select_weighted(self, proxies: list[Proxy]) -> Proxy:
        """Select a proxy using weighted random based on success rate + latency."""
        weights = [p.weight for p in proxies]
        total = sum(weights)
        if total == 0:
            return random.choice(proxies)

        r = random.uniform(0, total)
        cumulative = 0
        for proxy, w in zip(proxies, weights):
            cumulative += w
            if r <= cumulative:
                return proxy
        return proxies[-1]

    def _select_round_robin(self, proxies: list[Proxy], region: str = None) -> Proxy:
        """Select proxy using round-robin with a per-region cursor."""
        key = region or "_all_"
        idx = self._rr_cursors.get(key, 0)
        proxy = proxies[idx % len(proxies)]
        self._rr_cursors[key] = idx + 1
        return proxy

    def get_proxy(self, session_id: str = None, region: str = None,
                  strategy: str = "weighted") -> Optional[Proxy]:
        """
        Select a proxy based on strategy.

        Args:
            session_id: If provided, returns the same proxy for the same session (sticky).
            region: Filter proxies by region.
            strategy: "weighted" (default) or "round_robin".

        Returns:
            Proxy object or None if no proxies available.
        """
        # Sticky session: return same proxy for same session_id.
        # If a region is requested, the sticky proxy must also match it,
        # otherwise we re-pin to a proxy in the requested region.
        if session_id and session_id in self._sticky_map:
            proxy_id = self._sticky_map[session_id]
            proxy = self.proxies.get(proxy_id)
            if proxy and proxy.active and (region is None or proxy.region == region):
                return proxy
            else:
                # Sticky proxy died or no longer matches region constraint; re-pin.
                if proxy and region is not None and proxy.region != region:
                    logger.info(
                        f"Sticky session '{session_id}' re-pinned: pinned proxy region "
                        f"'{proxy.region}' != requested '{region}'"
                    )
                del self._sticky_map[session_id]

        active = self._get_active_proxies(region)
        if not active:
            logger.error(f"No active proxies available (region={region})")
            return None

        if strategy == "round_robin":
            proxy = self._select_round_robin(active, region)
        else:
            proxy = self._select_weighted(active)

        if session_id:
            self._sticky_map[session_id] = proxy.id

        return proxy

    async def request(self, method: str, url: str, session_id: str = None,
                      region: str = None, headers: dict = None,
                      json: dict = None, data=None, strategy: str = "weighted",
                      **kwargs) -> Optional["ProxyResponse"]:
        """
        Execute an HTTP request through a proxy with automatic failover.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Target URL
            session_id: Sticky session identifier
            region: Geo-targeting
            headers: Request headers
            json: JSON body
            data: Form/raw body
            strategy: "weighted" or "round_robin"
            **kwargs: Additional aiohttp request kwargs

        Returns:
            ProxyResponse or None if all retries failed
        """
        session = await self._get_session()
        attempted_proxies = set()
        last_error = None

        for attempt in range(self.max_retries):
            # Backoff between retries (not before the first attempt).
            if attempt > 0:
                delay = self.retry_backoff_base * (2 ** (attempt - 1))
                delay += random.uniform(0, delay * 0.25)  # jitter
                await asyncio.sleep(delay)

            proxy = self.get_proxy(session_id=session_id, region=region, strategy=strategy)

            if proxy is None:
                logger.error("No proxy available for request")
                break

            if proxy.id in attempted_proxies:
                # Already tried this one, try to get a different proxy
                active = self._get_active_proxies(region)
                remaining = [p for p in active if p.id not in attempted_proxies]
                if not remaining:
                    logger.error(f"All proxies exhausted after {attempt + 1} attempts")
                    break
                proxy = (self._select_weighted(remaining) if strategy == "weighted"
                         else self._select_round_robin(remaining, region))

            attempted_proxies.add(proxy.id)
            logger.info(f"Attempt {attempt+1}/{self.max_retries}: {method} {url} via {proxy.host}:{proxy.port}")

            start_time = time.time()
            try:
                async with session.request(
                    method, url,
                    proxy=proxy.url,
                    headers=headers,
                    json=json,
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout),
                    **kwargs
                ) as resp:
                    latency_ms = (time.time() - start_time) * 1000

                    # Read body while context is open
                    body = await resp.read()

                    proxy.record_success(latency_ms)
                    self.db.log_request(
                        proxy_id=proxy.id,
                        session_id=session_id,
                        url=url,
                        status_code=resp.status,
                        success=True,
                        latency_ms=latency_ms,
                    )

                    r = ProxyResponse(resp.status, dict(resp.headers), body, proxy)
                    logger.info(f"Success: {resp.status} in {latency_ms:.0f}ms via {proxy.host}:{proxy.port}")
                    return r

            except asyncio.TimeoutError:
                latency_ms = (time.time() - start_time) * 1000
                last_error = "timeout"
                proxy.record_failure()
                self.db.log_request(proxy.id, session_id, url, None, False, latency_ms, "timeout")
                logger.warning(f"Timeout via {proxy.host}:{proxy.port}")
            except aiohttp.ClientError as e:
                latency_ms = (time.time() - start_time) * 1000
                last_error = str(e)
                proxy.record_failure()
                self.db.log_request(proxy.id, session_id, url, None, False, latency_ms, str(e))
                logger.warning(f"ClientError via {proxy.host}:{proxy.port}: {e}")
            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                last_error = str(e)
                proxy.record_failure()
                self.db.log_request(proxy.id, session_id, url, None, False, latency_ms, str(e))
                logger.warning(f"Error via {proxy.host}:{proxy.port}: {e}")

        logger.error(f"All {self.max_retries} attempts failed. Last error: {last_error}")
        return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
        self.db.close()

    def stats(self) -> list[dict]:
        """Get runtime stats for all proxies."""
        results = []
        for p in self.proxies.values():
            results.append({
                "id": p.id,
                "host": p.host,
                "port": p.port,
                "region": p.region,
                "active": p.active,
                "weight": round(p.weight, 3),
                "success_count": p.success_count,
                "fail_count": p.fail_count,
                "success_rate": round(p.success_rate * 100, 1),
                "avg_latency_ms": round(p.avg_latency, 1),
                "last_used": p.last_used,
            })
        return results
