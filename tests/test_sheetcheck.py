import unittest

try:
    import openpyxl
except ImportError:  # optional dependency
    openpyxl = None

if openpyxl:
    from reactionding.sheetcheck import (Sheet, check_formula_blocks, check_profit_sheet,
                                         check_quantity_sheet)

RECIPES = {
    "Caesarium Cadmide": {"group": "simple", "out": 200.0,
                          "in": {"Oxygen Fuel Block": 5.0, "Cadmium": 100.0, "Caesium": 100.0}},
    "Crystalline Carbonide": {"group": "complex", "out": 10000.0,
                              "in": {"Helium Fuel Block": 5.0, "Caesarium Cadmide": 100.0}},
    "Fulleroferrocene": {"group": "hybrid", "out": 1000.0,
                         "in": {"Oxygen Fuel Block": 5.0, "Fullerite-C50": 200.0}},
}


def sheet(cells, title="t"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    for ref, value in cells.items():
        ws[ref] = value
    return Sheet(ws)


@unittest.skipIf(openpyxl is None, "openpyxl not installed")
class ProfitSheetTest(unittest.TestCase):
    def test_correct_and_wrong_formulas(self):
        s = sheet({
            "E3": "Cadmium", "E4": "Caesium", "E5": "Oxygen Fuel Block", "E6": "Fullerite-C50",
            "H3": "=(100*A3+100*A4+5*A5)/200", "J3": "Caesarium Cadmide",
            "H4": "=(5*A5+100*A6)/1000", "J4": "Fulleroferrocene",
        })
        findings = check_profit_sheet(s, RECIPES)
        self.assertEqual([(f.cell, f.reaction) for f in findings], [("H4", "Fulleroferrocene")])
        self.assertIn("sheet 100, website 200", findings[0].message)
        self.assertEqual(findings[0].fix, "=(5*A5+200*A6)/1000")


@unittest.skipIf(openpyxl is None, "openpyxl not installed")
class FormulaBlockTest(unittest.TestCase):
    def test_block(self):
        s = sheet({"F2": "Caesarium Cadmide Formula", "F4": "Cadmium", "G4": 100, "F5": "Caesium",
                   "G5": 50, "F6": "Oxygen Fuel Block", "G6": 5,
                   "F9": "Caesarium Cadmide", "G9": 200})
        findings = check_formula_blocks(s, RECIPES)
        self.assertEqual(len(findings), 1)
        self.assertIn("Caesium: sheet 50, website 100", findings[0].message)


@unittest.skipIf(openpyxl is None, "openpyxl not installed")
class QuantitySheetTest(unittest.TestCase):
    def test_goo_demand_and_orders(self):
        s = sheet({
            "AB1": "Rig", "AC1": -0.0264,
            "F2": "Demand", "L2": "Stock", "M2": "production order", "N2": "batch production",
            "T2": "Reaction Formulas", "AA2": "1 run output",
            "J3": "Atmospheric Gases", "J4": "Cadmium", "J5": "Caesium", "J6": "Oxygen Fuel Block",
            "F4": "=MAX(M3-L3,0)",  # wrong: 1 Cadmium per Caesarium Cadmide
            "F5": "=ROUNDUP(54400*(1+$AC$1),0)*O3",  # corrected form -> must pass
            "F6": "=ROUNDUP(5/200*N3*(1+$AC$1),0)",
            "R3": "Caesarium Cadmide",
            "M3": "=ROUNDUP(54400*(1+$AC$1),0)*T3",
            "N3": "=roundup(if(L3>M3,0,M3-L3)/108800,0)*108800",
            "T3": 2, "AA3": 10000, "AD3": "Crystalline Carbonide",
        })
        findings = check_quantity_sheet(s, RECIPES)
        cells = sorted({f.cell for f in findings})
        self.assertEqual(cells, ["F4"])
        f4 = next(f for f in findings if f.cell == "F4")
        self.assertIn("sheet 1, website 0.5", f4.message)
        self.assertEqual(f4.fix, "=ROUNDUP(54400*(1+$AC$1),0)*O3")


if __name__ == "__main__":
    unittest.main()
