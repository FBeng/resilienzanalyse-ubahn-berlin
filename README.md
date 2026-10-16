# Resilienz-Analyse des Berliner U-Bahn-Netzes

Simulation exogener Streckenausfälle in einem graphentheoretischen Modell des Berliner
U-Bahn-Netzes. Die Ergebnisse gehen als CSV-Tabellen heraus, Auswertung und Abbildungen
entstehen außerhalb dieses Projekts.

Projekt wurde im Rahmen einer Bachelorarbeit von Fabian Beng an der Freien Universität Berlin realisiert.

Forschungsfrage (komprimiert): Wie unterscheidet sich der Zerfall des Berliner U-Bahn-Netzes (GCC, unerreichbare Stationspaare, mittlere Pfadlänge) unter zufälligen, betweennessbasierten und nachfragebasierten Streckenausfällen, und wo liegen die Kipppunkte?

Abgabe: 16.10.2026

## Inhalt

- **`build_graph.py`**: Liest die GTFS-Fahrplandaten und die Baublöcke mit Einwohnerzahlen ein, baut daraus den Graphen des U-Bahn-Netzes (170 Stationen, 183 Strecken) samt Nachfragepotenzial je Strecke und schreibt ihn nach `network.json`.
- **`simulate.py`**: Lässt die Strecken in den vier Szenarien nacheinander ausfallen, misst nach jedem Ausfall die vier Metriken und schreibt alle Ergebnisse als CSV-Tabellen nach `ergebnisse/`.
- **`evaluate2.py`**: Spielt die Ausfallreihenfolgen der drei gezielten Szenarien nach und hält je Schritt Betweenness, Brückeneigenschaft und abgetrennte Stationen in `ergebnisse/ausfaelle_detail.csv` fest.
- **`netvis.py`**: Zeichnet den Graphen aus `network.json` als Netzkarte in Linienfarben und speichert sie als SVG und PNG unter `ergebnisse/abbildungen/`.
- **`test.py`**: Prüft die Metrikformeln aus `simulate.py` an einem kleinen Testgraphen, dessen Werte sich von Hand nachrechnen lassen.
- **`network.json`**: Enthält den fertigen Graphen mit Stationen, Strecken, Einzugsbevölkerung und Nachfragepotenzial und ist die Eingabe für alle weiteren Skripte.
- **`ergebnisse/`**: Enthält die Ergebnistabellen des Laufs mit 100 Zufallsdurchläufen, auf dem die Auswertung beruht.
- **`ergebnisse_1000/`**: Enthält dieselben Tabellen aus einem Kontrolllauf mit 1.000 Zufallsdurchläufen.

Bemerkung: Für die Durchführung der 1000 Zufallsläufe muss in `simulate.py` die entsprechende Konstante angepasst werden und der `ergebnisse`-Ordner gesichert werden, da er sonst überschrieben wird.

## Verarbeitungskette
<pre>
  GTFS/  +  bloecke_ew2025.geojson
               │
        ┌──────▼───────┐
        │build_graph.py│
        └──────┬───────┘
               │
          network.json ──────────────┬──────────────┐
               │                     │              │
        ┌──────▼──────┐              │              │
        │ simulate.py │              │              │
        └──────┬──────┘              │              │
               │                     │              │
        ergebnisse/*.csv             │              │
               │                     │              │
        ┌──────▼──────┐              │       ┌──────▼──────┐
        │ evaluate2.py │◄─────────────┘       │  netvis.py  │
        └──────┬──────┘                      └──────┬──────┘
               │                                    │
     ausfaelle_detail.csv                     netzkarte.svg
</pre>

## Voraussetzungen und Installation

Empfohlen wird Python 3.14, da auch  die Implementierung in 3.14 stattfand.

Zuerst sollte im Projektordner eine virtuelle Umgebung angelegt weden. Sie hält die Bibliotheken getrennt vom restlichen System:

```bash
python3 -m venv .venv
```

Danach die vier Abhängigkeiten aus `requirements.txt` in den dort festgelegten Versionen installieren
(networkx, numpy, pyproj, matplotlib):

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Unter Windows lautet der Pfad `.venv\Scripts\python` 


## Start

Alle Befehle werden im Projektordner ausgeführt, in dieser Reihenfolge. Die Laufzeiten wurden auf
einem Mac gemessen (Python 3.14.0).

```bash
.venv/bin/python test.py          # ~1 s   Selbsttest der Metrikformeln
.venv/bin/python build_graph.py   # ~7 s   Rohdaten -> network.json (optional, siehe unten)
.venv/bin/python simulate.py      # ~16 s  network.json -> ergebnisse/*.csv
.venv/bin/python evaluate2.py      # ~3 s   network.json + ergebnisse/*.csv -> ergebnisse/ausfaelle_detail.csv
.venv/bin/python netvis.py        # ~3 s   network.json -> ergebnisse/abbildungen/netzkarte.svg/.png
```

`network.json` liegt bei, deshalb läuft `simulate.py` auch ohne die Rohdaten.
`build_graph.py` braucht dagegen den Ordner `GTFS/` und die Datei `bloecke_ew2025_EPSG25833.geojson`.
Beide sind wegen ihrer Größe nicht in der Abgabe enthalten. Bezugsquellen stehen unter "Rohdaten".
Mit den Rohdaten erzeugt `build_graph.py` eine byteweise identische `network.json`.

`simulate.py` überschreibt beim Lauf die Tabellen in `ergebnisse/`. `evaluate2.py` muss nach jedem
`simulate.py`-Lauf neu laufen, weil es dessen Ergebnisse liest.

## Rohdaten

Die Rohdaten liegen der Abgabe nicht bei, weil sie zu groß sind (zusammen rund 680 MB). Gebraucht werden
sie nur für `build_graph.py`. Alle anderen Skripte arbeiten mit der beiliegenden `network.json`.

### GTFS-Fahrplandaten

| | |
|---|---|
| Herausgeber | Verkehrsverbund Berlin-Brandenburg (VBB) |
| Quelle | <https://www.vbb.de/vbbgtfs> (ZIP-Download) |
| Abgerufen am | 25.06.2026 |
| Fahrplanperiode | 23.06.2026 bis 12.12.2026 |
| Verwendete Dateien | `routes.txt`, `trips.txt`, `stops.txt`, `stop_times.txt` |

Der Feed enthält keine Versionsnummer. Den Datenstand legen deshalb Abrufdatum und Fahrplanperiode fest.
Ein späterer Feed kann ein anderes Netz ergeben, wenn der VBB Stationen oder Linien ändert.

### Einwohner-Blockdaten

| | |
|---|---|
| Herausgeber | Umweltatlas Berlin, Geodateninfrastruktur Berlin |
| Datensatz | Einwohnerdichte 2025 (Einwohnerstand 2025, 26.613 Baublöcke) |
| Quelle | WFS-Dienst `https://gdi.berlin.de/services/wfs/ua_einwohnerdichte_2025` |
| Abgerufen am | 02.09.2026 über den [WFS-Explorer](https://wfsexplorer.odis-berlin.de/?wfs=https%3A%2F%2Fgdi.berlin.de%2Fservices%2Fwfs%2Fua_einwohnerdichte_2025&layer=ua_einwohnerdichte_2025%3Aua_einwohnerdichte_2025) |
| Koordinatensystem | EPSG:25833 |



### Ablage im Projektordner

Beide Rohdaten gehören direkt in den Projektordner, neben `build_graph.py`:

```
Projektordner/
├── build_graph.py
├── GTFS/                                  entpacktes ZIP des VBB
│   ├── routes.txt
│   ├── trips.txt
│   ├── stops.txt
│   ├── stop_times.txt
│   └── ...
└── bloecke_ew2025_EPSG25833.geojson
```

Ordner- und Dateiname müssen genau so lauten, denn `build_graph.py` sucht die Daten unter diesen Namen.
Wichtig ist, dass die `.txt`-Dateien direkt in `GTFS/` liegen und nicht in einem weiteren Unterordner.


## Parameter

Alle Stellschrauben stehen als Konstanten oben in der jeweiligen Datei.

| Parameter | Wert | Datei | Bedeutung |
|---|---|---|---|
| `SEED` | 42 | `simulate.py` | Startwert des Zufallsgenerators. Damit liefert jeder Lauf exakt dieselbe Zufallsreihenfolge und dieselben Ergebnisse. |
| `N_RANDOM_RUNS` | 100 | `simulate.py` | Anzahl der Durchläufe im Zufallsszenario. Ausgewertet werden Median und Streuungsband über alle Läufe. |
| `TOP_K` | 20 | `simulate.py` | Länge der beiden Ranglisten (Betweenness und Nachfragepotenzial), deren Überschneidung verglichen wird. 20 von 183 Kanten sind rund 10 %. |
| `MAX_DIST_M` | 960 | `build_graph.py` | Maximaler Abstand in Metern zwischen Baublock und Station. Weiter entfernte Blöcke zählen zu keiner Station. 960 m entsprechen 12 Gehminuten (TfL 2015, übernommen von Zhang et al. 2019). |

Wird `MAX_DIST_M` geändert, müssen `build_graph.py` und danach alle weiteren Skripte neu laufen.
Für die übrigen Parameter reicht ein neuer Lauf von `simulate.py` und `evaluate2.py`.

### Kontrolllauf mit 1.000 Zufallsdurchläufen

Der Ordner `ergebnisse_1000/` stammt aus demselben Code mit nur einer Änderung. So lässt er sich erzeugen:

1. Den Ordner `ergebnisse/` sichern, zum Beispiel als Kopie. `simulate.py` überschreibt ihn sonst.
2. In `simulate.py` die Zeile `N_RANDOM_RUNS = 100` in `N_RANDOM_RUNS = 1000` ändern.
3. `.venv/bin/python simulate.py` ausführen. Der Lauf dauert etwa 2,5 Minuten.
4. Den neu geschriebenen Ordner `ergebnisse/` in `ergebnisse_1000/` umbenennen und die Sicherung aus Schritt 1 zurück nach `ergebnisse/` legen.
5. `N_RANDOM_RUNS` wieder auf 100 setzen.

Nachgeprüft am 16.10.2026: Der so erzeugte Lauf ist mit den Tabellen in `ergebnisse_1000/` byteweise
identisch. Nur `laufzeiten.csv` weicht ab, weil sie gemessene Uhrzeiten enthält.

## Ergebnisse

| Ordner | Lauf | Verwendung in der Arbeit |
|---|---|---|
| `ergebnisse/` | Hauptlauf mit 100 Zufallsdurchläufen (`N_RANDOM_RUNS = 100`, `SEED = 42`) | Grundlage aller Abbildungen, Tabellen und Zahlen in Kapitel 6 |
| `ergebnisse_1000/` | Kontrolllauf mit 1.000 Zufallsdurchläufen, sonst identisch | nur Abschnitt 5.3: Prüfung, ob 100 Läufe ausreichen |

Zuordnung der Abbildungen und Tabellen der Arbeit zu den Dateien in `ergebnisse/`:

| In der Arbeit | Inhalt | Datei |
|---|---|---|
| Abb. 1 | Stationsgraph als Netzkarte | aus `network.json`, erzeugt von `netvis.py`|
| Abb. 2 | GCC-Anteil je Szenario mit Streuungsband | `verlauf_gcc.csv` |
| Abb. 3 | Anteil unerreichbarer Stationspaare | `verlauf_unreachable.csv` |
| Abb. 4 | Mittlere Pfadlänge der gezielten Szenarien | `verlauf_apl.csv`, Kipppunkte aus `kennzahlen.csv` |
| Tab. 1 | Die ersten acht Ausfälle der gezielten Szenarien | `ausfaelle_detail.csv` (erzeugt von `evaluate2.py`) |
| Tab. 2 | Kipppunkte der Ausfallszenarien | `kennzahlen.csv` |
| Tab. A1 | Entfernte Scheinkanten | keine CSV, ergibt sich aus `build_graph.py` (Abschnitt "Scheinkanten entfernen") |
| Tab. A2 | Gemessene Laufzeiten | `laufzeiten.csv` |

R-Index und Überschneidung der Top-20-Listen im Text stehen ebenfalls in `kennzahlen.csv`.

## Hinweis zur KI-Nutzung

Der Code wurde mit Unterstützung des KI-Werkzeugs Claude Code (Anthropic) entwickelt, `netvis.py` stammt fast vollständig von Claude Code. Entwurf, Methodik und Prüfung der Ergebnisse lagen beim Verfasser.
Art und Umfang der Nutzung sind in Anhang B der Arbeit dokumentiert.
