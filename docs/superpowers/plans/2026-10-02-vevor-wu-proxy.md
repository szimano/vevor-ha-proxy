# Vevor Weather Station Proxy + Home Assistant Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture a Vevor YT60234 station's Wunderground uploads locally in Home Assistant while still relaying them to Wunderground unchanged.

**Architecture:** A stateless Python (aiohttp) proxy container with its own LAN IP answers the station's HTTP upload with `success`, then in the background POSTs the readings (minus `PASSWORD`) to an HA webhook and replays the original request to Wunderground. A Python HA custom integration (`vevor_wu`) owns the webhook, converts readings to metric, and exposes push-updated sensors.

**Tech Stack:** Python 3.13, aiohttp, pytest, pytest-aiohttp, pytest-homeassistant-custom-component, Docker Compose (macvlan).

**Spec:** `docs/superpowers/specs/2026-10-02-vevor-wu-proxy-design.md`

## Global Constraints

- Station request: plain HTTP `GET /weatherstation/updateweatherstation.php`, port 80, params `ID`, `PASSWORD`, `dateutc`, `tempf`, `humidity`, `baromin`, `dewptf`, `rainin`, `dailyrainin`, `winddir`, `windspeedmph`, `windgustmph`, `UV`, `solarRadiation`.
- The station always gets `success` (200, text/plain), regardless of HA or Wunderground outcome.
- `PASSWORD` is stripped before anything is sent to HA and redacted in every log line. The HA webhook URL is also a secret and is never logged.
- aiohttp access logging is disabled (it would log the query string, including the password).
- Upstream relay defaults to HTTPS (`https://rtupdate.wunderground.com`); relay replays the original raw query unchanged.
- Timeouts: HA webhook 5 s, Wunderground 10 s. No retry queue, no persistence.
- Query string capped at 4096 bytes (HTTP 414 above that). Unknown paths return 404 and are logged (path only, never the query).
- Webhook registered `local_only=True`, `allowed_methods=["POST"]`.
- Units are metric at ingest: °C, hPa, km/h, mm, mm. Rounding: 1 decimal, 2 for rain.
- Sensors go `unavailable` after 10 minutes without a valid reading.
- Container DNS pinned to `1.1.1.1` so the upstream relay does not resolve to the overridden Pi-hole record.
- HA runs with `network_mode: host`; proxy reaches it via `host.docker.internal` (`host-gateway`).

---

## File Structure

```
weather-ha/
├── pytest.ini
├── requirements-proxy-dev.txt
├── requirements-ha-dev.txt
├── .gitignore
├── README.md
├── proxy/
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── compose.yml
│   ├── .env.example
│   └── wu_proxy/
│       ├── __init__.py
│       ├── __main__.py       # entrypoint + run_kwargs
│       ├── healthcheck.py    # Docker HEALTHCHECK script
│       ├── config.py         # Settings.from_env
│       ├── redact.py         # strip_secrets, redact_query
│       └── app.py            # aiohttp app, handlers, fan-out
├── custom_components/
│   ├── __init__.py
│   └── vevor_wu/
│       ├── __init__.py       # setup/unload, webhook handler
│       ├── manifest.json
│       ├── const.py
│       ├── conversions.py    # unit conversion functions
│       ├── readings.py       # parse_readings, unknown_params
│       ├── config_flow.py
│       ├── sensor.py
│       ├── strings.json
│       └── translations/en.json
└── tests/
    ├── proxy/                # conftest.py, test_redact.py, test_config.py, test_app.py, test_fanout.py, test_main.py
    └── integration/          # conftest.py, test_readings.py, test_config_flow.py, test_webhook.py, test_sensor.py
```

Proxy tests and HA tests use **separate virtualenvs** because `pytest-homeassistant-custom-component` pins Home Assistant's dependency versions.

---

### Task 1: Project scaffolding

**Files:**
- Create: `.gitignore`, `pytest.ini`, `requirements-proxy-dev.txt`, `requirements-ha-dev.txt`, `proxy/requirements.txt`, `proxy/wu_proxy/__init__.py`, `custom_components/__init__.py`

**Interfaces:**
- Produces: two venvs (`.venv-proxy`, `.venv-ha`); `pytest.ini` puts `.` and `proxy` on `pythonpath` so tests import `wu_proxy` and `custom_components.vevor_wu`.

- [ ] **Step 1: Initialise git and create files**

Run: `cd /Users/szimano/code/weather-ha && git init`

`.gitignore`:
```
.venv-*/
__pycache__/
.pytest_cache/
.env
```

`pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
pythonpath = . proxy
testpaths = tests
```

`proxy/requirements.txt`:
```
aiohttp>=3.10
```

`requirements-proxy-dev.txt`:
```
-r proxy/requirements.txt
pytest
pytest-asyncio
pytest-aiohttp
```

`requirements-ha-dev.txt`:
```
pytest-homeassistant-custom-component
```

`proxy/wu_proxy/__init__.py` and `custom_components/__init__.py`: empty files.

- [ ] **Step 2: Create the virtualenvs**

Run: `python3 --version` (the HA test plugin needs the Python version current Home Assistant requires, 3.13 or newer; if `python3` is older, use `python3.13` below).

Run:
```bash
python3 -m venv .venv-proxy && .venv-proxy/bin/pip install -r requirements-proxy-dev.txt
python3 -m venv .venv-ha && .venv-ha/bin/pip install -r requirements-ha-dev.txt
```
Expected: both installs finish without errors.

- [ ] **Step 3: Verify pytest runs in both venvs**

Run: `.venv-proxy/bin/pytest` and `.venv-ha/bin/pytest`
Expected: both print `no tests ran` (exit code 5 is fine here).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: project scaffolding" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Proxy settings and redaction helpers

**Files:**
- Create: `proxy/wu_proxy/config.py`, `proxy/wu_proxy/redact.py`
- Test: `tests/proxy/test_redact.py`, `tests/proxy/test_config.py`

**Interfaces:**
- Produces:
  - `config.DEFAULT_UPSTREAM_URL: str`
  - `config.Settings` frozen dataclass: `ha_webhook_url: str`, `upstream_url: str`, `relay_enabled: bool`, `host: str`, `port: int`, `max_query_bytes: int`, `ha_timeout: float`, `upstream_timeout: float`; classmethod `Settings.from_env(env: Mapping[str, str] | None = None) -> Settings`.
  - `redact.REDACTED: str`, `redact.strip_secrets(params: Mapping[str, str]) -> dict[str, str]`, `redact.redact_query(query: str) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/proxy/test_redact.py`:
```python
from wu_proxy.redact import REDACTED, redact_query, strip_secrets


def test_strip_secrets_removes_password():
    params = {"ID": "IWARSA474", "PASSWORD": "hunter2", "tempf": "50.0"}
    assert strip_secrets(params) == {"ID": "IWARSA474", "tempf": "50.0"}


def test_strip_secrets_is_case_insensitive():
    assert strip_secrets({"Password": "x", "a": "1"}) == {"a": "1"}


def test_redact_query_masks_password_value():
    out = redact_query("ID=IWARSA474&PASSWORD=hunter2&tempf=50.0")
    assert "hunter2" not in out
    assert f"PASSWORD={REDACTED}" in out
    assert "tempf=50.0" in out


def test_redact_query_handles_empty_and_blank_values():
    assert redact_query("") == ""
    assert redact_query("a=&b=1") == "a=&b=1"
```

`tests/proxy/test_config.py`:
```python
import pytest

from wu_proxy.config import DEFAULT_UPSTREAM_URL, Settings


def test_from_env_defaults():
    s = Settings.from_env({"HA_WEBHOOK_URL": "http://h:8123/api/webhook/abc"})
    assert s.ha_webhook_url == "http://h:8123/api/webhook/abc"
    assert s.upstream_url == DEFAULT_UPSTREAM_URL
    assert s.relay_enabled is True
    assert s.host == "0.0.0.0"
    assert s.port == 80
    assert s.max_query_bytes == 4096
    assert s.ha_timeout == 5.0
    assert s.upstream_timeout == 10.0


def test_from_env_overrides():
    s = Settings.from_env(
        {
            "HA_WEBHOOK_URL": "http://h/x",
            "UPSTREAM_URL": "http://localhost:9/",
            "RELAY_ENABLED": "false",
            "PORT": "8080",
            "BIND_HOST": "192.168.1.60",
        }
    )
    assert s.upstream_url == "http://localhost:9"
    assert s.relay_enabled is False
    assert s.port == 8080
    assert s.host == "192.168.1.60"


def test_missing_webhook_url_raises():
    with pytest.raises(ValueError, match="HA_WEBHOOK_URL"):
        Settings.from_env({})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-proxy/bin/pytest tests/proxy -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wu_proxy.redact'` (and `config`).

- [ ] **Step 3: Write the implementation**

`proxy/wu_proxy/redact.py`:
```python
"""Helpers that keep the station's Wunderground password out of HA and logs."""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode

REDACTED = "REDACTED"
_SECRET_KEYS = {"password"}


def strip_secrets(params: Mapping[str, str]) -> dict[str, str]:
    """Return params without secret keys (case-insensitive)."""
    return {k: v for k, v in params.items() if k.lower() not in _SECRET_KEYS}


def redact_query(query: str) -> str:
    """Return a raw query string with secret values masked, safe to log."""
    pairs = parse_qsl(query, keep_blank_values=True)
    return urlencode(
        [(k, REDACTED if k.lower() in _SECRET_KEYS else v) for k, v in pairs]
    )
```

`proxy/wu_proxy/config.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-proxy/bin/pytest tests/proxy -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add proxy tests
git commit -m "feat(proxy): settings and secret redaction helpers" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Proxy HTTP app (route, `success`, 404, size cap, healthz)

**Files:**
- Create: `proxy/wu_proxy/app.py`, `tests/proxy/conftest.py`
- Test: `tests/proxy/test_app.py`

**Interfaces:**
- Consumes: `Settings` (Task 2).
- Produces: `app.WU_PATH`, `app.SETTINGS_KEY`, `app.TASKS_KEY` (`web.AppKey` for `set` of background tasks), `app.create_app(settings: Settings) -> web.Application`. Test fixtures: `fake_ha` and `fake_wu` (recorders with `.requests`, `.status`, `.url`), `proxy` (aiohttp test client), `drain(app)` (awaits background tasks).

- [ ] **Step 1: Write the fixtures and failing tests**

`tests/proxy/conftest.py`:
```python
import asyncio

import pytest
from aiohttp import web

from wu_proxy.app import TASKS_KEY, create_app
from wu_proxy.config import Settings


class Recorder:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.url = ""


@pytest.fixture
async def fake_ha(aiohttp_server):
    rec = Recorder()

    async def handler(request):
        rec.requests.append({"json": await request.json()})
        return web.Response(status=rec.status, text="ok")

    app = web.Application()
    app.router.add_post("/api/webhook/abc", handler)
    server = await aiohttp_server(app)
    rec.url = str(server.make_url("/api/webhook/abc"))
    return rec


@pytest.fixture
async def fake_wu(aiohttp_server):
    rec = Recorder()

    async def handler(request):
        rec.requests.append({"raw_query": request.rel_url.raw_query_string})
        return web.Response(status=rec.status, text="success\n")

    app = web.Application()
    app.router.add_get("/weatherstation/updateweatherstation.php", handler)
    server = await aiohttp_server(app)
    rec.url = str(server.make_url("")).rstrip("/")
    return rec


@pytest.fixture
async def proxy(aiohttp_client, fake_ha, fake_wu):
    settings = Settings(
        ha_webhook_url=fake_ha.url,
        upstream_url=fake_wu.url,
        ha_timeout=2,
        upstream_timeout=2,
    )
    return await aiohttp_client(create_app(settings))


@pytest.fixture
def drain():
    async def _drain(app):
        await asyncio.gather(*list(app[TASKS_KEY]), return_exceptions=True)

    return _drain
```

`tests/proxy/test_app.py`:
```python
import logging

WU_PATH = "/weatherstation/updateweatherstation.php"
QUERY = "ID=IWARSA474&PASSWORD=hunter2&dateutc=now&tempf=50.0&humidity=60"


async def test_valid_update_returns_success(proxy):
    resp = await proxy.get(f"{WU_PATH}?{QUERY}")
    assert resp.status == 200
    assert resp.content_type == "text/plain"
    assert (await resp.text()).strip() == "success"


async def test_healthz(proxy):
    resp = await proxy.get("/healthz")
    assert resp.status == 200


async def test_unknown_path_is_404_and_logged_without_query(proxy, caplog):
    with caplog.at_level(logging.WARNING, logger="wu_proxy"):
        resp = await proxy.get("/something/else?PASSWORD=hunter2")
    assert resp.status == 404
    assert "/something/else" in caplog.text
    assert "hunter2" not in caplog.text


async def test_oversized_query_rejected(proxy):
    resp = await proxy.get(f"{WU_PATH}?x={'a' * 5000}")
    assert resp.status == 414
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-proxy/bin/pytest tests/proxy/test_app.py -v`
Expected: FAIL with `ImportError: cannot import name 'create_app'` (module `wu_proxy.app` missing).

- [ ] **Step 3: Write the minimal implementation**

`proxy/wu_proxy/app.py`:
```python
"""HTTP front end: accepts the station's Wunderground upload and fans it out."""
from __future__ import annotations

import logging

from aiohttp import web

from .config import Settings

_LOGGER = logging.getLogger("wu_proxy")

WU_PATH = "/weatherstation/updateweatherstation.php"
SETTINGS_KEY = web.AppKey("settings", Settings)
TASKS_KEY = web.AppKey("tasks", set)


async def handle_update(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    raw_query = request.rel_url.raw_query_string
    if len(raw_query.encode()) > settings.max_query_bytes:
        return web.Response(status=414, text="query too long\n")
    return web.Response(text="success\n")


async def handle_healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok\n")


async def handle_unknown(request: web.Request) -> web.Response:
    # Log the path only: the query string may contain the station password.
    _LOGGER.warning(
        "Unexpected request: %s %s (host=%s)",
        request.method,
        request.path,
        request.host,
    )
    return web.Response(status=404, text="not found\n")


def create_app(settings: Settings) -> web.Application:
    app = web.Application()
    app[SETTINGS_KEY] = settings
    app[TASKS_KEY] = set()
    app.router.add_get(WU_PATH, handle_update)
    app.router.add_get("/healthz", handle_healthz)
    app.router.add_route("*", "/{tail:.*}", handle_unknown)
    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-proxy/bin/pytest tests/proxy -v`
Expected: all pass (11 passed).

- [ ] **Step 5: Commit**

```bash
git add proxy tests
git commit -m "feat(proxy): HTTP app answering station uploads with success" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Fan-out to HA webhook and Wunderground

**Files:**
- Modify: `proxy/wu_proxy/app.py`
- Test: `tests/proxy/test_fanout.py`

**Interfaces:**
- Consumes: `redact.strip_secrets`, `redact.redact_query`, `app.SETTINGS_KEY`, `app.TASKS_KEY`, fixtures from Task 3.
- Produces: `app.SESSION_KEY`; `forward_to_ha(session, settings, params)` and `relay_to_wunderground(session, settings, raw_query)` coroutines that never raise.

- [ ] **Step 1: Write the failing tests**

`tests/proxy/test_fanout.py`:
```python
import logging

from wu_proxy.app import create_app
from wu_proxy.config import Settings

WU_PATH = "/weatherstation/updateweatherstation.php"
QUERY = "ID=IWARSA474&PASSWORD=hunter2&dateutc=now&tempf=50.0&humidity=60"


async def test_ha_receives_readings_without_password(proxy, fake_ha, drain):
    await proxy.get(f"{WU_PATH}?{QUERY}")
    await drain(proxy.app)
    assert len(fake_ha.requests) == 1
    assert fake_ha.requests[0]["json"] == {
        "ID": "IWARSA474",
        "dateutc": "now",
        "tempf": "50.0",
        "humidity": "60",
    }


async def test_wunderground_receives_original_query(proxy, fake_wu, drain):
    await proxy.get(f"{WU_PATH}?{QUERY}")
    await drain(proxy.app)
    assert len(fake_wu.requests) == 1
    assert fake_wu.requests[0]["raw_query"] == QUERY


async def test_relay_can_be_disabled(aiohttp_client, fake_ha, fake_wu, drain):
    settings = Settings(
        ha_webhook_url=fake_ha.url, upstream_url=fake_wu.url, relay_enabled=False
    )
    client = await aiohttp_client(create_app(settings))
    await client.get(f"{WU_PATH}?{QUERY}")
    await drain(client.app)
    assert len(fake_ha.requests) == 1
    assert fake_wu.requests == []


async def test_ha_failure_does_not_affect_response_or_relay(
    proxy, fake_ha, fake_wu, drain, caplog
):
    fake_ha.status = 500
    with caplog.at_level(logging.WARNING, logger="wu_proxy"):
        resp = await proxy.get(f"{WU_PATH}?{QUERY}")
        await drain(proxy.app)
    assert (await resp.text()).strip() == "success"
    assert len(fake_wu.requests) == 1
    assert "HTTP 500" in caplog.text
    assert "hunter2" not in caplog.text


async def test_upstream_error_status_is_logged_without_password(
    proxy, fake_wu, drain, caplog
):
    fake_wu.status = 500
    with caplog.at_level(logging.WARNING, logger="wu_proxy"):
        resp = await proxy.get(f"{WU_PATH}?{QUERY}")
        await drain(proxy.app)
    assert (await resp.text()).strip() == "success"
    assert "HTTP 500" in caplog.text
    assert "hunter2" not in caplog.text


async def test_unreachable_upstream_still_succeeds_and_does_not_leak(
    aiohttp_client, fake_ha, drain, caplog
):
    settings = Settings(
        ha_webhook_url=fake_ha.url,
        upstream_url="http://127.0.0.1:1",
        ha_timeout=2,
        upstream_timeout=2,
    )
    client = await aiohttp_client(create_app(settings))
    with caplog.at_level(logging.DEBUG):
        resp = await client.get(f"{WU_PATH}?{QUERY}")
        await drain(client.app)
    assert (await resp.text()).strip() == "success"
    assert len(fake_ha.requests) == 1
    assert "hunter2" not in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-proxy/bin/pytest tests/proxy/test_fanout.py -v`
Expected: FAIL (`fake_ha.requests` is empty: nothing is forwarded yet).

- [ ] **Step 3: Write the implementation**

Replace `proxy/wu_proxy/app.py` with:
```python
"""HTTP front end: accepts the station's Wunderground upload and fans it out."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine
from typing import Any

import aiohttp
from aiohttp import web
from yarl import URL

from .config import Settings
from .redact import redact_query, strip_secrets

_LOGGER = logging.getLogger("wu_proxy")

WU_PATH = "/weatherstation/updateweatherstation.php"
SETTINGS_KEY = web.AppKey("settings", Settings)
SESSION_KEY = web.AppKey("session", aiohttp.ClientSession)
TASKS_KEY = web.AppKey("tasks", set)


async def forward_to_ha(
    session: aiohttp.ClientSession, settings: Settings, params: dict[str, str]
) -> None:
    """POST the readings (without secrets) to the HA webhook. Never raises."""
    payload = strip_secrets(params)
    try:
        async with session.post(
            settings.ha_webhook_url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=settings.ha_timeout),
        ) as resp:
            if resp.status >= 400:
                _LOGGER.warning("HA webhook returned HTTP %s", resp.status)
    except Exception as err:  # noqa: BLE001 - a background task must never raise
        # Log the class only: messages can embed the secret webhook URL.
        _LOGGER.warning("HA webhook delivery failed: %s", type(err).__name__)


async def relay_to_wunderground(
    session: aiohttp.ClientSession, settings: Settings, raw_query: str
) -> None:
    """Replay the station's original request upstream. Never raises."""
    url = URL(f"{settings.upstream_url}{WU_PATH}?{raw_query}", encoded=True)
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=settings.upstream_timeout)
        ) as resp:
            if resp.status >= 400:
                _LOGGER.warning(
                    "Wunderground returned HTTP %s for %s",
                    resp.status,
                    redact_query(raw_query),
                )
            else:
                _LOGGER.debug("Wunderground relay HTTP %s", resp.status)
    except Exception as err:  # noqa: BLE001 - a background task must never raise
        _LOGGER.warning("Wunderground relay failed: %s", type(err).__name__)


def _spawn(app: web.Application, coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    app[TASKS_KEY].add(task)
    task.add_done_callback(app[TASKS_KEY].discard)


async def handle_update(request: web.Request) -> web.Response:
    app = request.app
    settings = app[SETTINGS_KEY]
    raw_query = request.rel_url.raw_query_string
    if len(raw_query.encode()) > settings.max_query_bytes:
        return web.Response(status=414, text="query too long\n")
    session = app[SESSION_KEY]
    _spawn(app, forward_to_ha(session, settings, dict(request.query)))
    if settings.relay_enabled:
        _spawn(app, relay_to_wunderground(session, settings, raw_query))
    return web.Response(text="success\n")


async def handle_healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok\n")


async def handle_unknown(request: web.Request) -> web.Response:
    # Log the path only: the query string may contain the station password.
    _LOGGER.warning(
        "Unexpected request: %s %s (host=%s)",
        request.method,
        request.path,
        request.host,
    )
    return web.Response(status=404, text="not found\n")


async def _client_session(app: web.Application) -> AsyncIterator[None]:
    async with aiohttp.ClientSession() as session:
        app[SESSION_KEY] = session
        yield
        pending = list(app[TASKS_KEY])
        if pending:
            await asyncio.wait(pending, timeout=5)


def create_app(settings: Settings) -> web.Application:
    app = web.Application()
    app[SETTINGS_KEY] = settings
    app[TASKS_KEY] = set()
    app.cleanup_ctx.append(_client_session)
    app.router.add_get(WU_PATH, handle_update)
    app.router.add_get("/healthz", handle_healthz)
    app.router.add_route("*", "/{tail:.*}", handle_unknown)
    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-proxy/bin/pytest tests/proxy -v`
Expected: all pass (17 passed).

- [ ] **Step 5: Commit**

```bash
git add proxy tests
git commit -m "feat(proxy): fan out readings to HA webhook and Wunderground" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Proxy entrypoint, container, and deployment docs

**Files:**
- Create: `proxy/wu_proxy/__main__.py`, `proxy/wu_proxy/healthcheck.py`, `proxy/Dockerfile`, `proxy/compose.yml`, `proxy/.env.example`, `README.md`
- Test: `tests/proxy/test_main.py`

**Interfaces:**
- Consumes: `Settings.from_env`, `create_app`.
- Produces: `__main__.run_kwargs(settings) -> dict` (always includes `access_log=None`); `__main__.main()`.

- [ ] **Step 1: Write the failing test**

`tests/proxy/test_main.py`:
```python
from wu_proxy.__main__ import run_kwargs
from wu_proxy.config import Settings


def test_run_kwargs_disables_access_log_and_binds_configured_address():
    settings = Settings(ha_webhook_url="http://h/x", host="192.168.1.60", port=80)
    kwargs = run_kwargs(settings)
    # The access log would print the query string, including the station password.
    assert kwargs["access_log"] is None
    assert kwargs["host"] == "192.168.1.60"
    assert kwargs["port"] == 80
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-proxy/bin/pytest tests/proxy/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wu_proxy.__main__'`.

- [ ] **Step 3: Write the implementation and deployment files**

`proxy/wu_proxy/__main__.py`:
```python
"""Entrypoint: python -m wu_proxy."""
from __future__ import annotations

import logging
import os
from typing import Any

from aiohttp import web

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
    web.run_app(create_app(settings), **run_kwargs(settings))


if __name__ == "__main__":
    main()
```

`proxy/wu_proxy/healthcheck.py`:
```python
"""Docker HEALTHCHECK: exit 0 if /healthz answers."""
import os
import sys
import urllib.request

host = os.environ.get("BIND_HOST", "127.0.0.1")
if host == "0.0.0.0":
    host = "127.0.0.1"
port = os.environ.get("PORT", "80")
try:
    urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=2)
except Exception:
    sys.exit(1)
```

`proxy/Dockerfile`:
```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY wu_proxy ./wu_proxy
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-m", "wu_proxy.healthcheck"]
CMD ["python", "-m", "wu_proxy"]
```

`proxy/.env.example`:
```
# Full webhook URL shown by the HA integration's setup dialog, reached via the host gateway.
HA_WEBHOOK_URL=http://host.docker.internal:8123/api/webhook/REPLACE_WITH_WEBHOOK_ID
# Free LAN address outside your DHCP range. Pi-hole will resolve rtupdate.wunderground.com to it.
PROXY_IP=192.168.1.60
# Host NIC the macvlan attaches to, and the LAN it sits on.
LAN_INTERFACE=enp8s0
LAN_SUBNET=192.168.1.0/24
LAN_GATEWAY=192.168.1.1
```

`proxy/compose.yml`:
```yaml
services:
  wu-proxy:
    build: .
    container_name: wu-proxy
    restart: unless-stopped
    environment:
      HA_WEBHOOK_URL: ${HA_WEBHOOK_URL:?set HA_WEBHOOK_URL in .env}
      BIND_HOST: ${PROXY_IP:?set PROXY_IP in .env}
      PORT: "80"
    # Never use the Pi-hole that overrides rtupdate.wunderground.com, or the relay loops to itself.
    dns:
      - 1.1.1.1
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks:
      # Default route goes out through the bridge (NAT via the host). It also keeps
      # host.docker.internal reachable. Needs Docker Engine 28+ for gw_priority.
      bridge_net:
        gw_priority: 10
      # Own LAN IP for the station; macvlan, so only the station-facing side uses it.
      lan:
        ipv4_address: ${PROXY_IP}
        gw_priority: 0

networks:
  bridge_net: {}
  lan:
    driver: macvlan
    driver_opts:
      parent: ${LAN_INTERFACE:-enp8s0}
    ipam:
      config:
        - subnet: ${LAN_SUBNET:-192.168.1.0/24}
          gateway: ${LAN_GATEWAY:-192.168.1.1}
```

`README.md`:
```markdown
# Vevor weather station: local Wunderground proxy

Captures the station's Wunderground uploads in Home Assistant and relays them to
Wunderground unchanged. See `docs/superpowers/specs/2026-10-02-vevor-wu-proxy-design.md`.

## Install the HA integration
1. Copy `custom_components/vevor_wu` into HA's `/config/custom_components/`.
2. Restart Home Assistant.
3. Settings > Devices & Services > Add Integration > "Vevor weather station".
4. Note the webhook path shown (`/api/webhook/<id>`).

## Run the proxy
1. `cd proxy && cp .env.example .env` and fill in `HA_WEBHOOK_URL`, `PROXY_IP`, `LAN_*`.
2. `docker compose up -d --build`
3. Verify routing (see checklist below), then add the DNS record.

## DNS
In Pi-hole/AdGuard add a local DNS record: `rtupdate.wunderground.com` -> `PROXY_IP`.
If the router has DNS rebind protection, allow that hostname. The station must use that DNS server.

## End-to-end checklist
Run the `curl` from another machine on the LAN (the Docker host itself cannot reach a macvlan address).
- [ ] `docker exec wu-proxy ip route` shows the default route via the bridge network, not the LAN.
- [ ] `curl "http://<PROXY_IP>/weatherstation/updateweatherstation.php?ID=TEST&PASSWORD=x&tempf=50&humidity=60"` prints `success`.
- [ ] `docker logs wu-proxy` shows no password and no warnings; the test reading appears in HA (temperature 10.0 °C).
- [ ] `docker exec wu-proxy python -c "import urllib.request as u; print(u.urlopen('https://rtupdate.wunderground.com/').status)"` works (proves the relay path).
- [ ] After the DNS record is added, the station's readings appear in HA within its upload interval.
- [ ] Wunderground's dashboard for the station still shows fresh data.
- [ ] `docker logs wu-proxy` shows no unexpected 404 paths (a different hostname or path means the station uses something we did not expect).
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-proxy/bin/pytest tests/proxy -v`
Expected: all pass (18 passed).

- [ ] **Step 5: Validate the compose file and image build**

Run: `cd proxy && cp .env.example .env && docker compose config -q && docker compose build; rm .env`
Expected: `config -q` prints nothing (valid); build succeeds.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(proxy): entrypoint, Dockerfile, compose, deployment docs" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Integration unit conversions and reading parser

**Files:**
- Create: `custom_components/vevor_wu/__init__.py` (empty for now), `custom_components/vevor_wu/conversions.py`, `custom_components/vevor_wu/readings.py`
- Test: `tests/integration/test_readings.py`

**Interfaces:**
- Produces:
  - `conversions.f_to_c(v: float) -> float`, `inhg_to_hpa`, `mph_to_kmh`, `in_to_mm` (each `float -> float`).
  - `readings.parse_readings(payload: Mapping[str, Any]) -> dict[str, float]` mapping sensor keys to metric values: `temperature`, `dew_point`, `humidity`, `pressure`, `wind_speed`, `wind_gust`, `wind_direction`, `rain_last_hour`, `rain_today`, `uv_index`, `solar_radiation`. Skips empty, non-numeric, non-finite and `-9999` values.
  - `readings.unknown_params(payload: Mapping[str, Any]) -> set[str]`: parameter names that are neither known nor ignorable.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_readings.py`:
```python
import pytest

from custom_components.vevor_wu.conversions import (
    f_to_c,
    in_to_mm,
    inhg_to_hpa,
    mph_to_kmh,
)
from custom_components.vevor_wu.readings import parse_readings, unknown_params


def test_conversions():
    assert f_to_c(32) == 0
    assert f_to_c(212) == pytest.approx(100)
    assert inhg_to_hpa(29.92) == pytest.approx(1013.2, abs=0.1)
    assert mph_to_kmh(10) == pytest.approx(16.09344)
    assert in_to_mm(1) == pytest.approx(25.4)


def test_parse_converts_to_metric_and_rounds():
    out = parse_readings(
        {
            "ID": "X",
            "tempf": "50.0",
            "dewptf": "41.0",
            "humidity": "60",
            "baromin": "29.92",
            "windspeedmph": "10",
            "windgustmph": "15",
            "winddir": "270",
            "rainin": "0.1",
            "dailyrainin": "0.25",
            "UV": "3",
            "solarRadiation": "500.5",
        }
    )
    assert out == {
        "temperature": 10.0,
        "dew_point": 5.0,
        "humidity": 60.0,
        "pressure": 1013.2,
        "wind_speed": 16.1,
        "wind_gust": 24.1,
        "wind_direction": 270.0,
        "rain_last_hour": 2.54,
        "rain_today": 6.35,
        "uv_index": 3.0,
        "solar_radiation": 500.5,
    }


@pytest.mark.parametrize("bad", ["", "--", "abc", "-9999", "nan", "inf"])
def test_bad_values_are_skipped_per_field(bad):
    assert parse_readings({"tempf": bad, "humidity": "60"}) == {"humidity": 60.0}


def test_param_names_are_case_insensitive():
    assert parse_readings({"uv": "2", "SOLARRADIATION": "10"}) == {
        "uv_index": 2.0,
        "solar_radiation": 10.0,
    }


def test_unknown_params_ignores_known_and_housekeeping_keys():
    payload = {
        "ID": "x",
        "tempf": "1",
        "foo": "2",
        "action": "updateraw",
        "dateutc": "now",
        "realtime": "1",
        "rtfreq": "5",
    }
    assert unknown_params(payload) == {"foo"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-ha/bin/pytest tests/integration/test_readings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'custom_components.vevor_wu.conversions'`.

- [ ] **Step 3: Write the implementation**

`custom_components/vevor_wu/__init__.py`: empty file (replaced in Task 8).

`custom_components/vevor_wu/conversions.py`:
```python
"""Imperial to metric conversions for Wunderground-format readings."""


def f_to_c(value: float) -> float:
    return (value - 32) * 5 / 9


def inhg_to_hpa(value: float) -> float:
    return value * 33.8639


def mph_to_kmh(value: float) -> float:
    return value * 1.609344


def in_to_mm(value: float) -> float:
    return value * 25.4
```

`custom_components/vevor_wu/readings.py`:
```python
"""Parse a Wunderground-format payload into metric sensor values."""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .conversions import f_to_c, in_to_mm, inhg_to_hpa, mph_to_kmh

_SENTINEL = -9999.0
_IGNORED_PARAMS = {"id", "dateutc", "action", "realtime", "rtfreq", "softwaretype"}


def _identity(value: float) -> float:
    return value


@dataclass(frozen=True)
class ReadingSpec:
    key: str
    param: str  # lowercase query parameter name
    convert: Callable[[float], float]
    decimals: int


SPECS: tuple[ReadingSpec, ...] = (
    ReadingSpec("temperature", "tempf", f_to_c, 1),
    ReadingSpec("dew_point", "dewptf", f_to_c, 1),
    ReadingSpec("humidity", "humidity", _identity, 1),
    ReadingSpec("pressure", "baromin", inhg_to_hpa, 1),
    ReadingSpec("wind_speed", "windspeedmph", mph_to_kmh, 1),
    ReadingSpec("wind_gust", "windgustmph", mph_to_kmh, 1),
    ReadingSpec("wind_direction", "winddir", _identity, 1),
    ReadingSpec("rain_last_hour", "rainin", in_to_mm, 2),
    ReadingSpec("rain_today", "dailyrainin", in_to_mm, 2),
    ReadingSpec("uv_index", "uv", _identity, 1),
    ReadingSpec("solar_radiation", "solarradiation", _identity, 1),
)
_KNOWN_PARAMS = {spec.param for spec in SPECS}


def _to_number(raw: Any) -> float | None:
    try:
        value = float(str(raw).strip())
    except ValueError:
        return None
    if not math.isfinite(value) or value == _SENTINEL:
        return None
    return value


def parse_readings(payload: Mapping[str, Any]) -> dict[str, float]:
    """Return metric values keyed by sensor key; invalid fields are skipped."""
    lowered = {str(k).lower(): v for k, v in payload.items()}
    out: dict[str, float] = {}
    for spec in SPECS:
        if spec.param not in lowered:
            continue
        value = _to_number(lowered[spec.param])
        if value is None:
            continue
        out[spec.key] = round(spec.convert(value), spec.decimals)
    return out


def unknown_params(payload: Mapping[str, Any]) -> set[str]:
    """Return parameter names we neither map nor deliberately ignore."""
    return {
        str(k)
        for k in payload
        if str(k).lower() not in _KNOWN_PARAMS | _IGNORED_PARAMS
    }
```

`tests/integration/conftest.py`:
```python
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-ha/bin/pytest tests/integration/test_readings.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components tests
git commit -m "feat(integration): unit conversions and reading parser" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Integration manifest, constants, and config flow

**Files:**
- Create: `custom_components/vevor_wu/manifest.json`, `const.py`, `config_flow.py`, `strings.json`, `translations/en.json`
- Modify: `custom_components/vevor_wu/__init__.py` (minimal setup so the flow can create an entry)
- Test: `tests/integration/test_config_flow.py`

**Interfaces:**
- Produces: `const.DOMAIN = "vevor_wu"`, `const.STALE_AFTER: timedelta` (10 minutes), `const.signal_update(entry_id: str) -> str`; a config flow with a single `user` step that creates an entry with `data={CONF_WEBHOOK_ID: <id>}` and title `"Vevor weather station"`, showing the path `/api/webhook/<id>` via description placeholder `path`; aborts with `single_instance_allowed` if an entry exists.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_config_flow.py`:
```python
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vevor_wu.const import DOMAIN


async def test_user_flow_creates_entry_with_webhook(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    path = result["description_placeholders"]["path"]
    assert path.startswith("/api/webhook/")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Vevor weather station"
    assert path == f"/api/webhook/{result['data'][CONF_WEBHOOK_ID]}"


async def test_only_one_instance_allowed(hass):
    MockConfigEntry(domain=DOMAIN, data={CONF_WEBHOOK_ID: "x"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-ha/bin/pytest tests/integration/test_config_flow.py -v`
Expected: FAIL (`Integration 'vevor_wu' not found` / missing manifest).

- [ ] **Step 3: Write the implementation**

`custom_components/vevor_wu/manifest.json`:
```json
{
  "domain": "vevor_wu",
  "name": "Vevor weather station (Wunderground proxy)",
  "codeowners": [],
  "config_flow": true,
  "dependencies": ["webhook"],
  "documentation": "https://github.com/szimano/weather-ha",
  "iot_class": "local_push",
  "requirements": [],
  "version": "0.1.0"
}
```

`custom_components/vevor_wu/const.py`:
```python
"""Constants for the Vevor weather station integration."""
from datetime import timedelta

DOMAIN = "vevor_wu"
STALE_AFTER = timedelta(minutes=10)


def signal_update(entry_id: str) -> str:
    """Dispatcher signal fired when a new reading is stored."""
    return f"{DOMAIN}_update_{entry_id}"
```

`custom_components/vevor_wu/config_flow.py`:
```python
"""Config flow: generates the webhook the proxy posts readings to."""
from __future__ import annotations

from typing import Any

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_WEBHOOK_ID

from .const import DOMAIN


class VevorWuConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._webhook_id: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if self._webhook_id is None:
            self._webhook_id = webhook.async_generate_id()
        if user_input is not None:
            return self.async_create_entry(
                title="Vevor weather station",
                data={CONF_WEBHOOK_ID: self._webhook_id},
            )
        return self.async_show_form(
            step_id="user",
            description_placeholders={"path": f"/api/webhook/{self._webhook_id}"},
        )
```

`custom_components/vevor_wu/strings.json` and `custom_components/vevor_wu/translations/en.json` (identical content):
```json
{
  "config": {
    "step": {
      "user": {
        "title": "Vevor weather station",
        "description": "A webhook will be created for the proxy to post readings to. After setup, set the proxy's HA_WEBHOOK_URL to http://host.docker.internal:8123{path}"
      }
    },
    "abort": {
      "single_instance_allowed": "Only one Vevor weather station can be configured."
    }
  }
}
```

`custom_components/vevor_wu/__init__.py` (temporary minimal version):
```python
"""Vevor weather station integration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-ha/bin/pytest tests/integration -v`
Expected: all pass (12 passed).

- [ ] **Step 5: Commit**

```bash
git add custom_components tests
git commit -m "feat(integration): manifest, constants, and config flow" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Webhook handler and runtime data

**Files:**
- Modify: `custom_components/vevor_wu/__init__.py`
- Test: `tests/integration/test_webhook.py`

**Interfaces:**
- Consumes: `const.signal_update`, `readings.parse_readings`, `readings.unknown_params`.
- Produces: `VevorWuData` dataclass (`values: dict[str, float]`, `last_seen: datetime | None`, `seen_unknown: set[str]`) stored as `entry.runtime_data`; type alias `VevorWuConfigEntry`; `PLATFORMS: list[Platform]` (empty until Task 9); webhook POST handler that updates `values`, sets `last_seen` (only when at least one valid reading), and fires `signal_update(entry.entry_id)`. Returns 200 `ok`, or 400 for non-JSON / non-object bodies.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_webhook.py`:
```python
import pytest
from homeassistant.const import CONF_WEBHOOK_ID
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vevor_wu.const import DOMAIN

WEBHOOK_ID = "test-webhook-id"
URL = f"/api/webhook/{WEBHOOK_ID}"


@pytest.fixture
async def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_WEBHOOK_ID: WEBHOOK_ID},
        title="Vevor weather station",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_post_stores_metric_readings(hass, hass_client_no_auth, entry):
    client = await hass_client_no_auth()
    resp = await client.post(URL, json={"ID": "X", "tempf": "50.0", "humidity": "60"})
    assert resp.status == 200
    assert entry.runtime_data.values == {"temperature": 10.0, "humidity": 60.0}
    assert entry.runtime_data.last_seen is not None


async def test_later_post_keeps_previous_values_for_missing_fields(
    hass, hass_client_no_auth, entry
):
    client = await hass_client_no_auth()
    await client.post(URL, json={"tempf": "50.0", "humidity": "60"})
    await client.post(URL, json={"tempf": "68.0", "humidity": "--"})
    assert entry.runtime_data.values == {"temperature": 20.0, "humidity": 60.0}


async def test_payload_without_valid_readings_does_not_refresh_last_seen(
    hass, hass_client_no_auth, entry
):
    client = await hass_client_no_auth()
    resp = await client.post(URL, json={"ID": "X", "tempf": "--"})
    assert resp.status == 200
    assert entry.runtime_data.values == {}
    assert entry.runtime_data.last_seen is None


async def test_invalid_json_is_rejected(hass, hass_client_no_auth, entry):
    client = await hass_client_no_auth()
    resp = await client.post(URL, data="not json")
    assert resp.status == 400


async def test_non_object_json_is_rejected(hass, hass_client_no_auth, entry):
    client = await hass_client_no_auth()
    resp = await client.post(URL, json=[1, 2, 3])
    assert resp.status == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-ha/bin/pytest tests/integration/test_webhook.py -v`
Expected: FAIL (`AttributeError: ... has no attribute 'runtime_data'` / 404 from the unregistered webhook).

- [ ] **Step 3: Write the implementation**

Replace `custom_components/vevor_wu/__init__.py` with:
```python
"""Vevor weather station integration: receives readings from the proxy."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import DOMAIN, signal_update
from .readings import parse_readings, unknown_params

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = []


@dataclass
class VevorWuData:
    values: dict[str, float] = field(default_factory=dict)
    last_seen: datetime | None = None
    seen_unknown: set[str] = field(default_factory=set)


type VevorWuConfigEntry = ConfigEntry[VevorWuData]


def _make_handler(entry: VevorWuConfigEntry):
    async def _handle(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        try:
            payload = await request.json()
        except ValueError:
            return web.Response(status=400, text="invalid json")
        if not isinstance(payload, dict):
            return web.Response(status=400, text="expected a json object")

        data = entry.runtime_data
        new_unknown = unknown_params(payload) - data.seen_unknown
        if new_unknown:
            data.seen_unknown |= new_unknown
            _LOGGER.debug("Ignoring unknown station parameters: %s", sorted(new_unknown))

        readings = parse_readings(payload)
        if readings:
            data.values.update(readings)
            data.last_seen = dt_util.utcnow()
            async_dispatcher_send(hass, signal_update(entry.entry_id))
        return web.Response(text="ok")

    return _handle


async def async_setup_entry(hass: HomeAssistant, entry: VevorWuConfigEntry) -> bool:
    entry.runtime_data = VevorWuData()
    webhook.async_register(
        hass,
        DOMAIN,
        entry.title,
        entry.data[CONF_WEBHOOK_ID],
        _make_handler(entry),
        local_only=True,
        allowed_methods=["POST"],
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VevorWuConfigEntry) -> bool:
    webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-ha/bin/pytest tests/integration -v`
Expected: all pass (17 passed).

- [ ] **Step 5: Commit**

```bash
git add custom_components tests
git commit -m "feat(integration): webhook handler storing metric readings" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Sensors with push updates and staleness

**Files:**
- Create: `custom_components/vevor_wu/sensor.py`
- Modify: `custom_components/vevor_wu/__init__.py` (set `PLATFORMS = [Platform.SENSOR]`)
- Test: `tests/integration/test_sensor.py`

**Interfaces:**
- Consumes: `VevorWuConfigEntry` / `VevorWuData` (Task 8), `const.signal_update`, `const.STALE_AFTER`. Sensor keys must match `readings.SPECS` keys.
- Produces: `sensor.async_setup_entry`; one device ("Vevor weather station", model YT60234); entities `sensor.vevor_weather_station_<name>` for temperature, dew point, humidity, pressure, wind speed, wind gust, wind direction, rain last hour, rain today, uv index, solar radiation, plus the diagnostic `last_update` timestamp. All are `unavailable` until the first reading and again after `STALE_AFTER` of silence.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_sensor.py`:
```python
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_WEBHOOK_ID, STATE_UNAVAILABLE
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.vevor_wu.const import DOMAIN

WEBHOOK_ID = "test-webhook-id"
URL = f"/api/webhook/{WEBHOOK_ID}"
FULL = {
    "ID": "X",
    "tempf": "50.0",
    "dewptf": "41.0",
    "humidity": "60",
    "baromin": "29.92",
    "windspeedmph": "10",
    "windgustmph": "15",
    "winddir": "270",
    "rainin": "0.1",
    "dailyrainin": "0.25",
    "UV": "3",
    "solarRadiation": "500.5",
}


@pytest.fixture
async def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_WEBHOOK_ID: WEBHOOK_ID},
        title="Vevor weather station",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _state(hass, name):
    return hass.states.get(f"sensor.vevor_weather_station_{name}")


async def test_sensors_unavailable_before_first_reading(hass, entry):
    assert _state(hass, "temperature").state == STATE_UNAVAILABLE
    assert _state(hass, "last_update").state == STATE_UNAVAILABLE


async def test_sensors_show_metric_values_after_post(hass, hass_client_no_auth, entry):
    client = await hass_client_no_auth()
    await client.post(URL, json=FULL)
    await hass.async_block_till_done()

    expected = {
        "temperature": ("10.0", "°C"),
        "dew_point": ("5.0", "°C"),
        "humidity": ("60.0", "%"),
        "pressure": ("1013.2", "hPa"),
        "wind_speed": ("16.1", "km/h"),
        "wind_gust": ("24.1", "km/h"),
        "wind_direction": ("270.0", "°"),
        "rain_last_hour": ("2.54", "mm"),
        "rain_today": ("6.35", "mm"),
        "uv_index": ("3.0", "UV index"),
        "solar_radiation": ("500.5", "W/m²"),
    }
    for name, (value, unit) in expected.items():
        state = _state(hass, name)
        assert state.state == value, name
        assert state.attributes["unit_of_measurement"] == unit, name
    assert _state(hass, "last_update").state != STATE_UNAVAILABLE


async def test_field_missing_from_later_post_is_unknown_until_reported(
    hass, hass_client_no_auth, entry
):
    client = await hass_client_no_auth()
    await client.post(URL, json={"tempf": "50.0"})
    await hass.async_block_till_done()
    assert _state(hass, "temperature").state == "10.0"
    assert _state(hass, "humidity").state == "unknown"


async def test_sensors_become_unavailable_after_silence(
    hass, hass_client_no_auth, entry
):
    client = await hass_client_no_auth()
    await client.post(URL, json=FULL)
    await hass.async_block_till_done()
    assert _state(hass, "temperature").state == "10.0"

    future = dt_util.utcnow() + timedelta(minutes=11)
    with patch("custom_components.vevor_wu.sensor.dt_util.utcnow", return_value=future):
        async_fire_time_changed(hass, future)
        await hass.async_block_till_done()
    assert _state(hass, "temperature").state == STATE_UNAVAILABLE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-ha/bin/pytest tests/integration/test_sensor.py -v`
Expected: FAIL (`AttributeError: 'NoneType' object has no attribute 'state'`: no entities exist).

- [ ] **Step 3: Write the implementation**

In `custom_components/vevor_wu/__init__.py` change `PLATFORMS: list[Platform] = []` to:
```python
PLATFORMS: list[Platform] = [Platform.SENSOR]
```

`custom_components/vevor_wu/sensor.py`:
```python
"""Sensors for the Vevor weather station; state is pushed by the webhook."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfIrradiance,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import VevorWuConfigEntry
from .const import DOMAIN, STALE_AFTER, signal_update

MEASUREMENT = SensorStateClass.MEASUREMENT

DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="dew_point",
        name="Dew point",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="pressure",
        name="Pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="wind_speed",
        name="Wind speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="wind_gust",
        name="Wind gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="wind_direction",
        name="Wind direction",
        native_unit_of_measurement=DEGREE,
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="rain_last_hour",
        name="Rain last hour",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
    ),
    SensorEntityDescription(
        key="rain_today",
        name="Rain today",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="uv_index",
        name="UV index",
        native_unit_of_measurement="UV index",
        state_class=MEASUREMENT,
    ),
    SensorEntityDescription(
        key="solar_radiation",
        name="Solar radiation",
        device_class=SensorDeviceClass.IRRADIANCE,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        state_class=MEASUREMENT,
    ),
)

LAST_UPDATE = SensorEntityDescription(
    key="last_update",
    name="Last update",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VevorWuConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[VevorWuSensor] = [VevorWuSensor(entry, d) for d in DESCRIPTIONS]
    entities.append(VevorWuLastUpdateSensor(entry, LAST_UPDATE))
    async_add_entities(entities)


class VevorWuSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, entry: VevorWuConfigEntry, description: SensorEntityDescription
    ) -> None:
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Vevor weather station",
            manufacturer="Vevor",
            model="YT60234",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_update(self._entry.entry_id),
                self.async_write_ha_state,
            )
        )
        # Re-evaluate availability so sensors flip to unavailable during silence.
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._recheck_availability, timedelta(minutes=1)
            )
        )

    @callback
    def _recheck_availability(self, now: datetime) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        last_seen = self._entry.runtime_data.last_seen
        return last_seen is not None and dt_util.utcnow() - last_seen < STALE_AFTER

    @property
    def native_value(self) -> float | None:
        return self._entry.runtime_data.values.get(self.entity_description.key)


class VevorWuLastUpdateSensor(VevorWuSensor):
    @property
    def native_value(self) -> datetime | None:  # type: ignore[override]
        return self._entry.runtime_data.last_seen
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-ha/bin/pytest tests/integration -v`
Expected: all pass (21 passed). If a unit assertion fails because HA converted a value to a different display unit, adjust the sensor description (not the test) so the native unit is what the test expects.

- [ ] **Step 5: Run the whole suite in both venvs**

Run: `.venv-proxy/bin/pytest tests/proxy -q && .venv-ha/bin/pytest tests/integration -q`
Expected: 18 passed, then 21 passed.

- [ ] **Step 6: Commit**

```bash
git add custom_components tests
git commit -m "feat(integration): push-updated metric sensors with staleness" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Deploy and verify end to end

**Files:**
- Modify: `README.md` only if a checklist step needs correcting after the real run.

**Interfaces:**
- Consumes: everything above. Produces: a working deployment.

- [ ] **Step 1: Install the integration into HA**

Copy `custom_components/vevor_wu` into HA's `/config/custom_components/` (the host path mounted at `/config`), then restart HA. Use `ha_get_system_health(include="config_check")` first to confirm the config is valid.

- [ ] **Step 2: Add the integration and note the webhook path**

Settings > Devices & Services > Add Integration > "Vevor weather station". Copy the `/api/webhook/<id>` path from the dialog.
Expected: 12 sensors, all `unavailable`.

- [ ] **Step 3: Start the proxy**

Fill in `proxy/.env` (`HA_WEBHOOK_URL=http://host.docker.internal:8123/api/webhook/<id>`, `PROXY_IP`, `LAN_*`), then run `cd proxy && docker compose up -d --build`.
Expected: `docker ps` shows `wu-proxy` as `healthy`.

- [ ] **Step 4: Run the README end-to-end checklist up to the DNS step**

Run each unchecked item except the last three (they need the DNS record). In particular `docker exec wu-proxy ip route` must show the default route via the bridge network; if it shows the LAN gateway instead, `gw_priority` is unsupported by the installed Docker Engine: upgrade Docker or swap the two network priorities and re-check that `host.docker.internal` still resolves and is reachable.
Expected: the `curl` test prints `success` and HA shows 10.0 °C.

- [ ] **Step 5: Add the DNS record and watch real data**

Add `rtupdate.wunderground.com -> PROXY_IP` in Pi-hole/AdGuard, power-cycle the station (or wait for its next upload), then complete the last three checklist items.
Expected: HA sensors fill with the station's readings; Wunderground still shows fresh data; no unexpected 404s in `docker logs wu-proxy`.

- [ ] **Step 6: Commit any doc corrections**

```bash
git add -A
git commit -m "docs: correct deployment checklist after end-to-end run" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
(Skip if nothing changed.)
