"""O que o vigia mostra: a cor e a mensagem de cada situação, e quais linhas do log podem sair na página.

A página não tem senha e abre em qualquer aparelho da casa, por isso as linhas passam por uma lista do que pode
aparecer, e nenhuma URL sai daqui: um link de lista Xtream carrega usuário e senha.
"""
import re
from dataclasses import dataclass
from typing import Optional, Sequence

GREEN, YELLOW, RED, GRAY = "green", "yellow", "red", "gray"
MAX_LINE = 160
MAX_REASON = 200
PUBLIC_PREFIXES = ("lista ", "painel ", "recusado:", "player ")
PLAYER_WORDS = ("erro", "Error", "caiu", "travou")  # o resto do player é rotina ("andou 30 s em 30 s")
CLOCK = re.compile(r"^\d\d:\d\d:\d\d ")
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I)
CREDENTIAL = re.compile(r"[?&]?\b(?:username|password)=[^\s&]*", re.I)


@dataclass(frozen=True)
class Facts:
    stopped: bool = False  # o dono desligou
    own_child: bool = False  # o server.py vivo é filho do vigia
    responding: bool = False  # a porta do Sofá respondeu
    crashed: bool = False  # caiu e ainda não voltou
    gave_up: bool = False  # esgotou as tentativas
    reason: str = ""
    on_battery: bool = False
    online: bool = True


@dataclass(frozen=True)
class Verdict:
    color: str
    title: str
    detail: str = ""


def decide(facts: Facts) -> Verdict:
    if facts.responding and not facts.own_child:
        return Verdict(YELLOW, "Sofá aberto pelo Terminal: Religar não funciona")
    if facts.stopped:
        return Verdict(GRAY, "Sofá desligado")
    if facts.gave_up:
        return Verdict(RED, "Sofá não consegue ligar", facts.reason)
    if not facts.responding:
        return Verdict(YELLOW, "Sofá caiu, religando" if facts.crashed else "Sofá ligando")
    if not facts.online:
        return Verdict(YELLOW, "Sem internet: os canais não vão tocar")
    if facts.on_battery:
        return Verdict(YELLOW, "Mac na bateria: vai dormir quando ficar parado")
    return Verdict(GREEN, "Sofá no ar")


def cut_urls(text: str) -> str:
    return CREDENTIAL.sub("", URL.sub("[link]", text))


def public_line(line: str) -> Optional[str]:
    """Linha do server.log como ela sai na página, ou None se ela não é para sair."""
    text = CLOCK.sub("", line.strip()).split(" | ", 1)[0]
    if not text.startswith(PUBLIC_PREFIXES):
        return None
    if text.startswith("player ") and not any(word in text for word in PLAYER_WORDS):
        return None
    return cut_urls(text)[:MAX_LINE]


def failure_reason(lines: Sequence[str], port: int) -> str:
    """O motivo de o Sofá não ligar, a partir das últimas linhas que ele escreveu."""
    if any("Address already in use" in line for line in lines):
        return f"Outro programa está usando a porta {port}"
    last = next((line for line in reversed(lines) if line.strip()), "")
    return cut_urls(last.strip())[:MAX_REASON] or "O Sofá fechou sem dizer o motivo"
