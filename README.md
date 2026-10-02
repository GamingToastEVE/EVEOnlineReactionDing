# EVE Online Reaction Ding

Profit-Rechner für alle **Reactions** in EVE Online – als Kommandozeilen-Tool und als
Web-Oberfläche im Browser. Die Zahlen kommen vom
[EVE Online Reactions Calculator](https://reactions.coalition.space) (Oxed G), primär über
dessen [API](https://reactions.coalition.space/api).

Abgedeckt sind alle 177 Reactions in 15 Gruppen:

| Calculator | Gruppen |
|---|---|
| Hybrid Reactions | Hybrid Reactions |
| Composite Reactions | Simple Reactions · Complex Reactions · Complex Chain Reactions · Unrefined Reactions (not reprocessed) · Unrefined Reactions (55% Efficiency) · Unrefined Mineral Reactions (no reprocessing) · Unrefined Mineral Reactions (MAX Refine 90.63%) |
| Biochemical Reactions | Synth Booster Reactions · Standard Booster Reactions · Improved Booster Reactions · Improved Booster Chain Reactions · Strong Booster Reactions · Strong Booster Chain Reactions · Molecular-Forging Reactions |

Benötigt nur **Python 3.9+**, keine weiteren Pakete. Für Windows gibt es alternativ eine fertige
**`EVEReactionDing.exe`** (siehe unten), die ohne Python läuft.

## Windows-Programm (.exe)

`EVEReactionDing.exe` **doppelklicken**: Ein Konsolenfenster startet den lokalen Server, die
Oberfläche öffnet sich im Browser (<http://127.0.0.1:8765/>). Fenster schließen = Programm beenden.
Die Einstellungen landen als `settings.json` neben der .exe.

Alle Befehle gehen auch in der Eingabeaufforderung, z.B. `EVEReactionDing.exe calc --sort profit --top 10`
oder `EVEReactionDing.exe check-sheet Operation_MoonShine_GT.xlsx --fixes`.

Die .exe ist nicht signiert. Windows SmartScreen meldet deshalb beim ersten Start „Der Computer wurde
durch Windows geschützt“. Mit **Weitere Informationen → Trotzdem ausführen** startet sie.

Selbst bauen (unter Windows): `pip install pyinstaller openpyxl` und `python packaging/build_exe.py`.
Der GitHub-Workflow `.github/workflows/build-exe.yml` baut sie bei jeder Änderung auf einem
Windows-Server und hängt sie als Artefakt an.

## Web-Oberfläche

```bash
python -m reactionding            # oder: python -m reactionding serve --open
```

Öffnet <http://127.0.0.1:8765/> im Browser. Dort gibt es:

- alle Settings des Calculators (In/Out Method + Market, Broker Fee, Sales Tax, Reactions-Skill,
  Facility, Rig, Space, System, IndyTax, SCC, Build Time, Cycles, Cost Index, Prismaticite)
- Tabellen pro Gruppe (Inputs · Tax · Output · Profit · % prof. · Profit/h), grün/rot nach Profit,
  sortierbar per Klick auf die Spaltenköpfe
- Klick auf eine Reaction → Detailansicht (Input-Mengen und Preise, Steueraufschlüsselung,
  Runs, übrig gebliebene Zwischenprodukte bei Chain Reactions)
- **Ranking**-Tab: alle Reactions in einer Liste nach Profit
- **Save as default** speichert die Settings in `settings.json`, **Export CSV** lädt die Tabelle herunter

## Kommandozeile

```bash
python -m reactionding calc                          # alle Reactions, Tabellen pro Gruppe
python -m reactionding calc composite                # nur ein Calculator …
python -m reactionding calc simple strong_chain      # … oder einzelne Gruppen
python -m reactionding calc --sort profit --top 20   # Ranking über alles
python -m reactionding calc --format csv > reactions.csv   # auch: --format json [--full]
python -m reactionding show "Methanofullerene"       # Detailansicht einer Reaction
python -m reactionding show "Strong Frentix" --group strong_chain
python -m reactionding list                          # alle Reactions mit Type ID
python -m reactionding settings --set inMarket=Amarr skill=4 rigs=1   # Defaults speichern
python -m reactionding verify                        # alle Reactions auf Korrektheit prüfen
```

Jede Einstellung lässt sich auch einmalig per Option überschreiben, z. B.
`--space wormhole --costIndex 4.5 --input sell`. `python -m reactionding calc --help` zeigt alle.

Gültige Märkte sind **Jita, Amarr, Perimeter** (andere Namen bewertet die API stillschweigend mit
0 ISK, daher lehnt das Programm sie ab). Den System-Namen prüft das Programm über die offizielle
EVE-API (ESI): Die Schreibweise wird automatisch korrigiert (`ignoitton` → `Ignoitton`, die
Calculator-API unterscheidet Groß-/Kleinschreibung), unbekannte Systeme werden abgelehnt, und der
aktuelle Reaction Cost Index des Systems wird angezeigt.

## Datenquellen und Korrektheit

`verify` geht **jede** Reaction durch und macht drei Prüfungen:

1. **catalog** – Ist die Reaction-Liste des Programms noch identisch mit dem Calculator?
2. **api** – Jede Reaction wird über die API abgefragt und mit der Calculator-Seite verglichen
   (gleiche Engine, gleiche Settings).
3. **sde** – Rezepte (Inputs, Output-Menge, Reaction-Zeit) werden mit CCPs Static Data Export
   (Dump von fuzzwork.co.uk) abgeglichen.

Ergebnis des Durchlaufs (Stand Oktober 2026):

- **129 Reactions** (Hybrid, Simple, Complex, Complex Chain, Unrefined, Unrefined 55%, Synth,
  Strong, Molecular-Forging) liefert die API korrekt – identisch mit dem Calculator.
- Bei 6 Gruppen (48 Reactions) ist die API fehlerhaft. Dafür nutzt das Programm automatisch die Daten der
  Calculator-Seite (gleiche Engine, Settings werden als Cookies mitgegeben; in der Oberfläche als
  „calculator page“ markiert):

  | Gruppe | API-Problem |
  |---|---|
  | Standard Booster Reactions | jede ID wird mit `TYPE_ID_MISMATCH` abgelehnt |
  | Improved Booster Reactions | jede ID wird mit `TYPE_ID_MISMATCH` abgelehnt |
  | Improved Booster Chain Reactions | jede ID wird mit `TYPE_ID_MISMATCH` abgelehnt |
  | Unrefined Mineral Reactions (MAX Refine 90.63%) | jede ID wird mit `TYPE_ID_MISMATCH` abgelehnt |
  | Unrefined Mineral Reactions (no reprocessing) | rechnet mit 3600 s statt 360 s Reaction-Zeit (SDE) → 10× zu wenige Runs |
  | Strong Booster Chain Reactions | löst die Kette nicht auf, liefert nur die Inputs der Strong Booster Reaction |

- Rezeptfehler im Calculator selbst (API **und** Seite, laut SDE):
  - *Unrefined Tritanium*: 1000 statt 100 Atmospheric Gases pro Run
  - *Unrefined Zydrine*: 600 statt 1000 Atmospheric Gases pro Run
  - *Pure Strong Frentix Booster*: 100 statt 20 Hydrochloric Acid pro Run

  Diese Werte können nur auf der Calculator-Seite korrigiert werden; `verify` meldet sie.

Mit `--source api` bzw. `--source web` lässt sich eine Quelle erzwingen. Läuft `verify` eines
Tages ohne Befunde bei der API durch, kann in `reactionding/catalog.py` die `source` der
betroffenen Gruppe wieder auf `api` gestellt werden.

Die API erlaubt ca. 90 Anfragen pro Minute; das Programm drosselt sich selbst (`--rate`,
Standard 5/s) und wiederholt bei `429`.

## Spreadsheet prüfen

`check-sheet` liest alle fest eingetragenen Reaction-Rezepte aus einem Workbook (z.B. „Operation
Moonshine“) und vergleicht sie mit der Website: Inputs, Mengen pro Run, Output pro Run, Fuel-Block-Typ,
Moon-Goo- und Fuel-Bedarf in den Planungsblättern. Das braucht zusätzlich `openpyxl`:

```bash
pip install openpyxl
python -m reactionding check-sheet Operation_MoonShine_GT.xlsx --fixes   # mit Korrekturformeln
```

Das Ergebnis für die aktuelle Version steht in [docs/sheet-check.md](docs/sheet-check.md).

## Tests

```bash
python -m unittest discover -s tests
```
