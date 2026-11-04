"""Tudo o que o vigia pede ao sistema: Mac acordado, nome na rede, bateria, endereço e início no login.

Fora do Mac estas peças não fazem nada e não dão erro, então `python vigia.py` já roda à mão no Windows e no Linux.
Para gerar o que o instalador registra: python3 vigia_system.py vigia-plist <python> | app-plist <binário>
"""
import os
import plistlib
import socket
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

IS_MAC = sys.platform == "darwin"
NAME = "sofa.local"
VIGIA_LABEL = "local.sofa.vigia"
APP_LABEL = "local.sofa.barra"
ROOT = Path(__file__).parent.resolve()
INTERNET_HOSTS = (("1.1.1.1", 443), ("8.8.8.8", 443))
INTERNET_TIMEOUT_S = 2
END_GRACE_S = 2


def lan_ip() -> Optional[str]:
    """IP na rede local, ou None sem rede. O connect UDP só escolhe a interface; nada é enviado."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 80))
            return s.getsockname()[0]
        except OSError:
            return None


def on_battery(run: Callable = subprocess.run) -> bool:
    if not IS_MAC:
        return False
    try:
        return "Battery Power" in run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False


def internet_ok(connect: Callable = socket.create_connection) -> bool:
    """Só abre uma conexão com DNS públicos: nunca toca no painel da lista, que bloqueia por excesso de pedidos."""
    for address in INTERNET_HOSTS:
        try:
            with connect(address, timeout=INTERNET_TIMEOUT_S):
                return True
        except OSError:
            continue
    return False


def _end(proc) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=END_GRACE_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


class _Helper:
    """Um programa do sistema que o vigia mantém aberto. Se ele não existir, desiste em vez de tentar a cada volta."""

    def __init__(self, popen: Callable, enabled: bool):
        self.popen, self.enabled = popen, enabled
        self.proc = None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def open(self, args: Sequence[str]) -> None:
        try:
            self.proc = self.popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            print(f"{args[0]} não abriu ({exc}); seguindo sem ele", flush=True)
            self.enabled = False

    def close(self) -> None:
        _end(self.proc)
        self.proc = None


class KeepAwake(_Helper):
    """Na tomada, o Mac não dorme enquanto o caffeinate viver. A tela apaga normalmente, e na bateria ele não vale."""

    def __init__(self, popen: Callable = subprocess.Popen, enabled: bool = IS_MAC):
        super().__init__(popen, enabled)

    def set(self, on: bool) -> None:
        if not on:
            self.close()
        elif self.enabled and not self.alive():
            self.open(["caffeinate", "-s", "-w", str(os.getpid())])  # some junto com o vigia


class NamePublisher(_Helper):
    """Publica sofa.local apontando para o IP atual. A TV LG não entende nomes .local: o nome é para o tablet."""

    def __init__(self, port: int, popen: Callable = subprocess.Popen, enabled: bool = IS_MAC):
        super().__init__(popen, enabled)
        self.port = port
        self.ip = None

    @property
    def name(self) -> Optional[str]:
        return NAME if self.alive() else None

    def update(self, ip: Optional[str]) -> None:
        if not self.enabled or (ip == self.ip and self.alive()):
            return
        self.stop()
        if ip:
            self.ip = ip
            self.open(["dns-sd", "-P", "Sofa", "_http._tcp", "local", str(self.port), NAME, ip])

    def stop(self) -> None:
        self.close()
        self.ip = None


def launch_agent_plist(label: str, args: Sequence[str], root: Path, keep_alive: bool,
                       log_path: Optional[Path] = None) -> bytes:
    plist = {
        "Label": label,
        "ProgramArguments": list(args),
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": keep_alive,
        "ProcessType": "Interactive",
    }
    if log_path:
        plist["StandardOutPath"] = plist["StandardErrorPath"] = str(log_path)
    return plistlib.dumps(plist)


def main(argv: Sequence[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("vigia-plist", "app-plist"):
        print("uso: vigia_system.py vigia-plist <python> | app-plist <binário>", file=sys.stderr)
        return 2
    kind, target = argv
    if kind == "vigia-plist":
        # O caminho vem de fora: sys.executable aponta para a versão exata do Python e sumiria num brew upgrade
        data = launch_agent_plist(VIGIA_LABEL, [target, "vigia.py"], ROOT, True, ROOT / "vigia.log")
    else:
        data = launch_agent_plist(APP_LABEL, [target, "--barra"], Path.home(), False)
    sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
