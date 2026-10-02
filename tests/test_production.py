import unittest

from reactionding import production, settings

RECIPES = {
    "Simple A": {"group": "simple", "out": 200.0, "in": {"Goo 1": 100.0, "Goo 2": 100.0, "Fuel": 5.0}},
    "Complex X": {"group": "complex", "out": 10000.0, "in": {"Simple A": 100.0, "Fuel": 5.0}},
}
COMPONENTS = {"Part": {"name": "Part", "capital": False, "outputPerRun": 1, "materials": {"Complex X": 9}}}
P = lambda b, s, note=None: {"buy": b, "split": (b + s) / 2, "sell": s, "note": note}  # noqa: E731
PRICES = {"Goo 1": P(10, 12), "Goo 2": P(20, 22), "Fuel": P(1000, 1000), "Simple A": P(30, 40),
          "Complex X": P(5, 6), "Part": P(100, 120)}


class HelpersTest(unittest.TestCase):
    def test_reaction_me(self):
        self.assertAlmostEqual(production.reaction_me(settings.normalize()), 0.0264)
        self.assertEqual(production.reaction_me(settings.normalize({"rigs": 0})), 0.0)
        self.assertAlmostEqual(production.reaction_me(settings.normalize({"space": "lowsec"})), 0.024)

    def test_job_quantity_like_eve(self):
        self.assertEqual(production.job_quantity(100, 544, 0.0264), 52964)
        self.assertEqual(production.job_quantity(5, 126, 0.0264), 614)  # calculator: 614 fuel blocks
        self.assertEqual(production.job_quantity(1, 10, 0.5), 10)  # never below one per run

    def test_parse_stock(self):
        text = ("Cadmium\t100.000\tMoon Materials\n"
                "Caesium\t1,234\n"
                "Hydrogen Fuel Block;500\n"
                "2 x Fullerides\n"
                "Cadmium\t5\n")
        self.assertEqual(production.parse_stock(text),
                         {"Cadmium": 100005, "Caesium": 1234, "Hydrogen Fuel Block": 500, "Fullerides": 2})


class ChainTest(unittest.TestCase):
    def test_costs(self):
        s = settings.normalize({"rigs": 0, "componentMe": 0})
        chain = production.cost_chain(RECIPES, s, prices=PRICES, components=COMPONENTS)
        simple = chain["simple"][0]
        # (100*10 + 100*20 + 5*1000) / 200 = 40 per unit with buy prices
        self.assertEqual(simple["cost"]["buy"], 40.0)
        self.assertEqual(simple["cost"]["sell"], (1200 + 2200 + 5000) / 200)
        self.assertEqual(simple["profit"]["buy"], 30 - 40.0)
        complex_ = chain["complex"][0]
        # own Simple A instead of market price: (100*40 + 5*1000) / 10000
        self.assertEqual(complex_["cost"]["buy"], 0.9)
        self.assertEqual(chain["components"][0]["cost"]["buy"], 9 * 0.9)

    def test_missing_price_note(self):
        prices = dict(PRICES, **{"Goo 1": P(10, 10, "no sell orders in Jita 4-4 - buy price used")})
        chain = production.cost_chain(RECIPES, settings.normalize(), prices=prices, components=COMPONENTS)
        self.assertIn("Goo 1", chain["simple"][0]["missingPrices"])


class PlanTest(unittest.TestCase):
    def test_plan_with_components_and_stock(self):
        s = settings.normalize()  # T2 rigs nullsec: 2.64 %, component ME 10 %
        state = {"runsPerJob": 544, "jobs": {"Complex X": 1}, "components": {"Part": 1000},
                 "stock": "Simple A\t50000\nGoo 1\t1000"}
        result = production.plan(RECIPES, s, state, prices=PRICES, components=COMPONENTS)
        top = result["top"][0]
        # Part: 1000 runs x 9 x 0.9 = 8100 Complex X -> 1 automatic job, plus 1 manual
        self.assertEqual((top["componentNeed"], top["autoJobs"], top["manualJobs"], top["jobs"]),
                         (8100, 1, 1, 2))
        simple = result["simple"][0]
        # 2 complex jobs x ceil(544*100*0.9736) = 105928, minus 50000 in stock -> 1 job
        self.assertEqual((simple["need"], simple["short"], simple["jobs"]), (105928, 55928, 1))
        shop = {x["name"]: x for x in result["shopping"]}
        self.assertEqual(shop["Goo 1"]["need"], 52964)
        self.assertEqual(shop["Goo 1"]["toBuy"], 51964)
        # fuel: 1 simple job + 2 complex jobs, 614... per job: ceil(544*5*0.9736) = 2649
        self.assertEqual(shop["Fuel"]["need"], 3 * 2649)
        self.assertEqual(shop["Goo 1"]["cost"]["sell"], 51964 * 12)
        self.assertEqual(result["shoppingTotal"]["buy"],
                         sum(x["cost"]["buy"] for x in result["shopping"]))


if __name__ == "__main__":
    unittest.main()
