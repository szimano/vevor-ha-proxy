"""Entrypoint: python -m wu_proxy."""
from __future__ import annotations

import logging
import os
from typing import Any

from aiohttp import web
from yarl import URL

from .app import create_app
from .config import Settings


def run_kwargs(settings: Settings) -> dict[str, Any]:
    return {"host": settings.host, "port": settings.port, "access_log": None}


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    logging.getLogger("wu_proxy").info(
        "Starting: relay %s, upstream host %s",
        "on" if settings.relay_enabled else "off",
        URL(settings.upstream_url).host,
    )
    web.run_app(create_app(settings), **run_kwargs(settings))


if __name__ == "__main__":
    main()
