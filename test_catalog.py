"""Testes da organização da playlist em ao vivo, filmes e séries. Rodar: python3 -m unittest -v"""
import unittest

import catalog

BASE = "http://painel.example:80"


def item(name, group, path, logo=""):
    return {"name": name, "group": group, "url": f"{BASE}{path}", "logo": logo, "tvgId": "", "id": 0}


class KindOfTest(unittest.TestCase):
    def test_classifies_xtream_paths_and_plain_files(self):
        self.assertEqual(catalog.kind_of(f"{BASE}/live/u/p/1.m3u8"), "live")
        self.assertEqual(catalog.kind_of(f"{BASE}/movie/u/p/2.mkv"), "movie")
        self.assertEqual(catalog.kind_of(f"{BASE}/series/u/p/3.mp4"), "series")
        self.assertEqual(catalog.kind_of("https://cdn.example/filme.mp4?token=1"), "movie")
        self.assertEqual(catalog.kind_of("https://cdn.example/canal/index.m3u8"), "live")
        self.assertEqual(catalog.kind_of("http://1.2.3.4:8080/canal"), "live")


class SplitTitleTest(unittest.TestCase):
    def test_extracts_year_in_parentheses(self):
        self.assertEqual(catalog.split_title("Codigo: Vingança (2026)"), ("Codigo: Vingança", 2026, False))

    def test_extracts_dashed_year_and_subtitled_marker(self):
        self.assertEqual(catalog.split_title("Die in a Gunfight - 2021 [L]"), ("Die in a Gunfight", 2021, True))

    def test_subtitled_marker_in_parentheses(self):
        self.assertEqual(catalog.split_title("The soul (2021) (L)"), ("The soul", 2021, True))

    def test_keeps_numbers_that_are_part_of_the_title(self):
        self.assertEqual(catalog.split_title("1917"), ("1917", None, False))
        self.assertEqual(catalog.split_title("Blade Runner 2049"), ("Blade Runner 2049", None, False))


class BuildCatalogTest(unittest.TestCase):
    def setUp(self):
        self.channels = [
            item("Globo SP", "Canais | Globos", "/live/u/p/10.m3u8"),
            item("Band", "Canais | Abertos", "/live/u/p/11.m3u8"),
            item("Codigo: Vingança (2026)", "Filmes: Lancamentos", "/movie/u/p/20.mp4"),
            item("Elite S01 Elite - S01E02 - Desejo", "SÉRIES | Crime", "/series/u/p/31.mp4", "elite-b.jpg"),
            item("Elite S01 Elite - S01E01 - Bem-vindos", "SÉRIES | Crime", "/series/u/p/30.mp4", "elite.jpg"),
            item("Elite S02 Episódio 1", "SÉRIES | Crime", "/series/u/p/32.mp4", "elite.jpg"),
            item("Parte 2", "SÉRIES | Crime", "/series/u/p/33.mp4"),
            item("3%", "SÉRIES | Netflix", "/series/u/p/40.mp4", "3.jpg"),
        ]
        self.cat = catalog.build_catalog(self.channels, epg_for=lambda name: [name])

    def test_live_channels_are_numbered_in_playlist_order_with_guide(self):
        self.assertEqual([(c["num"], c["name"], c["epg"]) for c in self.cat.live],
                         [(1, "Globo SP", ["Globo SP"]), (2, "Band", ["Band"])])

    def test_movies_get_clean_title_and_year(self):
        (movie,) = self.cat.movies
        self.assertEqual((movie["title"], movie["year"], movie["subtitled"]), ("Codigo: Vingança", 2026, False))

    def test_episodes_are_grouped_by_show_and_season_in_episode_order(self):
        elite = next(s for s in self.cat.shows if s["name"] == "Elite")
        detail = catalog.show_detail(self.cat, elite["id"])

        self.assertEqual((elite["seasonCount"], elite["episodeCount"], elite["logo"]), (2, 4, "elite.jpg"))
        self.assertEqual([(e["num"], e["title"]) for e in detail["seasons"][0]["episodes"]],
                         [(1, "Bem-vindos"), (2, "Desejo")])

    def test_episode_without_season_marker_joins_the_previous_show(self):
        elite = next(s for s in self.cat.shows if s["name"] == "Elite")
        season2 = catalog.show_detail(self.cat, elite["id"])["seasons"][1]

        self.assertEqual(season2["number"], 2)
        self.assertEqual([(e["num"], e["title"]) for e in season2["episodes"]],
                         [(1, "Episódio 1"), (2, "Parte 2")])

    def test_lone_item_without_previous_show_becomes_its_own_show(self):
        lone = next(s for s in self.cat.shows if s["group"] == "SÉRIES | Netflix")
        self.assertEqual((lone["name"], lone["episodeCount"]), ("3%", 1))

    def test_show_ids_are_stable_and_scoped_by_category(self):
        again = catalog.build_catalog(self.channels)
        self.assertEqual([s["id"] for s in again.shows], [s["id"] for s in self.cat.shows])
        moved = catalog.build_catalog([{**self.channels[4], "group": "SÉRIES | Netflix"}])
        self.assertNotEqual(moved.shows[0]["id"], self.cat.shows[0]["id"])

    def test_unknown_show_raises_key_error(self):
        with self.assertRaises(KeyError):
            catalog.show_detail(self.cat, "nao-existe")

    def test_summary_counts_categories_in_playlist_order(self):
        summary = catalog.summary(self.cat)

        self.assertEqual(summary["live"]["groups"],
                         [{"name": "Canais | Globos", "count": 1}, {"name": "Canais | Abertos", "count": 1}])
        self.assertEqual((summary["series"]["count"], summary["series"]["episodes"]), (2, 5))
        self.assertEqual(summary["movie"]["count"], 1)


class LiveVersionsTest(unittest.TestCase):
    """'A&E FHD', 'A&E FHD [Alt]', 'A&E HD', 'A&E SD' são o mesmo canal: uma linha, e o CH± passa por ele uma vez."""

    def live(self, *rows, epg_for=lambda name: []):
        channels = [item(name, group, f"/live/u/p/{i}.m3u8") for i, (name, group) in enumerate(rows)]
        return catalog.build_catalog(channels, epg_for=epg_for).live

    def test_versions_become_one_channel_with_the_best_first(self):
        live = self.live(("A&E HD", "Canais | Variedades"), ("A&E SD", "Canais | Variedades"),
                         ("A&E FHD [Alt]", "Canais | Variedades"), ("A&E FHD", "Canais | Variedades"),
                         ("AMC FHD", "Canais | Filmes"))

        self.assertEqual([(c["num"], c["name"]) for c in live], [(1, "A&E"), (2, "AMC")])
        self.assertEqual([v["label"] for v in live[0]["variants"]], ["FHD", "FHD Alt", "HD", "SD"])
        self.assertEqual(live[0]["url"], f"{BASE}/live/u/p/3.m3u8")
        self.assertEqual(live[0]["url"], live[0]["variants"][0]["url"])

    def test_h265_versions_are_left_out_because_the_player_cannot_read_them(self):
        live = self.live(("A&E FHD [H265]", "Canais | 4K - H265"), ("A&E HD", "Canais | Variedades"),
                         ("Discovery 4K", "Canais | 4K - H265"))

        self.assertEqual([(c["name"], [v["label"] for v in c["variants"]]) for c in live], [("A&E", ["HD"])])

    def test_channel_stays_in_every_category_of_its_versions(self):
        live = self.live(("Polishop FHD", "Canais | Variedades"), ("Polishop HD", "Canais | Abertos"))
        summary = catalog.summary(catalog.Catalog(live, [], [], {}))

        self.assertEqual(live[0]["groups"], ["Canais | Variedades", "Canais | Abertos"])
        self.assertEqual(live[0]["group"], "Canais | Variedades")
        self.assertEqual(summary["live"]["groups"],
                         [{"name": "Canais | Variedades", "count": 1}, {"name": "Canais | Abertos", "count": 1}])

    def test_names_lose_resolution_and_availability_notes(self):
        live = self.live(("Band (720p) [Not 24/7]", "News"), ("Arte 1 (1080p) [Geo-blocked]", "Culture"),
                         ("[24H] Os Ursinhos Gummi", "24 Horas"), ("A Fazenda [Cam 01]", "Reality"),
                         ("A Fazenda [Cam 02]", "Reality"), ("Record (720p)", "General"), ("Record (1080p)", "General"))

        self.assertEqual([c["name"] for c in live],
                         ["Band", "Arte 1", "Os Ursinhos Gummi", "A Fazenda [Cam 01]", "A Fazenda [Cam 02]", "Record"])
        self.assertEqual([v["label"] for v in live[-1]["variants"]], ["1080p", "720p"])

    def test_same_name_twice_gets_numbered_versions(self):
        live = self.live(("ESPN", "Canais | Esportes"), ("ESPN", "Canais | ESPN"), ("ESPN HD", "Canais | ESPN"))

        self.assertEqual([v["label"] for v in live[0]["variants"]], ["Versão 1", "Versão 2", "HD"])

    def test_guide_comes_from_any_version_that_has_one(self):
        live = self.live(("Globo FHD", "Canais | Globos"), ("Globo HD", "Canais | Globos"),
                         epg_for=lambda name: ["Jornal"] if name == "Globo HD" else [])

        self.assertEqual(live[0]["epg"], ["Jornal"])


class BrowseTest(unittest.TestCase):
    def setUp(self):
        names = ["Duna (2021)", "A Volta de Duna (2024)", "Vingança Sombria (2020)", "Dunkirk (2017)"]
        self.movies = catalog.build_catalog(
            [item(n, "Filmes: Ação" if i % 2 else "Filmes: Drama", f"/movie/u/p/{i}.mp4") for i, n in enumerate(names)]
        ).movies

    def test_search_ignores_accents_and_case(self):
        page = catalog.browse(self.movies, query="VINGANCA")
        self.assertEqual([m["title"] for m in page["items"]], ["Vingança Sombria"])

    def test_titles_starting_with_the_search_come_first(self):
        page = catalog.browse(self.movies, query="duna")
        self.assertEqual([m["title"] for m in page["items"]], ["Duna", "A Volta de Duna"])

    def test_filters_by_category_and_paginates(self):
        page = catalog.browse(self.movies, group="Filmes: Ação", offset=1, limit=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual([m["title"] for m in page["items"]], ["Dunkirk"])

    def test_items_do_not_leak_internal_search_key(self):
        page = catalog.browse(self.movies)
        self.assertNotIn("key", page["items"][0])


if __name__ == "__main__":
    unittest.main()
