# Deployment guide (Portainer)

Order matters: HA integration first, then the proxy, then Pi-hole, test with `curl`, and
only then point the station at Pi-hole. Until the station uses the DNS override, it keeps
talking to Wunderground directly and nothing can break.

Values used below (replace with yours): HA host `192.168.1.84`, NIC `enp8s0`, LAN
`192.168.1.0/24`, gateway `192.168.1.1`, proxy IP `192.168.1.60`, Pi-hole IP `192.168.1.61`.

## Step 0: Pre-flight (5 min)

1. **Find the station's IP and subnet** (UniFi > Clients, look for the Vevor/ESP device).
   The proxy's and Pi-hole's macvlan IPs **must be in the same subnet as the station**. Your
   network also has 192.168.2.x devices, so check. If the station is on 192.168.2.x, use
   free 192.168.2.x addresses and a 192.168.2.0/24 subnet and gateway below, and tell me:
   the host NIC must then also be on that VLAN.
2. **Pick two free IPs** outside the DHCP range (UniFi > Settings > Networks), one for the
   proxy and one for Pi-hole, ideally reserved. Example: `192.168.1.60` and `192.168.1.61`.
3. **Check the Docker Engine version** on the HA host: `docker version`. Engine 28+ is
   needed for `gw_priority`. If older, see "Troubleshooting".
4. **Check the gateway and NIC** on the HA host: `ip route | grep default`. The line shows
   `via <gateway> dev <nic>`.

## Step 1: Install the integration into HA

1. In Portainer, open the HA container and find which host folder is mounted at
   `/config` (Volumes / Binds section).
2. From your Mac, copy the integration into that folder:
   ```bash
   scp -r /Users/szimano/code/weather-ha/custom_components/vevor_wu \
     USER@192.168.1.84:/PATH/TO/HA/CONFIG/custom_components/
   ```
   If `custom_components` doesn't exist there yet, create it (your other custom
   components such as `sonoff` and `filetrack` already live there).
3. Restart HA (Portainer: restart the HA container, or Developer Tools > Restart).
4. Settings > Devices & Services > Add Integration > search **"Vevor weather station"**.
5. The dialog shows `http://host.docker.internal:8123/api/webhook/<ID>`. **Copy the
   `<ID>` now.** It is shown only on this screen. Then click Submit.
   If you lose it, delete the integration and add it again for a new ID.
6. You now have a device "Vevor weather station" with 12 sensors, all `unavailable`.

## Step 2: Build the image on the HA host

The image built during development is on the Mac, not the server. Build it on the
server's Docker:

1. On your Mac:
   ```bash
   cd /Users/szimano/code/weather-ha/proxy
   tar czf ~/wu-proxy-build.tar.gz --exclude=.env --exclude=__pycache__ .
   ```
2. In Portainer, select the **HA host's environment**, then Images > **Build a new image**.
3. Name: `wu-proxy:latest`. Method: **Upload**, choose `~/wu-proxy-build.tar.gz`.
   Click **Build the image** and wait for the success output.

## Step 3: Create the shared macvlan network (once)

The proxy and Pi-hole both need their own LAN IP, so they share one macvlan network.
Create it once in Portainer instead of inside a stack (two stacks can't each create a
macvlan on the same subnet):

Portainer > Networks > Add network:
- Name: `wu_lan`
- Driver: `macvlan`
- Subnet: `192.168.1.0/24` (the station's subnet), Gateway: `192.168.1.1`
- Parent network card: `enp8s0` (your NIC from step 0)
- Leave the rest as is, then **Create the network**.

## Step 4: Create the proxy stack

Portainer > Stacks > Add stack > name `wu-proxy` > Web editor. Paste this and edit the
two marked values:

```yaml
services:
  wu-proxy:
    image: wu-proxy:latest
    container_name: wu-proxy
    restart: unless-stopped
    environment:
      HA_WEBHOOK_URL: "http://host.docker.internal:8123/api/webhook/PASTE_ID_HERE"   # <- your ID
      BIND_HOST: "192.168.1.60"                                                      # <- proxy IP
      PORT: "80"
      LOG_LEVEL: "INFO"
    dns:
      - 1.1.1.1
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks:
      bridge_net:
        gw_priority: 10
      lan:
        ipv4_address: 192.168.1.60                                                   # <- proxy IP
        gw_priority: 0

networks:
  bridge_net: {}
  lan:
    external: true
    name: wu_lan
```

Click **Deploy the stack**. The container should show `healthy` after about 30 s.

Notes:
- Do not use the Pi-hole as this container's DNS: the relay would resolve
  `rtupdate.wunderground.com` to itself and loop. `1.1.1.1` is pinned on purpose.
- `HA_WEBHOOK_URL` is a secret (the ID protects the webhook). Treat the stack like a password.

## Step 5: Verify the proxy (before touching DNS)

1. **Default route.** Portainer > Containers > `wu-proxy` > Console (`/bin/sh`), run
   `cat /proc/net/route`. The row with Destination `00000000` is the default route.
   Its **Iface must be the bridge interface**, not the macvlan one. To tell them apart,
   open the container's Inspect > Networks: the interface on `wu_lan` has
   `192.168.1.60`, the one on `wu-proxy_bridge_net` has a `172.x.x.x` address, and
   `cat /proc/net/dev` lists the interface names (`eth0`, `eth1`).
2. **HA reachable from the container.** In the same console:
   `python -c "import urllib.request as u; print(u.urlopen('http://host.docker.internal:8123/').status)"`
   Any HTTP status (even 401/404) is fine; a timeout means the host firewall blocks the
   Docker subnet from port 8123 (allow it).
3. **Relay path.** In the console:
   `python -c "import urllib.request as u; print(u.urlopen('https://rtupdate.wunderground.com/').status)"`
   Any HTTP answer (even 404) is fine; a timeout means no internet path.
4. **End to end, from another machine** (not the Docker host, which cannot reach a
   macvlan address):
   ```bash
   curl "http://192.168.1.60/weatherstation/updateweatherstation.php?ID=TEST&PASSWORD=x&tempf=50&humidity=60"
   ```
   Expected output: `success`. This also relays `ID=TEST` to Wunderground, which just
   rejects it (harmless).
5. In HA, Developer Tools > States: `sensor.vevor_weather_station_temperature` should be
   `10.0` (°C) and humidity `60.0`. If not, check container logs (Portainer > Logs):
   a `HA webhook returned HTTP ...` line shows the cause (404 = wrong webhook ID,
   403 = webhook refused the source address).

## Step 6: Set up Pi-hole (Docker)

Pi-hole is the DNS server that answers `rtupdate.wunderground.com` with the proxy's IP and
forwards everything else normally. It gets its own LAN IP on the same `wu_lan` network, so
it needs no port mappings and cannot clash with ports 53/80 on the HA host.

If you already run Pi-hole or AdGuard elsewhere, skip this step and just add the DNS record
from step 7.

1. Portainer > Stacks > Add stack > name `pihole` > Web editor:

   ```yaml
   services:
     pihole:
       image: pihole/pihole:latest
       container_name: pihole
       hostname: pihole
       restart: unless-stopped
       environment:
         TZ: "Europe/Warsaw"
         FTLCONF_webserver_api_password: "CHANGE_ME"        # <- web UI password
         FTLCONF_dns_upstreams: "1.1.1.1;8.8.8.8"           # upstream resolvers
       volumes:
         - pihole_etc:/etc/pihole
       networks:
         lan:
           ipv4_address: 192.168.1.61                       # <- Pi-hole IP

   volumes:
     pihole_etc: {}

   networks:
     lan:
       external: true
       name: wu_lan
   ```

   Click **Deploy the stack**. This is the current (v6) image; its variables start with
   `FTLCONF_`. Use a strong password and keep it out of screenshots.
2. Open `http://192.168.1.61/admin` from another machine on the LAN and log in. (The
   Docker host itself cannot reach a macvlan address, so test from your Mac.)
3. Add the override: Local DNS > DNS Records > add domain `rtupdate.wunderground.com`,
   IP `192.168.1.60` (the proxy), then Add.
4. Test from your Mac:
   ```bash
   dig @192.168.1.61 rtupdate.wunderground.com +short   # expect 192.168.1.60
   dig @192.168.1.61 example.com +short                  # expect a normal public address
   ```
   If the second query is refused, Pi-hole is rejecting the source: add the environment
   variable `FTLCONF_dns_listeningMode: "ALL"` to the stack and redeploy.

## Step 7: Switch the station over (DNS)

The station has to ask Pi-hole for DNS. The simple way is to hand Pi-hole out through DHCP:

1. UniFi > Settings > Networks > (the station's network) > DHCP Name Server: set to
   **Manual**, DNS server 1 = `192.168.1.61`. Leave server 2 **empty**: a second public
   resolver lets the station skip the override whenever it picks that one.
   Trade-off: every device on that network now uses Pi-hole, so if the Pi-hole container
   is down, DNS is down. It restarts automatically (`unless-stopped`), but you could also
   limit the change to the station's network/VLAN.
2. Power-cycle the station (it re-reads DHCP and flushes its DNS cache).
3. Pi-hole > Query Log should show the station asking for `rtupdate.wunderground.com` and
   getting `192.168.1.60`. If you see a different hostname, tell me. If you see nothing,
   the station is not using Pi-hole (it may have a hardcoded DNS server, in which case it
   needs a UniFi firewall/NAT rule redirecting its DNS traffic to Pi-hole).
4. Within a few minutes: the HA sensors fill with real values, Wunderground's dashboard for
   your station still updates, and the `wu-proxy` logs show no warnings.

## Rollback

Remove the Pi-hole DHCP DNS setting in UniFi (or delete the `rtupdate.wunderground.com`
record in Pi-hole) and power-cycle the station. It talks to Wunderground directly again.
Then stop or remove the stacks if you want.

## Troubleshooting

- **Stack rejects `gw_priority`** (older Portainer/Compose): delete the two
  `gw_priority` lines. Docker then orders gateways by network name, and `bridge_net`
  sorts before `wu_lan`, which is the order we want on older engines. Re-check step 5.1.
- **Default route is the macvlan interface:** HA becomes unreachable (step 5.2 fails).
  Fix the priority as above, or upgrade Docker Engine.
- **Station gets no answer:** it must be on the same subnet/VLAN as the proxy IP, and
  nothing else may use that IP.
- **Port 80 refused:** check the container is running and `BIND_HOST` equals its `wu_lan` IP.
- **More detail in logs:** set `LOG_LEVEL` to `DEBUG` temporarily to see each relay
  status. The station password is never logged.
- **Your UDM supports local DNS records** (UniFi Network settings with a DNS/Local Records
  section): you can skip Pi-hole entirely and add an A record for
  `rtupdate.wunderground.com` -> `192.168.1.60` there.
