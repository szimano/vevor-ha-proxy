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
