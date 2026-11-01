# Baualert Karte

Karte aller aktuellen Baugesuche in Basel-Landschaft und im Wallis: https://bopsinger.github.io/baualert-karte/

- Daten: Amtsblattportal des SECO, täglich um 04:47 UTC aktualisiert (`.github/workflows/daten.yml`, `bauen.py`).
- Bewusst ohne Namen von Bauherrschaften oder anderen Personen; jeder Eintrag verlinkt auf die amtliche Publikation.
- Eigene Gebiete werden nur im Browser gespeichert (localStorage) und nie übertragen.
- Kartengrundlage: swisstopo.
