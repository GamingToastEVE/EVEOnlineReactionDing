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


def priced(values, name="x", item_id=1, minutes=60):
    """Calculator-like result whose prices and market fees depend on the price methods:
    inputs 100 (buy) / 110 (sell), output 200 (sell) / 180 (buy), install taxes 5,
    broker fee 3 on bought inputs, 10 (broker + sales) or 4 (sales) on the output."""
    buy_in, sell_out = values["input"] == "buy", values["output"] == "sell"
    inputs, output = (100.0 if buy_in else 110.0), (200.0 if sell_out else 180.0)
    fee_in, fee_out = (3.0 if buy_in else 0.0), (10.0 if sell_out else 4.0)
    return {"id": item_id, "name": name, "runs": 2,
            "input": [{"id": 9, "name": "Mat", "quantity": 10, "price": inputs}],
            "output": {"id": item_id, "name": name, "quantity": 4, "price": output},
            "input_total": inputs, "output_total": output,
            "taxes": {"total": {"install": 5.0},
                      "market": {"total": {"inputs": fee_in, "output": fee_out}}},
            "profit": output - inputs - 5.0 - fee_in - fee_out,
            "cycle_data": {"total_time": minutes}}


class FakeClient:
    def __init__(self):
        self.api_calls = []
        self.web_calls = []

    def api_calculate(self, group, item_id, values):
        self.api_calls.append((group.key, item_id, values["input"], values["output"]))
        if item_id == 30303:
            raise ApiError(400, "TYPE_ID_MISMATCH", "boom")
        return priced(values, item_id=item_id)

    def web_results(self, calculator, values):
        self.web_calls.append((calculator, values["input"], values["output"]))
        pages = {}
        for g in GROUPS.values():
            if g.calculator == calculator:
                # chain tables on the page carry no id, only the name
                pages[g.web_key] = [dict(priced(values, n), id=None) for _, n in g.items]
        return pages


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

    def test_markets_are_canonical(self):
        self.assertEqual(settings.normalize({"inMarket": "amarr"})["inMarket"], "Amarr")
        with self.assertRaises(settings.SettingsError):
            settings.normalize({"outMarket": "Dodixie"})  # API would price it at 0 ISK

    def test_invalid(self):
        for bad in ({"sales": 9}, {"skill": 6}, {"facility": "small"}, {"duration": 1.5}, {"foo": 1}):
            with self.assertRaises(settings.SettingsError):
                settings.normalize(bad)

    def test_query_and_cookies(self):
        s = settings.normalize({"tax": 1})
        self.assertEqual(settings.to_query(s)["tax"], "1")
        self.assertEqual(settings.to_query(s)["sales"], "3.6")
        cookies = settings.to_cookies(s)
        self.assertEqual((cookies["indyTax"], cookies["sccTax"]), ("1", "4"))
        self.assertNotIn("tax", cookies)


class CatalogTest(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(len(GROUPS), 15)
        self.assertEqual(sum(len(g.items) for g in GROUPS.values()), 177)

    def test_chain_groups_reuse_base_ids(self):
        for chain, base in (("chain", "complex"), ("improved_chain", "improved"),
                            ("strong_chain", "strong"), ("refined", "unrefined"),
                            ("eratic_repro", "eratic")):
            self.assertEqual(GROUPS[chain].items, GROUPS[base].items)

    def test_every_web_group_documents_issue(self):
        for g in GROUPS.values():
            self.assertEqual(g.source == "web", bool(g.issue), g.key)

    def test_groups_for_and_find(self):
        self.assertEqual(len(groups_for(["biochemical"])), 7)
        self.assertEqual([g.key for g in groups_for(["eratic-repro"])], ["eratic_repro"])
        with self.assertRaises(KeyError):
            groups_for(["nope"])
        self.assertEqual({g.key for g, _, _ in find_items("30306")}, {"hybrid"})


class EngineTest(unittest.TestCase):
    def test_auto_mixes_api_and_web(self):
        client = FakeClient()
        rows = calculate(settings.normalize(), groups_for(["hybrid", "strong_chain"]), client=client)
        self.assertEqual(len(rows), 17)
        # one page request per price variant
        self.assertEqual(client.web_calls, [("biochemical", "buy", "sell"), ("biochemical", "sell", "buy")])
        hybrid = [r for r in rows if r.group.key == "hybrid"]
        self.assertTrue(all(r.source == "api" for r in hybrid))
        self.assertEqual(len(client.api_calls), 18)  # 9 reactions x 2 variants
        failed = [r for r in hybrid if not r.ok]
        self.assertEqual([r.item_id for r in failed], [30303])
        chain = [r for r in rows if r.group.key == "strong_chain"]
        self.assertTrue(all(r.ok and r.source == "web" for r in chain))
        self.assertEqual(chain[0].profit, 82.0)  # 200 - 100 - (5 + 3 + 10)
        self.assertEqual(chain[0].profit_per_hour, 82.0)
        # order follows the catalog
        self.assertEqual([r.item_id for r in hybrid], [i for i, _ in GROUPS["hybrid"].items])

    def test_buy_split_sell_combinations(self):
        rows = calculate(settings.normalize({"input": "split", "output": "split"}), ["simple"],
                         client=FakeClient())
        row = rows[0]
        # split = middle of buy and sell, for prices and market fees
        v = row.view()
        self.assertEqual((v["inputs"], v["output"], v["taxes"]), (105.0, 190.0, 5.0 + 1.5 + 7.0))
        self.assertEqual(row.profit, 190.0 - 105.0 - 13.5)
        self.assertEqual(row.view("sell", "buy")["profit"], 180.0 - 110.0 - 9.0)
        self.assertEqual(row.view("buy", "buy")["profit"], 180.0 - 100.0 - 12.0)
        self.assertEqual(row.view("sell", "sell")["profit"], 200.0 - 110.0 - 15.0)
        prices = row.unit_prices()
        self.assertEqual(prices["Mat"], {"buy": 10.0, "split": 10.5, "sell": 11.0})
        self.assertEqual(prices["x"], {"buy": 45.0, "split": 47.5, "sell": 50.0})
        data = row.to_dict(full=True)
        self.assertEqual(len(data["views"]), 9)
        self.assertEqual(data["profit"], data["views"]["split|split"]["profit"])

    def test_several_outputs(self):
        rows = calculate(settings.normalize(), ["refined"], client=FakeClient())
        row = rows[0]
        for res, factor in ((row.a, 1.0), (row.b, 0.9)):
            res["output"] = [{"name": "Vanadium", "quantity": 2, "price": 100.0 * factor},
                             {"name": "Vanadium Hafnite", "quantity": 1, "price": 100.0 * factor}]
        prices = row.unit_prices()
        self.assertEqual(prices["Vanadium"], {"buy": 45.0, "split": 47.5, "sell": 50.0})
        self.assertEqual(prices["Vanadium Hafnite"]["split"], 95.0)
        self.assertEqual(len(row.to_dict(full=True)["views"]), 9)

    def test_calculator_never_gets_split(self):
        client = FakeClient()
        calculate(settings.normalize({"input": "split", "output": "split"}), ["hybrid", "standard"],
                  client=client)
        modes = {(i, o) for *_, i, o in client.api_calls} | {(i, o) for _, i, o in client.web_calls}
        self.assertEqual(modes, {("buy", "sell"), ("sell", "buy")})

    def test_force_source(self):
        client = FakeClient()
        rows = calculate(settings.normalize(), ["strong_chain"], source="api", client=client)
        self.assertEqual(len(client.api_calls), 16)
        self.assertEqual(client.web_calls, [])
        self.assertTrue(all(r.source == "api" for r in rows))

    def test_zero_output_is_json_safe(self):
        client = FakeClient()
        rows = calculate(settings.normalize(), ["eratic"], client=client)
        rows[0].a["output_total"] = rows[0].b["output_total"] = 0.0
        self.assertIsNone(rows[0].to_dict()["profitPercent"])
        rows[0].a["profit_per"] = float("-inf")
        self.assertIsNone(rows[0].to_dict(full=True)["result"]["profit_per"])


class VerifyTest(unittest.TestCase):
    def test_catalog_detects_new_reaction(self):
        pages = FakeClient().web_results("hybrid", settings.normalize())
        pages["hybrid"].append({"name": "New Thing", "id": 1})
        issues = check_catalog({"hybrid": pages})
        self.assertEqual([i["name"] for i in issues], ["New Thing"])

    def test_sde_recipe_and_time(self):
        g = GROUPS["hybrid"]
        entries = []
        products, materials, times = {}, {}, {}
        for n, (item_id, name) in enumerate(g.items):
            bp = 1000 + n
            products[item_id] = (bp, 10)
            materials[bp] = {1: 5}
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
