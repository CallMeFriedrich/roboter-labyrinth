# Setup-Anleitung: vom Einschalten bis zur Freigabe

Stand: 25.11.2026. Gilt für ABB IRB 120 am IRC5, Platte „Heißer Draht 300“ (300 × 300 mm).
Wie alles technisch funktioniert, steht in [Dokumentation.md](Dokumentation.md).

## Was muss ich wann machen?

| Situation | Kapitel |
|---|---|
| Neuer Laptop | 1, dann alles Weitere |
| Normaler Tag, nichts verändert | 2 → 4.4 → 5 → 9 |
| Jemand anderes hat den Roboter benutzt | 2 → 4 → 5 → 9 |
| Stift oder Halterung verändert | 6 → 7 → 8 → 9 |
| Platte verschoben | 8 → 9 |
| Batterie leer, Marken stimmen nicht, Stift dreht sich beim Fahren mit | 3 → 6 → 7 → 8 → 9 |
| Not-Halt gedrückt | 10 |

## Sicherheit

- **Gamemaster 2 steht immer am Not-Halt**, solange sich der Roboter bewegen kann. Niemand ist in der Absperrung.
- **„Lauf abbrechen“ ersetzt nie den Not-Halt.** Eine schon gesendete Bewegung fährt der Roboter zu Ende.
- **Vor jedem Play prüfen, welches Programm geladen ist** (Kapitel 4.4). Ein fremdes Programm fährt sofort los.
- Beim ersten Fahren nach einer Änderung: Platte weg, langsam, kleine Schritte.
- Beim Fahren von Hand schützt die Software **nicht** vor Zusammenstößen mit Tisch, Platte oder dem Roboter selbst.

## Was ihr braucht

Roboter mit FlexPendant, Laptop, Netzwerkkabel, Tablet, Besucher-Monitor mit Tastatur, Platte mit Gestell und Zwingen, Stift mit Halterung, Lineal/Messschieber, Wasserwaage, eine feste Spitze (Schraube), USB-Stick (FAT32) mit `SERVER.mod`.

---

## 1. Laptop einrichten (einmalig)

1. Python 3.12 installieren und den Projektordner auf den Laptop kopieren.
2. PowerShell **als Administrator** öffnen, in den Projektordner wechseln (dort liegt `start.bat`) und ausführen. Das braucht Internet:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
   ```
   Es richtet Python ein und gibt Port 8000 im privaten Netz frei.
3. Ethernet-Anschluss zum Roboter: feste IP **192.168.0.100**, Maske **255.255.255.0**, Gateway leer.
4. In `config.toml` unter `[robot]` muss stehen: `ip = "192.168.0.30"`. Nach Versuchen mit RobotStudio unbedingt zurückstellen.
5. Mobilen Hotspot einrichten. Netzwerkprofil in Windows: **Privat**.
6. Admin-PIN ändern, danach den Server neu starten:
   ```powershell
   .venv\Scripts\python tools\set_pin.py
   ```
7. Für den Veranstaltungstag: Energiesparen und Bildschirmschoner aus, „Nicht stören“ ein, Updates pausieren.

Prüfen, ob das Kabel zum Roboter funktioniert:

```powershell
ping 192.168.0.30
```

---

## 2. Roboter einschalten

1. Netzwerkkabel Controller ↔ Laptop einstecken, Arbeitsraum freimachen.
2. Hauptschalter am Controller **ein**. Warten, bis das FlexPendant bereit ist.
3. Meldungen lesen und bestätigen. Steht dort etwas von **Umdrehungszählern nicht aktualisiert**, zuerst Kapitel 3.

Den Schlüsselschalter braucht ihr in zwei Stellungen:

| Stellung | Wofür |
|---|---|
| **Einrichtbetrieb (Manuell)** | Kalibrieren, Tool einmessen, Programm laden, Fahren mit dem Joystick (Freigabetaste halten) |
| **Automatik** | alles, was über Tablet und Laptop läuft, und der Spielbetrieb |

---

## 3. Achsen prüfen und kalibrieren

Nur nötig, wenn etwas nicht stimmt. **Nur zusammen mit dem Lehrer**, denn es betrifft alle Programme auf dem Roboter. Vorher ein Backup machen.

**Warum das wichtig ist:** Sind die Achsen falsch kalibriert, rechnet der Controller mit falschen Winkeln. Das sieht so aus: Der Stift dreht sich beim geraden Fahren mit, Strecken stimmen nicht, das Einmessen ergibt kein Quadrat. Kein Tool und keine Einstellung in der Software kann das ausgleichen.

### 3.1 Prüfen

1. Platte wegstellen. Einrichtbetrieb, **Bewegen**, Bewegungsart **Achse 1–3** bzw. **Achse 4–6**.
2. Alle sechs Achsen langsam auf **0°** fahren. Bei 0° steht der Oberarm senkrecht, der Unterarm zeigt waagrecht nach vorne, der Flansch ebenfalls.
3. An jeder Achse müssen die **Synchronisationsmarken** genau übereinanderstehen.
   - Alle Marken passen: nichts tun, weiter mit Kapitel 4.
   - Eine Marke passt nicht: 3.2.

### 3.2 Umdrehungszähler aktualisieren

1. Einrichtbetrieb, **Achse für Achse** so fahren, dass die Marken übereinanderstehen. **Nach den Marken richten, nicht nach der Anzeige.** Jede Achse immer aus derselben Richtung anfahren.
2. **Achse 6:** nicht um ganze Umdrehungen verdrehen. Steht sie eine Umdrehung falsch, geht die richtige Kalibrierstellung beim IRB 120 verloren, auch wenn die Marke passt. Auf den Werteaufkleber am Roboter achten.
3. **ABB → Kalibrierung** → `ROB_1`.
4. Ab RobotWare 6.02: **Manuelle Methode (erweitert)**.
5. **Umdrehungszähler → Umdrehungszähler aktualisieren …** → **Ja**.
6. Die betroffenen Achsen anhaken → **Aktualisieren** → nochmals **Aktualisieren**. Das lässt sich nicht rückgängig machen.
7. **Prüfung 3.1 wiederholen.** Pflicht, denn ein falsch aktualisierter Zähler führt zu falschen Bewegungen.

Quelle: ABB Produkthandbuch IRB 120 (3HAC035728-001), Abschnitte 5.2, 5.3 und 5.7. Menünamen können je nach RobotWare leicht abweichen.

### 3.3 Danach ist alles Alte ungültig

Home, Tool und Einmessung der Platte **neu machen** (Kapitel 6, 7, 8). Am Tablet zuerst **Einmessen → Aktive Einmessung entfernen**.

---

## 4. SERVER.mod auf den Controller laden

`SERVER.mod` ist das Programm auf dem Roboter, mit dem unsere Software spricht. Die Datei liegt im Projekt unter `reference\rapid\SERVER.mod` und wird **nicht verändert**. Das Laden ist nur beim ersten Mal nötig oder wenn jemand das Programm ersetzt hat.

### 4.1 Fremdes Programm sichern

1. Einrichtbetrieb. **ABB → Programmeditor**, Task **T_ROB1**.
2. Ist ein fremdes Programm geladen: **Datei → Programm speichern unter …**, damit nichts verloren geht. Im Zweifel den Lehrer fragen.

### 4.2 Laden

1. `SERVER.mod` auf einen USB-Stick (FAT32) kopieren und am FlexPendant oder Controller einstecken. Alternativ über RobotStudio.
2. **Datei → Neues Programm …** Die Frage nach dem Speichern mit Nein beantworten, gesichert ist schon.
3. **Module → Datei → Modul laden …** → USB-Laufwerk → `SERVER.mod` → **OK**.
4. Das automatisch angelegte leere `MainModule` markieren → **Datei → Modul löschen**. Es enthält ein zweites `main`, und es darf nur eines geben.
5. Kontrolle: Es bleiben nur `SERVER` und die Systemmodule (`BASE`, `user`). Im Modul steht `ipController := "192.168.0.30"`.

### 4.3 Dauerhaft speichern

**Datei → Programm speichern unter …** → Name **`Labyrinth`**. Künftig genügt im Produktionsfenster **Programm laden … → `Labyrinth`**.

### 4.4 Starten (jeden Tag)

1. Schlüsselschalter auf **Automatik**, bestätigen.
2. **Motoren an** (Taster am Controller).
3. Quickset-Menü (unten rechts) → **Tasks**: nur **T_ROB1** angewählt. `T_ROB2` **abwählen**, sonst stoppt Fehler 40813 alles.
   - Lässt sich nichts abwählen: im Einrichtbetrieb versuchen, oder Systemsteuerung → FlexPendant → Task-Panel-Einstellungen.
4. **Produktionsfenster:** In `T_ROB1` muss **`SERVER`** stehen. **Sonst nicht Play drücken**, sondern `Labyrinth` laden.
5. **PZ → main** (PP to Main) → bestätigen → **Play**.
6. Der Roboter bewegt sich nicht. Am Pendant steht: `SERVER: Server waiting for incoming connections ...`

---

## 5. Software starten und verbinden

1. Monitor anschließen (erweitern, rechts vom Laptop), Mobilen Hotspot einschalten.
2. `start.bat` doppelklicken. Ohne zweiten Monitor: `start.bat fenster`. Das schwarze Fenster bleibt offen.
3. Tablet ins Hotspot-WLAN, `http://192.168.137.1:8000/admin` öffnen (mit `http://`), PIN eingeben.
4. **Roboter → Treiber: Standard**. Nach wenigen Sekunden: „Verbunden, Home offen“.

**Nicht sofort Home anfahren, wenn etwas verändert wurde.** Erst prüfen, ob die gespeicherte Home-Stellung noch passt und der Weg frei ist.

| Fehlermeldung | Bedeutung | Lösung |
|---|---|---|
| **verweigert** (10061) | Netzwerk gut, `SERVER` läuft nicht | Kapitel 4.4 |
| **timed out**, Ping geht | `SERVER` hängt an einer alten Verbindung oder ist gestoppt | Treiber auf Simulator, Pendant **Stop → PZ → main → Play**, dann wieder Standard |
| **timed out**, Ping geht nicht | Kabel oder IP falsch | Kapitel 1, Schritte 3 und 4 |

---

## 6. Werkzeug (Tool) einmessen

Das Tool sagt dem Roboter, wo die Stiftspitze ist und wohin der Stift zeigt. **z zeigt entlang des Stifts aus der Spitze heraus.**

> **Für die Software zählt nur der Wert am Tablet** (Einmessen → Werkzeug). Das Tool im Pendant dient zum Ermitteln und Kontrollieren.

**Aktuelle Werte** (26.11.2026, Endschalter mit Federstab, rechtwinklig zum Flansch, gemessen):

| x | y | z | q1 | q2 | q3 | q4 |
|---|---|---|---|---|---|---|
| −140 | 0 | 30 | 0,7071068 | 0 | −0,7071068 | 0 |

Vorher (bis 25.11., Schraubendreher in der gedruckten Halterung): −110 / 0 / 30, gleiche Drehung.

Der Federstab ist biegsam: beim Einmessen die Bohrungen nur berühren, nicht drücken.

### 6.1 Weg A: ausmessen

Für diese Halterung, solange der Stift rechtwinklig zum Flansch steht:

- **x** = Flanschmitte bis Spitze, **negativ** eintragen.
- **z** = Flanschfläche bis Stiftachse.
- y = 0, Quaternion wie oben. **Auf die zwei Minuszeichen bei x und q3 achten.**

### 6.2 Weg B: „TCP & Z“ am FlexPendant

Video dazu: [ABB RobotStudio Tool Definition with TCP & Z](https://youtu.be/dKPoA5kXlFM) (2:35 min, Ardavan Bidgoli). Vorher anschauen, am Veranstaltungstag gibt es kein Internet.

1. Einrichtbetrieb. Eine Schraube mit der Spitze nach oben **fest einspannen**.
2. **Bewegen → Werkzeug → Neu …** (z. B. `tStift`). Danach **Bearbeiten → Wert ändern**: `mass` auf das ungefähre Gewicht, z. B. **0.1**. Bei −1 lässt sich das Tool nicht auswählen.
3. Tool markieren → **Bearbeiten → Definieren …** → Methode **TCP & Z**, **4 Punkte**.
4. **Punkte 1–4:** jedes Mal dieselbe Spitze auf die Schraube, aber mit **deutlich verschiedener Neigung** (30–60°, aus verschiedenen Richtungen). Jeweils **Position ändern**. Beim 4. Punkt den Stift gerade stellen, zum Beispiel senkrecht.
5. **Z-Punkt:** Den Stift **gerade entlang seiner Achse zurückziehen**, 50–100 mm, ohne zu drehen. Die Schraube liegt danach vor der Spitze, in der Verlängerung des Stifts. **Position ändern**.
   - Steht der Stift bei Punkt 4 senkrecht nach unten, einfach linear im Koordinatensystem **Basis** in **+Z** hochfahren.
6. **OK.** Mittlerer Fehler unter 0,5 mm ist gut, über 1 mm wiederholen.
7. `trans` (x, y, z) und `rot` (q1–q4) ablesen. **Vorzeichen genau abschreiben.** Ein falsches Minus bei q3 hat uns Tage gekostet.

### 6.3 Kontrolle (immer)

Am Pendant das Tool auswählen:

| Test | Muss so sein |
|---|---|
| **Umorientieren**, Spitze auf der Schraube | Spitze bleibt stehen (wenige mm sind ok) |
| **Linear, Koordinatensystem Werkzeug, +Z** | Stift fährt **in Richtung seiner Spitze** |

Fährt er rückwärts, war der Z-Punkt auf der falschen Seite. Dann 6.2 wiederholen.

### 6.4 Eintragen

1. Zurück auf Automatik und starten (Kapitel 4.4).
2. Tablet: **Einmessen → Werkzeug**, 7 Werte eintragen → **Tool setzen**.
3. Nach jeder Änderung am Tool: Platte **neu einmessen** (Kapitel 8).

---

## 7. Stift ausrichten und Home einlernen

1. Platte wegstellen. Einrichtbetrieb, **Achse 4–6**.
2. **Flansch nach unten, Stift waagrecht nach vorne** in Richtung Platte. Mit der Wasserwaage prüfen.
   Zur Orientierung, unser Home: `[0 / −5,8 / 54,7 / 0 / 41 / 0]` Grad. Das gilt nur bei richtig kalibrierten Achsen.
3. Automatik, starten (Kapitel 4.4). Ab jetzt nur noch mit dem Tablet fahren: **Roboter → Von Hand fahren**, Koordinatensystem **Basis**.
4. Eine Stellung wählen, die frei und deutlich **vor** der Platte liegt.
5. **„Aktuelle Stellung als Home einlernen“**. Erst danach **Home anfahren**. Der Roboter darf sich dabei kaum bewegen.

### Linealtest (Pflicht nach Kalibrierung oder Tool-Änderung)

Tablet, **Basis**, Schrittweite 10 mm, ohne Platte:

| Fahren | Muss |
|---|---|
| 20 × nach rechts | 200 mm am Lineal, gleiche Höhe |
| 10 × nach oben | 100 mm am Lineal, senkrecht |
| die ganze Zeit | Stift bleibt parallel zu sich selbst |

**Die Anzeige am Tablet reicht nicht**, sie zeigt nur den befohlenen Wert. Stimmt der Test nicht: **nicht einmessen**, zurück zu Kapitel 3. Dass sich das Handgelenk mitdreht, ist normal. Der Stift selbst darf sich nicht drehen.

---

## 8. Platte einmessen

1. Platte aufstellen und **festspannen**. Lose Klötze verrutschen bei der ersten Berührung. Die Platte steht senkrecht, gerade vor dem Roboter und in Höhe etwa der Schulter.
   Zur Orientierung, am 25.11.: Plattenmitte bei x ≈ 492, y ≈ 56, z ≈ 317 mm.
2. **Labyrinth:** richtiges Labyrinth aktiv („Heißer Draht 300“), Start und Ziel stimmen, Weg berechnet.
3. **Einmessen → Stift und Platte:** Stiftdurchmesser, Eintauchtiefe, Rückzug, **Besucher stehen** (entscheidet, welche Bohrung „links“ ist).
4. Der Stift muss **senkrecht zur Platte** stehen. **Diese Kopfstellung behält der Roboter im Spiel bei.** Ab jetzt nicht mehr drehen.
5. **Messpunkte verwerfen**, Koordinatensystem **Basis**.
6. **Oben links** (aus Sicht der Besucher) mit dem Pad anfahren: 10 mm → 1 mm → 0,1 mm. Spitze mittig auf die Bohrung, nur leicht berühren → **Übernehmen**.
7. Die anderen drei Bohrungen:
   1. **Hinfahren** (hält 20 mm davor)
   2. **Näher ran (2 mm)**
   3. mit dem Pad genau auf die Bohrung
   4. **Übernehmen**
8. Ergebnis prüfen:

   | Wert | Soll |
   |---|---|
   | Abstände zur Nachbarbohrung | 285 ± 2 mm, sonst rot |
   | Winkelfehler der Ecke | unter 1° |
   | Kopfdrehung zwischen den Bohrungen | unter 1° |
   | Abweichung Kontrollbohrung | unter 2 mm |

   Ist ein Punkt rot: diese Bohrung neu anfahren und nochmals **Übernehmen**.
9. **Einmessung aktivieren.** Dann mit dem Pad den Stift von der Platte wegfahren.

---

## 9. Probelauf und Freigabe

1. **Spiel:** alle Geschwindigkeiten ganz nach unten.
2. **Übersicht → Freigeben** → „Home anfahren und freigeben“.
3. **Probelauf** am Besucher-Bildschirm, Hand am Not-Halt. Auf Wände, Eintauchtiefe und Richtung achten (W = oben, A = links, S = unten, D = rechts).
4. **Auto-Lauf** langsam. Passt alles, Geschwindigkeiten schrittweise erhöhen.
5. **Bestenliste:** Testläufe löschen, bei Bedarf **Roboter-Bestzeit zurücksetzen**.
6. **Übersicht:** alle Punkte der Checkliste erledigt, oben steht **„Besucher können starten“**.

**Pausieren** sperrt neue Läufe, **Freigeben** hebt das auf.

---

## 10. Nach einem Not-Halt

1. Ursache klären, Not-Halt entriegeln, am Pendant quittieren.
2. **Motoren an**.
3. Programm prüfen (`SERVER`, nur `T_ROB1`), **PZ → main**, **Play**.
4. Die Software verbindet sich von selbst neu.
5. **Steckt der Stift noch im Kanal, nicht Home anfahren.** Zuerst von Hand gerade herausfahren.
6. Ist der Stift frei: **Übersicht → Freigeben**.

---

## 11. Fehler und Lösungen

| Problem | Ursache | Lösung |
|---|---|---|
| Fehler **40813**, `T_ROB2` | zweite Task mitgestartet | `T_ROB2` abwählen (4.4) |
| Roboter fährt nach Play los | fremdes Programm | **Stop**, `Labyrinth` laden (4) |
| Verbindung verweigert / timed out | siehe Tabelle in Kapitel 5 | Kapitel 5 |
| Tool lässt sich nicht auswählen, `tload.mass` ungültig | Masse −1 | `mass` auf z. B. 0.1 |
| Stift dreht sich beim geraden Fahren mit | Achsen falsch kalibriert | Kapitel 3 |
| Einmessen ergibt kein Quadrat | Platte bewegt, falscher Punkt oder Achsen falsch | Sofort-Kontrolle beachten, Platte festspannen, Linealtest |
| Kontrollbohrung rund 20 mm daneben | Punkt direkt nach „Hinfahren“ übernommen | Stift ganz auf die Bohrung fahren (8.7) |
| Stift zeigt in Home nach oben | Achse 5 um 90° falsch, alte Home-Stellung | Kapitel 7 |
| „Ziel außerhalb des Arbeitsraums“ | Grenze in `config.toml` unter `[workspace_base]` | Ziel prüfen, Grenze nur bewusst ändern |
| Tablet erreicht die Seite nicht | Hotspot aus, falsches WLAN, Netz „Öffentlich“ | Hotspot an, Netzwerkprofil Privat. Gast-WLANs trennen Geräte meist |
| Andere Geräte können nicht steuern | Absicht | Nur der Laptop darf steuern |
| Änderungen nicht sichtbar | alter Server oder alte Seite | `start.bat` neu starten, Seite neu laden |

---

## 12. Feierabend

1. **Übersicht → Pausieren**, warten bis kein Lauf mehr läuft.
2. **Roboter → Home anfahren**, dann **Trennen**.
3. Server-Fenster am Laptop schließen.
4. Pendant: **Stop**. Motoren aus, Hauptschalter aus.
5. Bestenliste liegt in `data\labyrinth.db`, Sicherungen in `data\backups`.

## 13. Checkliste für den Veranstaltungstag

- [ ] Platte und Gestell festgespannt, Stift fest
- [ ] Absperrung steht, Not-Halt getestet, Gamemaster 2 am Platz
- [ ] `config.toml`: `ip = "192.168.0.30"`
- [ ] Nur `T_ROB1`, Programm `SERVER`, PZ → main, Play
- [ ] Hotspot an, Tablet verbunden, Treiber Standard
- [ ] Home frei und angefahren
- [ ] Eine Bohrung mit dem Stift kontrolliert: Einmessung passt noch
- [ ] Ein Probelauf und ein Auto-Lauf ohne Wandkontakt
- [ ] Testläufe aus der Bestenliste gelöscht
- [ ] Admin-PIN geändert
- [ ] „Besucher können starten“
