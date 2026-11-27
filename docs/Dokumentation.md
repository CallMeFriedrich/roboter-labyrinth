# Roboter-Labyrinth – Dokumentation

Exponat zum Tag der offenen Tür der TFO Bruneck am 28.11.2026.
Stand: 14.11.2026, vor dem ersten Robotertermin. Abschnitt 6 wird nach den Terminen am 18. und 20.11. ergänzt.

---

## 1. Projektidee und Ziel

Besucherinnen und Besucher steuern einen Industrieroboter (ABB IRB 120) mit den Tasten W, A, S und D. Am Roboter sitzt ein Stift, der durch ein senkrecht stehendes, gelasertes Holzlabyrinth (400 × 400 mm) geführt wird – ein „Heißer Draht“ mit Roboter.

- Die Software misst die Zeit automatisch zwischen Start- und Ziellinie.
- Die zehn besten Zeiten stehen auf einer Bestenliste (Name und Geburtsjahr).
- Auf Wunsch fährt der Roboter den mathematisch kürzesten Weg selbst. Seine Zeit steht als Referenz neben der Bestenliste: „Schaffst du die Maschine?“

Ziel des Exponats ist, Robotik anfassbar zu machen: Koordinatensysteme, Bahnplanung, Sicherheit und die Grenzen einer Steuerung über ein Netzwerk werden beim Spielen sichtbar.

## 2. Aufbau

```
                 Besucher                         Gamemaster 2
                    │                             (am Not-Halt)
          ┌─────────┴──────────┐
          │  Besucher-Monitor  │        ┌──────────────┐      ┌───────────┐
          │  Tastatur (WASD)   │        │ Holzplatte   │◄─────│ IRB 120   │
          └─────────┬──────────┘        │ 400 × 400    │ Stift│ + IRC5    │
                    │ HDMI              │ senkrecht    │      └─────┬─────┘
          ┌─────────┴──────────┐        └──────────────┘            │ Ethernet
          │      Laptop        │────────────────────────────────────┘ 192.168.0.x
          │  Server + Browser  │
          └─────────┬──────────┘
                    │ WLAN (Windows-Hotspot, 192.168.137.x)
          ┌─────────┴──────────┐
          │ Tablet (Admin)     │   Gamemaster 1
          └────────────────────┘
```

| Teil | Beschreibung |
|---|---|
| Roboter | ABB IRB 120-3/0.6 am Controller IRC5, Reichweite 580 mm, Traglast 3 kg |
| Platte | Holz, 400 × 400 mm, senkrecht vor dem Roboter, gelasert (Creality Falcon2). Vier Bohrungen Ø 5 mm in den Ecken dienen als Passpunkte |
| Stift | an einer Halterung am Werkzeugflansch (Ø 40 mm, 4 × M5 auf Lochkreis Ø 31,5 mm) |
| Laptop | Windows, führt die Software aus. Ethernet zum Roboter, Hotspot für das Tablet |
| Besucher-Monitor | externer Bildschirm mit Tastatur: Timer, Bestenliste, Anmeldung |
| Tablet | Admin-Oberfläche im Browser, mit PIN geschützt |

Fotos des Aufbaus werden nach dem Termin am 20.11. ergänzt.

## 3. Technik

### 3.1 Architektur

Auf dem Laptop läuft ein einziges Programm (Python 3.12, FastAPI). Es liefert zwei Webseiten aus und spricht mit dem Roboter:

- **Besucher-Bildschirm** (`/`): Timer, Anmeldung, Bestenliste. Tasten werden über einen WebSocket an den Server geschickt.
- **Admin-Panel** (`/admin`): Verbindung, Einmessen, Labyrinth, Einstellungen, Bestenliste.
- **Roboter-Treiber:** Simulator (ohne Roboter), Standard (echter Roboter) – beide mit derselben Schnittstelle. Alles wurde zuerst im Simulator entwickelt und getestet.

Die Oberflächen kommen ohne Internet aus: keine externen Schriften, Skripte oder Dienste.

### 3.2 Protokoll zum Roboter

Auf dem Controller läuft das RAPID-Programm `SERVER.mod` (aus dem Projekt *open_abb*). Es nimmt über TCP (Port 5000) Textbefehle an, zum Beispiel:

```
01 +00201.3 +00088.0 -00005.0 +0.00000 +1.00000 +0.00000 +0.00000 #
```

Das bedeutet: „Fahre linear zur Position x/y/z mit dieser Orientierung (Quaternion)“. Der Roboter antwortet erst, wenn die Bewegung ausgeführt ist. Wichtige Eigenschaften:

- Der Server arbeitet **einen Befehl nach dem anderen** ab. Eine laufende Bewegung lässt sich über das Protokoll nicht abbrechen.
- Unser Programm schickt deshalb immer nur kleine Schritte (wenige Millimeter) und wartet jedes Mal auf die Antwort.
- Geht die Verbindung verloren, verbindet sich die Software alle 2 Sekunden neu und schickt Werkzeug und Koordinatensystem erneut.

Das RAPID-Programm wurde **nicht verändert**. Die Tabelle aller Befehle steht im Anhang.

### 3.3 Koordinaten und Einmessen

Die Spiellogik rechnet in **Plattenkoordinaten**: Ursprung oben links, x nach rechts, y nach unten (aus Sicht der Besucher), in Millimetern – genau wie in der SVG-Zeichnung des Labyrinths.

Damit der Roboter diese Koordinaten versteht, wird die Platte eingemessen:

1. Die Stiftspitze wird von Hand mittig auf drei Bohrungen gefahren (oben links P1, oben rechts P2, unten links P3).
2. Aus den drei Punkten entsteht ein Koordinatensystem:
   - x-Achse: `ex = (P2 − P1)`, normiert
   - y-Achse: der Anteil von `(P3 − P1)`, der senkrecht auf `ex` steht, normiert
   - z-Achse: `ez = ex × ey` (zeigt von den Besuchern weg)
   - Ursprung: `O = P1 − 7,5·ex − 7,5·ey` (die Bohrungen sitzen 7,5 mm vom Rand)
3. Kontrolle: Der Abstand der Bohrungen muss 385 mm ± 2 mm sein, und die vierte Bohrung muss auf weniger als 2 mm getroffen werden.

Dieses Koordinatensystem wird dem Roboter als *Workobject* übergeben. Danach kann jede Position direkt in Plattenkoordinaten gefahren werden – auch wenn die Platte leicht schief steht.

### 3.4 Virtuelle Wände

Die Platte hat keine Sensoren. Die Wände existieren in der Software:

- Aus der SVG-Datei wird die freigeschnittene Fläche (Kanal mit Inseln) gelesen.
- Diese Fläche wird um den halben Stiftdurchmesser plus eine einstellbare Toleranz verkleinert. Das Ergebnis ist die Fläche, in der sich der Stiftmittelpunkt bewegen darf.
- Jeder Schritt wird vor dem Senden geprüft. Würde er die Fläche verlassen, **gleitet** der Stift an der Wand entlang, statt hängen zu bleiben.

Der Stift kann die erlaubte Fläche also nicht verlassen. Ob er das Holz wirklich berührt, sehen die Gamemaster selbst.

### 3.5 Kürzester Weg

Für den Auto-Lauf berechnet die Software den kürzesten Weg vom Start- zum Zielkreis:

- Knoten sind Start, Ziel und alle Ecken, um die man „herumbiegen“ muss.
- Zwei Knoten sind verbunden, wenn die gerade Linie zwischen ihnen vollständig in der erlaubten Fläche liegt (Sichtbarkeitsgraph).
- Der Dijkstra-Algorithmus findet darin den kürzesten Weg.

Für den ersten Entwurf ist dieser Weg rund 1,2 m lang und in unter einer Sekunde berechnet.

### 3.6 Zeitmessung

- Start- und Ziellinie haben eine Richtung. Gezählt wird nur das Überfahren in Fahrtrichtung.
- Maßgeblich ist die Uhr des Servers. Der Zeitpunkt des Überfahrens wird zwischen zwei Schritten interpoliert.
- Beim Auto-Lauf hält der Roboter kurz an Start- und Ziellinie; gemessen wird dazwischen. Läuft das Logger-Programm auf dem Controller, kann stattdessen die echte Position ausgewertet werden.

## 4. Sicherheit

**Grundsatz: Die Absicherung vor Ort trägt die Sicherheit. Die Software ergänzt sie nur. Ein Software-Stopp ersetzt nie den Not-Halt.**

| Maßnahme | Beschreibung |
|---|---|
| Betriebsart | Automatik mit Absicherung (mit dem Lehrer abgeklärt) |
| Absperrung | Besucher stehen außerhalb der Reichweite des Roboters. Position der Absperrung: wird am 18.11. festgelegt |
| Not-Halt | in Reichweite von Gamemaster 2, der während des Betriebs beim Roboter bleibt |
| Rollen | Gamemaster 1 bedient das Tablet, Gamemaster 2 beobachtet Roboter und Besucher |

Software-Grenzen (zusätzlich):

- **Arbeitsraum:** Fahrziele werden nur innerhalb der Platte und zwischen „Rückzug“ und „Eintauchtiefe“ angenommen. Eingetaucht darf der Stift nur im Kanal stehen. Alles andere lehnt der Treiber ab.
- **Geschwindigkeit:** getrennte Grenzen für Besucher, Auto-Lauf und Anfahrt. Die harten Obergrenzen stehen in der Datei `config.toml` und lassen sich in der Oberfläche nicht überschreiten.
- **Totmann-Logik:** Kommt 300 ms lang kein Tastensignal vom Besucher-Bildschirm, gelten alle Tasten als losgelassen. Dasselbe passiert, wenn das Fenster den Fokus verliert.
- **Fehler:** Bei Verbindungsverlust oder einem unbekannten Fehler werden keine Fahrbefehle mehr gesendet. Beide Oberflächen zeigen einen Hinweis. Erst nach „Home anfahren“ durch einen Gamemaster sind neue Läufe möglich.
- **Nur der Laptop steuert:** Andere Geräte im WLAN können den Roboter nicht bewegen. Das Admin-Panel ist mit einer PIN geschützt.

**Grenze der Software:** Eine bereits gesendete Bewegung fährt der Roboter zu Ende. „Lauf abbrechen“ wirkt deshalb beim Auto-Lauf erst nach dem laufenden Wegstück. Im Notfall gilt immer der Not-Halt.

### Ablauf nach einem Not-Halt

1. Ursache klären und beseitigen.
2. Not-Halt entriegeln, am Controller quittieren.
3. **Motoren an** (Taster am Controller).
4. FlexPendant: **PP to Main** → bestätigen → **Play**.
5. Die Software verbindet sich von selbst neu.
6. Am Tablet prüfen, dass der Stift frei ist (sonst von Hand herausfahren), dann **Home anfahren**.

## 5. Bedienungsanleitung für die Aufsicht

Der komplette Ablauf mit Kalibrierung, `SERVER.mod` und Tool steht in der [Setup-Anleitung](Setup-Anleitung.md).

### 5.1 Start

1. Roboter-Ethernet an den Laptop, Monitor anschließen, Hotspot einschalten.
2. Roboter einschalten, Schlüsselschalter auf **Automatik**, **Motoren an**.
3. FlexPendant: **ABB** → **Production Window** → **PP to Main** → bestätigen → **Play-Taste**.
4. Am Laptop `start.bat` doppelklicken. Der Besucher-Bildschirm öffnet sich im Vollbild.
5. Tablet: `http://192.168.137.1:8000/admin` öffnen, PIN eingeben.
6. **Roboter** → Treiber **Standard**. Wenn „Verbunden“ erscheint: Arbeitsraum prüfen, **Home anfahren**.

### 5.2 Einmessen (nach jedem Auf- oder Umbau der Platte)

1. **Einmessen** öffnen. Unter **Roboter** das Koordinatensystem **Basis** wählen.
2. Mit dem Jog-Pad die Stiftspitze mittig auf die Bohrung **oben links** fahren (aus Sicht der Besucher), **Übernehmen**.
3. Ebenso **oben rechts**, **unten links** und zur Kontrolle **unten rechts**.
4. Ergebnis prüfen: Abstände Plattenbreite − 15 mm (300er-Platte: 285 mm) ± 2 mm, Kontrollabweichung unter 2 mm.
5. **Einmessung aktivieren**, dann **Home anfahren**.

Werkzeug-Versatz, Stiftdurchmesser, Eintauchtiefe, Rückzug und Besucherseite stehen auf derselben Seite.

### 5.3 Spielbetrieb

- Der Besucher gibt Name und Geburtsjahr ein und drückt **Start**. Der Roboter fährt in den Startkreis, nach dem Countdown ist die Steuerung frei.
- Die Zeit startet an der Startlinie und stoppt an der Ziellinie. Danach fährt der Roboter Home.
- **Aufgeben** ist jederzeit möglich (zweimal klicken). Es gibt keinen Eintrag.
- Auf dem Tablet zeigt die **Übersicht** die Live-Karte. **Lauf abbrechen** wirkt mit einem Tipp.
- **Töne:** Der Besucher-Bildschirm piept beim Countdown (3 · 2 · 1 · Los) und spielt einen Ton bei Ziel, neuer Bestzeit, Wandberührung und Aufgeben. Unter **Spiel → Töne** lassen sie sich ausschalten, die Lautstärke einstellen und jeder Ton testen. Der Ton kommt aus dem Laptop; zusätzlich gilt die Windows-Lautstärke.

### 5.3a Dashboard, Profile, Export und Statistik

- **Admin → Dashboard:** Live-Vorschau des Besucher-Bildschirms und der Statistik-Seite (die Vorschau steuert nichts und spielt keine Töne). Hier stellst du ein: **Darstellung** Dunkel/Hell (gilt für Besucher-Bildschirm und Statistik), wie oft die Bestenliste im Leerlauf zwischen den Tempi wechselt, **Töne** (an/aus, Lautstärke, Testen) sowie Countdown und Ergebnisdauer.
- **Bestenlisten-Profile (Admin → Bestenliste):** Jedes Profil hat eigene Bestenlisten, z. B. „Probelauf“ und „Tag der offenen Tür“. Neue Zeiten landen immer im aktiven Profil, die anderen bleiben gespeichert. Wechseln geht nur, wenn gerade kein Lauf ist. Das aktive Profil lässt sich nicht löschen.
- **Export:** „Aktives Profil exportieren“ (oder „Export“ beim jeweiligen Profil) lädt eine CSV-Datei, die sich direkt in Excel öffnet: Platz im Tempo, Tempo, Name, Geburtsjahr, Alter, Zeit, Status, Labyrinth, Datum.
- **Statistik-Seite fürs zweite iPad:** `http://192.168.137.1:8000/stats` im Safari öffnen und über Teilen → „Zum Home-Bildschirm“ als Vollbild-App ablegen. Sie zeigt Zahlen zum Tag, „Zeit nach Alter“ (jeder Lauf ein Punkt, Form und Farbe = Tempo), die schnellste Zeit je Altersgruppe und die Top 5 je Tempo. Alles aktualisiert sich live, ein Login ist nicht nötig.

### 5.3b Wiederholungen (Replays)

- Bei jedem Besucher-Lauf wird der gefahrene Weg mitgespeichert – auch bei Wandberührung oder Aufgeben. Läufe von vor dieser Funktion haben keine Aufzeichnung („ohne Aufzeichnung“).
- **Statistik-iPad:** „Letzte Versuche“ zeigt die letzten 8 Versuche, die Top 5 jedes Tempos haben einen Abspiel-Knopf. **Ansehen** spielt den Lauf auf der Labyrinth-Karte im Original-Rhythmus ab. **Am echten Roboter** schickt eine Anfrage; auf dem Tablet erscheint das Banner „Wiederholung angefragt“ mit Freigeben/Ablehnen (ohne Antwort verfällt die Anfrage nach 60 s).
- Alles auf dem Statistik-iPad kehrt von selbst zur Startansicht zurück: 45 s ohne Berührung, 12 s nach dem Ende einer Wiedergabe, 5 s nach einer Anfrage.
- **Admin → Bestenliste:** Bei jedem Lauf **Ansehen** (virtuell) und **Am Roboter** (startet sofort nach Bestätigung).
- Der Roboter fährt den aufgezeichneten Weg mit dem damaligen Tempo (heutiger Wert in mm/s) und den Pausen nach – immer begrenzt auf die **heutige** befahrbare Fläche und die Besucher-Geschwindigkeitsgrenzen. Eine Wiederholung erzeugt keinen Eintrag und lässt sich wie jeder Lauf mit **Lauf abbrechen** stoppen.

### 5.3c Leerlauf-Show

- Spielt für eine einstellbare Zeit niemand (**Dashboard → Leerlauf-Show → Startet nach**, Standard 5 min), macht der Arm ein paar große, ruhige Bewegungen: aufrichten, nach links und rechts schauen, ganz nach oben strecken, links und rechts ganz ausstrecken (volle Spannweite), nicken, winken, Stift drehen – und das **ohne Pause in Dauerschleife**, bis jemand spielt, am Besucher-Bildschirm tippt oder der Admin sie stoppt; dann fährt er über die aufrechte Stellung Home. **Jetzt vorführen** spielt die Show einmal ab, auch wenn „Automatisch“ aus ist.
- **Sicherheit:** Jede Bewegung wird vorher aus Home-Position, Tool und Einmessung berechnet (Vorwärtskinematik des IRB 120, 24 Prüfpunkte pro Bewegung entlang Arm, Halter und Stift). Gefahren werden nur Bewegungen mit mindestens **8 cm Abstand** zur Platte (inkl. Ständer darunter und Raum dahinter) und zum Tisch, innerhalb der Achsbereiche (10° Reserve) und nur innerhalb des **freien Umkreises** (Einstellung, Standard 75 cm). Ganz ausgestreckt braucht der Arm etwa 70 cm; ist der Umkreis kleiner, werden diese Figuren ausgelassen. **Im eingestellten Umkreis darf nichts stehen** (Laptop, Monitor, Absperrung). Ohne Einmessung oder mit zu wenigen freien Bewegungen startet keine Show. Das Admin-Panel zeigt „x von y frei“.
- **Bewegungen:** „Ausgestreckt“ zeigt die volle Spannweite (ganz nach oben, links und rechts ganz aus; braucht ca. 70 cm Umkreis). „Kompakt“ ist die ruhigere Variante ohne Ausstrecken, der Arm bleibt im Umkreis von etwa 52 cm.
- Startet ein Besucher, fragt jemand einen Auto-Lauf/eine Wiederholung an oder bewegt der Admin den Roboter, beendet der Arm die aktuelle Bewegung und fährt sofort Home.
- **Größe:** Für jede Variante getrennt einstellbar (10–100 %). Alle Figuren werden um die aufrechte Haltung verkleinert – bei 50 % schwenkt jede Achse nur halb so weit. Da die Endlagen im Controller eng und nicht genau bekannt sind: klein anfangen (z. B. 30 %) und in RobotStudio langsam erhöhen, bis eine Endlage meldet; dann eine Stufe zurück.
- **Achsgrenzen:** Die Show rechnet mit den Grenzen aus `config.toml` (`joint_limits`, Grad, 10° Reserve). Im Controller sind eigene, engere Endlagen einprogrammiert – diese Werte dort eintragen (Konfiguration → Motion → Arm → rob1_1 … rob1_6, „Lower/Upper Joint Bound“ in Radiant × 57,2958). Figuren, die nicht hineinpassen, werden ausgelassen.
- Standardmäßig **aus**. Vor dem ersten Einsatz am Roboter mit niedrigem Tempo (z. B. 30 mm/s) ausprobieren, Hand am Not-Halt, Bereich um den Roboter frei.

### 5.4 Auto-Lauf

- Besucher: **Roboter fahren lassen**. Auf dem Tablet erscheint ein Banner: **Freigeben** oder **Ablehnen**.
- Vor dem Freigeben prüfen, dass niemand im Bereich des Roboters ist.
- Der Admin kann den Auto-Lauf auch direkt unter **Spiel** starten.

### 5.5 Störungen

| Anzeige | Was tun |
|---|---|
| Besucher-Bildschirm: „Kurze Pause …“ | Tablet ansehen: Verbindung und Hinweis unter **Übersicht** |
| „Getrennt“ | Kabel, Controller-Zustand (Automatik, Motoren an, Programm läuft) prüfen. Die Software verbindet sich selbst neu |
| „Home nicht bestätigt“ | Stift frei? Dann **Roboter → Home anfahren** |
| Stift bleibt an einer Wand hängen | Lauf abbrechen, Wandtoleranz unter **Spiel** leicht erhöhen |
| Roboter steht, Motoren aus | Ablauf wie nach Not-Halt (Abschnitt 4) |
| Tablet erreicht die Seite nicht | Hotspot an? Tablet im richtigen WLAN? Firewall-Regel (siehe README) |

### 5.6 Abbau

1. Am Tablet **Home anfahren**, dann **Trennen**.
2. Server-Fenster am Laptop schließen.
3. Am FlexPendant Programm stoppen, Motoren aus, Roboter ausschalten.
4. Die Datenbank mit der Bestenliste liegt in `data\labyrinth.db` (Backups in `data\backups`).

## 6. Ergebnisse und Erkenntnisse

Wird nach den Robotertermin (18.11. und 20.11.) und nach dem Tag der offenen Tür ergänzt:

- Messprotokoll der Diagnose (Antwortzeiten, Nachlauf, Reichweite)
- gewählte Einstellungen (Geschwindigkeiten, Zone, Wandtoleranz)
- Erfahrungen am Veranstaltungstag (Anzahl Läufe, beste Zeiten, Probleme)

Stand der Software am 14.11.: Alle Funktionen laufen im Simulator. 100 automatische Tests prüfen Protokoll, Geometrie, Einmessen, Spielablauf und das Zusammenspiel mit einem nachgebauten Controller.

## 7. Anhang

### 7.1 Befehle von SERVER.mod (TCP, Port 5000)

Anfrage: `<Code> <Parameter …> #` · Antwort: `<Code> <1 = ok | 0 = Fehler> <Daten>`

| Code | Funktion | Parameter |
|---|---|---|
| 0 | Ping | – |
| 1 | linear fahren (`MoveL`) | x y z q1 q2 q3 q4 |
| 2 | Gelenke fahren (`MoveAbsJ`) | j1 … j6 in Grad |
| 3 | Pose lesen | – |
| 4 | Gelenke lesen | – |
| 6 | Werkzeug setzen | x y z q1 q2 q3 q4 |
| 7 | Workobject setzen | x y z q1 q2 q3 q4 |
| 8 | Geschwindigkeit setzen | v_tcp v_ori (mm/s, °/s) |
| 9 | Zone setzen | fine(0/1) pzone_tcp pzone_ori zone_ori |
| 30 | Punkt in den Puffer | x y z q1 q2 q3 q4 |
| 31 | Puffer leeren | – |
| 32 | Pufferlänge lesen | – |
| 33 | Puffer abfahren | – |
| 98 | Roboter-Info | – |
| 99 | Verbindung schließen | – |

Quaternionen bei ABB: `[q1, q2, q3, q4] = [w, x, y, z]`.

### 7.2 Einstellungen im Admin-Panel

| Einstellung | Standard | Bereich |
|---|---|---|
| Geschwindigkeit Besucher | 50 mm/s | 10–150 |
| Geschwindigkeit Auto-Lauf | 250 mm/s | 50–1000 |
| Geschwindigkeit Anfahrt | 100 mm/s | 20–300 |
| Takt der Steuerung | 25 Hz | 10–50 |
| Zone beim Steuern | z1 | z0, z1, z5 |
| Stiftdurchmesser | 8 mm | 1–14 |
| Wandtoleranz | 1,0 mm | −1 bis +3 |
| Reserve im Auto-Lauf | 1,5 mm | 0–5 |
| Eintauchtiefe | 5 mm | 0–20 |
| Rückzug | 30 mm | 10–100 |
| Stiftdrehung | 0° | −180 bis 180 |
| Countdown | 3 s | 0–5 |
| Ergebnis anzeigen | 8 s | 3–30 |
| Töne | an | an, aus |
| Lautstärke | 70 % | 0–100 % |
| Darstellung Besucher/Statistik | Dunkel | Dunkel, Hell |
| Bestenliste wechseln alle | 8 s | 0–60 s (0 = aus) |
| Leerlauf-Show | aus | an, aus |
| Show startet nach | 5 min | 1–120 min |
| Tempo der Show | 100 mm/s | 20–250 mm/s |
| Freier Umkreis | 75 cm | 40–100 cm |
| Bewegungen der Show | Ausgestreckt | Ausgestreckt, Kompakt |
| Größe: Ausgestreckt | 50 % | 10–100 % |
| Größe: Kompakt | 100 % | 10–100 % |
| Besucherseite | gegenüber | gegenüber, Roboterseite |
| Zeitmessung Auto-Lauf | Halt an Linien | LOGGER, Halt an Linien, berechnet |

### 7.3 Labyrinth als SVG

- `width="400mm" height="400mm" viewBox="0 0 400 400"`: eine Einheit ist ein Millimeter.
- Gruppe `id="Schnitt"`: Plattenrand, vier Bohrungen Ø 5 mm (7,5 mm vom Rand) und der Kanal als geschlossene Kontur. Geschlossene Konturen innerhalb des Kanals sind Inseln.
- Gruppen `id="Gravur_…"` werden nur angezeigt, nicht als Wand gewertet.
- Im Admin unter **Labyrinth** hochladen, Start und Ziel prüfen, Weg berechnen, aktivieren.
