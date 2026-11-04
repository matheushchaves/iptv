"""O vigia: mantém o server.py no ar e mostra numa página se está tudo bem.

Roda separado do Sofá e nunca importa o server.py, para um erro lá não derrubar quem precisa avisar do erro.
Rodar: python3 vigia.py [porta do Sofá] [porta da página]
"""
import http.client
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Optional, Sequence

from vigia_state import Facts, failure_reason, public_line

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
