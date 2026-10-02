# Vevor Weather Station Local Proxy + Home Assistant Integration — Design

Date: 2026-10-02
Status: Draft, pending user review

## Goal

A Vevor YT60234 weather station uploads readings to Weather Underground. Capture
those readings locally in Home Assistant (fast, no cloud round trip) while still
reporting to Weather Underground exactly as before.

## Background

- The station sends plain **HTTP on port 80**:
  `GET /weatherstation/updateweatherstation.php?ID=...&PASSWORD=...&tempf=...`
  to `rtupdate.wunderground.com`. Wunderground replies `success`.
- The station has no custom-server setting, so interception is a **DNS override**
  (Pi-hole / AdGuard / similar) pointing that hostname at the proxy.
- Query params: `ID`, `PASSWORD`, `dateutc`, `tempf`, `humidity`, `baromin`,
  `dewptf`, `rainin`, `dailyrainin`, `winddir`, `windspeedmph`, `windgustmph`,
  `UV`, `solarRadiation`.
- Prior art: VevorWeatherbridge (Docker, MQTT). We deliberately differ: native HA
  integration via webhook, and relay uses the station's own credentials.
- Environment: HA Container 2026.9.x on the same Docker host as the proxy; HA uses
  `network_mode: host` (192.168.1.84).
- `rainin` in the Wunderground protocol is rain accumulated over the last hour
  (inches); `dailyrainin` is rain since local midnight.

## Architecture

```
weather-ha/
├── proxy/                      # own container
│   ├── app.py                  # aiohttp server on :80
│   ├── Dockerfile
│   └── compose.yml             # macvlan (own LAN IP) + default bridge, dns: 1.1.1.1
├── custom_components/vevor_wu/ # installed into /config/custom_components
│   ├── manifest.json, __init__.py, const.py
│   ├── config_flow.py          # generates webhook ID, shows URL for proxy config
│   ├── webhook.py              # receives readings from the proxy
│   └── sensor.py               # one device, sensor entities
└── tests/                      # pytest for both halves
```

Language: Python for both parts.

### Proxy

- Serves `GET /weatherstation/updateweatherstation.php`; other paths return 404 and
  are logged. `GET /healthz` for the Docker HEALTHCHECK.
- Config via env: `HA_WEBHOOK_URL`, `UPSTREAM_URL` (default
  `https://rtupdate.wunderground.com`), `RELAY_ENABLED`, `BIND_HOST` (the macvlan IP),
  `PORT` (default 80).
- aiohttp access logging is disabled: it would print the query string, including the
  station password.
- Relay upstream over **HTTPS** by default (configurable).
- Stateless; no database, no queue.

### Network (approach A: dual-homed container)

- Interface 1: macvlan with its own LAN IP. Pi-hole resolves
  `rtupdate.wunderground.com` to this IP; the station connects here on :80.
- Interface 2: a Docker bridge network, which carries the container's **default
  route** (`gw_priority`, Docker Engine 28+). It is used to reach HA via
  `host.docker.internal` (`extra_hosts: host-gateway`), avoiding macvlan host
  isolation, and for the upstream relay (NAT via the host). The macvlan interface only
  receives the station's traffic. HA runs with `network_mode: host` (confirmed), so it
  listens on all host interfaces including the bridge gateway.
- Container DNS pinned (`dns: 1.1.1.1`) so the upstream relay does not resolve to
  the overridden record and loop to itself.

## Data flow

1. Station sends `GET` to the proxy.
2. Proxy parses the query and immediately replies `success` (200, text/plain).
3. Two independent background tasks:
   - **To HA:** `POST` JSON to the webhook, 5 s timeout, `PASSWORD` stripped.
   - **To Wunderground:** replay the original query unchanged (real `PASSWORD`),
     10 s timeout, log only the status code.
4. Failures are logged (password redacted) and dropped. No retry, no disk buffer;
   the station re-sends regularly.

## Home Assistant entities

One device ("Vevor weather station", model YT60234) with all entities created at
setup (unavailable until the first reading), so nothing depends on the station `ID`.
`Rain last hour` has no state class (the precipitation device class only allows
total-type state classes). The integration
converts to **metric at ingest**, so native values and units are metric. The proxy
forwards raw imperial values to HA; it forwards imperial to Wunderground unchanged.

| Query param | Entity | Device class | Native unit | Conversion |
|---|---|---|---|---|
| `tempf` | Temperature | temperature | °C | (°F − 32) × 5/9 |
| `dewptf` | Dew point | temperature | °C | (°F − 32) × 5/9 |
| `humidity` | Humidity | humidity | % | none |
| `baromin` | Pressure | pressure | hPa | inHg × 33.8639 |
| `windspeedmph` | Wind speed | wind_speed | km/h | mph × 1.609344 |
| `windgustmph` | Wind gust | wind_speed | km/h | mph × 1.609344 |
| `winddir` | Wind direction | — | ° | none |
| `rainin` | Rain last hour | precipitation (no state class) | mm | in × 25.4 |
| `dailyrainin` | Rain today | precipitation (`total_increasing`) | mm | in × 25.4 |
| `UV` | UV index | — | UV index | none |
| `solarRadiation` | Solar radiation | irradiance | W/m² | none |
| (receipt time) | Last update | timestamp (diagnostic) | — | — |

Rounding: 1 decimal, 2 for rain.

- Unknown params are ignored and logged once at debug level.
- Empty or non-numeric values (`--`, `-9999`) are skipped per field; the sensor keeps
  its previous value.
- All sensors become `unavailable` after 10 minutes without a reading.
- `dateutc` is ignored; receipt time is used (station clock is untrusted).
- Push model via `async_dispatcher_send`; no coordinator.

## Error handling and security

- Webhook registered `local_only=True`; the webhook ID is the secret.
- Station always receives `success`, regardless of HA or Wunderground outcome.
  Behavior change vs. today: the station will not notice if the internet is down.
- Proxy hardening: single route, query string capped at 4 KB, no auth (station
  cannot send any), listens on the macvlan IP only.
- `PASSWORD` stripped before HA and redacted in all logs.
- Failures logged at warning level; no crash, no retry.

## Testing

- **Proxy** (pytest + aiohttp test client; HA and Wunderground mocked): valid request
  returns `success`; HA payload excludes `PASSWORD`; upstream request carries the
  original query; HA/upstream failures do not alter the response; unknown path 404;
  oversized query rejected; logs contain no password.
- **Integration** (pytest-homeassistant-custom-component): config flow creates the
  webhook; payload creates expected entities with correct metric values; bad values
  skipped; unavailable after 10 minutes of silence.
- **Conversions:** known values (32 °F → 0 °C, 29.92 inHg → ~1013 hPa).
- **End to end (manual):** add the Pi-hole record, start the container, confirm
  entities appear, confirm `ID`/`PASSWORD` arrive unchanged on Wunderground.

## Out of scope

Retry queue or persistence, authentication on the proxy, HTTPS termination for the
station, MQTT delivery, multiple stations, RF decoding.
