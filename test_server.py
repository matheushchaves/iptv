"""Testes do servidor: proxy, leitura de M3U e guia, API do catálogo. Rodar: python3 -m unittest -v"""
import http.client
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock
from urllib.parse import quote
from xml.sax.saxutils import escape

import server

PAYLOAD = bytes(range(256)) * 40  # 10 KB


class FakeXtream(BaseHTTPRequestHandler):
    """Imita o painel: redireciona para a CDN, que serve o arquivo com suporte a Range."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/live/eu/segredo/9.m3u8":  # painel recusando (limite de conexões, por exemplo)
            self.send_response(403)
            self.end_headers()
            return
        if self.path == "/movie/1.mp4":
            self.send_response(302)
            self.send_header("Location", "/play/1.mp4")
            self.end_headers()
            return
        rng = self.headers.get("Range")
        if rng:
            start, end = rng.removeprefix("bytes=").split("-")
            start, end = int(start), int(end) if end else len(PAYLOAD) - 1
            body = PAYLOAD[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(PAYLOAD)}")
        else:
            body = PAYLOAD
            self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        # O servidor real manda "0-<tamanho>" em vez de "bytes"
        self.send_header("Accept-Ranges", f"0-{len(PAYLOAD) - 1}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakeLiveCdn(BaseHTTPRequestHandler):
    """Pedaços do ao vivo sem tamanho anunciado (chunked); /cut.ts cai na metade, como o painel faz às vezes."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "video/mp2t")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        half = len(PAYLOAD) // 2
        for part in (PAYLOAD[:half], PAYLOAD[half:]):
            self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
            if self.path == "/cut.ts":
                self.close_connection = True
                return
        self.wfile.write(b"0\r\n\r\n")


def serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class ProxyVodTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = serve(FakeXtream)
        cls.app = serve(server.Handler)
        movie = f"http://127.0.0.1:{cls.upstream.server_port}/movie/1.mp4"
        cls.proxy_url = f"http://127.0.0.1:{cls.app.server_port}/proxy?u=" + quote(movie, safe="")

    @classmethod
    def tearDownClass(cls):
        for httpd in (cls.upstream, cls.app):
            httpd.shutdown()
            httpd.server_close()

    def get(self, headers=None):
        req = urllib.request.Request(self.proxy_url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()

    def test_forwards_range_and_returns_partial_content(self):
        status, headers, body = self.get({"Range": "bytes=100-199"})

        self.assertEqual(status, 206)
        self.assertEqual(headers["Content-Range"], f"bytes 100-199/{len(PAYLOAD)}")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(body, PAYLOAD[100:200])

    def test_open_ended_range_returns_rest_of_file(self):
        status, _, body = self.get({"Range": "bytes=10000-"})

        self.assertEqual(status, 206)
        self.assertEqual(body, PAYLOAD[10000:])

    def test_without_range_returns_whole_file_and_advertises_seeking(self):
        status, headers, body = self.get()

        self.assertEqual(status, 200)
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(body, PAYLOAD)


class ProxyLiveSegmentTest(unittest.TestCase):
    """Pedaço cortado não pode chegar ao player como se estivesse inteiro: ele tapa o buraco e o áudio fica robotizado."""

    @classmethod
    def setUpClass(cls):
        cls.upstream = serve(FakeLiveCdn)
        cls.app = serve(server.Handler)

    @classmethod
    def tearDownClass(cls):
        for httpd in (cls.upstream, cls.app):
            httpd.shutdown()
            httpd.server_close()

    def read(self, name):
        url = f"http://127.0.0.1:{self.upstream.server_port}/{name}"
        with urllib.request.urlopen(f"http://127.0.0.1:{self.app.server_port}/proxy?u={quote(url, safe='')}", timeout=5) as resp:
            return resp.read()

    def test_segment_without_length_arrives_whole(self):
        self.assertEqual(self.read("seg.ts"), PAYLOAD)

    def test_segment_cut_upstream_reaches_the_player_as_an_error(self):
        with mock.patch.object(server, "log") as log, self.assertRaises(http.client.IncompleteRead):
            self.read("cut.ts")

        self.assertIn("parou no meio", log.call_args[0][0])


class FailureLogTest(unittest.TestCase):
    """Na TV não há console: o que deu errado com o vídeo precisa ficar no log do servidor (sem a senha do painel)."""

    @classmethod
    def setUpClass(cls):
        cls.upstream = serve(FakeXtream)
        cls.app = serve(server.Handler)
        cls.base = f"http://127.0.0.1:{cls.app.server_port}"

    @classmethod
    def tearDownClass(cls):
        for httpd in (cls.upstream, cls.app):
            httpd.shutdown()
            httpd.server_close()

    def proxy_status(self, url):
        try:
            with urllib.request.urlopen(f"{self.base}/proxy?u={quote(url, safe='')}", timeout=5) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def assert_logged_without_credentials(self, log, *expected):
        line = " ".join(str(c.args[0]) for c in log.call_args_list)
        for text in expected:
            self.assertIn(text, line)
        self.assertNotIn("segredo", line)
        self.assertNotIn("/eu/", line)

    def test_upstream_refusal_is_logged_and_still_retryable(self):
        url = f"http://127.0.0.1:{self.upstream.server_port}/live/eu/segredo/9.m3u8"
        with mock.patch.object(server, "log") as log:
            status = self.proxy_status(url)

        self.assertEqual(status, 502)  # 4xx o hls.js nem tenta de novo; 502 ele tenta
        self.assert_logged_without_credentials(log, "403", "9.m3u8")

    def test_unreachable_upstream_is_logged(self):
        with mock.patch.object(server, "log") as log:
            status = self.proxy_status("http://127.0.0.1:9/live/eu/segredo/9.m3u8")

        self.assertEqual(status, 502)
        self.assert_logged_without_credentials(log, "9.m3u8")

    def test_player_errors_reported_by_the_page_are_logged(self):
        body = json.dumps({"msg": "12 Globo News: networkError/levelLoadError " + "x" * 1000}).encode()
        req = urllib.request.Request(f"{self.base}/api/log", data=body, headers={"Content-Type": "application/json"})
        with mock.patch.object(server, "log") as log:
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)

        line = log.call_args[0][0]
        self.assertIn("12 Globo News: networkError/levelLoadError", line)
        self.assertLess(len(line), 400)


class ParseM3uTest(unittest.TestCase):
    def test_keeps_commas_in_the_display_name(self):
        text = ('#EXTM3U\n#EXTINF:-1 tvg-name="x" group-title="SÉRIES | Animes",'
                'Pokémon S01 Pokémon - S01E01 - Pokémon, Eu Escolho Você!\nhttp://a/series/1.mp4\n')

        (ch,) = server.parse_m3u(text)

        self.assertEqual(ch["name"], "Pokémon S01 Pokémon - S01E01 - Pokémon, Eu Escolho Você!")
        self.assertEqual(ch["group"], "SÉRIES | Animes")

    def test_commas_inside_attributes_do_not_split_the_name(self):
        text = '#EXTINF:-1 group-title="Filmes, Drama" tvg-logo="http://l/a,b.png",Duna (2021)\nhttp://a/movie/2.mp4\n'

        (ch,) = server.parse_m3u(text)

        self.assertEqual((ch["name"], ch["group"], ch["logo"]), ("Duna (2021)", "Filmes, Drama", "http://l/a,b.png"))


BRT = timezone(timedelta(hours=-3))
SHANGHAI = timezone(timedelta(hours=8))


def epg_xml(*programmes):
    body = "".join(f'<programme start="{s}" stop="{e}" channel="1"><title>{t}</title></programme>'
                   for s, e, t in programmes)
    return io.BytesIO(f'<tv><channel id="1"><display-name>GloboNews</display-name></channel>{body}</tv>'.encode())


def brt_ms(*args):
    return int(datetime(*args, tzinfo=BRT).timestamp() * 1000)


class ParseEpgTest(unittest.TestCase):
    NOW = datetime(2026, 10, 27, 22, 46, tzinfo=BRT)  # J10 no ar, conferido na tela da Globo News

    def parse(self, raw, real_tz=None):
        out = io.StringIO()
        with redirect_stdout(out):
            guide = server.parse_epg(raw, real_tz=real_tz, now=self.NOW, source="teste")
        return guide.programmes, out.getvalue()

    def test_utc_label_is_read_in_the_real_timezone_of_the_source(self):
        # epg.pw: Estúdio i (13h em Brasília) vem como 00:00 "+0000"; J10 (22h) como 09:00 "+0000"
        raw = epg_xml(("20261028000000 +0000", "20261028030000 +0000", "Estúdio i"),
                      ("20261028090000 +0000", "20261028103000 +0000", "Jornal das Dez"))

        progs, log = self.parse(raw, real_tz=SHANGHAI)

        self.assertEqual([(p["title"], p["start"], p["stop"]) for p in progs["globonews"]],
                         [("Jornal das Dez", brt_ms(2026, 10, 27, 22, 0), brt_ms(2026, 10, 27, 23, 30))])
        self.assertEqual(log, "")

    def test_explicit_offset_is_never_reinterpreted(self):
        raw = epg_xml(("20261027220000 -0300", "20261027233000 -0300", "Jornal das Dez"))

        progs, _ = self.parse(raw, real_tz=SHANGHAI)

        self.assertEqual(progs["globonews"][0]["start"], brt_ms(2026, 10, 27, 22, 0))

    def test_sources_without_correction_keep_utc(self):
        raw = epg_xml(("20261028010000 +0000", "20261028023000 +0000", "Jornal das Dez"))

        progs, _ = self.parse(raw)

        self.assertEqual(progs["globonews"][0]["start"], brt_ms(2026, 10, 27, 22, 0))

    def test_same_programme_from_regional_copies_of_a_channel_appears_once(self):
        programme = '<programme start="{}" stop="{}" channel="{}"><title>{}</title></programme>'
        raw = io.BytesIO((
            '<tv><channel id="1"><display-name>São Paulo/SP Record News</display-name></channel>'
            '<channel id="2"><display-name>Record News</display-name></channel>'
            + programme.format("20261028013000 +0000", "20261028020000 +0000", 1, "Mulheres Positivas")
            + programme.format("20261028013000 +0000", "20261028020000 +0000", 2, "Mulheres Positivas")
            + programme.format("20261028020000 +0000", "20261028030000 +0000", 2, "Record News Rural")
            + "</tv>").encode())

        progs, _ = self.parse(raw)

        self.assertEqual([p["title"] for p in progs["recordnews"]], ["Mulheres Positivas", "Record News Rural"])

    def test_warns_when_source_stops_starting_at_local_midnight(self):
        # Se a epg.pw passar a gravar UTC de verdade, o arquivo começa às 16:00 "+0000" (meia-noite em Xangai)
        raw = epg_xml(("20261027160000 +0000", "20261027190000 +0000", "Estúdio i"))

        _, log = self.parse(raw, real_tz=SHANGHAI)

        self.assertIn("teste", log)
        self.assertIn("fuso", log)


class ChannelNameTest(unittest.TestCase):
    def test_different_channels_get_different_keys(self):
        self.assertNotEqual(server.norm("Rede TV HD"), server.norm("Rede Brasil HD"))
        self.assertNotEqual(server.norm("HBO+ FHD"), server.norm("HBO 4K"))
        self.assertNotEqual(server.norm("TV Cultura FHD"), server.norm("Cultura"))

    def test_quality_markers_and_spelling_do_not_matter(self):
        self.assertEqual(server.norm("Band (720p)"), server.norm("Band HD"))
        self.assertEqual(server.norm("Music Box Brazil FHD [H265]"), server.norm("Music Box Brasil"))
        self.assertEqual(server.norm("HBO+ FHD [Alt]"), server.norm("HBO Plus"))

    def test_generic_words_are_kept(self):
        self.assertEqual(server.norm("TV Brasil FHD"), "tvbrasil")


class GuideMatchTest(unittest.TestCase):
    NOW = datetime(2026, 10, 27, 22, 46, tzinfo=BRT)

    def guide(self, channels):
        """channels: [(nome no guia, título no ar ou None para canal sem programação)]."""
        xml = "".join(f'<channel id="{i}"><display-name>{escape(name)}</display-name></channel>' for i, (name, _) in enumerate(channels))
        xml += "".join(f'<programme start="20261028013000 +0000" stop="20261028020000 +0000" channel="{i}"><title>{escape(title)}</title></programme>'
                       for i, (_, title) in enumerate(channels) if title)
        return server.parse_epg(io.BytesIO(f"<tv>{xml}</tv>".encode()), now=self.NOW)

    def titles(self, guide, name):
        return [p["title"] for p in guide.for_channel(name)]

    def test_similar_names_keep_their_own_guide(self):
        g = self.guide([("São Paulo/SP Rede TV", "A Tarde é Sua"), ("Rede Brasil HD", "Culto")])

        self.assertEqual(self.titles(g, "Rede TV FHD"), ["A Tarde é Sua"])
        self.assertEqual(self.titles(g, "Rede Brasil SD"), ["Culto"])

    def test_generic_words_are_ignored_only_when_unambiguous(self):
        g = self.guide([("Sony", "Seinfeld"), ("Sony Movies Brazil", "Filme"),
                        ("Cultura", "Roda Viva"), ("TV Cultura", "Roda Viva")])

        self.assertEqual(self.titles(g, "Canal Sony HD"), ["Seinfeld"])
        self.assertEqual(self.titles(g, "Canal Cultura"), [])  # "Cultura" ou "TV Cultura"? não chuta

    def test_channel_without_schedule_is_not_a_candidate(self):
        g = self.guide([("Universal Channel", "Law & Order"), ("São Paulo/SP Universal TV", None)])
        self.assertEqual(self.titles(g, "Universal Channel TV FHD"), ["Law & Order"])

    def test_known_channel_without_schedule_never_borrows_another_guide(self):
        g = self.guide([("Rede TV", None), ("Rede Brasil", "Culto")])
        self.assertEqual(self.titles(g, "Rede TV HD"), [])

    def test_known_channel_without_schedule_borrows_same_name_plus_generic_word(self):
        g = self.guide([("São Paulo/SP Record", None), ("Record TV", "Cidade Alerta")])
        self.assertEqual(self.titles(g, "Record FHD [Alt]"), ["Cidade Alerta"])


PLAYLIST = """#EXTM3U
#EXTINF:-1 group-title="Canais | Abertos",Band
http://p/live/u/s/1.m3u8
#EXTINF:-1 group-title="Filmes: Drama",Duna (2021)
http://p/movie/u/s/2.mp4
#EXTINF:-1 group-title="Filmes: Ação",Vingança Sombria (2020)
http://p/movie/u/s/3.mp4
#EXTINF:-1 group-title="SÉRIES | Crime" tvg-logo="elite.jpg",Elite S01 Elite - S01E01 - Bem-vindos
http://p/series/u/s/4.mp4
"""


class CatalogApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "t1.m3u").write_text(PLAYLIST)
        (root / "playlists.json").write_text(json.dumps([
            {"id": "t1", "name": "Teste", "file": "t1.m3u"},
            {"id": "x1", "name": "Painel", "url": "http://painel.example:8080/get.php?username=eu&password=segredo"},
        ]))
        (root / "static" / "js").mkdir(parents=True)
        (root / "static" / "js" / "main.js").write_text("export {};")
        cls.patches = [
            mock.patch.object(server, "PLAYLISTS_FILE", root / "playlists.json"),
            mock.patch.object(server, "UPLOADS_DIR", root),
            mock.patch.object(server, "STATIC_DIR", root / "static"),
            mock.patch.object(server, "load_epg", lambda: server.EMPTY_GUIDE),
            mock.patch.object(server, "CACHE_DIR", root / "cache"),
            mock.patch.dict(server._catalog_cache, clear=True),
            mock.patch.dict(server._panels, clear=True),
            mock.patch.object(server, "_desk", []),
        ]
        for p in cls.patches:
            p.start()
        cls.app = serve(server.Handler)
        cls.base = f"http://127.0.0.1:{cls.app.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.app.server_close()
        for p in reversed(cls.patches):
            p.stop()
        cls.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as resp:
                return resp.status, resp.headers.get("Content-Type"), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Content-Type"), exc.read()

    def get_json(self, path):
        status, _, body = self.get(path)
        return status, json.loads(body)

    def test_catalog_summarizes_each_section(self):
        status, data = self.get_json("/api/catalog?playlist=t1")

        self.assertEqual(status, 200)
        self.assertEqual((data["live"]["count"], data["movie"]["count"], data["series"]["count"]), (1, 2, 1))

    def test_saved_lists_show_the_server_but_not_the_password(self):
        status, _, body = self.get("/api/playlists")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [{"id": "t1", "name": "Teste", "source": "Arquivo local"},
                                            {"id": "x1", "name": "Painel", "source": "painel.example"}])
        self.assertNotIn(b"segredo", body)

    def test_movie_synopsis_needs_a_numeric_id_and_a_list_with_panel(self):
        self.assertEqual(self.get_json("/api/vodinfo?playlist=x1&id=abc")[0], 400)
        self.assertEqual(self.get_json("/api/vodinfo?playlist=t1&id=101")[0], 404)

    def test_movie_synopsis_is_pending_while_the_panel_cannot_answer(self):
        with mock.patch.object(server, "fetch", side_effect=OSError("sem rede")), mock.patch("builtins.print"):
            status, data = self.get_json("/api/vodinfo?playlist=x1&id=101")

        self.assertEqual((status, data), (202, {"pending": True}))

    def test_desk_answers_even_with_every_source_down(self):
        with mock.patch.object(server, "fetch", side_effect=OSError("sem rede")), mock.patch("builtins.print"):
            status, data = self.get_json("/api/desk?playlist=t1")

        self.assertEqual(status, 200)
        self.assertEqual({k: data[k] for k in ("weather", "markets", "launch", "news", "account")},
                         {"weather": None, "markets": None, "launch": None, "news": None, "account": None})
        self.assertIn("name", data)

    def test_live_lists_numbered_channels(self):
        _, data = self.get_json("/api/live?playlist=t1")
        self.assertEqual([(c["num"], c["name"]) for c in data], [(1, "Band")])

    def test_browse_searches_movies(self):
        status, data = self.get_json("/api/browse?playlist=t1&kind=movie&q=vinganca")

        self.assertEqual(status, 200)
        self.assertEqual([m["title"] for m in data["items"]], ["Vingança Sombria"])

    def test_browse_rejects_unknown_section(self):
        status, data = self.get_json("/api/browse?playlist=t1&kind=radio")
        self.assertEqual(status, 400)
        self.assertIn("kind", data["error"])

    def test_show_returns_seasons_and_unknown_show_is_404(self):
        _, page = self.get_json("/api/browse?playlist=t1&kind=series")
        status, show = self.get_json(f"/api/show?playlist=t1&id={page['items'][0]['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(show["seasons"][0]["episodes"][0]["title"], "Bem-vindos")

        status, data = self.get_json("/api/show?playlist=t1&id=nada")
        self.assertEqual((status, data["error"]), (404, "Série não encontrada"))

    def test_unknown_playlist_is_404(self):
        status, data = self.get_json("/api/catalog?playlist=zzz")
        self.assertEqual((status, data["error"]), (404, "Playlist não encontrada"))

    def test_serves_static_scripts_but_not_files_outside_static(self):
        status, ctype, body = self.get("/static/js/main.js")
        self.assertEqual((status, body), (200, b"export {};"))
        self.assertIn("javascript", ctype)

        self.assertEqual(self.get("/static/../t1.m3u")[0], 404)
        self.assertEqual(self.get("/static/js/nao-existe.js")[0], 404)


class RewriteM3u8Test(unittest.TestCase):
    def test_segments_point_back_to_proxy(self):
        text = "#EXTM3U\n#EXTINF:9.6,\nseg1.ts\n"

        out = server.rewrite_m3u8(text, "http://cdn.example/hls/index.m3u8")

        self.assertIn("/proxy?u=" + quote("http://cdn.example/hls/seg1.ts", safe=""), out)


if __name__ == "__main__":
    unittest.main()
