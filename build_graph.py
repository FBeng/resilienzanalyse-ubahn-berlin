"""
Baut aus den GTFS-Fahrplandaten und den Einwohner-Blockdaten den Graphen des U-Bahn-Netzes
(Stationen, Strecken) samt Nachfragepotenzial je Strecke und schreibt ihn nach network.json.
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from pyproj import Transformer

HERE = Path(__file__).parent
GTFS = HERE / "GTFS"
BLOCKS = HERE / "bloecke_ew2025_EPSG25833.geojson"
OUT = HERE / "network.json"

UBAHN_ROUTE_TYPE = "400"
MAX_DIST_M = 960


def read_gtfs():
    """Liest die GTFS-Dateien und liefert die Bausteine des Graphen.
    Anforderung: siehe Readme.md
    Es wird genutzt:
    routes.txt      für Linien                         -> route_id, route_short_name, route_type
    trips.txt       für Einzelfahrten einer Linie      -> trip_id, route_id
    stops.txt       für Haltestellen und Bahnsteige    -> stop_id, parent_station, Koordinaten
    stop_times.txt  für Halte jeder Fahrt              -> trip_id, stop_id, stop_sequence

    Immer zwei aufeinanderfolgende Halte einer Fahrt liefern eine Kante. Über alle Kanten
    entsteht die Menge aller Kanten. Zu jeder Kante wird gespeichert welche Linie sie bedient.
    Kanten, die eine Station überspringen, werden entfernt. Stationen und Kanten werden sortiert
    zurückgegeben.

    Rückgabe:
    stations: Dictionary  Stations-ID -> {"name", "lat", "lon"}, nur befahrene Stationen
    edges:    Dictionary  (Station A, Station B) -> Menge der bedienenden Linien
    """
    routes = {}
    with open(GTFS/"routes.txt") as routesFile:
        for row in csv.DictReader(routesFile):
            if row["route_type"] == UBAHN_ROUTE_TYPE:
                routes[row["route_id"]] = row["route_short_name"]

    trip_to_line = {}
    with open(GTFS/"trips.txt", encoding="utf-8") as tripsFile:
        for row in csv.DictReader(tripsFile):
            if row["route_id"] in routes:
                trip_to_line[row["trip_id"]] = routes[row["route_id"]]

    station_info = {}
    with open(GTFS/"stops.txt", encoding="utf-8") as stopsFile:
        rows = list(csv.DictReader(stopsFile))
    for row in rows:
        if row["location_type"] == "1":
            station_info[row["stop_id"]] = {
                "name": row["stop_name"], "lat": float(row["stop_lat"]), "lon": float(row["stop_lon"])}

    stop_to_station = {}
    for row in rows:
        if row["location_type"] in ("0", "1"):
            parent = row.get("parent_station")
            if parent:
                stop_to_station[row["stop_id"]] = parent
            else:
                stop_to_station[row["stop_id"]] = row["stop_id"]

    trip_stops = defaultdict(list)
    with open(GTFS/"stop_times.txt", encoding="utf-8") as stopTimesFile:
        for row in csv.DictReader(stopTimesFile):
            stop_id = row["stop_id"]
            trip_id = row["trip_id"]
            if trip_id not in trip_to_line:
                continue
            if stop_id not in stop_to_station:
                # Ein übersprungener Halt würde Nachbarn direkt verbinden --> Scheinkante
                raise KeyError(f"{stop_id} der Fahrt {trip_id} hat keine Station")
            station_id = stop_to_station[stop_id]
            trip_stops[trip_id].append((int(row["stop_sequence"]), station_id))

    edges = defaultdict(set)
    used = set()
    station_sequences = set()

    for trip_id in trip_stops:
        curr_stops = trip_stops[trip_id]
        curr_stops.sort()
        curr_line = trip_to_line[trip_id]
        curr_station_sequence = [station_id for _, station_id in curr_stops]
        used.update(curr_station_sequence)
        station_sequences.add(tuple(curr_station_sequence))
        for station_a, station_b in zip(curr_station_sequence, curr_station_sequence[1:]):
            if station_a != station_b:
                # sorted Tupel: A-B = B-A ergeben 
                edges[tuple(sorted([station_a, station_b]))].add(curr_line)

    # Hält irgendeine Fahrt zwischen A und C noch an einer Station --> A und C keine Nachbarn
    not_adjacent = set()
    for sequence in station_sequences:
        clean_sequence = []
        for station in sequence:
            if len(clean_sequence) == 0 or clean_sequence[-1] != station:
                clean_sequence.append(station)
        for i in range(len(clean_sequence)):
            for j in range(i + 2, len(clean_sequence)):
                not_adjacent.add(tuple(sorted([clean_sequence[i], clean_sequence[j]])))

    removed = [edge for edge in edges if edge in not_adjacent]
    for edge in removed:
        del edges[edge]
    print(f"{len(removed)} Scheinkanten entfernt")

    sorted_used = sorted(used)
    sorted_edges = dict(sorted(edges.items()))
    sorted_stations = {sid: station_info[sid] for sid in sorted_used}

    return sorted_stations, sorted_edges


def polygon_centroid(geometry):
    """Berechnet den Flächenschwerpunkt eines GeoJSON-Polygons oder -MultiPolygons.

    Benötigt: die GeoJSON-Geometrie eines Baublocks mit Koordinaten in Metern.
        Polygon:      coordinates = [Umriss]                 Umriss = [[x, y], ...]
        MultiPolygon: coordinates = [[Umriss], [Umriss]]     ein Eintrag je Teilfläche

    Formel (Gaußsche Trapezformel) für einen geschlossenen Umriss mit den Eckpunkten (x_i, y_i):
        c_i = x_i * y_(i+1) - x_(i+1) * y_i
        A   = Summe(c_i) / 2
        Cx  = Summe((x_i + x_(i+1)) * c_i) / (6 A)
        Cy  = Summe((y_i + y_(i+1)) * c_i) / (6 A)
    Teilflächen werden mit ihrer Fläche gewichtet.

    Rückgabe: 
    [Ostwert, Nordwert] des Schwerpunkts
    """
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]

    # Rechnen relativ zum ersten Eckpunkt vermeidet Rundungsfehler bei großen UTM-Werten
    x0, y0 = polygons[0][0][0]

    area_sum, cx_sum, cy_sum = 0.0, 0.0, 0.0
    for polygon in polygons:
        outline = np.asarray(polygon[0], dtype=float)
        x, y = outline[:, 0] - x0, outline[:, 1] - y0
        x_next, y_next = np.roll(x, -1), np.roll(y, -1)
        cross = x * y_next - x_next * y
        a = cross.sum() / 2
        if a == 0:
            continue
        cx = ((x + x_next) * cross).sum() / (6 * a)
        cy = ((y + y_next) * cross).sum() / (6 * a)
        area_sum += abs(a)
        cx_sum += abs(a) * cx
        cy_sum += abs(a) * cy
    return [x0 + cx_sum / area_sum, y0 + cy_sum / area_sum]


def load_inhabited_blocks():
    """Liest die Blockdaten und liefert Schwerpunkt und Einwohnerzahl je bewohntem Block.

    Benötigt: bloecke_ew2025_EPSG25833.geojson mit der Einwohnerzahl im Attribut "ew2025".
    Blöcke ohne Einwohner werden übersprungen.

    Rückgabe:
    sp: Schwerpunkte, eine Zeile je Block, Spalten = Ostwert/Nordwert in Metern
    ew: Einwohnerzahl je Block
    """
    with open(BLOCKS) as blocks_file:
        feature_collection = json.load(blocks_file)
    sp, ew = [], []

    for feature in feature_collection["features"]:
        ew_currBlock = feature["properties"].get("ew2025")
        if not ew_currBlock:
            continue
        sp.append(polygon_centroid(feature["geometry"]))
        ew.append(float(ew_currBlock))

    return np.asarray(sp), np.asarray(ew)


def assign_pop_to_stations(stations):
    """Ordnet jeden bewohnten Block der nächstgelegenen Station zu (Thiessen-Zerlegung).

    Benötigt: stations aus read_gtfs() mit Koordinaten in WGS84.
    Die Stationskoordinaten werden nach EPSG:25833 umgerechnet, damit Abstände in Metern
    vorliegen. Blöcke, deren nächste Station weiter als MAX_DIST_M entfernt ist, zählen
    zu keiner Station.

    Rückgabe: Dictionary  Stations-ID -> Einwohnerzahl im Einzugsgebiet
    """
    station_ids = list(stations)

    to25833 = Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True)
    lons = [stations[i]["lon"] for i in station_ids]
    lats = [stations[i]["lat"] for i in station_ids]
    sx, sy = to25833.transform(lons, lats)
    st = np.column_stack([sx, sy])

    blocks_sp, blocks_ew = load_inhabited_blocks()

    # Broadcasting: (Blöcke, 1, 2) - (1, Stationen, 2) ergibt alle Block-Station-Differenzen
    diff = blocks_sp[:, None, :] - st[None, :, :]
    block_station_dist = np.linalg.norm(diff, axis=2)
    nearest_id = block_station_dist.argmin(axis=1)
    dist = block_station_dist[np.arange(len(blocks_sp)), nearest_id]

    pop_per_station = dict.fromkeys(station_ids, 0.0)
    for station_index, block_dist, pop in zip(nearest_id, dist, blocks_ew):
        if block_dist > MAX_DIST_M:
            continue
        pop_per_station[station_ids[station_index]] += pop
    return pop_per_station


def norm(values):
    """Min-Max-Normierung: rechnet eine Liste linear aufs Intervall [0, 1] um.
    kleinster Wert      --> 0
    größter Wert        --> 1
    Alle Werte gleich   --> alle 0.
    Rückgabe: Liste der normierten Werte in derselben Reihenfolge
    """
    lo = min(values)
    hi = max(values)
    normed = []
    for v in values:
        if hi == lo:
            normed.append(0.0)
        else:
            normed.append((v - lo) / (hi - lo))
    return normed


def main():
    """Baut den Graphen, berechnet das Nachfragepotenzial je Kante und schreibt network.json.

    Nachfragepotenzial einer Kante = Mittel aus der normierten Linienanzahl und der
    normierten mittleren Einzugsbevölkerung ihrer beiden Endstationen
    Danach folgen Kontrollausgaben auf der Konsole, die an den Daten nichts ändern.
    """
    stations, edges = read_gtfs()
    print(f"{len(stations)} Stationen, {len(edges)} Kanten")

    pop = assign_pop_to_stations(stations)

    edgekeys = list(edges)
    n_lines = [len(edges[k]) for k in edgekeys]
    pop_mean = [(pop[a] + pop[b]) / 2 for a, b in edgekeys]

    normed_n_lines = norm(n_lines)
    normed_pop_mean = norm(pop_mean)

    demand = []
    for a, b in zip(normed_n_lines, normed_pop_mean):
        demand.append((a + b) / 2)

    stations_out = []
    for s in stations:
        stations_out.append({
            "id": s,
            "name": stations[s]["name"],
            "lat": stations[s]["lat"],
            "lon": stations[s]["lon"],
            "pop": round(pop[s])
        })

    edges_out = []
    for (a, b), nl, pm, ld in zip(edgekeys, n_lines, pop_mean, demand):
        edges_out.append({
            "stationA": a,
            "stationB": b,
            "lines": sorted(edges[(a, b)]),
            "n_lines": nl,
            "pop_mean": round(pm),
            "demand": round(ld, 6)
        })

    data = {
        "max_dist_m": MAX_DIST_M,
        "stations": stations_out,
        "edges": edges_out
    }

    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {OUT.name}")

    short = lambda s: stations[s]["name"].replace(" (Berlin)", "").replace("S+U ", "").replace("U ", "")

    heaviest = max(data["edges"], key=lambda e: e["demand"])
    print(f'  höchstes Nachfragepotenzial {heaviest["demand"]:.3f}  '
          f'{short(heaviest["stationA"])} – {short(heaviest["stationB"])}')

    hist = Counter(e["n_lines"] for e in data["edges"])
    single_line_edges = hist.get(1, 0)
    share_single_line = 100 * single_line_edges / len(data["edges"])
    print(f'  Linien je Strecke {dict(sorted(hist.items()))}  ->  {share_single_line:.0f} % der Strecken '
          f'erhalten aus der Linienkomponente den Wert 0')

    # Keine Linie verzweigt --> Station mit nur einer Linie hat höchstens zwei Nachbarn 
    lines_at = defaultdict(set)
    neighbours = defaultdict(set)
    for (a, b), line_set in edges.items():
        lines_at[a] |= line_set
        lines_at[b] |= line_set
        neighbours[a].add(b)
        neighbours[b].add(a)

    notable = []
    for s in stations:
        if len(lines_at[s]) > 1 or len(neighbours[s]) > 2:
            notable.append(s)
    notable.sort(key=lambda s: (-len(lines_at[s]), -len(neighbours[s]), short(s)))

    print(f'\n  Stationen mit mehr als einer Linie oder mehr als zwei Nachbarn ({len(notable)}):')
    print(f'  {"Station":28s} {"Linien":14s} Nachbarn')
    for s in notable:
        print(f'  {short(s):28s} {", ".join(sorted(lines_at[s])):14s} {len(neighbours[s])}')

if __name__ == "__main__":
    sys.exit(main())
