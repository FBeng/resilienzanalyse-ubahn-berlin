"""
Simuliert Streckenausfälle im U-Bahn-Netz aus network.json in vier Szenarien (zufällig,
Betweenness dynamisch, Betweenness statisch, Nachfragepotenzial), misst nach jedem Ausfall
die Zielmetriken und schreibt alle Ergebnisse als CSV-Tabellen nach ergebnisse/.
"""
import csv
import json
import random
import sys
import time
from pathlib import Path

import networkx as nx
import numpy as np

HERE = Path(__file__).parent

N_RANDOM_RUNS = 100
SEED = 42
TOP_K = 20
TIMING_REPEATS = 5


def metrics(G, n):
    """Berechnet die vier Zielmetriken für den aktuellen Zustand des Netzes.

    Benötigt:
        G: Graph im aktuellen Zustand
        n: Knotenzahl des intakten Netzes

    Rückgabe: Dictionary mit
        gcc:          Anteil der Stationen in der größten Komponente
        second:       Anteil der Stationen in der zweitgrößten Komponente
        unreachable:  Anteil der geordneten Stationspaare, die nicht mehr verbunden sind
        apl:          mittlere Länge der kürzesten Wege zwischen verbundenen Paaren, in Kanten
    """
    components = nx.connected_components(G)
    sizes = []
    for c in components:
        sizes.append(len(c))
    sizes.sort(reverse=True)

    gcc = sizes[0] / n

    if len(sizes) > 1:
        second = (sizes[1]) / n
    else:
        second = 0

    # Eine Komponente mit s Stationen enthält s*(s-1) geordnete verbundene Paare
    connected_pairs = 0
    for s in sizes:
        connected_pairs += s * (s - 1)
    total_pairs = n * (n - 1)

    unreachable = (total_pairs - connected_pairs) / total_pairs

    dist_sum = 0
    distanceTo = nx.all_pairs_shortest_path_length(G)
    for start, distances in distanceTo:
        for ziel, d in distances.items():
            dist_sum += d

    if connected_pairs != 0:
        apl = dist_sum / connected_pairs
    else:
        apl = 0.0

    return {
        "gcc": gcc,
        "second": second,
        "unreachable": unreachable,
        "apl": apl
    }


def run(G0, pick):
    """Führt einen vollständigen Ausfallverlauf durch, bis das Netz keine Kante mehr hat.

    Benötigt:
        G0:    das intakte Netz, es wird auf einer Kopie gearbeitet
        pick:  Funktion, die zu einem Graphen die nächste Ausfallkante liefert

    Nach jedem Ausfall werden die Metriken gemessen, der Startzustand ebenfalls.

    Rückgabe:
    failure_order:    Liste der Kanten in der Reihenfolge ihres Ausfalls
    metrics_history:  Liste der Metrik-Dictionaries, ein Eintrag mehr als failure_order
    """
    G = G0.copy()
    n = G0.number_of_nodes()
    failure_order = []
    metrics_history = [metrics(G, n)]

    while G.number_of_edges() != 0:
        next_failure_edge = pick(G)
        G.remove_edge(*next_failure_edge)
        failure_order.append(next_failure_edge)
        metrics_history.append(metrics(G, n))

    return failure_order, metrics_history


def static_picker(ranking):
    """Baut eine pick-Funktion für run() aus einer festen Ausfallreihenfolge.

    Benötigt: ranking, die vorab festgelegte Reihenfolge der Kanten.
    Die erzeugte Funktion merkt sich ihre Position in ranking und liefert bei jedem Aufruf
    die nächste Kante, die im Graphen noch vorhanden ist.

    Rückgabe: 
    pick-Funktion
    """
    it = iter(ranking)

    def pick(G):
        for e in it:
            if G.has_edge(*e) == True:
                return e

    return pick


def dynamic_picker(G):
    """pick-Funktion für das dynamische Betweenness-Szenario.

    Benötigt: den Graphen im aktuellen Zustand.
    Berechnet die Kanten-Betweenness bei jedem Aufruf neu, weil sich die kürzesten Wege
    nach jedem Ausfall verlagern.

    Rückgabe: Kante mit höchster Betweenness
    """
    betweenness = nx.edge_betweenness_centrality(G)
    most_critical_edge = max(betweenness, key=betweenness.get)
    return most_critical_edge


def find_tipping_point(q, values, rising):
    """Bestimmt den Kipppunkt, also den Ausfallschritt mit der stärksten Änderung einer Kurve.

    Benötigt:
        q:       Ausfallanteil je Schritt (0 bis 1)
        values:  Werte der Kurve je Schritt
        rising:  True, wenn der stärkste Anstieg gesucht ist, False für den stärksten Abfall

    Verwendet wird die ungeglättete Differenz zwischen zwei aufeinanderfolgenden Schritten.

    Rückgabe: 
    Dictionary mit
        q:      Ausfallanteil am Kipppunkt
        index:  Position des Kipppunkts in q und values
        value:  Kurvenwert am Kipppunkt
        delta:  Höhe des Sprungs
    """
    d = np.diff(np.asarray(values, float))
    if rising == True:
        jump_position = np.argmax(d)
    else:
        jump_position = np.argmin(d)
    # d[k] ist der Sprung von k nach k+1, gesucht ist der Zustand nach dem Sprung
    i = int(jump_position) + 1

    return {
        "q": float(q[i]),
        "index": i,
        "value": float(values[i]),
        "delta": float(d[i - 1])
        }


def second_max(q, values):
    """Findet das Maximum der zweitgrößten Komponente (Perkolationsübergang).

    Benötigt:
        q:       Ausfallanteil je Schritt (0 bis 1)
        values:  Anteil der zweitgrößten Komponente je Schritt

    Rückgabe: Dictionary mit q, index und value am Maximum
    """
    i = int(np.argmax(values))

    return {
        "q": float(q[i]),
        "index": i,
        "value": float(values[i])
        }


def r_index(gcc_series):
    """Robustheitsmaß R: Mittelwert der GCC-Kurve über den gesamten Verlauf.

    Benötigt: die GCC-Werte je Schritt.
    Je kleiner R, desto schneller zerfällt das Netz im Verlauf.

    Rückgabe: R als Zahl
    """
    r = float(np.mean(gcc_series))

    return r


def path_lead(q, apl, gcc_tipping_q):
    """Prüft, ob die mittlere Pfadlänge steigt, bevor die GCC zerfällt.

    Benötigt:
        q:              Ausfallanteil je Schritt (0 bis 1)
        apl:            mittlere Pfadlänge je Schritt
        gcc_tipping_q:  Ausfallanteil am GCC-Kipppunkt

    Solange das Netz zusammenhängt, erzwingen Ausfälle Umwege und die Pfadlänge steigt.
    Zerfällt das Netz, fallen lange Verbindungen aus der Berechnung und die Kurve sinkt.
    Das Maximum markiert den Übergang zwischen beiden Effekten.

    Rückgabe: 
    Dictionary mit
        apl_start:  Pfadlänge im intakten Netz
        apl_max:    höchste erreichte Pfadlänge
        q_max:      Ausfallanteil beim Maximum
        rise_pct:   prozentualer Anstieg bis zum Maximum
        lead:       Abstand vom Maximum zum GCC-Kipppunkt, positiv heißt Maximum liegt davor
    """
    apl_array = np.asarray(apl, float)
    i = int(np.argmax(apl_array))

    rise_pct = 100 * (apl_array[i] / apl_array[0] - 1)

    lead = gcc_tipping_q - q[i]

    return {
        "apl_start": float(apl_array[0]),
        "apl_max": float(apl_array[i]),
        "q_max": float(q[i]),
        "rise_pct": float(rise_pct),
        "lead": float(lead)
        }


def complexity_report(G, timings):
    """Misst die Laufzeit der beiden aufwendigsten Einzelberechnungen auf dem intakten Netz.

    Benötigt:
        G:        das intakte Netz
        timings:  Dictionary mit den gemessenen Gesamtlaufzeiten der vier Szenarien

    Gemessen werden eine Kanten-Betweenness-Berechnung und ein Aufruf von metrics(),
    jeweils TIMING_REPEATS-mal, berichtet wird der Median.

    Rückgabe: Dictionary mit Knotenzahl V, Kantenzahl E, den beiden Einzelzeiten und timings
    """
    V, E = G.number_of_nodes(), G.number_of_edges()

    def median_time(func, *args):
        """Führt func(*args) TIMING_REPEATS-mal aus und gibt den Median der Laufzeiten zurück."""
        times = []
        for _ in range(TIMING_REPEATS):
            start = time.perf_counter()
            func(*args)
            times.append(time.perf_counter() - start)
        return float(np.median(times))

    t_ebc = median_time(nx.edge_betweenness_centrality, G)
    t_met = median_time(metrics, G, V)

    return {
        "V": V,
        "E": E,
        "t_betweenness": t_ebc,
        "t_metrics": t_met,
        "timings": timings,
        }


def topology(G):
    """Berechnet Kennzahlen zur Struktur des intakten Netzes.

    Benötigt: intaktes G

    Rückgabe: Dictionary mit
        n, m:              Knoten- und Kantenzahl
        mean_degree:       mittlerer Knotengrad <k>
        degree_hist:       Knotengrad -> Anzahl der Stationen mit diesem Grad
        heterogeneity:     <k^2> / <k>^2, Ungleichheit der Gradverteilung
        bridges:           Anzahl der Kanten, deren Ausfall das Netz sofort trennt
        cycles:            Zahl der unabhängigen Kreise, m - n + 1
        q_c_random_graph:  Molloy-Reed-Schwelle q_c = 1 - <k>/(<k^2> - <k>), bei der ein
                           Zufallsnetz mit derselben Gradverteilung zerfallen würde
    """
    grade = []
    for nodes, deg in G.degree():
        grade.append(deg)

    k = np.array(grade, float)
    n = G.number_of_nodes()
    m = G.number_of_edges()

    k2 = (k ** 2).mean()

    degree_hist = {}
    for deg_value in sorted(set(k)):
        counter = (k == deg_value).sum()
        degree_hist[int(deg_value)] = int(counter)

    return {
        "n": n,
        "m": m,
        "mean_degree": float(k.mean()),
        "degree_hist": degree_hist,
        "heterogeneity": float(k2 / k.mean() ** 2),
        "bridges": len(list(nx.bridges(G))),
        "cycles": m - n + 1,
        "q_c_random_graph": float(1 - k.mean() / (k2 - k.mean())),
           }


RESULTS_DIR = HERE / "ergebnisse"

# True: CSV für deutsches Excel
# False: internationales CSV

CSV_GERMAN_FORMAT = True

WRITTEN = []


def format_number(value, decimals=6):
    """Schreibt eine Zahl als Text im eingestellten CSV-Format.

    Benötigt: die Zahl und die Anzahl der Nachkommastellen

    Rückgabe: Text, z. B. "0,179892" (deutsch) oder "0.179892" (international)
    """
    text = f"{value:.{decimals}f}"
    if CSV_GERMAN_FORMAT:
        text = text.replace(".", ",")
    return text


def write_csv(filename, header, rows):
    """Schreibt eine Tabelle in den Ordner ergebnisse und vermerkt sie in WRITTEN.

    Benötigt:
    filename:  Name der Datei
    header:    Liste der Spaltennamen
    rows:      Liste von Zeilen, jede Zeile eine Liste von Werten
    """
    RESULTS_DIR.mkdir(exist_ok=True)

    if CSV_GERMAN_FORMAT:
        delimiter = ";"
        encoding = "utf-8-sig"
    else:
        delimiter = ","
        encoding = "utf-8"

    # newline="" verhindert unter Windows leere Zwischenzeilen
    with open(RESULTS_DIR / filename, "w", newline="", encoding=encoding) as file:
        writer = csv.writer(file, delimiter=delimiter)
        writer.writerow(header)
        writer.writerows(rows)
    WRITTEN.append((filename, len(rows)))


def rank_list(values):
    """Vergibt Rangplätze, 1 = größter Wert. Gleiche Werte teilen sich den Rang (1, 2, 2, 4).

    Benötigt: eine Liste von Zahlen, eine je Kante.

    Rückgabe: Liste gleicher Länge, an Position i der Rang von values[i]
    """
    def value_at(position):
        return values[position]

    sorted_positions = sorted(range(len(values)), key=value_at, reverse=True)

    ranks = [0] * len(values)
    for place, position in enumerate(sorted_positions):
        vorherige = sorted_positions[place - 1]
        if place > 0 and values[position] == values[vorherige]:
            ranks[position] = ranks[vorherige]
        else:
            ranks[position] = place + 1
    return ranks


def export_csv(net, edge_order, q, scen, overlap, betweenness_per_edge, demand, topo, cx, G):
    """Schreibt alle Ergebnistabellen als CSV nach ergebnisse/.

    Benötigt die bereits berechneten Ergebnisse aus main(): Netzdaten, Kantenreihenfolge,
    Ausfallanteile, Szenarioergebnisse, Top-k-Überschneidung, Betweenness und
    Nachfragepotenzial je Kante, Netzkennzahlen, Laufzeiten und den intakten Graphen.

    Geschrieben werden stationen.csv, strecken.csv, verlaeufe.csv, verlauf_<metrik>.csv,
    ausfallreihenfolge.csv, kennzahlen.csv, lauf.csv und laufzeiten.csv.
    """
    WRITTEN.clear()

    # Nachschlagetabellen Stations-ID -> Datensatz und Kurzname
    station_by_id = {}
    short_name_by_id = {}
    for station in net["stations"]:
        station_by_id[station["id"]] = station
        short_name = station["name"].replace(" (Berlin)", "").replace("S+U ", "").replace("U ", "")
        short_name_by_id[station["id"]] = short_name

    # stationen.csv
    rows = []
    for station in net["stations"]:
        rows.append([station["id"], station["name"], format_number(station["lat"]),
                     format_number(station["lon"]), station["pop"]])
    write_csv("stationen.csv", ["id", "name", "lat", "lon", "einwohner"], rows)

    # strecken.csv: eine Zeile je Kante mit Rängen, Brücke und Top-k-Markierung
    betweenness_ranks = rank_list(betweenness_per_edge)
    demand_ranks = rank_list(demand)

    bridges = set()
    for a, b in nx.bridges(G):
        bridges.add(tuple(sorted((a, b))))

    in_both = set(overlap["in_both_by_betweenness"])

    rows = []
    for i, edge in enumerate(net["edges"]):
        a = station_by_id[edge["stationA"]]
        b = station_by_id[edge["stationB"]]

        if tuple(sorted((edge["stationA"], edge["stationB"]))) in bridges:
            is_bridge = 1
        else:
            is_bridge = 0

        if i in in_both:
            in_both_top20 = 1
        else:
            in_both_top20 = 0

        rows.append([i, edge["stationA"], edge["stationB"],
                     short_name_by_id[edge["stationA"]], short_name_by_id[edge["stationB"]],
                     format_number(a["lat"]), format_number(a["lon"]),
                     format_number(b["lat"]), format_number(b["lon"]),
                     ",".join(edge["lines"]), edge["n_lines"], edge["pop_mean"],
                     format_number(betweenness_per_edge[i]), betweenness_ranks[i],
                     format_number(demand[i]), demand_ranks[i],
                     in_both_top20, is_bridge])
    write_csv("strecken.csv",
              ["position", "station_a", "station_b", "name_a", "name_b",
               "lat_a", "lon_a", "lat_b", "lon_b", "linien", "n_linien", "pop_mean",
               "betweenness", "rang_betweenness", "nachfrage", "rang_nachfrage",
               "in_beiden_top_k", "ist_bruecke"], rows)

    # verlaeufe.csv: alle Szenarien und Metriken im Langformat
    rows = []
    for name, sc in scen.items():
        for step in range(len(q)):
            row = [name, step, format_number(q[step]),
                   format_number(sc["gcc"][step]), format_number(sc["second"][step]),
                   format_number(sc["unreachable"][step]), format_number(sc["apl"][step])]
            if "gcc_lo" in sc:
                row.append(format_number(sc["gcc_lo"][step]))
                row.append(format_number(sc["gcc_hi"][step]))
            else:
                row.append("")
                row.append("")
            rows.append(row)
    write_csv("verlaeufe.csv",
              ["szenario", "schritt", "q", "gcc", "second", "unreachable", "apl",
               "gcc_perzentil_10", "gcc_perzentil_90"], rows)

    # verlauf_<metrik>.csv: je Metrik eine Datei, eine Spalte je Szenario
    for metric in ("gcc", "second", "unreachable", "apl"):
        header = ["q"]
        for name in scen:
            header.append(name)
        if metric == "gcc":
            header.append("zufall_perzentil_10")
            header.append("zufall_perzentil_90")

        rows = []
        for step in range(len(q)):
            row = [format_number(q[step])]
            for name in scen:
                row.append(format_number(scen[name][metric][step]))
            if metric == "gcc":
                row.append(format_number(scen["random"]["gcc_lo"][step]))
                row.append(format_number(scen["random"]["gcc_hi"][step]))
            rows.append(row)
        write_csv(f"verlauf_{metric}.csv", header, rows)

    # ausfallreihenfolge.csv
    rows = []
    for name, sc in scen.items():
        for step, position in enumerate(sc["order"], start=1):
            station_a, station_b = edge_order[position]
            rows.append([name, step, position, station_a, station_b,
                         short_name_by_id[station_a], short_name_by_id[station_b]])
    write_csv("ausfallreihenfolge.csv",
              ["szenario", "schritt", "position", "station_a", "station_b",
               "name_a", "name_b"], rows)

    # kennzahlen.csv: Kipppunkte, R-Index und Überschneidung
    rows = []
    for name, sc in scen.items():
        for measure, values in sc["tipping"].items():
            for key_name, value in values.items():
                if key_name == "index":
                    continue
                rows.append([name, measure, key_name, format_number(value)])

        rows.append([name, "r_index", "median", format_number(sc["r_index"])])
        if "r_lo" in sc:
            rows.append([name, "r_index", "perzentil_10", format_number(sc["r_lo"])])
            rows.append([name, "r_index", "perzentil_90", format_number(sc["r_hi"])])
        if "r_percentile_in_random" in sc:
            rows.append([name, "r_index", "perzentil_in_zufall",
                         format_number(sc["r_percentile_in_random"], 1)])

    rows.append(["alle", "overlap", "top_k", TOP_K])
    rows.append(["alle", "overlap", "in_beiden_top_k", len(overlap["in_both_by_betweenness"])])
    write_csv("kennzahlen.csv", ["szenario", "groesse", "kennzahl", "wert"], rows)

    # lauf.csv: Parameter und Netzkennzahlen
    rows = [
        ["seed", SEED],
        ["timing_repeats", TIMING_REPEATS],
        ["n_random_runs", N_RANDOM_RUNS],
        ["max_dist_m", net["max_dist_m"]],
        ["knoten", topo["n"]],
        ["kanten", topo["m"]],
        ["mittlerer_grad", format_number(topo["mean_degree"], 3)],
        ["heterogenitaet", format_number(topo["heterogeneity"], 3)],
        ["bruecken", topo["bridges"]],
        ["bruecken_anteil_prozent", format_number(100 * topo["bridges"] / topo["m"], 1)],
        ["unabhaengige_maschen", topo["cycles"]],
        ["q_c_molloy_reed", format_number(topo["q_c_random_graph"], 3)],
    ]
    for degree, count in sorted(topo["degree_hist"].items()):
        rows.append([f"stationen_mit_grad_{degree}", count])
    write_csv("lauf.csv", ["kennzahl", "wert"], rows)

    # laufzeiten.csv
    rows = [["einzelschritt", "kanten_betweenness", format_number(1000 * cx["t_betweenness"], 1)],
            ["einzelschritt", "metrics", format_number(1000 * cx["t_metrics"], 1)]]
    for name, seconds in cx["timings"].items():
        rows.append(["szenario", name, format_number(1000 * seconds, 1)])
    write_csv("laufzeiten.csv", ["bereich", "kennzahl", "millisekunden"], rows)

    total_rows = sum(n for _, n in WRITTEN)
    print(f"  {len(WRITTEN)} Tabellen, {total_rows} Zeilen -> ergebnisse/")


def main():
    """Liest network.json, simuliert alle vier Szenarien, wertet sie aus und schreibt die CSV-Tabellen.

    Ablauf:
        1. Graph aufbauen, Betweenness und Nachfragepotenzial je Kante bereitstellen
        2. Zufallsszenario N_RANDOM_RUNS-mal laufen lassen und über die Läufe zusammenfassen
           (Median + Perzentile der Kurven, Kipppunkte und R-Index)
        3. Die drei gezielten Szenarien je einmal laufen lassen und auswerten
        4. Überschneidung der Top-k-Kanten nach Betweenness und Nachfragepotenzial bestimmen
        5. Laufzeiten messen, Zusammenfassung ausgeben, CSV-Tabellen schreiben

    Alle Ergebnisse je Szenario sammeln sich in scen, mit den Schlüsseln order, gcc, second,
    unreachable, apl, tipping und r_index, beim Zufallsszenario zusätzlich die Perzentile.
    """
    # Netz einlesen, Kantenreihenfolge und Positionsindex anlegen
    net = json.loads((HERE / "network.json").read_text(encoding="utf-8"))
    edges = net["edges"]

    edge_order = []
    for e in edges:
        edge_order.append((e["stationA"], e["stationB"]))

    index = {}
    for i, k in enumerate(edge_order):
        index[k] = i

    def idx(order):
        """Wandelt eine Liste von Kanten in ihre Positionen in edge_order um.

        NetworkX liefert Kanten teils in umgekehrter Knotenreihenfolge, dann wird das
        gedrehte Tupel nachgeschlagen.
        """
        positions = []
        for e in order:
            if e in index:
                edge = e
            else:
                edge = (e[1], e[0])
            positions.append(index[edge])
        return positions

    # Knoten zuerst, damit Stationen ohne verbleibende Kante im Graphen bleiben
    G = nx.Graph()
    station_ids = []
    for station in net["stations"]:
        station_ids.append(station["id"])

    G.add_nodes_from(station_ids)
    G.add_edges_from(edge_order)

    # Ausfallanteil q je Schritt, von 0 bis 1
    number_e = G.number_of_edges()

    q = []
    for i in range(number_e + 1):
        q.append(i / number_e)

    # Betweenness und Nachfragepotenzial je Kante in der Reihenfolge von edge_order
    ebc = nx.edge_betweenness_centrality(G)

    betweenness_per_edge = []
    for k in edge_order:
        if k in ebc:
            value = ebc[k]
        elif (k[1], k[0]) in ebc:
            value = ebc[(k[1], k[0])]
        else:
            raise KeyError(f"Keine Kanten-Betweenness für {k}")

        betweenness_per_edge.append(value)

    demand = []
    for e in edges:
        demand.append(e["demand"])

    # Netzkennzahlen des intakten Netzes
    topo = topology(G)
    print(f'Netz: {topo["n"]} Knoten, {topo["m"]} Kanten, '
          f'{topo["bridges"]} Brücken ({100*topo["bridges"]/topo["m"]:.0f} %), '
          f'<k>={topo["mean_degree"]:.2f}')

    # Auswertung eines Laufs, für gcc wird der stärkste Abfall gesucht, sonst der stärkste Anstieg
    RISING = {"gcc": False, "unreachable": True, "apl": True}

    def evaluate(metrics_history):
        """Wertet einen einzelnen Lauf aus.

        Benötigt: metrics_history eines Laufs aus run()

        Rückgabe:
            tipping_points:  Kipppunkte für gcc, unreachable und apl, dazu second_max und path_lead
            R:               R-Index des Laufs
        """
        tipping_points = {}
        for metric in RISING:
            metric_values = []
            for x in metrics_history:
                metric_values.append(x[metric])
            tipping_points[metric] = find_tipping_point(q, metric_values, RISING[metric])

        second_values = []
        for x in metrics_history:
            second_values.append(x["second"])
        tipping_points["second_max"] = second_max(q, second_values)

        apl_values = []
        for x in metrics_history:
            apl_values.append(x["apl"])
        tipping_points["path_lead"] = path_lead(q, apl_values, tipping_points["gcc"]["q"])

        gcc_values = []
        for x in metrics_history:
            gcc_values.append(x["gcc"])

        return tipping_points, r_index(gcc_values)

    # Zufallsszenario: N_RANDOM_RUNS Läufe mit je neu gemischter Ausfallreihenfolge
    rng = random.Random(SEED)
    runs = []
    run_tips = []
    run_R = []
    timings = {}

    _t_random = time.perf_counter()
    for r in range(N_RANDOM_RUNS):
        shuffled = edge_order[:]
        rng.shuffle(shuffled)
        order, metrics_history = run(G, static_picker(shuffled))
        runs.append(metrics_history)

        # Kipppunkt je Lauf statt auf der gemittelten Kurve, weil Mitteln die Sprünge glättet
        tipping_points, R = evaluate(metrics_history)
        run_tips.append(tipping_points)
        run_R.append(R)

        if r == 0:
            first_order = order

        print(f"\r  Zufallslauf {r + 1}/{N_RANDOM_RUNS}", end="", flush=True)
    print()
    timings["random"] = time.perf_counter() - _t_random

    # Zufallsläufe zusammenfassen: Median und 10./90. Perzentil der Kurven
    scen = {}
    scen["random"] = {"order": idx(first_order)}

    METRICS = ("gcc", "second", "unreachable", "apl")

    for m in METRICS:
        tabel = []
        for metrics_history in runs:
            row = []
            for x in metrics_history:
                row.append(x[m])
            tabel.append(row)

        # Zeilen = Läufe, Spalten = Ausfallschritte, axis=0 fasst je Schritt über alle Läufe zusammen
        tabel_np = np.array(tabel)
        median_curve = np.median(tabel_np, axis=0)
        scen["random"][m] = median_curve.tolist()

        curve_lo = np.percentile(tabel_np, 10, axis=0)
        curve_hi = np.percentile(tabel_np, 90, axis=0)
        scen["random"][m + "_lo"] = curve_lo.tolist()
        scen["random"][m + "_hi"] = curve_hi.tolist()

    # Kipppunkte, Pfadlängen-Vorlauf und R-Index der Zufallsläufe zusammenfassen
    scen["random"]["tipping"] = {}
    for k in ("gcc", "unreachable", "apl", "second_max"):
        qs = []
        for tipping_points in run_tips:
            qs.append(tipping_points[k]["q"])

        summary = {
            "q": float(np.median(qs)),
            "q_lo": float(np.percentile(qs, 10)),
            "q_hi": float(np.percentile(qs, 90)),
            "index": int(round(np.median(qs) * number_e)),
        }
        if k != "second_max":
            ds = []
            for tipping_points in run_tips:
                ds.append(tipping_points[k]["delta"])
            summary["delta"] = float(np.median(ds))
        scen["random"]["tipping"][k] = summary

    path_lead_summary = {}
    for k in ("apl_start", "apl_max", "q_max", "rise_pct", "lead"):
        values = []
        for tipping_points in run_tips:
            values.append(tipping_points["path_lead"][k])
        path_lead_summary[k] = float(np.median(values))
    scen["random"]["tipping"]["path_lead"] = path_lead_summary

    rises = []
    for tipping_points in run_tips:
        rises.append(tipping_points["path_lead"]["rise_pct"])

    scen["random"]["tipping"]["path_lead"]["rise_lo"] = float(np.percentile(rises, 10))
    scen["random"]["tipping"]["path_lead"]["rise_hi"] = float(np.percentile(rises, 90))

    scen["random"]["r_index"] = float(np.median(run_R))
    scen["random"]["r_lo"] = float(np.percentile(run_R, 10))
    scen["random"]["r_hi"] = float(np.percentile(run_R, 90))

    # Feste Ausfallreihenfolgen nach Betweenness und Nachfragepotenzial des intakten Netzes
    def betweenness_of(position):
        return betweenness_per_edge[position]

    def demand_of(position):
        return demand[position]

    # sort() ist stabil: Kanten mit gleichem Wert behalten ihre Reihenfolge aus network.json,
    # dadurch ist die Ausfallreihenfolge bei Gleichstand eindeutig
    ebc_positions = list(range(len(edge_order)))
    ebc_positions.sort(key=betweenness_of, reverse=True)
    static_ebc = []
    for i in ebc_positions:
        static_ebc.append(edge_order[i])

    demand_positions = list(range(len(edge_order)))
    demand_positions.sort(key=demand_of, reverse=True)
    static_demand = []
    for i in demand_positions:
        static_demand.append(edge_order[i])

    # Die drei gezielten Szenarien, je ein Lauf
    for name, pick in (("betweenness_dyn", dynamic_picker),
                       ("betweenness_stat", static_picker(static_ebc)),
                       ("demand", static_picker(static_demand))):
        _t = time.perf_counter()
        order, metrics_history = run(G, pick)
        timings[name] = time.perf_counter() - _t
        tipping_points, R = evaluate(metrics_history)

        metric_curves = {}
        for m in METRICS:
            curve = []
            for x in metrics_history:
                curve.append(x[m])
            metric_curves[m] = curve

        scen[name] = {
            "order": idx(order),
            "tipping": tipping_points,
            "r_index": R
                }

        for m in metric_curves:
            scen[name][m] = metric_curves[m]

        # np.mean über Wahr/Falsch-Werte ergibt den Anteil der Zufallsläufe mit kleinerem R
        run_R_array = np.array(run_R)
        smaller_than_r = run_R_array < R
        fraction_smaller = np.mean(smaller_than_r)
        r_percentile_in_random = float(100 * fraction_smaller)

        scen[name]["r_percentile_in_random"] = r_percentile_in_random

    # Überschneidung der Top-k-Kanten nach Betweenness und nach Nachfragepotenzial
    def top(value_list, k=TOP_K):
        """Liefert die Positionen der k größten Werte in value_list als Menge."""
        desc_positions = np.argsort(value_list)[::-1]
        top_k = desc_positions[:k]

        result = set()
        for i in top_k:
            result.add(i)
        return result

    top_betweenness_set = top(betweenness_per_edge)
    top_demand_set = top(demand)

    both_set = top_betweenness_set & top_demand_set

    betweenness_value_index_pairs = []
    for i in both_set:
        betweenness_value_index_pairs.append((betweenness_per_edge[i], i))
    betweenness_value_index_pairs_sorted = sorted(betweenness_value_index_pairs, reverse=True)

    both_by_betweenness = []
    for value, i in betweenness_value_index_pairs_sorted:
        both_by_betweenness.append(i)

    demand_value_index_pairs = []
    for i in both_set:
        demand_value_index_pairs.append((demand[i], i))
    demand_value_index_pairs_sorted = sorted(demand_value_index_pairs, reverse=True)

    both_by_demand = []
    for value, i in demand_value_index_pairs_sorted:
        both_by_demand.append(i)

    top_betweenness = []
    for i in np.argsort(betweenness_per_edge)[::-1][:TOP_K]:
        top_betweenness.append(int(i))

    top_demand = []
    for i in np.argsort(demand)[::-1][:TOP_K]:
        top_demand.append(int(i))

    in_both_by_betweenness = []
    for i in both_by_betweenness:
        in_both_by_betweenness.append(int(i))

    in_both_by_demand = []
    for i in both_by_demand:
        in_both_by_demand.append(int(i))

    overlap = {"top_betweenness": top_betweenness,
             "top_demand": top_demand,
             "in_both_by_betweenness": in_both_by_betweenness,
             "in_both_by_demand": in_both_by_demand}

    # Laufzeiten messen, Zusammenfassung ausgeben, Tabellen schreiben
    cx = complexity_report(G, timings)

    print(f'\n  {"Szenario":17s} {"R":>6s} {"Perzentil":>10s} {"GCC-Kipppunkt":>16s} {"Umweg":>7s}')
    for name in ("random", "betweenness_dyn", "betweenness_stat", "demand"):
        sc = scen[name]
        tip = sc["tipping"]["gcc"]
        umweg = sc["tipping"]["path_lead"]["rise_pct"]

        if name == "random":
            perzentil = f'{sc["r_lo"]:.3f}-{sc["r_hi"]:.3f}'
            hinweis = ""
        else:
            pc = sc["r_percentile_in_random"]
            perzentil = f"{pc:.0f}."
            hinweis = "   wie Zufall" if 10 <= pc <= 90 else ""

        print(f'  {name:17s} {sc["r_index"]:6.3f} {perzentil:>10s} '
              f'{tip["q"]:8.3f} ({tip["delta"]:+.3f}) {umweg:6.1f}%{hinweis}')

    print(f'\n  Überschneidung: {len(overlap["in_both_by_betweenness"])}/{TOP_K} Kanten in beiden Top-{TOP_K}')
    gesamtzeit = sum(cx["timings"].values())
    print(f'  Laufzeit: {gesamtzeit:.1f} s')

    export_csv(net, edge_order, q, scen, overlap, betweenness_per_edge, demand, topo, cx, G)


if __name__ == "__main__":
    sys.exit(main())
