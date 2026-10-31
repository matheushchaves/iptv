"""Ao vivo para TV antiga. O navegador de uma Samsung de 2013 (Chrome 25) não toca HLS e não tem onde o hls.js
rodar, mas toca um .ts contínuo: aqui os pedaços do HLS saem um atrás do outro, numa resposta só. Conferido numa
Samsung dessas em 31/10/2026: a TV Brasil assim abriu em 720p (o primeiro quadro leva uns segundos)."""
from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Callable, Iterator
from urllib.parse import urljoin, urlparse

START_SEGMENTS = 3  # começa uns 15 s atrás do ao vivo: a TV junta um bocado antes de mostrar o primeiro quadro
MAX_HEIGHT = 720  # a TV desenha em 1280x720; mais que isso só pesa no Wi-Fi
NO_DECODE = ("hvc1", "hev1", "av01", "vp09")  # H.265, AV1 e VP9: o chip de 2013 não decodifica
MISSES = 10  # consultas seguidas sem pedaço novo (ou sem resposta) antes de desistir do canal
MIN_WAIT, MAX_WAIT = 1.0, 4.0
PATH_PREFIX = "/aovivo/"


class Unsupported(Exception):
    """Canal que não dá para juntar num .ts (criptografado ou em fMP4)."""


@dataclass(frozen=True)
class Media:
    segments: list[tuple[int, str]]  # (número na sequência, url)
    ended: bool
    target: float


def channel_path(url: str) -> str:
    """Endereço do canal no Sofá. Termina em .ts porque a TV escolhe como tocar pelo fim do endereço: com
    "?u=...index.m3u8" no fim ela nem tentou (teste de 31/10/2026). O link vai em base64 para não ter "/" nem "?"."""
    return PATH_PREFIX + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=") + ".ts"


def url_from_path(path: str) -> str:
    code = path[len(PATH_PREFIX):-len(".ts")] if path.startswith(PATH_PREFIX) and path.endswith(".ts") else ""
    try:
        url = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError):
        url = ""
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("Canal inválido")
    return url


def xtream_ts(url: str) -> str | None:
    """O painel Xtream já entrega o canal como .ts contínuo (/live/usuário/senha/123.ts): nada a juntar."""
    parts = urlparse(url)
    if not re.search(r"/live/[^/]+/[^/]+/\d+\.m3u8$", parts.path):
        return None
    return parts._replace(path=parts.path[:-len(".m3u8")] + ".ts").geturl()


def _attr(attrs: str, pattern: str) -> str:
    found = re.search(pattern, attrs)
    return found.group(1) if found else ""


def pick_variant(text: str, base: str) -> str | None:
    """Da lista mestra, a versão que a TV dá conta: H.264 até 720p, a de maior taxa. None se não for lista mestra."""
    lines = text.splitlines()
    variants = []
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        uri = next((l.strip() for l in lines[i + 1:] if l.strip() and not l.startswith("#")), None)
        if uri:
            attrs = line.split(":", 1)[1]
            variants.append((urljoin(base, uri), int(_attr(attrs, r"(?<![-\w])BANDWIDTH=(\d+)") or 0),
                             int(_attr(attrs, r"RESOLUTION=\d+x(\d+)") or 0), _attr(attrs, r'CODECS="([^"]*)"').lower()))
    if not variants:
        return None
    playable = [v for v in variants if not any(c in v[3] for c in NO_DECODE)] or variants
    fits = [v for v in playable if v[2] <= MAX_HEIGHT] or [min(playable, key=lambda v: (v[2], v[1]))]
    return max(fits, key=lambda v: v[1])[0]


def parse_media(text: str, base: str) -> Media:
    first, segments, ended, target = 0, [], False, 6.0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            first = int(s.split(":", 1)[1])
        elif s.startswith("#EXT-X-TARGETDURATION:"):
            target = float(s.split(":", 1)[1])
        elif s.startswith("#EXT-X-KEY:") and "METHOD=NONE" not in s:
            raise Unsupported("canal criptografado")
        elif s.startswith("#EXT-X-MAP:"):
            raise Unsupported("canal em fMP4")
        elif s == "#EXT-X-ENDLIST":
            ended = True
        elif s and not s.startswith("#"):
            segments.append((first + len(segments), urljoin(base, s)))
    return Media(segments, ended, target)


def segments(url: str, get_text: Callable[[str], tuple[str, str]], sleep: Callable[[float], None],
             note: Callable[[str], None] = lambda reason: None) -> Iterator[str]:
    """Os pedaços do canal, em ordem, enquanto ele estiver no ar. get_text(url) devolve (texto, url depois dos
    redirecionamentos). O primeiro erro sobe (o canal não abriu); depois disso, falhas só contam como falta, e
    note(motivo) diz por que o canal foi largado."""
    text, final = get_text(url)
    variant = pick_variant(text, final)
    if variant:
        url = variant
        text, final = get_text(url)
    last, misses = None, 0
    while True:
        media = parse_media(text, final)
        if last is None:
            if not media.segments:
                raise Unsupported("lista sem pedaços")
            new = media.segments[-START_SEGMENTS:]
        else:
            new = [s for s in media.segments if s[0] > last]
            if not new and media.segments and media.segments[-1][0] < last:  # a sequência recomeçou do zero
                new = media.segments[-1:]
        for last, segment in new:
            yield segment
        if media.ended:
            return note("o canal terminou")
        misses = 0 if new else misses + 1
        failure = None
        while True:
            if misses >= MISSES:
                return note(f"a lista não respondeu ({failure})" if failure else "a lista parou de mudar")
            sleep(max(MIN_WAIT, min(media.target / 2, MAX_WAIT)))
            try:
                text, final = get_text(url)
                break
            except OSError as exc:
                failure = exc
                misses += 1
