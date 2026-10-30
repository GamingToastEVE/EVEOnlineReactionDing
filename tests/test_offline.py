import unittest

from reactionding import devalue, settings
from reactionding.catalog import GROUPS, find_items, groups_for
from reactionding.client import ApiError
from reactionding.engine import calculate
from reactionding.verify import check_catalog, check_sde


def result(item_id, name, profit, runs=10, inputs=(), out_qty=None):
    return {"id": item_id, "name": name, "profit": profit, "profit_per": 1.0, "runs": runs,
            "input_total": 100.0, "taxes_total": 5.0, "output_total": 105.0 + profit,
            "input": list(inputs), "output": {"id": item_id, "name": name, "quantity": out_qty},
            "cycle_data": {"total_time": 600}}


def calc_result(item_id=1, name="x", minutes=60):
    """Calculator-like result: 10 Mat + 1 Fuel in, 4 units out, job cost 5."""
    return {"id": item_id, "name": name, "runs": 2,
            "input": [{"id": 9, "name": "Mat", "quantity": 10}, {"id": 8, "name": "Fuel", "quantity": 1}],
            "output": {"id": item_id, "name": name, "quantity": 4},
            "taxes": {"total": {"install": 5.0}}, "cycle_data": {"total_time": minutes}}


PRICES = {"Mat": {"buy": 10.0, "split": 11.0, "sell": 12.0, "note": None},
          "Fuel": {"buy": 100.0, "split": 100.0, "sell": 100.0,
                   "note": "no sell orders in Jita 4-4 - buy price used"},
          "x": {"buy": 50.0, "split": 55.0, "sell": 60.0, "note": None}}


class FakeClient:
    def __init__(self):
        self.api_calls = []
        self.web_calls = []

    def api_calculate(self, group, item_id, values, name=""):
        self.api_calls.append((group.key, item_id))
        if item_id == 30303:
            raise ApiError(400, "TYPE_ID_MISMATCH", "boom")
        return calc_result(item_id)

    def web_results(self, calculator, values):
        self.web_calls.append(calculator)
        pages = {}
        for g in GROUPS.values():
            if g.calculator == calculator:
                # chain tables on the page carry no id, only the name
                pages[g.web_key] = [dict(calc_result(name=n), id=None) for _, n in g.items]
        return pages


def priced_rows(groups, values=None):
    rows = calculate(values or settings.normalize(), groups, client=FakeClient(), prices=False)
    for row in rows:
        if row.result:
            row.prices = {n: PRICES.get(n, PRICES["x"]) for n in ("Mat", "Fuel", row.result["output"]["name"])}
            row.brokers, row.sales = 3.0, 4.0
    return rows


class DevalueTest(unittest.TestCase):
    def test_unflatten_references_and_specials(self):
        data = [{"a": 1, "b": 2, "c": 3}, "x", [1, -5], [1, 1]]
        self.assertEqual(devalue.unflatten(data), {"a": "x", "b": ["x", float("-inf")], "c": ["x", "x"]})

    def test_decode_page(self):
        payload = {"type": "data", "nodes": [None, {"type": "data", "data": [{"results": 1}, [2], 5]}]}
        self.assertEqual(devalue.decode_page(payload), [None, {"results": [5]}])


class SettingsTest(unittest.TestCase):
    def test_defaults_valid(self):
        self.assertEqual(settings.normalize()["skill"], 5)

    def test_aliases_and_types(self):
        s = settings.normalize({"indyTax": "2.5", "rigs": "1", "space": "WORMHOLE", "duration": "60"})
        self.assertEqual((s["tax"], s["rigs"], s["space"], s["duration"]), (2.5, 1, "wormhole", 60))

    def test_old_price_settings_are_ignored(self):
        values = settings.normalize({"inMarket": "Amarr", "input": "split"})
        self.assertNotIn("inMarket", values)
        query = settings.to_query(values)  # API v2: Jita, prices come from ESI anyway
        self.assertEqual((query["inputHub"], query["outputHub"]), ("jita", "jita"))
        self.assertNotIn("componentMe", query)

    def test_invalid(self):
        for bad in ({"sales": 9}, {"skill": 6}, {"facility": "small"}, {"duration": 1.5}, {"foo": 1}):
            with self.assertRaises(settings.SettingsError):
                settings.normalize(bad)

    def test_v2_query(self):
        q = settings.to_query(settings.normalize({"tax": 1, "rigs": 1, "facility": "medium", "duration": 20160}))
        self.assertEqual((q["facilityTax"], q["salesTax"], q["broker"]), ("1", "3.6", "3"))
        self.assertEqual((q["structure"], q["meRig"], q["teRig"], q["cycleDays"]), ("athanor", "t1", "t1", "14"))
        self.assertNotIn("costIndex", q)  # only for wormholes, else the system's index is used
        q = settings.to_query(settings.normalize({"space": "wormhole", "costIndex": 4.5}))
        self.assertEqual(q["costIndex"], "4.5")


class CatalogTest(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(len(GROUPS), 15)
        self.assertEqual(sum(len(g.items) for g in GROUPS.values()), 177)

    def test_chain_groups_reuse_base_ids(self):
        for chain, base in (("chain", "complex"), ("improved_chain", "improved"),
                            ("strong_chain", "strong"), ("refined", "unrefined"),
                            ("eratic_repro", "eratic")):
            self.assertEqual(GROUPS[chain].items, GROUPS[base].items)

    def test_every_group_uses_api_v2(self):
        from reactionding.catalog import v2_view
        self.assertTrue(all(g.source == "api" and not g.issue for g in GROUPS.values()))
        self.assertEqual(v2_view(GROUPS["strong_chain"]), ("chain", "product"))
        self.assertEqual(v2_view(GROUPS["refined"]), ("single", "reprocessed"))
        self.assertEqual(v2_view(GROUPS["hybrid"]), ("single", "product"))

    def test_groups_for_and_find(self):
        self.assertEqual(len(groups_for(["biochemical"])), 7)
        self.assertEqual([g.key for g in groups_for(["eratic-repro"])], ["eratic_repro"])
        with self.assertRaises(KeyError):
            groups_for(["nope"])
        self.assertEqual({g.key for g, _, _ in find_items("30306")}, {"hybrid"})


class EngineTest(unittest.TestCase):
    def test_everything_through_the_api(self):
        client = FakeClient()
        rows = calculate(settings.normalize(), groups_for(["hybrid", "strong_chain"]), client=client,
                         prices=False)
        self.assertEqual(len(rows), 17)
        self.assertEqual(len(client.api_calls), 17)
        hybrid = [r for r in rows if r.group.key == "hybrid"]
        self.assertTrue(all(r.source == "api" for r in rows))
        self.assertEqual([r.item_id for r in hybrid if r.result is None], [30303])
        # order follows the catalog
        self.assertEqual([r.item_id for r in hybrid], [i for i, _ in GROUPS["hybrid"].items])

    def test_cost_and_profit_for_buy_split_sell(self):
        row = priced_rows(["simple"])[0]
        buy, split, sell = row.view("buy"), row.view("split"), row.view("sell")
        # buy: inputs 10*10 + 1*100 = 200, broker 3 % = 6, job cost 5 -> cost 211
        #      output 4*50 = 200, sold into buy orders: sales tax 4 % = 8
        self.assertEqual((buy["inputs"], buy["inputFees"], buy["cost"]), (200.0, 6.0, 211.0))
        self.assertEqual((buy["output"], buy["outputFees"], buy["profit"]), (200.0, 8.0, 200 - 8 - 211))
        # sell: inputs 10*12 + 100 = 220, no broker -> cost 225; output 240, broker + sales 7 %
        self.assertEqual(sell["cost"], 225.0)
        self.assertAlmostEqual(sell["profit"], 240 - 240 * 0.07 - 225)
        # split is the middle of buy and sell
        self.assertAlmostEqual(split["cost"], (211 + 225) / 2)
        self.assertAlmostEqual(split["profit"], (buy["profit"] + sell["profit"]) / 2)
        d = row.to_dict(full=True)
        self.assertEqual(set(d["views"]), {"buy", "split", "sell"})
        self.assertAlmostEqual(d["profit_split"], split["profit"])
        self.assertEqual(d["missingPrices"], {"Fuel": "no sell orders in Jita 4-4 - buy price used"})

    def test_several_outputs(self):
        row = priced_rows(["refined"])[0]
        row.result["output"] = [{"name": "x", "quantity": 2}, {"name": "x", "quantity": 1}]
        self.assertEqual(row.view("buy")["output"], 150.0)

    def test_v2_result_conversion(self):
        from reactionding.client import convert_v2
        r = convert_v2({"name": "X", "runs": 10, "runTimeSeconds": 60,
                        "inputs": [{"typeId": 1, "name": "Mat", "quantity": 50}],
                        "outputs": [{"typeId": 2, "name": "X", "quantity": 20}],
                        "jobCost": {"systemCost": 3.0, "total": 7.5}, "totals": {"slotSeconds": 600}})
        self.assertEqual(r["input"], [{"name": "Mat", "id": 1, "quantity": 50}])
        self.assertEqual(r["output"][0]["quantity"], 20)
        self.assertEqual(r["taxes"]["total"]["install"], 7.5)
        self.assertEqual(r["cycle_data"]["total_time"], 10.0)

    def test_zero_output_is_json_safe(self):
        row = priced_rows(["eratic"])[0]
        row.prices[row.result["output"]["name"]] = {"buy": 0.0, "split": 0.0, "sell": 0.0, "note": None}
        self.assertIsNone(row.to_dict()["profitPercent_buy"])
        row.result["profit_per"] = float("-inf")
        self.assertIsNone(row.to_dict(full=True)["result"]["profit_per"])

    def test_ccp_recipe_note(self):
        from reactionding import engine, sde
        rows = priced_rows(["simple"])
        sde._loaded["data"] = {"reactions": {rows[0].name: {"in": {"Mat": 5, "Fuel": 0.5}}}}
        try:
            engine.compare_with_ccp(rows)
        finally:
            sde._loaded.clear()
        self.assertEqual(rows[0].notes, [])  # 10 Mat / 2 runs = 5 per run
        rows[0].result["input"][0]["quantity"] = 40
        sde._loaded["data"] = {"reactions": {rows[0].name: {"in": {"Mat": 5, "Fuel": 0.5}}}}
        try:
            engine.compare_with_ccp(rows)
        finally:
            sde._loaded.clear()
        self.assertIn("CCP recipe says 5", rows[0].notes[0])


class VerifyTest(unittest.TestCase):
    def test_catalog_detects_new_reaction(self):
        from reactionding.verify import CHAINED
        recipes = [{"reactor": g.calculator, "name": n, "product": {"typeId": i, "name": n}}
                   for g in GROUPS.values() if g.key not in CHAINED for i, n in g.items]
        self.assertEqual(check_catalog(recipes), [])
        recipes.append({"reactor": "hybrid", "name": "New Thing", "product": {"typeId": 1, "name": "New Thing"}})
        recipes.pop(0)
        issues = check_catalog(recipes)
        self.assertEqual(sorted(i["name"] for i in issues), sorted(["New Thing", GROUPS["hybrid"].items[0][1]]))

    def test_sde_recipe_and_time(self):
        g = GROUPS["hybrid"]
        entries = []
        products, materials, times = {}, {}, {}
        for n, (item_id, name) in enumerate(g.items):
            bp = 1000 + n
            products[item_id] = (bp, 10)
            materials[bp] = {"Mat": 5}
            times[bp] = 600
            entries.append(result(item_id, name, 0, runs=4, out_qty=40,
                                  inputs=[{"id": 1, "name": "Mat", "quantity": 20}]))
        entries[0]["input"][0]["quantity"] = 100  # 25/run instead of 5
        entries[1]["runs"] = 40  # 10x too many runs for the reaction time
        entries[1]["output"]["quantity"] = 400
        entries[1]["input"][0]["quantity"] = 200
        issues = check_sde({"hybrid": {"hybrid": entries}}, (products, materials, times))
        messages = [(i["name"], i["message"]) for i in issues]
        self.assertEqual(len(messages), 2, messages)
        self.assertIn("SDE says 5/run", messages[0][1])
        self.assertIn("reaction time", messages[1][1])


if __name__ == "__main__":
    unittest.main()


class EsiSystemCheckTest(unittest.TestCase):
    def setUp(self):
        from reactionding import esi
        self.esi = esi
        self._resolve, self._index = esi.resolve_system, esi.reaction_cost_index
        esi.resolve_system = lambda name: {"ignoitton": (30002647, "Ignoitton")}.get(name.lower())
        esi.reaction_cost_index = lambda system_id: 0.1029

    def tearDown(self):
        self.esi.resolve_system, self.esi.reaction_cost_index = self._resolve, self._index

    def test_corrects_case_and_reports_index(self):
        values, notes = self.esi.check_system(settings.normalize({"system": "ignoitton"}))
        self.assertEqual(values["system"], "Ignoitton")
        self.assertIn("10.29 %", notes[-1])

    def test_unknown_system_rejected(self):
        with self.assertRaises(settings.SettingsError):
            self.esi.check_system(settings.normalize({"system": "Foobar"}))

    def test_network_error_keeps_settings(self):
        def boom(name):
            raise self.esi.EsiError("offline")
        self.esi.resolve_system = boom
        values, notes = self.esi.check_system(settings.normalize({"system": "X"}))
        self.assertEqual(values["system"], "X")
        self.assertIn("offline", notes[0])
