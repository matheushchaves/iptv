"""Ao vivo para TV antiga: o HLS vira um .ts contínuo. Rodar: python3 -m unittest -v test_tslive"""
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from unittest import mock

import server
import tslive

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=3962525,RESOLUTION=1920x1080,CODECS="hvc1.main.main.4.B0,mp4a.40.2"
hevc_1080.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
avc_1080.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,CODECS="avc1.4d401f,mp4a.40.2"
avc_720.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,CODECS="avc1.42e01e,mp4a.40.2"
avc_360.m3u8
"""


def media(first, count, ended=False):
    lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:6", f"#EXT-X-MEDIA-SEQUENCE:{first}"]
    for n in range(first, first + count):
        lines += ["#EXTINF:6.0,", f"seg{n}.ts"]
    return "\n".join(lines + (["#EXT-X-ENDLIST"] if ended else [])) + "\n"


class ChannelPathTest(unittest.TestCase):
    def test_path_ends_in_ts_and_brings_the_link_back(self):
        url = "http://painel.example:80/live/eu/segredo/380134.m3u8?token=a+b/c"

        path = tslive.channel_path(url)

        self.assertTrue(path.startswith("/aovivo/") and path.endswith(".ts"))
        self.assertNotIn("?", path)
        self.assertEqual(tslive.url_from_path(path), url)

    def test_garbage_or_non_http_links_are_refused(self):
        for path in ("/aovivo/!!!.ts", "/aovivo/abc", tslive.channel_path("file:///etc/passwd")):
            with self.subTest(path=path), self.assertRaises(ValueError):
                tslive.url_from_path(path)


class XtreamTsTest(unittest.TestCase):
    def test_panel_live_channel_becomes_the_continuous_ts(self):
        self.assertEqual(tslive.xtream_ts("http://painel.example:80/live/eu/segredo/380134.m3u8"),
                         "http://painel.example:80/live/eu/segredo/380134.ts")

    def test_other_lists_are_left_alone(self):
        for url in ("https://cdn.example/hls/main.m3u8", "http://painel.example/movie/eu/segredo/9.mp4"):
            self.assertIsNone(tslive.xtream_ts(url), url)


class PickVariantTest(unittest.TestCase):
    def test_best_h264_up_to_720p(self):
        self.assertEqual(tslive.pick_variant(MASTER, "http://cdn.example/hls/main.m3u8"),
                         "http://cdn.example/hls/avc_720.m3u8")

    def test_only_hevc_still_returns_something_to_try(self):
        text = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1,CODECS=\"hvc1.1\"\nh.m3u8\n"
        self.assertEqual(tslive.pick_variant(text, "http://cdn.example/a/"), "http://cdn.example/a/h.m3u8")

    def test_without_resolution_takes_the_highest_rate(self):
        text = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900000\nlow.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2000000\nhigh.m3u8\n"
        self.assertEqual(tslive.pick_variant(text, "http://cdn.example/"), "http://cdn.example/high.m3u8")

    def test_media_playlist_is_not_a_master(self):
        self.assertIsNone(tslive.pick_variant(media(1, 3), "http://cdn.example/"))


class ParseMediaTest(unittest.TestCase):
    def test_segments_get_their_sequence_number(self):
        parsed = tslive.parse_media(media(40, 2), "http://cdn.example/hls/index.m3u8")

        self.assertEqual(parsed.segments, [(40, "http://cdn.example/hls/seg40.ts"), (41, "http://cdn.example/hls/seg41.ts")])
        self.assertFalse(parsed.ended)

    def test_encrypted_or_fmp4_channels_cannot_be_joined(self):
        for tag in ('#EXT-X-KEY:METHOD=AES-128,URI="k"', '#EXT-X-MAP:URI="init.mp4"'):
            with self.subTest(tag=tag), self.assertRaises(tslive.Unsupported):
                tslive.parse_media(f"#EXTM3U\n{tag}\n#EXTINF:6,\na.ts\n", "http://cdn.example/")


class SegmentsTest(unittest.TestCase):
    def run_feed(self, playlists, limit=50):
        """URLs que saem, dado o que a lista mostra a cada consulta (a última se repete)."""
        feed = list(playlists)
        get = lambda url: ((feed.pop(0) if len(feed) > 1 else feed[0]), url)
        return [u.rsplit("/", 1)[-1] for u in list(_take(tslive.segments("http://cdn.example/i.m3u8", get, lambda s: None), limit))]

    def test_starts_near_the_live_edge_and_follows_new_segments(self):
        out = self.run_feed([media(10, 6), media(11, 6), media(13, 6, ended=True)])

        self.assertEqual(out, ["seg13.ts", "seg14.ts", "seg15.ts", "seg16.ts", "seg17.ts", "seg18.ts"])

    def test_goes_through_the_master_to_the_variant(self):
        seen = []

        def get(url):
            seen.append(url.rsplit("/", 1)[-1])
            return (MASTER if url.endswith("i.m3u8") else media(1, 2, ended=True)), url

        out = list(tslive.segments("http://cdn.example/i.m3u8", get, lambda s: None))

        self.assertEqual(seen, ["i.m3u8", "avc_720.m3u8"])
        self.assertEqual(out, ["http://cdn.example/seg1.ts", "http://cdn.example/seg2.ts"])

    def test_restarted_sequence_keeps_playing(self):
        out = self.run_feed([media(500, 3), media(1, 3, ended=True)])

        self.assertEqual(out, ["seg500.ts", "seg501.ts", "seg502.ts", "seg3.ts"])

    def test_gives_up_when_nothing_new_arrives(self):
        reasons = []
        get = lambda url: (media(1, 3), url)

        out = list(tslive.segments("http://cdn.example/i.m3u8", get, lambda s: None, reasons.append))

        self.assertEqual(len(out), 3)  # e para: canal parado não segura a conexão para sempre
        self.assertEqual(reasons, ["a lista parou de mudar"])

    def test_gives_up_when_the_list_stops_answering(self):
        calls = []

        def get(url):
            calls.append(url)
            if len(calls) > 1:
                raise OSError("timed out")
            return media(1, 3), url

        reasons = []

        out = list(tslive.segments("http://cdn.example/i.m3u8", get, lambda s: None, reasons.append))

        self.assertEqual(len(out), 3)
        self.assertEqual(len(calls), 1 + tslive.MISSES)
        self.assertEqual(reasons, ["a lista não respondeu (timed out)"])


def _take(iterable, n):
    for i, item in enumerate(iterable):
        if i >= n:
            return
        yield item


class FakeUpstream(BaseHTTPRequestHandler):
    """Uma CDN com HLS (lista mestra, lista de pedaços, pedaços) e um painel Xtream que também dá o .ts direto."""

    def log_message(self, *args):
        pass

    asked = []

    def do_GET(self):
        FakeUpstream.asked.append(self.path)
        if self.path == "/live/eu/segredo/5.ts" and FakeUpstream.asked.count(self.path) == 1:
            self.send_response(409)
            self.end_headers()
            return
        bodies = {
            "/hls/main.m3u8": MASTER.encode(),
            "/hls/avc_720.m3u8": media(1, 2, ended=True).encode(),
            "/hls/seg1.ts": b"PEDACO1",
            "/hls/seg2.ts": b"PEDACO2",
            "/live/eu/segredo/7.ts": b"TS-DIRETO-DO-PAINEL",
            "/live/eu/segredo/5.ts": b"TS-DEPOIS-DO-409",
        }
        if self.path not in bodies:
            self.send_response(406)  # o painel recusando o formato
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.apple.mpegurl" if self.path.endswith(".m3u8") else "video/mp2t")
        self.end_headers()
        self.wfile.write(bodies[self.path])


class LiveEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servers = [ThreadingHTTPServer(("127.0.0.1", 0), h) for h in (FakeUpstream, server.Handler)]
        for httpd in cls.servers:
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
        cls.upstream, cls.app = (f"http://127.0.0.1:{s.server_port}" for s in cls.servers)

    @classmethod
    def tearDownClass(cls):
        for httpd in cls.servers:
            httpd.shutdown()
            httpd.server_close()

    def setUp(self):
        FakeUpstream.asked = []
        patcher = mock.patch.object(server, "BUSY_RETRY_S", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, url):
        with urllib.request.urlopen(self.app + tslive.channel_path(url), timeout=5) as resp:
            return resp.headers["Content-Type"], resp.read()

    def test_hls_channel_arrives_as_one_ts(self):
        self.assertEqual(self.get(f"{self.upstream}/hls/main.m3u8"), ("video/mp2t", b"PEDACO1PEDACO2"))

    def test_panel_channel_comes_straight_as_ts(self):
        self.assertEqual(self.get(f"{self.upstream}/live/eu/segredo/7.m3u8"), ("video/mp2t", b"TS-DIRETO-DO-PAINEL"))

    def test_busy_panel_gets_a_second_try_at_the_ts(self):
        # A conta tem uma conexão: logo depois de trocar de canal o painel ainda conta o anterior e responde 409
        with mock.patch.object(server, "log"):
            self.assertEqual(self.get(f"{self.upstream}/live/eu/segredo/5.m3u8"), ("video/mp2t", b"TS-DEPOIS-DO-409"))

        self.assertEqual(FakeUpstream.asked, ["/live/eu/segredo/5.ts", "/live/eu/segredo/5.ts"])

    def test_end_of_a_direct_channel_is_logged(self):
        with mock.patch.object(server, "log") as log:
            self.get(f"{self.upstream}/live/eu/segredo/7.m3u8")

        self.assertRegex(log.call_args[0][0], r"ao vivo: .*7\.m3u8 o painel fechou depois de")

    def test_channel_that_does_not_open_is_an_error_without_the_password_in_the_log(self):
        with mock.patch.object(server, "log") as log, self.assertRaises(urllib.error.HTTPError) as caught:
            self.get(f"{self.upstream}/live/eu/segredo/8.m3u8")

        self.assertEqual(caught.exception.code, 502)
        logged = " ".join(c[0][0] for c in log.call_args_list)
        self.assertIn("8.m3u8", logged)
        self.assertNotIn("segredo", logged)


if __name__ == "__main__":
    unittest.main()
