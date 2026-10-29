"""Área de trabalho do Sofá: onde você está, o tempo, a bolsa (B3), câmbio, o próximo foguete e manchetes de tecnologia
(em português: Tecnoblog, Canaltech, TecMundo e Meio Bit, pelo RSS de cada um).

Tudo de fontes gratuitas e sem chave, buscado aqui no servidor e guardado por um tempo (algumas limitam pedidos,
e a TV não precisa saber de nenhuma). Cada parte cai sozinha: sem resposta, fica a última que deu certo, e as
outras janelas aparecem do mesmo jeito. O lugar vem do IP da casa e fica guardado em disco por um dia."""
from __future__ import annotations

import getpass
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

PLACE_URL = "http://ip-api.com/json/?fields=status,city,region,lat,lon,timezone&lang=pt-BR"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast?"
MARKETS_URL = "https://economia.awesomeapi.com.br/json/last/USD-BRL,EUR-BRL,BTC-BRL,ETH-BRL"
# Cotação da própria B3 (a do site deles, com atraso), um papel por pedido. Testado em 29/10/2026: Yahoo responde
# 429, brapi pede chave; a B3 responde sem chave.
B3_URL = "https://cotacao.b3.com.br/mds/api/v1/instrumentQuotation/"
B3_SYMBOLS = {"IBOV": "Ibovespa", "PETR4": "Petrobras", "VALE3": "Vale", "ITUB4": "Itaú"}
LAUNCHES_URL = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=5&mode=list"
# Testados em 29/10/2026 (Jovem Nerd e Omelete não têm mais RSS; o do g1 chegava cortado; o do Olhar Digital traz anúncio)
NEWS_FEEDS = {
    "Tecnoblog": "https://tecnoblog.net/feed/", "Canaltech": "https://canaltech.com.br/rss/",
    "TecMundo": "https://rss.tecmundo.com.br/feed", "Meio Bit": "https://meiobit.com/feed/",
}

TTL = {"place": 24 * 3600, "weather": 15 * 60, "markets": 5 * 60, "b3": 5 * 60, "launch": 3600, "headlines": 20 * 60}  # segundos
RETRY = 120  # fonte que falhou: tenta de novo depois disso, não a cada pedido
WAIT = 10    # quanto a página espera por todas as fontes juntas
MARKET_NAMES = {"USD": "Dólar", "EUR": "Euro", "BTC": "Bitcoin", "ETH": "Ethereum"}
NEWS_COUNT = 8
NEWS_PER_SOURCE = 2  # a faixa não pode virar um site só
ADS = re.compile(r"\b(cupo(m|ns)|desconto|promo(ção|ções)|oferta)", re.I)  # os sites misturam propaganda no feed


def owner_name() -> str:
    """O nome da conta do Mac que roda o servidor ('matheus' -> 'Matheus'), para o bem-vindo."""
    try:
        return getpass.getuser().capitalize()
    except Exception:  # sem usuário no ambiente: bem-vindo sem nome
        return ""


def _place(raw: dict) -> dict:
    if raw.get("status") != "success":
        raise ValueError("ip-api não achou o lugar")
    return {"city": raw["city"], "region": raw["region"], "lat": raw["lat"], "lon": raw["lon"], "tz": raw["timezone"]}


def _weather(raw: dict) -> dict:
    cur, hourly, daily = raw["current"], raw["hourly"], raw["daily"]
    hour_now = cur["time"][:13] + ":00"
    i = hourly["time"].index(hour_now)
    hours = [{"hour": hourly["time"][j][11:16], "temp": round(hourly["temperature_2m"][j]), "code": hourly["weather_code"][j],
              "rain": hourly["precipitation_probability"][j], "day": bool(hourly["is_day"][j])}
             for j in range(i + 3, min(i + 13, len(hourly["time"])), 3)]
    days = [{"date": daily["time"][j], "max": round(daily["temperature_2m_max"][j]), "min": round(daily["temperature_2m_min"][j]),
             "code": daily["weather_code"][j], "rain": daily["precipitation_probability_max"][j]} for j in range(1, len(daily["time"]))]
    now = {"temp": round(cur["temperature_2m"]), "feels": round(cur["apparent_temperature"]), "code": cur["weather_code"],
           "humidity": cur["relative_humidity_2m"], "wind": round(cur["wind_speed_10m"]), "day": bool(cur["is_day"])}
    return {"now": now, "hours": hours, "days": days}


def _markets(raw: dict) -> list[dict]:
    quotes = {q["code"]: q for q in raw.values()}
    return [{"code": code, "name": name, "value": float(quotes[code]["bid"]), "change": float(quotes[code]["pctChange"])}
            for code, name in MARKET_NAMES.items() if code in quotes]


def _b3(symbol: str, raw: dict) -> dict:
    trade = raw["Trad"][0]["scty"]
    quote = trade["SctyQtn"]
    return {"symbol": symbol, "name": B3_SYMBOLS[symbol], "value": quote["curPrc"], "change": round(quote["prcFlcn"], 2),
            "at": raw["Msg"]["dtTm"][11:16]}


def _launch(raw: dict, now: float) -> dict | None:
    for item in raw["results"]:
        net = datetime.fromisoformat(item["net"].replace("Z", "+00:00")).timestamp()
        if net > now:
            rocket, _, mission = item["name"].partition(" | ")
            return {"rocket": rocket, "mission": mission or rocket, "net": int(net * 1000), "pad": item.get("pad") or "",
                    "location": item.get("location") or "", "status": (item.get("status") or {}).get("abbrev", "")}
    return None


def _feed(source: str, raw: bytes) -> list[dict]:
    """Manchetes de um RSS: título (sem quebras de linha) e quando saiu, em ms."""
    items = []
    for item in ET.fromstring(raw).iter("item"):
        title, when = " ".join((item.findtext("title") or "").split()), item.findtext("pubDate")
        try:
            at = int(parsedate_to_datetime(when).timestamp() * 1000)
        except (TypeError, ValueError):
            continue
        if title and not ADS.search(title):
            items.append({"title": title, "source": source, "at": at})
    return items


def _headlines(feeds: list[list[dict]]) -> list[dict]:
    """As mais recentes de todos os sites, no máximo NEWS_PER_SOURCE de cada um."""
    picked, per_source = [], Counter()
    for item in sorted((i for feed in feeds for i in feed), key=lambda i: -i["at"]):
        if per_source[item["source"]] < NEWS_PER_SOURCE:
            per_source[item["source"]] += 1
            picked.append(item)
    return picked[:NEWS_COUNT]


class Desk:
    """fetch_json(url) -> JSON decodificado; fetch_text(url) -> bytes (RSS). Levantam OSError/ValueError quando a fonte falha."""

    def __init__(self, fetch_json: Callable[[str], object], cache_file: Path, clock=time.time,
                 fetch_text: Callable[[str], bytes] | None = None):
        self.fetch_json, self.cache_file, self.clock, self.fetch_text = fetch_json, Path(cache_file), clock, fetch_text
        self.lock = threading.Lock()
        self.busy: dict[str, threading.Lock] = {k: threading.Lock() for k in TTL}
        self.failed_at: dict[str, float] = {}
        try:
            self.cache = json.loads(self.cache_file.read_text())
        except (OSError, ValueError):
            self.cache = {}

    def _save(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False))
        tmp.replace(self.cache_file)

    def _get(self, key: str, load: Callable[[], object]):
        """O valor guardado, ou um novo se venceu; se a fonte falhar, o último que deu certo (ou None)."""
        now = self.clock()
        with self.lock:
            kept = self.cache.get(key)
        fresh = kept and now - kept["at"] < TTL[key]
        if fresh or now - self.failed_at.get(key, -RETRY) < RETRY or not self.busy[key].acquire(blocking=False):
            return kept and kept["value"]
        try:
            value = load()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.failed_at[key] = now
            print(f"área de trabalho: {key} indisponível ({type(exc).__name__})", flush=True)
            return kept and kept["value"]
        finally:
            self.busy[key].release()
        with self.lock:
            self.cache = {**self.cache, key: {"at": now, "value": value}}
            self._save()
        return value

    def place(self):
        return self._get("place", lambda: _place(self.fetch_json(PLACE_URL)))

    def weather(self, place):
        if not place:
            return None
        query = urlencode({
            "latitude": place["lat"], "longitude": place["lon"], "timezone": "auto", "forecast_days": 4,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
            "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        })
        return self._get("weather", lambda: _weather(self.fetch_json(WEATHER_URL + query)))

    def markets(self):
        return self._get("markets", lambda: _markets(self.fetch_json(MARKETS_URL)))

    def b3(self):
        """Ibovespa e as ações mais negociadas, da B3 (no fim de semana e à noite, a última cotação do pregão)."""
        def load():
            with ThreadPoolExecutor(max_workers=len(B3_SYMBOLS)) as pool:
                return list(pool.map(lambda s: _b3(s, self.fetch_json(B3_URL + s)), B3_SYMBOLS))
        return self._get("b3", load)

    def launch(self):
        # A lista guardada vale uma hora; o próximo lançamento é escolhido de novo a cada pedido (um pode ter subido)
        raw = self._get("launch", lambda: self.fetch_json(LAUNCHES_URL))
        return _launch(raw, self.clock()) if raw else None

    def news(self):
        """Manchetes de tecnologia em português; um site fora do ar não derruba os outros."""
        def one(source):
            try:
                return _feed(source, self.fetch_text(NEWS_FEEDS[source]))
            except (OSError, ValueError, ET.ParseError):
                return []

        def load():
            with ThreadPoolExecutor(max_workers=len(NEWS_FEEDS)) as pool:
                items = _headlines(list(pool.map(one, NEWS_FEEDS)))
            if not items:
                raise ValueError("nenhum site de notícias respondeu")
            return items
        return self._get("headlines", load)

    def snapshot(self) -> dict:
        """Tudo junto, buscando as fontes ao mesmo tempo; a que demorar mais que WAIT aparece da próxima vez.
        O lugar vem antes (o tempo depende dele; é rápido e fica guardado um dia)."""
        place = self.place()
        parts = {"weather": lambda: self.weather(place), "markets": self.markets, "b3": self.b3, "launch": self.launch,
                 "news": self.news}
        pool = ThreadPoolExecutor(max_workers=len(parts))
        futures = {key: pool.submit(fn) for key, fn in parts.items()}
        wait(futures.values(), timeout=WAIT)
        pool.shutdown(wait=False)  # a que atrasou termina sozinha e fica guardada para o próximo pedido
        return {"place": place, **{key: f.result() if f.done() else None for key, f in futures.items()}}
