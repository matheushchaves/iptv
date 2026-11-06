"""A coluna de canais mostra a lista em uso; sem lista pronta, o aviso, nunca o que sobrou de outra tela ou lista.

O início e a lista moram no mesmo #browse: ir do início para o ao vivo com a lista carregando ou fora do ar deixava a
área de trabalho espremida na coluna de canais. Roda num navegador de verdade, com a API imitada (o defeito é da
ordem das telas, e um teste que só lê o código deixaria passar). Sem o Playwright instalado, fica de fora.
"""
import functools
import json
import threading
import unittest
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

import catalog
import server

try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).parent
THEMES = ("modern", "retro")
FAILURE = "Não abriu a lista (sem resposta)."
PLAYLISTS = [{"id": "lista", "name": "Lista de teste", "source": "arquivo"}]
STUCK_THEN_GOOD = [{"id": "presa", "name": "Presa", "source": "painel"}, {"id": "boa", "name": "Boa", "source": "arquivo"}]
GOOD_LIST = catalog.build_catalog(server.parse_m3u("#EXTM3U\n#EXTINF:-1,Canal Um\nhttp://canal.example/1.m3u8\n"))
SETTLE_MS = 300  # a resposta atrasada já passou pela página: um defeito teria aparecido
PREFS = {"favs": [], "progress": {}, "recent": [], "saved": []}
SKIP_ENTRY = """(theme) => {
  localStorage.setItem("iptv.theme", theme);
  localStorage.setItem("iptv.bootDay", new Date().toDateString());
}"""


class QuietStatic(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def abort_all(routes):
    for route in routes:
        route.abort()


@unittest.skipIf(sync_playwright is None, "Playwright não instalado")
class ListNotReadyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(QuietStatic, directory=str(ROOT))
        cls.httpd = server.SofaServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.httpd.server_close)
        cls.addClassCleanup(cls.httpd.shutdown)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        try:
            cls.browser = cls.playwright.chromium.launch()
        except PlaywrightError as exc:
            raise unittest.SkipTest(f"Chromium do Playwright indisponível: {exc}")
        cls.addClassCleanup(cls.browser.close)

    def open_app(self, theme, answer_list, playlists=PLAYLISTS, slug="inicio"):
        """A página aberta na seção slug. answer_list(route) responde /api/catalog e /api/live."""
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.add_init_script(f"({SKIP_ENTRY})({json.dumps(theme)})")
        page.route(lambda url: "127.0.0.1" not in url, lambda route: route.abort())  # fontes e hls.js de fora
        answers = {"playlists": playlists, "prefs": PREFS, "desk": {}, "version": {"version": "1"}}
        for name, body in answers.items():
            page.route(f"**/api/{name}*", functools.partial(lambda data, route: route.fulfill(json=data), body))
        page.route("**/api/catalog*", answer_list)
        page.route("**/api/live*", answer_list)
        page.goto(f"http://127.0.0.1:{self.httpd.server_address[1]}/#{slug}")
        return page

    def walk_home_then_live(self, page):
        """Abriu sem lista: o caminho até a lista passa por um vai e volta ao início."""
        for slug, view in (("ao-vivo", "live"), ("inicio", "home"), ("ao-vivo", "live")):
            page.evaluate("(slug) => { location.hash = slug; }", slug)
            page.wait_for_function("(view) => document.body.dataset.view === view", arg=view)
            if view == "home":
                page.wait_for_selector("#browse .desk")

    def assert_list_column_shows(self, page, text):
        self.assertEqual(page.locator("#browse .desk").count(), 0, "o início ficou dentro da coluna de canais")
        self.assertIn(text, page.locator("#browse .note").inner_text())

    def test_failed_list_shows_the_reason_after_leaving_the_home(self):
        def refuse(route):
            route.fulfill(status=502, json={"error": FAILURE})

        for theme in THEMES:
            with self.subTest(theme=theme):
                page = self.open_app(theme, refuse)
                page.wait_for_selector(f"#browse .note:has-text('{FAILURE}')")
                self.walk_home_then_live(page)
                self.assert_list_column_shows(page, FAILURE)

    def test_list_still_loading_shows_the_wait_after_leaving_the_home(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                held = []
                page = self.open_app(theme, lambda route: held.append(route))
                self.addCleanup(abort_all, held)  # rota pendente ao fechar vira CancelledError no Playwright
                page.wait_for_selector("#browse .note:has-text('Carregando a lista')")
                self.walk_home_then_live(page)
                self.assert_list_column_shows(page, "Carregando a lista")

    def test_late_failure_of_the_previous_list_keeps_the_new_one_on_screen(self):
        held = []

        def answer(route):
            url = route.request.url
            if "playlist=presa" in url:
                held.append(route)
            else:
                route.fulfill(json=catalog.summary(GOOD_LIST) if "/api/catalog" in url else GOOD_LIST.live)

        page = self.open_app("modern", answer, playlists=STUCK_THEN_GOOD, slug="ao-vivo")
        page.wait_for_selector("#browse .note:has-text('Carregando a lista')")
        page.select_option("#playlist", "boa")
        page.wait_for_selector("#browse .ch")
        self.assertTrue(held, "a lista presa nem chegou a ser pedida")
        for route in held:
            route.fulfill(status=502, json={"error": FAILURE})
        page.wait_for_timeout(SETTLE_MS)
        self.assertEqual(page.locator("#browse .note").count(), 0, "a falha velha apagou a lista nova")
        self.assertEqual(page.locator("#browse .ch").count(), 1)


if __name__ == "__main__":
    unittest.main()
