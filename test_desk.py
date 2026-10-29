"""Área de trabalho: tempo, câmbio, foguetes e manchetes, guardados e sem derrubar o resto quando uma fonte cai.
Rodar: python3 -m unittest -v"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import desk

PLACE = {"status": "success", "city": "João Pessoa", "region": "PB", "lat": -7.12, "lon": -34.86, "timezone": "America/Fortaleza"}
WEATHER = {
    "current": {"time": "2026-10-29T16:00", "temperature_2m": 27.4, "apparent_temperature": 30.1, "relative_humidity_2m": 70,
                "weather_code": 2, "wind_speed_10m": 18.2, "is_day": 1},
    "hourly": {"time": [f"2026-10-29T{h:02d}:00" for h in range(24)] + [f"2026-10-30T{h:02d}:00" for h in range(24)],
               "temperature_2m": list(range(48)), "weather_code": [61] * 48, "precipitation_probability": [40] * 48, "is_day": [1] * 48},
    "daily": {"time": ["2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"], "weather_code": [2, 61, 95, 0],
              "temperature_2m_max": [31.0, 29.5, 28.0, 30.2], "temperature_2m_min": [24.0, 23.1, 22.8, 23.9],
              "precipitation_probability_max": [10, 70, 90, 0]},
}
MARKETS = {"USDBRL": {"code": "USD", "name": "Dólar Americano/Real Brasileiro", "bid": "5.4061", "pctChange": "1.12"},
           "BTCBRL": {"code": "BTC", "name": "Bitcoin/Real Brasileiro", "bid": "436723", "pctChange": "-0.56"}}
LAUNCHES = {"results": [
    {"name": "Falcon 9 Block 5 | Starlink Group 15-18", "net": "2026-10-28T21:30:00Z", "pad": "SLC-4E", "location": "Vandenberg SFB, CA, USA",
     "status": {"abbrev": "Success"}},
    {"name": "GSLV Mk II | IRNSS-1L (NVS-03)", "net": "2026-10-30T18:21:00Z", "pad": "Second Launch Pad", "location": "Sriharikota, India",
     "status": {"abbrev": "Go"}},
]}
NEWS_IDS = [11, 12, 13, 14, 15, 16]
B3 = {"BizSts": {"cd": "OK"}, "Msg": {"dtTm": "2026-10-29 16:31:04"},
      "Trad": [{"scty": {"SctyQtn": {"curPrc": 169691.16, "prcFlcn": -0.7712}, "symb": "IBOV", "desc": "IBOVESPA"}}]}
NEWS_ITEM = {"title": "Show HN: Um player de IPTV no Chrome 79", "score": 321, "url": "https://example.com/post"}
NOW = 1_793_294_400  # 29/10/2026 14:20 em Fortaleza: depois do Falcon 9, antes do GSLV


class Web:
    """Respostas falsas por pedaço da URL; 'down' faz a fonte falhar."""

    def __init__(self, down=()):
        self.calls, self.down = [], set(down)

    def __call__(self, url):
        self.calls.append(url)
        for key, answer in (("ip-api", PLACE), ("open-meteo", WEATHER), ("awesomeapi", MARKETS), ("thespacedevs", LAUNCHES),
                            ("topstories", NEWS_IDS), ("item/", NEWS_ITEM), ("cotacao.b3", B3)):
            if key in url:
                if key in self.down:
                    raise OSError("fora do ar")
                return answer
        raise AssertionError(url)


class DeskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "desk.json"
        self.now = NOW

    def tearDown(self):
        self.tmp.cleanup()

    def desk(self, web):
        return desk.Desk(web, self.file, clock=lambda: self.now)

    def test_everything_comes_ready_for_the_screen(self):
        data = self.desk(Web()).snapshot()

        self.assertEqual(data["place"], {"city": "João Pessoa", "region": "PB", "lat": -7.12, "lon": -34.86, "tz": "America/Fortaleza"})
        now = data["weather"]["now"]
        self.assertEqual((now["temp"], now["feels"], now["code"], now["day"]), (27, 30, 2, True))
        self.assertEqual([h["hour"] for h in data["weather"]["hours"]], ["19:00", "22:00", "01:00", "04:00"])
        self.assertEqual([(d["date"], d["max"], d["min"], d["rain"]) for d in data["weather"]["days"]],
                         [("2026-10-30", 30, 23, 70), ("2026-10-31", 28, 23, 90), ("2026-11-01", 30, 24, 0)])
        self.assertEqual(data["markets"][0], {"code": "USD", "name": "Dólar", "value": 5.4061, "change": 1.12})
        self.assertEqual([b["symbol"] for b in data["b3"]], ["IBOV", "PETR4", "VALE3", "ITUB4"])
        self.assertEqual(data["b3"][0], {"symbol": "IBOV", "name": "Ibovespa", "value": 169691.16, "change": -0.77, "at": "16:31"})
        self.assertEqual(data["launch"]["rocket"], "GSLV Mk II")  # o que já subiu não conta
        self.assertEqual(data["launch"]["mission"], "IRNSS-1L (NVS-03)")
        self.assertEqual(len(data["news"]), 5)
        self.assertEqual(data["news"][0], {"title": NEWS_ITEM["title"], "score": 321, "site": "example.com"})

    def test_each_source_is_asked_again_only_after_its_time(self):
        web = Web()
        d = self.desk(web)
        d.snapshot()
        first = len(web.calls)

        self.now += 60
        d.snapshot()
        self.assertEqual(len(web.calls), first)
        self.now += desk.TTL["markets"]
        d.snapshot()
        self.assertEqual(sum("awesomeapi" in u for u in web.calls), 2)

    def test_a_source_that_is_down_leaves_only_its_window_empty(self):
        with mock.patch("builtins.print"):
            data = self.desk(Web(down={"open-meteo", "thespacedevs"})).snapshot()

        self.assertIsNone(data["weather"])
        self.assertIsNone(data["launch"])
        self.assertEqual(data["markets"][0]["code"], "USD")

    def test_last_good_answer_stays_when_a_source_goes_down(self):
        web = Web()
        d = self.desk(web)
        d.snapshot()

        web.down.add("awesomeapi")
        self.now += desk.TTL["markets"] + 1
        with mock.patch("builtins.print"):
            self.assertEqual(d.snapshot()["markets"][0]["code"], "USD")

    def test_place_is_remembered_across_restarts(self):
        self.desk(Web()).snapshot()
        web = Web()

        self.desk(web).snapshot()

        self.assertFalse(any("ip-api" in u for u in web.calls))


class GreetingTest(unittest.TestCase):
    def test_name_comes_from_the_mac_account(self):
        with mock.patch("getpass.getuser", return_value="matheus"):
            self.assertEqual(desk.owner_name(), "Matheus")


if __name__ == "__main__":
    unittest.main()
