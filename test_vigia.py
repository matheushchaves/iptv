"""Testes do vigia: cuidar do server.py e a página de estado. Rodar: python3 -m unittest -v"""
import dataclasses
import http.client
import json
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import vigia
from test_compat import JS_SYNTAX
from vigia import ServerLog, Supervisor, Vigia, bind_status, probe_server
from vigia_state import GREEN, RED, Facts, decide

ROOT = Path(__file__).parent

FAKE_SERVER = r'''
import http.server, pathlib, sys, time
mode = pathlib.Path("mode").read_text().strip()
if mode == "crash":
    print("boom em http://p.com/x", flush=True)
    sys.exit(1)
if mode == "busy":
    print("OSError: [Errno 48] Address already in use", flush=True)
    sys.exit(1)
if mode == "noise":
    sys.stdout.buffer.write(b"\xff\xfe\n" + b"x" * 1000000 + b"\n")
    sys.stdout.buffer.flush()
    print("12:00:00 painel x: respondeu 403", flush=True)
seen = []
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        seen.append(1)
        if mode == "hang" and len(seen) > 1:
            time.sleep(60)
        body = b'{"version": "1"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
'''


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeChild:
    stdout = None

    def __init__(self):
        self.code = None
        self.ignores_terminate = self.killed = False

    def poll(self):
        return self.code

    def terminate(self):
        if not self.ignores_terminate:
            self.code = -15

    def kill(self):
        self.killed = True
        self.code = -9

    def wait(self, timeout=None):
        if self.code is None:
            raise subprocess.TimeoutExpired("server.py", timeout)
        return self.code


class Rig:
    """Supervisor com relógio, sonda e filhos de mentira: cada tick é uma volta do vigia."""

    def __init__(self, root, **kwargs):
        self.now = 0.0
        self.answering = False
        self.children, self.events = [], []
        self.sup = Supervisor(root, 8000, spawn=self.spawn, probe=lambda: self.answering, clock=lambda: self.now,
                              on_event=self.events.append, **kwargs)

    def spawn(self):
        self.children.append(FakeChild())
        return self.children[-1]

    def facts(self):
        return self.sup.facts(False, True)

    def alive(self):
        return [c for c in self.children if c.poll() is None]


class SupervisorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.rig = Rig(self.root)
        self.sup = self.rig.sup

    def come_up(self):
        self.sup.tick()
        self.rig.answering = True
        self.sup.tick()

    def test_starts_once_and_goes_green(self):
        self.come_up()
        self.sup.tick()
        self.assertEqual(len(self.rig.children), 1)
        self.assertEqual(decide(self.rig.facts()).color, GREEN)
        self.assertEqual(self.rig.events, ["Sofá ligou"])

    def test_restart_waits_the_growing_delays(self):
        self.sup.tick()
        for delay in (1, 2, 5, 10, 30):
            self.rig.children[-1].code = 1
            self.sup.tick()
            before = len(self.rig.children)
            self.rig.now += delay - 0.5
            self.sup.tick()
            self.assertEqual(len(self.rig.children), before, f"cedo demais na espera de {delay}")
            self.rig.now += 0.5
            self.sup.tick()
            self.assertEqual(len(self.rig.children), before + 1, f"não religou depois de {delay}")

    def fall_until_giving_up(self):
        self.sup.tick()
        for delay in (1, 2, 5, 10, 30):
            self.rig.children[-1].code = 1
            self.sup.tick()
            self.rig.now += delay
            self.sup.tick()

    def test_gives_up_after_all_delays_but_keeps_trying(self):
        self.fall_until_giving_up()
        self.assertTrue(self.rig.facts().gave_up)
        before = len(self.rig.children)
        self.rig.children[-1].code = 1
        self.sup.tick()
        self.rig.now += 60
        self.sup.tick()
        self.assertEqual(len(self.rig.children), before + 1)

    def test_back_after_giving_up_is_not_red(self):
        self.fall_until_giving_up()
        self.rig.answering = True
        self.sup.tick()
        self.assertFalse(self.rig.facts().gave_up)

    def test_stable_run_clears_the_failures(self):
        self.fall_until_giving_up()
        self.rig.answering = True
        self.sup.tick()
        self.rig.now += 60
        self.sup.tick()
        self.rig.children[-1].code = 1
        self.rig.answering = False
        self.sup.tick()
        self.assertFalse(self.rig.facts().gave_up)
        self.rig.now += 1
        self.sup.tick()
        self.assertTrue(self.rig.alive())

    def test_hung_child_is_killed_and_restarted(self):
        self.come_up()
        self.rig.answering = False
        for _ in range(3):
            self.sup.tick()
        self.assertEqual(self.rig.children[0].code, -15)
        self.assertIn("Sofá travou, religando", self.rig.events)
        self.rig.now += 1
        self.sup.tick()
        self.assertEqual(len(self.rig.alive()), 1)

    def test_slow_start_is_not_hung(self):
        self.sup.tick()
        self.rig.now += 29
        for _ in range(5):
            self.sup.tick()
        self.assertEqual(len(self.rig.children), 1)
        self.assertIsNone(self.rig.children[0].code)

    def test_start_that_never_answers_is_restarted(self):
        self.sup.tick()
        self.rig.now += 30
        self.sup.tick()
        self.assertEqual(self.rig.children[0].code, -15)

    def test_terminal_instance_is_left_alone(self):
        self.rig.answering = True
        self.sup.tick()
        self.assertEqual(self.rig.children, [])
        self.assertTrue(self.sup.external)
        self.assertFalse(self.sup.restart())

    def test_spawns_when_terminal_instance_goes_away(self):
        self.rig.answering = True
        self.sup.tick()
        self.rig.answering = False
        self.sup.tick()
        self.assertEqual(len(self.rig.children), 1)

    def test_dead_child_is_not_mistaken_for_terminal(self):
        self.come_up()
        self.rig.children[0].code = 1
        self.assertFalse(self.sup.external)

    def test_stop_persists_and_start_clears(self):
        self.come_up()
        self.sup.stop()
        self.assertEqual(self.rig.children[0].code, -15)
        self.assertTrue(self.sup.stopped)
        again = Rig(self.root)
        again.sup.tick()
        self.assertTrue(again.sup.stopped)
        self.assertEqual(again.children, [])
        again.sup.start()
        again.sup.tick()
        self.assertFalse(again.sup.stopped)
        self.assertEqual(len(again.alive()), 1)
        self.assertFalse(Rig(self.root).sup.stopped)

    def test_restart_replaces_the_child(self):
        self.come_up()
        self.assertTrue(self.sup.restart())
        self.assertEqual(self.rig.children[0].code, -15)
        self.assertEqual(len(self.rig.alive()), 1)

    def test_restart_while_stopped_does_nothing(self):
        self.come_up()
        self.sup.stop()
        self.assertFalse(self.sup.restart())
        self.assertEqual(self.rig.alive(), [])

    def test_child_ignoring_terminate_is_killed(self):
        self.come_up()
        self.rig.children[0].ignores_terminate = True
        self.sup.restart()
        self.assertTrue(self.rig.children[0].killed)

    def test_shutdown_ends_the_child(self):
        self.come_up()
        self.sup.shutdown()
        self.assertEqual(self.rig.alive(), [])

    def test_spawn_error_does_not_kill_the_vigia(self):
        def broken():
            raise OSError("sem python")
        self.sup.spawn = broken
        self.sup.tick()
        self.assertTrue(self.rig.facts().crashed)
        self.assertEqual(self.rig.facts().reason, "Não consegui abrir o server.py")

    def test_two_restarts_at_once_leave_one_child(self):
        self.come_up()
        go = threading.Barrier(2)

        def press():
            go.wait()
            self.sup.restart()
        threads = [threading.Thread(target=press) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(self.rig.alive()), 1)


class RealChildTest(unittest.TestCase):
    """Com um server.py falso de verdade, que cai, trava ou ocupa a porta."""

    def rig(self, mode, *, write_server=True, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        if write_server:
            (self.root / "server.py").write_text(FAKE_SERVER)
        (self.root / "mode").write_text(mode)
        self.port = free_port()
        self.events = []
        options = {"delays": (0.01,), "hung_probes": 2, "retry_s": 0.05, **kwargs}
        self.sup = Supervisor(self.root, self.port, probe=lambda: probe_server(self.port, timeout=0.2),
                              on_event=self.events.append, **options)
        self.addCleanup(self.sup.shutdown)
        return self.sup

    def wait_until(self, condition, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.sup.tick()
            if condition():
                return
            time.sleep(0.02)
        self.fail(f"não aconteceu; eventos: {self.events}")

    def facts(self):
        return self.sup.facts(False, True)

    def test_healthy_child_goes_green(self):
        self.rig("ok")
        self.wait_until(lambda: self.facts().responding)
        self.assertEqual(decide(self.facts()).color, GREEN)

    def test_crash_shows_the_error_as_reason(self):
        self.rig("crash")
        self.wait_until(lambda: self.facts().gave_up)
        self.assertEqual(decide(self.facts()).detail, "boom em [link]")

    def test_busy_port_is_reported_in_plain_words(self):
        self.rig("busy")
        self.wait_until(lambda: self.facts().gave_up)
        self.assertEqual(decide(self.facts()).detail, f"Outro programa está usando a porta {self.port}")

    def test_hang_is_restarted(self):
        self.rig("hang")
        self.wait_until(lambda: "Sofá travou, religando" in self.events)

    def test_missing_server_goes_red(self):
        self.rig("ok", write_server=False)
        self.wait_until(lambda: self.facts().gave_up)
        verdict = decide(self.facts())
        self.assertEqual((verdict.color, verdict.detail), (RED, "Não consegui abrir o server.py"))

    def test_invalid_bytes_do_not_stop_the_reader(self):
        self.rig("noise")
        self.wait_until(lambda: "painel x: respondeu 403" in self.events)
        self.wait_until(lambda: self.facts().responding)
        log = (self.root / "server.log").read_bytes().splitlines()
        self.assertEqual(log[0], b"\xff\xfe")
        self.assertLessEqual(len(log[1]), 4096)
        self.assertEqual(log[2], b"12:00:00 painel x: respondeu 403")

    def test_full_disk_does_not_stop_the_reader(self):
        self.rig("noise")
        with mock.patch.object(ServerLog, "write", side_effect=OSError("disco cheio")):
            self.wait_until(lambda: "painel x: respondeu 403" in self.events)
            self.wait_until(lambda: self.facts().responding)


class ProbeTest(unittest.TestCase):
    def test_nothing_listening_is_not_the_sofa(self):
        self.assertFalse(probe_server(free_port(), timeout=0.2))


class ServerLogTest(unittest.TestCase):
    def test_rotates_past_the_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = ServerLog(Path(tmp) / "server.log", max_bytes=10)
            log.write(b"primeira\n")
            log.write(b"segunda\n")
            log.close()
            self.assertEqual((Path(tmp) / "server.log").read_bytes(), b"segunda\n")
            self.assertEqual((Path(tmp) / "server.1.log").read_bytes(), b"primeira\n")


class FakeSupervisor:
    port = 8000

    def __init__(self):
        self.stopped = False
        self.accepts_restart = True
        self.facts_now = Facts(own_child=True, responding=True)
        self.calls = []
        self.emit = None

    def tick(self):
        self.calls.append("tick")

    def restart(self):
        self.calls.append("restart")
        return self.accepts_restart

    def stop(self):
        self.calls.append("stop")

    def start(self):
        self.calls.append("start")

    def shutdown(self):
        self.calls.append("shutdown")

    def facts(self, on_battery, online):
        return dataclasses.replace(self.facts_now, on_battery=on_battery, online=online)


class FakeAwake:
    def __init__(self):
        self.calls = []

    def set(self, on):
        self.calls.append(on)


class FakeNames:
    name = "sofa.local"

    def __init__(self):
        self.ips = []
        self.stopped = False

    def update(self, ip):
        self.ips.append(ip)

    def stop(self):
        self.stopped = True


def make_vigia(**kwargs):
    options = {"ip": lambda: "192.168.0.4", "battery": lambda: False, "online": lambda: True}
    sup, awake, names = FakeSupervisor(), FakeAwake(), FakeNames()
    return Vigia(sup, awake, names, **{**options, **kwargs}), sup, awake, names


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.vigia, self.sup, self.awake, self.names = make_vigia()
        self.httpd = bind_status(self.vigia, 0, host="127.0.0.1")
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def ask(self, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        self.addCleanup(conn.close)
        conn.request(method, path, headers=headers or {})
        res = conn.getresponse()
        return res.status, res.read()

    def status(self):
        return json.loads(self.ask("GET", "/api/status")[1])


class StatusApiTest(ApiCase):
    def test_status_has_tv_address_and_message(self):
        body = self.status()
        self.assertEqual((body["color"], body["title"]), ("green", "Sofá no ar"))
        self.assertEqual(body["address"], {"ip": "192.168.0.4", "port": 8000, "name": "sofa.local",
                                           "status_port": self.vigia.status_port})
        self.assertEqual([c["label"] for c in body["checks"]], ["Mac", "Serviço", "Internet"])

    def test_no_network_never_shows_loopback(self):
        self.vigia.ip = lambda: None
        self.assertIsNone(self.status()["address"]["ip"])

    def test_events_come_newest_first(self):
        self.sup.emit("primeiro")
        self.sup.emit("segundo")
        self.assertEqual([e["text"] for e in self.status()["events"]], ["segundo", "primeiro"])

    def test_refuses_the_internet(self):
        with mock.patch.object(vigia, "from_home", return_value=False):
            self.assertEqual(self.ask("GET", "/api/status")[0], 403)
            self.assertEqual(self.ask("POST", "/api/restart")[0], 403)
        self.assertNotIn("restart", self.sup.calls)

    def test_page_opens_while_sofa_is_down(self):
        self.sup.facts_now = Facts(gave_up=True)
        code, body = self.ask("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn("<title>", body.decode())
        self.assertEqual(self.status()["color"], "red")

    def test_unknown_path_is_404(self):
        self.assertEqual(self.ask("GET", "/nada")[0], 404)


class ActionsTest(ApiCase):
    def test_restart_works_from_the_tablet(self):
        with mock.patch.object(vigia, "is_loopback", return_value=False):
            self.assertEqual(self.ask("POST", "/api/restart")[0], 200)
        self.assertIn("restart", self.sup.calls)

    def test_stop_is_refused_from_another_device(self):
        with mock.patch.object(vigia, "is_loopback", return_value=False):
            self.assertEqual(self.ask("POST", "/api/stop")[0], 403)
        self.assertNotIn("stop", self.sup.calls)

    def test_stop_works_on_the_mac(self):
        self.assertEqual(self.ask("POST", "/api/stop")[0], 200)
        self.assertIn("stop", self.sup.calls)

    def test_start_works_from_the_tablet(self):
        with mock.patch.object(vigia, "is_loopback", return_value=False):
            self.assertEqual(self.ask("POST", "/api/start")[0], 200)
        self.assertIn("start", self.sup.calls)

    def test_stop_button_only_on_the_mac(self):
        self.assertTrue(self.status()["can_stop"])
        with mock.patch.object(vigia, "is_loopback", return_value=False):
            self.assertFalse(self.status()["can_stop"])

    def test_buttons_follow_the_state(self):
        self.assertEqual((self.status()["can_restart"], self.status()["can_start"]), (True, False))
        self.sup.facts_now = Facts(stopped=True)
        body = self.status()
        self.assertEqual((body["can_restart"], body["can_start"], body["can_stop"]), (False, True, False))
        self.sup.facts_now = Facts(responding=True)
        body = self.status()
        self.assertEqual((body["can_restart"], body["can_start"], body["can_stop"]), (False, False, False))

    def test_restart_on_terminal_instance_is_409(self):
        self.sup.accepts_restart = False
        self.assertEqual(self.ask("POST", "/api/restart")[0], 409)

    def test_post_from_another_site_is_refused(self):
        self.assertEqual(self.ask("POST", "/api/restart", {"Origin": "http://evil.example"})[0], 403)
        self.assertNotIn("restart", self.sup.calls)

    def test_rebinding_host_is_refused(self):
        headers = {"Host": "evil.example", "Origin": "http://evil.example"}
        self.assertEqual(self.ask("POST", "/api/restart", headers)[0], 403)

    def test_same_origin_post_is_accepted(self):
        headers = {"Host": "sofa.local:8010", "Origin": "http://sofa.local:8010"}
        self.assertEqual(self.ask("POST", "/api/restart", headers)[0], 200)

    def test_post_without_origin_is_accepted(self):
        self.assertEqual(self.ask("POST", "/api/restart")[0], 200)

    def test_unknown_action_is_404(self):
        self.assertEqual(self.ask("POST", "/api/nada")[0], 404)


class StepTest(unittest.TestCase):
    def test_keeps_mac_awake_only_while_on(self):
        v, sup, awake, _ = make_vigia()
        v.step()
        sup.stopped = True
        v.step()
        self.assertEqual(awake.calls, [True, False])

    def test_ticks_the_supervisor(self):
        v, sup, _, _ = make_vigia()
        v.step()
        self.assertIn("tick", sup.calls)

    def test_ip_change_republishes_and_logs(self):
        ips = ["192.168.0.4", "192.168.0.10"]
        v, _, _, names = make_vigia(ip=lambda: ips[0])
        v.step()
        ips.pop(0)
        v.step()
        self.assertEqual(names.ips, ["192.168.0.4", "192.168.0.10"])
        self.assertEqual([e["text"] for e in v.status(True)["events"]], ["IP mudou para 192.168.0.10"])

    def test_since_only_moves_when_the_title_changes(self):
        now = [1000.0]
        v, sup, _, _ = make_vigia(wall=lambda: now[0])
        first = v.status(True)["since"]
        now[0] = 2000.0
        self.assertEqual(v.status(True)["since"], first)
        sup.facts_now = Facts(gave_up=True)
        self.assertEqual(v.status(True)["since"], 2000.0)

    def test_battery_and_internet_reach_the_status(self):
        v, _, _, _ = make_vigia(battery=lambda: True, online=lambda: False)
        v.step()
        wait_for(lambda: not v.status(True)["checks"][2]["ok"])
        body = v.status(True)
        self.assertEqual(body["title"], "Sem internet: os canais não vão tocar")
        self.assertEqual(body["checks"][0]["value"], "na bateria")

    def test_slow_internet_check_does_not_hold_step(self):
        release = threading.Event()
        self.addCleanup(release.set)
        v, _, _, _ = make_vigia(online=lambda: release.wait(5))
        started = time.monotonic()
        v.step()
        self.assertLess(time.monotonic() - started, 1)

    def test_shutdown_ends_everything(self):
        v, sup, awake, names = make_vigia()
        v.shutdown()
        self.assertIn("shutdown", sup.calls)
        self.assertEqual(awake.calls, [False])
        self.assertTrue(names.stopped)


def wait_for(condition, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not condition():
        time.sleep(0.01)


class SecondVigiaTest(unittest.TestCase):
    def test_exits_without_starting_a_server(self):
        sofa_port = free_port()
        with socket.socket() as taken:
            taken.bind(("0.0.0.0", 0))
            taken.listen()
            status_port = taken.getsockname()[1]
            done = subprocess.run([sys.executable, "vigia.py", str(sofa_port), str(status_port)], cwd=ROOT,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 1)
        self.assertIn("já está rodando", done.stdout)
        self.assertFalse(probe_server(sofa_port, timeout=0.2))


class PageTest(unittest.TestCase):
    page = (ROOT / "vigia.html").read_text() if (ROOT / "vigia.html").exists() else ""

    def test_follows_chrome_79(self):
        for name, pattern in JS_SYNTAX.items():
            self.assertNotRegex(self.page, pattern, name)
        self.assertNotRegex(self.page, re.compile(r"\bgap\s*:"))
        self.assertNotIn("inset", self.page)

    def test_never_writes_html_from_data(self):
        self.assertNotIn("innerHTML", self.page)

    def test_has_the_no_network_message(self):
        self.assertIn("Sem rede no Mac", self.page)

    def test_tells_when_the_vigia_is_gone(self):
        self.assertIn("Vigia fora do ar", self.page)


if __name__ == "__main__":
    unittest.main()
