"""Abruf von Baupublikationen aus dem Amtsblattportal (SECO).

Basel-Landschaft und Wallis publizieren ihr Amtsblatt über amtsblattportal.ch.
Die Liste kommt als JSON, jede Meldung zusätzlich als XML mit allen Feldern.

Unterrubriken (geprüft am 01.11.2026):
  BP-BL05  Baugesuch (BL)
  BA-VS05  Gesuch für Baubewilligung (VS)
  BA-VS10  Öffentliche Planauflage (VS)
  BA-VS20  Plangenehmigung Starkstromanlagen (VS)
  RP-BL10  Öffentliche Planauflage (BL)
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date

BASIS = "https://amtsblattportal.ch/api/v1"
DETAIL_URL = "https://amtsblattportal.ch/#!/search/publications/detail/{id}"
KOPF = {"User-Agent": "baualert/1.0 (+https://github.com)"}


@dataclass
class Gesuch:
    id: str
    kanton: str
    unterrubrik: str
    nummer: str
    datum: str
    titel: str
    projekt: str = ""
    gemeinde: str = ""
    parzelle: str = ""
    frist: str = ""
    bauherrschaft: list[str] = field(default_factory=list)
    koordinaten: tuple[float, float] | None = None   # WGS84 (lat, lon)
    unterlagen: str = ""
    text: str = ""

    @property
    def link(self) -> str:
        return DETAIL_URL.format(id=self.id)


def _get(url: str, accept: str, versuche: int = 3) -> bytes:
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers=dict(KOPF, Accept=accept))
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception:
            if i == versuche - 1:
                raise
            time.sleep(2 ** (i + 1))
    raise RuntimeError("unerreichbar")


def _titel(meta: dict) -> str:
    t = meta.get("title") or {}
    sprache = meta.get("language") or "de"
    return t.get(sprache) or t.get("de") or t.get("fr") or ""


def gemeinde_aus_titel(titel: str) -> str:
    """Titel enden mit «…, Gemeinde», z. B. «Baugesuch - Umbau Wohnhaus, Hemmiken»."""
    return titel.rsplit(",", 1)[1].strip() if "," in titel else ""


def liste(unterrubriken: list[str], von: date, bis: date) -> list[Gesuch]:
    ergebnis: list[Gesuch] = []
    seite, groesse = 0, 200
    while True:
        params = [
            ("publicationStates", "PUBLISHED"),
            ("publicationDate.start", von.isoformat()),
            ("publicationDate.end", bis.isoformat()),
            ("pageRequest.page", str(seite)),
            ("pageRequest.size", str(groesse)),
        ] + [("subRubrics", r) for r in unterrubriken]
        daten = json.loads(_get(f"{BASIS}/publications?{urllib.parse.urlencode(params)}", "application/json"))
        inhalt = daten.get("content", [])
        for e in inhalt:
            m = e.get("meta", e)
            if m.get("subRubric") not in unterrubriken:   # Absicherung, falls der Filter ignoriert wird
                continue
            titel = _titel(m)
            ergebnis.append(Gesuch(
                id=m["id"],
                kanton=",".join(m.get("cantons") or []),
                unterrubrik=m.get("subRubric", ""),
                nummer=m.get("publicationNumber", ""),
                datum=(m.get("publicationDate") or "")[:10],
                titel=titel,
                gemeinde=gemeinde_aus_titel(titel),
            ))
        seite += 1
        if not inhalt or seite * groesse >= daten.get("total", 0):
            break
    return ergebnis


def lv95_zu_wgs84(e: float, n: float) -> tuple[float, float]:
    """Näherungsformel von swisstopo (Genauigkeit ca. 1 m)."""
    y, x = (e - 2_600_000) / 1e6, (n - 1_200_000) / 1e6
    lon = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3
    lat = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3
    return lat * 100 / 36, lon * 100 / 36


def _koord_aus_text(s: str) -> tuple[float, float] | None:
    # Wallis: «2'601'736 1'126'924»; Baselland: Geoview-Link mit map_x=…&map_y=…
    m = re.search(r"map_x=(\d{7}(?:\.\d+)?)&map_y=(\d{7}(?:\.\d+)?)", s)
    if not m:
        m = re.search(r"(2['’ ]?\d{3}['’ ]?\d{3}(?:\.\d+)?)\D{1,5}(1['’ ]?\d{3}['’ ]?\d{3}(?:\.\d+)?)", s)
    if not m:
        return None
    e, n = (float(re.sub(r"['’ ]", "", g)) for g in m.groups())
    if not (2_480_000 < e < 2_840_000 and 1_070_000 < n < 1_300_000):
        return None
    return lv95_zu_wgs84(e, n)


def _texte(el: ET.Element) -> list[str]:
    return [t.text.strip() for t in el.iter()
            if t.text and t.text.strip() and t.tag not in ("key", "valueType", "selectType", "sex")]


def details(g: Gesuch) -> Gesuch:
    wurzel = ET.fromstring(_get(f"{BASIS}/publications/{g.id}/xml", "application/xml"))
    alles: list[str] = []
    for el in wurzel.iter("element"):
        schluessel = (el.findtext("key") or "").lower()
        werte = _texte(el)
        if not werte:
            continue
        bezeichnung, inhalt = werte[0], werte[1:]
        b = bezeichnung.lower()
        if el.find("deadline") is not None and not g.frist:
            g.frist = el.findtext("deadline/date") or ""
        if el.find("valueText") is not None and schluessel == "" and not g.projekt and inhalt:
            g.projekt = inhalt[0]
        elif schluessel == "parcel" and inhalt:
            g.parzelle = inhalt[0]
        elif "projektgemeinde" in b and inhalt:
            g.gemeinde = re.sub(r"^\d{4}\s+", "", inhalt[0])
        elif schluessel in ("buildingcontractor", "applicantparty"):
            namen = [w for w in inhalt if "<br>" not in w and not w.isdigit() and w not in ("true", "false")]
            if namen:
                g.bauherrschaft.append(" ".join(namen[:2]) if len(namen) >= 2 and len(namen[0]) < 25 else namen[0])
        elif schluessel == "externalprojectinformation" and inhalt:
            g.unterlagen = inhalt[0]
        elif "econstruction" in b and el.find("valueTextNeutral") is not None and inhalt:
            g.unterlagen = f"eConstruction-Nr. {inhalt[0]}"
        if g.koordinaten is None and schluessel in ("coordinates", "geoview"):
            g.koordinaten = _koord_aus_text(" ".join(inhalt))
        alles.extend(werte)
    g.text = " ".join(alles)
    return g
