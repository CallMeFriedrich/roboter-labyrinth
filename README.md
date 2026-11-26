# Roboter-Labyrinth

Exponat für den Tag der offenen Tür der TFO Bruneck (28.11.2026): Besucher steuern einen ABB IRB 120 mit W A S D durch ein senkrechtes Holzlabyrinth. Die Software misst die Zeit, führt die Bestenliste und kann den kürzesten Weg selbst fahren.

**Komplette Anleitung vom Einschalten bis zur Freigabe: [docs/Setup-Anleitung.md](docs/Setup-Anleitung.md)**

Alles läuft ohne Roboter im **Simulator**. Am echten Roboter wird nur gemessen und eingemessen.

## Schnellstart auf diesem PC

1. Doppelklick auf **`start.bat`** (oder `start.bat fenster`, wenn kein zweiter Monitor angeschlossen ist).
2. Der Besucher-Bildschirm öffnet sich nach 3 Sekunden: <http://127.0.0.1:8000/>
3. Admin-Panel: <http://localhost:8000/admin> – PIN siehe unten.

Beim ersten Start wird der Labyrinth-Entwurf 1 eingespielt, der Simulator verbindet sich und fährt Home. Danach ist das Spiel sofort spielbar: Name und Geburtsjahr eingeben, **Start**, nach dem Countdown mit **W A S D** oder den Pfeiltasten fahren.

## Einmalige Einrichtung (neuer PC)

```powershell
powershell -ExecutionPolicy Bypass -File setup_windows.ps1
```

Das Skript legt die Python-Umgebung an (`.venv`, Python 3.12), installiert die Pakete aus `requirements.txt` und legt – als Administrator ausgeführt – die Firewall-Regel für Port 8000 im privaten Netz an. Internet braucht nur dieser eine Schritt; im Betrieb läuft alles offline.

## Admin-PIN

Die PIN steht nur als Hash in `config.toml`. Voreingestellt ist **2811**. Vor dem Veranstaltungstag ändern:

```powershell
.venv\Scripts\python tools\set_pin.py
```

Danach den Server neu starten.

## Netzwerk am Veranstaltungstag

| Gerät | Adresse |
|---|---|
| Roboter-Controller | `192.168.0.30`, Port 5000 (LOGGER: 5001) |
| Laptop, Ethernet zum Roboter | fest `192.168.0.100`, Maske `255.255.255.0` |
| Laptop, Windows Mobile Hotspot | `192.168.137.1` |
| Tablet (im Hotspot-WLAN) | öffnet `http://192.168.137.1:8000/admin` |
| Statistik-iPad (im Hotspot-WLAN) | öffnet `http://192.168.137.1:8000/stats` |
| Besucher-Monitor | Kiosk-Browser auf `http://127.0.0.1:8000/` |

- **Hotspot:** Einstellungen → Netzwerk und Internet → Mobiler Hotspot → Ein. SSID und Passwort dort festlegen und hier notieren: SSID `____________`, Passwort `____________`.
- **Tablet:** Adresse in Safari öffnen → Teilen → „Zum Home-Bildschirm“. Die Seite startet dann wie eine App im Vollbild.
- **Steuern darf nur der Laptop selbst.** Andere Geräte im Hotspot sehen den Besucher-Bildschirm, können aber weder starten noch fahren (`visitor_control_hosts` in `config.toml`).

## Start am Veranstaltungstag (Kaltstart < 5 Minuten)

1. Roboter-Ethernet an den Laptop, Besucher-Monitor anschließen (erweitern, rechts vom Laptop).
2. Roboter einschalten, Schlüsselschalter auf **Automatik**, **Motoren an**.
3. FlexPendant: **ABB** → **Production Window** → **PP to Main** → bestätigen → **Play-Taste**.
4. Hotspot einschalten, `start.bat` doppelklicken.
5. Tablet: Admin öffnen, PIN eingeben. Unter **Roboter** den Treiber **Standard** wählen.
6. Arbeitsraum prüfen, dann **Home anfahren**. Der Zustand wechselt auf „Bereit“.
7. Einen Probelauf und einen Auto-Lauf fahren.

Windows vorher vorbereiten: Energiesparen und Bildschirmschoner aus, „Nicht stören“ ein, Updates pausieren.

## Nach einem Not-Halt

1. Ursache klären, Not-Halt entriegeln und am Controller quittieren.
2. **Motoren an**.
3. FlexPendant: **PP to Main** → **Play**.
4. Die Software verbindet sich von selbst neu (alle 2 Sekunden) und schickt Tool und Workobject erneut.
5. Am Tablet prüfen, dass der Stift frei ist, dann **Home anfahren**. Erst danach sind neue Läufe möglich.

Ein Software-Stopp („Lauf abbrechen“) ersetzt nie den Not-Halt: Eine bereits gesendete Bewegung fährt der Roboter zu Ende.

## Die drei Treiber

| Treiber | Wofür |
|---|---|
| **Simulator** | Standard. Kein Roboter nötig, gleiche Zeit-Semantik wie der echte Server |
| **Standard** | echter Roboter über das unveränderte `SERVER.mod` (Schritt-Jog) |
| **Erweitert** | noch nicht gebaut – erst nach dem 18.11. und nur mit Freigabe (CLAUDE.md §8.5) |

Den Standard-Treiber ohne Roboter testen:

```powershell
.venv\Scripts\python tools\fake_controller.py
```

Dann in `config.toml` unter `[robot]` `ip = "127.0.0.1"` setzen, Server neu starten und im Admin **Standard** wählen. Nicht vergessen, die IP danach wieder auf `192.168.0.30` zu stellen.

## Robotertermin 18.11.: Diagnose

```powershell
.venv\Scripts\python tools\diagnose.py
```

Fragt vor jeder Bewegung nach und schreibt `data\diagnose\diagnose_JJJJMMTT_HHMM.json` und `.md`: Ping-Latenz, Roboter-Info, Pose, LOGGER-Prüfung, Antwortzeiten der Schritte (1/2/3/5 mm, 30/50/100 mm/s, z0/z1/z5), Puffer-Test, Reichweite der Plattenecken, Checkliste. Mit `--no-motion` wird nur gelesen.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

## Wo liegt was

| Pfad | Inhalt |
|---|---|
| `config.toml` | Ports, harte Grenzen, PIN-Hash, Simulator-Platte |
| `app/` | Backend: `robot/` (Protokoll, Treiber, Sicherheit), `geometry/` (SVG, Wände, Weg, Einmessen), `game/` (Zustände, Timer, Bestenliste), `api/` |
| `web/` | Besucher-Bildschirm, Admin-Panel, gemeinsame Bausteine, Schrift Inter (lokal) |
| `tools/` | `diagnose.py`, `fake_controller.py`, `set_pin.py`, `svg_to_lightburn.py` (Labyrinth-SVG → LightBurn) |
| `laser/` | LightBurn-Dateien zum Lasern der Platte |
| `data/` | Datenbank `labyrinth.db`, Backups (bei jedem Start), Logs, Diagnose-Protokolle |
| `docs/` | Dokumentation für den Lehrer |
| `reference/` | Originaldateien, unverändert |

Die Datenbank zurücksetzen: Server beenden und `data\labyrinth.db` löschen. Beim nächsten Start wird wieder Entwurf 1 eingespielt.

## Eigenes Labyrinth

SVG in Millimetern (`width="300mm" height="300mm" viewBox="0 0 300 300"`, erlaubt sind 100 bis 600 mm je Seite):

| Gruppe | Inhalt |
|---|---|
| `Schnitt` | rot, wird durchgeschnitten: Plattenrand, **4 Bohrungen Ø 5 mm je 7,5 mm vom Rand**, Kanal-Außenkontur, Inseln |
| `Startlinie`, `Ziellinie` | Linie oder schmales Rechteck **quer über den ganzen Gang**; die kleinere Seite ist der Start- bzw. Zielbereich. Alternativ: Kreise Ø ≈ 26 mm am Gangende |
| `Gravur_…` | wird nur graviert (Logo, Schachbrett) |

Beispiel: `labyrinths/Heisser_Draht_300.svg`, Laserdatei `laser/Heisser_Draht_300.lbrn2`. Neue Laserdatei aus einer SVG: `.venv\Scripts\python tools\svg_to_lightburn.py <svg> <lbrn2>`.

Nach dem Wechsel auf eine andere Plattengröße: Labyrinth im Admin aktivieren und die Platte **neu einmessen** (die Soll-Abstände der Bohrungen richten sich nach dem aktiven Labyrinth).

## Noch offen

Siehe CLAUDE.md §16: endgültiges Labyrinth und welcher Kreis Start ist, Stift (Durchmesser, Tool-Versatz), Besucherseite, Lage der Platte, Optionen des Controllers, LOGGER, TFO-Akzentfarbe (`--accent` in `web/shared/tokens.css`). Alles davon ist im Admin oder in einer Datei einstellbar; am Code muss dafür nichts geändert werden.
