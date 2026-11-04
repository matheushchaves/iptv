"""Testes do vigia: cuidar do server.py e a página de estado. Rodar: python3 -m unittest -v"""
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from vigia import ServerLog, Supervisor, probe_server
from vigia_state import GREEN, RED, decide

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
            self.assertEqual((Path(tmp) / "server.log").read_bytes(), b"segunda\n")
            self.assertEqual((Path(tmp) / "server.1.log").read_bytes(), b"primeira\n")


if __name__ == "__main__":
    unittest.main()
