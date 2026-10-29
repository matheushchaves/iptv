"""Programação mais rica: um programa do guia que é um filme ou uma série do catálogo do painel ganha nota, ano,
gênero e sinopse, e o filme pode ser visto do começo. Só nos canais de filmes e séries: em outro canal o mesmo
título costuma ser outra coisa ("Mama" numa novela coreana não é o filme de terror)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from catalog import fold, split_title

FILM_CHANNEL = re.compile(
    r"filme|s[ée]rie|cine|telecine|hbo|megapix|warner|universal|\btnt\b|space|\baxn\b|sony|\bamc\b|"
    r"paramount|\bstar\b|\bfx\b|\btcm\b|canal brasil|\bmax\b|disney|prime|film", re.I)
EPISODE_PART = re.compile(r"\s*[-–:;]\s+")  # "Série - Episódio 4", "Curta na Tela: Dona Irene"


def stream_id(url: str) -> str:
    """'http://painel/movie/u/p/101.mp4' -> '101' (o id do filme no painel)."""
    return url.rsplit("/", 1)[-1].split(".")[0]


@dataclass(frozen=True)
class Index:
    movies: dict[str, list[dict]]  # título sem acento -> filmes do catálogo com esse título
    shows: dict[str, dict]         # nome sem acento -> série do catálogo
    ratings: dict[str, float]      # id do filme no painel -> nota
    series: dict[str, dict]        # nome sem acento -> nota, sinopse, gênero e ano da série no painel


def build_index(movies: list[dict], shows: list[dict], ratings: dict, series: dict) -> Index:
    by_title: dict[str, list[dict]] = {}
    for m in movies:
        by_title.setdefault(fold(m["title"]), []).append(m)
    return Index(by_title, {fold(s["name"]): s for s in shows}, ratings, series)


def _movie(index: Index, title: str) -> dict | None:
    clean, year, _ = split_title(title)
    found = [m for m in index.movies.get(fold(clean), []) if not year or m["year"] in (None, year)]
    if not found or len({m["year"] for m in found if m["year"]}) > 1:
        return None  # nenhum, ou dois filmes diferentes com o mesmo nome e o guia sem o ano
    best = sorted(found, key=lambda m: m["subtitled"])[0]  # dublado primeiro
    rating = next((index.ratings[stream_id(m["url"])] for m in [best, *found] if stream_id(m["url"]) in index.ratings), None)
    return {"kind": "movie", "rating": rating, "year": best["year"], "url": best["url"], "title": best["title"],
            "subtitled": best["subtitled"], "group": best["group"], "logo": best["logo"], "id": stream_id(best["url"])}


def _series(index: Index, title: str) -> dict | None:
    show = index.shows.get(fold(title)) or index.shows.get(fold(EPISODE_PART.split(title, 1)[0]))
    if not show:
        return None
    info = index.series.get(fold(show["name"]), {})
    return {"kind": "series", "showId": show["id"], "name": show["name"], "logo": show["logo"],
            "rating": info.get("rating"), "year": info.get("year"), "genre": info.get("genre"), "plot": info.get("plot")}


def match(index: Index, title: str) -> dict | None:
    return _movie(index, title) or _series(index, title)


def is_film_channel(channel: dict) -> bool:
    return bool(FILM_CHANNEL.search(" ".join([channel["name"], *channel["groups"]])))


def annotate(live: list[dict], index: Index) -> list[dict]:
    """Canais de filmes e séries: cada programa que está no catálogo ganha 'vod'. Devolve canais novos."""
    out = []
    for ch in live:
        if not ch["epg"] or not is_film_channel(ch):
            out.append(ch)
            continue
        epg = []
        for p in ch["epg"]:
            vod = match(index, p["title"])
            epg.append({**p, "vod": vod} if vod else p)
        out.append({**ch, "epg": epg})
    return out
