"""
Prüft metrics(), run(), static_picker() und find_tipping_point() aus simulate.py an einem
Pfadgraphen A-B-C-D, dessen Werte sich von Hand nachrechnen lassen.

Mittlere Pfadlänge des intakten Pfads über alle 12 geordneten Paare:
Distanz 1: A-B, B-C, C-D  ->  6 geordnete Paare, Beitrag 6
Distanz 2: A-C, B-D       ->  4 geordnete Paare, Beitrag 8
Distanz 3: A-D            ->  2 geordnete Paare, Beitrag 6

apl = 20 / 12
"""
import networkx as nx
from simulate import metrics, run, static_picker, find_tipping_point

G = nx.Graph([("A", "B"), ("B", "C"), ("C", "D")])

# Test 1: intaktes Netz
m = metrics(G, 4)
assert m["gcc"] == 1.0, m
assert m["second"] == 0.0, m
assert m["unreachable"] == 0.0, m
# Vergleich mit Toleranz statt == wegen Rundungsfehler in Kommazahlen  
assert abs(m["apl"] - 20 / 12) < 1e-12

print("Test 1 erfolgreich bestanden: intaktes Netz korrekt ausgewertet.")

# Test 2: Ausfall der Mittelkante B-C, zwei Komponenten mit je 2 Stationen
G1 = G.copy()
G1.remove_edge("B", "C")
m = metrics(G1, 4)
assert m["gcc"] == 0.5, m
assert m["second"] == 0.5, m
assert abs(m["unreachable"] - 8 / 12) < 1e-12, m
assert m["apl"] == 1.0, m

print("Test 2 erfolgreich bestanden: Zustand nach Ausfall korrekt ausgewertet.")

# Test 3: vollständiger Lauf mit fester Ausfallreihenfolge
fixed_order_out = static_picker([("B", "C"), ("A", "B"), ("C", "D")])
actual_order_out, metrics_measures = run(G, fixed_order_out)
assert actual_order_out == [("B", "C"), ("A", "B"), ("C", "D")], actual_order_out
assert len(metrics_measures) == 4
assert metrics_measures[-1]["gcc"] == 0.25, metrics_measures[-1]
assert metrics_measures[1]["gcc"] == 0.5, metrics_measures[1]

print("Test 3 erfolgreich bestanden: vollständiger Simulationslauf korrekt ausgewertet.")

# Test 4: stärkster Abfall im ersten Schritt, erwartet wird der Zustand danach (Index 1)
assert find_tipping_point([0, 1/3, 2/3, 1], [1.0, 0.5, 0.5, 0.25], rising=False)["index"] == 1

print("Test 4 erfolgreich bestanden: Kipppunkt korrekt ausgewertet.")

print("Alle Tests erfolgreich bestanden!")
