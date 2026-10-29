"""Tela cheia: o número do canal (OSD) só aparece se quem entra em tela cheia for a moldura, não o <video>.

O botão de tela cheia nativo do <video> põe só o vídeo na tela e deixa o OSD de fora (foi o que a TV mostrou).
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
HTML = (ROOT / "index.html").read_text()
PLAYER = (ROOT / "static" / "js" / "player.js").read_text()


class FullscreenTest(unittest.TestCase):
    def test_native_fullscreen_button_is_off(self):
        video = re.search(r"<video\b[^>]*>", HTML).group(0)
        self.assertIn('controlslist="nofullscreen"', video)

    def test_osd_lives_inside_the_element_that_goes_fullscreen(self):
        screen = re.search(r'<div class="screen">(.*?)</div>\s*<div class="mini-bar">', HTML, re.S).group(1)
        self.assertIn('id="osd"', screen)
        self.assertIn('id="status"', screen)
        self.assertTrue('const screen = $(".screen")' in PLAYER, "player.js não pega a moldura .screen")
        self.assertTrue("screen.requestFullscreen(" in PLAYER, "a tela cheia não é a da moldura")
        self.assertFalse("video.requestFullscreen" in PLAYER, "a tela cheia do <video> deixa o OSD de fora")

    def test_channel_list_lives_inside_the_fullscreen_frame(self):
        screen = re.search(r'<div class="screen">(.*?)</div>\s*<div class="mini-bar">', HTML, re.S).group(1)
        self.assertIn('id="zapper"', screen)


if __name__ == "__main__":
    unittest.main()
