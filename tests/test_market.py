import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from reactionding import market
from reactionding.esi import EsiError


class PriceCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        file = Path(self.tmp.name) / "prices.json"
        for target, value in ((market, "_cache_file"), ):
            patcher = mock.patch.object(target, value, return_value=file)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.saved = (dict(market._prices), dict(market._ids), dict(market._state))
        market._prices.clear()
        market._state.update(loaded=False, fetched=None, error=None)
        self.addCleanup(self.restore)

    def restore(self):
        market._prices.clear(); market._prices.update(self.saved[0])
        market._state.clear(); market._state.update(self.saved[2])

    def test_cached_for_15_minutes_and_kept_on_disk(self):
        calls = []
        fake = lambda t: calls.append(t) or market._complete(10.0, 12.0)  # noqa: E731
        with mock.patch.object(market, "_fetch_one", fake):
            self.assertEqual(market.jita_prices([34])[34]["split"], 11.0)
            market.jita_prices([34])
            self.assertEqual(calls, [34])  # second call from the cache
            market._prices.clear(); market._state["loaded"] = False
            market.jita_prices([34])  # after a "restart": from the disk cache
            self.assertEqual(calls, [34])
        self.assertEqual(market.CACHE_SECONDS, 900)
        self.assertLess(market.status()["age"], 5)

    def test_old_prices_used_when_esi_fails(self):
        market._state["loaded"] = True
        market._prices[34] = (time.time() - 3600, market._complete(5.0, 7.0))

        def broken(_):
            raise EsiError("down")
        with mock.patch.object(market, "_fetch_one", broken):
            self.assertEqual(market.jita_prices([34])[34]["buy"], 5.0)
            self.assertEqual(market.status()["error"], "down")
            with self.assertRaises(EsiError):
                market.jita_prices([35])  # never seen - nothing to fall back to


if __name__ == "__main__":
    unittest.main()
