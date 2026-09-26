#!/usr/bin/env python3
# Copyright 2026 Bozó Bernát
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright Bozó Bernát — https://github.com/bozobernat/mikrotik-wireguard-provision
"""wg_provision.py — Android/Windows eszköz bevonása egy MikroTik router
WireGuard-szerverébe, kulcsgenerálástól a kliens-oldali kézbesítésig.

Két, egymástól független művelet:

    provision   — WG-kulcspár generálása, peer felvétele a routeren,
                  kliens-config + QR-kód előállítása, kézbesítés Android
                  (ADB) vagy Windows felé.
    pin-lan-ip  — egy már csatlakozott eszköz DYNAMIC DHCP-lease-ét STATIC-ra
                  állítja (`make-static`) a router LAN-oldalán, hogy mindig
                  ugyanazt az IP-t kapja, és a router-alapú jelenlét-követés
                  stabilan lássa. EZ ELŐFELTÉTELEZI, hogy a telefonon a
                  MAC-randomizáció ki van kapcsolva az otthoni hálózatokra —
                  véletlen MAC-re nem lehet tartós lease-t kötni, mert minden
                  csatlakozáskor másik cím jönne. Ez a lépés Android-oldalon
                  ma NEM automatizálható ADB-ből (nincs rá nem-root parancs),
                  tehát kézi lépés marad.

A `provision` és a `pin-lan-ip` ÍR a routeren — ehhez külön, írásra jogosult
wrapper kell (l. WG_ROUTER_WRITE_CMD). Ha az nem áll, a szkript ezt tisztán
jelzi, nem hamis sikert.

Privát kulcs SOHA nem kerül verziókövetés alá: a generált kliens-config és a
QR-kód a scratch könyvtárba íródik, kézbesítés után törlendő — a `registry.md`
nyilvántartásba csak a PUBLIKUS kulcs kerül.

Használat:
    python3 wg_provision.py provision --name "Telefon" --platform android
    python3 wg_provision.py provision --name "MUNKA-PC" --platform windows --full-tunnel
    python3 wg_provision.py pin-lan-ip --mac AA:BB:CC:DD:EE:FF --name "Telefon"
    python3 wg_provision.py status

Konfiguráció — környezeti változók (l. README):

    WG_ROUTER_READ_CMD    olvasó router-wrapper       alap: ~/bin/mikrotik-ssh.sh
    WG_ROUTER_WRITE_CMD   ÍRÓ router-wrapper          alap: ~/bin/mikrotik-ssh-admin.sh
    WG_INTERFACE          a router WG-interfésze      alap: wireguard1
    WG_SUBNET             a WG-alhálózat              alap: 10.10.10.0/24
    WG_ENDPOINT           publikus végpont:port       KÖTELEZŐ
    WG_DNS                a klienseknek adott DNS     alap: a LAN átjáró
    LAN_SUBNET            a belső LAN                 alap: 192.168.88.0/24
    WG_HOME_SSID          otthoni SSID-k, vesszővel   alap: (üres)
    WG_INTERNAL_DOMAIN    belső domain a CA-hoz       alap: lan
    WG_ROOT_CA            belső root CA .crt útja     alap: (nincs, kimarad)
    WG_SCRATCH            hova írja a privát kulcsot  alap: rendszer-tempdir

Függőségek: `cryptography` (X25519), `segno` (QR).
"""

import argparse
import glob
import ipaddress
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone

PROJEKT_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FAJL = os.path.join(PROJEKT_DIR, "registry.md")

# A routert két külön wrapper éri el: egy CSAK OLVASÓ és egy ÍRÓ. A kettő
# szétválasztása szándékos — a napi lekérdezés ne írhasson. A wrapper egyetlen
# elvárása: kapjon egy RouterOS-parancsot $1-ben, és írja a kimenetet stdoutra.
MT = os.environ.get(
    "WG_ROUTER_READ_CMD", os.path.expanduser("~/bin/mikrotik-ssh.sh"))
MT_ADMIN = os.environ.get(
    "WG_ROUTER_WRITE_CMD", os.path.expanduser("~/bin/mikrotik-ssh-admin.sh"))

WG_INTERFACE = os.environ.get("WG_INTERFACE", "wireguard1")
WG_PREFIX = ipaddress.ip_network(os.environ.get("WG_SUBNET", "10.10.10.0/24"))
WG_ENDPOINT = os.environ.get("WG_ENDPOINT", "")
LAN_PREFIX = os.environ.get("LAN_SUBNET", "192.168.88.0/24")
WG_DNS = os.environ.get(
    "WG_DNS", str(next(ipaddress.ip_network(LAN_PREFIX).hosts())))

# Otthoni SSID-k (vesszővel elválasztva) — csak a kiírt kézi lépésekben
# jelennek meg, a szkript logikáját nem érintik.
HOME_SSID = os.environ.get("WG_HOME_SSID", "").strip()
_SSID_TXT = HOME_SSID if HOME_SSID else "az otthoni WiFi-hálózat(ok)"

# A belső szolgáltatások domainje (pl. "lan" → valami.lan, masik.lan).
INTERNAL_DOMAIN = os.environ.get("WG_INTERNAL_DOMAIN", "lan")

# Belső root CA — publikus tanúsítvány, nem titok. Ha meg van adva, minden
# bevont eszközre felkerül, hogy a belső HTTPS-szolgáltatások ne adjanak
# cert-hibát. Ha nincs, ez a lépés csendben kimarad.
ROOT_CA_PATH = os.environ.get("WG_ROOT_CA", "")

# Hivatalos WireGuard Android APK — a WireGuard projekt SAJÁT letöltő-
# szerveréről (download.wireguard.com), NEM harmadik féltől (APKMirror/
# APKPure stb.) — ez tudatos döntés. Aláírás
# ellenőrizve `apksigner`-rel telepítés előtt: "O=WireGuard LLC,
# CN=WireGuard Android Infrastructure". Cache-elve, hogy ne töltsük le
# minden eszközhöz újra.
WIREGUARD_APK_URL = "https://download.wireguard.com/android-client/com.wireguard.android-1.0.20260315.apk"
WIREGUARD_APK_CACHE = os.path.expanduser(
    os.environ.get("WG_APK_CACHE", "~/.cache/wg-provision/wireguard-android.apk"))
WIREGUARD_PACKAGE = "com.wireguard.android"
WIREGUARD_SIGNER_SHA256 = (
    "84a13fa2c4e0064b0c11654b8a86574b7a9b9352a3834cee32455b061c3d4127"
)

# Ide kerul a privat kulcsot tartalmazo config es a QR — kezbesites utan
# torlendo. Alapbol a rendszer tempdir-je alatt; a jogosultsag a umask szerinti
# (l. README), megosztott gepen allitsd WG_SCRATCH-et sajat, 0700-as mappara.
SCRATCH_DIR = os.environ.get(
    "WG_SCRATCH", os.path.join(tempfile.gettempdir(), "wg-provision"))


def _fut(parancs: list, timeout: int = 20) -> tuple:
    """(stdout, hiba) — a stdout üres/hibás, ha hiba nem None."""
    try:
        p = subprocess.run(parancs, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"időtúllépés ({timeout}s)"
    except FileNotFoundError:
        return None, f"a parancs nem található: {parancs[0]}"
    if p.returncode != 0:
        hiba = (p.stderr or p.stdout or "").strip().splitlines()
        return None, (hiba[-1][:400] if hiba else f"exit kód {p.returncode}")
    return p.stdout, None


def mt_read(routeros_parancs: str, timeout: int = 20) -> str:
    out, hiba = _fut([MT, routeros_parancs], timeout=timeout)
    if hiba:
        sys.exit(f"olvasó lekérdezés sikertelen ({MT}): {hiba}")
    return out or ""


def mt_write(routeros_parancs: str, timeout: int = 20) -> str:
    out, hiba = _fut([MT_ADMIN, routeros_parancs], timeout=timeout)
    if hiba:
        sys.exit(
            f"ÍRÓ csatorna sikertelen ({MT_ADMIN}): "
            f"{hiba}\n\n"
            "Az ÍRÓ wrapper (WG_ROUTER_WRITE_CMD) nem működik — enélkül a\n"
            "router-oldal nem automatizálható. Ellenőrizd, hogy a wrapper létezik,\n"
            "futtatható, és a mögötte lévő RouterOS-fiók írásra jogosult."
        )
    return out or ""


# --------------------------------------------------------------------------
# Router-oldali lekérdezések
# --------------------------------------------------------------------------

def router_public_key() -> str:
    parancs = f':put [/interface/wireguard/get [find name="{WG_INTERFACE}"] public-key]'
    return mt_read(parancs).strip()


def wg_used_ips() -> set:
    """A WG-alhálózatban már foglalt címek a peer-listából (allowed-address /32-k)."""
    parancs = (
        f':foreach p in=[/interface/wireguard/peers/find interface="{WG_INTERFACE}"] '
        f'do={{:put [/interface/wireguard/peers/get $p allowed-address]}}'
    )
    out = mt_read(parancs)
    hasznalt = set()
    for sor in out.strip().splitlines():
        sor = sor.strip()
        if not sor:
            continue
        for darab in sor.split(","):
            darab = darab.strip().split("/")[0]
            try:
                cim = ipaddress.ip_address(darab)
            except ValueError:
                continue
            if cim in WG_PREFIX:
                hasznalt.add(cim)
    return hasznalt


def wg_next_free_ip() -> ipaddress.IPv4Address:
    """A router-oldalt ÉLŐBEN kérdezi le, sosem a registry.md-ből feltételezi
    (egy elavult nyilvántartás korábban 4 peert
    mutatott, élőben 5 volt)."""
    hasznalt = wg_used_ips()
    for cim in WG_PREFIX.hosts():
        if cim == WG_PREFIX.network_address + 1:  # .1 — maga a router
            continue
        if cim not in hasznalt:
            return cim
    sys.exit(f"nincs szabad cím a {WG_PREFIX}-ban")


def dhcp_dynamic_leases() -> list:
    """[(ip, mac, hostname, comment)] — csak DYNAMIC (D flag) lease-ek."""
    parancs = (
        ':foreach l in=[/ip/dhcp-server/lease/find dynamic=yes] do={:put '
        '(  [/ip/dhcp-server/lease/get $l address] . "|" '
        '. [/ip/dhcp-server/lease/get $l mac-address] . "|" '
        '. [/ip/dhcp-server/lease/get $l host-name] . "|" '
        '. [/ip/dhcp-server/lease/get $l comment] )}'
    )
    out = mt_read(parancs)
    talalatok = []
    for sor in out.strip().splitlines():
        reszek = sor.strip().split("|")
        if len(reszek) >= 2:
            ip, mac = reszek[0].strip(), reszek[1].strip()
            hostname = reszek[2].strip() if len(reszek) > 2 else ""
            comment = reszek[3].strip() if len(reszek) > 3 else ""
            talalatok.append((ip, mac, hostname, comment))
    return talalatok


# --------------------------------------------------------------------------
# Kulcsgenerálás — tiszta Python, `wg` bináris nélkül (nem kell telepíteni)
# --------------------------------------------------------------------------

def genkeypair() -> tuple:
    """(privát_b64, publikus_b64) — WG ugyanaz a formátum, mint egy nyers
    X25519 kulcspár base64-ben (RFC 7748), a `wg genkey`/`wg pubkey` is ezt
    csinálja a háttérben."""
    from cryptography.hazmat.primitives.asymmetric import x25519
    from cryptography.hazmat.primitives import serialization
    import base64

    priv = x25519.X25519PrivateKey.generate()
    priv_b = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_b = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(priv_b).decode(), base64.b64encode(pub_b).decode()


# --------------------------------------------------------------------------
# Kliens-config
# --------------------------------------------------------------------------

def _endpoint_kotelezo():
    """Csak a `provision` allit elo kliens-configot, tehat csak annak kell a
    publikus vegpont. A `status` es a `pin-lan-ip` enelkul is mukodik."""
    if not WG_ENDPOINT:
        sys.exit("WG_ENDPOINT nincs beállítva (pl. vpn.example.com:51820) — l. README.")


_KOMMENT_MINTA = re.compile(r"\A[\w .-]+\Z", re.UNICODE)


def mt_komment_ellenoriz(szoveg: str) -> str:
    """A `--name` értéke RouterOS-parancsba kerül `comment="..."` alakban —
    idézőjelet vagy egyéb, a RouterOS-parancsnyelvet megzavaró karaktert nem
    tartalmazhat, különben egy rosszul (vagy szándékosan rosszul) megválasztott
    --name RouterOS-parancs-injekciót tenne lehetővé. A `wg_tunnel_nev()`-vel
    ellentétben itt NEM vágjuk/alakítjuk a szöveget — a teljes, ékezetes nevet
    meg kell tartani a commentben és a registry.md-ben, csak a veszélyes
    karaktereket zárjuk ki, hibával leállva, ha ilyet találunk."""
    if not _KOMMENT_MINTA.match(szoveg):
        sys.exit(
            f'a --name érték ("{szoveg}") RouterOS-parancsba kerül, ezért csak '
            "betűt, számot, szóközt, pontot, kötőjelet és aláhúzást "
            "tartalmazhat."
        )
    return szoveg


def wg_tunnel_nev(nev: str, max_hossz: int = 15) -> str:
    """A fájlnév (kiterjesztés nélkül) lesz a WireGuard-appban az alagút
    neve importáláskor — az app ezt a régi Linux IFNAMSIZ-konvenció szerint
    max 15 karakterre, ékezet/speciális karakter nélkül korlátozza. Élőben
    megbukott: egy 17 karakteres és egy 18 karakteres (ékezetes) eszköznév
    egyaránt „nem importálható” hibát adott a WireGuard appban, egy 13
    karakteres viszont ment. Ezért a nevet ékezet nélkülre alakítjuk és 15
    karakterre vágjuk — a TELJES,
    ékezetes eszköznév továbbra is megvan a peer-commentben és a
    registry.md-ben, csak a fájl/alagút-nevet érinti."""
    nfkd = unicodedata.normalize("NFKD", nev)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    if len(slug) > max_hossz:
        slug = slug[:max_hossz].rstrip("-")
    return slug or "wgeszkoz"


def build_client_config(priv_key: str, device_ip: ipaddress.IPv4Address,
                         router_pubkey: str, full_tunnel: bool) -> str:
    if full_tunnel:
        allowed_ips = "0.0.0.0/0, ::/0"
    else:
        allowed_ips = f"{LAN_PREFIX}, {WG_PREFIX}"
    return (
        "[Interface]\n"
        f"PrivateKey = {priv_key}\n"
        f"Address = {device_ip}/32\n"
        f"DNS = {WG_DNS}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {router_pubkey}\n"
        f"Endpoint = {WG_ENDPOINT}\n"
        f"AllowedIPs = {allowed_ips}\n"
        "PersistentKeepalive = 25\n"
    )


def registry_sor_beszur(nev: str, platform: str, ip, pubkey: str, mod: str):
    """Célzott beszúrás a registry.md táblázat végére — nem teljes újraírás
    — hogy egy párhuzamos szerkesztés ne vesszen el némán."""
    datum = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    sor = f"| {nev} | {platform} | {ip} | {pubkey} | {datum} | {mod} |\n"
    with open(REGISTRY_FAJL, encoding="utf-8") as f:
        tartalom = f.read()
    jelolo = "|---|---|---|---|---|---|\n"
    if jelolo not in tartalom:
        sys.exit(f"a registry.md táblázat-fejléce nem található változatlan formában — "
                  f"ellenőrizd kézzel, nem írom felül automatikusan: {REGISTRY_FAJL}")
    if sor in tartalom:
        return  # már benne van, ne duplikáljuk
    uj_tartalom = tartalom.replace(jelolo, jelolo + sor, 1)
    with open(REGISTRY_FAJL, "w", encoding="utf-8") as f:
        f.write(uj_tartalom)


# --------------------------------------------------------------------------
# Kézbesítés
# --------------------------------------------------------------------------

def wireguard_app_telepitve(adb_serial: str) -> bool:
    out, _ = _fut(["adb", "-s", adb_serial, "shell", "pm", "list", "packages",
                   WIREGUARD_PACKAGE], timeout=15)
    return bool(out and WIREGUARD_PACKAGE in out)


def wireguard_apk_biztosit() -> str:
    """Letölti (ha még nincs cache-elve) és aláírás szerint ellenőrzi a
    hivatalos WireGuard APK-t. Kizárólag download.wireguard.com — l. a
    modul tetején a „Döntések" kommentet. Visszaadja a helyi útvonalat."""
    if not os.path.exists(WIREGUARD_APK_CACHE):
        os.makedirs(os.path.dirname(WIREGUARD_APK_CACHE), exist_ok=True)
        print(f"WireGuard APK letöltése ({WIREGUARD_APK_URL})...")
        _, hiba = _fut(["curl", "-sL", "-o", WIREGUARD_APK_CACHE, WIREGUARD_APK_URL],
                        timeout=120)
        if hiba or not os.path.exists(WIREGUARD_APK_CACHE):
            sys.exit(f"WireGuard APK letöltése sikertelen: {hiba}")
    apksigner_glob = os.path.expanduser("~/android-sdk/build-tools/*/apksigner")
    talalatok = sorted(glob.glob(apksigner_glob), reverse=True)
    if not talalatok:
        print("⚠️ apksigner nem található — aláírás-ellenőrzés kihagyva, "
              "csak a hivatalos forrás-URL véd.")
        return WIREGUARD_APK_CACHE
    out, hiba = _fut([talalatok[0], "verify", "--print-certs", WIREGUARD_APK_CACHE],
                      timeout=30)
    if hiba or WIREGUARD_SIGNER_SHA256 not in (out or ""):
        sys.exit(
            "⚠️ A cache-elt WireGuard APK aláírása NEM egyezik a várt "
            f"„WireGuard LLC”-vel ({WIREGUARD_SIGNER_SHA256}) — "
            f"NEM telepítem. Töröld a cache-t ({WIREGUARD_APK_CACHE}) és "
            "próbáld újra, hogy friss letöltés induljon."
        )
    return WIREGUARD_APK_CACHE


def wireguard_app_telepit(adb_serial: str):
    apk_path = wireguard_apk_biztosit()
    print(f"WireGuard app telepítése ({adb_serial})...")
    out, hiba = _fut(["adb", "-s", adb_serial, "install", apk_path], timeout=60)
    if hiba or "Success" not in (out or ""):
        sys.exit(f"WireGuard app telepítése sikertelen: {hiba or out}")
    print("WireGuard app telepítve.")


def qr_keszit(config_text: str, ki_fajl: str):
    try:
        import segno
    except ImportError:
        sys.exit(
            "a `segno` csomag nincs telepítve ebben az interpreterben — futtasd a "
            "`pip install -r requirements.txt`, vagy futtasd azzal a venv-vel, "
            "amelyikbe telepítve van."
        )
    qr = segno.make(config_text, micro=False)
    qr.save(ki_fajl, scale=8, border=4)


def android_kezbesit(nev: str, config_text: str, adb_serial: str, dry_run: bool):
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    # A slug itt LESZ az alagút neve is a WireGuard appban (a fájlnévből
    # veszi át importáláskor) — max 15 karakter, ékezet nélkül, l.
    # wg_tunnel_nev() docstringje.
    slug = wg_tunnel_nev(nev)
    conf_path = os.path.join(SCRATCH_DIR, f"{slug}.conf")
    qr_path = os.path.join(SCRATCH_DIR, f"{slug}-qr.png")

    with open(conf_path, "w", encoding="utf-8") as f:
        f.write(config_text)
    qr_keszit(config_text, qr_path)

    print(f"\n--- Android kézbesítés: {nev} ---")

    adb = "adb"
    out, hiba = _fut([adb, "devices", "-l"], timeout=10)
    ket_soros = (out or "").strip().splitlines()
    csatlakozott = [s for s in ket_soros[1:] if "\tdevice" in s or " device " in s]

    if dry_run:
        print("[DRY-RUN] ADB push kihagyva — csak a config+QR készült el helyben.")
        if csatlakozott:
            print("Figyelem: van csatlakoztatott ADB-eszköz "
                  f"({len(csatlakozott)} db) — éles futtatásnál KÖTELEZŐ "
                  "az --adb-serial megadása, hogy ne a véletlenül épp "
                  "csatlakoztatott (pl. egy másik projekt) eszközre menjen.")
    elif hiba or not csatlakozott:
        print("Nincs csatlakoztatott/engedélyezett ADB-eszköz "
              "(`adb devices` üres vagy hibás) — csak a QR-kódot készítettem el, "
              "azt kell beolvasni a WireGuard-appban.")
    elif not adb_serial:
        print("⚠️ VAN csatlakoztatott ADB-eszköz, de --adb-serial nincs megadva — "
              "SZÁNDÉKOSAN nem push-olok, nehogy egy másik, épp csatlakoztatott "
              "eszközre kerüljön a config. Csatlakoztatott "
              f"eszközök: {'; '.join(csatlakozott) or '(nincs részlet)'}. "
              "Add meg: --adb-serial <serial vagy ip:port>.")
    else:
        talalt = [s for s in csatlakozott if s.startswith(adb_serial)]
        if not talalt:
            print(f"⚠️ A megadott --adb-serial ({adb_serial}) nem szerepel a "
                  f"csatlakoztatott eszközök közt ({'; '.join(csatlakozott)}) — "
                  "nem push-olok.")
        else:
            if not wireguard_app_telepitve(adb_serial):
                print("A WireGuard app nincs fent — telepítem (hivatalos "
                      "download.wireguard.com APK, aláírás-ellenőrizve).")
                wireguard_app_telepit(adb_serial)
            target_path = f"/sdcard/Download/{slug}.conf"
            _, push_hiba = _fut([adb, "-s", adb_serial, "push", conf_path, target_path],
                                 timeout=20)
            if push_hiba:
                print(f"adb push sikertelen ({push_hiba}) — QR-kód a fallback.")
            else:
                print(f"Config feltéve ADB-vel ({adb_serial}): {target_path} "
                      "(a WireGuard-appban: „+” → „Create from file or archive”).")
            if os.path.exists(ROOT_CA_PATH):
                ca_target = "/sdcard/Download/sajat_belso_ca_root.crt"
                _, ca_hiba = _fut([adb, "-s", adb_serial, "push", ROOT_CA_PATH, ca_target],
                                   timeout=20)
                if ca_hiba:
                    print(f"Root CA push sikertelen ({ca_hiba}) — ezt is kézzel kell "
                          f"átvinni, ha kell a .{INTERNAL_DOMAIN}-szolgáltatásokhoz.")
                else:
                    print(f"Belső root CA is feltéve ADB-vel: {ca_target} "
                          "(telepítés: l. az 1. manuális lépést lent).")

    print(f"QR-kód (garantált, verzió-független út): {qr_path}")
    print("A WireGuard-appban: „+” → „Scan from QR code”.")
    print("\nMANUÁLIS lépések ehhez az eszközhöz (nem automatizálhatók ADB-ből):")
    print(f"  1. Belső root CA telepítése (a .{INTERNAL_DOMAIN}-szolgáltatások "
          "HTTPS-éhez): Beállítások → Biztonság "
          "→ (Samsungon: Egyéb biztonsági beállítások →) Tanúsítványok "
          "telepítése → CA-tanúsítvány → sajat_belso_ca_root.crt a "
          "Letöltésekből. Android megmutat egy figyelmeztetést — ez OS-szintű "
          "védelem, el kell fogadni. (Egy `am start VIEW` intent-es "
          "próbálkozás a telepítő közvetlen megnyitására NEM vált be — "
          "élőben mérve nem nyitotta meg automatikusan, mindig kézi útra "
          "számíts.)")
    print(f"  2. Beállítások → WiFi → {_SSID_TXT} → (fogaskerék/Speciális) → "
          "Adatvédelem → „Eszköz MAC-címének használata” (mindkét sávra, ha külön "
          "mentett hálózat) — enélkül a router-oldali fix IP (lásd `pin-lan-ip`) "
          "minden csatlakozáskor máshova kötne. FONTOS: ez után a telefon ÚJ "
          "DHCP-lease-t kap (más IP-vel) — a `pin-lan-ip`-hez a valódi MAC-et "
          "a router `/interface/wifi/registration-table`-jából erősítsd meg "
          "(ténylegesen csatlakozva), ne csak a lease-lista hostname-egyezéséből.")
    print("  3. WireGuard-app → az importált tunnel szerkesztése → „...” → "
          "Applications → „Allowed applications” (include-only) → csak a "
          "Home Assistant appot pipáld be.")
    print(f"  4. (Opcionális) WiFi-alapú auto ki/be a tunnelhez, hogy "
          f"otthon ({_SSID_TXT}) NE menjen a WireGuard: Automate "
          "(LlamaLab, Play Store) telepítése → WireGuard-app → Advanced → "
          "„Allow remote control apps” bekapcsolása → mindkét app "
          "akkumulátor-korlátozás alól kivéve („Unrestricted”) → Automate → "
          "Community → keresés „WiFi toggle Wireguard” → import, benne az "
          "SSID és a tunnel neve beírva (a tunnel neve valószínűleg "
          f"„{slug}”, ellenőrizd a WireGuard appban) → Automate → "
          "„Control Wireguard tunnels” jog engedélyezése. Egyik lépés sem "
          "automatizálható ADB-ből.")
    print("  5. Ha Home Assistant Companion App is van a telefonon → Beállítások "
          "→ Companion App → Manage Sensors → szándékosan MINIMÁLIS készlet: "
          "Battery Level, Battery State, Charger Type, Wi-Fi Connection. Ennél "
          "többet ne kapcsolj be indok nélkül — minden szenzor adatot küld.")
    print(f"\nA privát kulcsot tartalmazó fájlokat ({conf_path}, {qr_path}) töröld "
          "a kézbesítés után — ezek átmeneti fájlok, nem verziókövetettek.")


def windows_kezbesit(nev: str, config_text: str):
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    slug = wg_tunnel_nev(nev)
    conf_path = os.path.join(SCRATCH_DIR, f"{slug}.conf")
    with open(conf_path, "w", encoding="utf-8") as f:
        f.write(config_text)
    print(f"\n--- Windows kézbesítés: {nev} ---")
    print(f"Config elkészült: {conf_path}")
    print("Ehhez a lépéshez emelt jogú hozzáférés kell a célgéphez.")
    print("Admin PowerShellben a célgépen:")
    print("  1. WireGuard for Windows telepítése, ha hiányzik: "
          "msiexec /i wireguard-installer.msi /quiet")
    print(f"  2. wireguard.exe /installtunnelservice <a config útja a célgépen>")
    print("A privát kulcsot tartalmazó config fájlt töröld a célgépről és innen is "
          "a kézbesítés után.")


# --------------------------------------------------------------------------
# Parancsok
# --------------------------------------------------------------------------

def cmd_status(_args):
    pubkey = router_public_key()
    hasznalt = sorted(wg_used_ips())
    kovetkezo = wg_next_free_ip()
    print(f"Router publikus kulcsa: {pubkey}")
    print(f"Foglalt WG-címek ma: {', '.join(str(c) for c in hasznalt) or '(nincs)'}")
    print(f"Következő szabad WG-cím: {kovetkezo}")


def cmd_provision(args):
    _endpoint_kotelezo()
    if not args.name.strip():
        sys.exit("--name kötelező")
    mt_komment_ellenoriz(args.name)

    pubkey = router_public_key()
    device_ip = wg_next_free_ip()
    priv_b64, pub_b64 = genkeypair()

    peer_parancs = (
        f'/interface/wireguard/peers/add interface={WG_INTERFACE} '
        f'public-key="{pub_b64}" allowed-address={device_ip}/32 '
        f'comment="{args.name}"'
    )
    if args.dry_run:
        print("[DRY-RUN] router-peer NEM lett felvéve, csak a parancs:")
        print(f"  {peer_parancs}")
    else:
        mt_write(peer_parancs)
        print(f"Peer felvéve a routeren: {args.name} → {device_ip}/32")

    config_text = build_client_config(priv_b64, device_ip, pubkey, args.full_tunnel)

    if args.platform == "android":
        android_kezbesit(args.name, config_text, args.adb_serial, args.dry_run)
    elif args.platform == "windows":
        windows_kezbesit(args.name, config_text)
    else:
        sys.exit(f"ismeretlen platform: {args.platform}")

    mod = "full-tunnel" if args.full_tunnel else "split-tunnel"
    if not args.dry_run:
        registry_sor_beszur(args.name, args.platform, device_ip, pub_b64, mod)
        print(f"\nregistry.md frissítve (csak publikus adat).")
    else:
        print("\n[DRY-RUN] registry.md NEM lett frissítve.")


_MAC_MINTA = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


def cmd_pin_lan_ip(args):
    mt_komment_ellenoriz(args.name)
    mac = args.mac.strip().upper()
    if not _MAC_MINTA.match(mac):
        sys.exit(f"érvénytelen MAC-cím formátum: {mac} (várt: AA:BB:CC:DD:EE:FF)")
    leasek = dhcp_dynamic_leases()
    talalat = [l for l in leasek if l[1].upper() == mac]
    if not talalat:
        sys.exit(
            f"nincs DYNAMIC lease ehhez a MAC-hez ({mac}) — az eszköznek előbb "
            f"csatlakoznia kell ehhez: {_SSID_TXT} — KIKAPCSOLT "
            "MAC-randomizációval (lásd a `provision` android-ági manuális lépéseit)."
        )
    ip, mac_talalt, hostname, _ = talalat[0]
    print(f"DYNAMIC lease találva: {ip} ({mac_talalt}, hostname={hostname or '(nincs)'})")

    parancs = f'/ip/dhcp-server/lease/make-static [find mac-address="{mac}"]'
    if args.dry_run:
        print(f"[DRY-RUN] NEM futtatva: {parancs}")
        return
    mt_write(parancs)
    # A comment-et is frissítjük, hogy a lease-lista (mint a többi eszköznél)
    # emberi névvel legyen olvasható.
    comment_parancs = (
        f'/ip/dhcp-server/lease/set [find mac-address="{mac}"] comment="{args.name}"'
    )
    mt_write(comment_parancs)
    print(f"STATIC lease kész: {ip} mindig ehhez a MAC-hez ({mac}) lesz kötve, "
          f"comment=\"{args.name}\". A router-alapú jelenlét-követés ettől "
          "kezdve stabilan lát rá.")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="parancs", required=True)

    p_status = sub.add_parser("status", help="router WG-állapot lekérdezése")
    p_status.set_defaults(func=cmd_status)

    p_prov = sub.add_parser("provision", help="új eszköz bevonása a WireGuardba")
    p_prov.add_argument("--name", required=True, help="eszköznév (peer comment, registry)")
    p_prov.add_argument("--platform", required=True, choices=["android", "windows"])
    p_prov.add_argument("--full-tunnel", action="store_true",
                         help="alapból split-tunnel (csak a LAN megy a tunnelen); "
                              "ezzel a kapcsolóval eszközönként felülírható")
    p_prov.add_argument("--dry-run", action="store_true",
                         help="router-írás, registry.md-frissítés és ADB push nélkül, "
                              "csak a kliens-config/QR előállítása")
    p_prov.add_argument("--adb-serial", default="",
                         help="melyik csatlakoztatott ADB-eszközre menjen a push "
                              "(`adb devices -l`-ből) — ha VAN csatlakoztatott eszköz, "
                              "ez KÖTELEZŐ, hogy ne a rossz eszközre menjen a config")
    p_prov.set_defaults(func=cmd_provision)

    p_pin = sub.add_parser("pin-lan-ip", help="dinamikus DHCP-lease static-ra állítása")
    p_pin.add_argument("--mac", required=True, help="az eszköz VALÓDI (nem randomizált) MAC-je")
    p_pin.add_argument("--name", required=True, help="lease comment")
    p_pin.add_argument("--dry-run", action="store_true")
    p_pin.set_defaults(func=cmd_pin_lan_ip)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
