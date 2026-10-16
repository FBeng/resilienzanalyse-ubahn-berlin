"""
Wertet die Ausfallreihenfolgen der gezielten Szenarien aus simulate.py Schritt für Schritt aus
und schreibt das Ergebnis nach ergebnisse/ausfaelle_detail.csv.
"""
import csv
import json
import sys
from pathlib import Path

import networkx as nx

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "ergebnisse"
SCENARIOS = ("betweenness_dyn", "betweenness_stat", "demand")


def format_number(value, decimals=6):
    """Schreibt eine Zahl als Text im Format der übrigen Ergebnis-CSVs.
    Rückgabe: Text mit Dezimalkomma
    """
    text = f"{value:.{decimals}f}"
    text = text.replace(".", ",")
    return text


def read_csv(filename):
    """Liest Ergebnistabelle (filename) aus ergebnisse.
    Rückgabe: Liste von Dictionaries, eine je Zeile, Spaltenname -> Wert
    """
    with open(RESULTS_DIR / filename, encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file, delimiter=";"))
    return rows


def write_csv(filename, header, rows):
    """Schreibt eine Tabelle in den Ordner ergebnisse/, im selben Format wie simulate.py.
    Benötigt:
        filename:  Name der Datei
        header:    Liste der Spaltennamen
        rows:      Liste von Zeilen, jede Zeile eine Liste von Werten
    """
    with open(RESULTS_DIR / filename, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


def build_graph(net):
    """Baut nochmal fix das intakte Netz aus den Daten von network.json.
    Benötigt: net, also network.json.
    Rückgabe: G intakt
    """
    G = nx.Graph()
    for station in net["stations"]:
        G.add_node(station["id"])
    for edge in net["edges"]:
        G.add_edge(edge["stationA"], edge["stationB"])
    return G


def edge_betweenness(G, a, b):
    """Berechnet die Betweenness der Kante a-b im aktuellen Zustand des Netzes.
    Benötigt: G und die Stationen der Kante
    NetworkX speichert die Kante entweder als (a, b) oder als (b, a), beide werden geprüft.
    Rückgabe: Betweenness der kante
    """
    betweenness = nx.edge_betweenness_centrality(G)
    if (a, b) in betweenness:
        value = betweenness[(a, b)]
    else:
        value = betweenness[(b, a)]
    return value


def is_bridge(G, a, b):
    """Prüft, ob die Kante a-b im aktuellen Zustand des Netzes eine Brücke ist.
    Benötigt: G vor dem Ausfall Stationen der Kante
    Rückgabe: True, wenn die Kante eeine Brücke ist
    """
    bridge_set = set()
    for edge in nx.bridges(G):
        bridge_set.add(frozenset(edge))
    return frozenset((a, b)) in bridge_set


def cut_off_stations(G, a, b):
    """Bestimmt, welche Stationen durch den Ausfall einer Brücke a-b abgetrennt wurden.
    Benötigt: G und die Stationen der Brücke
    Abgetrennt ist der kleinere der beiden Teile, bei gleicher Größe der Teil von a.
    Rückgabe: Menge der abgetrennten Stationen
    """
    part_a = nx.node_connected_component(G, a)
    part_b = nx.node_connected_component(G, b)
    if len(part_a) <= len(part_b):
        cut_off = part_a
    else:
        cut_off = part_b
    return cut_off


def replay_scenario(G0, scenario, failure_order, expected_gcc, name_by_id):
    """Spielt die Ausfallreihenfolge eines Szenarios Schritt für Schritt nach.
    Benötigt:
        G0:             das intakte Netz, es wird auf einer Kopie gearbeitet
        scenario:       Name des Szenarios
        failure_order:  Zeilen aus ausfallreihenfolge.csv
        expected_gcc:   (Szenario, Schritt) -> GCC-Anteil aus verlaeufe.csv
        name_by_id:     Stations-ID -> Stationsname

    Für jeden Ausfall wird festgehalten:
        - Betweenness der Kante unmittelbar davor
        - ob die Kante eine Brücke war
        - wie viele und welche Stationen dabei abgetrennt wurden
        - wie groß die größte Komponente danach ist
    Weicht die GCC von verlaeufe.csv ab, bricht das Skript ab.
    Rückgabe: Liste der Ausgabezeilen, eine je Ausfall
    """
    G = G0.copy()
    n = G.number_of_nodes()
    rows = []

    for r in failure_order:
        if r["szenario"] != scenario:
            continue
        a = r["station_a"]
        b = r["station_b"]

        # Betweenness und Brücke werden vor dem Ausfall bestimmt
        betweenness = edge_betweenness(G, a, b)
        bridge = is_bridge(G, a, b)
        G.remove_edge(a, b)

        # Nur eine Brücke trennt Stationen ab
        cut_off = set()
        if bridge == True:
            cut_off = cut_off_stations(G, a, b)

        # Namen der abgetrennten Stationen, alphabetisch
        names = []
        for station in cut_off:
            names.append(name_by_id[station])
        names.sort()

        # Größe der größten Komponente nach dem Ausfall
        sizes = []
        for c in nx.connected_components(G):
            sizes.append(len(c))
        gcc = max(sizes)

        # Kontrolle gegen den GCC-Wert aus simulate.py
        step = int(r["schritt"])
        if abs(gcc / n - expected_gcc[(scenario, step)]) > 1e-6:
            raise SystemExit(f"Abweichung zu verlaeufe.csv: {scenario}, Schritt {step}")

        # Ausgabezeile für diesen Ausfall
        rows.append([scenario, step, r["name_a"], r["name_b"], format_number(betweenness),
                     int(bridge), len(cut_off), gcc, ", ".join(names)])
    return rows


def main():
    """Liest network.json und die Ergebnisse von simulate.py. spielt die gezielten Szenarien
    nach und schreibt ausfaelle_detail.csv.
    """
    # Netz einlesen und intakten Graphen bauen
    net = json.loads((HERE / "network.json").read_text(encoding="utf-8"))
    G0 = build_graph(net)

    # Nachschlagetabelle Stations-ID -> Name
    name_by_id = {}
    for station in net["stations"]:
        name_by_id[station["id"]] = station["name"]

    # Ausfallreihenfolge und GCC-Sollwerte aus den Ergebnissen von simulate.py
    failure_order = read_csv("ausfallreihenfolge.csv")

    expected_gcc = {}
    for row in read_csv("verlaeufe.csv"):
        expected_gcc[(row["szenario"], int(row["schritt"]))] = float(row["gcc"].replace(",", "."))

    # Jedes gezielte Szenario nachspielen
    rows = []
    for scenario in SCENARIOS:
        rows.extend(replay_scenario(G0, scenario, failure_order, expected_gcc, name_by_id))

    # Ergebnis schreiben
    write_csv("ausfaelle_detail.csv",
              ["szenario", "schritt", "name_a", "name_b",
               "betweenness_vor_ausfall", "ist_bruecke_vor_ausfall",
               "abgetrennte_stationen", "gcc_stationen_danach", "abgetrennte_stationen_namen"], rows)

    print(f"{len(rows)} Ausfälle geschrieben, GCC stimmt in allen Schritten mit verlaeufe.csv überein.")


if __name__ == "__main__":
    sys.exit(main())
