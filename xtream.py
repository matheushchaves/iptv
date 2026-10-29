"""Painel Xtream (lista "get.php?username=...&password=..."): além da lista, o player_api.php tem a nota de todos
os filmes e nota, sinopse e gênero das séries, numa consulta cada; a sinopse de um filme vem um por vez.

O painel recusa rajadas (403 depois de umas 6 consultas em um minuto, 29/10/2026). Por isso as listas completas
vêm uma vez por dia e ficam em disco, cada sinopse é buscada uma vez só, e nunca passa de CALLS_PER_MINUTE.
O arquivo guardado não tem usuário nem senha."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse

from catalog import fold

BULK_TTL = 24 * 60 * 60
ACCOUNT_TTL = 10 * 60
CALLS_PER_MINUTE = 4
BLOCKED_PAUSE = 10 * 60
MAX_PLOT = 400
MAX_CAST = 160


@dataclass(frozen=True)
class Account:
    base: str
    username: str
    password: str


def account(playlist: dict) -> Account | None:
    url = urlparse(playlist.get("url", ""))
    query = parse_qs(url.query)
    if not url.path.endswith("get.php") or not query.get("username") or not query.get("password"):
        return None
    return Account(f"{url.scheme}://{url.netloc}", query["username"][0], query["password"][0])


def rating(value) -> float | None:
    try:
        r = round(float(value), 1)
    except (TypeError, ValueError):
        return None
    return r if r > 0 else None


def _year(date) -> int | None:
    head = str(date or "")[:4]
    return int(head) if head.isdigit() else None


def _series_info(s: dict) -> dict:
    return {"rating": rating(s.get("rating")), "plot": (s.get("plot") or "")[:MAX_PLOT], "genre": s.get("genre") or "",
            "year": _year(s.get("releaseDate") or s.get("release_date")), "cast": (s.get("cast") or "")[:MAX_CAST]}


def _movie_info(raw) -> dict:
    i = raw.get("info") if isinstance(raw, dict) else None
    i = i if isinstance(i, dict) else {}
    return {"plot": (i.get("plot") or i.get("description") or "")[:MAX_PLOT], "genre": i.get("genre") or "",
            "duration": i.get("duration") or "", "cast": (i.get("cast") or "")[:MAX_CAST], "director": i.get("director") or ""}


class Panel:
    """fetch_json(url) -> JSON decodificado; levanta erro HTTP como o urllib."""

    def __init__(self, acct: Account, cache_file: Path, fetch_json: Callable[[str], object], clock=time.time):
        self.acct, self.cache_file, self.fetch_json, self.clock = acct, Path(cache_file), fetch_json, clock
        self.lock = threading.Lock()
        self.calls: deque[float] = deque()
        self.blocked_until = 0.0
        self.account = (0.0, None)  # (quando, situação da conta): só na memória, muda a toda hora
        self.data = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(self.cache_file.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.data = data
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        tmp.replace(self.cache_file)

    def _call(self, **params):
        """Uma consulta ao painel. None quando não é hora (limite por minuto ou pausa depois de uma recusa)."""
        now = self.clock()
        while self.calls and now - self.calls[0] >= 60:
            self.calls.popleft()
        if now < self.blocked_until or len(self.calls) >= CALLS_PER_MINUTE:
            return None
        self.calls.append(now)
        query = urlencode({"username": self.acct.username, "password": self.acct.password, **params})
        try:
            return self.fetch_json(f"{self.acct.base}/player_api.php?{query}")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 429):
                self.blocked_until = now + BLOCKED_PAUSE
            print(f"painel {urlparse(self.acct.base).hostname}: {params.get('action')} respondeu {exc.code}", flush=True)
        except (OSError, ValueError) as exc:
            print(f"painel {urlparse(self.acct.base).hostname}: {params.get('action')} falhou ({type(exc).__name__})", flush=True)
        return None

    def bulk(self) -> dict:
        """Notas dos filmes ({id: nota}) e dados das séries ({nome sem acento: ...}); da última vez que deu certo."""
        with self.lock:
            if self.clock() - self.data.get("bulkAt", 0) < BULK_TTL:
                return self.data
            movies = self._call(action="get_vod_streams")
            series = self._call(action="get_series") if isinstance(movies, list) else None
            if not isinstance(series, list):
                return self.data
            ratings = {str(m["stream_id"]): r for m in movies if (r := rating(m.get("rating"))) and m.get("stream_id")}
            shows = {fold(s["name"]): _series_info(s) for s in series if s.get("name")}
            self._save({**self.data, "bulkAt": self.clock(), "ratings": ratings, "series": shows})
            return self.data

    def account_info(self) -> dict | None:
        """Situação da conta (ativa, vencimento, conexões em uso), sem usuário nem senha; guardada por uns minutos."""
        with self.lock:
            at, info = self.account
            if info and self.clock() - at < ACCOUNT_TTL:
                return info
            raw = self._call()
            user = raw.get("user_info") if isinstance(raw, dict) else None
            if not isinstance(user, dict):
                return info
            num = lambda v: int(v) if str(v or "").isdigit() else None
            info = {"status": user.get("status") or "", "expires": num(user.get("exp_date")),
                    "active": num(user.get("active_cons")), "max": num(user.get("max_connections"))}
            self.account = (self.clock(), info)
            return info

    def movie_info(self, vod_id: str) -> dict | None:
        """Sinopse, gênero, duração e elenco de um filme; None se o painel ainda não pode ser consultado."""
        with self.lock:
            known = self.data.get("movies", {})
            if vod_id in known:
                return known[vod_id]
            raw = self._call(action="get_vod_info", vod_id=vod_id)
            if raw is None:
                return None
            info = _movie_info(raw)
            self._save({**self.data, "movies": {**known, vod_id: info}})
            return info
