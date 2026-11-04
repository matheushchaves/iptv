"""O vigia: mantém o server.py no ar e mostra numa página se está tudo bem.

Roda separado do Sofá e nunca importa o server.py, para um erro lá não derrubar quem precisa avisar do erro.
Rodar: python3 vigia.py [porta do Sofá] [porta da página]
"""
import errno
import http.client
import ipaddress
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional, Sequence
from urllib.parse import urlparse

from vigia_state import Facts, Verdict, decide, failure_reason, public_line
from vigia_system import KeepAwake, NamePublisher, internet_ok, lan_ip, on_battery

ROOT = Path(__file__).parent.resolve()
PAGE = ROOT / "vigia.html"
SERVER_PORT = 8000
STATUS_PORT = 8010
TICK_S = 2
PROBE_TIMEOUT_S = 2
HUNG_PROBES = 3
STARTUP_GRACE_S = 30
RESTART_DELAYS = (1, 2, 5, 10, 30)
RETRY_AFTER_GIVING_UP_S = 60
STABLE_S = 60  # no ar por esse tempo, as quedas anteriores deixam de contar
STOP_GRACE_S = 3
MAX_LOG_BYTES = 5 * 1024 * 1024
MAX_LINE_BYTES = 4096
RECENT_LINES = 20
READER_JOIN_S = 1
MAX_EVENTS = 40
BATTERY_EVERY_S = 30
INTERNET_EVERY_S = 60


def probe_server(port: int, timeout: float = PROBE_TIMEOUT_S) -> bool:
    """A porta responde como o Sofá? Outro programa nela não conta."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/api/version")
        res = conn.getresponse()
        return res.status == 200 and "version" in json.loads(res.read())
    except (OSError, http.client.HTTPException, ValueError, TypeError):
        return False
    finally:
        conn.close()


class ServerLog:
    """O server.log de sempre, agora com limite: o serviço fica ligado por semanas."""

    def __init__(self, path: Path, max_bytes: int = MAX_LOG_BYTES):
        self.path, self.max_bytes = Path(path), max_bytes
        self.file = None
        self.size = 0
        self.lock = threading.Lock()

    def _rotate(self) -> None:
        self.file.close()
        self.file = None
        os.replace(self.path, self.path.with_suffix(".1.log"))  # server.log.1 escaparia do *.log do .gitignore

    def write(self, line: bytes) -> None:
        with self.lock:
            if self.file is not None and self.size + len(line) > self.max_bytes:
                self._rotate()
            if self.file is None:
                self.file = open(self.path, "ab")
                self.size = os.fstat(self.file.fileno()).st_size
            self.file.write(line)
            self.file.flush()
            self.size += len(line)

    def close(self) -> None:
        with self.lock:
            if self.file is not None:
                self.file.close()
                self.file = None


class Supervisor:
    """Sobe o server.py, religa quando ele cai ou trava, e não briga com um Sofá aberto pelo Terminal."""

    def __init__(self, root: Path, port: int, *, spawn: Optional[Callable] = None, probe: Optional[Callable] = None,
                 clock: Callable = time.monotonic, on_event: Optional[Callable] = None,
                 stop_flag: Optional[Path] = None, delays: Sequence[float] = RESTART_DELAYS,
                 retry_s: float = RETRY_AFTER_GIVING_UP_S, hung_probes: int = HUNG_PROBES,
                 startup_grace_s: float = STARTUP_GRACE_S, stable_s: float = STABLE_S,
                 stop_grace_s: float = STOP_GRACE_S):
        self.root, self.port = Path(root), port
        self.spawn = spawn or self._spawn
        self.probe = probe or (lambda: probe_server(port))
        self.clock = clock
        self.emit = on_event or (lambda text: None)
        self.stop_flag = Path(stop_flag) if stop_flag else self.root / "cache" / "vigia-desligado"
        self.delays, self.retry_s, self.hung_probes = delays, retry_s, hung_probes
        self.startup_grace_s, self.stable_s, self.stop_grace_s = startup_grace_s, stable_s, stop_grace_s
        self.log = ServerLog(self.root / "server.log")
        self.lock = threading.Lock()
        self.stopped = self.stop_flag.exists()
        self.child = self.reader = None
        self.recent = deque(maxlen=RECENT_LINES)
        self.responding = self.answered = self.crashed = self.log_failed = False
        self.attempts = self.misses = 0
        self.started_at = self.up_since = self.next_try = 0.0
        self.reason = ""

    @property
    def external(self) -> bool:
        return self.responding and self.child is None

    def _spawn(self) -> subprocess.Popen:
        if not (self.root / "server.py").exists():
            raise FileNotFoundError("server.py")
        return subprocess.Popen([sys.executable, "-u", "server.py", str(self.port)], cwd=self.root,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONUTF8": "1"})

    def _read(self, child) -> None:
        # Esta thread não pode parar: com o pipe cheio, o próximo print do Sofá congelaria o servidor inteiro
        with child.stdout:
            for raw in child.stdout:
                self._take(raw if len(raw) <= MAX_LINE_BYTES else raw[:MAX_LINE_BYTES - 1] + b"\n")

    def _take(self, line: bytes) -> None:
        try:
            self.log.write(line)
        except OSError as exc:
            if not self.log_failed:
                self.log_failed = True
                self.emit(f"Não consegui gravar o server.log ({exc.strerror or exc})")
        text = line.decode("utf-8", "replace").rstrip()
        self.recent.append(text)
        shown = public_line(text)
        if shown:
            self.emit(shown)

    def _launch(self, now: float) -> None:
        self.recent.clear()
        self.answered, self.misses, self.started_at = False, 0, now
        try:
            child = self.spawn()
        except OSError:
            return self._fall(now, "Sofá caiu", "Não consegui abrir o server.py")
        self.child = child
        if child.stdout:
            self.reader = threading.Thread(target=self._read, args=(child,), daemon=True)
            self.reader.start()

    def _fall(self, now: float, event: str, reason: Optional[str] = None) -> None:
        if self.reader:
            self.reader.join(READER_JOIN_S)
        self.child = None
        self.crashed = True
        self.attempts += 1
        self.reason = reason or failure_reason(list(self.recent), self.port)
        late = self.attempts > len(self.delays)
        self.next_try = now + (self.retry_s if late else self.delays[self.attempts - 1])
        self.emit(event)

    def _end_child(self) -> None:
        child, self.child = self.child, None
        self.responding = False
        if child is None or child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=self.stop_grace_s)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()

    def _watch(self, answering: bool, now: float) -> None:
        if answering:
            if not self.answered:
                self.answered, self.up_since = True, now
                self.emit("Sofá voltou" if self.crashed else "Sofá ligou")
                self.crashed = False
            self.misses = 0
            if self.attempts and now - self.up_since >= self.stable_s:
                self.attempts, self.reason = 0, ""
            return
        if self.answered:
            self.misses += 1
            if self.misses < self.hung_probes:
                return
        elif now - self.started_at < self.startup_grace_s:
            return
        self._end_child()
        self._fall(now, "Sofá travou, religando", "O Sofá parou de responder")

    def tick(self) -> None:
        answering = self.probe()  # fora do lock: com o Sofá travado, o Religar não pode esperar a sonda
        with self.lock:
            now = self.clock()
            self.responding = answering
            if self.child is not None and self.child.poll() is not None:
                self._fall(now, "Sofá caiu")
            if self.child is not None:
                self._watch(answering, now)
            elif not answering and not self.stopped and now >= self.next_try:
                self._launch(now)

    def _forget_failures(self) -> None:
        self.crashed, self.attempts, self.reason, self.next_try = False, 0, "", 0.0

    def restart(self) -> bool:
        with self.lock:
            if self.external or self.stopped:
                return False
            self._end_child()
            self._forget_failures()
            self._launch(self.clock())
            return True

    def _save_stop(self, stopped: bool) -> None:
        self.stopped = stopped
        try:
            if stopped:
                self.stop_flag.parent.mkdir(parents=True, exist_ok=True)
                self.stop_flag.touch()
            else:
                self.stop_flag.unlink(missing_ok=True)
        except OSError as exc:  # segue valendo até o vigia reiniciar
            self.emit(f"Não consegui guardar o estado ({exc.strerror or exc})")

    def stop(self) -> None:
        with self.lock:
            self._save_stop(True)
            self._end_child()
            self._forget_failures()
            self.emit("Sofá desligado")

    def start(self) -> None:
        with self.lock:
            self._save_stop(False)
            self._forget_failures()
            if not self.external and self.child is None:
                self._launch(self.clock())

    def shutdown(self) -> None:
        with self.lock:
            self._end_child()
            if self.reader:
                self.reader.join(READER_JOIN_S)
            self.log.close()

    def facts(self, on_battery: bool, online: bool) -> Facts:
        with self.lock:
            gave_up = self.attempts >= len(self.delays) and not self.responding
            return Facts(stopped=self.stopped, own_child=self.child is not None, responding=self.responding,
                         crashed=self.crashed, gave_up=gave_up, reason=self.reason, on_battery=on_battery,
                         online=online)


def from_home(addr: str) -> bool:
    """Mesma regra do server.py, que o vigia não importa."""
    try:
        return not ipaddress.ip_address(addr).is_global
    except ValueError:
        return False


def is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def trusted_host(name: str) -> bool:
    """Endereços que a casa usa de verdade. Um nome qualquer aqui seria um site apontando seu DNS para o Mac."""
    if name == "localhost" or name.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def same_site(host: str, origin: Optional[str]) -> bool:
    """Uma página qualquer aberta num navegador da casa não pode apertar os botões do vigia."""
    name = urlparse(f"//{host}").hostname or ""
    return trusted_host(name) and (not origin or urlparse(origin).hostname == name)


class Vigia:
    """Junta o que aconteceu com o Sofá e o estado do Mac no que a página e o app mostram."""

    def __init__(self, supervisor, awake, names, *, ip: Callable = lan_ip, battery: Callable = on_battery,
                 online: Callable = internet_ok, status_port: int = STATUS_PORT, clock: Callable = time.monotonic,
                 wall: Callable = time.time):
        self.supervisor, self.awake, self.names = supervisor, awake, names
        self.ip, self.battery, self.online, self.status_port = ip, battery, online, status_port
        self.clock, self.wall = clock, wall
        self.lock = threading.Lock()
        self.events = deque(maxlen=MAX_EVENTS)
        self.last_ip = self.title = None
        self.since = wall()
        self.on_battery, self.is_online = False, True
        self.battery_due = self.internet_due = 0.0
        self.done = threading.Event()
        supervisor.emit = self.add_event

    def add_event(self, text: str) -> None:
        with self.lock:
            self.events.append((self.wall(), text))

    def _follow_ip(self) -> None:
        ip = self.ip()
        self.names.update(ip)
        if ip and ip != self.last_ip:
            if self.last_ip:
                self.add_event(f"IP mudou para {ip}")
            self.last_ip = ip

    def _check_internet(self) -> None:
        self.is_online = self.online()

    def step(self) -> None:
        self.supervisor.tick()
        self.awake.set(not self.supervisor.stopped)
        self._follow_ip()
        now = self.clock()
        if now >= self.battery_due:
            self.battery_due = now + BATTERY_EVERY_S
            self.on_battery = self.battery()
        if now >= self.internet_due:
            self.internet_due = now + INTERNET_EVERY_S
            threading.Thread(target=self._check_internet, daemon=True).start()
        self.status(True)  # sem ninguém olhando, o "desde" também precisa andar

    def _note(self, verdict: Verdict) -> tuple:
        with self.lock:
            if verdict.title != self.title:
                self.title, self.since = verdict.title, self.wall()
            return self.since, [{"at": at, "text": text} for at, text in reversed(self.events)]

    def _checks(self, facts: Facts) -> list:
        service = "respondendo" if facts.responding else "desligado" if facts.stopped else "fora do ar"
        return [
            {"label": "Mac", "value": "na bateria" if facts.on_battery else "na tomada", "ok": not facts.on_battery},
            {"label": "Serviço", "value": service, "ok": facts.responding},
            {"label": "Internet", "value": "ok" if facts.online else "sem conexão", "ok": facts.online},
        ]

    def status(self, local: bool) -> dict:
        facts = self.supervisor.facts(self.on_battery, self.is_online)
        verdict = decide(facts)
        since, events = self._note(verdict)
        external = facts.responding and not facts.own_child
        running = not facts.stopped and not external
        return {
            "color": verdict.color, "title": verdict.title, "detail": verdict.detail, "since": since,
            "address": {"ip": self.ip(), "port": self.supervisor.port, "name": self.names.name,
                        "status_port": self.status_port},
            "checks": self._checks(facts),
            "events": events,
            "can_restart": running,
            "can_start": facts.stopped and not external,
            "can_stop": local and running,
        }

    def run(self, httpd: ThreadingHTTPServer) -> None:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            while True:
                self.step()
                if self.done.wait(TICK_S):
                    return
        finally:
            httpd.shutdown()
            self.shutdown()

    def shutdown(self) -> None:
        self.supervisor.shutdown()
        self.awake.set(False)
        self.names.stop()


def make_handler(vigia: Vigia) -> type:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, code: int, data: dict) -> None:
            self.send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def at_home(self) -> bool:
            if from_home(self.client_address[0]):
                return True
            self.send_json(403, {"error": "O vigia só atende a rede de casa"})
            return False

        def do_GET(self):
            if not self.at_home():
                return
            path = urlparse(self.path).path
            if path == "/":
                self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/status":
                self.send_json(200, vigia.status(is_loopback(self.client_address[0])))
            else:
                self.send_json(404, {"error": "Não encontrado"})

        def do_POST(self):
            if not self.at_home():
                return
            if not same_site(self.headers.get("Host", ""), self.headers.get("Origin")):
                return self.send_json(403, {"error": "Pedido de outro site recusado"})
            path = urlparse(self.path).path
            if path == "/api/restart":
                done = vigia.supervisor.restart()
                self.send_json(200, {"ok": True}) if done else self.send_json(409, {"error": "Religar não funciona agora"})
            elif path == "/api/start":
                vigia.supervisor.start()
                self.send_json(200, {"ok": True})
            elif path == "/api/stop":
                # Do sofá isso não teria volta: o Mac dormiria e a página pararia de abrir
                if not is_loopback(self.client_address[0]):
                    return self.send_json(403, {"error": "Desligar só funciona no próprio Mac"})
                vigia.supervisor.stop()
                self.send_json(200, {"ok": True})
            else:
                self.send_json(404, {"error": "Não encontrado"})

    return Handler


def bind_status(vigia: Vigia, port: int, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(vigia))


def main(argv: Sequence[str]) -> int:
    port = int(argv[0]) if argv else SERVER_PORT
    status_port = int(argv[1]) if len(argv) > 1 else STATUS_PORT
    # Nada sobe antes da primeira volta: um segundo vigia para aqui, sem criar um segundo server.py
    vigia = Vigia(Supervisor(ROOT, port), KeepAwake(), NamePublisher(port), status_port=status_port)
    try:
        httpd = bind_status(vigia, status_port)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        print(f"O vigia já está rodando (porta {status_port} ocupada)", flush=True)
        return 1
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *args: vigia.done.set())
    print(f"Vigia rodando em http://localhost:{status_port}", flush=True)
    vigia.run(httpd)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
