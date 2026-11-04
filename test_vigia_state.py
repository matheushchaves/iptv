"""Testes do que o vigia decide mostrar: cor, mensagem e linhas do log. Rodar: python3 -m unittest -v"""
import unittest

from vigia_state import GRAY, GREEN, RED, YELLOW, Facts, cut_urls, decide, failure_reason, public_line


class DecideTest(unittest.TestCase):
    def test_each_situation_has_the_spec_message(self):
        cases = [
            (Facts(own_child=True, responding=True), GREEN, "Sofá no ar"),
            (Facts(own_child=True, crashed=True), YELLOW, "Sofá caiu, religando"),
            (Facts(own_child=True), YELLOW, "Sofá ligando"),
            (Facts(own_child=True, responding=True, on_battery=True), YELLOW,
             "Mac na bateria: vai dormir quando ficar parado"),
            (Facts(own_child=True, responding=True, online=False), YELLOW,
             "Sem internet: os canais não vão tocar"),
            (Facts(responding=True), YELLOW, "Sofá aberto pelo Terminal: Religar não funciona"),
            (Facts(gave_up=True), RED, "Sofá não consegue ligar"),
            (Facts(stopped=True), GRAY, "Sofá desligado"),
        ]
        for facts, color, title in cases:
            with self.subTest(title=title):
                verdict = decide(facts)
                self.assertEqual((verdict.color, verdict.title), (color, title))

    def test_red_carries_the_reason(self):
        verdict = decide(Facts(gave_up=True, reason="Outro programa está usando a porta 8000"))
        self.assertEqual(verdict.detail, "Outro programa está usando a porta 8000")

    def test_owner_stop_wins_over_old_crash(self):
        self.assertEqual(decide(Facts(stopped=True, crashed=True, gave_up=True)).color, GRAY)

    def test_terminal_instance_wins_over_stopped(self):
        self.assertEqual(decide(Facts(stopped=True, responding=True)).title,
                         "Sofá aberto pelo Terminal: Religar não funciona")


class PublicLineTest(unittest.TestCase):
    def test_keeps_what_the_owner_should_see(self):
        cases = {
            "19:02:28 player 192.168.0.5: erro de script: x em a.js:1 | Mozilla/5.0":
                "player 192.168.0.5: erro de script: x em a.js:1",
            "painel ex.com: get_live_streams respondeu 403": "painel ex.com: get_live_streams respondeu 403",
            "12:00:00 lista Didugy: não abriu (403)": "lista Didugy: não abriu (403)",
            "12:00:00 recusado: 8.8.8.8 está fora da rede de casa": "recusado: 8.8.8.8 está fora da rede de casa",
        }
        for line, shown in cases.items():
            with self.subTest(line=line):
                self.assertEqual(public_line(line), shown)

    def test_drops_everything_else(self):
        for line in ("Carregando EPG...", "12:00:00 proxy: a/…/b parou no meio (timeout)",
                     "Falha ao carregar EPG http://x/y: boom", "12:00:00 player 192.168.0.5: andou 30 s em 30 s"):
            with self.subTest(line=line):
                self.assertIsNone(public_line(line))

    def test_cuts_urls_and_credentials(self):
        self.assertEqual(cut_urls("falhou http://p.com/get.php?username=u&password=s ok"), "falhou [link] ok")
        self.assertNotIn("segredo", cut_urls("username=eu&password=segredo"))
        self.assertNotIn("p.com", public_line("12:00:00 player 1.2.3.4: erro em http://p.com/live/u/s/1.ts"))

    def test_long_line_is_capped(self):
        self.assertLessEqual(len(public_line("player 1.2.3.4: erro " + "x" * 500)), 160)


class FailureReasonTest(unittest.TestCase):
    def test_busy_port_is_explained(self):
        self.assertEqual(failure_reason(["OSError: [Errno 48] Address already in use"], 8000),
                         "Outro programa está usando a porta 8000")

    def test_uses_last_line_without_urls(self):
        self.assertEqual(failure_reason(["boom em http://p.com/x", ""], 8000), "boom em [link]")

    def test_no_output(self):
        self.assertEqual(failure_reason([], 8000), "O Sofá fechou sem dizer o motivo")


if __name__ == "__main__":
    unittest.main()
