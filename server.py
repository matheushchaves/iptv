#!/usr/bin/env python3
"""Servidor IPTV local: playlist M3U + EPG XMLTV + proxy HLS. Só stdlib."""
import json
import re
import socket
import sys
import threading
import time
import unicodedata
import uuid
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime, timezone, timedelta
from http.client import HTTPException
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote, urljoin

import catalog
import prefs
import vodmatch
import xtream

DEFAULT_PLAYLISTS = [
    {"id": "iptv-org-br", "name": "Canais abertos BR (iptv-org)",
     "url": "https://iptv-org.github.io/iptv/countries/br.m3u"},
]
EPG_SOURCES = [
    # epg.pw grava o horário de Xangai e rotula como UTC ("+0000"). Conferido em 27/10/2026: o Jornal
    # das Dez da Globo News (22h) aparecia às 06h. "real_tz" diz em que fuso ler esse "+0000".
    {"url": "https://epg.pw/xmltv/epg_BR.xml", "real_tz": timezone(timedelta(hours=8))},
]
QUALITY_WORDS = {"hd", "sd", "fhd", "uhd", "4k", "8k", "h264", "h265", "hevc"}
GENERIC_WORDS = {"tv", "canal", "channel", "brasil"}
# Aceita conexões da rede de casa para a TV abrir o player pelo IP do Mac.
HOST = "0.0.0.0"
CACHE_TTL = 60 * 60
EPG_WINDOW = timedelta(hours=8)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"
ROOT = Path(__file__).parent
PLAYLISTS_FILE = ROOT / "playlists.json"
UPLOADS_DIR = ROOT / "uploads"
PREFS = prefs.Store(ROOT / "prefs.json")  # favoritos e "continuar assistindo", iguais na TV e no Mac
CACHE_DIR = ROOT / "cache"  # notas e sinopses do painel Xtream (sem usuário e senha)
MAX_PREFS_BODY = 1024 * 1024  # um navegador antigo manda tudo o que tinha guardado de uma vez
MAX_NAME = 80
MAX_UPLOAD = 300 * 1024 * 1024

_epg_cache = {"at": 0, "data": None}
STATIC_DIR = ROOT / "static"
STATIC_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}

_catalog_cache = {}  # playlist id -> {"at", "source", "data": catalog.Catalog}
_catalog_lock = threading.Lock()
_epg_lock = threading.Lock()
_playlist_lock = threading.Lock()
_panels = {}  # playlist id -> xtream.Panel
_panel_lock = threading.Lock()


def fetch(url, timeout=20, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def where(url):
    """Servidor e último pedaço do caminho: dá para saber o canal sem gravar o usuário e a senha do painel."""
    parts = urlparse(url)
    return f"{parts.hostname}/…/{parts.path.rsplit('/', 1)[-1][:40]}"


def name_words(name):
    """'HBO+ FHD [Alt]' -> ['hbo', 'plus']: sem acento, qualidade e marcações; 'Brazil' vira 'brasil'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s.replace("+", " plus "))
    s = re.sub(r"\.br\s*$", " ", s)
    words = ["brasil" if w == "brazil" else w for w in re.findall(r"[a-z0-9]+", s)]
    return [w for w in words if w not in QUALITY_WORDS and not re.fullmatch(r"\d{3,4}p", w)]


def norm(name):
    """Chave exata do canal: 'Rede TV HD' -> 'redetv', diferente de 'Rede Brasil' -> 'redebrasil'."""
    return "".join(name_words(name))


def loose_key(name):
    """Chave sem palavras genéricas ('Canal Sony' ~ 'Sony'). Só vale quando aponta para um único canal."""
    return "".join(w for w in name_words(name) if w not in GENERIC_WORDS)


@dataclass(frozen=True)
class Guide:
    programmes: dict  # chave exata -> programas na janela
    known: frozenset  # chaves exatas de todos os canais do guia, com ou sem programação
    loose: dict       # chave frouxa -> chaves exatas que têm programação
    words: dict       # chave exata com programação -> palavras do nome

    def for_channel(self, name):
        key = norm(name)
        if self.programmes.get(key):
            return self.programmes[key]
        candidates = self.loose.get(loose_key(name), frozenset())
        if key in self.known:
            # O canal existe sem grade: só vale o mesmo nome com palavra genérica a mais ("Record" ~ "Record TV"),
            # nunca um parecido ("Rede TV" não é "Rede Brasil")
            mine = set(name_words(name))
            candidates = [c for c in candidates if mine <= self.words[c]]
        return self.programmes[next(iter(candidates))] if len(candidates) == 1 else []

    def merge(self, other):
        """A primeira fonte tem prioridade quando as duas têm o mesmo canal."""
        loose = {k: self.loose.get(k, frozenset()) | other.loose.get(k, frozenset()) for k in {*self.loose, *other.loose}}
        return Guide({**other.programmes, **self.programmes}, self.known | other.known, loose,
                     {**other.words, **self.words})


EMPTY_GUIDE = Guide({}, frozenset(), {}, {})


def parse_m3u(text):
    channels, info = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', line))
            # O nome vem depois da 1ª vírgula fora dos atributos e pode ter vírgulas ("Pokémon, Eu Escolho Você!")
            title = re.sub(r'[\w-]+="[^"]*"', "", line).partition(",")[2]
            info = {
                "name": title.strip() or attrs.get("tvg-name", ""),
                "logo": attrs.get("tvg-logo", ""),
                "group": (attrs.get("group-title") or "Outros").split(";")[0],
                "tvgId": attrs.get("tvg-id", ""),
            }
        elif line and not line.startswith("#") and info:
            channels.append({**info, "url": line, "id": len(channels)})
            info = None
    return channels


def parse_epg_time(value, real_tz=None):
    t = datetime.strptime(value, "%Y%m%d%H%M%S %z")
    # Só o rótulo "+0000" está errado: mantém o relógio e troca o fuso. Fuso explícito é respeitado.
    return t.replace(tzinfo=real_tz) if real_tz and t.utcoffset() == timedelta(0) else t


def parse_epg(raw, real_tz=None, now=None, source="EPG"):
    now = now or datetime.now(timezone.utc)
    limit = now + EPG_WINDOW
    progs, names, labels, first = {}, {}, {}, None
    seen = set()  # cópias regionais ("São Paulo/SP Record News" e "Record News") repetem a mesma grade
    for _, el in ET.iterparse(raw, events=("end",)):
        if el.tag == "channel":
            # epg.pw usa IDs numéricos e nomes como "São Paulo/SP Record News"
            label = re.sub(r"^.*?/[A-Z]{2}\s+", "", el.findtext("display-name") or "").strip() or el.get("id", "")
            names[el.get("id")] = norm(label)
            labels.setdefault(norm(label), label)
            el.clear()
            continue
        if el.tag != "programme":
            continue
        try:
            start = parse_epg_time(el.get("start"), real_tz)
            stop = parse_epg_time(el.get("stop"), real_tz)
        except (TypeError, ValueError):
            el.clear()
            continue
        first = min(first, start) if first else start
        cid = el.get("channel", "")
        key = names.get(cid) or norm(cid)
        title = el.findtext("title") or ""
        if stop > now and start < limit and (key, start, stop, title) not in seen:
            seen.add((key, start, stop, title))
            progs.setdefault(key, []).append({
                "title": title,
                "desc": (el.findtext("desc") or "")[:300],
                "start": int(start.timestamp() * 1000),
                "stop": int(stop.timestamp() * 1000),
            })
        el.clear()
    for lst in progs.values():
        lst.sort(key=lambda p: p["start"])
    # O arquivo diário começa à meia-noite no fuso real; se não começar, a fonte mudou e a correção erra
    if real_tz and first and first.astimezone(real_tz).time() != datetime.min.time():
        print(f"Aviso: {source} não começa à meia-noite em {real_tz}; o fuso da fonte pode ter mudado. "
              "Confira os horários do guia e o 'real_tz' em EPG_SOURCES.", flush=True)
    loose = {}
    for key in progs:  # só canais com programação concorrem na comparação frouxa
        if lk := loose_key(labels.get(key, key)):
            loose.setdefault(lk, set()).add(key)
    words = {key: frozenset(name_words(labels.get(key, key))) for key in progs}
    return Guide(progs, frozenset(names.values()) | frozenset(progs), {k: frozenset(v) for k, v in loose.items()}, words)


def load_playlists():
    if not PLAYLISTS_FILE.exists():
        return list(DEFAULT_PLAYLISTS)
    try:
        return json.loads(PLAYLISTS_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"playlists.json inválido, usando padrão: {exc}", flush=True)
        return list(DEFAULT_PLAYLISTS)


def save_playlists(playlists):
    tmp = PLAYLISTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(playlists, ensure_ascii=False, indent=2))
    tmp.replace(PLAYLISTS_FILE)


def add_playlist(name, url):
    name, url = (name or "").strip()[:MAX_NAME], (url or "").strip()
    if urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
        raise ValueError("URL precisa começar com http:// ou https://")
    with _playlist_lock:
        playlists = load_playlists()
        if any(p.get("url") == url for p in playlists):
            raise ValueError("Essa playlist já está salva")
        new = {"id": uuid.uuid4().hex[:10], "name": name or urlparse(url).netloc, "url": url}
        save_playlists([*playlists, new])
        return new


def add_playlist_file(name, filename, stream, length):
    """Grava o upload em blocos (listas podem ter dezenas de MB) e registra a playlist."""
    if length <= 0:
        raise ValueError("Arquivo vazio")
    if length > MAX_UPLOAD:
        raise ValueError(f"Arquivo maior que {MAX_UPLOAD // (1024 * 1024)} MB")
    pid = uuid.uuid4().hex[:10]
    UPLOADS_DIR.mkdir(exist_ok=True)
    dest = UPLOADS_DIR / f"{pid}.m3u"
    with dest.open("wb") as out:
        head = stream.read(min(length, 64 * 1024))
        if b"#EXTINF" not in head and b"#EXTM3U" not in head:
            out.close()
            dest.unlink()
            raise ValueError("O arquivo não parece ser uma playlist M3U")
        out.write(head)
        remaining = length - len(head)
        while remaining > 0:
            chunk = stream.read(min(remaining, 1024 * 1024))
            if not chunk:
                break
            out.write(chunk)
            remaining -= len(chunk)
    label = (name or "").strip()[:MAX_NAME] or Path(filename or "").stem[:MAX_NAME] or "Arquivo local"
    new = {"id": pid, "name": label, "file": dest.name}
    with _playlist_lock:
        save_playlists([*load_playlists(), new])
    return new


def public_playlist(playlist):
    """O que a página mostra: o link de uma lista Xtream tem usuário e senha, e a tela de listas aparece na TV da sala."""
    source = "Arquivo local" if playlist.get("file") else urlparse(playlist.get("url", "")).hostname or ""
    return {"id": playlist["id"], "name": playlist["name"], "source": source}


def remove_playlist(pid):
    with _playlist_lock:
        playlists = load_playlists()
        target = next((p for p in playlists if p["id"] == pid), None)
        if not target:
            raise KeyError("Playlist não encontrada")
        save_playlists([p for p in playlists if p["id"] != pid])
        _catalog_cache.pop(pid, None)
    if target.get("file"):
        (UPLOADS_DIR / Path(target["file"]).name).unlink(missing_ok=True)


def read_playlist_source(playlist):
    if playlist.get("file"):
        return (UPLOADS_DIR / Path(playlist["file"]).name).read_text("utf-8", "replace")
    return fetch(playlist["url"], timeout=60).read().decode("utf-8", "replace")


def load_epg():
    with _epg_lock:
        if _epg_cache["data"] is not None and time.time() - _epg_cache["at"] < CACHE_TTL:
            return _epg_cache["data"]
        print("Carregando EPG...", flush=True)
        epg = EMPTY_GUIDE
        for src in EPG_SOURCES:
            try:
                epg = epg.merge(parse_epg(fetch(src["url"], timeout=60), real_tz=src.get("real_tz"), source=src["url"]))
            except Exception as exc:  # EPG é opcional: segue sem guia
                print(f"Falha ao carregar EPG {src['url']}: {exc}", flush=True)
        _epg_cache.update(at=time.time(), data=epg)
        return epg


def panel_for(playlist):
    """O painel da lista Xtream (um por lista, para o limite de consultas valer para todos os pedidos)."""
    acct = xtream.account(playlist)
    if not acct:
        return None
    with _panel_lock:
        if playlist["id"] not in _panels:
            _panels[playlist["id"]] = xtream.Panel(acct, CACHE_DIR / f"xtream-{playlist['id']}.json",
                                                   lambda url: json.loads(fetch(url, timeout=60).read()))
        return _panels[playlist["id"]]


def with_vod_info(cat, panel):
    """Programas dos canais de filmes e séries que estão no catálogo ganham nota, sinopse e o link do filme."""
    info = panel.bulk()
    index = vodmatch.build_index(cat.movies, cat.shows, info.get("ratings", {}), info.get("series", {}))
    live = vodmatch.annotate(cat.live, index)
    linked = sum("vod" in p for ch in live for p in ch["epg"])
    print(f"{linked} programas do guia ligados ao catálogo", flush=True)
    return replace(cat, live=live)


def load_catalog(pid):
    playlist = next((p for p in load_playlists() if p["id"] == pid), None)
    if not playlist:
        raise KeyError("Playlist não encontrada")
    source = playlist.get("file") or playlist.get("url")
    # Um lock só: a página pede resumo e canais juntos, e a lista não pode ser baixada duas vezes
    with _catalog_lock:
        cached = _catalog_cache.get(pid)
        if cached and cached["source"] == source and time.time() - cached["at"] < CACHE_TTL:
            return cached["data"]
        print(f"Carregando playlist {playlist['name']}...", flush=True)
        epg = load_epg()
        cat = catalog.build_catalog(parse_m3u(read_playlist_source(playlist)),
                                    epg_for=epg.for_channel)
        panel = panel_for(playlist)
        if panel:
            cat = with_vod_info(cat, panel)
        matched = sum(bool(ch["epg"]) for ch in cat.live)
        print(f"{len(cat.live)} ao vivo ({matched} com guia), {len(cat.movies)} filmes, "
              f"{len(cat.shows)} séries", flush=True)
        _catalog_cache[pid] = {"at": time.time(), "source": source, "data": cat}
        return cat


def movie_info(pid, vod_id):
    """Sinopse de um filme do painel: 202 quando o painel ainda não pode ser consultado (a página pede de novo)."""
    if not vod_id.isdigit():
        raise ValueError("id precisa ser um número")
    playlist = next((p for p in load_playlists() if p["id"] == pid), None)
    panel = playlist and panel_for(playlist)
    if not panel:
        raise KeyError("Essa lista não tem catálogo no painel")
    info = panel.movie_info(vod_id)
    return (200, info) if info is not None else (202, {"pending": True})


def arg(query, name):
    return query.get(name, [""])[0]


def browse_section(query):
    cat = load_catalog(arg(query, "playlist"))
    entries = {"movie": cat.movies, "series": cat.shows}.get(arg(query, "kind"))
    if entries is None:
        raise ValueError("kind precisa ser movie ou series")
    try:
        offset, limit = int(arg(query, "offset") or 0), int(arg(query, "limit") or 60)
    except ValueError:
        raise ValueError("offset e limit precisam ser números") from None
    return catalog.browse(entries, arg(query, "group"), arg(query, "q"), offset, limit)


def proxied(url):
    return "/proxy?u=" + quote(url, safe="")


def rewrite_m3u8(text, base):
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(proxied(urljoin(base, s)))
        elif 'URI="' in s:
            out.append(re.sub(r'URI="([^"]+)"', lambda m: f'URI="{proxied(urljoin(base, m.group(1)))}"', s))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype, cors=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, data):
        self.send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def handle_errors(fn):
        def wrapper(self):
            try:
                fn(self)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except KeyError as exc:
                self.send_json(404, {"error": exc.args[0] if exc.args else "Não encontrado"})
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
            except Exception as exc:
                try:
                    self.send_json(502, {"error": f"Falha ao buscar: {exc}"})
                except Exception:
                    pass
        return wrapper

    @handle_errors
    def do_GET(self):
        path = urlparse(self.path)
        query = parse_qs(path.query)
        if path.path in ("/", "/index.html"):
            self.send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path.path == "/api/playlists":
            self.send_json(200, [public_playlist(p) for p in load_playlists()])
        elif path.path == "/api/catalog":
            self.send_json(200, catalog.summary(load_catalog(arg(query, "playlist"))))
        elif path.path == "/api/live":
            self.send_json(200, load_catalog(arg(query, "playlist")).live)
        elif path.path == "/api/browse":
            self.send_json(200, browse_section(query))
        elif path.path == "/api/prefs":
            self.send_json(200, PREFS.read())
        elif path.path == "/api/vodinfo":
            self.send_json(*movie_info(arg(query, "playlist"), arg(query, "id")))
        elif path.path == "/api/show":
            self.send_json(200, catalog.show_detail(load_catalog(arg(query, "playlist")), arg(query, "id")))
        elif path.path.startswith("/static/"):
            self.static(path.path.removeprefix("/static/"))
        elif path.path == "/proxy":
            self.proxy(query.get("u", [""])[0])
        else:
            self.send(404, b"not found", "text/plain")

    def static(self, rel):
        target = (STATIC_DIR / rel).resolve()
        ctype = STATIC_TYPES.get(target.suffix)
        if not ctype or STATIC_DIR.resolve() not in target.parents or not target.is_file():
            return self.send(404, b"not found", "text/plain")
        self.send(200, target.read_bytes(), ctype)

    def read_json(self, limit=10_000):
        # Exigir JSON força preflight CORS, que não respondemos: bloqueia POST de outros sites
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise ValueError("Content-Type precisa ser application/json")
        length = min(int(self.headers.get("Content-Length") or 0), limit)
        return json.loads(self.rfile.read(length) or b"{}")

    @handle_errors
    def do_POST(self):
        path = urlparse(self.path)
        if path.path == "/api/playlists":
            body = self.read_json()
            return self.send_json(201, public_playlist(add_playlist(body.get("name"), body.get("url"))))
        if path.path == "/api/playlists/upload":
            # octet-stream não é "simple request": outro site não consegue enviar sem preflight
            if self.headers.get("Content-Type", "") != "application/octet-stream":
                raise ValueError("Content-Type precisa ser application/octet-stream")
            query = parse_qs(path.query)
            created = add_playlist_file(
                query.get("name", [""])[0], query.get("filename", [""])[0],
                self.rfile, int(self.headers.get("Content-Length") or 0),
            )
            return self.send_json(201, public_playlist(created))
        if path.path == "/api/prefs":
            PREFS.apply(self.read_json(MAX_PREFS_BODY))
            return self.send_json(200, {"ok": True})
        if path.path == "/api/log":  # erros do player (na TV não há console para ver)
            log(f"player {self.client_address[0]}: {str(self.read_json().get('msg', ''))[:300]}")
            return self.send_json(200, {"ok": True})
        self.send(404, b"not found", "text/plain")

    @handle_errors
    def do_DELETE(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/playlists/"):
            return self.send(404, b"not found", "text/plain")
        remove_playlist(path.rsplit("/", 1)[-1])
        self.send_json(200, {"ok": True})

    def proxy(self, url):
        if urlparse(url).scheme not in ("http", "https"):
            return self.send(400, b"bad url", "text/plain")
        # Filmes/séries: o <video> pede pedaços do arquivo (Range) para avançar e voltar
        rng = self.headers.get("Range")
        # Falha do painel vira 502 para o player: 4xx o hls.js nem tenta de novo
        try:
            resp = fetch(url, headers={"Range": rng} if rng else None)
        except urllib.error.HTTPError as exc:
            log(f"proxy: {where(url)} respondeu {exc.code}")
            return self.send(502, b"upstream error", "text/plain", cors=True)
        except OSError as exc:
            log(f"proxy: {where(url)} não respondeu ({exc})")
            return self.send(502, b"upstream unreachable", "text/plain", cors=True)
        with resp:
            ctype = resp.headers.get("Content-Type", "application/octet-stream")
            final = resp.geturl()
            if "mpegurl" in ctype.lower() or urlparse(final).path.endswith(".m3u8"):
                body = rewrite_m3u8(resp.read().decode("utf-8", "replace"), final).encode()
                return self.send(200, body, "application/vnd.apple.mpegurl", cors=True)
            # Sem tamanho anunciado, um corte no meio pareceria o fim normal e o player tocaria o pedaço pela
            # metade (o áudio fica robotizado até recarregar). Em chunked, cair sem o pedaço final é erro de rede.
            chunked = not resp.headers.get("Content-Length") and self.request_version == "HTTP/1.1"
            if chunked:
                self.protocol_version = "HTTP/1.1"
            self.send_response(resp.status)
            self.send_header("Content-Type", ctype)
            self.send_header("Access-Control-Allow-Origin", "*")
            for name in ("Content-Length", "Content-Range"):
                if resp.headers.get(name):
                    self.send_header(name, resp.headers[name])
            # O painel anuncia "0-<tamanho>" em vez de "bytes", que é o que o navegador entende
            if resp.status == 206 or resp.headers.get("Accept-Ranges", "none") != "none":
                self.send_header("Accept-Ranges", "bytes")
            if chunked:
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
            self.end_headers()
            self.relay(resp, url, chunked)

    def relay(self, resp, url, chunked):
        while True:
            try:
                chunk = resp.read(64 * 1024)
            except (OSError, HTTPException) as exc:
                return log(f"proxy: {where(url)} parou no meio ({exc!r})")
            if not chunk:
                if chunked:
                    self.wfile.write(b"0\r\n\r\n")
                return
            # cano quebrado aqui é o player desistindo (troca de canal): normal
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk) if chunked else chunk)


def lan_ip():
    """IP do Mac na rede local. O connect UDP só escolhe a interface; nada é enviado."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    threading.Thread(target=load_epg, daemon=True).start()
    print(f"IPTV rodando em http://localhost:{PORT} e, na rede, http://{lan_ip()}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
