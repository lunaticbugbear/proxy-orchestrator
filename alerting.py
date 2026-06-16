"""
Proxy Orchestrator - Alerting
Webhook-based alerts (Telegram, Discord, Slack, generic HTTP).
"""

import asyncio
import aiohttp
import logging
import json

logger = logging.getLogger("proxy_orchestrator.alerting")


class AlertManager:
    """
    Sends alerts to configured webhooks.

    Supports:
    - Telegram Bot API
    - Discord Webhooks
    - Slack Webhooks
    - Generic HTTP POST

    Usage:
        alerts = AlertManager(webhooks_config)
        alerts.send("Pool dropped below threshold!")
    """

    def __init__(self, webhooks: list[dict] = None):
        self.webhooks = webhooks or []
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def send(self, message: str):
        """Send alert to all configured webhooks."""
        if not self.webhooks:
            logger.debug(f"No webhooks configured, skipping alert: {message}")
            return

        session = await self._get_session()
        tasks = [self._send_to_webhook(session, wh, message) for wh in self.webhooks]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_to_webhook(self, session: aiohttp.ClientSession,
                               webhook: dict, message: str):
        url = webhook.get("url", "")
        if not url or "<" in url:
            # Skip placeholder URLs from config template
            return

        method = webhook.get("method", "POST")
        body_template = webhook.get("body_template", '{"text": "{message}"}')

        # Replace {message} placeholder
        body_str = body_template.replace("{message}", message.replace('"', '\\"'))

        headers = {"Content-Type": "application/json"}

        # Merge any extra headers from config
        if "headers" in webhook:
            headers.update(webhook["headers"])

        # Merge payload fields (for Telegram-style configs)
        payload = webhook.get("payload", {})
        if payload:
            try:
                body_json = json.loads(body_str)
                body_json.update(payload)
                body_str = json.dumps(body_json)
            except json.JSONDecodeError:
                pass  # use template as-is

        try:
            async with session.request(
                method, url, data=body_str, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status < 300:
                    logger.info(f"Alert sent to {url[:50]}... (status: {resp.status})")
                else:
                    text = await resp.text()
                    logger.error(f"Alert failed to {url[:50]}... (status: {resp.status}): {text[:200]}")
        except Exception as e:
            logger.error(f"Alert delivery error to {url[:50]}...: {e}")

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


def create_alert_callback(alert_manager: AlertManager):
    """
    Create a sync callback that schedules async send.
    Useful for passing to HealthChecker which calls it synchronously.
    """
    def callback(message: str):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(alert_manager.send(message))
        except RuntimeError:
            # No running loop, create one
            asyncio.run(alert_manager.send(message))

    return callback
