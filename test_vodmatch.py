"""Programa do guia que é um filme ou uma série do catálogo ganha nota e sinopse. Rodar: python3 -m unittest -v"""
import unittest

import vodmatch

P = "http://painel.example/movie/u/p"
MOVIES = [
    {"id": 0, "title": "13º Distrito", "year": 2014, "subtitled": False, "logo": "13.jpg", "group": "Filmes: Ação", "url": f"{P}/101.mp4"},
    {"id": 1, "title": "Sexta-Feira 13", "year": 1980, "subtitled": False, "logo": "", "group": "Filmes: Terror", "url": f"{P}/102.mp4"},
    {"id": 2, "title": "Sexta-Feira 13", "year": 2009, "subtitled": False, "logo": "", "group": "Filmes: Terror", "url": f"{P}/103.mp4"},
    {"id": 3, "title": "Duna", "year": 2021, "subtitled": True, "logo": "", "group": "Legendados", "url": f"{P}/104.mkv"},
    {"id": 4, "title": "Duna", "year": 2021, "subtitled": False, "logo": "duna.jpg", "group": "Filmes: Ficção", "url": f"{P}/105.mp4"},
    {"id": 5, "title": "Mama", "year": 2013, "subtitled": False, "logo": "", "group": "Filmes: Terror", "url": f"{P}/106.mp4"},
]
SHOWS = [{"id": "s1", "name": "Caôs Urbanos", "group": "SÉRIES | Nacionais", "logo": "caos.jpg", "seasonCount": 1, "episodeCount": 8}]
RATINGS = {"101": 6.6, "105": 7.8}
SERIES = {"caos urbanos": {"rating": 8.0, "plot": "Histórias da cidade.", "genre": "Documentário", "year": 2019}}


def channel(name, *programmes, groups=("Canais | Filmes e Séries",)):
    return {"id": 0, "name": name, "groups": list(groups),
            "epg": [{"title": t, "desc": "", "start": i, "stop": i + 1} for i, t in enumerate(programmes)]}


class AnnotateTest(unittest.TestCase):
    def setUp(self):
        self.index = vodmatch.build_index(MOVIES, SHOWS, RATINGS, SERIES)

    def vod(self, *programmes, **kw):
        (ch,) = vodmatch.annotate([channel("Megapix", *programmes, **kw)], self.index)
        return [p.get("vod") for p in ch["epg"]]

    def test_movie_on_air_gets_rating_year_and_what_is_needed_to_play_it(self):
        (vod,) = self.vod("13º Distrito (2014)")

        self.assertEqual((vod["kind"], vod["rating"], vod["year"], vod["url"]), ("movie", 6.6, 2014, f"{P}/101.mp4"))
        self.assertEqual((vod["title"], vod["group"], vod["logo"]), ("13º Distrito", "Filmes: Ação", "13.jpg"))

    def test_dubbed_copy_is_preferred_when_both_exist(self):
        (vod,) = self.vod("Duna")
        self.assertEqual((vod["url"], vod["rating"]), (f"{P}/105.mp4", 7.8))

    def test_same_title_with_different_years_needs_the_year_from_the_guide(self):
        self.assertEqual(self.vod("Sexta-Feira 13"), [None])
        (vod,) = self.vod("Sexta-Feira 13 (2009)")
        self.assertEqual(vod["url"], f"{P}/103.mp4")

    def test_series_episode_finds_the_show(self):
        (vod,) = self.vod("Caôs Urbanos - Caôs Urbanos - Episódio 04")

        self.assertEqual((vod["kind"], vod["showId"], vod["rating"], vod["plot"]), ("series", "s1", 8.0, "Histórias da cidade."))

    def test_only_film_and_series_channels_are_matched(self):
        (ch,) = vodmatch.annotate([channel("TV Korea", "Mama", groups=["Canais | Variedades"])], self.index)
        self.assertNotIn("vod", ch["epg"][0])
        self.assertEqual(self.vod("Mama")[0]["kind"], "movie")

    def test_unknown_programme_is_left_alone_and_input_is_not_changed(self):
        live = [channel("Megapix", "Sessão da Tarde")]

        (ch,) = vodmatch.annotate(live, self.index)

        self.assertEqual(ch["epg"], live[0]["epg"])
        self.assertNotIn("vod", live[0]["epg"][0])


if __name__ == "__main__":
    unittest.main()
