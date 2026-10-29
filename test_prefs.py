"""Favoritos e "continuar assistindo" no servidor: a TV e o Mac precisam ver os mesmos. Rodar: python3 -m unittest -v"""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import prefs
import server
from test_server import serve

MOVIE = {"playlist": "p1", "kind": "movie", "url": "http://x/movie/1.mp4", "title": "Filme"}
SHOW = {"playlist": "p1", "kind": "series", "showId": "s9", "url": "http://x/series/9.mp4", "showName": "Série"}


class OperationsTest(unittest.TestCase):
    def test_favorite_is_added_once_and_removed(self):
        data = prefs.apply_op(prefs.empty(), {"op": "fav", "url": "http://a", "on": True}, at=1)
        data = prefs.apply_op(data, {"op": "fav", "url": "http://a", "on": True}, at=2)
        self.assertEqual(data["favs"], ["http://a"])

        data = prefs.apply_op(data, {"op": "fav", "url": "http://a", "on": False}, at=3)
        self.assertEqual(data["favs"], [])

    def test_progress_keeps_the_newest_videos(self):
        data = prefs.empty()
        with mock.patch.object(prefs, "MAX_PROGRESS", 2):
            for at, url in enumerate(["http://1", "http://2", "http://3"]):
                data = prefs.apply_op(data, {"op": "progress", "url": url, "t": 60, "d": 120}, at=at)

        self.assertEqual(sorted(data["progress"]), ["http://2", "http://3"])
        self.assertEqual(data["progress"]["http://3"], {"t": 60, "d": 120, "at": 2})

    def test_recent_has_one_item_per_show_newest_first(self):
        data = prefs.apply_op(prefs.empty(), {"op": "touch", "item": SHOW}, at=1)
        data = prefs.apply_op(data, {"op": "touch", "item": MOVIE}, at=2)
        data = prefs.apply_op(data, {"op": "touch", "item": {**SHOW, "url": "http://x/series/10.mp4"}}, at=3)

        self.assertEqual([r["url"] for r in data["recent"]], ["http://x/series/10.mp4", MOVIE["url"]])
        self.assertEqual(data["recent"][0]["at"], 3)

        data = prefs.apply_op(data, {"op": "forget", "key": "s9"}, at=4)
        self.assertEqual([r["url"] for r in data["recent"]], [MOVIE["url"]])

    def test_import_merges_what_each_browser_had(self):
        mine = prefs.apply_op(prefs.empty(), {"op": "fav", "url": "http://a", "on": True}, at=1)
        mine = prefs.apply_op(mine, {"op": "progress", "url": "http://v", "t": 10, "d": 100}, at=5)
        mine = prefs.apply_op(mine, {"op": "touch", "item": MOVIE}, at=5)
        tv = {
            "favs": ["http://b", "http://a"],
            "progress": {"http://v": {"t": 90, "d": 100, "at": 9}, "http://w": {"t": 1, "d": 2, "at": 1}},
            "recent": [{**SHOW, "at": 7}, {**MOVIE, "at": 2}],
        }

        data = prefs.apply_op(mine, {"op": "import", "data": tv}, at=10)

        self.assertEqual(data["favs"], ["http://a", "http://b"])
        self.assertEqual(data["progress"]["http://v"]["t"], 90)  # o mais recente vence
        self.assertIn("http://w", data["progress"])
        self.assertEqual([r.get("showId") or r["url"] for r in data["recent"]], ["s9", MOVIE["url"]])
        self.assertEqual(data["recent"][1]["at"], 5)

    def test_import_skips_malformed_leftovers(self):
        junk = {"favs": ["http://ok", 3, ""], "progress": {"http://p": {"t": "x"}}, "recent": [{"kind": "x"}, "y"]}

        data = prefs.apply_op(prefs.empty(), {"op": "import", "data": junk}, at=1)

        self.assertEqual(data, {**prefs.empty(), "favs": ["http://ok"]})

    def test_my_list_keeps_movies_and_shows_newest_first_once_each(self):
        movie = {"playlist": "p1", "section": "movie", "item": {"url": "http://x/movie/1.mp4", "title": "Duna"}}
        show = {"playlist": "p1", "section": "series", "item": {"id": "abc123", "name": "Elite"}}

        data = prefs.apply_op(prefs.empty(), {"op": "save", "entry": movie}, at=1)
        data = prefs.apply_op(data, {"op": "save", "entry": show}, at=2)
        data = prefs.apply_op(data, {"op": "save", "entry": movie}, at=3)

        self.assertEqual([(s["item"].get("title") or s["item"]["name"], s["at"]) for s in data["saved"]],
                         [("Duna", 3), ("Elite", 2)])

        data = prefs.apply_op(data, {"op": "unsave", "key": "p1|abc123"}, at=4)
        self.assertEqual([s["item"]["title"] for s in data["saved"]], ["Duna"])

    def test_importing_old_browser_data_keeps_my_list(self):
        show = {"playlist": "p1", "section": "series", "item": {"id": "abc123", "name": "Elite"}}
        data = prefs.apply_op(prefs.empty(), {"op": "save", "entry": show}, at=1)

        data = prefs.apply_op(data, {"op": "import", "data": {"favs": ["http://a"]}}, at=2)

        self.assertEqual(len(data["saved"]), 1)

    def test_bad_operations_are_refused(self):
        for op in ({"op": "nada"}, {"op": "fav", "url": ""}, {"op": "progress", "url": "http://a", "t": -1, "d": 1},
                   {"op": "touch", "item": {"kind": "movie"}}, {"op": "touch", "item": {**MOVIE, "title": "x" * 5000}},
                   {"op": "save", "entry": {"playlist": "p1", "section": "live", "item": {"url": "http://a"}}},
                   {"op": "save", "entry": {"playlist": "p1", "section": "movie", "item": {"title": "sem link"}}},
                   {"op": "save", "entry": {"playlist": "", "section": "movie", "item": {"url": "http://a"}}}, []):
            with self.subTest(op=op), self.assertRaises(ValueError):
                prefs.apply_op(prefs.empty(), op, at=1)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "prefs.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_changes_survive_a_restart(self):
        prefs.Store(self.path).apply({"op": "fav", "url": "http://a", "on": True})

        self.assertEqual(prefs.Store(self.path).read()["favs"], ["http://a"])

    def test_unreadable_file_is_set_aside_instead_of_overwritten(self):
        self.path.write_text("{quebrado")

        with mock.patch("builtins.print"):
            store = prefs.Store(self.path)
            store.apply({"op": "fav", "url": "http://a", "on": True})

        self.assertEqual(self.path.with_suffix(".json.bad").read_text(), "{quebrado")
        self.assertEqual(store.read()["favs"], ["http://a"])


class PrefsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(server, "PREFS", prefs.Store(Path(self.tmp.name) / "prefs.json"))
        self.patch.start()
        self.app = serve(server.Handler)
        self.base = f"http://127.0.0.1:{self.app.server_port}/api/prefs"

    def tearDown(self):
        self.app.shutdown()
        self.app.server_close()
        self.patch.stop()
        self.tmp.cleanup()

    def post(self, body, ctype="application/json"):
        req = urllib.request.Request(self.base, data=json.dumps(body).encode(), headers={"Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def get(self):
        with urllib.request.urlopen(self.base, timeout=5) as resp:
            return json.loads(resp.read())

    def test_one_device_saves_and_the_other_sees_it(self):
        self.assertEqual(self.post({"op": "fav", "url": "http://a", "on": True}), (200, {"ok": True}))
        self.post({"op": "touch", "item": MOVIE})

        data = self.get()

        self.assertEqual(data["favs"], ["http://a"])
        self.assertEqual(data["recent"][0]["url"], MOVIE["url"])

    def test_large_import_from_an_old_browser_fits(self):
        progress = {f"http://x/movie/{i}.mp4": {"t": 1, "d": 2, "at": i} for i in range(400)}

        status, _ = self.post({"op": "import", "data": {"favs": [], "progress": progress, "recent": []}})

        self.assertEqual(status, 200)
        self.assertEqual(len(self.get()["progress"]), 400)

    def test_bad_operation_is_400(self):
        status, body = self.post({"op": "nada"})

        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_other_sites_cannot_post_a_simple_form(self):
        status, _ = self.post({"op": "fav", "url": "http://a", "on": True}, ctype="text/plain")

        self.assertEqual(status, 400)
        self.assertEqual(self.get()["favs"], [])


if __name__ == "__main__":
    unittest.main()
