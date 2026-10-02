"""Proxy configuration, read from environment variables."""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_UPSTREAM_URL = "https://rtupdate.wunderground.com"
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    ha_webhook_url: str
    upstream_url: str = DEFAULT_UPSTREAM_URL
    relay_enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 80
    max_query_bytes: int = 4096
    ha_timeout: float = 5.0
    upstream_timeout: float = 10.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        webhook = env.get("HA_WEBHOOK_URL")
        if not webhook:
            raise ValueError("HA_WEBHOOK_URL is required")
        return cls(
            ha_webhook_url=webhook,
            upstream_url=env.get("UPSTREAM_URL", DEFAULT_UPSTREAM_URL).rstrip("/"),
            relay_enabled=env.get("RELAY_ENABLED", "true").lower() in _TRUE,
            host=env.get("BIND_HOST", "0.0.0.0"),
            port=int(env.get("PORT", "80")),
        )
