# Prüfung „Operation Moonshine GT“ gegen den Reactions Calculator

Stand: 1. Oktober 2026. Geprüft wurden **alle Reactions, die im Workbook vorkommen**: 50 verschiedene
Reactions (24 Simple Reactions, 17 Complex Reactions, 9 Hybrid Reactions). Grundlage ist das
Basis-Rezept jeder Reaction laut API von reactions.coalition.space, abgefragt ohne Rigs, also ohne
Material-Bonus. Verglichen wurde mit den fest eingetragenen Mengen in den Formeln.

Erneut prüfen (z.B. nach dem Korrigieren):

```bash
pip install openpyxl
python -m reactionding check-sheet Operation_MoonShine_GT.xlsx --fixes
```

## Übersicht

| Blatt | Reactions | Ergebnis |
|---|---|---|
| 7 - Reactions Calculations Prof | 24 Simple, 17 Complex, 9 Hybrid | 48 ✅, **2 Fehler** |
| 8 - Reactions Calculations Quan | 24 Simple, 17 Complex | Rezept-Matrix ✅, **Moon-Goo-Bedarf falsch** |
| 8.1 - RCQ GamingToast | 24 Simple, 17 Complex | Rezept-Matrix ✅, **Moon-Goo-Bedarf falsch** |
| Kopie von 8.0 - Reactions Calcu | 24 Simple, 17 Complex, 9 Hybrid | wie 8, zusätzlich **Oxy-Faktor 10× und 4 Hybrid-Fehler** |
| 9 - Core Temperature Regulator | 7 (Formula-Blöcke) | alle ✅, Einkaufsliste pro CTR ✅ |
| 4.1 - Material GT / BPO Archive | nur als Material | – |

Alle Preisabfragen (`getStationMarketPrice`) zeigen auf die richtige Zeile und auf Jita 4-4
(Region 10000002, Station 60003760) ✅.

## Blatt 7 – Reactions Calculations Prof

| Zelle | Reaction | Fehler | Korrektur |
|---|---|---|---|
| **H39** | Fulleroferrocene | 100 Fullerite-C50 statt **200** | `=(5*A32+200*A39+100*A41+1000*A51)/1000` |
| H42 | Methanofullerene | Isogen über `C46` (Jita Buy) statt `A46` („Personal Buy“) – solange B2 = 0 gleiches Ergebnis | `=(5*A30+100*A42+100*A43+300*A46)/160` |

Korrekt sind alle 24 Simple-Reaction-Preise (H3–H26), alle 17 Complex-Reaction-Preise (M3–M19), der
Output pro Run in Spalte R und 8 von 9 Hybriden.

Hinweise (keine Rezeptfehler):

- Fuel Blocks werden fast überall mit dem festen Wert aus A29–A32 (19.500 ISK) gerechnet, nur
  Scandium Metallofullerene (H44) nutzt den Marktpreis aus A24.
- „Profit“ (Spalte Q) = Jita Sell − Materialkosten. Job-Kosten (System Cost Index, Facility, SCC),
  Broker/Sales Tax und der Material-Bonus der Rigs fehlen. Die Website und dieses Programm rechnen
  sie mit ein, deshalb weichen die Profite ab.

## Blätter 8 und 8.1 – Mengenplanung

Korrekt ✅:

- welche Simple Reactions jede Complex Reaction braucht und wie viele (Spalte M bzw. L)
- Output pro Run der Complex Reactions (Spalte AA bzw. Z)
- Batch-Größen (108.800 = 544 Runs × 200, Oxy-Organic Solvents 5.440 = 544 × 10)
- Fuel Blocks der Complex Reactions inklusive Typ

### Fehler 1: Moon-Goo-Bedarf doppelt so hoch (Spalte F bzw. E)

Eine Simple Reaction macht aus **100 + 100 Moon Goo 200 Stück**, pro Stück Produkt braucht man also
**0,5** Goo. Die Formeln rechnen mit `MAX(M-L,0)`, also mit **1 Goo pro Stück**. Außerdem nutzen sie
den Fehlbestand statt der tatsächlich gestarteten Batches.

### Fehler 2: falsche oder fehlende Zuordnungen

| Zelle (8.1) | Problem |
|---|---|
| F10 Hafnium | **Vanadium Hafnite fehlt** (braucht 100 Hafnium/Run) |
| F12 Mercury | **Promethium Mercurite fehlt**, dafür ist **Prometium** drin (braucht kein Mercury) |
| F24/F29 → F27/F32 | **Prometium** braucht **Oxygen** Fuel Block, nicht Helium |
| F3, F11 | Oxy-Organic Solvents: Faktor `1059277/5440` enthält den Rig-Bonus schon und wird zusätzlich mit `(1+$AC$1)` multipliziert (194,72 statt 200 pro Stück vor Bonus) |

Auswirkung mit der aktuellen Planung in 8.1 (Cached-Werte aus der Datei):

| Material | Sheet „Demand“ | korrekt |
|---|---:|---:|
| Atmospheric Gases | 515.280 | 264.820 |
| Cadmium | 206.112 | 105.928 |
| Evaporite Deposits | 824.448 | 423.712 |
| **Hafnium** | **0** | **52.964** |
| Hydrocarbons | 618.336 | 317.784 |
| Silicates | 927.504 | 476.676 |
| Vanadium | 206.112 | 105.928 |
| übrige Goo (je 1 Job) | 103.056 | 52.964 |
| Fuel Blocks | ✅ (±3 durch Rundung) | |

### Korrigierte Formeln für 8.1 (Bedarf pro gestartetem 544-Run-Job, mit Rig-Bonus)

Spalte O = Anzahl Jobs aus „batch production“.

| Zelle | Material | Formel |
|---|---|---|
| F3 | Atmospheric Gases | `=ROUNDUP(1088000*(1+$AC$1),0)*O15+ROUNDUP(54400*(1+$AC$1),0)*O22+ROUNDUP(54400*(1+$AC$1),0)*O23` |
| F4 | Cadmium | `=ROUNDUP(54400*(1+$AC$1),0)*O3+ROUNDUP(54400*(1+$AC$1),0)*O7+ROUNDUP(54400*(1+$AC$1),0)*O18` |
| F5 | Caesium | `=ROUNDUP(54400*(1+$AC$1),0)*O3+ROUNDUP(54400*(1+$AC$1),0)*O21` |
| F6 | Chromium | `=ROUNDUP(54400*(1+$AC$1),0)*O12+ROUNDUP(54400*(1+$AC$1),0)*O21+ROUNDUP(54400*(1+$AC$1),0)*O25` |
| F7 | Cobalt | `=ROUNDUP(54400*(1+$AC$1),0)*O7` |
| F8 | Dysprosium | `=ROUNDUP(54400*(1+$AC$1),0)*O8+ROUNDUP(54400*(1+$AC$1),0)*O10` |
| F9 | Evaporite Deposits | `=ROUNDUP(54400*(1+$AC$1),0)*O4+ROUNDUP(54400*(1+$AC$1),0)*O6+ROUNDUP(54400*(1+$AC$1),0)*O20+ROUNDUP(54400*(1+$AC$1),0)*O22` |
| F10 | Hafnium | `=ROUNDUP(54400*(1+$AC$1),0)*O10+ROUNDUP(54400*(1+$AC$1),0)*O24+ROUNDUP(54400*(1+$AC$1),0)*O26` |
| F11 | Hydrocarbons | `=ROUNDUP(54400*(1+$AC$1),0)*O4+ROUNDUP(54400*(1+$AC$1),0)*O5+ROUNDUP(1088000*(1+$AC$1),0)*O15` |
| F12 | Mercury | `=ROUNDUP(54400*(1+$AC$1),0)*O8+ROUNDUP(54400*(1+$AC$1),0)*O14+ROUNDUP(54400*(1+$AC$1),0)*O17` |
| F13 | Neodymium | `=ROUNDUP(54400*(1+$AC$1),0)*O11+ROUNDUP(54400*(1+$AC$1),0)*O14` |
| F14 | Platinum | `=ROUNDUP(54400*(1+$AC$1),0)*O12+ROUNDUP(54400*(1+$AC$1),0)*O16+ROUNDUP(54400*(1+$AC$1),0)*O19` |
| F15 | Promethium | `=ROUNDUP(54400*(1+$AC$1),0)*O13+ROUNDUP(54400*(1+$AC$1),0)*O17+ROUNDUP(54400*(1+$AC$1),0)*O18` |
| F16 | Scandium | `=ROUNDUP(54400*(1+$AC$1),0)*O9` |
| F17 | Silicates | `=ROUNDUP(54400*(1+$AC$1),0)*O5+ROUNDUP(54400*(1+$AC$1),0)*O6+ROUNDUP(54400*(1+$AC$1),0)*O20+ROUNDUP(54400*(1+$AC$1),0)*O23` |
| F18 | Technetium | `=ROUNDUP(54400*(1+$AC$1),0)*O16` |
| F19 | Thulium | `=ROUNDUP(54400*(1+$AC$1),0)*O11+ROUNDUP(54400*(1+$AC$1),0)*O24` |
| F20 | Titanium | `=ROUNDUP(54400*(1+$AC$1),0)*O25` |
| F21 | Tungsten | `=ROUNDUP(54400*(1+$AC$1),0)*O19` |
| F22 | Vanadium | `=ROUNDUP(54400*(1+$AC$1),0)*O9+ROUNDUP(54400*(1+$AC$1),0)*O13+ROUNDUP(54400*(1+$AC$1),0)*O26` |

Fuel: In **F24 und F29** den Term `ROUNDUP(5/200*N18*(1+$AC$1),0)` entfernen und in **F27 und F32**
einfügen (Prometium → Oxygen Fuel Block).

Für Blatt 8 gelten dieselben Korrekturen mit verschobenen Spalten (Bedarf E, Jobs N, Rig `$AB$1`).
`check-sheet --fixes` gibt die passenden Formeln aus.

## Kopie von 8.0

Dieselben Fehler wie in 8, zusätzlich:

- **E3/E11 Oxy-Organic Solvents**: Faktor `1088000/544` = **2000** Atmospheric Gases bzw. Hydrocarbons
  pro Stück, richtig sind **200** (2000 pro Run bei 10 Stück Output), also 10× zu viel.
- **Hybrid-Planung (Zeilen 37–53)**, die Zellbezüge sind teilweise um eine Zeile verrutscht:

  | Reaction | Problem |
  |---|---|
  | Graphene Nanoribbons (N41) | **400 Nocxium fehlen** (E50 zählt nur Lanthanum Metallofullerene) |
  | PPD Fullerene Fibers (N44) | bekommt Fullerite-C72 und 25 Zydrine, braucht aber **Fullerite-C60** (300 C50 und 800 Pyerite stimmen) |
  | Scandium Metallofullerene (N45) | **Fullerite-C72 und 25 Zydrine fehlen** (stehen bei N44) |
  | Methanofullerene (N43) | Fuel unter **Nitrogen** (E26) bzw. **Oxygen** (E32), richtig ist **Hydrogen** (E25/E30) |

  Korrektur: in E44 und E53 `N44` → `N45`, in E42 `+roundup((N44*100)*(1+AC1),0)` ergänzen, in E50
  `+roundup((N41*400)*(1+AC1),0)` ergänzen, Methanofullerene-Fuel `(N43*5)` aus E26/E32 nach E25/E30.

## Blatt 9 – Core Temperature Regulator

Alle 7 Formula-Blöcke stimmen (Carbon Polymers, Sulfuric Acid, Oxy-Organic Solvents, Carbon Fiber,
Thermosetting Polymer, Pressurized Oxidizers, Reinforced Carbon Fiber). Die Einkaufsliste pro Core
Temperature Regulator (je 1350 Hydrocarbons und Atmospheric Gases, je 450 Evaporite Deposits und
Silicates) ist nachgerechnet korrekt. Sie rechnet ohne Rig-Bonus, ist also leicht konservativ.
