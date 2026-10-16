"""
Zeichnet den Graphen aus network.json als Netzkarte in Linienfarben und speichert sie als
ergebnisse/abbildungen/netzkarte.svg und .png.

Strecken mehrerer Linien werden abwechselnd gestrichelt in deren Farben gezeichnet.
Kanten, die keine Brücke sind, liegen auf einem grauen Band. Stationen mit mindestens drei
Streckenabschnitten erscheinen als größerer weißer Punkt.

ERSTELLT MIT CLAUDE CODE
"""
import json
from collections import Counter
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import networkx as nx

HERE = Path(__file__).parent
OUT = HERE / "ergebnisse" / "abbildungen"
COLORS = {"U1": "#7DAD4C", "U2": "#DA421E", "U3": "#16683D", "U4": "#F0D722", "U5": "#7E5330",
          "U6": "#8C6DAB", "U7": "#528DBA", "U8": "#224F86", "U9": "#F3791D"}
DASH = 1.5

net = json.loads((HERE / "network.json").read_text(encoding="utf-8"))
edges = [(e["stationA"], e["stationB"]) for e in net["edges"]]
pos = {s["id"]: (s["lon"], s["lat"]) for s in net["stations"]}
degree = Counter(s for edge in edges for s in edge)
bridges = {frozenset(b) for b in nx.bridges(nx.Graph(edges))}

fig, ax = plt.subplots(figsize=(7, 6))
for e, (a, b) in zip(net["edges"], edges):
    xs, ys = zip(pos[a], pos[b])
    if frozenset((a, b)) not in bridges:
        ax.plot(xs, ys, color="#ccc", lw=7, solid_capstyle="round", zorder=1)
    lines = sorted(e["lines"])
    for i, line in enumerate(lines):
        # Jede Linie zeichnet jeden k-ten Strich, um i Striche versetzt, bei nur einer Linie durchgezogen
        ax.plot(xs, ys, color=COLORS[line], lw=2.4, linestyle=(i * DASH, (DASH, (len(lines) - 1) * DASH)), zorder=2)
for sid, (x, y) in pos.items():
    hub = degree[sid] >= 3
    ax.scatter(x, y, s=16 if hub else 5, c="white" if hub else "#333", edgecolors="#333", lw=0.8, zorder=10)

legend_style = dict(loc="upper center", frameon=False, fontsize=7)
# add_artist hält die erste Legende fest, sonst ersetzt die zweite sie
ax.add_artist(ax.legend(handles=[ax.plot([], [], color=c, lw=3, label=l)[0] for l, c in COLORS.items()],
                        ncol=9, bbox_to_anchor=(0.5, 0), handlelength=1.2, columnspacing=1.0,
                        handletextpad=0.5, **legend_style))
ax.legend(handles=[ax.scatter([], [], s=5, c="#333", edgecolors="#333", lw=0.8, label="Station"),
                   ax.scatter([], [], s=16, c="white", edgecolors="#333", lw=0.8,
                              label="Knotenpunkt (≥ 3 Streckenabschnitte)"),
                   Patch(color="#ccc", label="Kern (keine Brücke)")],
          ncol=3, bbox_to_anchor=(0.5, -0.04), columnspacing=1.5, handletextpad=0.3,
          scatteryoffsets=[0.5], **legend_style)
# Ein Längengrad ist bei 52,5° N nur 0,609-mal so breit wie ein Breitengrad
ax.set_aspect(1 / 0.609)
ax.axis("off")

OUT.mkdir(parents=True, exist_ok=True)
for ext in ("svg", "png"):
    fig.savefig(OUT / f"netzkarte.{ext}", dpi=600, bbox_inches="tight")
print(f"-> {OUT.name}/netzkarte.svg, .png")
