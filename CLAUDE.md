# Roboter-Labyrinth – Projektübergabe für Claude Code

> Diese Datei ist die einzige Quelle der Wahrheit für das Projekt. Sie fasst alle Entscheidungen, die Analyse der Originaldateien (`reference/`) und die Design-Vorgaben zusammen. Lies sie vollständig, bevor du Code schreibst.

---

## 0. Arbeitsregeln für den Agenten

- **Sprache:** Mit Thomas auf Deutsch kommunizieren. Alle UI-Texte auf Deutsch (Besucher in Du-Form). Code, Bezeichner und Kommentare auf Englisch, die Lehrer-Doku auf Deutsch.
- **Thomas mag:** direkte, technisch präzise Schritt-für-Schritt-Anleitungen und vollständige Dateien statt Schnipsel.
- **Simulator zuerst:** Alles muss ohne Roboter laufen und testbar sein. Am echten Roboter wird nur gemessen, eingemessen und feinjustiert (Termine: 18.11. und 20.11.2026).
- **Nie ungetestet echte Bewegungen erzeugen.** Neuer Bewegungscode läuft zuerst gegen den Simulator und den Fake-Controller (siehe §12), danach am Roboter mit niedriger Geschwindigkeit.
- **RAPID (`SERVER.mod`) nicht ändern**, ohne vorher Thomas zu fragen. Ob und wie das geht, klärt erst der 18.11.
- **Offline-fähig:** Am Veranstaltungstag gibt es kein Internet. Kein CDN, keine externen Fonts, keine Online-Abhängigkeiten zur Laufzeit.
- **Zielsystem:** Windows-Laptop. Python frei wählbar (Ziel: Python 3.12).
- Die Dateien in `reference/` sind **Referenzmaterial**. Sie werden nicht verändert und nicht direkt importiert. Wir schreiben einen sauberen eigenen Client (siehe §4.3).

---

## 1. Projekt & Rahmen

**Was:** Ein interaktives Exponat für den **Tag der offenen Tür der TFO Bruneck am 28.11.2026** (ca. 3 h, nicht durchgehend in Betrieb). Besucher steuern einen **ABB IRB 120** per **WASD** und führen einen Stift durch ein **senkrecht stehendes Holzlabyrinth** (400 × 400 mm) – ein „Heißer Draht“ mit Roboter. Die Zeit zwischen Start- und Ziellinie misst die Software automatisch. Die besten 10 kommen auf eine Bestenliste. Ein **Auto-Lauf** fährt den mathematisch kürzesten Weg mit voller Geschwindigkeit und liefert eine **Referenzzeit** („Schaffst du die Maschine?“).

**Festgelegte Entscheidungen (final):**

| Thema | Entscheidung |
|---|---|
| Platte | Holz, 400 × 400 mm, **senkrecht**, gelasert (Creality Falcon2) |
| Wandberührung | **keine Erkennung** – die Gamemaster schauen selbst |
| Stift | noch offen (wahrscheinlich gerollte Papierrolle, evtl. echter Stift), Halterung wird gebaut |
| Wände | **virtuelle Wände in Software**, Toleranz einstellbar (auch leichte Berührung möglich) |
| Betriebsart | **Automatik mit Absicherung** (mit Lehrer abgeklärt) |
| Tastenbelegung | W = oben, S = unten, A = links, D = rechts (aus Sicht der Besucher), Diagonalen erlaubt, konstante Geschwindigkeit solange gedrückt |
| Geschwindigkeit Besucher | im Admin einstellbar |
| Ablauf | Name + Geburtsjahr → Start → Roboter fährt in den Startkreis → **3-2-1-Countdown** → WASD frei → Timer beim Überfahren der Startlinie → Stopp an der Ziellinie → Platzierung → Roboter fährt **Home** |
| Aufgeben | jederzeit möglich, Roboter fährt Home, kein Eintrag. Kein Zeitlimit |
| Bestenliste | Felder Name + Geburtsjahr, **Top 10** angezeigt, keine Strafzeiten, kein Export |
| Auto-Lauf | volle (im Admin begrenzte) Geschwindigkeit. Ein Besucher fordert ihn an, ein Admin muss **bestätigen**. Ergebnis ist eine **Referenzzeit neben** der Bestenliste, kein Platz darin. **Die beste Roboterzeit bleibt stehen** |
| Besucher-Bildschirm | externer Monitor am Laptop: großer Timer, Bestenliste, Start / Aufgeben / Roboter fahren lassen. TFO-Design |
| Admin | **Tablet im Browser** über den Windows-Hotspot des Laptops, mit **PIN** geschützt |
| Labyrinth | Layout **noch nicht final**. Es muss im Admin per SVG-Upload austauschbar sein. Am Tag selbst gibt es nur ein Labyrinth und eine Bestenliste |
| Team | 2 Gamemaster: einer mit Tablet, einer beim Roboter am Not-Halt |
| Doku | für den Lehrer, auf Deutsch: gesamter Vorgang, Aufbau & Technik, Bedienung, Sicherheit |

---

## 2. Hardware & Netzwerk

### 2.1 Roboter: ABB IRB 120-3/0.6 an IRC5
Quelle: `reference/docs/IRB120_Product_Manual.pdf`, Abschnitt 2.2.2 und 2.3.6.

- Reichweite 580 mm (Handgelenkmitte), Traglast 3 kg.
- Achsbereiche:

| Achse | Bereich |
|---|---|
| 1 | ±165° |
| 2 | ±110° |
| 3 | +70° / −110° |
| 4 | ±160° |
| 5 | ±120° |
| 6 | ±400° |

- Handgelenkmitte, Beispielpositionen (x/z): A (302/630) bei Achse 2 = 0°, Achse 3 = 0°; D (580/270) bei +90°/−77°; C (169/300). Achse 2 sitzt ca. 290 mm über der Fußfläche.
- **Werkzeugflansch:** Ø 40 mm, 4× M5 (8 mm tief) auf Lochkreis Ø 31,5 mm, Passstiftbohrung Ø 5 H7. Schrauben in Qualität 12.9.
- Quaternionen bei ABB: `[q1, q2, q3, q4] = [w, x, y, z]`.

### 2.2 Netzwerk

| Gerät | Adresse |
|---|---|
| Roboter-Controller | `192.168.0.30/24`, Motion-Server Port **5000**, Logger Port **5001** |
| Laptop (Ethernet zum Roboter) | fest `192.168.0.100/24` |
| Laptop (Windows Mobile Hotspot) | standardmäßig `192.168.137.1` |
| Tablet | im Hotspot-WLAN, öffnet `http://192.168.137.1:8000/admin` |
| Besucher-Monitor | Browser im Kiosk-Vollbild auf `http://localhost:8000/` |

- Der Server bindet auf `0.0.0.0:8000`.
- Für das private Netzwerk eine Windows-Firewall-Regel für Port 8000 anlegen (im Setup-Skript dokumentieren).

### 2.3 Roboter starten (aus den Kommentaren der Original-Skripte)

**Automatik (wird verwendet):**
1. Roboter-Ethernet mit dem Laptop verbinden, Roboter einschalten.
2. Schlüsselschalter am Controller auf **Automatik**.
3. **Motoren an:** Taster neben dem Hauptschalter am Controller („Motors On“).
4. FlexPendant: **ABB** (oben links) → **Production Window** (unten links) → **PP to Main** → bestätigen.
5. **Play-Taste** (Hardware) am FlexPendant drücken.
6. Am Laptop die Software starten.

**Manuell (nur zur Info / zum Einrichten):** wie oben, aber im manuellen Modus muss die **Freigabetaste** rechts am Pendant dauerhaft gehalten werden. Laut Originalkommentar war nach dem Loslassen nötig: Python-Skript abbrechen, PP to Main, Play. → Unsere Software muss Verbindungsabbrüche selbst erkennen und neu verbinden (siehe §8.2).

### 2.4 Platte & Stift
- Die Platte steht senkrecht vor dem Roboter. Plattenmitte ungefähr auf Schulterhöhe (Achse 2). Abstand und Höhe werden am 18.11. ermittelt: Alle 4 Ecken werden mit der richtigen Stiftausrichtung angefahren.
- Die alten Testskripte arbeiten mit `orientation = [0.707, 0, 0.707, 0]` (Werkzeug-z zeigt horizontal nach +x der Basis). Sie fahren Kreise in der senkrechten Ebene bei x = 474 mm (`doCirc`: Mitte y = 0, z = 350, r = 80). Das bestätigt, dass eine senkrechte Platte vor dem Roboter erreichbar ist.
- Stift: Typ, Länge und Durchmesser offen. Alles ist parametrierbar (Tool-Offset, Stiftdurchmesser, Eintauchtiefe, Rückzug).

---

## 3. Sicherheitsanforderungen

- **Die Absicherung vor Ort trägt die Sicherheit:** Absperrung/Abstand, Not-Halt in Reichweite von Gamemaster 2. Die Software ergänzt sie nur. **Ein Software-Stopp ersetzt nie den Not-Halt.**
- **Virtuelle Wände:** Der Stift verlässt nie den (verkleinerten) Kanal.
- **Arbeitsraum-Grenze:** Kartesische Ziele sind nur erlaubt
  - innerhalb der Plattenfläche (Plattenkoordinaten, siehe §6) mit z zwischen „Rückzug“ und „Eintauchtiefe“, oder
  - auf den definierten Anfahrwegen Home ↔ über Startkreis.

  Alles andere wird im Treiber abgelehnt (`ValueError`, geloggt).
- **Geschwindigkeitsgrenzen** gelten getrennt für Besucher, Auto-Lauf und Anfahrt. Harte Obergrenzen stehen in `config.toml`, nicht in der UI.
- **Totmann-Logik Tastatur:** Kommt 300 ms lang kein Tasten-Heartbeat vom Besucher-Client, werden alle Tasten als losgelassen behandelt. Dasselbe gilt bei `blur`/`visibilitychange` des Fensters.
- Bei Verbindungsverlust oder unbekanntem Fehler: keine weiteren Fahrbefehle, Spiel in Zustand `ERROR`, Hinweis auf beiden Oberflächen.
- In der Lehrer-Doku ausdrücklich beschreiben: Ablauf nach Not-Halt (quittieren, Motoren an, PP to Main, Play, Software verbindet neu).

---

## 4. Analyse der Originaldateien (`reference/`)

### 4.1 Überblick

| Datei | Inhalt | Nutzen |
|---|---|---|
| `reference/abb.py` | Python-Client von open_abb (M. Dawson-Haggerty), von „Aaron“ minimal auf Python 3 angepasst | Protokoll-Referenz. Wird durch einen eigenen Client ersetzt |
| `reference/rapid/SERVER.mod` | RAPID-Server auf dem Controller, IP auf `192.168.0.30` gesetzt | **läuft auf dem Roboter**. Definiert das Protokoll |
| `reference/rapid/LOGGER.mod` | RAPID-Logger, Port 5001, streamt Pose und Gelenke | evtl. für echte Ist-Position (ob er läuft: am 18.11. prüfen) |
| `reference/scripts/*.py` | Test- und Beispielskripte (nicht von Thomas, „gelootet“) | Startposen, Orientierungen, Beispielwerte |
| `reference/labyrinth/Labyrinth_Deckplatte_Entwurf1.svg` | erster Labyrinth-Entwurf | Testdaten + SVG-Konvention |
| `reference/docs/*.pdf` | IRB-120-Handbuch, open_abb README + Wiki | Nachschlagen |

### 4.2 Protokoll von `SERVER.mod` (TCP, Port 5000)

**Request:** ASCII `"<code> <p1> <p2> … #"`.
- Der Code steht zweistellig vorne, die Parameter sind durch Leerzeichen getrennt, `#` beendet die Nachricht.
- Python formatiert die Parameter mit `format(v, "+08.1f")` (Position), `"+08.5f"` (Quaternion), `"+08.2f"` (Gelenke).
- Der Server parst mit `StrMatch`/`StrToVal` und erlaubt maximal 10 Parameter (`params{10}`).

**Response:** `"<code> <ok> <addString>"`, wobei `ok` = 1 (SERVER_OK) oder 0 (SERVER_BAD_MSG) ist. Beispiel `get_cartesian` → `"3 1 x y z q1 q2 q3 q4"` (Positionen mit 2, Quaternion mit 3 Nachkommastellen).

| Code | Funktion | Parameter | Verhalten |
|---|---|---|---|
| 0 | Ping | – | sofortige Antwort |
| 1 | Kartesisch fahren | x y z q1 q2 q3 q4 | `MoveL` mit currentSpeed/currentZone/currentTool/currentWobj, `ConfL \Off`, `SingArea \Wrist`. **Antwort erst, wenn die RAPID-Anweisung „fertig“ ist** (bei Zone ≠ fine schon beim Übergang in die nächste Bahn, bei fine nach Stillstand) |
| 2 | Gelenke fahren | j1..j6 (Grad) | `MoveAbsJ` |
| 3 | Pose lesen | – | `CRobT` mit aktuellem Tool/Wobj |
| 4 | Gelenke lesen | – | `CJointT` |
| 5 | externe Achsen lesen | – | (nicht relevant) |
| 6 | Tool setzen | x y z q1..q4 | `currentTool.tframe` |
| 7 | Workobject setzen | x y z q1..q4 | `currentWobj.oframe` (uframe bleibt Identität) |
| 8 | Speed setzen | v_tcp v_ori v_leax v_reax (oder nur 2 Werte) | mm/s, °/s |
| 9 | Zone setzen | fine(0/1) pzone_tcp pzone_ori zone_ori | |
| 30 | Pose an Puffer anhängen | x y z q1..q4 | max. 512 Einträge, speichert auch den aktuellen Speed |
| 31 | Puffer leeren | – | |
| 32 | Pufferlänge | – | |
| 33 | Puffer ausführen | – | `FOR`-Schleife `MoveL`. Die Antwort kommt erst nach der letzten Anweisung → **blockiert** |
| 34 | externe Achse fahren | 6 Werte | (nicht relevant) |
| 35 / 36 | Kreisbewegung (Hilfspunkt / Zielpunkt) | je 7 | `MoveC` |
| 98 | Roboter-Info | – | Seriennr. `*` RobotWare-Version `*` Robotertyp |
| 99 | Verbindung schließen | – | Server schließt den Socket und wartet auf eine neue Verbindung |

**Wichtige Eigenschaften:**
- `Initialize` setzt Tool, Wobj und Speed `[100, 50, 0, 0]` sowie Zone z0. `Robot.__init__` in Python setzt danach Units, Tool, Wobj, Speed `[100, 50, 50, 50]` und Zone `z1`.
- Der Server ist **single-threaded:** Während eine `MoveL` läuft, werden keine weiteren Befehle gelesen. Es gibt keinen Weg, eine laufende Bewegung über das Protokoll abzubrechen.
- Error-Handler: Bei `ERR_SOCK_CLOSED` und unbekannten Fehlern schließt der Server den Socket, wartet neu (`ServerCreateAndConnect`) und macht `RETRY`.
- Geht eine Verbindung verloren, muss der Client neu verbinden und **Tool, Wobj, Speed und Zone neu setzen**. Diese Werte sind `PERS`, aber `Initialize` läuft bei PP to Main.
- Werden zwei Nachrichten zu schnell nacheinander gesendet, kann `SocketReceive` sie zusammenfassen, und `ParseMsg` nimmt nur die erste. Deshalb wartet `abb.py` 80 ms nach jedem Senden. **Unser Client arbeitet strikt Request → Response** (immer erst die Antwort lesen, dann senden). Dann ist die 80-ms-Pause unnötig. Die Latenz wird am 18.11. gemessen.
- Zonen-Tabelle aus `abb.py` (pzone_tcp, pzone_ori, zone_ori):

| Zone | Werte |
|---|---|
| z0 | 0.3, 0.3, 0.03 |
| z1 | 1, 1, 0.1 |
| z5 | 5, 8, 0.8 |
| z10 | 10, 15, 1.5 |
| z20 | 20, 30, 3 |
| z50 | 50, 75, 7.5 |
| z100 | 100, 150, 15 |
| z200 | 200, 300, 30 |

### 4.3 Probleme in `reference/abb.py` (Gründe für einen eigenen Client)
- `send()` nutzt `sock.send` statt `sendall`, `recv(4096)` liest ohne Framing, und nach jedem Befehl gibt es ein festes `time.sleep(0.08)`.
- `inspect.stack()` bei **jedem** Befehl kostet im 30-Hz-Loop spürbar Zeit.
- `get_robotinfo()` ist unter Python 3 kaputt: `str(bytes)[5:]` liefert `"b'98 1 …"`.
- `connect_logger()` ist Python-2-Code: `map()` wird indiziert, Bytes werden nicht dekodiert.
- `set_external_axis()` nutzt die undefinierte Variable `axis_values`, `load_json_tool()` die undefinierte `filename`. `log.warn` ist veraltet.
- Es gibt keine Timeouts beim Empfangen (`settimeout(None)` nach dem Connect) und keine Wiederverbindung.

→ Neuer Client `robot/protocol.py`:
- gleiche Nachrichtenformate,
- `sendall`, Antwort lesen bis zum Ende der Nachricht. Die Antworten haben kein `#`, also bis keine Daten mehr kommen bzw. per kurzem Read-Timeout; die Antwort ist immer ein einzelnes Paket < 100 Byte,
- konfigurierbarer Timeout (Standard 5 s, bei Bewegungen länger: Distanz/Speed + 2 s),
- Exceptions statt `None`,
- Latenz-Messung pro Befehl.

### 4.4 Werte aus den Testskripten (nur als Startpunkte)

| Skript | Relevantes |
|---|---|
| `setAllAnglesZero.py` | `set_speed([150,150,50,5])`, `set_joints([0,0,0,0,0,0])` |
| `testCalibration.py` | Startpose `set_joints([0,45,0,0,-45,0])`; Tool-Beispiel `set_tool([[20,150,0],[0.707,0,-0.707,0]])`; Kommentar: `[0,0,1,0]` = „tool down“, `[1,0,0,0]` = „tool up“ |
| `tfo.py` | Pose `set_joints([0,45,0,0,-45,105])`; Orientierung `[0.5,-0.5,0.5,-0.5]`; Rechteck x 120–420 / y ±200 bei z = 247,05 |
| `tmp.py`, `roulette.py` | Orientierung `[0.707,0,0.707,0]`; Rechteck x 260–560 / y ±200 bei z = 247,05; `draw_logo` nutzt `buffer_add`/`buffer_execute`; Kreise r = 50 / 25 um (400, 120) |
| alle | auskommentiertes Tool `[[20,0,-150],[0,0,1,0]]`; Hinweis „quaternions.online“ zur Visualisierung |

---

## 5. Labyrinth

### 5.1 SVG-Konvention (Pflicht für jedes Layout)
- `width="400mm" height="400mm" viewBox="0 0 400 400"` → 1 SVG-Einheit = 1 mm. Ursprung oben links, y nach unten.
- Gruppe `id="Schnitt"`: rote Konturen (`stroke="#FF0000"`), alles was gelasert geschnitten wird:
  - **Plattenrand:** Rechteck 0,0 – 400,400 → wird ignoriert.
  - **4 Bohrungen** Ø 5 mm, Mittelpunkte (7,5|7,5), (392,5|7,5), (7,5|392,5), (392,5|392,5) → Passpunkte zum Einmessen.
  - **Kanal:** die größte geschlossene Kontur innerhalb des Rands = Außenkontur der freigeschnittenen Fläche. Weitere geschlossene Unterpfade **innerhalb** davon sind **Inseln** (stehen gebliebenes Holz). Achtung: Im Entwurf sind Kanal und Inseln **Unterpfade desselben `<path>`** (mehrere `M … Z`). Der Parser muss Unterpfade trennen und nach Enthaltensein klassifizieren (Even-Odd-Logik).
- Gruppe `id="Gravur_*"` (z. B. `Gravur_Logo`): wird nur in der Vorschau angezeigt, nicht als Wand.
- Kurven (Bögen, Béziers) mit ≤ 0,2 mm Sehnenfehler linearisieren.

### 5.2 Validierung beim Upload
- Kanal gefunden und geschlossen, Inseln innerhalb.
- 4 Bohrungen gefunden (sonst Warnung, Einmessen über manuell eingegebene Passpunkte).
- Kleinste Kanalbreite ≥ Stiftdurchmesser + 2 × Toleranz. Andernfalls Engstellen markieren und eine Warnung zeigen.
- Ziel vom Start aus erreichbar (nach Verkleinerung).
- Länge des optimalen Wegs und geschätzte Besucher-Fahrzeit anzeigen.

### 5.3 Erster Entwurf (`Labyrinth_Deckplatte_Entwurf1.svg`) – Messwerte
- Kanal **16 mm** breit, auf einem **11 × 11-Raster** mit 33,636 mm Abstand (Mittellinien bei 31,818 + n·33,636). Ecken innen mit 8 mm Radius gerundet.
- Kanalgänge zwischen 23,818 und 376,182 mm. Inklusive der Kreise reicht die Kontur von 18,818 bis 381,182 mm (x und y).
- **Kreise** Ø 26 mm: oben rechts, Mitte ≈ (368,18 | 31,82), und unten links, Mitte ≈ (31,82 | 368,18). Welcher Kreis Start und welcher Ziel ist, ist **noch offen**.
- **2 Inseln** (→ Schleifen): Bounding-Boxen (73,5–192,0 | 39,8–124,7) und (241,6–360,2 | 208,0–292,9).
- Mehrere Sackgassen. TFO-Logo als Gravur unten rechts (≈ 254–376 | 331–373).
- Datei nicht ändern, nur als Testdatensatz in `tests/data/` kopieren.

### 5.4 Start- und Ziellinie
- Wird im Admin festgelegt (Tipp auf zwei Punkte, die automatisch auf die Kanalwände gesnappt werden). Vorschlag: automatisch am Übergang Kreis → Kanal, senkrecht zur Kanalrichtung.
- Jede Linie speichert zusätzlich eine **Richtung** (Normalenvektor in Fahrtrichtung). Gezählt wird nur ein Überqueren in Vorwärtsrichtung.

---

## 6. Koordinaten & Einmessen

### 6.1 Plattenkoordinaten
- Alles in der Spiel-Logik passiert in **Plattenkoordinaten (mm)**, identisch mit den SVG-Koordinaten: Ursprung oben links, **x nach rechts, y nach unten, aus Sicht der Besucher**. z = senkrecht zur Platte.
- Im Roboter wird daraus ein **Workobject** (`set_workobject`). Danach werden Ziele direkt in Plattenkoordinaten an den Server geschickt.
- **Offener Punkt:** Von welcher Seite schauen die Besucher – von der Roboterseite oder von der gegenüberliegenden Seite (Kanal ist durchgeschnitten, also beidseitig sichtbar)? Die Gravur muss zur Besucherseite zeigen. → Lösung über die Konfiguration `viewer_side = "robot" | "opposite"` und über die Reihenfolge der Bohrungen beim Einmessen (immer **aus Besuchersicht** oben links, oben rechts, unten links).

### 6.2 Mathematik des Einmessens (3 Punkte)
1. Tool (Stiftspitze) ist gesetzt, Workobject ist Identität.
2. Gemessen werden die Stiftspitzen-Positionen in Basiskoordinaten an den Bohrungsmitten (Plattenoberfläche):
   - P1 = oben links (7,5 | 7,5)
   - P2 = oben rechts (392,5 | 7,5)
   - P3 = unten links (7,5 | 392,5)
3. Berechnung:
   - `ex = normalize(P2 − P1)`
   - `v = P3 − P1`, `ey = normalize(v − (v·ex)·ex)`
   - `ez = ex × ey` (zeigt bei x rechts / y unten von den Besuchern weg in die Platte)
   - `O = P1 − 7,5·ex − 7,5·ey`
   - `R = [ex ey ez]` → Quaternion `[w,x,y,z]` (robuste Umrechnung, z. B. Shepperd-Methode)
4. Plausibilität:
   - `|P2−P1|` und `|P3−P1|` müssen 385 mm ± 2 mm sein.
   - Kontrolle mit der 4. Bohrung: erwartet `O + 392,5·ex + 392,5·ey`, Abweichung < 2 mm. Sonst Warnung.
5. Ergebnis speichern (SQLite) und bei jeder (Wieder-)Verbindung `set_workobject` senden.

### 6.3 Werkzeugausrichtung im Workobject
- Der Stift muss senkrecht zur Platte stehen und zur Platte hin zeigen.
- Steht der Roboter auf der Seite, auf die `ez` zeigt (Besucher gegenüber), zeigt die Werkzeug-z gegen `ez`. Eintauchen heißt dann z negativ, und die Tool-Orientierung ist z. B. `[0,1,0,0]` (180° um x).
- Schauen die Besucher von der Roboterseite, gilt `[1,0,0,0]` und Eintauchen heißt z positiv.
- Zusätzlich gibt es eine einstellbare Drehung um die Stiftachse (`tool_roll_deg`), um Handgelenk-Grenzen und Singularitäten zu vermeiden.
- Alle Vorzeichen zentral in `geometry/frames.py` kapseln und mit Tests absichern.

### 6.4 Tool
- `set_tool([[tx,ty,tz],[q]])`: Versatz der Stiftspitze zum Flansch.
- Im Admin eingeben. Optional einlernen über 4-Punkt-Methode (gleiche Spitze aus 4 Orientierungen → Least Squares). Das ist nur „nice to have“.

---

## 7. Architektur & Projektstruktur

**Stack:**
- Python 3.12, FastAPI, Uvicorn (`[standard]` für WebSockets), Pydantic v2
- shapely ≥ 2, svgelements, numpy
- SQLite (stdlib `sqlite3`), pytest
- Frontend ohne Build-Schritt: HTML + CSS + Vanilla-JS (ES-Module), vom Backend statisch ausgeliefert. Kein Framework, keine Node-Abhängigkeit zur Laufzeit. Fonts lokal.

```
roboter-labyrinth/
├─ CLAUDE.md                  ← diese Datei
├─ README.md                  ← Kurzanleitung Start/Setup (Deutsch)
├─ config.toml                ← harte Grenzen, Ports, PIN-Hash, Pfade
├─ requirements.txt
├─ start.bat                  ← startet Server + Kiosk-Browser auf Monitor 2
├─ setup_windows.ps1          ← Firewall-Regel, Hotspot-Hinweise, venv
├─ app/
│  ├─ main.py                 ← FastAPI-App, Routen, Static, Lifespan
│  ├─ settings.py             ← config.toml + DB-Settings (Pydantic)
│  ├─ db.py                   ← SQLite-Schema & Zugriff
│  ├─ game/
│  │  ├─ state_machine.py     ← Spielzustände, Übergänge
│  │  ├─ timer.py             ← monotone Zeit, Linienüberquerung
│  │  └─ leaderboard.py
│  ├─ robot/
│  │  ├─ protocol.py          ← TCP-Client für SERVER.mod (sauber, siehe §4.3)
│  │  ├─ driver_base.py       ← abstraktes Interface
│  │  ├─ driver_sim.py        ← Simulator (Kinematik-frei, Zeitmodell)
│  │  ├─ driver_standard.py   ← Schritt-Jog über bestehendes SERVER.mod
│  │  ├─ driver_extended.py   ← (später, nur nach Freigabe) Jog-Befehl
│  │  ├─ jog_loop.py          ← Tasten → Zielpunkte, 20–30 Hz
│  │  └─ safety.py            ← Arbeitsraum-/Geschwindigkeitsprüfung
│  ├─ geometry/
│  │  ├─ svg_import.py        ← SVG → Kanal, Inseln, Bohrungen, Gravur
│  │  ├─ channel.py           ← erlaubte Fläche, Projektion/Gleiten
│  │  ├─ lines.py             ← Start-/Ziellinie, Kreuzungstest
│  │  ├─ pathfinding.py       ← Sichtbarkeitsgraph + Dijkstra
│  │  └─ frames.py            ← Einmessen, Quaternionen, Plattenframe
│  └─ api/
│     ├─ ws_visitor.py
│     ├─ ws_admin.py
│     └─ admin_rest.py
├─ web/
│  ├─ visitor/ (index.html, visitor.css, visitor.js)
│  ├─ admin/   (index.html, admin.css, admin.js)
│  ├─ shared/  (tokens.css, components.css, ws.js, format.js, icons.svg)
│  └─ fonts/   (Inter Variable woff2, lokal)
├─ tools/
│  ├─ diagnose.py             ← Diagnose für Robotertermin 18.11. (§13)
│  └─ fake_controller.py      ← TCP-Server, der SERVER.mod nachbildet (§12)
├─ tests/
│  └─ data/Labyrinth_Deckplatte_Entwurf1.svg
├─ docs/                      ← Lehrer-Doku (Deutsch), Bedienungsanleitung
└─ reference/                 ← Originaldateien, unverändert
```

---

## 8. Module im Detail

### 8.1 Treiber-Interface (`driver_base.py`)
```python
class RobotDriver(Protocol):
    async def connect(self) -> None
    async def disconnect(self) -> None
    @property
    def connected(self) -> bool
    async def configure(self, tool, wobj, speed, zone) -> None   # nach jeder (Wieder-)Verbindung
    async def move_linear(self, pose: Pose, speed: float, zone: str) -> None  # Plattenkoordinaten
    async def move_joints(self, joints: list[float], speed: float) -> None
    async def get_pose(self) -> Pose          # Basis- oder Plattenkoordinaten je nach Wobj
    async def run_path(self, poses: list[Pose], speed: float, zone: str,
                       on_progress: Callable | None) -> None
    async def info(self) -> RobotInfo
```
- **Alle Aufrufe laufen über eine einzige asyncio-Queue / einen Lock pro Verbindung.** Das Protokoll ist strikt sequenziell.
- Blockierende Socket-Aufrufe laufen in `asyncio.to_thread` oder über asyncio-Streams.

### 8.2 Verbindung & Wiederverbindung
- Ein Hintergrund-Task überwacht die Verbindung: Ping (Code 0) alle 2 s, wenn sonst kein Verkehr ist.
- Bei Fehler oder Timeout:
  1. Zustand `DISCONNECTED`, laufendes Spiel abbrechen (kein Eintrag).
  2. Alle 2 s neu verbinden.
  3. Danach `configure()` und Zustand `IDLE` (Roboter-Position unbekannt → Admin muss „Home anfahren“ bestätigen, bevor neue Läufe starten).

### 8.3 Simulator (`driver_sim.py`)
- Simuliert die Position in Plattenkoordinaten mit Trapez-Geschwindigkeitsprofil (Beschleunigung einstellbar, z. B. 1000 mm/s²).
- Bildet die **Server-Semantik** nach: `move_linear` gibt bei Zone ≠ fine etwas vor dem Ende zurück, bei fine nach Stillstand.
- Künstliche Latenz einstellbar (Standard 15 ms). So lässt sich der Jog-Loop realistisch tunen.
- Die Admin-Live-Karte zeigt die simulierte Position.

### 8.4 Standard-Jog (`jog_loop.py` + `driver_standard.py`)
- Der Loop läuft mit 25 Hz (einstellbar). Er liest die Tastenmenge `{w,a,s,d}` und bildet daraus den Richtungsvektor:
  - `d = (D−A, S−W)`, normiert (diagonal = gleiche Geschwindigkeit).
- Schritt `Δ = v_besucher · Δt` (bei 50 mm/s und 25 Hz → 2 mm).
- Ziel `p_soll = p_letztes_ziel + d·Δ` → über `channel.constrain(p_letztes_ziel, p_soll)` (siehe 8.6) → `move_linear(p, v, zone="z1")`.
- **Nie mehr als 1 Befehl unterwegs:** Der nächste Schritt wird erst nach der Antwort des vorherigen gesendet. Δt wird dynamisch aus der gemessenen Zykluszeit genommen. So läuft keine Befehlsschlange voll, und der Nachlauf beim Loslassen bleibt ≤ 1–2 Schritte.
- Tasten losgelassen → keine weiteren Befehle (der Roboter bleibt am letzten Ziel stehen).
- Die **kommandierte Position** (`p_letztes_ziel`) ist die Wahrheit für Timer und Live-Anzeige.
- Am 18.11. messen: Antwortzeit von `move_linear` bei Schrittweiten von 1/2/3/5 mm und Speed 30/50/100 mm/s, jeweils mit z0/z1/z5. Daraus ergeben sich Default-Werte.

### 8.5 Erweiterter Treiber (`driver_extended.py`) – NICHT ohne Freigabe umsetzen
Ziel: flüssiges Jog mit sofortigem Stopp. Kandidaten (müssen gegen das RAPID-Handbuch und die Optionen des Controllers geprüft werden):
- **(a)** Neuer Befehl in `SERVER.mod`: `MoveL \Conc` auf ein weit entferntes, auf den Kanal begrenztes Ziel, dann weiter `SocketReceive`. Beim Stopp-Befehl `StopMove` → `ClearPath` → `StartMove`. **Prüfen**, in welchem Ausführungskontext `ClearPath` erlaubt ist (evtl. nur in TRAP/Error-Handler) und wie sich `\Conc` mit der Socket-Schleife verträgt.
- **(b)** Zweiter RAPID-Task (Option **Multitasking**) als Stopp-Kanal.
- **(c)** **EGM** (Externally Guided Motion), falls die Option vorhanden ist: echtes Positions-Streaming. Das wäre die beste Lösung.

Die Entscheidung fällt nach dem 18.11. (Optionen auslesen, RobotStudio-Zugang). Bis dahin bleibt der Standard-Treiber Pflicht und muss alleine reichen.

### 8.6 Geometrie (`channel.py`, `lines.py`, `pathfinding.py`)
- **Erlaubte Fläche:** `allowed = channel_polygon.buffer(-(pin_d/2 + wall_tolerance), join_style=round)`.
  - `wall_tolerance` ist im Admin einstellbar (−1 … +3 mm, Standard +1). Negativ = Stift berührt die Wand leicht.
  - Bei Mehrteiligkeit (Engstelle schneidet durch) den Teil nehmen, der den Startkreis enthält, und warnen.
- **`constrain(p_from, p_to)`:**
  1. Liegt das Segment p_from→p_to komplett in `allowed` (`covers`), ist das Ergebnis p_to.
  2. Sonst **gleiten:** Die Teilbewegungen nur in x und nur in y separat versuchen, und den nächstgelegenen Punkt auf dem Rand von `allowed` (`nearest_points`) zum Ziel bestimmen. Unter den Kandidaten, deren Segment in `allowed` liegt, den mit dem größten Fortschritt in Richtung d wählen.
  3. Falls nichts passt, bei p_from bleiben.
  - Ziel: Der Stift „rutscht“ an Wänden entlang, statt hängen zu bleiben. Schrittweiten sind klein gegenüber der Wandstärke (Entwurf: ≥ 17 mm), es gibt also kein Tunneln.
- **Linien-Kreuzung:** Bei jedem neuen kommandierten Segment prüfen, ob es Start-/Ziellinie schneidet (`LineString.intersects`) **und** in Vorwärtsrichtung (Skalarprodukt mit der Linien-Normale > 0). Der Zeitpunkt wird zwischen den Zeitstempeln der beiden Punkte interpoliert.
- **Kürzester Weg:**
  - Knoten: Start (Mitte Startkreis), Ziel (Mitte Zielkreis) und alle konkaven Ecken von `allowed`. Für den Auto-Lauf eine zusätzliche Sicherheitsreserve verwenden: `allowed.buffer(-auto_extra_margin)`, Standard 1,5 mm, ≥ Zonenradius.
  - Kanten: Sichtlinien, die `covers` erfüllen. Dann Dijkstra.
  - Ergebnis: Polylinie. Die Schnittpunkte mit Start- und Ziellinie werden als eigene Wegpunkte eingefügt.
  - Admin zeigt die Länge, die Vorschau und die geschätzte Zeit bei aktueller Auto-Geschwindigkeit.

### 8.7 Auto-Lauf
1. Home → über den Startkreis → eintauchen (Anfahrgeschwindigkeit).
2. Weg abfahren mit `v_auto` und Zone z1. Kleinere Zonen bei Ecken sind ok, denn größere Zonen schneiden Ecken nach innen ab → Richtung Wand. Deshalb gilt `auto_extra_margin` ≥ Zonenradius.
3. **Zeitmessung** (in der Priorität):
   - **a)** LOGGER (Port 5001) läuft → Ist-Position streamen, Kreuzungen wie beim Besucher erkennen.
   - **b)** Sonst die Wegpunkte auf Start- und Ziellinie mit `fine`-Zone fahren und die Antwortzeitpunkte der Einzelbefehle nehmen (kurzer Halt an den Linien ist akzeptabel).
   - **c)** Fallback: analytisch aus Weglänge und Geschwindigkeitsprofil.

   Welche Variante genutzt wird, steht im Admin. Am 18.11. wird verglichen.
4. Ziel → herausziehen → Home. Wenn die Zeit besser ist als die gespeicherte beste Roboterzeit, wird sie ersetzt.

### 8.8 Spiel-Zustandsautomat (`state_machine.py`)
```
DISCONNECTED ─(verbunden + Home bestätigt)→ IDLE
IDLE ─(Besucher: Start mit Name+Jahr)→ MOVING_TO_START
MOVING_TO_START → COUNTDOWN (3 s) → ARMED   (WASD frei, Timer steht)
ARMED ─(Startlinie vorwärts)→ RUNNING       (Timer läuft)
RUNNING ─(Ziellinie vorwärts)→ FINISHED     (WASD gesperrt, Eintrag speichern, Platz berechnen)
FINISHED → RETURNING_HOME → IDLE            (Ergebnis 8 s sichtbar, dann Idle)
ARMED|RUNNING|COUNTDOWN|MOVING_TO_START ─(Aufgeben | Admin: Abbrechen)→ ABORTING → RETURNING_HOME → IDLE
IDLE ─(Besucher: Roboter fahren lassen)→ AUTO_REQUESTED ─(Admin bestätigt)→ AUTO_RUN → RETURNING_HOME → IDLE
AUTO_REQUESTED ─(Admin lehnt ab | 60 s Timeout)→ IDLE
* ─(Verbindungsfehler)→ ERROR → DISCONNECTED
```
- Ein Zustandswechsel wird sofort an alle Clients gesendet.
- Es ist immer nur **ein** Lauf aktiv.
- Der Admin kann den Auto-Lauf auch direkt starten (ohne Anfrage).

### 8.9 Timer
- Die Server-Uhr (`time.monotonic_ns`) ist maßgeblich.
- Clients interpolieren die Anzeige lokal ab `run_started_at`. Der Endwert kommt vom Server.
- Anzeigeformat `m:ss.cc` (z. B. `0:42.17`). Gespeichert wird `time_ms` als Integer.
- Kommandierte Position ≠ Ist-Position: Die Verzögerung (≈ 1 Zyklus) tritt bei Start und Ziel gleich auf und kürzt sich weitgehend heraus.

### 8.10 Datenbank (SQLite, `data/labyrinth.db`)
```sql
labyrinths(id INTEGER PK, name TEXT, svg TEXT, created_at TEXT, active INTEGER,
           start_line TEXT, finish_line TEXT, path TEXT)        -- JSON-Felder
runs(id INTEGER PK, labyrinth_id INTEGER, name TEXT, birth_year INTEGER,
     time_ms INTEGER, status TEXT CHECK(status IN ('finished','aborted')),
     created_at TEXT, deleted INTEGER DEFAULT 0)
robot_runs(id INTEGER PK, labyrinth_id INTEGER, time_ms INTEGER, speed REAL,
           timing_method TEXT, created_at TEXT)
settings(key TEXT PK, value TEXT)                               -- JSON
calibration(id INTEGER PK, created_at TEXT, p1 TEXT, p2 TEXT, p3 TEXT, p4_check TEXT,
            wobj TEXT, tool TEXT, active INTEGER)
```
- Bestenliste = `runs` mit `status='finished' AND deleted=0` des aktiven Labyrinths, sortiert nach `time_ms`, Top 10. Die Platzierung eines neuen Laufs wird über alle Läufe berechnet („Platz 14 von 52“).
- Validierung:
  - Name 1–20 Zeichen, getrimmt, keine Steuerzeichen.
  - Geburtsjahr 1920 – aktuelles Jahr.
  - Doppelte Namen sind erlaubt.

### 8.11 Einstellungen (Defaults → Admin änderbar, harte Grenzen in `config.toml`)

| Schlüssel | Default | Grenze |
|---|---|---|
| `visitor_speed` mm/s | 50 | 10–150 |
| `auto_speed` mm/s | 250 | 50–1000 |
| `approach_speed` mm/s | 100 | 20–300 |
| `jog_rate_hz` | 25 | 10–50 |
| `jog_zone` | z1 | z0/z1/z5 |
| `pin_diameter` mm | 8 | 1–14 |
| `wall_tolerance` mm | 1.0 | −1…+3 |
| `auto_extra_margin` mm | 1.5 | 0–5 |
| `insert_depth` mm | 5 | 0–20 |
| `retract_distance` mm | 30 | 10–100 |
| `tool_roll_deg` | 0 | −180…180 |
| `countdown_s` | 3 | 0–5 (0 = aus) |
| `result_display_s` | 8 | 3–30 |
| `viewer_side` | "opposite" | robot/opposite |
| `driver` | "sim" | sim/standard/extended |
| `admin_pin` | in config.toml als Hash | 4–8 Ziffern |

### 8.12 API & WebSocket
- `GET /` → Besucher-UI, `GET /admin` → Admin-UI (Login mit PIN).
- `POST /api/admin/login {pin}` → httpOnly-Session-Cookie (8 h).
- `WS /ws/visitor` und `WS /ws/admin` (Admin nur mit gültiger Session).

**Server → Clients (Broadcast bei Änderung, Position max. 20 Hz):**
```json
{"type":"state","state":"RUNNING","run":{"name":"Lena","started_at_ms":123456,"elapsed_ms":4210},
 "robot":{"connected":true,"driver":"standard","pos":[201.3,88.0]},
 "leaderboard":[{"rank":1,"name":"Max","birth_year":2009,"time_ms":38120}],
 "robot_best_ms":18420,"auto_request":null}
```
`{"type":"result","time_ms":42170,"rank":4,"total":37}` · `{"type":"error","message":"…"}`

**Besucher → Server:**
- `{"type":"keys","down":["w","d"],"seq":812}` bei jeder Änderung **und** alle 100 ms als Heartbeat.
- `{"type":"start","name":"…","birth_year":2008}` · `{"type":"give_up"}` · `{"type":"request_auto"}`

**Admin (REST oder WS-Kommandos):**
- connect/disconnect, driver wählen
- jog (Richtung + Schrittweite, Hold-to-move mit Heartbeat wie Besucher)
- home teach/go
- calib point 1–4 speichern, calib berechnen/aktivieren
- tool setzen, settings patch
- labyrinth upload / Linien setzen / Pfad berechnen / aktivieren
- auto approve/reject/start, run abort
- leaderboard Eintrag löschen / zurücksetzen (mit Bestätigung)

---

## 9. Oberflächen – Inhalte & Verhalten

### 9.1 Besucher-Bildschirm (externer Monitor, 1920 × 1080, Kiosk, Maus + Tastatur)
**Layout:** 12-Spalten-Raster, 64 px Außenrand.
- **Links (7 Spalten):** Statuszeile (klein, oben) · **Timer** (sehr groß) · darunter der kontextabhängige Bereich (Anmeldung / WASD-Hinweis / Ergebnis).
- **Rechts (5 Spalten):** Karte „Bestzeit Roboter“ und darunter die „Bestenliste“ (Top 10).
- **Kopf:** TFO-Logo (aus dem Gravur-SVG als Vektor, monochrom), dezent oben links. Kein Seitentitel-Banner.

**Zustände:**
- **IDLE:**
  - Timer zeigt `0:00.00` gedimmt.
  - Formular: „Name“, „Geburtsjahr“ (numerisch, 4 Ziffern), primärer Button **Start**.
  - Darunter ein sekundärer Text-Button **Roboter fahren lassen**.
  - Nach 60 s ohne Eingabe wird das Formular geleert.
- **MOVING_TO_START:** Statuszeile „Der Roboter fährt zum Start …“, Formular ausgeblendet.
- **COUNTDOWN:** große Ziffern 3 · 2 · 1 als Overlay über dem Timer-Bereich, dann „Los“.
- **ARMED / RUNNING:**
  - Timer läuft (ab Startlinie).
  - Darunter vier Tastenkappen **W A S D** als Live-Feedback: Sie leuchten beim Drücken. Hinweis „Fahr mit W A S D durchs Labyrinth.“
  - Button **Aufgeben**: zweistufig, erster Klick → „Wirklich aufgeben?“ für 3 s, zweiter Klick bestätigt. Kein Modal.
- **FINISHED:**
  - Timer stoppt und wird hervorgehoben, Zeile „Geschafft.“ + „Platz 4 von 37“.
  - Der neue Eintrag in der Bestenliste wird kurz hervorgehoben (Hintergrund blendet aus). Ist er nicht in den Top 10, wird er unter der Liste als eigene Zeile gezeigt.
  - Nach `result_display_s` → IDLE.
- **AUTO_REQUESTED:** „Ein Betreuer gibt den Roboter gleich frei …“ mit Abbrechen.
- **AUTO_RUN:** „Der Roboter fährt den kürzesten Weg.“ Der Timer läuft mit Roboter-Kennzeichnung.
- **ERROR / DISCONNECTED:** ruhige Vollflächen-Meldung „Kurze Pause – ein Betreuer kümmert sich darum.“ Keine technischen Details für Besucher.

**Tastatur:**
- WASD und Pfeiltasten. `preventDefault` für diese Tasten.
- `keydown`-Repeat ignorieren, nur Zustandsänderungen + Heartbeat senden.
- Enter im Formular = Start.
- Fokus bleibt immer auf der Seite: Kiosk-Modus, keine anderen Fenster.

### 9.2 Admin-Panel (Tablet, iPad-Layout, Touch)
Aufbau wie die iPadOS-Einstellungen: **Seitenleiste** (320 px) mit Abschnitten, rechts der Inhalt als **gruppierte Listen**. Hochformat: die Seitenleiste wird zur Navigation mit Zurück.

| Abschnitt | Inhalt |
|---|---|
| **Übersicht** | Verbindungsstatus, Treiber, Spielzustand, **Live-Karte** (Labyrinth-SVG, erlaubte Fläche, optimaler Weg gestrichelt, Start-/Ziellinie, Stiftposition als Punkt), letzte Läufe. Banner bei Auto-Lauf-Anfrage mit **Freigeben** / **Ablehnen** (erscheint auf jeder Seite). Großer Button **Lauf abbrechen** (rot) |
| **Roboter** | Verbinden/Trennen, Treiberwahl (Segmented Control: Simulator · Standard · Erweitert), Jog-Pad (8 Richtungen + z vor/zurück, Hold-to-move, Schrittweite 0,1 · 1 · 10 mm oder Dauer), aktuelle Pose, Home einlernen / anfahren, Gelenke auf Startpose |
| **Einmessen** | Assistent in 4 Schritten (Bohrung oben links → oben rechts → unten links → Kontrolle unten rechts) mit Skizze, welche Bohrung gemeint ist. Messwerte, Abweichungen, Aktivieren. Tool-Versatz, Stiftdurchmesser, Eintauchtiefe, Rückzug, Stiftdrehung, Besucherseite |
| **Labyrinth** | SVG hochladen (Datei-Auswahl am Tablet), Validierungsergebnis, Vorschau. Start-/Ziellinie per Tipp setzen (mit Vorschlag). Weg berechnen (Länge, geschätzte Zeiten). Aktivieren |
| **Spiel** | Geschwindigkeiten (Slider mit Zahlenwert), Wandtoleranz, Countdown, Ergebnisdauer, Zeitmess-Methode Auto-Lauf, Auto-Lauf starten |
| **Bestenliste** | alle Läufe (durchsuchbar), Eintrag löschen (Wischen oder Bearbeiten-Modus), Bestenliste zurücksetzen (Bestätigung per Action Sheet), Roboter-Bestzeit zurücksetzen |

Gefährliche Aktionen (Zurücksetzen, Kalibrierung überschreiben, Lauf abbrechen) sind rot und brauchen eine Bestätigung per Action Sheet. Ausnahme ist **Lauf abbrechen** im Notfall: ein Tipp, kein Dialog.

---

## 10. Design-System – Apple-Qualität, nicht „nach KI aussehend“

**Leitbild:** So, als hätte ein kleines, sehr gutes Designteam bei Apple ein Messe-Exponat gebaut. Ruhig, präzise, selbstbewusst. Typografie trägt das Design, nicht Effekte. Jede Fläche, jeder Abstand und jede Animation hat einen Grund. Grundlage sind die **Apple Human Interface Guidelines**: Klarheit, Zurückhaltung (Deference), Tiefe durch Ebenen statt Deko, Konsistenz.

### 10.1 Typografie
- **Font:** `Inter` (Variable, OFL, **lokal** einbinden mit `font-display: swap`), auf dem iPad bevorzugt das System-SF.
  - Stack: `-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI Variable", system-ui, sans-serif`.
  - SF Pro **nicht** als Webfont einbetten (Lizenz erlaubt das nur auf Apple-Plattformen). Auf dem iPad greift `-apple-system` legal automatisch.
- Inter-Features: `font-feature-settings: "cv11", "ss01", "ss03"`. **Zahlen immer `font-variant-numeric: tabular-nums`** (Timer, Zeiten, Ränge, Messwerte).
- Optische Feinheiten:
  - große Größen mit negativem Letter-Spacing (Display: −0.022em, Title: −0.012em, Body: −0.004em),
  - kleine Größen leicht positiv (Caption: +0.01em),
  - Zeilenhöhe Body 1.47, Titel 1.1.
- **Skala Admin (pt = px, wie iOS):**

| Stufe | Größe / Zeilenhöhe / Gewicht |
|---|---|
| Large Title | 34/41 Bold |
| Title 1 | 28/34 Bold |
| Title 2 | 22/28 Bold |
| Title 3 | 20/25 Semibold |
| Headline | 17/22 Semibold |
| Body | 17/22 Regular |
| Callout | 16/21 |
| Subheadline | 15/20 |
| Footnote | 13/18 |
| Caption | 12/16 |

- **Skala Besucher (für 2–3 m Betrachtungsabstand):**

| Element | Größe / Gewicht |
|---|---|
| Timer | 220 px, Semibold 600, Hundertstel 0.55× in Sekundärfarbe |
| Countdown-Ziffern | 360 px |
| Statuszeile | 28 px, Medium, Sekundärfarbe |
| Sektionstitel | 15 px, Semibold, versal mit +0.08em Tracking, Tertiärfarbe |
| Listenzeilen | 30 px |
| Buttons | 22 px Semibold |

- Satzbau: Sentence case, keine Versalien für Fließtext, keine Ausrufezeichen-Inflation (höchstens eines im ganzen UI).

### 10.2 Farben (Design-Tokens in `web/shared/tokens.css`)
**Besucher-Bildschirm: immer dunkel** (Bühnenwirkung, Kontrast im hellen Raum, Fokus auf den Timer). Werte angelehnt an die iOS-Systemfarben (dunkel):

| Token | Wert |
|---|---|
| `--bg` | `#000000` |
| `--surface-1` | `#1C1C1E` |
| `--surface-2` | `#2C2C2E` |
| `--separator` | `rgba(84,84,88,0.6)` |
| `--label` | `#FFFFFF` |
| `--label-2` | `rgba(235,235,245,0.62)` |
| `--label-3` | `rgba(235,235,245,0.32)` |
| `--success` | `#30D158` |
| `--danger` | `#FF453A` |
| `--warning` | `#FFD60A` |
| `--accent` | **TFO-Akzentfarbe** (Thomas fragen bzw. aus dem TFO Corporate Design übernehmen). Bis dahin neutral `#0A84FF`. Es gibt genau **eine** Akzentfarbe |

**Admin: hell/dunkel automatisch** (`prefers-color-scheme`). Hell:

| Token | Wert |
|---|---|
| Hintergrund (grouped) | `#F2F2F7` |
| Zellen | `#FFFFFF` |
| Separator | `rgba(60,60,67,0.29)` |
| Label | `#000000` |
| Label 2 | `rgba(60,60,67,0.6)` |
| Akzent | `#007AFF` bzw. TFO-Farbe |
| Danger | `#FF3B30` |

Dunkel wie die Besucher-Werte, mit `--bg-grouped: #000`, Zellen `#1C1C1E`.

- Kontraste nach WCAG AA (Text ≥ 4.5:1). Status nie nur über Farbe, immer auch über Text bzw. Form.

### 10.3 Raster, Abstände, Formen
- 4-pt-Basis, Abstände nur aus `4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 96`.
- Radien:
  - Listen-Zellen-Gruppen 10 px (Admin, wie iOS inset grouped), Karten 16 px (Besucher), Sheets 22 px,
  - Buttons: Pill (999 px) für Primäraktionen am Besucher-Bildschirm, 12 px im Admin,
  - Radien verschachtelter Elemente konzentrisch (innen = außen − Abstand).
- Touch-Ziele mindestens 44 × 44 px (Admin), Besucher-Buttons 64 px hoch.
- Ausrichtung pixelgenau an Grundlinien und Spaltenkanten. Zahlenspalten rechtsbündig.

### 10.4 Komponenten
- **Buttons:**
  - Primär = Akzentfläche, Label weiß, Semibold.
  - Sekundär = `--surface-2` mit Label in Akzentfarbe.
  - Tertiär = nur Text in Akzentfarbe.
  - Destruktiv = Text oder Fläche in `--danger`.
  - Gedrückt: Helligkeit −8 % und `scale(0.98)` für 120 ms. Deaktiviert: 35 % Deckkraft.
- **Eingabefelder (Besucher):** 64 px hoch, `--surface-1`, kein Rahmen, Radius 14. Label klein darüber, Fokus durch einen 2-px-Ring in Akzentfarbe mit 3 px Abstand. Platzhalter nur als Beispiel („z. B. Lena“).
- **Bestenliste:** keine Tabelle mit Rahmen, sondern ruhige Zeilen.
  - Rang (tabular, `--label-3`, Platz 1 in `--label`), Name (`--label`), Geburtsjahr (`--label-2`), Zeit rechtsbündig (tabular, Semibold).
  - Haarlinien-Separatoren eingerückt ab der Namensspalte.
  - Keine Medaillen-Emojis, keine Pokale.
- **Roboter-Bestzeit:** eigene Karte über der Liste: kleines, selbst gezeichnetes Liniensymbol (Roboterarm, 1.5 px Strich), Label „Bestzeit Roboter“, Zeit groß.
- **Tastenkappen W A S D:**
  - 72 × 72 px, Radius 14, `--surface-1` mit 1 px innerem Highlight oben (`inset 0 1px 0 rgba(255,255,255,0.06)`), Buchstabe 26 px Semibold.
  - Aktiv: Akzentfläche, um 2 px nach unten versetzt, 80 ms.
  - Anordnung wie auf der Tastatur (W über S, A links, D rechts).
- **Admin-Listen:** iOS Inset Grouped. Zellen 44 px min, Label links, Wert/Steuerelement rechts, Disclosure-Chevron bei Navigation. Section-Header als Footnote versal in Label 2, Footer-Erklärtexte als Footnote.
- **Steuerelemente Admin:** Segmented Control, Toggle (51 × 31, Grün `#34C759` an), Slider mit Wertanzeige, Stepper für ±-Werte, Action Sheets für destruktive Bestätigungen, nicht-blockierende Banner oben (Auto-Lauf-Anfrage).
- **Live-Karte:**
  - Platte als `--surface-1`, Kanal ausgespart (`--bg`), erlaubte Fläche als feine Kontur.
  - Optimaler Weg 1.5 px gestrichelt `--label-3`, Start-/Ziellinie in `--success` / `--label`.
  - Stift als 10-px-Punkt in Akzentfarbe mit weichem Halo, Bewegung interpoliert (rAF).
- **Icons:** sparsam. Wo nötig eigene, einheitliche Linien-Icons (20 px, 1.5 px Strich, runde Enden) in `icons.svg` als Sprite. **Keine SF Symbols** (Lizenz), keine Icon-Bibliothek „aus dem Baukasten“, kein Icon pro Listeneintrag.

### 10.5 Bewegung
- Animationen erklären Zustandswechsel, sie schmücken nicht.
- Kurven:
  - Standard `cubic-bezier(0.25, 0.1, 0.25, 1)` 200 ms,
  - Sheets/Overlays iOS-Kurve `cubic-bezier(0.32, 0.72, 0, 1)` 420 ms,
  - Countdown: Skalierung 1.15 → 1.0 + Einblenden 300 ms, Ausblenden 200 ms.
- Timer-Ziffern springen nicht. Feste Breite durch tabular-nums. Keine Ziffern-Roll-Effekte.
- Neuer Bestenlisten-Eintrag: Zeile schiebt sich an ihren Platz (FLIP, 450 ms), Hintergrund Akzent 18 % → 0 über 2 s.
- Materialien: `backdrop-filter: saturate(180%) blur(20px)` **nur** für Overlays/Banner, nicht für Karten.
- `prefers-reduced-motion`: nur Überblendungen, keine Skalierung oder Verschiebung.

### 10.6 Anti-„KI-Look“-Regeln (verbindlich)
- **Keine** Verläufe (besonders kein Lila → Blau), kein Neon, kein Glow, keine farbigen Schatten, keine Glasmorphism-Karten überall.
- **Keine** Emojis im UI, keine Konfetti-Explosionen, keine „🚀 Let's go!“-Sprache.
- **Keine** generischen Hero-Sektionen, keine zentrierten Alles-Layouts, keine Karten-Raster mit gleichförmigen Icons.
- **Keine** Tailwind-Standardoptik (`rounded-2xl shadow-lg` überall, `gray-50`-Flächen, Indigo-Akzent).
- **Keine** Fülltexte oder Platzhalterinhalte. Jeder Text ist echter, natürlicher deutscher Text in Du-Form, kurz und freundlich, ohne Werbesprache.
- **Weniger Elemente, bessere Details:** saubere Haarlinien (0.5 px auf Retina via `transform: scaleY(.5)` bzw. 1 px), exakte Abstände, konsistente Zahlenformate (`0:42.17`, Geburtsjahr ohne Tausenderpunkt).
- Leere Zustände gestalten (z. B. leere Bestenliste: „Noch keine Zeiten. Sei die oder der Erste.“).
- Fehlermeldungen menschlich und konkret, nie Stacktraces oder Codes in der Besucher-UI.

### 10.7 Microcopy (Deutsch, Du-Form, Besucher)

| Kontext | Text |
|---|---|
| Idle-Unterzeile | „Steuere den Roboterarm durchs Labyrinth.“ |
| Felder | „Name“ · „Geburtsjahr“ |
| Primärbutton | „Start“ |
| Sekundär | „Roboter fahren lassen“ |
| Anfahrt | „Der Roboter fährt zum Start …“ |
| Countdown | „3“ · „2“ · „1“ · „Los“ |
| Fahren | „Fahr mit W A S D durchs Labyrinth.“ |
| Aufgeben | „Aufgeben“ → „Wirklich aufgeben?“ |
| Ziel | „Geschafft.“ · „Platz 4 von 37“ |
| Neuer Rekord | „Neue Bestzeit!“ (das einzige Ausrufezeichen) |
| Auto-Anfrage | „Ein Betreuer gibt den Roboter gleich frei …“ |
| Auto-Lauf | „Der Roboter fährt den kürzesten Weg.“ |
| Karte | „Bestzeit Roboter“ |
| Liste | „Bestenliste“ |
| Leer | „Noch keine Zeiten. Sei die oder der Erste.“ |
| Fehler | „Kurze Pause – ein Betreuer kümmert sich darum.“ |
| Validierung | „Bitte gib deinen Namen ein.“ · „Bitte gib ein Geburtsjahr wie 2009 ein.“ |

---

## 11. Meilensteine & Abnahmekriterien

| # | Bis | Inhalt | Abnahme |
|---|---|---|---|
| M1 | 15.11. | Projektgerüst, `protocol.py`, `fake_controller.py`, Simulator-Treiber, Tests | `pytest` grün. Der Client spricht fehlerfrei mit dem Fake-Controller (alle Codes aus §4.2) |
| M2 | 16.11. | Geometrie: SVG-Import, erlaubte Fläche, `constrain`, Linien, kürzester Weg, Einmess-Mathe | Entwurf 1 wird korrekt erkannt (Kanal, 2 Inseln, 4 Bohrungen, 16 mm Breite). Weg vom Kreis oben rechts zum Kreis unten links wird gefunden und liegt vollständig in der Fläche. Einmessen mit synthetischen Punkten (Rotation + Translation) ergibt < 0,01 mm Fehler |
| M3 | 17.11. | Backend: Zustandsautomat, Jog-Loop, Timer, DB, API/WS. Besucher- und Admin-UI vollständig im Design aus §10 | Kompletter Besucher-Lauf und Auto-Lauf im Simulator, bedient über Monitor + Tablet. Live-Karte flüssig. Heartbeat-Totmann greift |
| M4 | 18.11. | `tools/diagnose.py`, Robotertermin 1 | Messprotokoll (JSON + Kurzbericht) liegt vor (§13) |
| M5 | 19.–20.11. | Tuning mit echten Werten, ggf. erweiterter Treiber (nur nach Freigabe), Robotertermin 2: Einmessen, Generalprobe | 10 Besucher-Läufe am echten Roboter ohne Eingriff. Auto-Lauf ohne Wandkontakt |
| M6 | 27.11. | Finales Labyrinth einspielen, Lehrer-Doku, `start.bat`, Notfallablauf | Kaltstart (Laptop aus → spielbereit) in < 5 min nach README |

---

## 12. Tests
- `pytest` für Geometrie (Import, Breite, `constrain`-Gleiten an Wänden und Ecken, Kreuzungen vorwärts/rückwärts, Pfad liegt in der Fläche), Einmessen (synthetische Frames, Ausreißer-Warnung), Zustandsautomat (alle Übergänge, Abbruch in jedem Zustand), Bestenliste (Sortierung, Platzberechnung, gelöschte Einträge), Protokoll (Formatierung exakt wie `abb.py`: `"+08.1f"`, `"+08.5f"`).
- **`tools/fake_controller.py`:** asyncio-TCP-Server auf Port 5000 (konfigurierbar). Er implementiert die Codes 0–9, 30–33, 98 und 99 mit derselben Semantik wie `SERVER.mod`: Antworten erst nach simulierter Bewegungsdauer, Zone-Verhalten, single-threaded, Fehler bei falscher Parameterzahl. Optionale künstliche Latenz und zufällige Verbindungsabbrüche zum Testen der Wiederverbindung.
- Integrations-Test: Standard-Treiber gegen den Fake-Controller, ein kompletter Lauf über WebSocket-Client.

---

## 13. Diagnose-Skript für den Robotertermin am 18.11. (`tools/diagnose.py`)
Ein Kommandozeilen-Skript, interaktiv mit Bestätigung vor jeder Bewegung, das ein Protokoll `diagnose_YYYYMMDD_HHMM.json` + `.md` schreibt:
1. Verbindung zu `192.168.0.30:5000`. Ping-Latenz (100×: min/median/p95).
2. `98` → Seriennummer, RobotWare-Version, Robotertyp.
3. `03`/`04` → aktuelle Pose und Gelenke.
4. Prüfen, ob LOGGER auf Port 5001 antwortet (nur verbinden, 2 s mitlesen, Format prüfen).
5. **Bewegungstest** (nach Bestätigung, Speed 20 mm/s, in freier Luft vor dem Roboter, Startpose `[0,45,0,0,-45,0]`): Schritte 1/2/3/5 mm in ±y/±z mit Zone z0/z1/z5 bei 30/50/100 mm/s, jeweils 20 Schritte. Gemessen werden die Antwortzeiten pro Befehl und der Nachlauf nach dem letzten Befehl (Pose vor/nach 1 s).
6. Puffer-Test (`30`–`33`) mit 10 Punkten.
7. Reichweiten-Test für eine 400-mm-Platte: Admin gibt Plattenmitte und Ebene ein (z. B. x = 450, Ebene y–z). Das Skript fährt die 4 Ecken ±185 mm mit Stiftausrichtung langsam an und protokolliert Erreichbarkeit und Gelenkwinkel (Abstand zu den Grenzen aus §2.1).
8. Checkliste zum Abhaken in der Konsole (manuell): Optionen am FlexPendant (PC Interface, Multitasking, EGM), RobotStudio-Zugang mit Schreibrecht, Not-Halt-Ablauf, Flanschmaße, Fotos.

---

## 14. Betrieb am 28.11.
- **`start.bat`:**
  1. venv aktivieren,
  2. `uvicorn app.main:app --host 0.0.0.0 --port 8000`,
  3. nach 2 s den Besucher-Bildschirm im Kiosk-Modus auf Monitor 2 öffnen: `msedge --kiosk http://localhost:8000/ --edge-kiosk-type=fullscreen --window-position=1920,0` (Position konfigurierbar; alternativ Chrome `--kiosk`).
- Windows-Energiesparen aus, Bildschirmschoner aus, Benachrichtigungen aus („Nicht stören“), Updates pausieren.
- Hotspot vorher einrichten (SSID/Passwort in der README). Admin-Lesezeichen auf dem Tablet als Home-Bildschirm-Web-App (`apple-mobile-web-app-capable`, Icon, Theme-Farbe).
- Datenbank-Backup automatisch beim Start (Kopie mit Zeitstempel).

---

## 15. Lehrer-Doku (`docs/`, Deutsch)
Gliederung:
1. Projektidee & Ziel
2. Aufbau (Fotos, Skizze: Roboter, Platte, Laptop, Monitor, Tablet, Netzwerk)
3. Technik (Architektur, Protokoll zum Roboter, Koordinaten & Einmessen, virtuelle Wände, kürzester Weg, Zeitmessung)
4. Sicherheit (Betriebsart Automatik, Absicherung, Not-Halt, Software-Grenzen, Rollen)
5. Bedienungsanleitung für die Aufsicht (Start, Einmessen, Spielbetrieb, Auto-Lauf, Störungen und Not-Halt-Ablauf, Abbau)
6. Ergebnisse & Erkenntnisse (Messwerte vom 18./20.11., Erfahrungen am Tag)
7. Anhang (Protokolltabelle, Einstellungen)

Format: Markdown in `docs/`. Am Ende gibt es zusätzlich ein Docs-/Word-Dokument (Thomas entscheidet).

---

## 16. Offene Punkte (vor dem Bauen nicht raten – nachfragen)

| Punkt | Wer | Bis |
|---|---|---|
| Labyrinth-Layout final, welcher Kreis Start, welcher Ziel | Thomas & Team | ca. 21.11. (lasern) |
| Stift: Typ, Länge, Durchmesser; Halterung | Team | 20.11. |
| Besucher schauen von Roboterseite oder Gegenseite (`viewer_side`, Gravurseite) | Thomas | 18.11. |
| Lage der Platte zum Roboter (Abstand, Höhe) | Thomas | 18.11. |
| RobotWare-Version, Optionen (Multitasking, EGM), RobotStudio-Zugang → Treiberwahl | Thomas | 18.11. |
| Läuft LOGGER.mod? (Zeitmessung Auto-Lauf) | Thomas | 18.11. |
| Absperrung, Not-Halt-Position mit Lehrer | Thomas | 18.11. |
| TFO-Akzentfarbe / Corporate Design | Thomas | vor M3 |
| Labyrinth-Generator im Admin (optional, nur wenn Zeit bleibt) | Thomas | – |
