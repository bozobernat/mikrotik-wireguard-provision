# mikrotik-wireguard-provision

Onboards an Android or Windows device into a **MikroTik router's WireGuard
server** — key generation, peer creation on the router, client config, QR code,
and delivery to the device — in one command.

```
python3 wg_provision.py provision --name "Phone" --platform android
```

Status: **in use, still being rolled out.** Several devices are live; the fleet
is not finished. Treat this as working code with an honest edge, not a polished
product.

*Magyar nyelvű leírás: [README.hu.md](README.hu.md)*

**License:** PolyForm Noncommercial 1.0.0 — free for any noncommercial use; commercial use needs a separate licence (see [License](#license)).

---

## The design decisions worth stealing

**Two router credentials, not one.** The script reads through one wrapper and
writes through a different one, each backed by its own RouterOS account and SSH
key (`read` group vs. write). Provisioning is rare; querying is constant. There
is no reason for the constant path to hold write access.

**The router is the source of truth for address allocation.** `wg_next_free_ip`
asks the router which addresses are taken, every time — it never infers free
addresses from the local registry. This is not theoretical: a stale registry
once claimed four peers when the router had more, and had the script trusted
it, the next device would have been handed a colliding address.

**The registry is inserted into, never rewritten.** A new device becomes a
single row placed directly under the table header; nothing else in the file is
touched, so a note you added by hand survives. If the header is not found
unchanged, the script exits rather than reformat a file it does not fully
understand.

**The private key never lands anywhere permanent — on this machine.** Keys are
generated in-process (X25519 via `cryptography` — no `wg` binary needed). The
`.conf` and the QR image go to a scratch directory, and the script tells you to
delete them after delivery. Only the **public** key reaches the registry.
Two things to know: the scratch directory is created with your umask, not
`0700`, so on a shared machine other users may be able to read it; and on the
Android path the `.conf` is pushed to `/sdcard/Download/` on the phone and
**stays there** — delete it from the phone too.

**The APK comes from WireGuard's own download server** — not APKMirror, not
APKPure — and its signature is checked with `apksigner` against a pinned signer
fingerprint before installation. The fingerprint in the source is the WireGuard
project's public signing certificate; it is not a secret. **Caveat:** `apksigner`
is looked for under `~/android-sdk/build-tools/*/`. If it is not there, the
check is *skipped with a warning* and the APK still installs — so install the
Android SDK build-tools if you want this guarantee.

**QR delivery is the primary path.** ADB push of a `.conf` is version-dependent
and fails quietly across Android versions; scanning a QR code in the WireGuard
app works everywhere. The QR is generated even when ADB succeeds.

## What it cannot do, and why

- **MAC randomization cannot be turned off from ADB.** There is no non-root
  command for it. The `pin-lan-ip` operation only works on a device whose real
  MAC is in use, so that step stays manual. The script prints the exact menu
  path instead of pretending.
- **The Automate flow for auto-toggling the tunnel at home cannot be
  scripted** either. Also printed as a manual step.
- **Windows delivery is half-automatic.** The config is generated; installing
  it needs elevated access on the target machine.
- **`pin-lan-ip` writes to the router.** After turning MAC randomization off,
  confirm the real MAC from `/interface/wifi/registration-table` — a
  *connected* device — rather than from a lease-list hostname match. Guessing
  wrong pins the wrong device.

> [!WARNING]
> **Read before use**
>
> This tool monitors network traffic and/or changes network and security
> settings. Use it only on networks you own, or have explicit permission from
> the operator to inspect — monitoring third-party networks without
> authorisation is unlawful in most jurisdictions. Treat generated keys,
> configuration files and logs as sensitive: never publish them. This is a
> personal project published without warranty, support or any service
> commitment; you assume all risk arising from its use.

## Setup

1. **Router wrappers.** Copy both files in `bin/` from `.example`. Each takes a
   RouterOS command as `$1` and prints the output. Use two separate RouterOS
   accounts.
2. **Dependencies:** `pip install -r requirements.txt` (`cryptography`, `segno`).
   External tools, depending on what you use: `curl` (downloads the APK from the
   internet), `adb` (Android delivery), and `apksigner` from the Android SDK
   build-tools (signature check — optional, see above).
3. **Configure by environment variable** — `WG_ENDPOINT` is required, the rest
   have defaults:

| Variable | Default | Meaning |
|---|---|---|
| `WG_ENDPOINT` | — **required** | public `host:port` of the WG server |
| `WG_ROUTER_READ_CMD` | `~/bin/mikrotik-ssh.sh` | read-only router wrapper |
| `WG_ROUTER_WRITE_CMD` | `~/bin/mikrotik-ssh-admin.sh` | write router wrapper |
| `WG_INTERFACE` | `wireguard1` | WG interface name on the router |
| `WG_SUBNET` | `10.10.10.0/24` | the WireGuard subnet |
| `LAN_SUBNET` | `192.168.88.0/24` | the internal LAN (MikroTik factory default) |
| `WG_DNS` | first host of `LAN_SUBNET` | DNS handed to clients |
| `WG_HOME_SSID` | *(empty)* | home SSIDs, shown in the manual steps |
| `WG_INTERNAL_DOMAIN` | `lan` | internal domain for the CA note |
| `WG_ROOT_CA` | *(none)* | internal root CA `.crt`; skipped if unset |
| `WG_SCRATCH` | `<tempdir>/wg-provision` | where the private key is written |
| `WG_APK_CACHE` | `~/.cache/wg-provision/…apk` | cached WireGuard APK |

4. Copy `registry.example.md` to `registry.md`. Both `registry.md` and your
   real wrappers are gitignored.

## Commands

```
wg_provision.py status                     # what the router currently has
wg_provision.py provision --name … --platform android|windows [--full-tunnel]
wg_provision.py pin-lan-ip --mac … --name …
```

`--dry-run` on `provision` generates the client config and QR **without** writing
to the router, updating the registry, or pushing to the device. On `pin-lan-ip`
it only prints the RouterOS command it would have run. (Windows delivery never
produces a QR — that path writes a `.conf` only.)

Default is split-tunnel: only LAN traffic goes through the tunnel. `--full-tunnel`
overrides this per device.

`--adb-serial` must be given **when any device is attached**: without it the
push is skipped with a warning, so the config cannot reach the wrong phone. Note
that this is a skipped push, not an abort — the peer is already on the router
and the registry is updated. Deliver the config by QR, or re-run with the
serial.

---

## Example output

Real output from a `status` call and a `provision --dry-run` call, both run
against a mock router wrapper — `WG_ROUTER_READ_CMD`/`WG_ROUTER_WRITE_CMD`
pointed at a throwaway script that returns made-up RouterOS data (a
placeholder WireGuard public key, three already-used addresses in the example
`10.10.10.0/24` subnet) instead of a real router. Nothing here touched a live
network; `--dry-run` also means the peer command shown was never actually sent.

```
$ python3 wg_provision.py status
Router publikus kulcsa: HmpR2XBbYbNsKL+IqcwQ2rLRlgx66XZrXzW50B2sxXY=
Foglalt WG-címek ma: 10.10.10.2, 10.10.10.5, 10.10.10.7
Következő szabad WG-cím: 10.10.10.3
```

```
$ python3 wg_provision.py provision --name "Teszt-Telefon" --platform android --dry-run
[DRY-RUN] router-peer NEM lett felvéve, csak a parancs:
  /interface/wireguard/peers/add interface=wireguard1 public-key="6ivkn+HjooigtVSiBsHI3eLMJywJcDxarUWBfwFVvyg=" allowed-address=10.10.10.3/32 comment="Teszt-Telefon"

--- Android kézbesítés: Teszt-Telefon ---
[DRY-RUN] ADB push kihagyva — csak a config+QR készült el helyben.
QR-kód (garantált, verzió-független út): /tmp/wg-provision/teszt-telefon-qr.png
A WireGuard-appban: „+” → „Scan from QR code”.

MANUÁLIS lépések ehhez az eszközhöz (nem automatizálhatók ADB-ből):
  1. Belső root CA telepítése (a .lan-szolgáltatások HTTPS-éhez): Beállítások → Biztonság → (Samsungon: Egyéb biztonsági beállítások →) Tanúsítványok telepítése → CA-tanúsítvány → sajat_belso_ca_root.crt a Letöltésekből. Android megmutat egy figyelmeztetést — ez OS-szintű védelem, el kell fogadni. (Egy `am start VIEW` intent-es próbálkozás a telepítő közvetlen megnyitására NEM vált be — élőben mérve nem nyitotta meg automatikusan, mindig kézi útra számíts.)
  2. Beállítások → WiFi → az otthoni WiFi-hálózat(ok) → (fogaskerék/Speciális) → Adatvédelem → „Eszköz MAC-címének használata” (mindkét sávra, ha külön mentett hálózat) — enélkül a router-oldali fix IP (lásd `pin-lan-ip`) minden csatlakozáskor máshova kötne. FONTOS: ez után a telefon ÚJ DHCP-lease-t kap (más IP-vel) — a `pin-lan-ip`-hez a valódi MAC-et a router `/interface/wifi/registration-table`-jából erősítsd meg (ténylegesen csatlakozva), ne csak a lease-lista hostname-egyezéséből.
  3. WireGuard-app → az importált tunnel szerkesztése → „...” → Applications → „Allowed applications” (include-only) → csak a Home Assistant appot pipáld be.
  4. (Opcionális) WiFi-alapú auto ki/be a tunnelhez, hogy otthon (az otthoni WiFi-hálózat(ok)) NE menjen a WireGuard: Automate (LlamaLab, Play Store) telepítése → WireGuard-app → Advanced → „Allow remote control apps” bekapcsolása → mindkét app akkumulátor-korlátozás alól kivéve („Unrestricted”) → Automate → Community → keresés „WiFi toggle Wireguard” → import, benne az SSID és a tunnel neve beírva (a tunnel neve valószínűleg „teszt-telefon”, ellenőrizd a WireGuard appban) → Automate → „Control Wireguard tunnels” jog engedélyezése. Egyik lépés sem automatizálható ADB-ből.
  5. Ha Home Assistant Companion App is van a telefonon → Beállítások → Companion App → Manage Sensors → szándékosan MINIMÁLIS készlet: Battery Level, Battery State, Charger Type, Wi-Fi Connection. Ennél többet ne kapcsolj be indok nélkül — minden szenzor adatot küld.

A privát kulcsot tartalmazó fájlokat (/tmp/wg-provision/teszt-telefon.conf, /tmp/wg-provision/teszt-telefon-qr.png) töröld a kézbesítés után — ezek átmeneti fájlok, nem verziókövetettek.

[DRY-RUN] registry.md NEM lett frissítve.
```

The public key in the peer command belongs to a disposable test keypair
generated for this run, not a real device. The full client `.conf` (which
does contain a private key) is written to disk but deliberately not printed
or reproduced here.

## How this was built, and what that means

The code was written by an AI coding agent (Claude). I specified the behaviour,
chose the trust model (split read/write credentials, live allocation, keys never
persisted), ran it against my own router and my own devices, hit the failure
modes, and I operate the result.

The parts worth reading are not the Python. They are the decisions above — and
the honesty about the four things it cannot do, each of which cost a real
attempt to discover.

Identifiers and inline comments are in Hungarian. The behaviour is fully
described above.

## License

This project is available under the **PolyForm Noncommercial License 1.0.0**
(see [LICENSE](LICENSE)). You may use, modify and share it free of charge,
without asking, **for any noncommercial purpose** — including personal and family
use, charitable organisations, educational institutions, publicly funded research
bodies, public health and public safety organisations, and government
institutions. Under the licence this holds regardless of how those organisations
are funded.

**Commercial use requires a separate licence from me.** That includes offering
the software, or a service built on it, for money — as a subscription, or bundled
with installation or a support desk. Open an issue at <https://github.com/bozobernat/mikrotik-wireguard-provision/issues> titled
"commercial licence". I am not against it; I want to know about it.

```
Required Notice: Copyright Bozó Bernát — https://github.com/bozobernat/mikrotik-wireguard-provision
```

*(Under the licence's "Notices" section, anyone who passes the software on must
keep this line.)* How the human and the machine contributions are separated:
[AUTHORSHIP.md](AUTHORSHIP.md).

### Contributing

Fixes are welcome. Before a pull request can be merged you need to sign
[CLA.md](CLA.md) — a short statement that I may also use your contribution,
including under commercial licences. Without it, your contribution would tie the
project's hands later.

### Trademarks

"WireGuard" and the "WireGuard" logo are registered trademarks of Jason A. Donenfeld. See <https://www.wireguard.com/>.

This project is not affiliated with, endorsed by, or sponsored by Mikrotikls SIA, the WireGuard project, Microsoft, or any other third party whose products it interoperates with. All trademarks are the property of their respective owners.
