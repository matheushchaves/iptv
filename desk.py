"""Área de trabalho do Sofá: onde você está, o tempo, a bolsa (B3), câmbio, o próximo foguete e as manchetes do Hacker News.

Tudo de fontes gratuitas e sem chave, buscado aqui no servidor e guardado por um tempo (algumas limitam pedidos,
e a TV não precisa saber de nenhuma). Cada parte cai sozinha: sem resposta, fica a última que deu certo, e as
outras janelas aparecem do mesmo jeito. O lugar vem do IP da casa e fica guardado em disco por um dia."""
from __future__ import annotations

import getpass
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urlparse

PLACE_URL = "http://ip-api.com/json/?fields=status,city,region,lat,lon,timezone&lang=pt-BR"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast?"
MARKETS_URL = "https://economia.awesomeapi.com.br/json/last/USD-BRL,EUR-BRL,BTC-BRL,ETH-BRL"
# Cotação da própria B3 (a do site deles, com atraso), um papel por pedido. Testado em 29/10/2026: Yahoo responde
# 429, brapi pede chave; a B3 responde sem chave.
B3_URL = "https://cotacao.b3.com.br/mds/api/v1/instrumentQuotation/"
B3_SYMBOLS = {"IBOV": "Ibovespa", "PETR4": "Petrobras", "VALE3": "Vale", "ITUB4": "Itaú"}
LAUNCHES_URL = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=5&mode=list"
NEWS_URL = "https://hacker-news.firebaseio.com/v0/"

TTL = {"place": 24 * 3600, "weather": 15 * 60, "markets": 5 * 60, "b3": 5 * 60, "launch": 3600, "news": 30 * 60}  # segundos
RETRY = 120  # fonte que falhou: tenta de novo depois disso, não a cada pedido
WAIT = 10    # quanto a página espera por todas as fontes juntas
MARKET_NAMES = {"USD": "Dólar", "EUR": "Euro", "BTC": "Bitcoin", "ETH": "Ethereum"}
NEWS_COUNT = 5


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


def _news_item(raw: dict) -> dict:
    host = urlparse(raw.get("url") or "").hostname or "news.ycombinator.com"
    return {"title": raw["title"], "score": raw.get("score", 0), "site": host.removeprefix("www.")}


class Desk:
    """fetch_json(url) -> JSON decodificado (levanta OSError/ValueError quando a fonte falha)."""

    def __init__(self, fetch_json: Callable[[str], object], cache_file: Path, clock=time.time):
        self.fetch_json, self.cache_file, self.clock = fetch_json, Path(cache_file), clock
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
        def load():
            ids = self.fetch_json(NEWS_URL + "topstories.json")[:NEWS_COUNT]
            with ThreadPoolExecutor(max_workers=NEWS_COUNT) as pool:
                return [_news_item(item) for item in pool.map(lambda i: self.fetch_json(f"{NEWS_URL}item/{i}.json"), ids)]
        return self._get("news", load)

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
