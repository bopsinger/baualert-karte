"""Erzeugt daten.json für die Karte: alle Baugesuche BL und VS der letzten Tage.

Bewusst ohne Namen von Bauherrschaften oder anderen Personen; dafür verlinkt
jeder Eintrag auf die amtliche Publikation.

Aufruf:  python bauen.py [--tage 90]
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import urllib.parse
import urllib.request

import quelle

_GEMEINDEN: dict[str, tuple[float, float] | None] = {}


def gemeinde_mitte(name: str) -> tuple[float, float] | None:
    """Mittelpunkt einer Gemeinde über die Suche von geo.admin.ch (Gemeindegrenzen)."""
    if name not in _GEMEINDEN:
        q = urllib.parse.urlencode({"searchText": name, "type": "locations", "origins": "gg25", "sr": "4326", "limit": "1"})
        try:
            with urllib.request.urlopen(f"https://api3.geo.admin.ch/rest/services/api/SearchServer?{q}", timeout=20) as r:
                t = json.loads(r.read()).get("results", [])
            _GEMEINDEN[name] = (t[0]["attrs"]["lat"], t[0]["attrs"]["lon"]) if t else None
        except Exception:
            _GEMEINDEN[name] = None
    return _GEMEINDEN[name]

ZIEL = Path(__file__).resolve().parent / "daten.json"
UNTERRUBRIKEN = ["BP-BL05", "BA-VS05", "BA-VS10"]


def eintrag(g: quelle.Gesuch) -> dict:
    e = {
        "id": g.id, "n": g.nummer, "r": g.unterrubrik, "k": g.kanton, "d": g.datum,
        "f": g.frist, "g": g.gemeinde, "p": g.projekt or g.titel, "z": g.parzelle,
    }
    if g.koordinaten:
        e["lat"], e["lon"] = round(g.koordinaten[0], 6), round(g.koordinaten[1], 6)
    if g.unterlagen:
        e["u"] = g.unterlagen
    return e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tage", type=int, default=90)
    args = ap.parse_args()

    alt = {}
    if ZIEL.exists():
        alt = {e["id"]: e for e in json.loads(ZIEL.read_text(encoding="utf-8"))["gesuche"]}

    heute = date.today()
    liste = quelle.liste(UNTERRUBRIKEN, heute - timedelta(days=args.tage), heute)
    neu = [g for g in liste if g.id not in alt]
    print(f"{len(liste)} Publikationen, {len(neu)} neu zu laden", file=sys.stderr)

    def laden(g):
        try:
            quelle.details(g)
        except Exception as ex:
            print(f"{g.nummer}: {ex}", file=sys.stderr)
        return eintrag(g)

    with ThreadPoolExecutor(max_workers=6) as pool:
        frisch = {e["id"]: e for e in pool.map(laden, neu)}

    aktuell = [frisch.get(g.id) or alt[g.id] for g in liste]
    for e in aktuell:
        if "lat" not in e and e["g"]:
            m = gemeinde_mitte(e["g"])
            if m:
                e["lat"], e["lon"], e["ca"] = round(m[0], 6), round(m[1], 6), 1
    aktuell.sort(key=lambda e: (e["d"], e["n"]), reverse=True)
    ZIEL.write_text(json.dumps({
        "stand": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "tage": args.tage,
        "gesuche": aktuell,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    ohne = sum(1 for e in aktuell if "lat" not in e)
    print(f"{len(aktuell)} Einträge geschrieben, davon {ohne} ohne Koordinaten", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
