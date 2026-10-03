# EVE Online Reaction Ding

Profit-Rechner, Kostenkette und Produktionsplaner für alle **Reactions** in EVE Online, als
Kommandozeilen-Tool und als Web-Oberfläche im Browser (bzw. Windows-.exe).

Woher die Daten kommen:

| Daten | Quelle |
|---|---|
| **Preise** | live aus der offiziellen EVE-API (ESI), Jita 4-4: **Buy** = höchste Buy-Order, **Sell** = niedrigste Sell-Order, **Split** = Mitte von Buy und Sell. Fehlt eine Seite, wird die andere genommen und das Item markiert ⚠. Die Preise werden 15 Minuten gecacht (auch auf der Festplatte) und im Hintergrund alle 15 Minuten erneuert. Ist ESI nicht erreichbar, gelten die letzten bekannten Preise. |
| **Rezepte** | CCPs offizieller Static Data Export (developers.eveonline.com). Gelesen wird nur der Blueprint-Teil (~190 KB). Eine Kopie liegt bei, falls man offline ist. |
| **Mengen, Runs, Job-Kosten** der Profit-Tabelle | [EVE Online Reactions Calculator](https://reactions.coalition.space) (Oxed G), primär über dessen [API](https://reactions.coalition.space/api) |
| **System Cost Index**, Systemnamen | ESI |

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
Wo die Daten landen, steht unter [Speicherort](#speicherort-mariadb-oder-ordner).

Alle Befehle gehen auch in der Eingabeaufforderung, z.B. `EVEReactionDing.exe calc --sort profit --top 10`
oder `EVEReactionDing.exe check-sheet Operation_MoonShine_GT.xlsx --fixes`.

Die .exe ist nicht signiert. Windows SmartScreen meldet deshalb beim ersten Start „Der Computer wurde
durch Windows geschützt“. Mit **Weitere Informationen → Trotzdem ausführen** startet sie.

Selbst bauen (unter Windows): `pip install pyinstaller openpyxl pymysql` und `python packaging/build_exe.py`.
Der GitHub-Workflow `.github/workflows/build-exe.yml` baut sie bei jeder Änderung auf einem
Windows-Server und hängt sie als Artefakt an.

## Web-Oberfläche

```bash
python -m reactionding            # oder: python -m reactionding serve --open
```

Öffnet <http://127.0.0.1:8765/> im Browser. Oben stehen die Einstellungen (Broker Fee, Sales Tax,
Reactions-Skill, Facility, Rig, Space, System, IndyTax, SCC, Build Time, Cycles, Cost Index,
Prismaticite, **Component ME %**). Darunter gibt es drei Bereiche, überall mit **Buy, Split und Sell
als Spalten nebeneinander**. Die Einstellungen sind eingeklappt, oben steht eine Zusammenfassung:

1. **Reactions:** alle 177 Reactions mit **Cost Buy | Cost Split | Cost Sell | Profit Buy |
   Profit Split | Profit Sell**, sortierbar, mit Ranking-Tab. Klick auf eine Reaction zeigt die
   Stückpreise und die Aufschlüsselung (Material, Marktgebühren, Job-Kosten, Output).
   - Cost = Input-Material + Marktgebühren Inputs + Job-Kosten (System Cost Index, Facility, SCC)
   - Profit = Output-Wert − Marktgebühren Output − Cost
   - Gebühren wie im Calculator: Kauf per Buy-Order kostet Broker Fee, Verkauf per Sell-Order Broker
     Fee + Sales Tax, Verkauf an Buy-Orders nur Sales Tax. Split = Mitte von Buy und Sell.
2. **Cost chain (Nachbau Blatt 7):** Herstellkosten pro Stück, wenn man alles selbst reagiert (Moon
   Goo → Simple → Complex → T2- und Capital-T2-Komponenten), gegen den Jita-Preis. Spalten: Jita
   Buy/Split/Sell, Cost Buy/Split/Sell, Profit Buy/Split/Sell, Marge, Profit pro Run. Wie Blatt 7
   ohne Job-Kosten und Gebühren, aber mit Rig-Bonus (Reaction ME) und Component ME.
3. **Monthly planner (Nachbau Blatt 8.1 als Pipeline über 1–3 Monate):** Ein Reaction-Job
   (544 Runs) dauert etwa einen Monat. Jeder Monat kann bei Bedarf einen **neuen Durchlauf ab Null**
   starten. Wie lange er dauert, hängt davon ab, was man reagieren will:

   | Auftrag | Monat 1 | Monat 2 | Monat 3 |
   |---|---|---|---|
   | Simple / Hybrid Reaction | Reaction | – | – |
   | Complex Reaction | Simple Reactions dafür | Complex Reaction | – |
   | Komponente (T2 / Capital T2) | Simple Reactions | Complex Reactions | Komponente bauen |

   - **＋ Create plan:** Assistent für einen neuen Plan. Startmonat, Runs pro Job und Slots wählen,
     Reactions/Komponenten hinzufügen, optional das Lager einfügen. Dabei zeigt eine **Live-Vorschau**
     Materialkosten, Wert der Produkte, Profit und Marge (Buy/Split/Sell), wie viele Monate der
     Durchlauf dauert und wie viele Jobs er braucht (ohne Job-Installationskosten und Marktgebühren).
     Der neue Durchlauf wird an den bestehenden Plan angehängt oder ersetzt ihn.
   - **Jeder Monat in 4 Schritten:** ① *Orders & stock* (Aufträge + Lager aus EVE einfügen),
     ② *Buy materials* (Einkaufsliste, „Copy for EVE Multibuy“, „Mark all as bought“),
     ③ *Reaction checklist* (jede Reaction mit Häkchen *started* / *done*, Fortschrittsbalken pro Stufe,
     „All started“ / „All done“), ④ *Close month*. Oben stehen Kosten → Wert = erwarteter Profit.
   - **Preise:** Ein Schalter Buy / Split / Sell gilt für den ganzen Planer.
   - **Gewinn ohne Doppelzählung:** Kosten eines Monats = Einkäufe + Wert der *eigenen
     Zwischenprodukte*, die aus dem Lager verbraucht werden (Simple-Produkte in Complex-Jobs,
     Complex-Produkte in Komponenten). Die Monatsgewinne eines Durchlaufs ergeben zusammen genau
     seinen Gesamtgewinn. Unter den Kennzahlen steht zusätzlich der Gewinn des ganzen Durchlaufs.
   - **„Add the finished products of …“** übernimmt die im Vormonat als *done* markierten Produkte
     ins Lager, falls du es nicht neu aus EVE einfügen willst.
   - **Lager:** wird zu jedem Monatsbeginn aus EVE eingefügt (Inventar, Strg+A, Strg+C).
   - **Stufe 2 und 3 laufen nur mit dem, was wirklich im Lager ist.** Sind die Simple Reactions
     nicht fertig oder nicht im eingefügten Lager, ist der Complex-Job *blockiert* und wandert in
     den nächsten Monat (er wird nicht auf die Einkaufsliste gesetzt). Ebenso werden nur so viele
     Komponenten gebaut, wie Complex-Produkte da sind.
   - **Reaction-Slots:** zuerst laufende Jobs, dann Stufe 2, dann übertragene Jobs, dann Stufe 1.
     Was keinen Slot bekommt, wandert weiter.
   - **Monat abschließen:** Unfertige, blockierte und verschobene Jobs sowie ungebaute Komponenten
     wandern in den nächsten Monat. Auf Wunsch starten die Aufträge dort als neuer Durchlauf.
     „Undo close“ macht das rückgängig, solange der neue Monat unbenutzt ist.
   - **📊 Overview:** Ausgaben, produzierter Wert und Gewinn gesamt, erwarteter Gewinn des offenen
     Monats, ein Balkendiagramm Kosten/Wert pro Monat, eine Zeitleiste, welcher Durchlauf in welchem
     Monat in welcher Stufe ist, und die Monatstabelle.

   Alles wird automatisch gespeichert (siehe [Speicherort](#speicherort-mariadb-oder-ordner)).

## Speicherort: MariaDB oder Ordner

Beim Start sucht das Programm auf **diesem PC** nach einer MariaDB (oder MySQL) auf den Ports
3306, 3307 und 3308:

- **MariaDB gefunden und Login klappt** → Einstellungen, Monatsplaner und einmaliger Plan werden
  in der Datenbank `eve_reaction_ding` gespeichert. Datenbank und Tabellen (`documents`, `history`
  mit den letzten 50 Ständen des Monatsplaners) legt das Programm selbst an. Zusätzlich liegt
  immer eine Sicherungskopie im Datenordner.
- **Keine MariaDB gefunden** → alles kommt in den Ordner `EVEReactionDing-data` neben der .exe
  (bzw. `data/` beim Start aus dem Quellcode).

Ohne gespeicherten Login probiert das Programm `root` ohne Passwort. Hat dein `root` ein Passwort
(beim Windows-Installer von MariaDB üblich), steht oben in den Settings unter **Storage**
„MariaDB found …, but: login refused“. Dann unter **MariaDB login** Benutzer und Passwort eintragen,
**Test connection** und **Save & connect**. Der Login steht dann in
`EVEReactionDing-data/database.json`. Das Passwort ist dort **im Klartext** gespeichert. Am besten
nimmst du daher einen eigenen Benutzer statt root:

```sql
CREATE USER 'eve'@'localhost' IDENTIFIED BY 'dein-passwort';
GRANT ALL PRIVILEGES ON eve_reaction_ding.* TO 'eve'@'localhost';
```

Ist die Datenbank später einmal nicht erreichbar, speichert das Programm in den Ordner und zeigt das
unter Storage an. „Use MariaDB: never“ schaltet die Datenbank ganz ab.

Alte Dateien (`settings.json`, `campaign.json`, `planner.json` neben der .exe) werden beim ersten
Start automatisch in den Datenordner bzw. in die Datenbank übernommen.

In der Kommandozeile gibt es dafür: `reactionding storage` (zeigt den Speicherort),
`reactionding storage --set user=eve password=geheim port=3306`, `--off` und `--on`.

## Auf einem Server (z. B. Railway)

`railway.json` / `Procfile` starten `python -m reactionding serve --host 0.0.0.0`; der Port kommt
aus der Umgebungsvariable `PORT`. Repo in Railway verbinden, deployen, unter *Settings → Networking*
eine Domain erzeugen. Daten liegen dort im Ordner `data/` und gehen bei einem neuen Deploy verloren
(für Dauerbetrieb eine MariaDB dazubuchen und den Login unter Settings → Storage eintragen).
Es gibt kein Login – jeder mit dem Link kann den Plan sehen und ändern.

## Kommandozeile

```bash
python -m reactionding calc                          # alle Reactions, Tabellen pro Gruppe
python -m reactionding calc composite                # nur ein Calculator …
python -m reactionding calc simple strong_chain      # … oder einzelne Gruppen
python -m reactionding calc --sort profit_split --top 20   # Ranking (auch profit_buy, cost_sell, …)
python -m reactionding calc --format csv > reactions.csv   # auch: --format json [--full]
python -m reactionding show "Methanofullerene"       # Detailansicht einer Reaction
python -m reactionding show "Strong Frentix" --group strong_chain
python -m reactionding list                          # alle Reactions mit Type ID
python -m reactionding chain complex components       # Kostenkette (Blatt 7)
python -m reactionding plan --job "Fullerides=2" --component "Antimatter Reactor Unit=1000" --stock lager.txt   # einmaliger Plan ohne Monate
python -m reactionding settings --set skill=4 rigs=1  # Defaults speichern
python -m reactionding verify                        # alle Reactions auf Korrektheit prüfen
```

Jede Einstellung lässt sich auch einmalig per Option überschreiben, z. B.
`--space wormhole --costIndex 4.5`. `python -m reactionding calc --help` zeigt alle.

Den System-Namen prüft das Programm über die offizielle
EVE-API (ESI): Die Schreibweise wird automatisch korrigiert (`ignoitton` → `Ignoitton`, die
Calculator-API unterscheidet Groß-/Kleinschreibung), unbekannte Systeme werden abgelehnt, und der
aktuelle Reaction Cost Index des Systems wird angezeigt.

## Datenquellen und Korrektheit

`verify` geht **jede** Reaction durch und macht drei Prüfungen:

1. **catalog** – Ist die Reaction-Liste des Programms noch identisch mit dem Calculator?
2. **api** – Jede Reaction wird über die API abgefragt und mit der Calculator-Seite verglichen
   (gleiche Engine, gleiche Settings).
3. **sde** – Rezepte (Inputs, Output-Menge, Reaction-Zeit) werden mit CCPs offiziellem Static Data
   Export abgeglichen.

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

- Rezeptfehler im Calculator selbst (API **und** Seite, laut CCPs offiziellen Daten; in der
  Profit-Tabelle mit ⚠ markiert, Kostenkette und Planner nutzen die richtigen CCP-Rezepte):
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
