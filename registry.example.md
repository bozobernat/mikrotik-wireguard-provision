# WireGuard — eszköz-nyilvántartás

Csak nem-titkos adat. **Privát kulcs soha nem kerül ide** — a privát kulcs
kizárólag az adott eszközön él; a bevonó szkript a generálás után nem tartja
meg lemezen.

A szkript ennek a táblázatnak a VÉGÉRE szúr be egy sort, célzottan — nem írja
újra a fájlt. Ha a fejléc nem található változatlan formában, inkább leáll,
mint hogy elrontsa. Ezért a fejléc sorát ne szerkeszd.

| Eszköznév | Platform | WG-cím | Publikus kulcs | Bevonás dátuma | AllowedIPs mód |
|---|---|---|---|---|---|
