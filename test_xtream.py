"""Painel Xtream: notas e sinopses guardadas, sem passar do limite de consultas. Rodar: python3 -m unittest -v"""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import xtream

XTREAM = {"id": "x1", "url": "http://painel.example:8080/get.php?username=eu&password=segredo&type=m3u_plus"}
VOD = [{"stream_id": 101, "name": "Duna", "rating": "7.84"}, {"stream_id": 102, "name": "Sem nota", "rating": ""}]
SERIES = [{"name": "Caôs Urbanos", "rating": "8", "plot": "Histórias.", "genre": "Documentário", "releaseDate": "2019-05-01", "cast": "Fulano"}]
INFO = {"info": {"plot": "Paul Atreides se une aos Fremen.", "genre": "Ficção científica", "duration": "02:35:00",
                 "cast": "Timothée Chalamet, Zendaya", "director": "Denis Villeneuve"}}


ACCOUNT = {"user_info": {"status": "Active", "exp_date": "1800000000", "active_cons": "1", "max_connections": "1",
                         "username": "eu", "password": "segredo"}}


class FakePanel:
    def __init__(self, refuse=False):
        self.calls, self.refuse = [], refuse

    def __call__(self, url):
        self.calls.append(url)
        if self.refuse:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        if "action=" not in url:
            return ACCOUNT
        action = url.split("action=")[1].split("&")[0]
        return {"get_vod_streams": VOD, "get_series": SERIES, "get_vod_info": INFO}[action]


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class AccountTest(unittest.TestCase):
    def test_reads_server_and_login_from_the_list_link(self):
        acct = xtream.account(XTREAM)
        self.assertEqual((acct.base, acct.username, acct.password), ("http://painel.example:8080", "eu", "segredo"))

    def test_other_lists_have_no_panel(self):
        self.assertIsNone(xtream.account({"url": "https://iptv-org.github.io/iptv/countries/br.m3u"}))
        self.assertIsNone(xtream.account({"file": "lista.m3u"}))


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "cache" / "xtream-x1.json"
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def panel(self, fake):
        return xtream.Panel(xtream.account(XTREAM), self.file, fake, clock=self.clock)

    def test_whole_catalog_comes_once_a_day_and_survives_a_restart(self):
        fake = FakePanel()
        data = self.panel(fake).bulk()

        self.assertEqual(data["ratings"], {"101": 7.8})
        self.assertEqual(data["series"]["caos urbanos"], {"rating": 8.0, "plot": "Histórias.", "genre": "Documentário",
                                                          "year": 2019, "cast": "Fulano"})
        self.clock.now += 3600
        self.assertEqual(self.panel(fake).bulk()["ratings"], {"101": 7.8})
        self.assertEqual(len(fake.calls), 2)
        self.assertNotIn("segredo", self.file.read_text())

    def test_movie_synopsis_is_fetched_once_and_kept(self):
        fake = FakePanel()
        panel = self.panel(fake)

        info = panel.movie_info("101")
        self.clock.now += 120
        again = self.panel(fake).movie_info("101")

        self.assertEqual(info["plot"], "Paul Atreides se une aos Fremen.")
        self.assertEqual(again, info)
        self.assertEqual(len(fake.calls), 1)

    def test_never_more_than_a_few_calls_a_minute(self):
        fake = FakePanel()
        panel = self.panel(fake)

        answers = [panel.movie_info(str(i)) for i in range(xtream.CALLS_PER_MINUTE + 2)]

        self.assertEqual(answers[-2:], [None, None])  # ainda não: a página pede de novo depois
        self.assertEqual(len(fake.calls), xtream.CALLS_PER_MINUTE)
        self.clock.now += 61
        self.assertIsNotNone(panel.movie_info("99"))

    def test_account_shows_expiry_and_connections_without_the_login(self):
        fake = FakePanel()
        panel = self.panel(fake)

        info = panel.account_info()
        self.clock.now += 60
        panel.account_info()

        self.assertEqual(info, {"status": "Active", "expires": 1800000000, "active": 1, "max": 1})
        self.assertEqual(len(fake.calls), 1)  # guardado por uns minutos

    def test_refusal_pauses_all_calls_for_a_while(self):
        refusing = FakePanel(refuse=True)
        panel = self.panel(refusing)

        with mock.patch("builtins.print"):
            self.assertEqual(panel.bulk(), {})
        self.assertIsNone(panel.movie_info("101"))
        self.assertEqual(len(refusing.calls), 1)
        self.clock.now += xtream.BLOCKED_PAUSE + 1
        refusing.refuse = False
        self.assertEqual(panel.bulk()["ratings"], {"101": 7.8})


if __name__ == "__main__":
    unittest.main()
