import unittest

from reactionding import settings, tracker

RECIPES = {
    "Simple A": {"group": "simple", "out": 200.0, "in": {"Goo 1": 100.0, "Goo 2": 100.0, "Fuel": 5.0}},
    "Complex X": {"group": "complex", "out": 10000.0, "in": {"Simple A": 100.0, "Fuel": 5.0}},
}
COMPONENTS = {"Part": {"name": "Part", "capital": False, "outputPerRun": 1, "materials": {"Complex X": 9}}}
P = lambda b, s: {"buy": b, "split": (b + s) / 2, "sell": s, "note": None}  # noqa: E731
PRICES = {"Goo 1": P(10, 12), "Goo 2": P(20, 22), "Fuel": P(1000, 1000), "Simple A": P(30, 40),
          "Complex X": P(5, 6), "Part": P(100, 120)}
S = settings.normalize()  # T2 rigs nullsec: 2.64 %, component ME 10 %


def plan(campaign, index=-1):
    index = index % len(campaign["months"])
    return tracker.plan_month(RECIPES, COMPONENTS, S, campaign, index, prices=PRICES)


def lines(p, stage):
    return {ln["name"]: ln for ln in p[f"stage{stage}"]}


class PipelineTest(unittest.TestCase):
    def campaign(self, orders, slots=30):
        c = tracker.new_campaign()
        c["months"][0]["id"] = "2026-10"
        c["months"][0]["orders"] = orders
        c["slots"] = slots
        return c

    def test_month_ids(self):
        self.assertEqual(tracker.next_month_id("2026-12"), "2027-01")
        self.assertEqual(tracker.next_month_id("2026-10"), "2026-11")

    def test_three_stage_pipeline(self):
        c = self.campaign({"jobs": {"Complex X": 1}, "components": {"Part": 1000}})
        m0 = plan(c)
        # month 1: only stage 1 - simple reactions for 2 complex jobs (1 ordered + 1 for 8100 Complex X)
        self.assertEqual(m0["stage2"], [])
        self.assertEqual(m0["stage3"], [])
        self.assertEqual(lines(m0, 1)["Simple A"]["count"], 1)  # 2 x 52964 < 108800
        shop = {x["name"]: x for x in m0["shopping"]}
        self.assertEqual(shop["Goo 1"]["toBuy"], 52964)
        self.assertEqual(shop["Fuel"]["toBuy"], 2649)

        # finish the simple job, close without repeating -> month 2 runs stage 2 only
        c["months"][0]["track"] = {"1|Simple A": {"started": 1, "done": 1}}
        tracker.close_month(c, 0, plan(c, 0))
        self.assertEqual(c["months"][1]["id"], "2026-11")
        self.assertEqual(c["months"][1]["orders"], {"jobs": {}, "components": {}})
        c["months"][1]["stock"] = "Simple A\t108800"
        m1 = plan(c)
        self.assertEqual(m1["stage1"], [])
        x = lines(m1, 2)["Complex X"]
        self.assertEqual((x["ordered"], x["auto"], x["count"]), (1, 1, 2))
        self.assertEqual((x["scheduled"], x["blocked"]), (2, 0))  # 2 x 52964 Simple A from stock
        self.assertEqual({s["name"] for s in m1["shopping"]}, {"Fuel"})

        # month 3: components of the first run
        c["months"][1]["track"] = {"2|Complex X": {"started": 2, "done": 2}}
        tracker.close_month(c, 1, plan(c, 1))
        c["months"][2]["stock"] = "Complex X\t20000"
        m2 = plan(c)
        part = m2["stage3"][0]
        self.assertEqual((part["name"], part["units"], part["buildable"], part["blocked"]), ("Part", 1000, 1000, 0))
        self.assertEqual(m2["stage1"] + m2["stage2"], [])

    def test_new_run_from_zero_every_month(self):
        c = self.campaign({"jobs": {"Complex X": 1}, "components": {}})
        m0 = plan(c)
        tracker.close_month(c, 0, m0, repeat_orders=True)
        m1 = plan(c)
        # wave of month 1 (stage 2) and a new run started in month 2 (stage 1) at the same time
        self.assertIn("Complex X", lines(m1, 2))
        self.assertIn("Simple A", lines(m1, 1))
        self.assertEqual(m1["waves"], {"stage1": "2026-11", "stage2": "2026-10", "stage3": None})

    def test_run_length_depends_on_order(self):
        recipes = dict(RECIPES, **{"Hybrid H": {"group": "hybrid", "out": 100.0, "in": {"Goo 1": 100.0, "Fuel": 5.0}}})
        c = self.campaign({"jobs": {"Simple A": 2, "Hybrid H": 1}, "components": {}})
        m0 = tracker.plan_month(recipes, COMPONENTS, S, c, 0, prices=dict(PRICES, **{"Hybrid H": P(1, 1)}))
        # simple and hybrid orders are one-month runs: both in stage 1 of the order month
        self.assertEqual({n: ln["count"] for n, ln in lines(m0, 1).items()}, {"Simple A": 2, "Hybrid H": 1})
        self.assertEqual(m0["stage2"], [])

    def test_slot_limit_and_carry_over(self):
        c = self.campaign({"jobs": {"Complex X": 5}, "components": {}}, slots=2)
        m0 = plan(c)
        simple = lines(m0, 1)["Simple A"]  # 5 x 52964 = 264820 -> 3 jobs
        self.assertEqual((simple["count"], simple["scheduled"], simple["postponed"]), (3, 2, 1))
        self.assertEqual(m0["slotsUsed"], 2)
        # materials only for the 2 scheduled jobs
        self.assertEqual({x["name"]: x["toBuy"] for x in m0["shopping"]}["Goo 1"], 2 * 52964)
        # 2 started, 1 finished -> 1 running + 1 postponed carried over
        c["months"][0]["track"] = {"1|Simple A": {"started": 2, "done": 1}}
        tracker.close_month(c, 0, plan(c, 0))
        self.assertEqual(c["months"][1]["carry"], [{"stage": 1, "name": "Simple A", "count": 2, "started": 1}])
        m1 = plan(c)
        carried = lines(m1, 1)["Simple A"]
        self.assertEqual((carried["running"], carried["scheduled"]), (1, 2))
        self.assertEqual(m1["slotsUsed"], 2 + 0)  # 1 running + 1 carried; stage 2 waits for slots
        x = lines(m1, 2)["Complex X"]  # no Simple A in stock -> blocked, not bought
        self.assertEqual((x["count"], x["scheduled"], x["blocked"]), (5, 0, 5))
        self.assertNotIn("Simple A", {s["name"] for s in m1["shopping"]})

    def test_stage2_needs_simple_products_in_stock(self):
        c = self.campaign({"jobs": {"Complex X": 3}, "components": {}})
        c["months"][0]["track"] = {"1|Simple A": {"started": 2, "done": 2}}
        tracker.close_month(c, 0, plan(c, 0))
        m1 = plan(c)  # nothing pasted: no simple products in stock -> nothing runs
        x = lines(m1, 2)["Complex X"]
        self.assertEqual((x["scheduled"], x["blocked"]), (0, 3))
        self.assertEqual(m1["shopping"], [])
        c["months"][1]["stock"] = "Simple A\t110000"  # enough for 2 jobs (52964 each)
        m1 = plan(c)
        x = lines(m1, 2)["Complex X"]
        self.assertEqual((x["scheduled"], x["blocked"]), (2, 1))
        self.assertEqual({s["name"]: s["toBuy"] for s in m1["shopping"]}, {"Fuel": 2 * 2649})
        # blocked jobs move on when the month is closed
        c["months"][1]["track"] = {"2|Complex X": {"started": 2, "done": 2}}
        tracker.close_month(c, 1, plan(c, 1))
        self.assertEqual(c["months"][2]["carry"], [{"stage": 2, "name": "Complex X", "count": 1, "started": 0}])

    def test_components_limited_by_stock_and_carried(self):
        c = self.campaign({"jobs": {}, "components": {"Part": 1000}})
        tracker.close_month(c, 0, plan(c, 0))
        tracker.close_month(c, 1, plan(c, 1))
        c["months"][2]["stock"] = "Complex X\t4050"  # half of the 8100 needed
        m2 = plan(c)
        part = m2["stage3"][0]
        self.assertEqual((part["units"], part["buildable"], part["blocked"]), (1000, 500, 500))
        c["months"][2]["track"] = {"3|Part": {"done": 500}}
        tracker.close_month(c, 2, plan(c, 2))
        self.assertIn({"stage": 3, "name": "Part", "count": 500, "started": 0}, c["months"][3]["carry"])
        self.assertEqual(plan(c)["stage3"][0]["units"], 500)  # carried units are planned again

    def test_tracking_is_clamped(self):
        c = self.campaign({"jobs": {"Complex X": 1}, "components": {}})
        c["months"][0]["track"] = {"1|Simple A": {"started": 0, "done": 9}}
        simple = lines(plan(c), 1)["Simple A"]
        self.assertEqual((simple["count"], simple["started"], simple["done"]), (1, 1, 1))
        tracker.close_month(c, 0, plan(c, 0))
        self.assertEqual(c["months"][1]["carry"], [])

    def test_checklist(self):
        c = self.campaign({"jobs": {"Complex X": 1}, "components": {}})
        m0 = plan(c)
        items = {i["key"]: i for i in m0["checklist"]}
        self.assertFalse(items["stock"]["done"])
        self.assertIn("install 1 × Simple A", items["install|1|Simple A"]["text"])
        c["months"][0]["stock"] = "Goo 1\t10"
        c["months"][0]["track"] = {"1|Simple A": {"started": 1}}
        c["months"][0]["checks"] = {"buy": True}
        items = {i["key"]: i for i in plan(c)["checklist"]}
        self.assertTrue(items["stock"]["done"] and items["install|1|Simple A"]["done"] and items["buy"]["done"])
        self.assertFalse(items["close"]["done"])

    def test_purchases_tracked(self):
        c = self.campaign({"jobs": {"Complex X": 1}, "components": {}})
        c["months"][0]["bought"] = {"Goo 1": {"qty": 50000, "price": 11}}
        m0 = plan(c)
        goo = {x["name"]: x for x in m0["shopping"]}["Goo 1"]
        self.assertEqual((goo["toBuy"], goo["bought"], goo["remaining"]), (52964, 50000, 2964))
        self.assertEqual(goo["cost"]["buy"], 2964 * 10)
        self.assertEqual(m0["spent"], 50000 * 11)
        c["months"][0]["track"] = {"1|Simple A": {"started": 1, "done": 1}}
        tracker.close_month(c, 0, plan(c, 0))
        row = tracker.overview(c)[0]
        self.assertEqual(row["spent"], 550000)
        self.assertEqual(row["producedValue"]["buy"], 108800 * 30)
        self.assertEqual(row["profit"]["buy"], 108800 * 30 - 550000)


if __name__ == "__main__":
    unittest.main()
