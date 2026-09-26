# mikrotik-wireguard-provision

Android- vagy Windows-eszközt von be egy **MikroTik router WireGuard-
szerverébe** — kulcsgenerálás, peer felvétele a routeren, kliens-config,
QR-kód és kézbesítés az eszközre — egyetlen paranccsal.

```
python3 wg_provision.py provision --name "Telefon" --platform android
```

Állapot: **használatban, de még kigurítás alatt.** Több eszköz él vele, a flotta
nincs kész. Működő kód, őszinte peremmel — nem kifényezett termék.

*(English version: [README.md](README.md))*

**Licenc:** PolyForm Noncommercial 1.0.0 — nem kereskedelmi célra szabadon használható; kereskedelmi felhasználáshoz külön engedély kell (l. [Licenc](#licenc)).

---

## A tervezési döntések, amiket érdemes ellopni

**Két router-hitelesítés, nem egy.** A szkript az egyik wrapperen keresztül
olvas, egy másikon keresztül ír, mindkettő mögött saját RouterOS-fiók és saját
SSH-kulcs (`read` csoport vs. írás). A bevonás ritka, a lekérdezés folyamatos.
Semmi nem indokolja, hogy a folyamatos útnak írásjoga legyen.

**A címkiosztásban a router az igazság forrása.** A `wg_next_free_ip` minden
alkalommal a routertől kérdezi meg, mely címek foglaltak — soha nem a helyi
nyilvántartásból következtet szabad címre. Ez nem elméleti kérdés: egy elavult
nyilvántartás egyszer négy peert állított, miközben a routeren több volt, és ha
a szkript hitt volna neki, a következő eszköz ütköző címet kapott volna.

**A nyilvántartásba beszúr, nem újraírja.** Egy új eszköz egyetlen sor lesz,
közvetlenül a táblázat fejléce alatt; a fájl többi részéhez nem nyúl, tehát a
kézzel odaírt megjegyzésed megmarad. Ha a fejlécet nem találja változatlan
formában, inkább leáll, mint hogy újraformázzon egy fájlt, amit nem ért
teljesen.

**A privát kulcs ezen a gépen nem marad meg tartósan.** A kulcsok a folyamaton
belül generálódnak (X25519 a `cryptography`-val — nem kell hozzá `wg` bináris).
A `.conf` és a QR-kép egy scratch könyvtárba kerül, és a szkript meg is mondja,
hogy kézbesítés után töröld. A nyilvántartásba csak a **publikus** kulcs jut el.
Két dolgot érdemes tudni: a scratch könyvtár a te umaskoddal jön létre, nem
`0700`-zal, tehát megosztott gépen más felhasználók is olvashatják; az
Android-ágon pedig a `.conf` felkerül a telefon `/sdcard/Download/` mappájába,
és **ott is marad** — a telefonról is töröld le.

**Az APK a WireGuard saját letöltőszerveréről jön** — nem APKMirrorról, nem
APKPure-ról —, és az aláírását `apksigner`-rel veti össze egy rögzített
aláíró-ujjlenyomattal, telepítés előtt. A forrásban lévő ujjlenyomat a
WireGuard projekt publikus aláíró tanúsítványa; nem titok. **Figyelem:** az
`apksigner`-t a `~/android-sdk/build-tools/*/` alatt keresi. Ha ott nincs, az
ellenőrzés *figyelmeztetéssel kimarad*, és az APK ettől még feltelepül — ha
kell ez a garancia, telepítsd az Android SDK build-toolst.

**A QR-kézbesítés az elsődleges út.** Egy `.conf` ADB-vel átküldve
verziófüggő, és Android-verziók között csendben elhasal; a QR-kód beolvasása a
WireGuard-appban mindenhol működik. A QR akkor is elkészül, ha az ADB sikerül.

## Amit nem tud, és miért

- **A MAC-randomizációt nem lehet ADB-ből kikapcsolni.** Nincs rá nem-root
  parancs. A `pin-lan-ip` csak olyan eszközön működik, ami a valódi MAC-jét
  használja, tehát ez a lépés kézi marad. A szkript kiírja a pontos menüutat,
  ahelyett hogy úgy tenne, mintha menne.
- **Az Automate-flow** (a tunnel automatikus ki/be kapcsolása otthon) **szintén
  nem szkriptelhető.** Ez is kiírt kézi lépés.
- **A Windows-kézbesítés félig automatikus.** A config elkészül; a telepítéséhez
  emelt jogú hozzáférés kell a célgépen.
- **A `pin-lan-ip` ír a routeren.** A MAC-randomizáció kikapcsolása után a
  valódi MAC-et a `/interface/wifi/registration-table`-ből erősítsd meg — egy
  *ténylegesen csatlakozott* eszközről —, ne a lease-lista hostname-egyezéséből.
  Rossz tipp esetén a rossz eszközt rögzíted.

> [!WARNING]
> **Figyelmeztetés — olvasd el használat előtt**
>
> Ez az eszköz hálózati forgalmat figyel, illetve hálózati és biztonsági
> beállításokat módosít. Kizárólag olyan hálózaton használd, amely a tiéd,
> vagy amelynek vizsgálatára a hálózat üzemeltetőjétől kifejezett engedélyed
> van — idegen hálózat engedély nélküli megfigyelése a legtöbb joghatóságban
> jogszabályba ütközik. A generált kulcsokat, konfigurációkat és naplófájlokat
> érzékeny adatként kezeld: ne töltsd fel őket nyilvános tárhelyre. Ezt
> személyes projektként, ellenszolgáltatás nélkül teszem közzé, garancia és
> támogatási kötelezettség nélkül; a használatból eredő bármilyen kárért,
> adatvesztésért vagy jogsértésért a felelősség a felhasználóé.

## Beállítás

1. **Router-wrapperek.** Másold mindkét fájlt a `bin/`-ben a `.example`-ből.
   Mindkettő egy RouterOS-parancsot kap `$1`-ben, és kiírja a kimenetet. Két
   külön RouterOS-fiókot használj.
2. **Függőségek:** `pip install -r requirements.txt` (`cryptography`, `segno`).
   Külső eszközök, attól függően, mit használsz: `curl` (az APK letöltése az
   internetről), `adb` (Android-kézbesítés), és `apksigner` az Android SDK
   build-toolsból (aláírás-ellenőrzés — opcionális, l. fent).
3. **Konfiguráció környezeti változóval** — a `WG_ENDPOINT` kötelező, a többinek
   van alapértéke:

| Változó | Alapérték | Mire való |
|---|---|---|
| `WG_ENDPOINT` | — **kötelező** | a WG-szerver publikus `host:port`-ja |
| `WG_ROUTER_READ_CMD` | `~/bin/mikrotik-ssh.sh` | csak olvasó router-wrapper |
| `WG_ROUTER_WRITE_CMD` | `~/bin/mikrotik-ssh-admin.sh` | író router-wrapper |
| `WG_INTERFACE` | `wireguard1` | a WG-interfész neve a routeren |
| `WG_SUBNET` | `10.10.10.0/24` | a WireGuard-alhálózat |
| `LAN_SUBNET` | `192.168.88.0/24` | a belső LAN (a MikroTik gyári alapértéke) |
| `WG_DNS` | a `LAN_SUBNET` első hosztja | a klienseknek adott DNS |
| `WG_HOME_SSID` | *(üres)* | otthoni SSID-k, a kézi lépésekben jelenik meg |
| `WG_INTERNAL_DOMAIN` | `lan` | belső domain a CA-megjegyzéshez |
| `WG_ROOT_CA` | *(nincs)* | belső root CA `.crt`; ha nincs, kimarad |
| `WG_SCRATCH` | `<tempdir>/wg-provision` | ide írja a privát kulcsot |
| `WG_APK_CACHE` | `~/.cache/wg-provision/…apk` | a gyorsítótárazott WireGuard APK |

4. Másold a `registry.example.md`-t `registry.md`-re. A `registry.md` és a
   valódi wrappereid is gitignore-olva vannak.

## Parancsok

```
wg_provision.py status                     # mi van most a routeren
wg_provision.py provision --name … --platform android|windows [--full-tunnel]
wg_provision.py pin-lan-ip --mac … --name …
```

A `--dry-run` a `provision`-nál előállítja a kliens-configot és a QR-t **anélkül**,
hogy a routerre írna, frissítené a nyilvántartást vagy pusholna az eszközre. A
`pin-lan-ip`-nél csak kiírja azt a RouterOS-parancsot, amit lefuttatott volna.
(A Windows-kézbesítés soha nem készít QR-t — az az ág csak `.conf`-ot ír.)

Alapértelmezés a split-tunnel: csak a LAN-forgalom megy az alagúton. A
`--full-tunnel` ezt eszközönként felülírja.

Az `--adb-serial`-t **meg kell adni, ha van csatlakoztatott eszköz**: enélkül a
push figyelmeztetéssel kimarad, tehát a config nem kerülhet rossz telefonra. Ez
kihagyott push, nem leállás — a peer ilyenkor már felkerült a routerre, és a
nyilvántartás is frissült. Kézbesítsd QR-rel, vagy futtasd újra a sorozatszámmal.

---

## Példa kimenet

Valódi kimenet egy `status` és egy `provision --dry-run` futásból, mindkettő
egy mock router-wrapperrel futtatva — a `WG_ROUTER_READ_CMD`/`WG_ROUTER_WRITE_CMD`
egy eldobható szkriptre mutatott, ami kitalált RouterOS-adatot ad vissza (egy
kitalált WG-publikuskulcsot, három már „foglalt” címet a példabeli
`10.10.10.0/24` alhálózatból) valódi router helyett. Ez nem érintett éles
hálózatot; a `--dry-run` miatt a kiírt peer-parancs sem futott le ténylegesen.

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

A peer-parancsban lévő publikus kulcs egy ehhez a próbafuttatáshoz generált,
eldobható kulcspárhoz tartozik, nem valódi eszközé. A teljes kliens-config
(ami már privát kulcsot is tartalmazna) lemezre kerül, de itt szándékosan nem
jelenik meg.

## Hogyan készült, és ez mit jelent

A kódot AI-ügynök (Claude) írta. Én határoztam meg a viselkedést, én döntöttem
el a bizalmi modellt (szétválasztott olvasó/író hitelesítés, élő címkiosztás,
sehol nem tárolt kulcsok), én futtattam a saját routeremen és a saját
eszközeimen, én futottam bele a hibamódokba, és én üzemeltetem az eredményt.

Amit érdemes elolvasni, az nem a Python. Hanem a fenti döntések — és az
őszinteség arról a négy dologról, amit nem tud, és amiknek mindegyike egy
valódi próbálkozásba került, mire kiderült.

Az azonosítók és a kommentek magyarul vannak.

## Licenc

Ez a projekt a **PolyForm Noncommercial License 1.0.0** alatt érhető el (lásd:
[LICENSE](LICENSE)). Ingyenesen, engedélykérés nélkül használhatod, módosíthatod
és továbbadhatod **bármilyen nem kereskedelmi célra**, ideértve kifejezetten:

- magánszemélyként, a saját vagy a hozzátartozód otthonában;
- jótékonysági szervezetként (pl. egyházi vagy karitatív szolgálat);
- oktatási intézményként és közfinanszírozott kutatóhelyként;
- közegészségügyi vagy közbiztonsági szervezetként;
- állami vagy önkormányzati intézményként.

A licenc szerint ez akkor is így van, ha a szervezet állami vagy pályázati
finanszírozásból működik.

**Kereskedelmi felhasználáshoz külön engedély kell tőlem.** Ide tartozik, ha a
szoftvert vagy a rá épülő szolgáltatást pénzért kínálod — akár előfizetésként,
akár telepítéssel vagy ügyfélszolgálattal együtt. Ilyen esetben **nyiss egy
issue-t** a projektben (<https://github.com/bozobernat/mikrotik-wireguard-provision/issues>), „commercial licence" címmel.
Nem zárkózom el tőle, csak tudni akarok róla.

```
Required Notice: Copyright Bozó Bernát — https://github.com/bozobernat/mikrotik-wireguard-provision
```

*(Ezt a sort a licenc „Notices" szakasza alapján mindenkinek tovább kell vinnie,
aki a szoftvert továbbadja.)* A szerzőség emberi és gépi részének elhatárolása:
[AUTHORSHIP.md](AUTHORSHIP.md).

### Hozzájárulás

Örülök a javításoknak. Mielőtt pull requestet fogadok el, alá kell írnod a
[CLA.md](CLA.md)-t — egy rövid nyilatkozatot arról, hogy a beküldött kódot én is
felhasználhatom, beleértve a kereskedelmi engedélyeket. Enélkül a hozzájárulásod
később megkötné a projektet.

### Védjegyek

A „WireGuard" név és logó Jason A. Donenfeld bejegyzett védjegye. Lásd: <https://www.wireguard.com/>.

Ez a projekt nem áll kapcsolatban a Mikrotikls SIA-val, a WireGuard projekttel, a Microsofttal, sem más olyan harmadik féllel, amelynek termékével együttműködik, és egyikük sem támogatja. A védjegyek a jogosultjaik tulajdonát képezik.
